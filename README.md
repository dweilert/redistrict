# redistrict

Population-only U.S. congressional redistricting plans, generated from 2020 Census P.L.
94-171 data and TIGER/Line block geometry. The only attribute used is total population
(`P1_001N`). No race, party, income, or other demographics enter the algorithm.

## What's here

- **Engine** — pluggable seed strategies + growth rules + a weighted scorecard. The same
  engine produces "legal" plans (population deviation as a hard constraint) and
  "exploratory" plans (population as one weight among many).
- **Streamlit viewer** — choose a state, set weights with sliders, generate a plan, view
  the map and per-district scorecard, export a self-contained PDF.
- **PDF export with embedded provenance** — every PDF carries the full plan
  (block→district assignment) plus all run parameters in its metadata. The viewer can
  re-render the map directly from the PDF, with no other files needed.

## Layout

```
redistrict/
  config.py        paths, FIPS table, seat counts
  loader.py        PL 94-171 + TIGER → joined GeoPackage
  graph.py         adjacency graph builder + cache
  scoring.py       weighted scorecard
  engine.py        seeds, growth, repair, top-level generate_plan()
  pdf_export.py    ReportLab PDF + provenance embed/read
  persistence.py   plan save/load + assignment encode/decode
  render.py        map rendering (matplotlib)
app/
  streamlit_app.py UI
scripts/
  prepare_state.py CLI: build blocks gpkg + adjacency cache for one state
  test_iowa.py     end-to-end smoke test
```

## Setup

```bash
conda env create -f environment.yml
conda activate redistrict

# point the loader at raw data:
#   /Users/bob/redistrict/pl94171/{state}2020.pl.zip       (PL 94-171, per state)
#   /Users/bob/redistrict/tiger_blocks/tl_2020_{fips}_tabblock20.zip  (TIGER blocks)
# (paths in redistrict/config.py)

python scripts/prepare_state.py IA       # one-time data prep, ~minutes
streamlit run app/streamlit_app.py       # open the UI
```

## Strategies (Phase 1)

- **Seed strategies:** `population` (k-means++ weighted by population), `sweep-ew`,
  `sweep-ns`, `extremes`, `random`.
- **Growth rules:** `nearest-centroid`, `bfs`, `min-area`.
- **Repair pass:** boundary-block swaps to drive max |population deviation| down toward
  ~0.5%, while preserving contiguity.

## Phase plan

1. **Phase 1 (this commit)** — single-state engine + Streamlit UI + PDF export with
   embedded provenance + load-saved-PDF screen.
2. **Phase 2** — alternate seeds & growth rules tuned, exploratory mode (population as
   weight, not constraint).
3. **Phase 3** — multiprocessing batch runner across all 50 states with a live progress
   map.
