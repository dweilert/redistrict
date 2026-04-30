"""Paths, state metadata, and configuration."""
from __future__ import annotations
from pathlib import Path

ROOT = Path("/Users/bob/redistrict")
TIGER_DIR = ROOT / "tiger_blocks"
PL_DIR = ROOT / "pl94171"

DATA_DIR = ROOT / "data"
PROCESSED_DIR = DATA_DIR / "processed"
RUNS_DIR = DATA_DIR / "runs"
EXPORTS_DIR = DATA_DIR / "exports"
CACHE_DIR = DATA_DIR / "cache"

for d in (PROCESSED_DIR, RUNS_DIR, EXPORTS_DIR, CACHE_DIR):
    d.mkdir(parents=True, exist_ok=True)

# State FIPS, USPS abbreviation, # of U.S. House seats (2020 apportionment).
STATES: dict[str, dict] = {
    "AL": {"fips": "01", "seats": 7},
    "AK": {"fips": "02", "seats": 1},
    "AZ": {"fips": "04", "seats": 9},
    "AR": {"fips": "05", "seats": 4},
    "CA": {"fips": "06", "seats": 52},
    "CO": {"fips": "08", "seats": 8},
    "CT": {"fips": "09", "seats": 5},
    "DE": {"fips": "10", "seats": 1},
    "DC": {"fips": "11", "seats": 0},
    "FL": {"fips": "12", "seats": 28},
    "GA": {"fips": "13", "seats": 14},
    "HI": {"fips": "15", "seats": 2},
    "ID": {"fips": "16", "seats": 2},
    "IL": {"fips": "17", "seats": 17},
    "IN": {"fips": "18", "seats": 9},
    "IA": {"fips": "19", "seats": 4},
    "KS": {"fips": "20", "seats": 4},
    "KY": {"fips": "21", "seats": 6},
    "LA": {"fips": "22", "seats": 6},
    "ME": {"fips": "23", "seats": 2},
    "MD": {"fips": "24", "seats": 8},
    "MA": {"fips": "25", "seats": 9},
    "MI": {"fips": "26", "seats": 13},
    "MN": {"fips": "27", "seats": 8},
    "MS": {"fips": "28", "seats": 4},
    "MO": {"fips": "29", "seats": 8},
    "MT": {"fips": "30", "seats": 2},
    "NE": {"fips": "31", "seats": 3},
    "NV": {"fips": "32", "seats": 4},
    "NH": {"fips": "33", "seats": 2},
    "NJ": {"fips": "34", "seats": 12},
    "NM": {"fips": "35", "seats": 3},
    "NY": {"fips": "36", "seats": 26},
    "NC": {"fips": "37", "seats": 14},
    "ND": {"fips": "38", "seats": 1},
    "OH": {"fips": "39", "seats": 15},
    "OK": {"fips": "40", "seats": 5},
    "OR": {"fips": "41", "seats": 6},
    "PA": {"fips": "42", "seats": 17},
    "RI": {"fips": "44", "seats": 2},
    "SC": {"fips": "45", "seats": 7},
    "SD": {"fips": "46", "seats": 1},
    "TN": {"fips": "47", "seats": 9},
    "TX": {"fips": "48", "seats": 38},
    "UT": {"fips": "49", "seats": 4},
    "VT": {"fips": "50", "seats": 1},
    "VA": {"fips": "51", "seats": 11},
    "WA": {"fips": "53", "seats": 10},
    "WV": {"fips": "54", "seats": 2},
    "WI": {"fips": "55", "seats": 8},
    "WY": {"fips": "56", "seats": 1},
}


def state_info(usps: str) -> dict:
    s = usps.upper()
    if s not in STATES:
        raise ValueError(f"Unknown state: {usps}")
    return {"usps": s, **STATES[s]}


def tiger_zip(usps: str) -> Path:
    fips = state_info(usps)["fips"]
    return TIGER_DIR / f"tl_2020_{fips}_tabblock20.zip"


def pl_zip(usps: str) -> Path:
    return PL_DIR / f"{usps.lower()}2020.pl.zip"


def blocks_gpkg(usps: str) -> Path:
    return PROCESSED_DIR / f"{usps.lower()}_blocks.gpkg"


def graph_cache(usps: str) -> Path:
    return CACHE_DIR / f"{usps.lower()}_adjacency.pkl"
