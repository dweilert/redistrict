"""Build and cache the dual graph used by the redistricting engine.

We use ``gerrychain.Graph`` directly. It is a NetworkX graph with these node attributes:
  - GEOID            block id
  - population       2020 P1_001N
  - area             sq mi (computed in equal-area projection)
  - perimeter        miles (block boundary length)
  - centroid_x, centroid_y     equal-area meters
  - county           5-char state+county FIPS

Edge attributes (added by gerrychain.from_geodataframe):
  - shared_perim     length of shared boundary in miles (used for Polsby-Popper)

Two units of analysis are supported via the ``unit`` argument:
  - "block"         ~175k nodes for Iowa (slowest, highest fidelity)
  - "blockgroup"    ~2.7k nodes for Iowa (fast, academic-standard for ReCom MCMC)

Output is pickled for fast reload.
"""
from __future__ import annotations

import pickle
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from gerrychain import Graph

from . import config, loader

EQUAL_AREA_CRS = "EPSG:9311"
SQM_PER_SQMI = 2_589_988.110336
M_PER_MI = 1609.344


def _aggregate_to_blockgroups(blocks: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Roll up blocks to block groups (first 12 chars of GEOID)."""
    blocks = blocks.copy()
    blocks["BG_GEOID"] = blocks["GEOID"].astype(str).str[:12]
    bg = blocks.dissolve(by="BG_GEOID", as_index=False, aggfunc={"population": "sum"})
    bg = bg.rename(columns={"BG_GEOID": "GEOID"})
    return bg


def build_graph(usps: str, *, unit: str = "blockgroup", force: bool = False) -> Graph:
    """Build (or load) the dual graph for ``usps`` at the chosen ``unit`` resolution."""
    if unit not in ("block", "blockgroup"):
        raise ValueError("unit must be 'block' or 'blockgroup'")

    cache = config.CACHE_DIR / f"{usps.lower()}_{unit}_graph.pkl"
    if cache.exists() and not force:
        with open(cache, "rb") as f:
            return pickle.load(f)

    blocks = loader.load_blocks(usps)
    if unit == "blockgroup":
        gdf = _aggregate_to_blockgroups(blocks)
    else:
        gdf = blocks.copy()

    # Reproject to equal-area for perimeter, area, centroid in consistent units.
    eq = gdf.to_crs(EQUAL_AREA_CRS)
    gdf = gdf.copy()
    gdf["area"] = (eq.geometry.area / SQM_PER_SQMI).to_numpy()
    gdf["perimeter"] = (eq.geometry.length / M_PER_MI).to_numpy()
    centroids = eq.geometry.centroid
    gdf["centroid_x"] = centroids.x.to_numpy()
    gdf["centroid_y"] = centroids.y.to_numpy()
    gdf["county"] = gdf["GEOID"].astype(str).str[:5]

    # gerrychain's from_geodataframe builds rook adjacency and adds 'shared_perim'.
    print(f"[{usps}/{unit}] building dual graph for {len(gdf):,} units…")
    g = Graph.from_geodataframe(
        gdf, adjacency="rook", reproject=False,
        cols_to_add=["GEOID", "population", "area", "perimeter",
                     "centroid_x", "centroid_y", "county"],
        ignore_errors=True,
    )

    # gerrychain stores 'shared_perim' in degrees (since we kept NAD83). Recompute in miles
    # using the equal-area geometries we already have.
    geoid_to_eq = dict(zip(gdf["GEOID"].astype(str), eq.geometry))
    fixed = 0
    for u, v in g.edges:
        gu = geoid_to_eq.get(g.nodes[u]["GEOID"])
        gv = geoid_to_eq.get(g.nodes[v]["GEOID"])
        if gu is None or gv is None:
            continue
        try:
            sp = gu.intersection(gv).length / M_PER_MI
        except Exception:
            sp = 0.0
        g.edges[u, v]["shared_perim"] = sp
        fixed += 1

    g.graph["usps"] = usps.upper()
    g.graph["unit"] = unit
    g.graph["total_population"] = int(gdf["population"].sum())

    with open(cache, "wb") as f:
        pickle.dump(g, f)
    print(f"[{usps}/{unit}] cached → {cache}  ({g.number_of_nodes():,} nodes, "
          f"{g.number_of_edges():,} edges)")
    return g


def graph_population(g: Graph) -> int:
    return g.graph["total_population"]
