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
