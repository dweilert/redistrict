"""FastAPI backend for the redistrict tool.

Exposes the existing Python pipeline (loader, engine, batch runner) as JSON / GeoJSON
endpoints. The React frontend polls these and renders the map client-side.

Run:
    uvicorn api.main:app --reload --port 8000
"""
from __future__ import annotations

import json
import threading
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import geopandas as gpd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from redistrict import batch as batch_mod, config


app = FastAPI(title="redistrict API", version="0.4.0")

# Open CORS for local development; tighten for production deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- helpers -----------------------------------------------------------------

_STATE_BOUNDARIES_CACHE = None


def _state_boundaries() -> gpd.GeoDataFrame:
    """Lazy-load the cached US state outlines (built by us_render once)."""
    global _STATE_BOUNDARIES_CACHE
    if _STATE_BOUNDARIES_CACHE is None:
        from redistrict.us_render import _load_state_boundaries
        _STATE_BOUNDARIES_CACHE = _load_state_boundaries(verbose=False)
    return _STATE_BOUNDARIES_CACHE


def _gdf_to_geojson(gdf: gpd.GeoDataFrame) -> dict:
    """Convert a GeoDataFrame to a plain GeoJSON FeatureCollection dict."""
    return json.loads(gdf.to_json(default=str))


# ---- meta endpoints ----------------------------------------------------------

@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/census-files")
def census_files_status():
    """For each Census download we depend on, report whether a newer version
    is available upstream. Frontend shows a banner if anything is stale."""
    from redistrict import census_downloads
    return census_downloads.check_for_updates()


@app.post("/api/census-files/{key}/download")
def census_files_download(key: str):
    """Force re-download of one Census file."""
    from redistrict import census_downloads
    if key not in census_downloads.FILES:
        raise HTTPException(404, f"Unknown census file key: {key}")
    f = census_downloads.FILES[key]
    census_downloads.download(f, force=True, verbose=False)
    # Invalidate any in-memory caches that depend on this file.
    if key == "state_outlines":
        try:
            from redistrict import us_render
            us_render._STATE_BOUNDARIES_CACHE = None
        except Exception:
            pass
        global _STATE_BOUNDARIES_CACHE
        _STATE_BOUNDARIES_CACHE = None
    elif key == "places":
        from redistrict import places
        places._PLACES_CACHE = None
        places._PLACE_POP_CACHE.clear()
    elif key == "cd119":
        from redistrict import cd_official
        cd_official._OFFICIAL_CACHE = None
        cd_official._SCORECARD_CACHE.clear()
    return {"downloaded": True, "key": key}


@app.get("/api/states")
def list_states():
    """Static metadata for every state we know about."""
    return [
        {"usps": k, "name": v["name"], "fips": v["fips"], "seats": v["seats"]}
        for k, v in config.STATES.items()
    ]


@app.get("/api/states.geojson")
def states_geojson():
    """Per-state outline GeoJSON for the live map (CB 500k file)."""
    gdf = _state_boundaries()
    # Reproject to EPSG:5070 (Albers Equal Area) so the frontend can display CONUS
    # without doing the projection itself. AK and HI come back in lat/lon and the
    # frontend places them in insets.
    return _gdf_to_geojson(gdf)


# ---- batch endpoints ---------------------------------------------------------

@app.get("/api/batches")
def list_batches():
    root = config.DATA_DIR / "batches"
    if not root.exists():
        return []
    out = []
    for p in sorted(root.iterdir(), reverse=True):
        manifest_p = p / "manifest.json"
        if not manifest_p.exists():
            continue
        try:
            m = json.loads(manifest_p.read_text())
        except json.JSONDecodeError:
            continue
        s = batch_mod.batch_summary(m["batch_id"])
        out.append({**m, "summary": s})
    return out


@app.get("/api/batches/{batch_id}/status")
def batch_status(batch_id: str):
    bd = batch_mod.batch_dir(batch_id)
    if not (bd / "manifest.json").exists():
        raise HTTPException(404, f"Batch {batch_id} not found")
    manifest = json.loads((bd / "manifest.json").read_text())
    statuses = batch_mod.read_all_status(batch_id)
    summary = batch_mod.batch_summary(batch_id)
    return {"manifest": manifest, "summary": summary, "statuses": statuses}


_DISTRICT_GEOJSON_CACHE: dict[tuple[str, str], dict] = {}


@app.get("/api/states/{usps}/cd119.geojson")
def state_cd119(usps: str):
    """Officially-adopted current (119th Congress) districts for one state.

    Comes from the Census CB cb_2024_us_cd119 file. Geometries are simplified
    server-side for fast browser rendering."""
    from redistrict import cd_official
    gdf = cd_official.load_state_districts(usps)
    if len(gdf) == 0:
        raise HTTPException(404, f"No CD119 entry for {usps}")
    gdf = gdf.copy()
    gdf["geometry"] = gdf.geometry.simplify(0.005, preserve_topology=True)
    # Convert CD119FP to 0-indexed so DistrictMap labels render as "1, 2, 3" via
    # the standard `did + 1` formula (matches our engine output).
    gdf["district"] = gdf["district"].apply(
        lambda v: int(v) - 1 if v is not None else None
    )
    gdf = gdf.dropna(subset=["district"])
    keep = gdf[["district", "NAMELSAD", "geometry"]].copy()
    return _gdf_to_geojson(keep)


@app.get("/api/states/{usps}/cd119/districts/{district}/cities")
def cd119_district_cities(usps: str, district: int):
    """Cities/places inside one district of the official 119th-Congress plan.

    The ``district`` path parameter is 0-indexed (matching our engine output);
    we add 1 to convert back to the source CD119FP value.
    """
    from redistrict import cd_official, places
    state_districts = cd_official.load_state_districts(usps)
    target_cd = int(district) + 1
    matching = state_districts[
        state_districts["district"].apply(
            lambda v: v is not None and int(v) == target_cd
        )
    ]
    if len(matching) == 0:
        raise HTTPException(404, f"No CD119 district {district} for {usps}")
    poly = matching.geometry.iloc[0]
    statefp = config.STATES.get(usps, {}).get("fips", "")
    cities = places.cities_in_polygon(poly, statefp, usps)
    return {"usps": usps, "district": int(district), "cities": cities}


@app.get("/api/states/{usps}/cd119/scorecard")
def state_cd119_scorecard(usps: str):
    """Same-shape scorecard as our engine output but computed against the
    official current plan. Useful for side-by-side comparisons."""
    from redistrict import cd_official
    return cd_official.official_scorecard(usps)


@app.get("/api/batches/{batch_id}/states/{usps}/districts/{district}/cities")
def district_cities(batch_id: str, usps: str, district: int):
    """Return list of Census places (cities/CDPs) whose representative point falls
    inside the given district's polygon. Sorted by land area desc."""
    from redistrict import places
    bd = batch_mod.batch_dir(batch_id)
    gpkg = bd / f"{usps}_districts.gpkg"
    if not gpkg.exists():
        raise HTTPException(404, f"No districts file for {usps} in batch {batch_id}")
    gdf = gpd.read_file(gpkg)
    matching = gdf[gdf["district"].astype(int) == int(district)]
    if len(matching) == 0:
        raise HTTPException(404, f"No district {district} in {usps}")
    poly = matching.geometry.iloc[0]
    statefp = config.STATES.get(usps, {}).get("fips", "")
    cities = places.cities_in_polygon(poly, statefp, usps)
    return {"usps": usps, "district": int(district), "cities": cities}


@app.get("/api/batches/{batch_id}/states/{usps}/plan")
def state_plan(batch_id: str, usps: str):
    bd = batch_mod.batch_dir(batch_id)
    plan_p = bd / f"{usps}_plan.json"
    if not plan_p.exists():
        raise HTTPException(404, f"No plan file for {usps} in batch {batch_id}")
    return json.loads(plan_p.read_text())


@app.get("/api/batches/{batch_id}/states/{usps}/districts.geojson")
def state_districts_geojson(batch_id: str, usps: str):
    """Per-state district choropleth GeoJSON, simplified for client rendering.

    The raw dissolved geometries can be 5–15 MB per state (CA, TX). For an SVG choropleth
    rendered at ~1000 px wide, a 500m simplification tolerance is invisible and shrinks
    the response by 10–100×. We cache the simplified result in memory.
    """
    key = (batch_id, usps)
    if key in _DISTRICT_GEOJSON_CACHE:
        return _DISTRICT_GEOJSON_CACHE[key]
    bd = batch_mod.batch_dir(batch_id)
    gpkg = bd / f"{usps}_districts.gpkg"
    if not gpkg.exists():
        raise HTTPException(404, f"No districts file for {usps} in batch {batch_id}")
    gdf = gpd.read_file(gpkg)
    # Simplify to ~500m tolerance in degrees (NAD83 lat/lon).
    gdf["geometry"] = gdf.geometry.simplify(0.005, preserve_topology=True)
    payload = _gdf_to_geojson(gdf)
    _DISTRICT_GEOJSON_CACHE[key] = payload
    return payload


# ---- batch control ----------------------------------------------------------

class CreateBatch(BaseModel):
    unit: str = "blockgroup"
    epsilon: float = 0.01
    chain_length: int = 500
    seed_strategy: str = "tree"
    weights: dict[str, float] | None = None
    random_seed: int | None = None
    states: list[str] | None = None


class WorkerControl(BaseModel):
    workers: int = 6


@app.post("/api/batches")
def create_batch(req: CreateBatch):
    manifest = batch_mod.create_batch(
        states=req.states,
        unit=req.unit,
        seed_strategy=req.seed_strategy,
        epsilon=req.epsilon,
        chain_length=req.chain_length,
        weights=req.weights,
        random_seed_base=req.random_seed,
    )
    return manifest


@app.post("/api/batches/{batch_id}/start")
def start_batch(batch_id: str, req: WorkerControl):
    """Spawn workers in a background thread (workers themselves are subprocesses)."""
    bd = batch_mod.batch_dir(batch_id)
    if not (bd / "manifest.json").exists():
        raise HTTPException(404, f"Batch {batch_id} not found")

    def _run():
        batch_mod.run_batch(batch_id, workers=req.workers)

    threading.Thread(target=_run, daemon=True).start()
    return {"started": True, "batch_id": batch_id, "workers": req.workers}


# ---- single-plan endpoints --------------------------------------------------

# In-memory registry of single-plan jobs. Localhost-only single-process server.
_SINGLE_PLANS: dict[str, dict] = {}


class SinglePlanRequest(BaseModel):
    usps: str
    unit: str = "blockgroup"
    epsilon: float = 0.01
    chain_length: int = 500
    seed_strategy: str = "tree"
    weights: dict[str, float] | None = None
    random_seed: int | None = None


@app.post("/api/single-plan")
def create_single_plan(req: SinglePlanRequest):
    """Kick off generation of a single-state plan in a background thread.
    Returns a plan_id immediately so the client can poll for progress."""
    import threading
    import uuid as _uuid
    from redistrict import config as _cfg, engine, graph as graph_mod

    if req.usps not in _cfg.STATES:
        raise HTTPException(400, f"Unknown state: {req.usps}")
    seats = _cfg.STATES[req.usps]["seats"]
    if seats < 2:
        raise HTTPException(400, f"{req.usps} has {seats} House seat(s); no districting needed")

    plan_id = _uuid.uuid4().hex[:12]
    _SINGLE_PLANS[plan_id] = {
        "plan_id": plan_id,
        "phase": "queued",
        "usps": req.usps,
        "n_districts": seats,
        "request": req.model_dump(),
        "step": 0,
        "best_score": None,
        "best_max_dev_pct": None,
        "best_polsby_popper_mean": None,
        "result": None,
        "error": None,
    }

    def _run():
        try:
            _SINGLE_PLANS[plan_id]["phase"] = "loading"
            g = graph_mod.build_graph(req.usps, unit=req.unit)
            _SINGLE_PLANS[plan_id]["phase"] = "districting"

            # Snapshot the current partition every PREVIEW_STRIDE steps so the live
            # preview keeps changing visibly even when the chain isn't finding new
            # bests. (ReCom only improves the best every N proposals; without these
            # interim snapshots the preview map looks frozen for long stretches.)
            PREVIEW_STRIDE = 25
            best = {"score": float("inf")}
            def _cb(partition, sc):
                step = _SINGLE_PLANS[plan_id]["step"] + 1
                _SINGLE_PLANS[plan_id]["step"] = step
                is_new_best = sc.score < best["score"]
                if is_new_best:
                    best["score"] = sc.score
                    _SINGLE_PLANS[plan_id]["best_score"] = float(sc.score)
                    _SINGLE_PLANS[plan_id]["best_max_dev_pct"] = float(sc.max_abs_deviation_pct)
                    _SINGLE_PLANS[plan_id]["best_polsby_popper_mean"] = float(sc.polsby_popper_mean)
                # Update the preview snapshot if this is a new best, on a stride
                # tick, or on the very first step (so the user sees something fast).
                if is_new_best or step == 1 or step % PREVIEW_STRIDE == 0:
                    _SINGLE_PLANS[plan_id]["best_assignment"] = {
                        partition.graph.nodes[n]["GEOID"]: int(partition.assignment[n])
                        for n in partition.graph.nodes
                    }
                    _SINGLE_PLANS[plan_id]["preview_step"] = step

            plan = engine.generate_plan(
                g, n_districts=seats,
                seed_strategy=req.seed_strategy,
                epsilon=req.epsilon,
                chain_length=req.chain_length,
                weights=req.weights,
                random_seed=req.random_seed,
                progress_cb=_cb,
            )
            _SINGLE_PLANS[plan_id]["phase"] = "done"
            _SINGLE_PLANS[plan_id]["result"] = {
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
                "assignment": plan.assignment,
            }
        except Exception as e:
            import traceback as _tb
            _SINGLE_PLANS[plan_id]["phase"] = "failed"
            _SINGLE_PLANS[plan_id]["error"] = str(e)
            _SINGLE_PLANS[plan_id]["traceback"] = _tb.format_exc()

    threading.Thread(target=_run, daemon=True).start()
    return {"plan_id": plan_id}


@app.get("/api/single-plan/{plan_id}/status")
def single_plan_status(plan_id: str):
    if plan_id not in _SINGLE_PLANS:
        raise HTTPException(404, f"Unknown plan: {plan_id}")
    s = _SINGLE_PLANS[plan_id]
    # Only return the lightweight progress fields here, not the (potentially large)
    # full result + assignment.
    return {k: v for k, v in s.items() if k not in ("result", "request")}


@app.get("/api/single-plan/{plan_id}/result")
def single_plan_result(plan_id: str):
    if plan_id not in _SINGLE_PLANS:
        raise HTTPException(404, f"Unknown plan: {plan_id}")
    s = _SINGLE_PLANS[plan_id]
    if s["phase"] != "done" or not s.get("result"):
        raise HTTPException(409, f"Plan {plan_id} not done yet (phase={s['phase']})")
    return s["result"]


@app.get("/api/single-plan/{plan_id}/districts.geojson")
def single_plan_districts(plan_id: str):
    """Dissolved district polygons for a completed single-plan run."""
    if plan_id not in _SINGLE_PLANS:
        raise HTTPException(404, f"Unknown plan: {plan_id}")
    s = _SINGLE_PLANS[plan_id]
    if s["phase"] != "done" or not s.get("result"):
        raise HTTPException(409, f"Plan {plan_id} not done yet")
    from redistrict import loader
    from redistrict.graph import _aggregate_to_blockgroups
    import pandas as pd
    res = s["result"]
    blocks = loader.load_blocks(res["usps"])
    units_gdf = (_aggregate_to_blockgroups(blocks)
                 if res["unit"] == "blockgroup" else blocks)
    df = pd.DataFrame.from_dict(res["assignment"], orient="index",
                                columns=["district"])
    df.index.name = "GEOID"
    df = df.reset_index()
    df["GEOID"] = df["GEOID"].astype(str)
    units_gdf = units_gdf.copy()
    units_gdf["GEOID"] = units_gdf["GEOID"].astype(str)
    merged = units_gdf.merge(df, on="GEOID", how="inner")
    merged["district"] = merged["district"].astype(int)
    diss = merged.dissolve(by="district", as_index=False)[["district", "geometry"]]
    diss["geometry"] = diss.geometry.simplify(0.005, preserve_topology=True)
    return _gdf_to_geojson(diss)


# In-memory cache of preview districts: (plan_id, preview_step) -> geojson.
_PREVIEW_CACHE: dict[tuple[str, int], dict] = {}


@app.get("/api/single-plan/{plan_id}/preview-districts.geojson")
def single_plan_preview(plan_id: str):
    """Live evolving district map for a running plan.

    Reads the current best assignment captured by the chain's progress_cb,
    dissolves units to district polygons, and returns simplified GeoJSON. The
    result is keyed on the current preview_step so the frontend's TanStack Query
    cache changes when (and only when) a new best plan has been found.
    """
    if plan_id not in _SINGLE_PLANS:
        raise HTTPException(404, f"Unknown plan: {plan_id}")
    s = _SINGLE_PLANS[plan_id]
    assignment = s.get("best_assignment")
    step = s.get("preview_step", 0)
    if not assignment:
        raise HTTPException(409, "No preview yet")
    cache_key = (plan_id, step)
    if cache_key in _PREVIEW_CACHE:
        return _PREVIEW_CACHE[cache_key]

    from redistrict import loader
    from redistrict.graph import _aggregate_to_blockgroups
    import pandas as pd

    req = s["request"]
    blocks = loader.load_blocks(req["usps"])
    units_gdf = (_aggregate_to_blockgroups(blocks)
                 if req["unit"] == "blockgroup" else blocks)
    df = pd.DataFrame.from_dict(assignment, orient="index", columns=["district"])
    df.index.name = "GEOID"
    df = df.reset_index()
    df["GEOID"] = df["GEOID"].astype(str)
    units_gdf = units_gdf.copy()
    units_gdf["GEOID"] = units_gdf["GEOID"].astype(str)
    merged = units_gdf.merge(df, on="GEOID", how="inner")
    merged["district"] = merged["district"].astype(int)
    diss = merged.dissolve(by="district", as_index=False)[["district", "geometry"]]
    diss["geometry"] = diss.geometry.simplify(0.01, preserve_topology=True)
    payload = _gdf_to_geojson(diss)
    payload["_step"] = step
    # Keep at most a couple of preview cache entries per plan to bound memory.
    _PREVIEW_CACHE[cache_key] = payload
    if len(_PREVIEW_CACHE) > 16:
        oldest = sorted(_PREVIEW_CACHE.keys(), key=lambda k: k[1])[0]
        _PREVIEW_CACHE.pop(oldest, None)
    return payload


@app.get("/api/single-plan/{plan_id}/districts/{district}/cities")
def single_plan_cities(plan_id: str, district: int):
    """Cities/places inside one district of a single-plan run."""
    from redistrict import places, loader
    from redistrict.graph import _aggregate_to_blockgroups
    import pandas as pd
    if plan_id not in _SINGLE_PLANS:
        raise HTTPException(404, f"Unknown plan: {plan_id}")
    s = _SINGLE_PLANS[plan_id]
    if s["phase"] != "done" or not s.get("result"):
        raise HTTPException(409, f"Plan {plan_id} not done yet")
    res = s["result"]
    blocks = loader.load_blocks(res["usps"])
    units_gdf = (_aggregate_to_blockgroups(blocks)
                 if res["unit"] == "blockgroup" else blocks)
    df = pd.DataFrame.from_dict(res["assignment"], orient="index",
                                columns=["district"])
    df.index.name = "GEOID"
    df = df.reset_index()
    df["GEOID"] = df["GEOID"].astype(str)
    units_gdf = units_gdf.copy()
    units_gdf["GEOID"] = units_gdf["GEOID"].astype(str)
    merged = units_gdf.merge(df, on="GEOID", how="inner")
    merged = merged[merged["district"].astype(int) == int(district)]
    if len(merged) == 0:
        raise HTTPException(404, f"No district {district} in plan {plan_id}")
    poly = merged.dissolve().geometry.iloc[0]
    statefp = config.STATES.get(res["usps"], {}).get("fips", "")
    cities = places.cities_in_polygon(poly, statefp, res["usps"])
    return {"plan_id": plan_id, "district": int(district), "cities": cities}


@app.get("/api/single-plan/{plan_id}/pdf")
def single_plan_pdf(plan_id: str):
    """Stream the PDF (with embedded provenance) for a completed plan."""
    from fastapi.responses import FileResponse
    if plan_id not in _SINGLE_PLANS:
        raise HTTPException(404, f"Unknown plan: {plan_id}")
    s = _SINGLE_PLANS[plan_id]
    if s["phase"] != "done" or not s.get("result"):
        raise HTTPException(409, f"Plan {plan_id} not done yet")
    res = s["result"]
    from redistrict import pdf_export, loader
    from redistrict.graph import _aggregate_to_blockgroups
    from redistrict.engine import PlanResult

    plan = PlanResult(
        plan_id=res["plan_id"],
        usps=res["usps"],
        unit=res["unit"],
        n_districts=res["n_districts"],
        seed_strategy=res["seed_strategy"],
        epsilon=res["epsilon"],
        chain_length=res["chain_length"],
        weights=res["weights"],
        random_seed=res["random_seed"],
        elapsed_sec=res["elapsed_sec"],
        accepted_steps=res["accepted_steps"],
        assignment=res["assignment"],
        scorecard=res["scorecard"],
    )
    blocks = loader.load_blocks(res["usps"])
    units_gdf = (_aggregate_to_blockgroups(blocks)
                 if res["unit"] == "blockgroup" else blocks)
    out = pdf_export.export_pdf(plan, units_gdf)
    return FileResponse(out, media_type="application/pdf",
                        filename=out.name)


@app.post("/api/batches/{batch_id}/retry")
def retry_failed(batch_id: str, req: WorkerControl):
    """Retry any state with phase=failed. Force-rebuilds graph caches."""
    bd = batch_mod.batch_dir(batch_id)
    if not (bd / "manifest.json").exists():
        raise HTTPException(404, f"Batch {batch_id} not found")
    manifest = json.loads((bd / "manifest.json").read_text())

    failed = []
    for f in sorted(bd.glob("*_status.json")):
        s = json.loads(f.read_text())
        if s.get("phase") == "failed":
            failed.append(s["usps"])
    if not failed:
        return {"started": False, "reason": "no failed states"}

    base_seed = manifest.get("random_seed_base", 0)

    def _retry():
        # Force rebuild stale graph caches.
        for usps in failed:
            cache_p = (config.CACHE_DIR
                       / f"{usps.lower()}_{manifest['unit']}_graph.pkl")
            if cache_p.exists():
                cache_p.unlink()
            batch_mod.write_status(batch_id, usps, phase="queued")
        args_list = [
            {
                "batch_id": batch_id,
                "usps": u,
                "unit": manifest["unit"],
                "seed_strategy": manifest["seed_strategy"],
                "epsilon": manifest["epsilon"],
                "chain_length": manifest["chain_length"],
                "weights": manifest.get("weights") or {},
                "random_seed": (base_seed + (j + 5000) * 1009) & 0xFFFFFFFF,
            }
            for j, u in enumerate(failed)
        ]
        with ProcessPoolExecutor(max_workers=min(req.workers, len(args_list))) as ex:
            list(ex.map(batch_mod._run_state, args_list))

    threading.Thread(target=_retry, daemon=True).start()
    return {"started": True, "batch_id": batch_id, "states": failed}
