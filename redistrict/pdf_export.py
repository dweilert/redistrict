"""Self-contained PDF export with embedded plan provenance.

Cover page lists run parameters; map and per-district scorecard follow. The full plan
(including a gzip+base64 GEOID→district mapping) is embedded in the PDF's /Keywords field
so the viewer can reconstruct the map from the PDF alone.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak,
)

from . import config, persistence
from .engine import PlanResult
from .render import render_plan_map


PROVENANCE_KEY = "RedistrictPlanV2"


def _provenance_payload(plan: PlanResult) -> dict:
    return {
        "schema": PROVENANCE_KEY,
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
        "assignment_b64gz": persistence.encode_assignment(plan.assignment),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def export_pdf(plan: PlanResult, units_gdf, out_path: Path | None = None) -> Path:
    out_path = out_path or (
        config.EXPORTS_DIR
        / f"{plan.usps}_{plan.unit}_{plan.n_districts}d_{plan.plan_id[:8]}.pdf"
    )

    map_png = render_plan_map(
        units_gdf, plan.assignment,
        title=f"{plan.usps} — {plan.n_districts} districts ({plan.unit} resolution)",
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=18, spaceAfter=12)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=13, spaceAfter=8)
    body = styles["BodyText"]

    payload_json = json.dumps(_provenance_payload(plan), default=_json_default)

    doc = SimpleDocTemplate(
        str(out_path), pagesize=LETTER,
        leftMargin=0.6 * inch, rightMargin=0.6 * inch,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
        title=f"{plan.usps} {plan.n_districts}-district plan {plan.plan_id[:8]}",
        author="redistrict",
        subject="Population-only congressional redistricting plan",
        keywords=f"{PROVENANCE_KEY}={payload_json}",
    )
    story = []
    sc = plan.scorecard

    story.append(Paragraph(f"{plan.usps} Districting Plan", h1))
    story.append(Paragraph(
        f"<b>Plan ID:</b> {plan.plan_id}<br/>"
        f"<b>Generated:</b> {datetime.now(timezone.utc).isoformat(timespec='seconds')}<br/>"
        f"<b>Unit of analysis:</b> {plan.unit}<br/>"
        f"<b>State seats:</b> {plan.n_districts}<br/>"
        f"<b>Total population:</b> {sc['total_population']:,}<br/>"
        f"<b>Target / district:</b> {sc['target_population']:,.1f}<br/>"
        f"<b>Max |deviation|:</b> {sc['max_abs_deviation_pct']:.4f}%<br/>"
        f"<b>Polsby–Popper (mean / min):</b> {sc['polsby_popper_mean']:.4f} / "
        f"{sc['polsby_popper_min']:.4f}<br/>"
        f"<b>County splits:</b> {sc['county_splits']}<br/>"
        f"<b>Cut edges:</b> {sc['cut_edges']:,}<br/>"
        f"<b>Contiguous:</b> {'yes' if sc['contiguous'] else 'NO'}<br/>"
        f"<b>Composite score (lower better):</b> {sc['score']:.4f}<br/>",
        body,
    ))
    story.append(Spacer(1, 0.15 * inch))
    story.append(Paragraph("Algorithm", h2))
    story.append(Paragraph(
        f"<b>Engine:</b> gerrychain ReCom MCMC<br/>"
        f"<b>Seed strategy:</b> {plan.seed_strategy}<br/>"
        f"<b>ε (population tolerance):</b> {plan.epsilon}<br/>"
        f"<b>Chain length:</b> {plan.chain_length} ({plan.accepted_steps} accepted)<br/>"
        f"<b>Random seed:</b> {plan.random_seed}<br/>"
        f"<b>Elapsed:</b> {plan.elapsed_sec:.2f} sec<br/>",
        body,
    ))
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph("Weights", h2))
    weight_rows = [["Variable", "Weight"]] + [
        [k, f"{v:.3f}"] for k, v in plan.weights.items()
    ]
    t = Table(weight_rows, hAlign="LEFT", colWidths=[2.5 * inch, 1 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    story.append(t)

    story.append(PageBreak())
    story.append(Paragraph(f"{plan.usps} — District Map", h1))
    story.append(Image(BytesIO(map_png), width=7.0 * inch, height=7.0 * inch,
                       kind="proportional"))

    story.append(PageBreak())
    story.append(Paragraph("Per-District Metrics", h1))
    rows = [["#", "Population", "Deviation %", "Area (sq mi)",
             "Perimeter (mi)", "PP", "Units"]]
    for d in sc["per_district"]:
        rows.append([
            str(d["district"]),
            f"{d['population']:,}",
            f"{d['deviation_pct']:+.4f}",
            f"{d['area_sqmi']:,.1f}",
            f"{d['perimeter_mi']:,.1f}",
            f"{d['polsby_popper']:.3f}",
            f"{d['block_count']:,}",
        ])
    t = Table(rows, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
    ]))
    story.append(t)

    story.append(Spacer(1, 0.3 * inch))
    story.append(Paragraph(
        "<i>This PDF embeds the full plan (GEOID → district mapping) in its metadata; "
        "the viewer can reconstruct the map directly from this file.</i>",
        body,
    ))

    doc.build(story)
    return out_path


def _json_default(o):
    import numpy as np
    if isinstance(o, np.integer): return int(o)
    if isinstance(o, np.floating): return float(o)
    if isinstance(o, np.ndarray): return o.tolist()
    raise TypeError(f"Not serializable: {type(o)}")


def read_provenance(pdf_path: Path) -> dict:
    from pypdf import PdfReader
    reader = PdfReader(str(pdf_path))
    keywords = reader.metadata.get("/Keywords") if reader.metadata else None
    if not keywords or not keywords.startswith(f"{PROVENANCE_KEY}="):
        raise ValueError(f"PDF has no embedded {PROVENANCE_KEY} provenance")
    return json.loads(keywords[len(PROVENANCE_KEY) + 1:])
