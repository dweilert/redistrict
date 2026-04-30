"""End-to-end smoke test on Iowa: generate a plan, save it, export PDF, read PDF back."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from redistrict import engine, graph, loader, pdf_export, persistence


def main():
    blocks = loader.load_blocks("IA")
    g = graph.build_graph("IA")
    print(f"Loaded {len(blocks):,} blocks")

    plan = engine.generate_plan(
        g, n_districts=4,
        seed_strategy="population",
        growth_rule="nearest-centroid",
        random_seed=42,
    )
    sc = plan.scorecard
    print(f"\nPlan {plan.plan_id[:8]}")
    print(f"  contiguous:    {sc['contiguous']}")
    print(f"  max |dev|:     {sc['max_abs_deviation_pct']:.3f}%")
    print(f"  county splits: {sc['county_splits']}")
    print(f"  score:         {sc['score']:.4f}")
    print(f"  elapsed:       {plan.elapsed_sec:.2f}s")
    for d in sc["per_district"]:
        print(f"    D{d['district']}: pop={d['population']:>10,}  "
              f"dev={d['deviation_pct']:+.3f}%  area={d['area_sqmi']:.0f} sq mi")

    persistence.save_plan(plan)
    pdf = pdf_export.export_pdf(plan, blocks)
    print(f"\nPDF: {pdf}")

    payload = pdf_export.read_provenance(pdf)
    a = persistence.decode_assignment(payload["assignment_b64gz"])
    assert len(a) == len(plan.assignment)
    assert (a == plan.assignment).all()
    print(f"Provenance round-trip OK ({len(a):,} blocks).")


if __name__ == "__main__":
    main()
