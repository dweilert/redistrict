"""Streamlit UI: generate plans, view results, export/load PDFs."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

# Make the parent package importable when run via `streamlit run app/streamlit_app.py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from redistrict import config, engine, graph as graph_mod, loader, pdf_export, persistence
from redistrict.render import render_plan_map, PALETTE
from redistrict.scoring import DEFAULT_WEIGHTS

st.set_page_config(page_title="Redistrict", layout="wide")

# ---- helpers (cached) -----------------------------------------------------

@st.cache_resource(show_spinner="Loading block geometry…")
def _load_blocks(usps: str):
    return loader.load_blocks(usps)


@st.cache_resource(show_spinner="Building adjacency graph…")
def _load_graph(usps: str):
    return graph_mod.build_graph(usps)


# ---- sidebar nav ----------------------------------------------------------

mode = st.sidebar.radio("Mode", ["Generate plan", "Load saved PDF"], index=0)

# =============================================================================
# GENERATE
# =============================================================================
if mode == "Generate plan":
    st.title("Generate districting plan")

    col_l, col_r = st.columns([1, 2])
    with col_l:
        st.subheader("State")
        states = sorted(k for k, v in config.STATES.items() if v["seats"] >= 1)
        usps = st.selectbox("State", states, index=states.index("IA"))
        seats = config.STATES[usps]["seats"]
        st.caption(f"{usps} — {seats} U.S. House seats")

        st.subheader("Algorithm")
        seed_strategy = st.selectbox("Seed strategy", engine.SEED_STRATEGIES, index=0)
        growth_rule = st.selectbox("Growth rule", engine.GROWTH_RULES, index=0)
        repair = st.checkbox("Run population-balance repair pass", value=True)
        random_seed = st.number_input("Random seed (0 = clock)", value=0, step=1)

        st.subheader("Variable weights")
        st.caption("Higher = more important. Score = Σ weight·metric (lower is better).")
        weights = {}
        for k, default in DEFAULT_WEIGHTS.items():
            weights[k] = st.slider(k, 0.0, 20.0, float(default), step=0.5)

        run = st.button("Generate", type="primary", use_container_width=True)

    with col_r:
        if run:
            blocks = _load_blocks(usps)
            graph = _load_graph(usps)
            with st.spinner(f"Generating {seats}-district plan for {usps}…"):
                plan = engine.generate_plan(
                    graph, n_districts=seats,
                    seed_strategy=seed_strategy,
                    growth_rule=growth_rule,
                    weights=weights,
                    random_seed=int(random_seed) if random_seed else None,
                    repair=repair,
                )
            persistence.save_plan(plan)
            st.session_state["last_plan"] = plan
            st.session_state["last_blocks"] = blocks

        plan = st.session_state.get("last_plan")
        blocks = st.session_state.get("last_blocks")

        if plan is not None and blocks is not None:
            sc = plan.scorecard
            colA, colB, colC, colD = st.columns(4)
            colA.metric("Total population", f"{sc['total_population']:,}")
            colB.metric("Target / district", f"{sc['target_population']:,.0f}")
            colC.metric("Max |deviation|", f"{sc['max_abs_deviation_pct']:.3f}%")
            colD.metric("County splits", sc["county_splits"])

            st.markdown(
                f"**Plan ID** `{plan.plan_id}` · "
                f"**Score** {sc['score']:.4f} · "
                f"**Contiguous** {'✅' if sc['contiguous'] else '❌'} · "
                f"**Elapsed** {plan.elapsed_sec:.2f}s"
            )

            with st.spinner("Rendering map…"):
                png = render_plan_map(blocks, plan.assignment,
                                      title=f"{plan.usps} — {plan.n_districts} districts")
            st.image(png, use_container_width=True)

            df = pd.DataFrame(sc["per_district"])
            st.subheader("Per-district metrics")
            st.dataframe(df, use_container_width=True, hide_index=True)

            # PDF export.
            st.subheader("Export")
            if st.button("Generate PDF"):
                with st.spinner("Writing PDF…"):
                    pdf_path = pdf_export.export_pdf(plan, blocks)
                st.success(f"Saved → {pdf_path}")
                with open(pdf_path, "rb") as f:
                    st.download_button("Download PDF", f.read(),
                                       file_name=pdf_path.name, mime="application/pdf")

# =============================================================================
# LOAD SAVED PDF
# =============================================================================
else:
    st.title("Load saved PDF")
    st.caption("Drop a PDF previously generated by this app to re-render the plan and "
               "inspect its metadata. The plan is reconstructed from the PDF alone.")

    up = st.file_uploader("PDF file", type=["pdf"])
    if up is not None:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(up.read())
            tmp_path = Path(tmp.name)
        try:
            payload = pdf_export.read_provenance(tmp_path)
        except Exception as e:
            st.error(f"Could not read provenance: {e}")
            st.stop()

        st.success(f"Loaded plan {payload['plan_id']} ({payload['usps']}, "
                   f"{payload['n_districts']} districts)")

        st.subheader("Run parameters")
        st.json({k: v for k, v in payload.items()
                 if k not in ("assignment_b64gz", "scorecard")})

        st.subheader("Scorecard")
        st.json(payload["scorecard"])

        st.subheader("Map")
        if st.button("Re-render map from PDF data"):
            blocks = _load_blocks(payload["usps"])
            assignment = persistence.decode_assignment(payload["assignment_b64gz"])
            if len(assignment) != len(blocks):
                st.error(f"Assignment length {len(assignment)} != block count {len(blocks)}")
            else:
                png = render_plan_map(blocks, assignment,
                                      title=f"{payload['usps']} — replay of {payload['plan_id'][:8]}")
                st.image(png, use_container_width=True)

        if st.button("Re-run with these settings"):
            st.session_state["prefill"] = payload
            st.info("Switch to 'Generate plan' to use these settings (sliders not yet auto-prefilled).")
