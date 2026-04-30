# redistrict

Population-only U.S. congressional redistricting plans, generated from 2020 Census P.L.
94-171 data and TIGER/Line block geometry. The only attribute used is total population
(`P1_001N`). No race, party, income, or other demographics enter the algorithm.

## Engine: gerrychain ReCom MCMC

The redistricting engine is built on [gerrychain](https://gerrychain.readthedocs.io/) — the
academic-standard ReCom (Recombination) Markov-chain Monte Carlo sampler used by Duke,
Princeton, and Pew. ReCom proposals work by picking two adjacent districts, merging them,
drawing a random spanning tree on the combined region, and cutting an edge to produce a
balanced split. Contiguity is preserved by construction; population deviation is held
within a user-set ε (default 1%). Plans routinely achieve **< 0.2% deviation** on Iowa.

## Highlights

- **Hard population guarantee.** ε is enforced by the chain — plans that violate it are
  never accepted.
- **Weighted multi-criteria scoring.** Slider-controlled weights for population
  deviation, Polsby–Popper compactness, county splits, cut edges, area, perimeter. The
  best-scoring plan across all chain steps is returned.
- **Two units of analysis.** `blockgroup` (~thousands of nodes, seconds) is the standard
  for ReCom; `block` (~hundreds of thousands) is supported for higher fidelity.
- **Self-contained PDF export.** Every PDF embeds the full plan (GEOID → district
  mapping) plus all run parameters in its metadata. The viewer can rebuild the map from
  the PDF alone — no other files needed.
- **Ensemble mode.** Run N chains in parallel processes, return the single best plan.
- **Reproducible.** A `(seed_strategy, random_seed, chain_length, weights)` tuple
  determines the entire run.

## Layout

```
redistrict/
  config.py          paths, FIPS table, seat counts
  loader.py          PL 94-171 + TIGER → joined GeoPackage
  graph.py           dual graph builder (gerrychain.Graph) + cache
  scoring.py         weighted scorecard with Polsby-Popper, county splits, cut edges
  engine.py          gerrychain ReCom MCMC + initial-partition strategies
  ensemble.py        multi-chain runner (ProcessPoolExecutor)
  pdf_export.py      ReportLab PDF + provenance embed/read
  persistence.py     plan save/load + assignment encode/decode
  render.py          choropleth map rendering (matplotlib)
app/
  streamlit_app.py   UI: generate plan, weight sliders, PDF export, load saved PDF
scripts/
  prepare_state.py   CLI: build blocks gpkg + dual graph cache
  test_iowa.py       end-to-end smoke test
tests/
  test_basic.py      pytest suite (loader, graph, engine ≤1% bar, PDF round-trip)
```

## Setup

```bash
conda env create -f environment.yml
conda activate redistrict

# Raw data (downloaded separately):
#   /Users/bob/redistrict/pl94171/{state}2020.pl.zip                 (PL 94-171, per state)
#   /Users/bob/redistrict/tiger_blocks/tl_2020_{fips}_tabblock20.zip (TIGER blocks)
# Paths configurable in redistrict/config.py.

python scripts/prepare_state.py IA --unit blockgroup     # one-time prep
streamlit run app/streamlit_app.py                       # open the UI
pytest tests/                                            # smoke + invariant tests
```

## Quality bar (Iowa, blockgroup, 4 districts, 200 ReCom steps, ~30s)

| Metric                 | Value         |
|------------------------|---------------|
| Max \|deviation\|      | < 0.15 %      |
| Contiguous             | yes           |
| Polsby–Popper (mean)   | ~0.22         |
| Chain elapsed          | 30 s          |

## Phase plan

1. **Phase 1 (legacy, tag `phase1-greedy`)** — hand-rolled greedy seed-and-grow engine.
   Plateaued at ~5–10% deviation. Kept as historical baseline; superseded.
2. **Phase 2 (current `main`)** — gerrychain ReCom engine, full scorecard, Streamlit UI,
   PDF provenance, ensemble runner, pytest suite.
3. **Phase 3 (planned)** — multiprocessing batch runner across all 50 states with a live
   progress map and nationwide PDF report.

## Notes

- ReCom is graph/spanning-tree work — CPU-bound. GPUs do not help. Apple Silicon and
  multi-core x86 boxes both run this fine; ensemble mode uses processes (not threads,
  due to the GIL).
- Block-level plans are supported but block-group is the academic standard for ReCom.
  Resulting plans transfer to blocks faithfully (each block inherits its block-group's
  district).
