"""Official current congressional districts (119th Congress) per state.

Uses the Census Cartographic Boundary file ``cb_2024_us_cd119_500k.zip`` —
each state's officially-adopted current U.S. House district map, aggregated
into a single 7-MB shapefile by Census. Downloaded once, cached.

We expose:
  - :func:`load_official` — full national GeoDataFrame (cached)
  - :func:`load_state_districts` — per-state subset, ready to render
  - :func:`official_scorecard` — same-shape scorecard as our engine output
    (population deviation, county splits, Polsby-Popper) computed against
    the 2020 Census block populations we already have on disk

This lets us compare a generated plan against the real, currently-operative
districts side by side.
"""
from __future__ import annotations

import urllib.request
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import numpy as np

from . import config

CD119_URL = ("https://www2.census.gov/geo/tiger/GENZ2024/shp/"
             "cb_2024_us_cd119_500k.zip")

EQUAL_AREA_CRS = "EPSG:9311"
SQM_PER_SQMI = 2_589_988.110336
M_PER_MI = 1609.344

_OFFICIAL_CACHE: gpd.GeoDataFrame | None = None
_SCORECARD_CACHE: dict[str, dict] = {}


def _zip_path() -> Path:
    return config.CACHE_DIR / "cb_2024_us_cd119_500k.zip"


def _ensure_zip(verbose: bool = True) -> Path:
    p = _zip_path()
    if not p.exists():
        if verbose:
            print(f"Downloading 119th Congress districts → {p}")
        urllib.request.urlretrieve(CD119_URL, p)
    return p


def load_official() -> gpd.GeoDataFrame:
    global _OFFICIAL_CACHE
    if _OFFICIAL_CACHE is not None:
        return _OFFICIAL_CACHE
    p = _ensure_zip()
    gdf = gpd.read_file(f"zip://{p}")
    if gdf.crs is None or gdf.crs.to_epsg() != 4269:
        gdf = gdf.to_crs("EPSG:4269")
    # Convert CD119FP to int district number (1-indexed in source); keep "ZZ" /
    # at-large markers as None.
    def _cd_to_int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None
    gdf["district"] = gdf["CD119FP"].apply(_cd_to_int)
    _OFFICIAL_CACHE = gdf
    return gdf


def load_state_districts(usps: str) -> gpd.GeoDataFrame:
    """Return only the rows for one state, sorted by district number."""
    gdf = load_official()
    fips = config.STATES[usps]["fips"]
    out = gdf[gdf["STATEFP"] == fips].copy()
    out = out.sort_values("district", na_position="last")
    return out


def official_scorecard(usps: str) -> dict:
    """Compute a scorecard for the official current plan for ``usps``.

    Same metrics as our engine: per-district population (and deviation), area,
    perimeter, Polsby-Popper, county splits. Computed by spatial-joining the
    2020 Census block populations into the official district polygons.
    """
    if usps in _SCORECARD_CACHE:
        return _SCORECARD_CACHE[usps]

    from . import loader  # avoid import cycle

    state_districts = load_state_districts(usps)
    if len(state_districts) == 0:
        return {"available": False, "reason": "no districts in source file"}

    blocks = loader.load_blocks(usps)
    if blocks.crs is None:
        blocks = blocks.set_crs("EPSG:4269")

    # Join blocks to districts via centroid containment.
    block_pts = blocks.copy()
    block_pts["geometry"] = block_pts.geometry.centroid
    joined = gpd.sjoin(
        block_pts[["GEOID", "population", "geometry"]],
        state_districts[["district", "geometry"]],
        how="inner",
        predicate="within",
    )

    # Per-district aggregates.
    eq = state_districts.to_crs(EQUAL_AREA_CRS)
    area_sqmi = (eq.geometry.area / SQM_PER_SQMI).to_numpy()
    perim_mi = (eq.geometry.length / M_PER_MI).to_numpy()

    n_districts = len(state_districts)
    by_d = defaultdict(int)
    counties_by_d: dict[int, set] = defaultdict(set)
    for _, row in joined.iterrows():
        d = int(row["district"])
        by_d[d] += int(row["population"])
        counties_by_d[d].add(str(row["GEOID"])[:5])

    total_pop = int(blocks["population"].sum())
    target = total_pop / max(1, n_districts)

    per_district = []
    max_dev_pct = 0.0
    pp_values = []
    for i, (_, row) in enumerate(state_districts.iterrows()):
        d = row["district"]
        if d is None:
            continue
        d = int(d)
        pop = by_d.get(d, 0)
        dev_pct = ((pop - target) / target * 100.0) if target > 0 else 0.0
        max_dev_pct = max(max_dev_pct, abs(dev_pct))
        a = float(area_sqmi[i])
        per = float(perim_mi[i])
        pp = (4 * np.pi * a) / (per * per) if per > 0 else 0.0
        pp_values.append(pp)
        per_district.append({
            "district": d - 1,  # convert to 0-indexed to match our engine output
            "population": pop,
            "deviation_pct": dev_pct,
            "area_sqmi": a,
            "perimeter_mi": per,
            "polsby_popper": pp,
            "block_count": 0,  # not tracked here
        })

    # County splits: counties whose blocks span more than one district.
    county_counts: dict[str, set[int]] = defaultdict(set)
    for d, counties in counties_by_d.items():
        for c in counties:
            county_counts[c].add(d)
    splits = sum(1 for v in county_counts.values() if len(v) > 1)

    result = {
        "available": True,
        "n_districts": n_districts,
        "total_population": total_pop,
        "target_population": target,
        "max_abs_deviation_pct": max_dev_pct,
        "polsby_popper_mean": float(np.mean(pp_values)) if pp_values else 0.0,
        "polsby_popper_min": float(np.min(pp_values)) if pp_values else 0.0,
        "county_splits": splits,
        "per_district": per_district,
    }
    _SCORECARD_CACHE[usps] = result
    return result
