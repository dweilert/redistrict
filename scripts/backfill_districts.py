"""Backfill <USPS>_districts.gpkg files for batches whose workers ran before
batch.py started saving them. Reads each <USPS>_assignment.csv, dissolves to
district polygons, and writes the small gpkg.

Usage:
    python scripts/backfill_districts.py <batch_id>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import geopandas as gpd
import pandas as pd

from redistrict import batch as batch_mod, config, loader
from redistrict.graph import _aggregate_to_blockgroups


def backfill_one(batch_id: str, usps: str, unit: str) -> bool:
    bd = batch_mod.batch_dir(batch_id)
    csv = bd / f"{usps}_assignment.csv"
    out = bd / f"{usps}_districts.gpkg"
    if not csv.exists():
        return False
    if out.exists():
        return False
    df = pd.read_csv(csv, names=["GEOID", "district"], dtype={"GEOID": str})
    blocks = loader.load_blocks(usps)
    units_gdf = (_aggregate_to_blockgroups(blocks) if unit == "blockgroup" else blocks)
    units_gdf = units_gdf.copy()
    units_gdf["GEOID"] = units_gdf["GEOID"].astype(str)
    merged = units_gdf.merge(df, on="GEOID", how="inner")
    merged["district"] = merged["district"].astype(int)
    diss = merged.dissolve(by="district", as_index=False)[["district", "geometry"]]
    diss.to_file(out, driver="GPKG")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("batch_id")
    args = ap.parse_args()

    bd = batch_mod.batch_dir(args.batch_id)
    manifest = json.loads((bd / "manifest.json").read_text())
    unit = manifest["unit"]

    done_usps = []
    for f in sorted(bd.glob("*_status.json")):
        s = json.loads(f.read_text())
        if s.get("phase") == "done":
            done_usps.append(s["usps"])

    print(f"Backfilling {len(done_usps)} states for batch {args.batch_id}…")
    written = 0
    for i, usps in enumerate(done_usps, 1):
        ok = backfill_one(args.batch_id, usps, unit)
        marker = "✓" if ok else "·"
        print(f"  [{i:>2}/{len(done_usps)}] {marker} {usps}", flush=True)
        if ok:
            written += 1
    print(f"Done. Wrote {written} new gpkg files.")


if __name__ == "__main__":
    main()
