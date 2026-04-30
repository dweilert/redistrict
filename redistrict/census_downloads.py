"""Cached Census downloads with update detection.

Each downloaded zip stores a sidecar ``.meta.json`` recording the HTTP
``Last-Modified`` header at download time. ``check_for_updates()`` does a HEAD
request against every tracked URL and compares; the API exposes the result so
the frontend can show "newer version available — re-download" banners.
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from . import config


@dataclass
class CensusFile:
    key: str
    url: str
    label: str           # human-friendly name
    why: str             # one-line explanation
    cache_filename: str

    @property
    def cache_path(self) -> Path:
        return config.CACHE_DIR / self.cache_filename

    @property
    def meta_path(self) -> Path:
        return self.cache_path.with_suffix(self.cache_path.suffix + ".meta.json")


# Registry of every Census download we depend on.
FILES: dict[str, CensusFile] = {
    "state_outlines": CensusFile(
        key="state_outlines",
        url=("https://www2.census.gov/geo/tiger/GENZ2020/shp/"
             "cb_2020_us_state_500k.zip"),
        label="U.S. state outlines (CB 2020 500k)",
        why="Drives the live nationwide map.",
        cache_filename="cb_2020_us_state_500k.zip",
    ),
    "places": CensusFile(
        key="places",
        url=("https://www2.census.gov/geo/tiger/GENZ2020/shp/"
             "cb_2020_us_place_500k.zip"),
        label="U.S. cities & places (CB 2020 500k)",
        why="Used to list cities inside each district.",
        cache_filename="cb_2020_us_place_500k.zip",
    ),
    "cd119": CensusFile(
        key="cd119",
        url=("https://www2.census.gov/geo/tiger/GENZ2024/shp/"
             "cb_2024_us_cd119_500k.zip"),
        label="119th-Congress districts (current)",
        why="Each state's officially-adopted current U.S. House districts.",
        cache_filename="cb_2024_us_cd119_500k.zip",
    ),
}


def _read_meta(f: CensusFile) -> dict:
    if f.meta_path.exists():
        try:
            return json.loads(f.meta_path.read_text())
        except json.JSONDecodeError:
            pass
    return {}


def _write_meta(f: CensusFile, last_modified: str | None) -> None:
    f.meta_path.write_text(json.dumps({
        "last_modified": last_modified,
        "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }, indent=2))


def download(f: CensusFile, force: bool = False, verbose: bool = True) -> Path:
    """Download (if missing or forced) and store the Last-Modified header."""
    if f.cache_path.exists() and not force:
        return f.cache_path
    if verbose:
        print(f"Downloading {f.label} → {f.cache_path}")
    req = urllib.request.Request(f.url, headers={"User-Agent": "redistrict/0.4"})
    with urllib.request.urlopen(req) as resp:
        last_modified = resp.headers.get("Last-Modified")
        data = resp.read()
    f.cache_path.write_bytes(data)
    _write_meta(f, last_modified)
    return f.cache_path


def remote_last_modified(f: CensusFile, timeout: float = 10.0) -> str | None:
    """HEAD request the remote URL; return the Last-Modified header or None."""
    req = urllib.request.Request(
        f.url, method="HEAD", headers={"User-Agent": "redistrict/0.4"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.headers.get("Last-Modified")
    except Exception:
        return None


def _parse(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return parsedate_to_datetime(s).astimezone(timezone.utc)
    except Exception:
        return None


def check_for_updates(timeout: float = 10.0) -> list[dict]:
    """Compare every cached file against the remote.

    Returns list of dicts with keys: key, label, why, url, present (bool),
    local_last_modified, remote_last_modified, update_available (bool).
    """
    out = []
    for f in FILES.values():
        meta = _read_meta(f)
        local_lm = meta.get("last_modified")
        present = f.cache_path.exists()
        remote_lm = remote_last_modified(f, timeout=timeout)
        ld = _parse(local_lm)
        rd = _parse(remote_lm)
        update_available = (
            present and ld is not None and rd is not None and rd > ld
        ) or (not present)
        out.append({
            "key": f.key,
            "label": f.label,
            "why": f.why,
            "url": f.url,
            "present": present,
            "local_last_modified": local_lm,
            "remote_last_modified": remote_lm,
            "update_available": update_available,
            "downloaded_at": meta.get("downloaded_at"),
        })
    return out
