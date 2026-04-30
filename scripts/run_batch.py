"""CLI: kick off a nationwide batch and stream a live progress table.

Usage:
    python scripts/run_batch.py
    python scripts/run_batch.py --workers 8 --chain-length 500 --epsilon 0.01
    python scripts/run_batch.py --states IA,KS,MN,WI,MO       # subset
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from redistrict import batch, config


def _watch_thread(batch_id: str, total: int, stop):
    last = ""
    while not stop.is_set():
        statuses = batch.read_all_status(batch_id)
        running = [s for s in statuses if s.get("phase") in ("loading", "graph", "districting")]
        done = sum(1 for s in statuses if s.get("phase") == "done")
        failed = sum(1 for s in statuses if s.get("phase") == "failed")
        skipped = sum(1 for s in statuses if s.get("phase") in ("skipped", "queued_skip"))
        line = (f"  done={done}  running={len(running)}  failed={failed}  "
                f"skipped={skipped}  ({done+failed+skipped}/{total})  "
                f"running: " +
                ", ".join(f"{s['usps']}:{s.get('phase','?')[:4]}" for s in running[:6]))
        if line != last:
            print(line, flush=True)
            last = line
        time.sleep(1.5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", choices=["blockgroup", "block"], default="blockgroup")
    ap.add_argument("--epsilon", type=float, default=0.01,
                    help="Population tolerance, fraction (default 0.01 = 1%%)")
    ap.add_argument("--chain-length", type=int, default=500)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--states", default=None,
                    help="Comma-separated USPS list (default = all states)")
    ap.add_argument("--seed-strategy", default="tree")
    ap.add_argument("--random-seed", type=int, default=None)
    args = ap.parse_args()

    states = (sorted(args.states.upper().split(",")) if args.states
              else sorted(config.STATES.keys()))
    multi_seat = [s for s in states if config.STATES[s]["seats"] >= 2]
    single_seat = [s for s in states if config.STATES[s]["seats"] <= 1]

    print(f"Batch: {len(states)} states "
          f"({len(multi_seat)} multi-seat + {len(single_seat)} single-seat skipped)")
    print(f"Settings: unit={args.unit}  ε={args.epsilon}  chain={args.chain_length}  "
          f"workers={args.workers or 'auto'}")

    manifest = batch.create_batch(
        states=states, unit=args.unit, seed_strategy=args.seed_strategy,
        epsilon=args.epsilon, chain_length=args.chain_length,
        random_seed_base=args.random_seed,
    )
    bid = manifest["batch_id"]
    print(f"Batch id: {bid}")
    print(f"Watch at: data/batches/{bid}/")

    stop = threading.Event()
    t = threading.Thread(target=_watch_thread, args=(bid, len(states), stop), daemon=True)
    t.start()

    t0 = time.time()
    results = batch.run_batch(bid, workers=args.workers)
    stop.set()
    elapsed = time.time() - t0

    final = batch.batch_summary(bid)
    print(f"\nFinished in {elapsed:.1f}s — {final}")
    failed = [r for r in results if r.get("phase") == "failed"]
    if failed:
        print("\nFailures:")
        for r in failed:
            print(f"  {r['usps']}: {r.get('error')}")


if __name__ == "__main__":
    main()
