"""Render district choropleth maps from a Plan + the underlying GeoDataFrame."""
from __future__ import annotations

from io import BytesIO

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np


PALETTE = [
    "#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F",
    "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F", "#BAB0AC",
    "#1F77B4", "#D62728", "#2CA02C", "#9467BD", "#8C564B",
    "#E377C2", "#17BECF", "#BCBD22", "#7F7F7F", "#AEC7E8",
] * 4


def render_plan_map(units_gdf: gpd.GeoDataFrame, assignment: dict,
                    title: str | None = None,
                    figsize: tuple[float, float] = (8.5, 8.5),
                    show_county: bool = True,
                    counties_gdf: gpd.GeoDataFrame | None = None) -> bytes:
    """Render the plan as a PNG.

    Args:
        units_gdf: GeoDataFrame with a GEOID column matching keys in `assignment`.
        assignment: mapping of GEOID → district id.
        counties_gdf: optional county outline overlay (thin gray line).
    """
    gdf = units_gdf.copy()
    gdf["GEOID"] = gdf["GEOID"].astype(str)
    gdf["district"] = gdf["GEOID"].map(assignment)
    gdf = gdf.dropna(subset=["district"])
    gdf["district"] = gdf["district"].astype(int)
    diss = gdf.dissolve(by="district", as_index=False)

    fig, ax = plt.subplots(figsize=figsize, dpi=150)
    n_d = int(diss["district"].max()) + 1
    colors = [PALETTE[i % len(PALETTE)] for i in range(n_d)]
    diss.plot(ax=ax,
              color=[colors[int(d)] for d in diss["district"]],
              edgecolor="white", linewidth=1.0)
    if show_county and counties_gdf is not None:
        counties_gdf.plot(ax=ax, facecolor="none", edgecolor="#555", linewidth=0.4)
    ax.set_axis_off()
    if title:
        ax.set_title(title, fontsize=11)
    fig.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=150)
    plt.close(fig)
    return buf.getvalue()
