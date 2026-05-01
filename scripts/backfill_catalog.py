"""Read every existing batch's per-state plan.json + assignment.csv files and
populate the catalog. Idempotent — skips entries already present."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from redistrict import catalog, config


def main():
    root = config.DATA_DIR / "batches"
    if not root.exists():
        print("No batches dir.")
        return
    n_added = 0
    for bdir in sorted(root.iterdir()):
        manifest_p = bdir / "manifest.json"
        if not manifest_p.exists():
            continue
        manifest = json.loads(manifest_p.read_text())
        batch_id = manifest["batch_id"]
        for plan_p in sorted(bdir.glob("*_plan.json")):
            usps = plan_p.name.split("_")[0]
            csv_p = bdir / f"{usps}_assignment.csv"
            if not csv_p.exists():
                continue
            try:
                plan = json.loads(plan_p.read_text())
            except json.JSONDecodeError:
                continue
            # Skip if any existing catalog entry already references this batch + state
            existing = catalog.list_entries(usps)
            already = any(
                e.get("batch_id") == batch_id for e in existing
            )
            if already:
                continue
            df = pd.read_csv(csv_p, names=["GEOID", "district"], dtype={"GEOID": str})
            assignment = dict(zip(df["GEOID"], df["district"].astype(int)))
            stamp = manifest.get("created_at", "")[:16].replace("T", " ")
            name = f"Nationwide {stamp}".strip() or f"Nationwide {batch_id[:8]}"
            catalog.save_entry(
                usps,
                name=name,
                source="nationwide",
                parameters={
                    "unit": manifest["unit"],
                    "epsilon": manifest["epsilon"],
                    "chain_length": manifest["chain_length"],
                    "seed_strategy": manifest["seed_strategy"],
                    "weights": manifest.get("weights") or {},
                    "random_seed": plan.get("random_seed"),
                },
                scorecard=plan.get("scorecard", {}),
                assignment=assignment,
                batch_id=batch_id,
            )
            n_added += 1
            print(f"  added: {usps} from {batch_id}")
    print(f"Done. {n_added} entries added.")


if __name__ == "__main__":
    main()
