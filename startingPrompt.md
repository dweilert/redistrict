I am building a Python project to generate population-only U.S. congressional redistricting plans.

Goal:
Create congressional districts based only on total population, not race, sex, religion, income, party, or other demographic attributes.

I already have:
- 2020 TIGER/Line Census block shapefiles (geometry + GEOID) in directory: /Users/bob/redistrict/tiger_blocks
- Census P.L. 94-171 Redistricting Data Summary Files in - directory: /Users/bob/redistrist/pl94171

I need to:
- Load Census P.L. 94-171 population data
- Join population to TIGER block geometry
- Build a graph of adjacent blocks
- Generate population-balanced districts

==================================================
CENSUS DATA SOURCE (POPULATION)
==================================================

Use 2020 Census P.L. 94-171 Redistricting Data Summary Files.

State ZIP files are named like:

  TX2020PL.zip
  CA2020PL.zip
  AL2020PL.zip

Example:

  TX2020PL.zip = Texas redistricting data

Inside each ZIP:

  txgeo2020.pl       → geographic identifiers
  tx000012020.pl     → population data (segment 1)

Key variable:

  P1_001N = total population

Join key:

  LOGRECNO

==================================================
WORKFLOW
==================================================

Step 1 — Extract population data

- Unzip TX2020PL.zip
- Read:
    txgeo2020.pl
    tx000012020.pl

- Join on:
    LOGRECNO

- Filter to:
    Census blocks (lowest level geography)

- Build:

    GEOID = state + county + tract + block

- Extract:

    GEOID
    total population (P1_001N)

==================================================
Step 2 — Load TIGER block shapefile (already available)

TIGER shapefile contains:

    GEOID
    geometry (polygon)

==================================================
Step 3 — Join population to geometry

Join:

    TIGER.GEOID  ←→  PL.GEOID

Result:

    block dataset with:

      GEOID
      population
      geometry

Save as:

    GeoPackage (recommended)
    or Parquet for performance

Example output:

    data/processed/states/tx_blocks.gpkg

==================================================
Step 4 — Build adjacency graph

Each Census block becomes a node.

Edges exist between blocks that touch:

    blocks are neighbors if geometries intersect/touch

Use:

    geopandas.sjoin OR shapely touches/intersects
    OR spatial index (rtree / pygeos)

Graph structure:

    node: GEOID
    attributes:
        population
        geometry (optional or external)

    edges:
        adjacency (shared boundary)

Store graph using:

    networkx OR custom adjacency list

==================================================
Step 5 — Define district targets

Input:

    number_of_districts (e.g., Texas = 38)

Compute:

    target_population = total_state_population / number_of_districts

==================================================
Step 6 — Generate districts

Constraints:

    - must be contiguous
    - population ≈ target_population
    - minimize deviation

Initial approach:

    1. Choose seed blocks
    2. Grow districts outward using neighbors
    3. Stop when near target population
    4. Repair imbalances
    5. Repeat multiple times

Optional scoring metrics:

    - population deviation
    - compactness (Polsby–Popper, perimeter/area)
    - minimize county splits

==================================================
Step 7 — Output results

Produce:

    - GeoPackage of districts
    - GeoJSON for visualization
    - CSV: block → district assignment
    - population report per district
    - deviation metrics

==================================================
Step 8 — View results

Produce:

    - Viewer app that allows users to view the generated data.


==================================================
PYTHON LIBRARIES I THINK I NEED
==================================================

geopandas
pandas
shapely
pyogrio
networkx
numpy
scipy
scikit-learn
tqdm

==================================================
IMPORTANT NOTES
==================================================

- TIGER shapefiles provide geometry; PL 94-171 provides population.
- GEOID is the bridge between the two datasets.
- Do NOT mirror the entire Census site.
- Work one state at a time.

==================================================
FIRST MILESTONE
==================================================

Write a script that:

1. Loads PL 94-171 files for one state
2. Extracts block-level population
3. Loads TIGER block shapefile
4. Joins population to geometry
5. Writes:

    data/processed/states/<state>_blocks.gpkg

Start with a small state before scaling to Texas.
