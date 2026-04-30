"""CLI: build joined blocks GeoPackage + dual graph cache for one state.

Usage:
    python scripts/prepare_state.py IA --unit blockgroup
    python scripts/prepare_state.py IA --unit block --force
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from redistrict import config, graph, loader


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("usps")
    ap.add_argument("--unit", choices=["block", "blockgroup"], default="blockgroup")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    info = config.state_info(args.usps)
    print(f"Preparing {info['usps']} (FIPS {info['fips']}, {info['seats']} seats) at {args.unit}…")

    blocks_path = loader.build_blocks(info["usps"], force=args.force)
    print(f"  blocks gpkg: {blocks_path}")

    g = graph.build_graph(info["usps"], unit=args.unit, force=args.force)
    print(f"  graph: {g.number_of_nodes():,} nodes, {g.number_of_edges():,} edges, "
          f"total pop {g.graph['total_population']:,}")


if __name__ == "__main__":
    main()
