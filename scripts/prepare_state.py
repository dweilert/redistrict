"""CLI: build blocks GeoPackage + adjacency graph cache for one state.

Usage:
    python scripts/prepare_state.py IA
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from redistrict import config, graph, loader


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("usps", help="State USPS code, e.g. IA")
    ap.add_argument("--force", action="store_true", help="Rebuild even if cached")
    args = ap.parse_args()

    info = config.state_info(args.usps)
    print(f"Preparing {info['usps']} (FIPS {info['fips']}, {info['seats']} seats)…")

    blocks_path = loader.build_blocks(info["usps"], force=args.force)
    print(f"  blocks: {blocks_path}")

    g = graph.build_graph(info["usps"], force=args.force)
    print(f"  graph: {len(g['geoids']):,} nodes, "
          f"{sum(len(a) for a in g['adjacency']) // 2:,} edges")


if __name__ == "__main__":
    main()
