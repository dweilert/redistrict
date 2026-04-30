"""Help text for every UI control. Two registers:

  - Plain-English tooltips (the `?` icon next to each slider). What the control does in
    everyday terms — written for someone who has never heard of MCMC.
  - A two-tab glossary expander: 'In plain English' (default) and 'Technical reference'
    for users who want the math.
"""
from __future__ import annotations

# ---- short tooltips (single sentence, plain English) -------------------------

TOOLTIP_UNIT = (
    "How fine-grained the map is. 'Blockgroup' is small neighborhood-sized pieces "
    "(fast). 'Block' is individual city blocks (slower, more detail). For most uses, "
    "blockgroup is fine."
)

TOOLTIP_SEED = (
    "How the computer draws its first attempt at a map before it starts improving. "
    "Stick with 'tree' — the others are mostly for experimenting."
)

TOOLTIP_EPSILON = (
    "How equal the district populations have to be. At 1%, the biggest and smallest "
    "districts can differ by at most 1% of the target. The federal courts use 1% as "
    "the rule for U.S. House districts."
)

TOOLTIP_CHAIN_LENGTH = (
    "How many different versions of the map to try before picking the best one. More "
    "tries = better map but longer wait. Start with 500 and increase if you want "
    "fancier results."
)

TOOLTIP_WEIGHTS = {
    "population_deviation": (
        "How hard to push for perfectly even populations across districts. The legal "
        "rule is already enforced separately — this just fine-tunes within it. Higher "
        "= the populations come out closer to identical."
    ),
    "polsby_popper": (
        "How much you care about district shape being tidy and round, vs. wiggly and "
        "long. Higher = rounder, more 'normal-looking' districts. Lower = the computer "
        "doesn't care and you might get oddly stretched shapes."
    ),
    "county_splits": (
        "How much you care about keeping counties whole. Higher = the computer works "
        "harder to draw district lines along county lines instead of cutting through them. "
        "Set this high if your state law requires respecting county boundaries."
    ),
    "cut_edges": (
        "How smooth you want the district borders. Higher = fewer jagged edges between "
        "districts. Closely related to 'polsby_popper' — usually set just one of these, "
        "not both."
    ),
    "total_area_sqmi": (
        "Mostly leave at 0. Only useful in advanced comparisons; on a single state "
        "the total area is fixed so this doesn't change much."
    ),
    "perimeter_total": (
        "Like 'cut_edges' — rewards short, smooth borders. Pick one of cut_edges or "
        "perimeter_total, not both."
    ),
    "reock": (
        "Not active yet. Reserved for a second compactness measurement."
    ),
}


# ---- plain-English glossary ---------------------------------------------------

GLOSSARY_PLAIN_MD = """
### What this tool does, in 30 seconds

It draws U.S. House districts using only **total population**. Nothing about race,
party, income, or anything else goes into the computer. The only rule is: each district
should have roughly the same number of people, and the shape should make sense
geographically.

You set how strict to be on different things using sliders. The computer tries thousands
of map variations, scores each one, and shows you the best. Then you can save the
result as a PDF and share it.

---

### The big picture

Every U.S. House district has to contain the same number of people — within about 1%.
That's federal law going back to a 1964 Supreme Court case. **This is the only hard
rule in the tool.** Everything else is preferences.

After population, you can ask the computer to also try to:

- keep counties whole instead of cutting them in half,
- make districts shaped tidily (round-ish) rather than long and stringy,
- keep borders smooth rather than zig-zaggy.

Those are the slider knobs. Crank one up, the computer prioritizes it. Set one to zero,
the computer ignores it.

---

### What does each slider actually do?

**Population tolerance ε**
The maximum gap between the biggest and smallest district. **Keep at 1.0% for any plan
you want to be legal.** Set it higher (3–5%) only if you're experimenting and want to
see what happens.

**Chain length**
How many map variations to try. Each variation takes a fraction of a second.
500 is plenty for Iowa-sized states. Increase to 1000–5000 for big states like Texas
or California.

**population_deviation weight**
The legal rule already caps this at 1%, so this slider just decides whether to push for
"as close to identical as possible" or "good enough at 0.9%". Higher = closer to
identical.

**polsby_popper weight (district shape)**
This is the tidiness score. Round districts = high score. Long stringy districts = low
score. Cranking this up gives you maps that look like reasonable, geographic regions.
Setting it to zero lets the computer draw whatever shape balances population most
easily — often weird-looking.

**county_splits weight**
A "split" happens when one county ends up partly in one district and partly in another.
Most state laws prefer keeping counties whole when possible. Higher = fewer splits, but
sometimes that conflicts with population balance, so the computer trades them off.

**cut_edges weight**
A more technical version of "are the borders smooth or jagged." Usually you'd weight
*either* this or polsby_popper, not both.

**total_area_sqmi / perimeter_total**
Niche — most users leave at 0.

**reock**
Reserved slot. Not active yet.

---

### Reading the result

Once the computer finishes, you'll see:

- **Max |deviation|** — biggest gap from average district size. Should be under your
  tolerance setting. The little ✅/❌ tells you at a glance.
- **Polsby–Popper (mean)** — overall tidiness. Around 0.20–0.30 is normal for real
  districts; higher is better.
- **County splits** — how many counties got cut. Lower is better.
- **Map** — the actual proposed districts. Each color is one district.
- **Per-district table** — population, deviation %, area, etc. for each district
  individually.

Try moving a slider, click Generate again, and see how the map changes. That's the
whole point: there's no single "right" map, there are tradeoffs, and this lets you see
them.

---

### Saving and re-opening

The "Generate PDF" button creates a PDF that contains the map, the scorecard, AND every
setting you used. Months later, you can drop the same PDF into the **Load saved PDF**
mode and the tool will rebuild the exact map. The PDF is the permanent record — share
it, archive it, print it.
"""

# ---- technical reference (kept for advanced users) ----------------------------

GLOSSARY_TECHNICAL_MD = """
### Engine

The engine is a Markov-chain Monte Carlo sampler called **ReCom** (Recombination), the
academic standard used by Duke, Princeton, and Pew. Each step of the chain:

1. Picks two adjacent districts.
2. Merges them into one combined region.
3. Draws a random spanning tree on that region.
4. Cuts an edge of the tree producing a balanced split.

This guarantees contiguity by construction and holds the population deviation within
ε. The chain runs `chain_length` steps; we keep the best-scoring plan we ever see.

---

### Polsby–Popper (compactness)

```
PP = 4π · area / perimeter²
```

| Score   | Shape |
|--------:|-------|
| 1.0     | perfect circle |
| ~0.5    | square / hexagon |
| 0.2–0.3 | typical real district |
| < 0.1   | stringy, gerrymander territory |

Penalizes natural boundaries (rivers, coastlines), which is a known limitation. Reock
score (area / area-of-min-enclosing-circle) is a complementary measure — slot reserved.

---

### Composite score

```
score(plan) = Σ weight[k] · normalized_metric[k]
```

Lower is better. Each metric is normalized to roughly 0–1 so weights compare cleanly.
The chain accept function tracks the best score seen and returns that plan; it does
not bias the proposals (proposals are uniform ReCom).

---

### Resolution

| Unit         | Iowa nodes | Time      |
|--------------|-----------:|-----------|
| blockgroup   | ~2,700     | seconds   |
| block        | ~175,000   | minutes   |

Plans drawn at blockgroup can be projected back to blocks (each block inherits its
blockgroup's district). Blockgroup is the academic standard for ReCom MCMC.

---

### Reproducibility

A `(seed_strategy, random_seed, chain_length, weights, ε)` tuple uniquely determines a
run. PDFs export the full tuple in their `/Keywords` metadata, plus the full GEOID →
district mapping (gzip+base64), so the resulting PDF is self-contained and a run is
re-creatable from it alone.

---

### Initial partition strategies

- **tree** — `gerrychain.tree.recursive_tree_part`. Matches the ReCom proposal; chain
  mixes faster.
- **centroid** — k-means++ on population-weighted centroids + multi-source BFS grow.
- **sweep-ew / sweep-ns** — bin nodes by x or y coordinate into equal-population strips.
"""
