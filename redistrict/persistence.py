"""Save and load plan results (canonical JSON + assignment array)."""
from __future__ import annotations

import gzip
import io
import json
from pathlib import Path

import numpy as np

from . import config
from .engine import PlanResult


def save_plan(plan: PlanResult) -> Path:
    """Save plan to data/runs/<plan_id>/. Returns the directory."""
    out = config.RUNS_DIR / plan.plan_id
    out.mkdir(parents=True, exist_ok=True)
    np.save(out / "assignment.npy", plan.assignment)
    meta = {
        "plan_id": plan.plan_id,
        "usps": plan.usps,
        "n_districts": plan.n_districts,
        "seed_strategy": plan.seed_strategy,
        "growth_rule": plan.growth_rule,
        "weights": plan.weights,
        "random_seed": plan.random_seed,
        "elapsed_sec": plan.elapsed_sec,
        "scorecard": plan.scorecard,
    }
    (out / "plan.json").write_text(json.dumps(meta, indent=2, default=_json_default))
    return out


def _json_default(o):
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"Not serializable: {type(o)}")


def encode_assignment(assignment: np.ndarray) -> str:
    """Compress + base64 encode for embedding in PDF metadata."""
    import base64
    buf = io.BytesIO()
    np.save(buf, assignment.astype(np.int32))
    return base64.b64encode(gzip.compress(buf.getvalue())).decode("ascii")


def decode_assignment(blob: str) -> np.ndarray:
    import base64
    raw = gzip.decompress(base64.b64decode(blob))
    return np.load(io.BytesIO(raw))
