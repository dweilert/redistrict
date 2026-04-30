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
from redistrict.help_text import (
    TOOLTIP_UNIT, TOOLTIP_SEED, TOOLTIP_EPSILON, TOOLTIP_CHAIN_LENGTH,
    TOOLTIP_WEIGHTS, GLOSSARY_PLAIN_MD, GLOSSARY_TECHNICAL_MD,
)
from redistrict.render import PALETTE

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

from redistrict import batch as batch_mod
from redistrict.us_render import (
    render_status_map, render_result_map,
    _load_state_boundaries, render_partial_buildmap,
)
from redistrict import config as _config


def _ensure_us_boundaries():
    """Build the us_states.gpkg cache with a live US map filling in as states finish.

    This is a one-time cost (~3 minutes) the first time any user opens the Nationwide
    batch tab. Subsequent loads are instant from the cached GeoPackage.
    """
    cache = _config.CACHE_DIR / "us_states.gpkg"
    if cache.exists():
        return
    st.warning("First-run setup — building U.S. state outlines from TIGER block files. "
               "This is a **one-time** cost (~3 minutes); the result is cached.")
    bar = st.progress(0.0, text="Starting…")
    detail = st.empty()
    map_slot = st.empty()
    def progress_cb(i, n, usps, msg):
        bar.progress(min(i / n, 1.0),
                     text=f"[{i}/{n}] {usps or 'done'} — {msg}")
        detail.caption(f"{usps}: {msg}")
    def render_cb(i, n, partial_gdf):
        try:
            png = render_partial_buildmap(partial_gdf, i, n)
            map_slot.image(png, use_container_width=True)
        except Exception:
            pass
    _load_state_boundaries(verbose=False,
                           progress_cb=progress_cb,
                           partial_render_cb=render_cb)
    bar.empty()
    detail.empty()
    map_slot.empty()
    st.success("State outlines cached. Map will render quickly from now on.")

mode = st.sidebar.radio(
    "Mode",
    ["Generate plan", "Load saved PDF", "Nationwide batch"],
    index=0,
)
st.sidebar.caption("v3 · gerrychain ReCom + nationwide batch")

# =============================================================================
# GENERATE
# =============================================================================
if mode == "Generate plan":
    st.title("Generate districting plan")

    with st.expander("📖 What do these controls mean?  (open me before you tweak sliders)"):
        tab_plain, tab_tech = st.tabs(["In plain English", "Technical reference"])
        with tab_plain:
            st.markdown(GLOSSARY_PLAIN_MD)
        with tab_tech:
            st.markdown(GLOSSARY_TECHNICAL_MD)

    col_l, col_r = st.columns([1, 2])
    with col_l:
        st.subheader("State")
        # Show full names like "Iowa (IA)" but keep the USPS code as the value.
        states = sorted(
            (k for k, v in config.STATES.items() if v["seats"] >= 2),
            key=lambda k: config.STATES[k]["name"],
        )
        usps = st.selectbox(
            "State", states,
            index=states.index("IA"),
            format_func=lambda k: f"{config.STATES[k]['name']} ({k})",
        )
        seats = config.STATES[usps]["seats"]
        st.caption(f"{config.STATES[usps]['name']} ({usps}) — {seats} U.S. House seats")

        st.subheader("Resolution")
        unit = st.selectbox(
            "Unit of analysis", ["blockgroup", "block"], index=0,
            help=TOOLTIP_UNIT,
        )

        st.subheader("Engine")
        seed_strategy = st.selectbox("Initial partition", engine.SEED_STRATEGIES, index=0,
                                     help=TOOLTIP_SEED)
        epsilon_pct = st.slider("Population tolerance ε (%)",
                                0.1, 5.0, 1.0, step=0.1,
                                help=TOOLTIP_EPSILON)
        chain_length = st.slider("Chain length (ReCom steps)",
                                 50, 5000, 500, step=50,
                                 help=TOOLTIP_CHAIN_LENGTH)
        random_seed = st.number_input("Random seed (0 = clock)", value=0, step=1,
                                      help="Same seed + same settings → identical plan. "
                                           "Use 0 to randomize each run.")

        st.subheader("Variable weights")
        st.caption("Composite score = Σ weight·metric (lower = better). "
                   "Hover the (?) on each for what it does.")
        weights = {}
        for k, default in DEFAULT_WEIGHTS.items():
            weights[k] = st.slider(
                k, 0.0, 20.0, float(default), step=0.5,
                help=TOOLTIP_WEIGHTS.get(k, ""),
            )

        run = st.button("Generate", type="primary", use_container_width=True)

    with col_r:
        if run:
            g = _load_graph(usps, unit)
            units_gdf = _load_units(usps, unit)
            progress = st.progress(0, text="Running ReCom chain…")
            best_score_box = st.empty()
            map_slot = st.empty()
            map_slot.info("Map will appear after the first chain step…")

            # Render the current best partition every N steps so the user sees the
            # districts evolve as the MCMC runs.
            RENDER_EVERY = max(1, int(chain_length) // 20)  # ~20 redraws total

            steps_seen = {"n": 0, "best": float("inf"), "best_partition": None}
            def _cb(partition, sc):
                steps_seen["n"] += 1
                if sc.score < steps_seen["best"]:
                    steps_seen["best"] = sc.score
                    steps_seen["best_partition"] = partition
                pct = min(100, int(100 * steps_seen["n"] / chain_length))
                progress.progress(pct, text=f"Step {steps_seen['n']}/{chain_length}")
                best_score_box.metric(
                    "Best score so far", f"{steps_seen['best']:.4f}",
                    f"max |dev| {sc.max_abs_deviation_pct:.3f}%",
                )
                # Eye-candy: render the current best partition periodically.
                if (steps_seen["n"] % RENDER_EVERY == 0
                        and steps_seen["best_partition"] is not None):
                    try:
                        bp = steps_seen["best_partition"]
                        live_assignment = {bp.graph.nodes[n]["GEOID"]: bp.assignment[n]
                                           for n in bp.graph.nodes}
                        png = render_plan_map(
                            units_gdf, live_assignment,
                            title=f"{usps} — best after {steps_seen['n']} chain steps",
                        )
                        map_slot.image(png, use_container_width=True)
                    except Exception:
                        pass

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
            c1.metric("Total population", f"{sc['total_population']:,}",
                      help="Sum of populations across all blocks/blockgroups in the state.")
            c2.metric("Max |deviation|", f"{sc['max_abs_deviation_pct']:.4f}%",
                      delta=("✅ ≤ε" if sc["max_abs_deviation_pct"] <= plan.epsilon * 100
                             else "❌ > ε"),
                      help="Worst |district pop − target| / target across all districts. "
                           "Must be ≤ ε to be legally viable. Federal standard: ≤1%.")
            c3.metric("Polsby–Popper (mean)", f"{sc['polsby_popper_mean']:.3f}",
                      help="Compactness: 4π·area / perimeter². 1.0 = perfect circle, "
                           "0.2–0.3 typical, <0.1 indicates stringy/gerrymander shapes.")
            c4.metric("County splits", sc["county_splits"],
                      help="Number of counties whose territory is divided across "
                           "more than one district. Lower = preserves county boundaries.")

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
            st.caption("The colored square in the **District** column matches the color "
                       "of that district on the map above. Numbers next to each colored "
                       "circle on the map show the district number.")

            # Style the dataframe so the District cell is shown as a colored swatch.
            # Districts display 1-indexed (D0 internal → "1" in UI).
            def _district_swatch(d: int) -> str:
                color = PALETTE[int(d) % len(PALETTE)]
                return (f'<div style="display:flex;align-items:center;gap:8px">'
                        f'<span style="display:inline-block;width:18px;height:18px;'
                        f'border-radius:4px;background:{color};'
                        f'border:1px solid #333"></span>'
                        f'<span style="font-weight:600">{int(d) + 1}</span></div>')

            display = df.copy()
            display.insert(0, "District", display["district"].apply(_district_swatch))
            display = display.drop(columns=["district"])
            display = display.rename(columns={
                "population": "Population",
                "deviation_pct": "Deviation %",
                "area_sqmi": "Area (sq mi)",
                "perimeter_mi": "Perimeter (mi)",
                "polsby_popper": "Polsby-Popper",
                "block_count": "Units",
            })
            # Format numeric columns.
            display["Population"] = display["Population"].apply(lambda v: f"{int(v):,}")
            display["Deviation %"] = display["Deviation %"].apply(lambda v: f"{v:+.4f}")
            display["Area (sq mi)"] = display["Area (sq mi)"].apply(lambda v: f"{v:,.1f}")
            display["Perimeter (mi)"] = display["Perimeter (mi)"].apply(lambda v: f"{v:,.1f}")
            display["Polsby-Popper"] = display["Polsby-Popper"].apply(lambda v: f"{v:.3f}")
            display["Units"] = display["Units"].apply(lambda v: f"{int(v):,}")
            st.markdown(
                display.to_html(escape=False, index=False,
                                classes="redistrict-table"),
                unsafe_allow_html=True,
            )
            st.markdown(
                "<style>.redistrict-table{border-collapse:collapse;width:100%;font-size:0.9rem}"
                ".redistrict-table th,.redistrict-table td{padding:6px 10px;border-bottom:1px solid #ddd;text-align:left}"
                ".redistrict-table th{background:#f3f4f6}</style>",
                unsafe_allow_html=True,
            )

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
elif mode == "Load saved PDF":
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

        sc = payload["scorecard"]
        usps = payload["usps"]
        full_name = config.STATES.get(usps, {}).get("name", usps)
        st.success(f"Loaded plan {payload['plan_id']} — {full_name} ({usps}), "
                   f"{payload['n_districts']} districts at {payload['unit']} resolution")

        # Headline metric tiles (same as Generate page).
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total population", f"{sc['total_population']:,}")
        c2.metric("Max |deviation|", f"{sc['max_abs_deviation_pct']:.4f}%",
                  delta=("✅ ≤ε" if sc["max_abs_deviation_pct"] <= payload["epsilon"] * 100
                         else "❌ > ε"),
                  help="Worst |district pop − target| / target across all districts.")
        c3.metric("Polsby–Popper (mean)", f"{sc['polsby_popper_mean']:.3f}",
                  help="District-shape compactness. Higher is rounder/tidier.")
        c4.metric("County splits", sc["county_splits"],
                  help="Counties cut across district boundaries. Lower is better.")

        st.markdown(
            f"**Plan ID** `{payload['plan_id']}` · **Score** {sc['score']:.4f} · "
            f"**Contiguous** {'✅' if sc['contiguous'] else '❌'} · "
            f"**Steps** {payload['accepted_steps']}/{payload['chain_length']} · "
            f"**ε** {payload['epsilon']*100:.2f}% · **Unit** {payload['unit']}"
        )

        # Map.
        st.subheader("Map")
        with st.spinner("Rendering map from embedded plan data…"):
            assignment = persistence.decode_assignment(payload["assignment_b64gz"])
            units_gdf = _load_units(usps, payload["unit"])
            png = render_plan_map(
                units_gdf, assignment,
                title=f"{full_name} ({usps}) — {payload['n_districts']} districts",
            )
        st.image(png, use_container_width=True)

        # Per-district table — same color-keyed format as Generate page.
        st.subheader("Per-district metrics")
        st.caption("The colored square in **District** matches the map color above. "
                   "Numbers on the map (1, 2, …) match this table.")
        df = pd.DataFrame(sc["per_district"])

        def _swatch(d: int) -> str:
            color = PALETTE[int(d) % len(PALETTE)]
            return (f'<div style="display:flex;align-items:center;gap:8px">'
                    f'<span style="display:inline-block;width:18px;height:18px;'
                    f'border-radius:4px;background:{color};'
                    f'border:1px solid #333"></span>'
                    f'<span style="font-weight:600">{int(d) + 1}</span></div>')

        display = df.copy()
        display.insert(0, "District", display["district"].apply(_swatch))
        display = display.drop(columns=["district"]).rename(columns={
            "population": "Population",
            "deviation_pct": "Deviation %",
            "area_sqmi": "Area (sq mi)",
            "perimeter_mi": "Perimeter (mi)",
            "polsby_popper": "Polsby-Popper",
            "block_count": "Units",
        })
        display["Population"] = display["Population"].apply(lambda v: f"{int(v):,}")
        display["Deviation %"] = display["Deviation %"].apply(lambda v: f"{v:+.4f}")
        display["Area (sq mi)"] = display["Area (sq mi)"].apply(lambda v: f"{v:,.1f}")
        display["Perimeter (mi)"] = display["Perimeter (mi)"].apply(lambda v: f"{v:,.1f}")
        display["Polsby-Popper"] = display["Polsby-Popper"].apply(lambda v: f"{v:.3f}")
        display["Units"] = display["Units"].apply(lambda v: f"{int(v):,}")
        st.markdown(
            display.to_html(escape=False, index=False, classes="redistrict-table"),
            unsafe_allow_html=True,
        )
        st.markdown(
            "<style>.redistrict-table{border-collapse:collapse;width:100%;font-size:0.9rem}"
            ".redistrict-table th,.redistrict-table td{padding:6px 10px;border-bottom:1px solid #ddd;text-align:left}"
            ".redistrict-table th{background:#f3f4f6}</style>",
            unsafe_allow_html=True,
        )

        # Run parameters (less prominent — for the curious).
        with st.expander("Run parameters & weights used"):
            st.json({k: v for k, v in payload.items()
                     if k not in ("assignment_b64gz", "scorecard")})


# =============================================================================
# NATIONWIDE BATCH
# =============================================================================
if mode == "Nationwide batch":
    st.title("Nationwide batch")
    st.caption("Run the engine on every state in parallel; watch the US map fill in "
               "as workers finish. Each state runs independently — districts never "
               "cross state lines.")
    # First-run boundary cache build (one-time, ~3 minutes). Shows a progress bar.
    _ensure_us_boundaries()

    # ---- batch picker / launcher ----
    batches_root = config.DATA_DIR / "batches"
    batches_root.mkdir(parents=True, exist_ok=True)
    existing = sorted([p.name for p in batches_root.iterdir()
                       if p.is_dir() and (p / "manifest.json").exists()],
                      reverse=True)

    # Controls expander: expanded when no batch chosen yet (so user can pick/launch),
    # collapses automatically once a batch is selected.
    selected_in_state = st.session_state.get("active_batch_selected")
    with st.expander("⚙️ Batch controls — pick or launch a batch",
                     expanded=not selected_in_state):
        col_top_l, col_top_r = st.columns([1, 1])
        with col_top_l:
            st.subheader("Watch existing batch")
            selected_batch = st.selectbox(
                "Batch", ["(none)"] + existing,
                help="Pick a batch directory to watch. The map below updates every few seconds.",
            )
        with col_top_r:
            st.subheader("Launch new batch")
            with st.form("launch_form"):
                unit_b = st.selectbox("Unit", ["blockgroup", "block"], index=0,
                                      help=TOOLTIP_UNIT)
                eps_b = st.slider("Population tolerance ε (%)", 0.1, 5.0, 1.0, 0.1)
                chain_b = st.slider("Chain length", 100, 3000, 500, 50)
                workers_b = st.slider("Workers (parallel processes)", 1, 16, 6,
                                      help="One state per worker. With a 10-CPU machine, "
                                           "6 leaves headroom for the UI and system. "
                                           "Bump to 8 if you want max throughput.")
                launch = st.form_submit_button("Launch all 50 states", type="primary")
        if launch:
            # Step 1: create the batch directory and write 'queued' status for every state
            # so the map can render BEFORE any worker starts.
            manifest = batch_mod.create_batch(
                unit=unit_b, epsilon=eps_b / 100.0, chain_length=int(chain_b),
            )
            st.session_state["batch_workers"] = int(workers_b)
            st.session_state["batch_id"] = manifest["batch_id"]
            st.session_state["batch_running"] = False
            st.session_state["batch_pending_start"] = True
            st.success(f"Created batch `{manifest['batch_id']}`. "
                       f"Map renders below; click 'Start workers' to begin.")
            st.rerun()

    # ---- live progress view ----
    active_batch = (st.session_state.get("batch_id")
                    if selected_batch == "(none)" else selected_batch)
    # Once we have an active batch, remember the selection so the controls expander
    # auto-collapses on subsequent reruns.
    if active_batch and active_batch != "(none)":
        st.session_state["active_batch_selected"] = True
    if active_batch and active_batch != "(none)":
        statuses = batch_mod.read_all_status(active_batch)
        summary = batch_mod.batch_summary(active_batch)

        # Compact batch summary as a single-line status (collapsible details below).
        st.markdown(
            f"**Batch** `{active_batch}` · "
            f"**{summary.get('done', 0)}/{summary.get('total', 0)} done** · "
            f"running {summary.get('running', 0)} · "
            f"failed {summary.get('failed', 0)} · "
            f"skipped {summary.get('skipped', 0) + summary.get('queued_skip', 0)}"
        )
        with st.expander("Batch details (counts + per-state table)", expanded=False):
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Total", summary.get("total", 0))
            c2.metric("Done", summary.get("done", 0))
            c3.metric("Running", summary.get("running", 0))
            c4.metric("Failed", summary.get("failed", 0))
            c5.metric("Skipped",
                      summary.get("skipped", 0) + summary.get("queued_skip", 0))

        # If this batch was just created and hasn't started, offer a "Start workers" button.
        if st.session_state.get("batch_pending_start") and \
           st.session_state.get("batch_id") == active_batch:
            if st.button("▶ Start workers", type="primary"):
                import threading
                def _bg(bid, workers):
                    batch_mod.run_batch(bid, workers=workers)
                t = threading.Thread(
                    target=_bg,
                    args=(active_batch, st.session_state.get("batch_workers", 8)),
                    daemon=True,
                )
                t.start()
                st.session_state["batch_pending_start"] = False
                st.session_state["batch_running"] = True
                st.rerun()

        # Live US status map. Two-pass render so the user gets *something* on screen
        # immediately:
        #   Pass 1 (fast): phase-color fill only — runs in <1s the first time, instant
        #                  on rerenders.
        #   Pass 2 (slow): replace done-state fills with their real district choropleth
        #                  if the checkbox is on.
        st.markdown('<div id="redistrict-us-map"></div>', unsafe_allow_html=True)
        show_districts = st.checkbox(
            "Render real districts on done states (slower)",
            value=True,
            help="When checked, finished states show their real district choropleth "
                 "instead of a solid green fill. Adds a few seconds per state on first "
                 "render; cached after.",
        )
        map_slot = st.empty()
        try:
            # Fast pass — paint phase colors so the user has visual feedback now.
            fast_png = render_status_map(
                statuses,
                batch_id=None,
                title=f"Batch {active_batch} — live progress",
            )
            map_slot.image(fast_png, use_container_width=True)
            # Slow pass — replace with real-district render if requested.
            if show_districts:
                with st.spinner("Adding real district overlays for done states…"):
                    detailed_png = render_status_map(
                        statuses,
                        batch_id=active_batch,
                        title=f"Batch {active_batch} — live progress",
                    )
                map_slot.image(detailed_png, use_container_width=True)
        except Exception as e:
            st.error(f"Map render failed: {type(e).__name__}: {e}")
            import traceback as _tb
            st.code(_tb.format_exc())
        # Auto-scroll the page so the map is in view (only on first paint of a batch).
        scroll_key = f"scrolled_{active_batch}"
        if not st.session_state.get(scroll_key):
            st.session_state[scroll_key] = True
            st.markdown(
                """<script>
                  setTimeout(() => {
                    const el = window.parent.document.getElementById('redistrict-us-map');
                    if (el) el.scrollIntoView({behavior: 'smooth', block: 'start'});
                  }, 250);
                </script>""",
                unsafe_allow_html=True,
            )

        # Per-state status table (compact).
        if statuses:
            df_st = pd.DataFrame([
                {
                    "USPS": s["usps"],
                    "Phase": s.get("phase", "?"),
                    "Seats": s.get("seats", "—"),
                    "Max |dev| %": (f"{s['max_abs_deviation_pct']:.4f}"
                                    if "max_abs_deviation_pct" in s else "—"),
                    "PP mean": (f"{s['polsby_popper_mean']:.3f}"
                                if "polsby_popper_mean" in s else "—"),
                    "Splits": s.get("county_splits", "—"),
                    "Elapsed s": (f"{s['elapsed_sec']:.1f}"
                                  if "elapsed_sec" in s else "—"),
                }
                for s in statuses
            ])
            st.dataframe(df_st, use_container_width=True, hide_index=True)

        # Auto-refresh only while workers are actually running. Queued without running
        # means the batch is paused/dead — no point refreshing.
        active = summary.get("running", 0) > 0
        if active:
            st.caption("⏳ Auto-refreshing every 3 seconds while workers are running.")
            import time as _time
            _time.sleep(3.0)
            st.rerun()
        elif summary.get("queued", 0) > 0:
            st.info(f"{summary.get('queued', 0)} state(s) queued but no workers "
                    f"running. Use the launch panel to start a fresh batch.")
        else:
            st.success("✅ Batch finished. Render the result map below.")
            if st.button("Render nationwide result map"):
                with st.spinner("Rendering result map…"):
                    png = render_result_map(
                        active_batch,
                        title=f"Batch {active_batch} — final districts",
                    )
                st.image(png, use_container_width=True)
