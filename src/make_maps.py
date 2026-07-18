"""
make_maps.py

Checkpoint 4 deliverable #3: a geographic view of the general and food-specific
gap scores.

A true county-polygon choropleth needs committed county geometries (a shapefile
/ GeoJSON), which is the very "data access" item the Checkpoint 3 report flagged
as still blocked. So this module ships two rendering paths:

  * choropleth_cartogram()  -- DEFAULT. A self-contained state tile-grid
    cartogram of the mean general gap and mean food-specific gap, built from the
    committed panel with matplotlib only (no geometry files, no new deps). Runs
    offline exactly like the Checkpoint 3 figures.

  * county_choropleth()     -- the real county-polygon choropleth, wired to the
    panel's own `county_fips` / `gap_score` / `food_gap_score` columns. It
    activates the moment geopandas and a county geometry file are available;
    until then it raises a clear, actionable error instead of a stub.

Both reuse the Checkpoint 3 figure palette (src/make_plots.py) so the Checkpoint
4 maps sit in the same visual system. Deterministic; no LLM, no statistics
beyond a state-level mean.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless, matching make_plots
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import TwoSlopeNorm

from make_plots import DIVERGING, GRID, INK, INK_2, MUTED, SURFACE, _save

# 2-digit state FIPS -> USPS abbreviation (only the codes that appear in the
# panel's county_fips[:2]; DC included, FL/CT present for completeness even
# though the Checkpoint 3 panel auto-drops them).
FIPS2_ABBR = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO",
    "09": "CT", "10": "DE", "11": "DC", "12": "FL", "13": "GA", "15": "HI",
    "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
    "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN",
    "28": "MS", "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
    "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD",
    "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA",
    "54": "WV", "55": "WI", "56": "WY",
}

# Approximate state centroids (lon, lat) for the contiguous US + DC; AK and HI
# are hard-placed in the reserved left column so they don't distort the grid.
_CENTROID = {
    "AL": (-86.8, 32.8), "AZ": (-111.9, 34.3), "AR": (-92.4, 34.8),
    "CA": (-119.7, 37.2), "CO": (-105.5, 39.0), "CT": (-72.7, 41.6),
    "DE": (-75.5, 39.0), "DC": (-77.0, 38.9), "FL": (-81.5, 28.6),
    "GA": (-83.4, 32.7), "IA": (-93.5, 42.0), "ID": (-114.5, 44.4),
    "IL": (-89.2, 40.0), "IN": (-86.3, 39.9), "KS": (-98.4, 38.5),
    "KY": (-85.3, 37.5), "LA": (-92.0, 31.1), "MA": (-71.8, 42.3),
    "MD": (-76.8, 39.0), "ME": (-69.2, 45.4), "MI": (-84.5, 43.3),
    "MN": (-94.3, 46.3), "MO": (-92.5, 38.4), "MS": (-89.7, 32.7),
    "MT": (-109.6, 47.0), "NC": (-79.4, 35.5), "ND": (-100.5, 47.4),
    "NE": (-99.8, 41.5), "NH": (-71.6, 43.7), "NJ": (-74.5, 40.1),
    "NM": (-106.1, 34.4), "NV": (-116.6, 39.3), "NY": (-75.5, 42.9),
    "OH": (-82.8, 40.3), "OK": (-97.5, 35.5), "OR": (-120.5, 43.9),
    "PA": (-77.8, 40.9), "RI": (-71.5, 41.7), "SC": (-80.9, 33.9),
    "SD": (-100.2, 44.4), "TN": (-86.4, 35.9), "TX": (-99.3, 31.5),
    "UT": (-111.7, 39.3), "VA": (-78.2, 37.5), "VT": (-72.7, 44.1),
    "WA": (-120.4, 47.4), "WI": (-90.0, 44.6), "WV": (-80.6, 38.6),
    "WY": (-107.5, 43.0),
}
_NROWS, _NCOLS = 8, 12   # col 0 reserved for AK (top) and HI (bottom)


def _tile_grid() -> dict[str, tuple[int, int]]:
    """Deterministically snap state centroids to unique (row, col) tiles.
    Collisions are resolved by nearest-free-cell spiral search."""
    lons = [lon for lon, _ in _CENTROID.values()]
    lats = [lat for _, lat in _CENTROID.values()]
    lon0, lon1, lat0, lat1 = min(lons), max(lons), min(lats), max(lats)
    placed: dict[str, tuple[int, int]] = {"AK": (0, 0), "HI": (_NROWS - 1, 0)}
    used = set(placed.values())

    def _free(r0: int, c0: int) -> tuple[int, int]:
        for radius in range(0, _NROWS + _NCOLS):
            for dr in range(-radius, radius + 1):
                for dc in range(-radius, radius + 1):
                    r, c = r0 + dr, c0 + dc
                    if 1 <= c < _NCOLS and 0 <= r < _NROWS and (r, c) not in used:
                        return r, c
        raise RuntimeError("tile grid exhausted")

    # Place west-to-east, north-to-south for stable collision handling.
    for st in sorted(_CENTROID, key=lambda s: (_CENTROID[s][0], -_CENTROID[s][1])):
        lon, lat = _CENTROID[st]
        col = 1 + round((lon - lon0) / (lon1 - lon0) * (_NCOLS - 2))
        row = round((lat1 - lat) / (lat1 - lat0) * (_NROWS - 1))
        r, c = _free(row, col)
        placed[st] = (r, c)
        used.add((r, c))
    return placed


def state_gap_means(panel: pd.DataFrame) -> pd.DataFrame:
    """Mean gap_score and food_gap_score per state abbreviation."""
    df = panel.copy()
    st = df["county_fips"].astype("string").str.zfill(5).str[:2].map(FIPS2_ABBR)
    df = df.assign(_state=st).dropna(subset=["_state"])
    agg = df.groupby("_state").agg(
        gap_score=("gap_score", "mean"),
        food_gap_score=("food_gap_score", "mean"),
        n_counties=("county_fips", "nunique"),
    )
    return agg


def _draw_tiles(ax, grid, values: pd.Series, label: str) -> None:
    vmax = float(np.nanmax(np.abs(values.to_numpy()))) or 1.0
    norm = TwoSlopeNorm(vmin=-vmax, vcenter=0.0, vmax=vmax)
    for st, (r, c) in grid.items():
        v = values.get(st, np.nan)
        color = DIVERGING(norm(v)) if pd.notna(v) else SURFACE
        ax.add_patch(plt.Rectangle((c, -r), 0.92, 0.92, facecolor=color,
                                   edgecolor=GRID, linewidth=0.8, zorder=2))
        txt = INK if (pd.isna(v) or abs(norm(v) - 0.5) < 0.28) else SURFACE
        ax.text(c + 0.46, -r + 0.46, st, ha="center", va="center",
                fontsize=8, color=txt, zorder=3)
    ax.set_xlim(-0.2, _NCOLS + 0.2)
    ax.set_ylim(-_NROWS + 0.0, 1.2)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(label, color=INK, fontsize=12, loc="left", pad=8)
    sm = plt.cm.ScalarMappable(cmap=DIVERGING, norm=norm)
    cbar = ax.figure.colorbar(sm, ax=ax, shrink=0.6, pad=0.02)
    cbar.set_label("mean gap (need z − capacity z)", color=INK_2, fontsize=8)
    cbar.ax.tick_params(colors=MUTED, labelsize=7)
    cbar.outline.set_edgecolor(GRID)


def choropleth_cartogram(panel: pd.DataFrame, out_dir: str | Path) -> Path:
    """State tile-grid cartogram of the general and food-specific gaps."""
    means = state_gap_means(panel)
    grid = _tile_grid()
    fig, axes = plt.subplots(1, 2, figsize=(16, 6), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    _draw_tiles(axes[0], grid, means["gap_score"],
                "General need-capacity gap (state mean)")
    _draw_tiles(axes[1], grid, means["food_gap_score"],
                "Food-specific need-capacity gap (state mean)")
    fig.suptitle("Where food-related need outpaces nonprofit capacity — "
                 "state means of the county gap scores",
                 color=INK, fontsize=13, x=0.02, ha="left")
    return _save(fig, Path(out_dir), "gap_choropleth.png")


def county_choropleth(panel: pd.DataFrame, geometry_path: str | Path,
                      out_dir: str | Path, score: str = "gap_score",
                      fips_field: str = "GEOID") -> Path:
    """Real county-polygon choropleth of `score`, joined to `panel.county_fips`.

    Activates only when geopandas and a county geometry file are present (the
    blocked data-access item); otherwise raises with an actionable message
    rather than emitting a stub map.
    """
    try:
        import geopandas as gpd  # optional; not in the offline requirements
    except ImportError as e:
        raise RuntimeError(
            "county_choropleth needs geopandas + a county geometry file. Until "
            "that data access lands, use choropleth_cartogram() (matplotlib "
            "only). Install: pip install geopandas; supply a US county GeoJSON."
        ) from e

    geo = gpd.read_file(geometry_path)
    geo[fips_field] = geo[fips_field].astype("string").str.zfill(5)
    vals = panel[["county_fips", score]].copy()
    vals["county_fips"] = vals["county_fips"].astype("string").str.zfill(5)
    merged = geo.merge(vals, left_on=fips_field, right_on="county_fips",
                       how="left")

    vmax = float(np.nanmax(np.abs(merged[score].to_numpy()))) or 1.0
    fig, ax = plt.subplots(figsize=(12, 7), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    merged.plot(column=score, cmap=DIVERGING,
                norm=TwoSlopeNorm(vmin=-vmax, vcenter=0.0, vmax=vmax),
                linewidth=0.05, edgecolor=GRID, ax=ax,
                missing_kwds={"color": SURFACE, "edgecolor": GRID,
                              "linewidth": 0.05})
    ax.axis("off")
    ax.set_title(f"County {score} choropleth", color=INK, fontsize=13, loc="left")
    return _save(fig, Path(out_dir), f"county_choropleth_{score}.png")
