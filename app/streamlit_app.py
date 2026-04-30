"""Streamlit UI for the redistrict tool (gerrychain ReCom engine)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from redistrict import config, engine, graph as graph_mod, loader, pdf_export, persistence
from redistrict.graph import _aggregate_to_blockgroups
from redistrict.render import render_plan_map
from redistrict.scoring import DEFAULT_WEIGHTS

st.set_page_config(page_title="Redistrict", layout="wide")


@st.cache_resource(show_spinner="Loading block geometry…")
def _load_blocks(usps: str):
    return loader.load_blocks(usps)


@st.cache_resource(show_spinner="Loading dual graph…")
def _load_graph(usps: str, unit: str):
    return graph_mod.build_graph(usps, unit=unit)


@st.cache_resource(show_spinner="Building units geometry…")
def _load_units(usps: str, unit: str):
    blocks = _load_blocks(usps)
    if unit == "blockgroup":
        return _aggregate_to_blockgroups(blocks)
    return blocks


# ---- sidebar nav ----------------------------------------------------------

mode = st.sidebar.radio("Mode", ["Generate plan", "Load saved PDF"], index=0)
st.sidebar.caption("v2 · gerrychain ReCom MCMC engine")

# =============================================================================
# GENERATE
# =============================================================================
if mode == "Generate plan":
    st.title("Generate districting plan")

    col_l, col_r = st.columns([1, 2])
    with col_l:
        st.subheader("State")
        states = sorted(k for k, v in config.STATES.items() if v["seats"] >= 2)
        usps = st.selectbox("State", states, index=states.index("IA"))
        seats = config.STATES[usps]["seats"]
        st.caption(f"{usps} — {seats} U.S. House seats")

        st.subheader("Resolution")
        unit = st.selectbox(
            "Unit of analysis", ["blockgroup", "block"], index=0,
            help=("blockgroup = ~thousands of nodes, MCMC runs in seconds. "
                  "block = ~hundreds of thousands; minutes per chain."),
        )

        st.subheader("Engine")
        seed_strategy = st.selectbox("Initial partition", engine.SEED_STRATEGIES, index=0,
                                     help="'tree' uses random spanning-tree splits "
                                          "(matches ReCom proposal); recommended.")
        epsilon_pct = st.slider("Population tolerance ε (%)",
                                0.1, 5.0, 1.0, step=0.1,
                                help="Hard limit on |district pop - target| / target. "
                                     "Federal congressional standard is ≤1%.")
        chain_length = st.slider("Chain length (ReCom steps)",
                                 50, 5000, 500, step=50,
                                 help="More steps = better optimization, longer wait. "
                                      "200–500 is plenty for small states; 1000–5000 "
                                      "for large ones.")
        random_seed = st.number_input("Random seed (0 = clock)", value=0, step=1)

        st.subheader("Variable weights")
        st.caption("Higher = more important during chain selection. Score = Σ weight·metric "
                   "(lower better).")
        weights = {}
        for k, default in DEFAULT_WEIGHTS.items():
            weights[k] = st.slider(k, 0.0, 20.0, float(default), step=0.5)

        run = st.button("Generate", type="primary", use_container_width=True)

    with col_r:
        if run:
            g = _load_graph(usps, unit)
            units_gdf = _load_units(usps, unit)
            progress = st.progress(0, text="Running ReCom chain…")
            best_score_box = st.empty()

            steps_seen = {"n": 0, "best": float("inf")}
            def _cb(partition, sc):
                steps_seen["n"] += 1
                if sc.score < steps_seen["best"]:
                    steps_seen["best"] = sc.score
                pct = min(100, int(100 * steps_seen["n"] / chain_length))
                progress.progress(pct, text=f"Step {steps_seen['n']}/{chain_length}")
                best_score_box.metric(
                    "Best score so far", f"{steps_seen['best']:.4f}",
                    f"max |dev| {sc.max_abs_deviation_pct:.3f}%",
                )

            with st.spinner(f"Generating {seats}-district plan for {usps}…"):
                plan = engine.generate_plan(
                    g, n_districts=seats,
                    seed_strategy=seed_strategy,
                    epsilon=epsilon_pct / 100.0,
                    chain_length=int(chain_length),
                    weights=weights,
                    random_seed=int(random_seed) if random_seed else None,
                    progress_cb=_cb,
                )
            progress.empty()
            persistence.save_plan(plan)
            st.session_state["last_plan"] = plan
            st.session_state["last_units"] = units_gdf

        plan = st.session_state.get("last_plan")
        units_gdf = st.session_state.get("last_units")

        if plan is not None and units_gdf is not None:
            sc = plan.scorecard
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total population", f"{sc['total_population']:,}")
            c2.metric("Max |deviation|", f"{sc['max_abs_deviation_pct']:.4f}%",
                      delta=("✅ ≤ε" if sc["max_abs_deviation_pct"] <= plan.epsilon * 100
                             else "❌ > ε"))
            c3.metric("Polsby–Popper (mean)", f"{sc['polsby_popper_mean']:.3f}")
            c4.metric("County splits", sc["county_splits"])

            st.markdown(
                f"**Plan ID** `{plan.plan_id}` · **Score** {sc['score']:.4f} · "
                f"**Contiguous** {'✅' if sc['contiguous'] else '❌'} · "
                f"**Steps** {plan.accepted_steps}/{plan.chain_length} · "
                f"**Elapsed** {plan.elapsed_sec:.1f}s · **Unit** {plan.unit}"
            )

            with st.spinner("Rendering map…"):
                png = render_plan_map(units_gdf, plan.assignment,
                                      title=f"{plan.usps} — {plan.n_districts} districts")
            st.image(png, use_container_width=True)

            df = pd.DataFrame(sc["per_district"])
            st.subheader("Per-district metrics")
            st.dataframe(df, use_container_width=True, hide_index=True)

            st.subheader("Export")
            if st.button("Generate PDF"):
                with st.spinner("Writing PDF…"):
                    pdf_path = pdf_export.export_pdf(plan, units_gdf)
                st.success(f"Saved → {pdf_path}")
                with open(pdf_path, "rb") as f:
                    st.download_button("Download PDF", f.read(),
                                       file_name=pdf_path.name, mime="application/pdf")

# =============================================================================
# LOAD SAVED PDF
# =============================================================================
else:
    st.title("Load saved PDF")
    st.caption("Drop a PDF previously generated by this app to re-render and inspect. "
               "The plan is reconstructed from the PDF alone.")
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
                   f"{payload['n_districts']} districts at {payload['unit']} resolution)")

        st.subheader("Run parameters")
        st.json({k: v for k, v in payload.items()
                 if k not in ("assignment_b64gz", "scorecard")})
        st.subheader("Scorecard")
        st.json(payload["scorecard"])

        st.subheader("Map")
        if st.button("Re-render map from PDF data"):
            assignment = persistence.decode_assignment(payload["assignment_b64gz"])
            units_gdf = _load_units(payload["usps"], payload["unit"])
            png = render_plan_map(units_gdf, assignment,
                                  title=f"{payload['usps']} — replay of {payload['plan_id'][:8]}")
            st.image(png, use_container_width=True)
