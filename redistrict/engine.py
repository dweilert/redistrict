"""Districting engine: pluggable seed + growth, weighted scoring.

Phase 1 ships:
  seed strategies:    'population' (k-means++ weighted by population)
  growth rules:       'nearest-centroid' (each step, the under-target district picks its
                      most-attractive frontier block based on a weighted cost)

The growth loop is a multi-source priority-queue flood fill:
  - Start with K seed blocks, one per district.
  - At each step, the district with the largest population shortfall pulls the lowest-cost
    unassigned neighbor (cost = euclidean distance to district centroid + weight terms).
  - Stop when every block is assigned.
  - A repair pass swaps boundary blocks between neighboring districts to reduce population
    deviation while preserving contiguity.
"""
from __future__ import annotations

import heapq
import time
import uuid
from dataclasses import dataclass, asdict
from typing import Iterable

import numpy as np

from . import scoring


SEED_STRATEGIES = ("population", "sweep-ew", "sweep-ns", "extremes", "random")
GROWTH_RULES = ("nearest-centroid", "bfs", "min-area")


@dataclass
class PlanResult:
    plan_id: str
    usps: str
    n_districts: int
    seed_strategy: str
    growth_rule: str
    weights: dict
    random_seed: int
    elapsed_sec: float
    assignment: np.ndarray
    scorecard: dict


# ---------------------------- seeds ---------------------------------------

def _seed_population(graph: dict, k: int, rng: np.random.Generator) -> list[int]:
    """K-means++ on centroids weighted by population."""
    pop = graph["population"].astype(np.float64)
    xy = graph["centroid_xy"]
    n = len(pop)
    if k > n:
        raise ValueError("More districts than blocks")

    # First seed: weighted by population.
    if pop.sum() > 0:
        first = int(rng.choice(n, p=pop / pop.sum()))
    else:
        first = int(rng.integers(0, n))
    seeds = [first]
    # Distance from each block to nearest existing seed.
    dist = np.linalg.norm(xy - xy[first], axis=1)
    for _ in range(1, k):
        probs = (dist ** 2) * pop
        if probs.sum() <= 0:
            probs = pop.copy()
            if probs.sum() <= 0:
                probs = np.ones_like(probs)
        probs = probs / probs.sum()
        nxt = int(rng.choice(n, p=probs))
        seeds.append(nxt)
        new_dist = np.linalg.norm(xy - xy[nxt], axis=1)
        dist = np.minimum(dist, new_dist)
    return seeds


def _seed_sweep(graph: dict, k: int, axis: str) -> list[int]:
    xy = graph["centroid_xy"]
    pop = graph["population"]
    coord = xy[:, 0] if axis == "ew" else xy[:, 1]
    order = np.argsort(coord if axis == "ew" else -coord)
    # Walk in sorted order, place a seed each time cumulative pop reaches target.
    cum = np.cumsum(pop[order])
    total = cum[-1]
    target = total / k
    seeds: list[int] = []
    for i in range(k):
        threshold = target * (i + 0.5)
        idx = int(np.searchsorted(cum, threshold))
        idx = min(idx, len(order) - 1)
        seeds.append(int(order[idx]))
    # Deduplicate (rare).
    seen = set()
    out = []
    for s in seeds:
        while s in seen:
            s = (s + 1) % len(order)
        seen.add(s)
        out.append(s)
    return out


def _seed_extremes(graph: dict, k: int) -> list[int]:
    xy = graph["centroid_xy"]
    n = len(xy)
    # Pick k extreme points by sweeping angle from centroid.
    cx, cy = xy.mean(axis=0)
    angles = np.arctan2(xy[:, 1] - cy, xy[:, 0] - cx)
    seeds = []
    seen = set()
    for i in range(k):
        target_angle = -np.pi + (2 * np.pi) * i / k
        # Pick block farthest from centroid within angular bin.
        bin_mask = np.abs(np.angle(np.exp(1j * (angles - target_angle)))) < (np.pi / k)
        if not bin_mask.any():
            bin_mask = np.ones(n, dtype=bool)
        d2 = ((xy[:, 0] - cx) ** 2 + (xy[:, 1] - cy) ** 2)
        d2_masked = np.where(bin_mask, d2, -1)
        idx = int(np.argmax(d2_masked))
        while idx in seen:
            idx = (idx + 1) % n
        seen.add(idx)
        seeds.append(idx)
    return seeds


def _seed_random(graph: dict, k: int, rng: np.random.Generator) -> list[int]:
    return [int(x) for x in rng.choice(len(graph["population"]), size=k, replace=False)]


def select_seeds(graph: dict, k: int, strategy: str, rng: np.random.Generator) -> list[int]:
    if strategy == "population":
        return _seed_population(graph, k, rng)
    if strategy == "sweep-ew":
        return _seed_sweep(graph, k, "ew")
    if strategy == "sweep-ns":
        return _seed_sweep(graph, k, "ns")
    if strategy == "extremes":
        return _seed_extremes(graph, k)
    if strategy == "random":
        return _seed_random(graph, k, rng)
    raise ValueError(f"Unknown seed strategy: {strategy}")


# ---------------------------- growth --------------------------------------

def _grow(graph: dict, seeds: list[int], n_districts: int, growth_rule: str,
          weights: dict) -> np.ndarray:
    """Population-aware multi-source flood fill.

    Each step picks the district with the largest population shortfall (relative to its
    target) and lets it claim the lowest-cost block on its frontier. If a district fills
    up, it stops pulling. This produces much better population balance than a single
    global priority queue.
    """
    pop = graph["population"]
    area = graph["area_sqmi"]
    xy = graph["centroid_xy"]
    adj = graph["adjacency"]
    n = len(pop)

    assignment = np.full(n, -1, dtype=np.int32)
    d_pop = np.zeros(n_districts, dtype=np.float64)
    d_centroid_sum = np.zeros((n_districts, 2), dtype=np.float64)
    d_count = np.zeros(n_districts, dtype=np.int64)
    target = pop.sum() / n_districts

    # Per-district frontier heap of (cost, tiebreak, block_idx).
    frontiers: list[list[tuple[float, int, int]]] = [[] for _ in range(n_districts)]
    counter = 0

    def cost_for(d: int, b: int) -> float:
        if growth_rule == "bfs":
            return 0.0
        if growth_rule == "min-area":
            return float(area[b])
        # nearest-centroid
        if d_count[d] == 0:
            cx, cy = xy[seeds[d]]
        else:
            cx = d_centroid_sum[d, 0] / d_count[d]
            cy = d_centroid_sum[d, 1] / d_count[d]
        return float(np.hypot(xy[b, 0] - cx, xy[b, 1] - cy))

    def push(d: int, b: int):
        nonlocal counter
        counter += 1
        heapq.heappush(frontiers[d], (cost_for(d, b), counter, int(b)))

    # Seed each district.
    for d, s in enumerate(seeds):
        assignment[s] = d
        d_pop[d] += float(pop[s])
        d_centroid_sum[d] += xy[s]
        d_count[d] += 1
        for nb in adj[s]:
            if assignment[nb] == -1:
                push(d, nb)

    assigned_count = n_districts
    overfill_factor = 1.0  # don't pull past target until everyone reached it once

    while assigned_count < n:
        # Choose district with biggest absolute shortfall that still has frontier candidates.
        # First pass: any district under target * overfill_factor.
        best_d = -1
        best_shortfall = -float("inf")
        for d in range(n_districts):
            if not frontiers[d]:
                continue
            shortfall = target * overfill_factor - d_pop[d]
            if shortfall > best_shortfall:
                best_shortfall = shortfall
                best_d = d
        if best_d == -1:
            # Everyone over target * overfill_factor (or out of frontier). Lift cap.
            if overfill_factor < 10.0:
                overfill_factor *= 1.05
                continue
            # Fallback: any district with non-empty frontier picks up remainders.
            for d in range(n_districts):
                if frontiers[d]:
                    best_d = d
                    break
            if best_d == -1:
                break

        # Pop best block from this district's frontier; skip stale entries.
        d = best_d
        block = -1
        while frontiers[d]:
            cost, _, b = heapq.heappop(frontiers[d])
            if assignment[b] == -1:
                block = b
                break
        if block == -1:
            continue  # frontier exhausted for this district; loop will pick another

        assignment[block] = d
        d_pop[d] += float(pop[block])
        d_centroid_sum[d] += xy[block]
        d_count[d] += 1
        assigned_count += 1
        for nb in adj[block]:
            if assignment[nb] == -1:
                push(d, nb)

    # Disconnected leftovers (rare): hand off to nearest district by centroid distance.
    leftover = np.where(assignment == -1)[0]
    if len(leftover) > 0:
        d_centroids = d_centroid_sum / np.maximum(d_count, 1)[:, None]
        for b in leftover:
            d2 = ((d_centroids[:, 0] - xy[b, 0]) ** 2 +
                  (d_centroids[:, 1] - xy[b, 1]) ** 2)
            d_best = int(np.argmin(d2))
            assignment[b] = d_best
            d_pop[d_best] += float(pop[b])
            d_count[d_best] += 1

    return assignment


# ---------------------------- repair --------------------------------------

def _repair_balance(graph: dict, assignment: np.ndarray, n_districts: int,
                    max_iters: int = 200_000, tol_pct: float = 0.5) -> np.ndarray:
    """Swap boundary blocks between neighboring districts to reduce population deviation.

    Strategy:
      - Maintain per-district adjacency (which districts touch which).
      - Each iteration: pick the district most over target (donor) and the adjacent
        neighbor most under target (recipient). Move a boundary block between them.
      - Accept any move that strictly reduces max |deviation|, preserves donor contiguity,
        and doesn't empty the donor.
      - Falls back to next-best donor if no move is found, then terminates.
    """
    pop = graph["population"].astype(np.int64)
    adj = graph["adjacency"]
    total = int(pop.sum())
    target = total / n_districts
    n = len(pop)

    d_pop = np.zeros(n_districts, dtype=np.int64)
    d_count = np.zeros(n_districts, dtype=np.int64)
    for d in range(n_districts):
        mask = assignment == d
        d_pop[d] = pop[mask].sum()
        d_count[d] = int(mask.sum())

    # Boundary set per district: blocks of district d with at least one neighbor in another district.
    # Recompute lazily on need.
    def is_boundary(b: int) -> bool:
        d = assignment[b]
        for nb in adj[b]:
            if assignment[nb] != d:
                return True
        return False

    def max_dev() -> float:
        return float(np.max(np.abs(d_pop - target)))

    iters = 0
    consecutive_failures = 0
    while iters < max_iters:
        iters += 1
        cur_max = max_dev()
        if cur_max / target * 100 <= tol_pct:
            break

        # Order districts by deviation (most-over first as donors).
        order_over = np.argsort(-(d_pop - target))  # most positive first
        order_under = np.argsort(d_pop - target)    # most negative first

        moved = False
        for donor in order_over:
            if d_pop[donor] <= target:
                break  # nothing left over
            if d_count[donor] <= 1:
                continue
            # Walk donor boundary and consider moves to neighboring districts.
            best_move = None  # (new_max, block, recipient)
            donor_members = np.where(assignment == donor)[0]
            for b in donor_members:
                if d_count[donor] - 1 < 1:
                    break
                # Only boundary blocks.
                neighbors_d = {assignment[nb] for nb in adj[b] if assignment[nb] != donor}
                if not neighbors_d:
                    continue
                for recipient in neighbors_d:
                    if d_pop[recipient] >= target and d_pop[donor] <= target:
                        continue
                    # Hypothetical d_pop after move.
                    new_donor = d_pop[donor] - int(pop[b])
                    new_recip = d_pop[recipient] + int(pop[b])
                    other_max = 0
                    for d in range(n_districts):
                        if d == donor or d == recipient:
                            continue
                        v = abs(d_pop[d] - target)
                        if v > other_max:
                            other_max = v
                    new_max = max(other_max, abs(new_donor - target), abs(new_recip - target))
                    if new_max + 1e-9 >= cur_max:
                        continue
                    # Contiguity check is the expensive bit; do last.
                    if not _move_preserves_contiguity(adj, assignment, int(b), int(donor)):
                        continue
                    if best_move is None or new_max < best_move[0]:
                        best_move = (new_max, int(b), int(recipient))
                        # Greedy: accept first improving move to keep things fast.
                        break
                if best_move is not None:
                    break
            if best_move is not None:
                new_max, b, recipient = best_move
                d_pop[donor] -= int(pop[b])
                d_pop[recipient] += int(pop[b])
                d_count[donor] -= 1
                d_count[recipient] += 1
                assignment[b] = recipient
                moved = True
                consecutive_failures = 0
                break
        if not moved:
            consecutive_failures += 1
            if consecutive_failures >= 1:
                break
    return assignment


def _move_preserves_contiguity(adj: list[list[int]], assignment: np.ndarray,
                               block: int, donor: int) -> bool:
    """Check whether removing `block` from `donor` leaves `donor` connected."""
    members = [int(x) for x in np.where(assignment == donor)[0] if int(x) != block]
    if not members:
        return True  # district vanishes — handled separately, allow
    member_set = set(members)
    start = members[0]
    stack = [start]
    seen = {start}
    while stack:
        v = stack.pop()
        for u in adj[v]:
            if u in member_set and u not in seen:
                seen.add(u)
                stack.append(u)
    return len(seen) == len(member_set)


# ---------------------------- top-level entry ------------------------------

def generate_plan(
    graph: dict,
    n_districts: int,
    *,
    seed_strategy: str = "population",
    growth_rule: str = "nearest-centroid",
    weights: dict | None = None,
    random_seed: int | None = None,
    repair: bool = True,
) -> PlanResult:
    if seed_strategy not in SEED_STRATEGIES:
        raise ValueError(f"seed_strategy must be one of {SEED_STRATEGIES}")
    if growth_rule not in GROWTH_RULES:
        raise ValueError(f"growth_rule must be one of {GROWTH_RULES}")

    rs = random_seed if random_seed is not None else int(time.time() * 1000) & 0xFFFFFFFF
    rng = np.random.default_rng(rs)
    weights = {**scoring.DEFAULT_WEIGHTS, **(weights or {})}

    t0 = time.time()
    seeds = select_seeds(graph, n_districts, seed_strategy, rng)
    assignment = _grow(graph, seeds, n_districts, growth_rule, weights)
    if repair:
        assignment = _repair_balance(graph, assignment, n_districts)
    elapsed = time.time() - t0

    sc = scoring.evaluate(graph, assignment, n_districts, weights)
    return PlanResult(
        plan_id=str(uuid.uuid4()),
        usps=graph["usps"],
        n_districts=n_districts,
        seed_strategy=seed_strategy,
        growth_rule=growth_rule,
        weights=weights,
        random_seed=rs,
        elapsed_sec=elapsed,
        assignment=assignment,
        scorecard=sc.to_dict(),
    )
