"""Per-state plan catalog.

Each state has a directory ``data/catalog/<USPS>/`` containing:

    <plan_uuid>.json    one JSON file per saved plan (full assignment + scorecard)
    default.json        a tiny pointer naming which entry is the default

Two source kinds for entries:

    "nationwide"  auto-saved when a batch worker finishes
    "single"      explicitly saved by the user from a single-state run

Plus one always-available virtual entry, ``census-current`` — returns the
state's official 119th-Congress districts. The default may name a real plan
uuid OR the literal string ``"census-current"``; if no default.json exists,
``census-current`` is implied.
"""
from __future__ import annotations

import json
import shutil
import uuid as _uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config

CENSUS_CURRENT = "census-current"


@dataclass
class CatalogEntry:
    plan_uuid: str
    usps: str
    name: str
    source: str           # 'nationwide' | 'single' | 'census'
    batch_id: str | None
    parameters: dict
    scorecard: dict
    assignment: dict      # GEOID -> district id
    created_at: str

    def to_dict(self) -> dict:
        return asdict(self)


def state_dir(usps: str) -> Path:
    p = config.DATA_DIR / "catalog" / usps.upper()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _entry_path(usps: str, plan_uuid: str) -> Path:
    return state_dir(usps) / f"{plan_uuid}.json"


def _default_path(usps: str) -> Path:
    return state_dir(usps) / "default.json"


# ---- read --------------------------------------------------------------------

def list_entries(usps: str) -> list[dict]:
    """List the catalog entries for a state.

    Returns a list of summary dicts (no full assignment, for size). The
    always-on ``census-current`` virtual entry is included first.
    """
    out: list[dict] = [_census_summary(usps)]
    sd = state_dir(usps)
    for p in sorted(sd.glob("*.json")):
        if p.name == "default.json":
            continue
        try:
            data = json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
        # Strip the heavy assignment dict for list view; client fetches it on demand.
        out.append(_strip_for_list(data))
    return out


def get_entry(usps: str, plan_uuid: str) -> CatalogEntry | None:
    if plan_uuid == CENSUS_CURRENT:
        return _build_census_entry(usps)
    p = _entry_path(usps, plan_uuid)
    if not p.exists():
        return None
    return CatalogEntry(**json.loads(p.read_text()))


def get_default_uuid(usps: str) -> str:
    p = _default_path(usps)
    if not p.exists():
        return CENSUS_CURRENT
    try:
        return json.loads(p.read_text()).get("plan_uuid", CENSUS_CURRENT)
    except json.JSONDecodeError:
        return CENSUS_CURRENT


# ---- write -------------------------------------------------------------------

def save_entry(usps: str, *, name: str, source: str,
               parameters: dict, scorecard: dict, assignment: dict,
               batch_id: str | None = None) -> CatalogEntry:
    """Persist a new catalog entry. Generates a uuid; never overwrites."""
    plan_uuid = _uuid.uuid4().hex[:12]
    e = CatalogEntry(
        plan_uuid=plan_uuid,
        usps=usps.upper(),
        name=name,
        source=source,
        batch_id=batch_id,
        parameters=parameters,
        scorecard=scorecard,
        assignment=assignment,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    _entry_path(usps, plan_uuid).write_text(json.dumps(e.to_dict(), indent=2))
    return e


def delete_entry(usps: str, plan_uuid: str) -> bool:
    if plan_uuid == CENSUS_CURRENT:
        return False  # virtual; can't delete
    p = _entry_path(usps, plan_uuid)
    if not p.exists():
        return False
    # If this was the default, fall back to census-current.
    if get_default_uuid(usps) == plan_uuid:
        set_default(usps, CENSUS_CURRENT)
    p.unlink()
    return True


def set_default(usps: str, plan_uuid: str) -> None:
    """Mark `plan_uuid` (or the census-current sentinel) as the state's default."""
    if plan_uuid != CENSUS_CURRENT and not _entry_path(usps, plan_uuid).exists():
        raise FileNotFoundError(f"No catalog entry {plan_uuid} for {usps}")
    _default_path(usps).write_text(json.dumps({"plan_uuid": plan_uuid}, indent=2))


# ---- helpers -----------------------------------------------------------------

def _strip_for_list(data: dict) -> dict:
    """Drop heavy fields for list views; keep summary metadata."""
    out = {k: v for k, v in data.items() if k != "assignment"}
    out["has_assignment"] = bool(data.get("assignment"))
    return out


def _census_summary(usps: str) -> dict:
    """Summary dict for the always-on Census current entry."""
    is_default = get_default_uuid(usps) == CENSUS_CURRENT
    sc = _safe_census_scorecard(usps)
    return {
        "plan_uuid": CENSUS_CURRENT,
        "usps": usps.upper(),
        "name": "Census 119th Congress (current)",
        "source": "census",
        "batch_id": None,
        "parameters": {},
        "scorecard": sc,
        "created_at": None,
        "is_default": is_default,
    }


def _safe_census_scorecard(usps: str) -> dict:
    try:
        from . import cd_official
        return cd_official.official_scorecard(usps)
    except Exception:
        return {"available": False}


def _build_census_entry(usps: str) -> CatalogEntry:
    """A pseudo CatalogEntry backed by the Census file. assignment is empty
    because the cd119 source has district polygons, not block-level assignments;
    callers that need the geometry should use the CD119 API directly."""
    sc = _safe_census_scorecard(usps)
    return CatalogEntry(
        plan_uuid=CENSUS_CURRENT,
        usps=usps.upper(),
        name="Census 119th Congress (current)",
        source="census",
        batch_id=None,
        parameters={},
        scorecard=sc,
        assignment={},
        created_at=None or datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


# ---- bundled views for the nationwide map ------------------------------------

def composed_default_summary() -> dict:
    """Return per-state default plan_uuid + how many states are tuned (i.e. their
    default is NOT census-current)."""
    out: dict[str, str] = {}
    tuned = 0
    for usps in config.STATES:
        d = get_default_uuid(usps)
        out[usps] = d
        if d != CENSUS_CURRENT:
            tuned += 1
    return {"defaults": out, "tuned_count": tuned, "total_states": len(config.STATES)}
