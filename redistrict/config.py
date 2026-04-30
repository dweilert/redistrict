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

# State FIPS, USPS abbreviation, full name, # of U.S. House seats (2020 apportionment).
STATES: dict[str, dict] = {
    "AL": {"fips": "01", "name": "Alabama", "seats": 7},
    "AK": {"fips": "02", "name": "Alaska", "seats": 1},
    "AZ": {"fips": "04", "name": "Arizona", "seats": 9},
    "AR": {"fips": "05", "name": "Arkansas", "seats": 4},
    "CA": {"fips": "06", "name": "California", "seats": 52},
    "CO": {"fips": "08", "name": "Colorado", "seats": 8},
    "CT": {"fips": "09", "name": "Connecticut", "seats": 5},
    "DE": {"fips": "10", "name": "Delaware", "seats": 1},
    "DC": {"fips": "11", "name": "District of Columbia", "seats": 0},
    "FL": {"fips": "12", "name": "Florida", "seats": 28},
    "GA": {"fips": "13", "name": "Georgia", "seats": 14},
    "HI": {"fips": "15", "name": "Hawaii", "seats": 2},
    "ID": {"fips": "16", "name": "Idaho", "seats": 2},
    "IL": {"fips": "17", "name": "Illinois", "seats": 17},
    "IN": {"fips": "18", "name": "Indiana", "seats": 9},
    "IA": {"fips": "19", "name": "Iowa", "seats": 4},
    "KS": {"fips": "20", "name": "Kansas", "seats": 4},
    "KY": {"fips": "21", "name": "Kentucky", "seats": 6},
    "LA": {"fips": "22", "name": "Louisiana", "seats": 6},
    "ME": {"fips": "23", "name": "Maine", "seats": 2},
    "MD": {"fips": "24", "name": "Maryland", "seats": 8},
    "MA": {"fips": "25", "name": "Massachusetts", "seats": 9},
    "MI": {"fips": "26", "name": "Michigan", "seats": 13},
    "MN": {"fips": "27", "name": "Minnesota", "seats": 8},
    "MS": {"fips": "28", "name": "Mississippi", "seats": 4},
    "MO": {"fips": "29", "name": "Missouri", "seats": 8},
    "MT": {"fips": "30", "name": "Montana", "seats": 2},
    "NE": {"fips": "31", "name": "Nebraska", "seats": 3},
    "NV": {"fips": "32", "name": "Nevada", "seats": 4},
    "NH": {"fips": "33", "name": "New Hampshire", "seats": 2},
    "NJ": {"fips": "34", "name": "New Jersey", "seats": 12},
    "NM": {"fips": "35", "name": "New Mexico", "seats": 3},
    "NY": {"fips": "36", "name": "New York", "seats": 26},
    "NC": {"fips": "37", "name": "North Carolina", "seats": 14},
    "ND": {"fips": "38", "name": "North Dakota", "seats": 1},
    "OH": {"fips": "39", "name": "Ohio", "seats": 15},
    "OK": {"fips": "40", "name": "Oklahoma", "seats": 5},
    "OR": {"fips": "41", "name": "Oregon", "seats": 6},
    "PA": {"fips": "42", "name": "Pennsylvania", "seats": 17},
    "RI": {"fips": "44", "name": "Rhode Island", "seats": 2},
    "SC": {"fips": "45", "name": "South Carolina", "seats": 7},
    "SD": {"fips": "46", "name": "South Dakota", "seats": 1},
    "TN": {"fips": "47", "name": "Tennessee", "seats": 9},
    "TX": {"fips": "48", "name": "Texas", "seats": 38},
    "UT": {"fips": "49", "name": "Utah", "seats": 4},
    "VT": {"fips": "50", "name": "Vermont", "seats": 1},
    "VA": {"fips": "51", "name": "Virginia", "seats": 11},
    "WA": {"fips": "53", "name": "Washington", "seats": 10},
    "WV": {"fips": "54", "name": "West Virginia", "seats": 2},
    "WI": {"fips": "55", "name": "Wisconsin", "seats": 8},
    "WY": {"fips": "56", "name": "Wyoming", "seats": 1},
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
