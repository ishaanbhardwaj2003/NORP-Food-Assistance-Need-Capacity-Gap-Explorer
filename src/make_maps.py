"""
make_maps.py

Final-checkpoint deliverable: the geographic view of the general and
food-specific gap scores. Two layers:

  * plot_county_choropleth() -- a TRUE county-polygon choropleth rendered with
    matplotlib only (no geopandas / GIS deps), from the committed
    data/reference/us_counties_geo.json (see PROVENANCE.md there). CONUS main
    axes with Alaska and Hawaii insets; counties present in the geometry but
    absent from the panel (Florida, Connecticut, unjoined counties) are drawn
    in a neutral no-data grey. A sidecar choropleth_meta.json records exactly
    how many counties were drawn/missing so the verifier can re-check the map.

  * choropleth_cartogram() -- the state tile-grid overview of mean gaps,
    adapted from the TA benchmark branch (ai-suggestions/cp4, commit c26faba),
    kept as the at-a-glance companion figure.

The benchmark's county map required geopandas plus a geometry file it did not
ship; committing public-domain Census-derived geometry and parsing the GeoJSON
directly removes both blockers. Deterministic; no LLM, no statistics beyond a
state-level mean.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless, matching make_plots
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.collections import PolyCollection
from matplotlib.colors import TwoSlopeNorm
from matplotlib.patches import Patch

from make_plots import DIVERGING, GRID, INK, INK_2, MUTED, SURFACE, _save

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GEOMETRY = PROJECT_ROOT / "data" / "reference" / "us_counties_geo.json"
NO_DATA = "#eeeee8"

SCORE_TITLES = {
    "gap_score": "General need-capacity gap by county (need z minus capacity z)",
    "food_gap_score": "Food-specific need-capacity gap by county",
}


# -- geometry ---------------------------------------------------------------

def load_county_geometries(path: str | Path = DEFAULT_GEOMETRY,
                           ) -> dict[str, list[np.ndarray]]:
    """FIPS -> list of exterior rings (each an (n, 2) lon/lat array).

    Parses Polygon and MultiPolygon features from the committed GeoJSON;
    interior rings (holes) are ignored, which is invisible at 20m-class
    cartographic resolution.
    """
    geo = json.loads(Path(path).read_text())
    out: dict[str, list[np.ndarray]] = {}
    for feat in geo.get("features", []):
        fips = str(feat.get("id", "")).zfill(5)
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates", [])
        if geom.get("type") == "Polygon":
            polys = [coords]
        elif geom.get("type") == "MultiPolygon":
            polys = coords
        else:
            continue
        rings = [np.asarray(poly[0], dtype=float)
                 for poly in polys if poly and len(poly[0]) >= 3]
        if rings:
            out[fips] = rings
    return out


def _axes_for(fips: str) -> str:
    if fips.startswith("02"):
        return "ak"
    if fips.startswith("15"):
        return "hi"
    return "conus"


# -- county choropleth ------------------------------------------------------

def plot_county_choropleth(panel: pd.DataFrame,
                           geoms: dict[str, list[np.ndarray]],
                           out_dir: Path, score: str = "gap_score") -> Path:
    values = dict(zip(panel["county_fips"].astype(str),
                      pd.to_numeric(panel[score], errors="coerce")))
    finite = np.array([v for v in values.values() if pd.notna(v)])
    vmax = float(np.percentile(np.abs(finite), 99.5)) or 1.0
    norm = TwoSlopeNorm(vmin=-vmax, vcenter=0.0, vmax=vmax)

    fig = plt.figure(figsize=(12.5, 8.2), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    axes = {
        "conus": fig.add_axes([0.02, 0.06, 0.9, 0.86]),
        "ak": fig.add_axes([0.03, 0.055, 0.22, 0.24]),
        "hi": fig.add_axes([0.27, 0.045, 0.14, 0.14]),
    }
    buckets = {k: {"polys": [], "colors": []} for k in axes}
    no_data_polys = {k: [] for k in axes}

    for fips, rings in geoms.items():
        target = _axes_for(fips)
        if target == "ak":  # drop Aleutian rings across the antimeridian
            rings = [r for r in rings if (r[:, 0] <= 0).all()]
            if not rings:
                continue
        v = values.get(fips)
        for ring in rings:
            if v is None or pd.isna(v):
                no_data_polys[target].append(ring)
            else:
                buckets[target]["polys"].append(ring)
                buckets[target]["colors"].append(DIVERGING(norm(float(np.clip(v, -vmax, vmax)))))

    for key, ax in axes.items():
        ax.set_facecolor(SURFACE if key == "conus" else "none")
        if no_data_polys[key]:
            ax.add_collection(PolyCollection(
                no_data_polys[key], facecolors=NO_DATA, edgecolors=GRID,
                linewidths=0.12, zorder=1))
        if buckets[key]["polys"]:
            ax.add_collection(PolyCollection(
                buckets[key]["polys"], facecolors=buckets[key]["colors"],
                edgecolors=SURFACE, linewidths=0.12, zorder=2))
        if key == "conus":
            ax.set_xlim(-125, -66)
            ax.set_ylim(24, 50)
        else:
            ax.autoscale_view()
            ax.margins(0.02)
        ax.set_aspect(1.25)
        ax.axis("off")

    ax = axes["conus"]
    ax.set_title(SCORE_TITLES.get(score, score), color=INK, fontsize=13,
                 loc="left", pad=10)
    sm = plt.cm.ScalarMappable(cmap=DIVERGING, norm=norm)
    cbar = fig.colorbar(sm, ax=ax, shrink=0.55, pad=0.01)
    cbar.set_label(f"{score} (blue = capacity outpaces need, red = need "
                   "outpaces capacity)", color=INK_2, fontsize=9)
    cbar.ax.tick_params(colors=MUTED, labelsize=8)
    cbar.outline.set_edgecolor(GRID)
    ax.legend(handles=[Patch(facecolor=NO_DATA, edgecolor=GRID,
                             label="no data (FL/CT auto-dropped or unjoined)")],
              loc="lower right", frameon=False, fontsize=8, labelcolor=INK_2)
    fig.text(0.02, 0.015,
             "Plate carree (plain lon/lat); AK and HI inset, Aleutian islands "
             "beyond the antimeridian omitted.", color=MUTED, fontsize=7)
    return _save(fig, out_dir, f"{score}_choropleth_county.png")


# -- state tile cartogram (adapted from the benchmark branch) ---------------

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
    return df.groupby("_state").agg(
        gap_score=("gap_score", "mean"),
        food_gap_score=("food_gap_score", "mean"),
        n_counties=("county_fips", "nunique"),
    )


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
    cbar.set_label("mean gap (need z minus capacity z)", color=INK_2, fontsize=8)
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
    fig.suptitle("Where food-related need outpaces nonprofit capacity: "
                 "state means of the county gap scores",
                 color=INK, fontsize=13, x=0.02, ha="left")
    return _save(fig, Path(out_dir), "gap_cartogram_states.png")


# -- orchestration ----------------------------------------------------------

def choropleth_metadata(panel: pd.DataFrame,
                        geoms: dict[str, list[np.ndarray]]) -> dict:
    panel_fips = set(panel["county_fips"].astype(str))
    geo_fips = set(geoms)
    return {
        "panel_counties": len(panel_fips),
        "counties_drawn": len(panel_fips & geo_fips),
        "missing_geometry_fips": sorted(panel_fips - geo_fips),
        "no_data_counties": len(geo_fips - panel_fips),
    }


def make_gap_maps(panel: pd.DataFrame, out_dir: str | Path,
                  geometry_path: str | Path = DEFAULT_GEOMETRY) -> list[Path]:
    """Render the cartogram plus both county choropleths; write the sidecar
    choropleth_meta.json the verifier checks. Skips the county maps with a
    clear warning when the committed geometry file is absent."""
    out_dir = Path(out_dir)
    paths = [choropleth_cartogram(panel, out_dir)]
    geometry_path = Path(geometry_path)
    if not geometry_path.exists():
        print(f"      WARNING: {geometry_path} missing; county choropleths "
              "skipped (cartogram only)")
        return paths
    geoms = load_county_geometries(geometry_path)
    for score in ("gap_score", "food_gap_score"):
        paths.append(plot_county_choropleth(panel, geoms, out_dir, score))
    meta = choropleth_metadata(panel, geoms)
    meta_path = out_dir / "choropleth_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2))
    paths.append(meta_path)
    return paths
