"""Load PL 94-171 population + TIGER block geometry, join, persist as GeoPackage.

PL 94-171 2020 format
---------------------
Pipe-delimited text files inside a per-state zip:
  {state}geo2020.pl       ~95 fields, geographic header
  {state}000012020.pl     P1 (race) segment, P1_001N at index 5 = total population
  {state}000022020.pl     P2 segment (unused here)
  {state}000032020.pl     H1 segment (unused here)

Join key: LOGRECNO (geo column index 7, segment column index 4).
Block summary level: SUMLEV == '750'.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd

from . import config

# 0-indexed column positions in the 2020 PL 94-171 geo header file.
# Source: 2020 Census P.L. 94-171 Redistricting Data Summary File technical doc.
GEO_COL = {
    "SUMLEV": 2,
    "LOGRECNO": 7,
    "GEOID": 9,        # GEOCODE: 15-digit block code (e.g. "190010201001000")
    "STATE": 12,
    "COUNTY": 14,
    "TRACT": 32,
    "BLOCK": 34,
    "POP100": 87,
    "INTPTLAT": 91,
    "INTPTLON": 92,
}

# In segment 1 the field order is:
# FILEID(0) STUSAB(1) CHARITER(2) CIFSN(3) LOGRECNO(4) P0010001(5) ...
SEG1_LOGRECNO = 4
SEG1_P1_001N = 5


def _read_pl_text(zip_path: Path, inner_name_glob: str) -> list[list[str]]:
    """Read a pipe-delimited PL 94-171 text file from inside a zip."""
    with zipfile.ZipFile(zip_path) as zf:
        match = [n for n in zf.namelist() if n.lower().endswith(inner_name_glob.lower())]
        if not match:
            raise FileNotFoundError(
                f"No file matching *{inner_name_glob} inside {zip_path}. "
                f"Members: {zf.namelist()}"
            )
        with zf.open(match[0]) as f:
            text = io.TextIOWrapper(f, encoding="latin-1", newline="")
            return [line.rstrip("\r\n").split("|") for line in text]


def load_population(usps: str) -> pd.DataFrame:
    """Return DataFrame with columns: GEOID (15-char block), population, intptlat, intptlon."""
    pl = config.pl_zip(usps)
    if not pl.exists():
        raise FileNotFoundError(f"PL zip not found: {pl}")

    geo_rows = _read_pl_text(pl, "geo2020.pl")
    seg1_rows = _read_pl_text(pl, "000012020.pl")

    # Build geo block table (filter SUMLEV == '750').
    geo_records = []
    max_idx = max(GEO_COL.values())
    for row in geo_rows:
        if len(row) <= max_idx:
            continue
        if row[GEO_COL["SUMLEV"]] != "750":
            continue
        geoid = row[GEO_COL["GEOID"]].strip()
        # Some Census exports prefix the geocode as "7500000US{geoid}". Strip prefix if present.
        if "US" in geoid:
            geoid = geoid.split("US", 1)[1]
        # Fallback: build from components.
        if len(geoid) != 15:
            geoid = (
                row[GEO_COL["STATE"]].zfill(2)
                + row[GEO_COL["COUNTY"]].zfill(3)
                + row[GEO_COL["TRACT"]].zfill(6)
                + row[GEO_COL["BLOCK"]].zfill(4)
            )
        try:
            lat = float(row[GEO_COL["INTPTLAT"]])
            lon = float(row[GEO_COL["INTPTLON"]])
        except (ValueError, IndexError):
            lat = lon = float("nan")
        geo_records.append({
            "LOGRECNO": row[GEO_COL["LOGRECNO"]],
            "GEOID": geoid,
            "intptlat": lat,
            "intptlon": lon,
        })

    if not geo_records:
        raise RuntimeError(f"No block-level rows (SUMLEV=750) found in {pl}")

    geo_df = pd.DataFrame.from_records(geo_records)

    # Build segment-1 population table.
    pop_records = []
    for row in seg1_rows:
        if len(row) <= SEG1_P1_001N:
            continue
        try:
            pop = int(row[SEG1_P1_001N])
        except ValueError:
            continue
        pop_records.append({"LOGRECNO": row[SEG1_LOGRECNO], "population": pop})
    pop_df = pd.DataFrame.from_records(pop_records)

    merged = geo_df.merge(pop_df, on="LOGRECNO", how="left")
    if merged["population"].isna().any():
        n_missing = int(merged["population"].isna().sum())
        raise RuntimeError(f"{n_missing} blocks missing population after join")
    merged = merged.drop(columns=["LOGRECNO"])
    return merged


def load_tiger_blocks(usps: str) -> gpd.GeoDataFrame:
    """Load TIGER tabblock20 shapefile from the per-state zip."""
    tz = config.tiger_zip(usps)
    if not tz.exists():
        raise FileNotFoundError(f"TIGER zip not found: {tz}")
    gdf = gpd.read_file(f"zip://{tz}")
    geoid_col = "GEOID20" if "GEOID20" in gdf.columns else "GEOID"
    gdf = gdf[[geoid_col, "geometry"]].rename(columns={geoid_col: "GEOID"})
    gdf["GEOID"] = gdf["GEOID"].astype(str).str.zfill(15)
    return gdf


def build_blocks(usps: str, *, force: bool = False) -> Path:
    """Join population + geometry, persist as GeoPackage. Returns path."""
    out = config.blocks_gpkg(usps)
    if out.exists() and not force:
        return out

    pop = load_population(usps)
    geom = load_tiger_blocks(usps)

    n_pop, n_geom = len(pop), len(geom)
    merged = geom.merge(pop, on="GEOID", how="inner")
    if len(merged) == 0:
        raise RuntimeError("Join produced 0 rows — check GEOID formatting")
    print(f"[{usps}] PL blocks: {n_pop:,}  TIGER blocks: {n_geom:,}  joined: {len(merged):,}")
    print(f"[{usps}] total population: {int(merged['population'].sum()):,}")

    # Persist.
    merged = merged.to_crs("EPSG:4269")  # NAD83, Census standard
    merged.to_file(out, driver="GPKG", layer="blocks")
    return out


_BLOCKS_MEM_CACHE: dict[str, gpd.GeoDataFrame] = {}


def load_blocks(usps: str) -> gpd.GeoDataFrame:
    """Load the cached blocks GeoPackage for a state, building it if needed.

    Module-level memo keeps the GeoDataFrame in memory across Streamlit reruns —
    block GeoPackages are 30–80 MB so re-reading them per render is painful.
    """
    if usps in _BLOCKS_MEM_CACHE:
        return _BLOCKS_MEM_CACHE[usps]
    p = build_blocks(usps)
    gdf = gpd.read_file(p, layer="blocks")
    _BLOCKS_MEM_CACHE[usps] = gdf
    return gdf
