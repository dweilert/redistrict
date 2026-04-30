"""Build and cache the block adjacency graph.

Two blocks are neighbors if their geometries share more than a point (Queen contiguity
filtered to Rook would skip corner-only neighbors; we use Queen for robustness then drop
zero-length intersections to approximate Rook).

Output is a pickled dict for fast reload:
    {
        'usps': str,
        'geoids': list[str],            # node ordering
        'population': np.ndarray[int],
        'centroid_xy': np.ndarray[float, (n, 2)],   # x=lon, y=lat
        'area_sqmi': np.ndarray[float],
        'county': np.ndarray['<U5'],    # county FIPS (state+county)
        'adjacency': list[list[int]],   # adjacency list of node indices
    }
"""
from __future__ import annotations

import pickle
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely.strtree import STRtree

from . import config, loader

# Equal-area projection for area calculations (US National Atlas, EPSG:9311 / former 2163).
EQUAL_AREA_CRS = "EPSG:9311"
SQM_PER_SQMI = 2_589_988.110336


def _build_adjacency(gdf: gpd.GeoDataFrame) -> list[list[int]]:
    """Queen-style adjacency via STRtree, dropping point-only touches."""
    geoms = list(gdf.geometry.values)
    tree = STRtree(geoms)
    n = len(geoms)
    adj: list[set[int]] = [set() for _ in range(n)]
    for i, g in enumerate(geoms):
        # Query candidates whose envelope intersects this geometry's envelope.
        candidates = tree.query(g)
        for j in candidates:
            j = int(j)
            if j <= i:
                continue
            other = geoms[j]
            if not g.intersects(other):
                continue
            inter = g.intersection(other)
            # Skip pure-point touches (corner contact).
            if inter.is_empty:
                continue
            if inter.geom_type in ("Point", "MultiPoint"):
                continue
            adj[i].add(j)
            adj[j].add(i)
    return [sorted(s) for s in adj]


def build_graph(usps: str, *, force: bool = False) -> dict:
    """Build node + adjacency cache for a state. Returns dict (also persisted)."""
    cache = config.graph_cache(usps)
    if cache.exists() and not force:
        with open(cache, "rb") as f:
            return pickle.load(f)

    gdf = loader.load_blocks(usps)
    print(f"[{usps}] building adjacency for {len(gdf):,} blocks…")

    # Reproject for area + centroids in equal-area meters.
    eq = gdf.to_crs(EQUAL_AREA_CRS)
    centroids = eq.geometry.centroid
    area_sqmi = (eq.geometry.area / SQM_PER_SQMI).to_numpy()

    # Adjacency uses NAD83 (degrees) — fine, it's just topology.
    adj = _build_adjacency(gdf)

    # County code = first 5 chars of GEOID (state FIPS + county FIPS).
    county = gdf["GEOID"].astype(str).str[:5].to_numpy()

    data = {
        "usps": usps.upper(),
        "geoids": gdf["GEOID"].astype(str).tolist(),
        "population": gdf["population"].astype(np.int64).to_numpy(),
        "centroid_xy": np.column_stack([centroids.x.to_numpy(), centroids.y.to_numpy()]),
        "area_sqmi": area_sqmi,
        "county": county,
        "adjacency": adj,
    }

    with open(cache, "wb") as f:
        pickle.dump(data, f)
    print(f"[{usps}] graph cached → {cache}")
    return data
