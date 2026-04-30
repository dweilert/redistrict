"""Scoring metrics for districting plans.

All functions take a ``gerrychain.Partition`` (or a Plan view) and return a metric.
Metrics:
  - max_abs_deviation_pct          worst |pop - target| / target × 100
  - polsby_popper_min / mean       4π·area / perim² per district (1.0 = perfect circle)
  - reock_min / mean               area / area_of_minimum_enclosing_circle
  - county_splits                  # of counties cut across districts
  - cut_edges                      # of dual-graph edges crossing district boundaries
  - perimeter_total                sum of district external perimeters (miles)

The composite score is Σ weight·normalized_metric (lower better). Weights are user-set.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from collections import defaultdict
from typing import Iterable

import math
import numpy as np


DEFAULT_WEIGHTS = {
    "population_deviation": 10.0,   # heavily penalize imbalance
    "polsby_popper": 1.0,           # reward compactness
    "county_splits": 1.0,
    "cut_edges": 0.0,
    "total_area_sqmi": 0.0,
    "perimeter_total": 0.0,
    "reock": 0.0,
}


@dataclass
class DistrictMetrics:
    district: str | int
    population: int
    deviation_pct: float
    area_sqmi: float
    perimeter_mi: float
    polsby_popper: float
    block_count: int


@dataclass
class Scorecard:
    n_districts: int
    target_population: float
    total_population: int
    per_district: list[DistrictMetrics]
    max_abs_deviation_pct: float
    polsby_popper_min: float
    polsby_popper_mean: float
    county_splits: int
    cut_edges: int
    total_area_sqmi: float
    perimeter_total: float
    weights: dict
    score: float
    contiguous: bool

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def _district_perimeter_and_area(partition) -> tuple[dict, dict, dict]:
    """Returns (perim_per_district, area_per_district, polsby_popper_per_district)."""
    g = partition.graph
    parts = partition.parts

    area = {d: 0.0 for d in parts}
    perim_external = {d: 0.0 for d in parts}

    for node, attrs in g.nodes(data=True):
        d = partition.assignment[node]
        area[d] += float(attrs.get("area", 0.0))
        perim_external[d] += float(attrs.get("perimeter", 0.0))

    # Subtract twice the shared perimeter for edges INSIDE a district (they cancel).
    # Edges crossing districts contribute their length once to each side's external perim.
    for u, v, edata in g.edges(data=True):
        sp = float(edata.get("shared_perim", 0.0))
        du = partition.assignment[u]
        dv = partition.assignment[v]
        if du == dv:
            perim_external[du] -= 2.0 * sp

    pp = {}
    for d in parts:
        if perim_external[d] > 0:
            pp[d] = (4 * math.pi * area[d]) / (perim_external[d] ** 2)
        else:
            pp[d] = 0.0
    return perim_external, area, pp


def _county_splits(partition) -> int:
    g = partition.graph
    by_county: dict[str, set] = defaultdict(set)
    for node, attrs in g.nodes(data=True):
        c = attrs.get("county", "")
        by_county[c].add(partition.assignment[node])
    return sum(1 for ds in by_county.values() if len(ds) > 1)


def _cut_edges(partition) -> int:
    n = 0
    for u, v in partition.graph.edges:
        if partition.assignment[u] != partition.assignment[v]:
            n += 1
    return n


def _is_contiguous(partition) -> bool:
    import networkx as nx
    g = partition.graph
    for d, nodes in partition.parts.items():
        sub = g.subgraph(nodes)
        if sub.number_of_nodes() == 0:
            return False
        if not nx.is_connected(sub):
            return False
    return True


def evaluate(partition, weights: dict | None = None) -> Scorecard:
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    g = partition.graph
    n_districts = len(partition.parts)
    # Prefer the population Tally updater (registered in engine.build_initial_partition);
    # fall back to summing node attrs.
    try:
        pop_tally = partition["population"]
        total_pop = int(sum(pop_tally.values()))
    except (KeyError, TypeError):
        total_pop = int(sum(attrs.get("population", 0) for _, attrs in g.nodes(data=True)))
    target = total_pop / n_districts

    perim, area, pp = _district_perimeter_and_area(partition)
    pop_per_d: dict = defaultdict(int)
    count_per_d: dict = defaultdict(int)
    for node, attrs in g.nodes(data=True):
        d = partition.assignment[node]
        pop_per_d[d] += int(attrs.get("population", 0))
        count_per_d[d] += 1

    per_d: list[DistrictMetrics] = []
    max_dev = 0.0
    for d in sorted(partition.parts):
        dev = (pop_per_d[d] - target) / target * 100.0 if target > 0 else 0.0
        max_dev = max(max_dev, abs(dev))
        per_d.append(DistrictMetrics(
            district=d,
            population=int(pop_per_d[d]),
            deviation_pct=float(dev),
            area_sqmi=float(area[d]),
            perimeter_mi=float(perim[d]),
            polsby_popper=float(pp[d]),
            block_count=int(count_per_d[d]),
        ))

    pp_values = [m.polsby_popper for m in per_d]
    pp_min = min(pp_values) if pp_values else 0.0
    pp_mean = sum(pp_values) / len(pp_values) if pp_values else 0.0

    splits = _county_splits(partition)
    cuts = _cut_edges(partition)
    contiguous = _is_contiguous(partition)
    total_area = sum(area.values())
    total_perim = sum(perim.values())

    # Normalize each metric to roughly 0–1 so weights compare cleanly.
    norm = {
        "population_deviation": max_dev / 1.0,
        "polsby_popper": (1.0 - pp_mean),                  # higher pp = better
        "county_splits": splits / max(1, n_districts),
        "cut_edges": cuts / max(1, g.number_of_edges()),
        "total_area_sqmi": total_area / max(1.0, total_area),  # near 1.0; weighted by user
        "perimeter_total": total_perim / max(1.0, total_perim),
        "reock": 0.0,
    }
    score = sum(weights.get(k, 0.0) * v for k, v in norm.items())
    if not contiguous:
        score += 1e6

    return Scorecard(
        n_districts=n_districts,
        target_population=target,
        total_population=total_pop,
        per_district=per_d,
        max_abs_deviation_pct=max_dev,
        polsby_popper_min=pp_min,
        polsby_popper_mean=pp_mean,
        county_splits=splits,
        cut_edges=cuts,
        total_area_sqmi=total_area,
        perimeter_total=total_perim,
        weights=weights,
        score=score,
        contiguous=contiguous,
    )
