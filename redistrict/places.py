"""Census places lookup — names + populations of cities/CDPs in each district.

Uses the Census Cartographic Boundary 'place' file (cb_2020_us_place_500k.zip,
~5MB, downloaded once). The CB file doesn't carry population, so we compute it
by intersecting each place polygon with the per-block population data we already
load for the engine. Block populations are summed for any block whose centroid
falls inside the place — fast and accurate enough for ranking.
"""
from __future__ import annotations

import urllib.request
from pathlib import Path

import geopandas as gpd

from . import config

CB_PLACE_500K_URL = ("https://www2.census.gov/geo/tiger/GENZ2020/shp/"
                     "cb_2020_us_place_500k.zip")

# LSAD = Legal/Statistical Area Description code → human label.
LSAD_LABELS: dict[str, str] = {
    "00": "",
    "21": "borough",
    "25": "city",
    "27": "comunidad",
    "37": "metro government",
    "39": "consolidated city",
    "41": "consolidated government",
    "43": "town",
    "45": "village",
    "46": "village",
    "47": "village",
    "53": "village",
    "57": "CDP",  # Census-designated place
}


def lsad_label(code: str) -> str:
    return LSAD_LABELS.get(code, code)


_PLACES_CACHE: gpd.GeoDataFrame | None = None
# Cache of state → place_geoid → population (computed once per state).
_PLACE_POP_CACHE: dict[str, dict[str, int]] = {}


def _places_zip() -> Path:
    return config.CACHE_DIR / "cb_2020_us_place_500k.zip"


def _ensure_places_zip(verbose: bool = True) -> Path:
    p = _places_zip()
    if not p.exists():
        if verbose:
            print(f"Downloading Census places file → {p}")
        urllib.request.urlretrieve(CB_PLACE_500K_URL, p)
    return p


def load_places() -> gpd.GeoDataFrame:
    """Read all U.S. places into a single GeoDataFrame (cached in memory)."""
    global _PLACES_CACHE
    if _PLACES_CACHE is not None:
        return _PLACES_CACHE
    p = _ensure_places_zip()
    gdf = gpd.read_file(f"zip://{p}")
    # Reproject to NAD83 (places file already is, but explicit).
    if gdf.crs is None or gdf.crs.to_epsg() != 4269:
        gdf = gdf.to_crs("EPSG:4269")
    # Keep only useful columns.
    keep = [c for c in ("STATEFP", "PLACEFP", "NAME", "NAMELSAD", "LSAD",
                        "ALAND", "AWATER", "geometry") if c in gdf.columns]
    gdf = gdf[keep].copy()
    # Compute representative_point once (cheap and stable).
    gdf["rep_point"] = gdf.geometry.representative_point()
    _PLACES_CACHE = gdf
    return gdf


def _place_populations(usps: str, statefp: str) -> dict[str, int]:
    """Population per place by spatial-joining state blocks → places.

    A block is attributed to the place that contains its centroid. Cached so the
    join only runs once per state per process.
    """
    if statefp in _PLACE_POP_CACHE:
        return _PLACE_POP_CACHE[statefp]
    from . import loader  # avoid import-time cycle
    blocks = loader.load_blocks(usps)
    places_gdf = load_places()
    state_places = places_gdf[places_gdf["STATEFP"] == statefp].copy()
    if len(state_places) == 0:
        _PLACE_POP_CACHE[statefp] = {}
        return {}
    state_places["place_id"] = state_places["STATEFP"] + state_places["PLACEFP"]

    # Keep only blocks with population > 0 to speed up the spatial join.
    blocks_pts = blocks[blocks["population"] > 0].copy()
    if blocks_pts.crs is None:
        blocks_pts = blocks_pts.set_crs("EPSG:4269")
    blocks_pts["geometry"] = blocks_pts.geometry.centroid
    joined = gpd.sjoin(
        blocks_pts[["population", "geometry"]],
        state_places[["place_id", "geometry"]],
        how="inner",
        predicate="within",
    )
    pops = (joined.groupby("place_id")["population"].sum().astype(int).to_dict())
    _PLACE_POP_CACHE[statefp] = pops
    return pops


def cities_in_polygon(district_polygon, statefp: str, usps: str,
                      max_results: int = 50) -> list[dict]:
    """Return Census places whose representative point lies inside the district.

    Sorted by population (descending). Population computed by spatially joining
    the state's per-block populations into each place once and caching.
    """
    gdf = load_places()
    state_places = gdf[gdf["STATEFP"] == statefp]
    if len(state_places) == 0:
        return []
    inside_mask = state_places["rep_point"].apply(
        lambda pt: district_polygon.contains(pt)
    )
    inside = state_places[inside_mask].copy()
    if len(inside) == 0:
        return []

    populations = _place_populations(usps, statefp)
    inside["place_id"] = inside["STATEFP"] + inside["PLACEFP"]
    inside["population"] = inside["place_id"].map(populations).fillna(0).astype(int)
    inside["area_sqmi"] = inside["ALAND"] / 2_589_988.110336
    inside = inside.sort_values(
        ["population", "area_sqmi"], ascending=[False, False]
    )

    out = []
    for _, row in inside.head(max_results).iterrows():
        lsad = str(row.get("LSAD", ""))
        out.append({
            "name": str(row.get("NAME", "")),
            "kind": lsad_label(lsad),
            "population": int(row["population"]),
            "area_sqmi": float(row["area_sqmi"]),
        })
    return out
