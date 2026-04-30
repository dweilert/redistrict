"""Retry the failed states in a batch after a fix to the engine/graph.

Reads the batch's manifest.json, finds states with phase 'failed', force-rebuilds their
graph cache (in case the fix is in graph.py), then reruns them in-process and updates
their status file.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from redistrict import batch as batch_mod, config


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("batch_id")
    ap.add_argument("--states", default=None,
                    help="Comma-separated USPS list to retry. Default = all 'failed' states.")
    ap.add_argument("--force-graph-rebuild", action="store_true", default=True)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    bd = batch_mod.batch_dir(args.batch_id)
    manifest = json.loads((bd / "manifest.json").read_text())

    if args.states:
        targets = sorted(args.states.upper().split(","))
    else:
        targets = []
        for f in sorted(bd.glob("*_status.json")):
            s = json.loads(f.read_text())
            if s.get("phase") == "failed":
                targets.append(s["usps"])

    if not targets:
        print("No failed states found.")
        return

    print(f"Retrying: {targets}")

    if args.force_graph_rebuild:
        from redistrict import graph as graph_mod
        for usps in targets:
            cache = config.CACHE_DIR / f"{usps.lower()}_{manifest['unit']}_graph.pkl"
            if cache.exists():
                cache.unlink()
                print(f"  removed {cache.name}")
            # Rebuild now (sequential — these are big states).
            graph_mod.build_graph(usps, unit=manifest["unit"], force=True)

    # Reset status to queued so the workers process them.
    for usps in targets:
        batch_mod.write_status(args.batch_id, usps, phase="queued")

    # Custom run loop: only over `targets`.
    from concurrent.futures import ProcessPoolExecutor, as_completed
    from redistrict.batch import _run_state
    base_seed = manifest["random_seed_base"]
    arg_list = [
        {
            "batch_id": args.batch_id,
            "usps": u,
            "unit": manifest["unit"],
            "seed_strategy": manifest["seed_strategy"],
            "epsilon": manifest["epsilon"],
            "chain_length": manifest["chain_length"],
            "weights": manifest["weights"],
            "random_seed": (base_seed + i * 1009) & 0xFFFFFFFF,
        }
        for i, u in enumerate(targets)
    ]

    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(_run_state, a): a["usps"] for a in arg_list}
        for fut in as_completed(futures):
            r = fut.result()
            print(f"  {r['usps']}: {r['phase']}")


if __name__ == "__main__":
    main()
