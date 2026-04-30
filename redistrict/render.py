"""Render district choropleth maps (matplotlib)."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np


# Distinct color palette (Tableau-ish), cycled for >10 districts.
PALETTE = [
    "#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F",
    "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F", "#BAB0AC",
    "#1F77B4", "#D62728", "#2CA02C", "#9467BD", "#8C564B",
    "#E377C2", "#17BECF", "#BCBD22", "#7F7F7F", "#AEC7E8",
] * 4


def render_plan_map(blocks: gpd.GeoDataFrame, assignment: np.ndarray,
                    title: str | None = None,
                    figsize: tuple[float, float] = (8.5, 8.5)) -> bytes:
    """Render the plan as a PNG (returns bytes). Dissolves blocks by district for speed."""
    gdf = blocks.copy()
    gdf["district"] = assignment
    # Dissolve heavy step but produces sharp district boundaries.
    diss = gdf.dissolve(by="district", as_index=False, aggfunc={"population": "sum"})
    fig, ax = plt.subplots(figsize=figsize, dpi=150)
    n_d = int(assignment.max()) + 1
    colors = [PALETTE[i % len(PALETTE)] for i in range(n_d)]
    diss.plot(ax=ax, color=[colors[int(d)] for d in diss["district"]],
              edgecolor="white", linewidth=0.6)
    ax.set_axis_off()
    if title:
        ax.set_title(title, fontsize=11)
    fig.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=150)
    plt.close(fig)
    return buf.getvalue()
