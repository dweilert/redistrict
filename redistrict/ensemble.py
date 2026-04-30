"""Ensemble runner: launch N independent ReCom chains and return the best plan.

Each chain runs in its own process (multiprocessing) since gerrychain proposals are CPU-
bound and Python's GIL makes threads useless. The returned PlanResult is the
single-best plan across all chains by composite score.
"""
from __future__ import annotations

import multiprocessing as mp
import os
import pickle
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from typing import Optional

import numpy as np

from . import engine, graph as graph_mod
from .engine import PlanResult


def _run_one_chain(args: dict) -> dict:
    """Worker entry point. Returns a dict (PlanResult is not pickleable through Process
    boundaries because it carries large dicts; plain dict is fine)."""
    g = graph_mod.build_graph(args["usps"], unit=args["unit"])
    plan = engine.generate_plan(
        g,
        n_districts=args["n_districts"],
        seed_strategy=args["seed_strategy"],
        epsilon=args["epsilon"],
        chain_length=args["chain_length"],
        weights=args["weights"],
        random_seed=args["random_seed"],
    )
    return {
        "plan_id": plan.plan_id,
        "score": plan.scorecard["score"],
        "max_abs_deviation_pct": plan.scorecard["max_abs_deviation_pct"],
        "polsby_popper_mean": plan.scorecard["polsby_popper_mean"],
        "random_seed": plan.random_seed,
        "elapsed_sec": plan.elapsed_sec,
        "plan_pickle": pickle.dumps(plan),
    }


def run_ensemble(
    usps: str, unit: str, n_districts: int,
    *,
    n_chains: int = 8,
    chain_length: int = 500,
    seed_strategy: str = "tree",
    epsilon: float = 0.01,
    weights: dict | None = None,
    base_seed: int | None = None,
    workers: Optional[int] = None,
) -> tuple[PlanResult, list[dict]]:
    """Run an ensemble of ReCom chains, return (best_plan, all_summaries).

    `all_summaries` is a list of {plan_id, score, max_abs_deviation_pct, ...} for every
    chain — useful for showing distribution / variance in the UI.
    """
    base_seed = base_seed if base_seed is not None else int.from_bytes(os.urandom(4), "big")
    rng = np.random.default_rng(base_seed)
    seeds = rng.integers(0, 2**31 - 1, size=n_chains).tolist()
    workers = workers or min(n_chains, mp.cpu_count())

    arg_list = [
        {
            "usps": usps,
            "unit": unit,
            "n_districts": n_districts,
            "seed_strategy": seed_strategy,
            "epsilon": epsilon,
            "chain_length": chain_length,
            "weights": weights,
            "random_seed": int(s),
        }
        for s in seeds
    ]

    summaries = []
    best = None
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(_run_one_chain, a) for a in arg_list]
        for fut in as_completed(futures):
            r = fut.result()
            summaries.append({k: v for k, v in r.items() if k != "plan_pickle"})
            plan = pickle.loads(r["plan_pickle"])
            if best is None or plan.scorecard["score"] < best.scorecard["score"]:
                best = plan
    return best, summaries
