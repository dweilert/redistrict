"""Weighted scorecard for a districting plan.

A Plan is described by:
  assignment: np.ndarray[int]  length = number of blocks, value in [0, n_districts)

Variables tracked per district and aggregated plan-wide:
  - population_deviation       max(|pop - target|) / target            (lower better)
  - total_area_sqmi            sum of district areas                    (lower = compact)
  - compactness_penalty        1 - mean(Polsby–Popper)                  (lower better)
  - county_splits              # of counties cut across districts       (lower better)
  - perimeter_total            sum of district external perimeters      (lower better)

Plan score = sum(weights[k] * normalized_metric[k]).
Lower score is better.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

import numpy as np

DEFAULT_WEIGHTS = {
    "population_deviation": 10.0,   # by default population dominates
    "total_area_sqmi": 0.0,
    "compactness_penalty": 1.0,
    "county_splits": 1.0,
    "perimeter_total": 0.0,
}


@dataclass
class DistrictMetrics:
    district: int
    population: int
    deviation_pct: float
    area_sqmi: float
    block_count: int


@dataclass
class PlanScorecard:
    n_districts: int
    target_population: float
    total_population: int
    per_district: list[DistrictMetrics]
    max_abs_deviation_pct: float
    total_area_sqmi: float
    county_splits: int
    weights: dict
    score: float
    contiguous: bool
    unassigned_blocks: int

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def evaluate(graph: dict, assignment: np.ndarray, n_districts: int,
             weights: dict | None = None) -> PlanScorecard:
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    pop = graph["population"]
    area = graph["area_sqmi"]
    county = graph["county"]
    adj = graph["adjacency"]
    total_pop = int(pop.sum())
    target = total_pop / n_districts

    per_d: list[DistrictMetrics] = []
    max_dev = 0.0
    total_area = 0.0
    for d in range(n_districts):
        mask = assignment == d
        d_pop = int(pop[mask].sum())
        d_area = float(area[mask].sum())
        dev_pct = (d_pop - target) / target * 100.0 if target > 0 else 0.0
        max_dev = max(max_dev, abs(dev_pct))
        total_area += d_area
        per_d.append(DistrictMetrics(
            district=d,
            population=d_pop,
            deviation_pct=dev_pct,
            area_sqmi=d_area,
            block_count=int(mask.sum()),
        ))

    # County splits: a county is split if its blocks span > 1 district.
    splits = 0
    for c in np.unique(county):
        ds = np.unique(assignment[county == c])
        if len(ds) > 1:
            splits += 1

    # Contiguity check.
    contiguous = _is_contiguous(adj, assignment, n_districts)
    unassigned = int(np.sum(assignment < 0))

    # Normalize metrics (rough scales; tunable).
    norm = {
        "population_deviation": max_dev / 1.0,                  # %, target 0
        "total_area_sqmi": total_area / 100_000.0,              # state-scale
        "compactness_penalty": 0.0,                             # filled below
        "county_splits": splits / max(1, n_districts),
        "perimeter_total": 0.0,                                 # not yet computed here
    }
    # (Compactness is computed in engine when geometry available; default 0 here.)
    score = sum(weights.get(k, 0.0) * v for k, v in norm.items())
    if not contiguous:
        score += 1e6  # heavy penalty
    if unassigned:
        score += 1e6 * unassigned

    return PlanScorecard(
        n_districts=n_districts,
        target_population=target,
        total_population=total_pop,
        per_district=per_d,
        max_abs_deviation_pct=max_dev,
        total_area_sqmi=total_area,
        county_splits=splits,
        weights=weights,
        score=score,
        contiguous=contiguous,
        unassigned_blocks=unassigned,
    )


def _is_contiguous(adj: list[list[int]], assignment: np.ndarray, n_districts: int) -> bool:
    seen = np.zeros(len(adj), dtype=bool)
    for d in range(n_districts):
        members = np.where(assignment == d)[0]
        if len(members) == 0:
            return False
        # BFS from members[0] limited to district d.
        start = int(members[0])
        member_set = set(int(x) for x in members)
        stack = [start]
        seen_local = {start}
        while stack:
            v = stack.pop()
            for u in adj[v]:
                if u in member_set and u not in seen_local:
                    seen_local.add(u)
                    stack.append(u)
        if len(seen_local) != len(member_set):
            return False
        seen[members] = True
    return True
