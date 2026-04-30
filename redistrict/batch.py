"""Nationwide batch runner.

Runs ReCom on every U.S. state in parallel (one process per state). Each worker writes
its progress to a per-state JSON status file inside the batch directory so the UI (or a
``watch`` invocation) can poll them and paint a live progress map.

Layout
------
    data/batches/<batch_id>/
        manifest.json             one-time write at batch creation: settings + state list
        <USPS>_status.json        live; rewritten as the worker progresses
        <USPS>_assignment.csv     written when the worker finishes
        <USPS>_plan.json          serialized PlanResult metadata (no big arrays)

Status phases
-------------
    'queued'        worker not started
    'loading'       loading PL 94-171 + TIGER + building gpkg
    'graph'         building dual graph
    'districting'   running ReCom chain
    'done'          finished; summary metrics filled in
    'failed'        exception; error in 'error' field
    'skipped'       state has 0 or 1 seats (no districting needed)
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import time
import traceback
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from . import config


def batch_dir(batch_id: str) -> Path:
    return config.DATA_DIR / "batches" / batch_id


def ensure_batch_dir(batch_id: str) -> Path:
    p = batch_dir(batch_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_status(batch_id: str, usps: str, **fields) -> None:
    """Atomic-ish status write — write to .tmp then rename."""
    p = batch_dir(batch_id) / f"{usps}_status.json"
    existing = {}
    if p.exists():
        try:
            existing = json.loads(p.read_text())
        except json.JSONDecodeError:
            pass
    existing.update(fields)
    existing["usps"] = usps
    existing["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(existing, indent=2, default=str))
    os.replace(tmp, p)


def read_all_status(batch_id: str) -> list[dict]:
    out = []
    bd = batch_dir(batch_id)
    if not bd.exists():
        return out
    for f in bd.glob("*_status.json"):
        try:
            out.append(json.loads(f.read_text()))
        except json.JSONDecodeError:
            continue
    return sorted(out, key=lambda s: s["usps"])


def _run_state(args: dict) -> dict:
    """Worker entry point. Loads its own data; writes progress to the batch dir."""
    batch_id = args["batch_id"]
    usps = args["usps"]
    info = config.STATES[usps]
    seats = info["seats"]

    # Single-seat states: no districting needed.
    if seats <= 1:
        write_status(batch_id, usps, phase="skipped", reason=f"{seats} seat(s)",
                     seats=seats)
        return {"usps": usps, "phase": "skipped"}

    try:
        write_status(batch_id, usps, phase="loading", seats=seats,
                     started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))

        # Imports inside worker so each process owns its state.
        from . import loader, graph as graph_mod, engine, persistence

        loader.build_blocks(usps)

        write_status(batch_id, usps, phase="graph")
        g = graph_mod.build_graph(usps, unit=args["unit"])

        write_status(batch_id, usps, phase="districting",
                     n_units=g.number_of_nodes())

        plan = engine.generate_plan(
            g, n_districts=seats,
            seed_strategy=args["seed_strategy"],
            epsilon=args["epsilon"],
            chain_length=args["chain_length"],
            weights=args["weights"],
            random_seed=args["random_seed"],
        )

        # Persist assignment + plan json into the batch directory.
        bd = batch_dir(batch_id)
        with (bd / f"{usps}_assignment.csv").open("w") as f:
            for geoid, d in plan.assignment.items():
                f.write(f"{geoid},{d}\n")

        plan_meta = {
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
        (bd / f"{usps}_plan.json").write_text(
            json.dumps(plan_meta, indent=2, default=_json_default)
        )

        sc = plan.scorecard
        write_status(batch_id, usps,
                     phase="done",
                     finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     elapsed_sec=plan.elapsed_sec,
                     max_abs_deviation_pct=sc["max_abs_deviation_pct"],
                     polsby_popper_mean=sc["polsby_popper_mean"],
                     county_splits=sc["county_splits"],
                     score=sc["score"],
                     contiguous=sc["contiguous"],
                     plan_id=plan.plan_id)
        return {"usps": usps, "phase": "done", "elapsed_sec": plan.elapsed_sec}

    except Exception as e:
        tb = traceback.format_exc()
        write_status(batch_id, usps, phase="failed",
                     error=str(e), traceback=tb,
                     finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        return {"usps": usps, "phase": "failed", "error": str(e)}


def _json_default(o):
    import numpy as np
    if isinstance(o, np.integer): return int(o)
    if isinstance(o, np.floating): return float(o)
    if isinstance(o, np.ndarray): return o.tolist()
    raise TypeError(f"Not serializable: {type(o)}")


# ---- public API --------------------------------------------------------------

def create_batch(*,
                 states: list[str] | None = None,
                 unit: str = "blockgroup",
                 seed_strategy: str = "tree",
                 epsilon: float = 0.01,
                 chain_length: int = 500,
                 weights: dict | None = None,
                 random_seed_base: int | None = None,
                 batch_id: str | None = None) -> dict:
    """Create a batch directory with manifest.json. Returns the manifest dict."""
    batch_id = batch_id or datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    states = states or sorted(config.STATES.keys())
    bd = ensure_batch_dir(batch_id)
    seed_base = random_seed_base or int.from_bytes(os.urandom(4), "big")

    manifest = {
        "batch_id": batch_id,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "states": states,
        "unit": unit,
        "seed_strategy": seed_strategy,
        "epsilon": epsilon,
        "chain_length": chain_length,
        "weights": weights or {},
        "random_seed_base": seed_base,
    }
    (bd / "manifest.json").write_text(json.dumps(manifest, indent=2))

    # Initialize 'queued' status for every state so the UI can paint them gray
    # before any worker starts.
    for usps in states:
        seats = config.STATES[usps]["seats"]
        if seats <= 1:
            write_status(batch_id, usps, phase="queued_skip", seats=seats)
        else:
            write_status(batch_id, usps, phase="queued", seats=seats)
    return manifest


def run_batch(batch_id: str, *, workers: int | None = None,
              progress_interval_sec: float = 0.0) -> list[dict]:
    """Run a previously-created batch. Returns the list of worker results."""
    bd = batch_dir(batch_id)
    manifest = json.loads((bd / "manifest.json").read_text())
    workers = workers or max(1, mp.cpu_count() - 2)

    # Order states largest-first (by seat count, a proxy for size) so heavy states get
    # workers first and the trailing tail is small.
    states = sorted(
        manifest["states"],
        key=lambda u: -config.STATES[u]["seats"],
    )

    # Build per-state arg lists. Skip 0/1 seat states (handled inline by worker).
    base_seed = manifest["random_seed_base"]
    arg_list = []
    for i, usps in enumerate(states):
        arg_list.append({
            "batch_id": batch_id,
            "usps": usps,
            "unit": manifest["unit"],
            "seed_strategy": manifest["seed_strategy"],
            "epsilon": manifest["epsilon"],
            "chain_length": manifest["chain_length"],
            "weights": manifest["weights"],
            "random_seed": (base_seed + i * 1009) & 0xFFFFFFFF,
        })

    results = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_run_state, a): a["usps"] for a in arg_list}
        for fut in as_completed(futures):
            try:
                r = fut.result()
            except Exception as e:
                r = {"usps": futures[fut], "phase": "failed", "error": repr(e)}
            results.append(r)
            if progress_interval_sec > 0:
                time.sleep(progress_interval_sec)
    return results


def batch_summary(batch_id: str) -> dict:
    """Return aggregate counts: total / done / running / queued / failed / skipped."""
    statuses = read_all_status(batch_id)
    counts = {"total": len(statuses)}
    for s in statuses:
        ph = s.get("phase", "?")
        counts[ph] = counts.get(ph, 0) + 1
    counts["running"] = (counts.get("loading", 0)
                         + counts.get("graph", 0)
                         + counts.get("districting", 0))
    return counts
