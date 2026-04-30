"""Save/load plan results, encode/decode assignment for PDF embedding."""
from __future__ import annotations

import base64
import gzip
import io
import json
import zlib
from pathlib import Path

import numpy as np

from . import config
from .engine import PlanResult


def save_plan(plan: PlanResult) -> Path:
    out = config.RUNS_DIR / plan.plan_id
    out.mkdir(parents=True, exist_ok=True)
    meta = {
        "plan_id": plan.plan_id,
        "usps": plan.usps,
        "unit": plan.unit,
        "n_districts": plan.n_districts,
        "seed_strategy": plan.seed_strategy,
        "epsilon": plan.epsilon,
        "chain_length": plan.chain_length,
        "weights": plan.weights,
        "random_seed": plan.random_seed,
        "elapsed_sec": plan.elapsed_sec,
        "accepted_steps": plan.accepted_steps,
        "scorecard": plan.scorecard,
    }
    (out / "plan.json").write_text(json.dumps(meta, indent=2, default=_json_default))

    # Compact assignment file: GEOID,district one per line.
    with (out / "assignment.csv").open("w") as f:
        for geoid, d in plan.assignment.items():
            f.write(f"{geoid},{d}\n")
    return out


def encode_assignment(assignment: dict) -> str:
    """Compress assignment dict to a base64 string for PDF metadata embedding.

    Format: list of [geoid, district] pairs encoded as JSON, gzipped, base64'd.
    """
    pairs = [[k, int(v)] for k, v in assignment.items()]
    raw = json.dumps(pairs, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(gzip.compress(raw, compresslevel=9)).decode("ascii")


def decode_assignment(blob: str) -> dict:
    raw = gzip.decompress(base64.b64decode(blob))
    pairs = json.loads(raw)
    return {p[0]: int(p[1]) for p in pairs}


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"Not serializable: {type(o)}")
