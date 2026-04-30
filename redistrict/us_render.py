"""Render nationwide views: status map (live progress) and result map (final plans).

Status map
----------
A choropleth of the 48 contiguous states + AK + HI inset, colored by phase:
    queued       light gray
    loading      pale yellow
    graph        amber
    districting  blue
    done         green
    failed       red
    skipped      dark gray (single-seat states or no-op)

Result map
----------
A choropleth of the country with each district drawn in a per-state color cycle. Used
for the nationwide PDF and the Streamlit batch view.

These renderers prefer the cb_2020_us_state_500k Cartographic Boundary file from Census
when present (smaller, faster) and fall back to building a state outline by dissolving
the per-state TIGER block files.
"""
from __future__ import annotations

import time
from io import BytesIO
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Patch

from . import config
from .render import PALETTE


PHASE_COLORS = {
    "queued":      "#e5e7eb",   # waiting — light gray
    "queued_skip": "#9ca3af",   # 1-seat state, no work — darker gray
    # In-progress phases all use the same pale amber so the user sees "this state is
    # being worked on right now" at a glance. Specific phase shows in the table below.
    "loading":     "#fde68a",
    "graph":       "#fde68a",
    "districting": "#fde68a",
    "done":        "#34d399",   # finished — green
    "failed":      "#f87171",   # red
    "skipped":     "#9ca3af",
    "?":           "#ffffff",
}

# Continental US display projection (Albers Equal Area).
CONUS_PROJ = "EPSG:5070"
# AK and HI use their own projections for legibility.
AK_PROJ = "EPSG:3338"
HI_PROJ = "EPSG:26963"


def _quick_state_bboxes() -> dict[str, tuple[float, float, float, float]]:
    """Read just the layer envelope from each TIGER zip — milliseconds per state."""
    import pyogrio
    out: dict[str, tuple] = {}
    for usps in config.STATES:
        zp = config.tiger_zip(usps)
        if not zp.exists():
            continue
        try:
            info = pyogrio.read_info(f"zip://{zp}")
            out[usps] = tuple(info["total_bounds"])
        except Exception:
            pass
    return out


def _quick_state_hulls(progress_cb=None) -> dict[str, "BaseGeometry"]:
    """Convex hull of every Nth block centroid per state.

    Much better-looking than rectangles; still fast (~5s total for 50 states because we
    sample only 1-in-200 blocks). Used as placeholder geometry while the real outlines
    are being built.
    """
    out: dict[str, object] = {}
    SAMPLE_EVERY = 200
    states = list(config.STATES.items())
    for i, (usps, info) in enumerate(states, 1):
        zp = config.tiger_zip(usps)
        if not zp.exists():
            continue
        if progress_cb:
            progress_cb(i, len(states), usps)
        try:
            gdf = gpd.read_file(f"zip://{zp}")
            sampled = gdf.iloc[::SAMPLE_EVERY].geometry
            # Union the centroids' convex hull — captures the rough state shape cheaply.
            from shapely.ops import unary_union
            hull = unary_union([g.centroid for g in sampled]).convex_hull
            out[usps] = hull
        except Exception:
            pass
    return out


CB_STATE_500K_URL = ("https://www2.census.gov/geo/tiger/GENZ2020/shp/"
                     "cb_2020_us_state_500k.zip")


def _load_state_boundaries(verbose: bool = True, progress_cb=None,
                           partial_render_cb=None) -> gpd.GeoDataFrame:
    """Load per-state outlines.

    Strategy
    --------
    Use the U.S. Census **Cartographic Boundary** state file (cb_2020_us_state_500k).
    It's a small (~3.5 MB) pre-aggregated state-level shapefile published by Census
    and is the right tool for state outlines (vs. dissolving 175k-block files
    ourselves, which is slow). If the file isn't already on disk, download it once
    (~1 second) and cache.
    """
    cache = config.CACHE_DIR / "us_states.gpkg"
    if cache.exists():
        return gpd.read_file(cache)

    # ---- get the CB state file (download if missing) ----
    cb_zip = config.CACHE_DIR / "cb_2020_us_state_500k.zip"
    if not cb_zip.exists():
        if verbose:
            print(f"Downloading Census state outline file → {cb_zip}", flush=True)
        if progress_cb:
            progress_cb(0, 1, "", "downloading Census state outlines (3.5MB)…")
        import urllib.request
        urllib.request.urlretrieve(CB_STATE_500K_URL, cb_zip)

    if progress_cb:
        progress_cb(1, 1, "", "loading state outlines…")
    gdf = gpd.read_file(f"zip://{cb_zip}")

    # Normalize columns: STATEFP, STUSPS, NAME come from the CB shapefile.
    fips_to_usps = {info["fips"]: usps for usps, info in config.STATES.items()}
    gdf["usps"] = gdf["STATEFP"].map(fips_to_usps)
    gdf = gdf[gdf["usps"].notna()].copy()

    rows = []
    for _, row in gdf.iterrows():
        u = row["usps"]
        info = config.STATES[u]
        rows.append({
            "usps": u,
            "name": info["name"],
            "seats": info["seats"],
            "geometry": row.geometry,
        })
    states = gpd.GeoDataFrame(rows, crs=gdf.crs)
    states.to_file(cache, driver="GPKG")

    if verbose:
        print(f"Cached {len(states)} states → {cache}", flush=True)
    return states


def _DEPRECATED_load_state_boundaries(verbose: bool = True, progress_cb=None,
                                       partial_render_cb=None):
    """Legacy fallback if no internet — kept for reference. Slow.

    Algorithm
    ---------
    For each state:
      1. Sample 1-in-N blocks (10 by default — sparse enough for speed, dense enough
         that buffered blocks overlap).
      2. Buffer each sampled block by ~1km. Adjacent blocks now overlap; sample gaps
         get bridged.
      3. unary_union → a single outline polygon (or MultiPolygon for islands).
      4. Negative buffer to undo most of the inflation.
      5. simplify() to a coarse tolerance.

    This produces a clean state outline in ~1s per state instead of several minutes
    for a full block-level dissolve.

    The cache is written to ``data/cache/us_states.gpkg`` once and never rebuilt
    unless the file is deleted.

    Args:
        verbose: print per-state progress to stdout.
        progress_cb: optional callable(i, n, usps, msg) called once per state — used
            by the Streamlit UI to show a live progress bar/status.
    """
    cache = config.CACHE_DIR / "us_states.gpkg"
    if cache.exists():
        return gpd.read_file(cache)

    if verbose:
        print(f"Building one-time US state boundary cache → {cache}", flush=True)

    SAMPLE_EVERY = 10
    BUFFER_DEG = 0.012      # ~1.3km near 40°N — enough to bridge sample gaps
    SIMPLIFY_TOL = 0.005    # ~500m near 40°N — fine for the rendered scale

    states_list = sorted(config.STATES.items())
    n = len(states_list)
    crs = "EPSG:4269"

    # ---- PASS 1: instant bbox placeholders for ALL 50 states ----
    # pyogrio.read_info gets layer envelope in milliseconds — total <1s for 50 states.
    # Bboxes are rectangular and not pretty but they show the WHOLE US instantly so the
    # user has visual context from the moment the page loads. Real outlines replace
    # them in PASS 2.
    placeholder_geoms: dict[str, object] = {}
    if partial_render_cb is not None:
        if progress_cb:
            progress_cb(0, n, "", "computing placeholder shapes…")
        from shapely.geometry import box
        bboxes = _quick_state_bboxes()
        for u, sinfo in config.STATES.items():
            if u not in bboxes:
                continue
            xmin, ymin, xmax, ymax = bboxes[u]
            placeholder_geoms[u] = box(xmin, ymin, xmax, ymax)

        ph_rows = []
        for usps, info in config.STATES.items():
            geom = placeholder_geoms.get(usps)
            if geom is None:
                continue
            ph_rows.append({
                "usps": usps,
                "name": info["name"],
                "seats": info["seats"],
                "geometry": geom,
                "_placeholder": True,
            })
        try:
            partial_render_cb(0, n, gpd.GeoDataFrame(ph_rows, crs=crs))
        except Exception as e:
            if verbose:
                print(f"  (placeholder pass render error: {e})", flush=True)

    # ---- PASS 2: high-quality outlines, one state at a time ----
    rows = []
    for i, (usps, info) in enumerate(states_list, 1):
        zp = config.tiger_zip(usps)
        if not zp.exists():
            continue
        if progress_cb:
            progress_cb(i, n, usps, "reading TIGER")
        t0 = time.time()
        gdf = gpd.read_file(f"zip://{zp}")
        crs = gdf.crs
        sampled = gdf.iloc[::SAMPLE_EVERY].geometry
        if progress_cb:
            progress_cb(i, n, usps, f"unioning {len(sampled):,} sampled blocks")
        # Buffer → union → unbuffer → simplify.
        inflated = sampled.buffer(BUFFER_DEG)
        outline = (inflated.union_all() if hasattr(inflated, "union_all")
                   else inflated.unary_union)
        outline = outline.buffer(-BUFFER_DEG * 0.6)  # partial deflate; full deflate would shrink small states
        outline = outline.simplify(SIMPLIFY_TOL, preserve_topology=True)
        rows.append({
            "usps": usps,
            "name": info["name"],
            "seats": info["seats"],
            "geometry": outline,
        })
        if verbose:
            print(f"  [{i:>2}/{n}] {usps:<3} {len(gdf):>7,} blocks → "
                  f"{len(sampled):>5,} sampled  ({time.time()-t0:.1f}s)", flush=True)
        # Eye-candy: merge built real outlines + remaining placeholder hulls so the
        # user sees the WHOLE country (real green outlines for done states + gray
        # placeholders for pending).
        if partial_render_cb is not None:
            try:
                done_usps = {r["usps"] for r in rows}
                merged = []
                for r in rows:
                    merged.append({**r, "_placeholder": False})
                for u, sinfo in config.STATES.items():
                    if u in done_usps:
                        continue
                    geom = placeholder_geoms.get(u)
                    if geom is None:
                        continue
                    merged.append({
                        "usps": u, "name": sinfo["name"], "seats": sinfo["seats"],
                        "geometry": geom,
                        "_placeholder": True,
                    })
                partial_render_cb(i, n, gpd.GeoDataFrame(merged, crs=crs))
            except Exception as e:
                if verbose:
                    print(f"    (partial render cb error: {e})", flush=True)

    states = gpd.GeoDataFrame(rows, crs=crs)
    states = states.drop(columns=[c for c in ("_placeholder",) if c in states.columns])
    states.to_file(cache, driver="GPKG")
    if verbose:
        print(f"Cached {len(states)} states to {cache}", flush=True)
    if progress_cb:
        progress_cb(n, n, "", "complete")
    return states


# ---- status map -------------------------------------------------------------

def render_partial_buildmap(partial_gdf: gpd.GeoDataFrame,
                            i: int, n: int,
                            figsize: tuple[float, float] = (12, 7)) -> bytes:
    """Render a CONUS+AK+HI map showing build progress.

    The first call (i=0) gets a placeholder GeoDataFrame containing every state's
    bounding box. Subsequent calls get real per-state outlines for the states built
    so far. We render placeholders as light gray, completed states as green.
    """
    fig = plt.figure(figsize=figsize, dpi=110)
    ax_main = fig.add_axes([0.0, 0.05, 1.0, 0.92])
    # Fixed CONUS extent in EPSG:5070 (meters). Covers from S Texas to Canadian border.
    ax_main.set_xlim(-2_400_000, 2_300_000)
    ax_main.set_ylim(200_000, 3_200_000)
    ax_main.set_axis_off()
    ax_main.set_aspect("equal")

    if len(partial_gdf):
        gdf = partial_gdf.copy()
        if "_placeholder" not in gdf.columns:
            gdf["_placeholder"] = False
        conus = gdf[~gdf["usps"].isin(["AK", "HI"])].to_crs(CONUS_PROJ)
        if len(conus):
            ph = conus[conus["_placeholder"] == True]
            done = conus[conus["_placeholder"] == False]
            if len(ph):
                ph.plot(ax=ax_main, color="#e5e7eb",
                        edgecolor="#9ca3af", linewidth=0.5)
            if len(done):
                done.plot(ax=ax_main, color="#34d399",
                          edgecolor="#0f5132", linewidth=0.4)
            for _, row in conus.iterrows():
                try:
                    pt = row.geometry.representative_point()
                    ax_main.annotate(row["usps"], xy=(pt.x, pt.y),
                                     ha="center", va="center", fontsize=7, color="#111")
                except Exception:
                    pass

    fig.suptitle(f"Building US state outlines… {i}/{n} done",
                 fontsize=12, y=0.99, color="#1f2937")

    buf = BytesIO()
    # NOTE: do NOT use bbox_inches="tight" — it crops to drawn content and chops off
    # northern states when only southern placeholders/outlines exist so far.
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def render_status_map(statuses: list[dict], title: str | None = None,
                      figsize: tuple[float, float] = (12, 7),
                      batch_id: str | None = None) -> bytes:
    """Render a CONUS+AK+HI choropleth.

    For states still in progress: filled with the phase color.
    For states with phase == 'done' (and a known batch_id): the state is *replaced*
        with its actual district choropleth so the user sees the real plan as soon as
        it completes (progressive reveal).
    """
    states = _load_state_boundaries()
    by_usps = {s["usps"]: s for s in statuses}

    fig = plt.figure(figsize=figsize, dpi=120)
    ax_main = fig.add_axes([0.0, 0.05, 1.0, 0.92])
    ax_main.set_axis_off()

    # Pre-project state outlines for CONUS.
    conus = states[~states["usps"].isin(["AK", "HI"])].to_crs(CONUS_PROJ)
    ak_states = states[states["usps"] == "AK"].to_crs(AK_PROJ)
    hi_states = states[states["usps"] == "HI"].to_crs(HI_PROJ)

    # Helper: draw one state on a given axis (districts if done, phase color otherwise).
    # NOTE: state_row.geometry is ALREADY in the target projection because we passed
    # already-projected gdfs (conus / ak_states / hi_states) to this function. So we
    # just label the GeoSeries with that projection directly — NO further reprojection.
    def draw_one(ax, state_row, projection, status):
        usps = state_row["usps"]
        phase = (status or {}).get("phase", "?")
        if phase == "done" and batch_id:
            # Try to load and draw actual districts. If anything fails, fall back to phase color.
            try:
                from . import batch as batch_mod
                csv = batch_mod.batch_dir(batch_id) / f"{usps}_assignment.csv"
                if csv.exists():
                    _draw_state_districts(ax, usps, csv, projection=projection)
                    return
            except Exception:
                pass
        # Default: solid fill with phase color.
        color = PHASE_COLORS.get(phase, "#ffffff")
        gpd.GeoSeries([state_row.geometry], crs=projection).plot(
            ax=ax, color=color, edgecolor="#374151", linewidth=0.5)

    # CONUS first.
    for _, srow in conus.iterrows():
        draw_one(ax_main, srow, CONUS_PROJ, by_usps.get(srow["usps"]))

    # State outline overlay (all states, no fill — gives clean borders even where
    # district fills replaced the state).
    conus.plot(ax=ax_main, facecolor="none", edgecolor="#374151", linewidth=0.5)

    # USPS labels.
    for _, row in conus.iterrows():
        try:
            pt = row.geometry.representative_point()
            ax_main.annotate(row["usps"], xy=(pt.x, pt.y),
                             ha="center", va="center", fontsize=7, color="#111")
        except Exception:
            pass

    # AK + HI insets.
    if len(ak_states):
        ax_ak = fig.add_axes([0.0, 0.05, 0.22, 0.32])
        for _, srow in ak_states.iterrows():
            draw_one(ax_ak, srow, AK_PROJ, by_usps.get(srow["usps"]))
        ak_states.plot(ax=ax_ak, facecolor="none", edgecolor="#374151", linewidth=0.4)
        ax_ak.set_axis_off()
        ax_ak.set_title("AK", fontsize=8)
    if len(hi_states):
        ax_hi = fig.add_axes([0.22, 0.05, 0.12, 0.18])
        for _, srow in hi_states.iterrows():
            draw_one(ax_hi, srow, HI_PROJ, by_usps.get(srow["usps"]))
        hi_states.plot(ax=ax_hi, facecolor="none", edgecolor="#374151", linewidth=0.4)
        ax_hi.set_axis_off()
        ax_hi.set_title("HI", fontsize=8)

    # Legend.
    legend_phases = ["queued", "loading", "graph", "districting", "done", "failed",
                     "skipped"]
    handles = [Patch(facecolor=PHASE_COLORS[p], edgecolor="#374151", label=p)
               for p in legend_phases]
    handles.append(Patch(facecolor="#aaa", edgecolor="#374151",
                         label="(done states show actual districts)"))
    # Place legend below the map (out of FL/coastline) using bbox_to_anchor.
    ax_main.legend(handles=handles,
                   loc="upper center", bbox_to_anchor=(0.5, -0.02),
                   fontsize=8, frameon=False, ncol=4)

    if title:
        fig.suptitle(title, fontsize=12, y=0.99)

    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


# ---- result map -------------------------------------------------------------

def render_result_map(batch_id: str, title: str | None = None,
                      figsize: tuple[float, float] = (13, 8)) -> bytes:
    """Render the nationwide result: every state's districts drawn in their colors."""
    from . import batch as batch_mod
    bd = batch_mod.batch_dir(batch_id)
    states = _load_state_boundaries()

    fig = plt.figure(figsize=figsize, dpi=120)
    ax_main = fig.add_axes([0.0, 0.05, 1.0, 0.92])

    # CONUS first.
    for _, srow in states.iterrows():
        usps = srow["usps"]
        if usps in ("AK", "HI"):
            continue
        plan_path = bd / f"{usps}_assignment.csv"
        if not plan_path.exists():
            # state was skipped or failed — draw plain outline.
            gpd.GeoSeries([srow.geometry], crs=states.crs).to_crs(CONUS_PROJ).plot(
                ax=ax_main, color="#e5e7eb", edgecolor="#374151", linewidth=0.5)
            continue
        _draw_state_districts(ax_main, usps, plan_path, projection=CONUS_PROJ)

    # AK / HI insets — same logic.
    ak = states[states["usps"] == "AK"]
    if len(ak):
        ax_ak = fig.add_axes([0.0, 0.05, 0.22, 0.32])
        plan_path = bd / "AK_assignment.csv"
        if plan_path.exists():
            _draw_state_districts(ax_ak, "AK", plan_path, projection=AK_PROJ)
        else:
            ak.to_crs(AK_PROJ).plot(ax=ax_ak, color="#e5e7eb",
                                    edgecolor="#374151", linewidth=0.4)
        ax_ak.set_axis_off()
        ax_ak.set_title("AK", fontsize=8)

    hi = states[states["usps"] == "HI"]
    if len(hi):
        ax_hi = fig.add_axes([0.22, 0.05, 0.12, 0.18])
        plan_path = bd / "HI_assignment.csv"
        if plan_path.exists():
            _draw_state_districts(ax_hi, "HI", plan_path, projection=HI_PROJ)
        else:
            hi.to_crs(HI_PROJ).plot(ax=ax_hi, color="#e5e7eb",
                                    edgecolor="#374151", linewidth=0.4)
        ax_hi.set_axis_off()
        ax_hi.set_title("HI", fontsize=8)

    ax_main.set_axis_off()
    if title:
        fig.suptitle(title, fontsize=12, y=0.99)

    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _draw_state_districts(ax, usps: str, plan_path: Path, *, projection: str):
    """Read the assignment CSV and draw the dissolved districts for one state."""
    from . import loader
    from .graph import _aggregate_to_blockgroups

    # Determine resolution by inspecting GEOID lengths in the CSV (12 for blockgroup, 15 for block).
    df = pd.read_csv(plan_path, names=["GEOID", "district"], dtype={"GEOID": str})
    sample_len = len(df["GEOID"].iloc[0])
    blocks = loader.load_blocks(usps)
    if sample_len == 12:
        units = _aggregate_to_blockgroups(blocks)
    else:
        units = blocks
    units["GEOID"] = units["GEOID"].astype(str)

    merged = units.merge(df, on="GEOID", how="left")
    merged = merged.dropna(subset=["district"])
    merged["district"] = merged["district"].astype(int)
    diss = merged.dissolve(by="district", as_index=False).to_crs(projection)
    n_d = int(diss["district"].max()) + 1
    colors = [PALETTE[i % len(PALETTE)] for i in range(n_d)]
    diss.plot(ax=ax, color=[colors[int(d)] for d in diss["district"]],
              edgecolor="white", linewidth=0.4)
