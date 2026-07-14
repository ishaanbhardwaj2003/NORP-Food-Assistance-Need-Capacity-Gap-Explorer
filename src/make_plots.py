"""
make_plots.py

Checkpoint 3 figures, rendered from the committed county panel so a grader can
regenerate every image with no API key. Four figures land in
data/output/figures/:

    top_gap_counties.png       horizontal bar of the highest-gap counties
    need_vs_capacity.png       scatter of the two composite scores
    gap_distribution.png       histogram of the gap score
    correlation_heatmap.png    need x capacity Spearman correlation grid

Styling follows a small fixed palette (single-hue marks, diverging blue/red
only where sign matters, recessive hairline grid, text in ink tokens).
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless: never require a display
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm

# Palette (light mode): validated single-hue + diverging pair.
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BLUE = "#2a78d6"      # series hue (magnitude)
BLUE_LIGHT = "#9ec5f4"
RED = "#e34948"       # diverging warm pole (high gap / positive corr)
NEUTRAL = "#f0efec"   # diverging midpoint

DIVERGING = LinearSegmentedColormap.from_list(
    "need_gap_div", [BLUE, NEUTRAL, RED]
)


def _style(ax):
    """Recessive chrome: hairline grid behind the data, no top/right spines."""
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _fig(w=8.0, h=5.0):
    fig, ax = plt.subplots(figsize=(w, h), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    _style(ax)
    return fig, ax


def _save(fig, out_dir: Path, name: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    fig.savefig(path, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    return path


def _county_label(row) -> str:
    name, state = row.get("county_name"), row.get("state")
    if pd.notna(name) and pd.notna(state):
        return f"{name}, {state}"
    return f"FIPS {row['county_fips']}"


def plot_top_gap_counties(panel: pd.DataFrame, out_dir: Path, top_n: int = 15) -> Path:
    top = panel.nlargest(top_n, "gap_score").iloc[::-1]  # largest at the top
    labels = [_county_label(r) for _, r in top.iterrows()]

    fig, ax = _fig(8.0, 0.42 * top_n + 1.2)
    ax.barh(labels, top["gap_score"], height=0.62, color=BLUE, zorder=3)
    for y, v in enumerate(top["gap_score"]):
        ax.text(v + 0.05, y, f"{v:+.2f}", va="center", ha="left",
                fontsize=9, color=INK_2)
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, top["gap_score"].max() * 1.14)
    ax.set_xlabel("Gap score (need z − capacity z)", color=INK_2, fontsize=10)
    ax.set_title(f"Top {top_n} counties where food-related need outpaces "
                 "nonprofit capacity", color=INK, fontsize=12, loc="left", pad=12)
    return _save(fig, out_dir, "top_gap_counties.png")


def plot_need_vs_capacity(panel: pd.DataFrame, out_dir: Path, top_n: int = 10) -> Path:
    top = panel.nlargest(top_n, "gap_score")
    rest = panel.drop(top.index)

    fig, ax = _fig(8.0, 6.0)
    ax.scatter(rest["capacity_score"], rest["need_score"], s=18,
               color=BLUE_LIGHT, edgecolors=SURFACE, linewidths=0.6,
               zorder=3, label="All counties")
    ax.scatter(top["capacity_score"], top["need_score"], s=52, color=RED,
               edgecolors=SURFACE, linewidths=1.2, zorder=4,
               label=f"Top {top_n} gap counties")
    # Iso-gap reference: need == capacity means gap == 0.
    lim = [panel[["capacity_score", "need_score"]].min().min() - 0.3,
           panel[["capacity_score", "need_score"]].max().max() + 0.3]
    ax.plot(lim, lim, color=MUTED, linewidth=1.0, linestyle=(0, (4, 3)), zorder=2)
    ax.text(lim[1], lim[1], " gap = 0", color=MUTED, fontsize=8, va="bottom")

    # Label selectively: walking down the gap ranking, label a point only if
    # it sits clear of every already-labeled point, so labels in the high-gap
    # cluster never collide (the legend + findings table name the rest).
    placed: list[tuple[float, float]] = []
    for _, r in top.iterrows():
        x, y = float(r["capacity_score"]), float(r["need_score"])
        if any(((x - px) ** 2 + (y - py) ** 2) ** 0.5 < 0.55 for px, py in placed):
            continue
        placed.append((x, y))
        ax.annotate(_county_label(r), (x, y), xytext=(7, 5),
                    textcoords="offset points", fontsize=8, color=INK_2)
    ax.set_xlabel("Capacity score (mean z of per-capita capacity)", color=INK_2, fontsize=10)
    ax.set_ylabel("Need score (mean z of need indicators)", color=INK_2, fontsize=10)
    ax.set_title("County need vs. nonprofit capacity — high-gap counties sit "
                 "far above the diagonal", color=INK, fontsize=12, loc="left", pad=12)
    ax.legend(loc="lower right", frameon=False, fontsize=9, labelcolor=INK_2)
    return _save(fig, out_dir, "need_vs_capacity.png")


def plot_gap_distribution(panel: pd.DataFrame, out_dir: Path) -> Path:
    gap = pd.to_numeric(panel["gap_score"], errors="coerce").dropna()

    fig, ax = _fig(8.0, 4.5)
    ax.hist(gap, bins=50, color=BLUE, edgecolor=SURFACE, linewidth=0.8, zorder=3)
    med = float(gap.median())
    ax.axvline(med, color=INK_2, linewidth=1.2, zorder=4)
    ax.text(med, ax.get_ylim()[1] * 0.96, f" median {med:+.2f}",
            color=INK_2, fontsize=9, va="top")
    ax.grid(axis="x", visible=False)
    ax.set_xlabel("Gap score", color=INK_2, fontsize=10)
    ax.set_ylabel("Counties", color=INK_2, fontsize=10)
    ax.set_title(f"Gap-score distribution across {len(gap):,} counties",
                 color=INK, fontsize=12, loc="left", pad=12)
    return _save(fig, out_dir, "gap_distribution.png")


def plot_correlation_heatmap(corrs: pd.DataFrame, out_dir: Path) -> Path:
    """Need (rows) x capacity (cols) Spearman grid, diverging blue/red."""
    grid = corrs.pivot(index="need_var", columns="capacity_var", values="spearman_r")

    fig, ax = _fig(1.5 * len(grid.columns) + 3.4, 0.62 * len(grid) + 1.8)
    ax.grid(False)
    norm = TwoSlopeNorm(vmin=-0.7, vcenter=0.0, vmax=0.7)
    im = ax.imshow(grid.values, cmap=DIVERGING, norm=norm, aspect="auto")

    ax.set_xticks(range(len(grid.columns)), grid.columns, rotation=25,
                  ha="right", fontsize=9, color=INK_2)
    ax.set_yticks(range(len(grid.index)), grid.index, fontsize=9, color=INK_2)
    for i in range(len(grid.index)):
        for j in range(len(grid.columns)):
            v = grid.values[i, j]
            if np.isnan(v):
                continue
            ax.text(j, i, f"{v:+.2f}", ha="center", va="center", fontsize=9,
                    color=INK if abs(v) < 0.45 else SURFACE)
    cbar = fig.colorbar(im, ax=ax, shrink=0.85)
    cbar.set_label("Spearman ρ", color=INK_2, fontsize=9)
    cbar.ax.tick_params(colors=MUTED, labelsize=8)
    cbar.outline.set_edgecolor(GRID)
    ax.set_title("Need × capacity correlations (Spearman, county level)",
                 color=INK, fontsize=12, loc="left", pad=12)
    return _save(fig, out_dir, "correlation_heatmap.png")


def make_all_plots(panel: pd.DataFrame, corrs: pd.DataFrame,
                   out_dir: str | Path) -> list[Path]:
    out_dir = Path(out_dir)
    return [
        plot_top_gap_counties(panel, out_dir),
        plot_need_vs_capacity(panel, out_dir),
        plot_gap_distribution(panel, out_dir),
        plot_correlation_heatmap(corrs, out_dir),
    ]
