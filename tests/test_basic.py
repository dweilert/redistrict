"""Smoke + invariant tests. Run with: pytest tests/"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from redistrict import config, engine, graph as graph_mod, loader, persistence, scoring
from redistrict.graph import _aggregate_to_blockgroups


# These tests need Iowa data prepped. Skip silently if it isn't available.
IA_GPKG = config.blocks_gpkg("IA")
IA_GRAPH_BG = config.CACHE_DIR / "ia_blockgroup_graph.pkl"

needs_ia = pytest.mark.skipif(
    not (IA_GPKG.exists() and IA_GRAPH_BG.exists()),
    reason="Iowa data not prepared; run scripts/prepare_state.py IA first.",
)


def test_state_info():
    info = config.state_info("IA")
    assert info["fips"] == "19"
    assert info["seats"] == 4
    with pytest.raises(ValueError):
        config.state_info("XX")


def test_assignment_round_trip():
    a = {"190010001001000": 0, "190010001001001": 1, "190010001001002": 2}
    blob = persistence.encode_assignment(a)
    b = persistence.decode_assignment(blob)
    assert a == b


@needs_ia
def test_iowa_load_and_graph():
    blocks = loader.load_blocks("IA")
    assert len(blocks) > 100_000
    assert blocks["population"].sum() > 3_000_000

    g = graph_mod.build_graph("IA", unit="blockgroup")
    assert g.number_of_nodes() > 1_000
    assert g.graph["total_population"] == int(blocks["population"].sum())
    # Graph should be connected (state is one connected territory).
    import networkx as nx
    assert nx.is_connected(g)


@needs_ia
def test_iowa_recom_meets_legal_bar():
    """A short ReCom chain on Iowa should produce a plan with ≤ 1% deviation."""
    g = graph_mod.build_graph("IA", unit="blockgroup")
    plan = engine.generate_plan(
        g, n_districts=4,
        seed_strategy="tree",
        epsilon=0.01,
        chain_length=100,
        random_seed=12345,
    )
    sc = plan.scorecard
    assert sc["contiguous"], "all districts must be contiguous"
    assert sc["max_abs_deviation_pct"] <= 1.0, (
        f"max |deviation| {sc['max_abs_deviation_pct']:.3f}% exceeds 1% legal bar"
    )
    # Population sums to the full state.
    total = sum(d["population"] for d in sc["per_district"])
    assert total == sc["total_population"]


@needs_ia
def test_pdf_provenance_round_trip(tmp_path):
    from redistrict import pdf_export
    g = graph_mod.build_graph("IA", unit="blockgroup")
    blocks = loader.load_blocks("IA")
    units = _aggregate_to_blockgroups(blocks)
    plan = engine.generate_plan(
        g, n_districts=4, seed_strategy="tree",
        epsilon=0.01, chain_length=50, random_seed=99,
    )
    pdf_path = pdf_export.export_pdf(plan, units, out_path=tmp_path / "plan.pdf")
    payload = pdf_export.read_provenance(pdf_path)
    assert payload["plan_id"] == plan.plan_id
    assert payload["usps"] == "IA"
    a = persistence.decode_assignment(payload["assignment_b64gz"])
    assert a == plan.assignment
