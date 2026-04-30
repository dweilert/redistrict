"""End-to-end smoke test on Iowa using gerrychain ReCom engine."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from redistrict import engine, graph, loader, pdf_export, persistence
from redistrict.graph import _aggregate_to_blockgroups


def main():
    blocks = loader.load_blocks("IA")
    print(f"Loaded {len(blocks):,} blocks")

    g = graph.build_graph("IA", unit="blockgroup")
    units = _aggregate_to_blockgroups(blocks)
    print(f"Graph: {g.number_of_nodes():,} block groups, {g.number_of_edges():,} edges")

    plan = engine.generate_plan(
        g, n_districts=4,
        seed_strategy="tree",
        epsilon=0.01,
        chain_length=200,
        random_seed=42,
    )
    sc = plan.scorecard
    print(f"\nPlan {plan.plan_id[:8]}")
    print(f"  unit:           {plan.unit}")
    print(f"  contiguous:     {sc['contiguous']}")
    print(f"  max |dev|:      {sc['max_abs_deviation_pct']:.4f}%")
    print(f"  PP mean / min:  {sc['polsby_popper_mean']:.4f} / {sc['polsby_popper_min']:.4f}")
    print(f"  county splits:  {sc['county_splits']}")
    print(f"  cut edges:      {sc['cut_edges']:,}")
    print(f"  score:          {sc['score']:.4f}")
    print(f"  chain steps:    {plan.accepted_steps}/{plan.chain_length}")
    print(f"  elapsed:        {plan.elapsed_sec:.1f}s")
    for d in sc["per_district"]:
        print(f"    D{d['district']}: pop={d['population']:>9,}  "
              f"dev={d['deviation_pct']:+.4f}%  PP={d['polsby_popper']:.3f}  "
              f"area={d['area_sqmi']:.0f} sq mi")

    persistence.save_plan(plan)
    pdf = pdf_export.export_pdf(plan, units)
    print(f"\nPDF: {pdf}")
    payload = pdf_export.read_provenance(pdf)
    a = persistence.decode_assignment(payload["assignment_b64gz"])
    assert len(a) == len(plan.assignment)
    print(f"Provenance round-trip OK ({len(a):,} units).")


if __name__ == "__main__":
    main()
