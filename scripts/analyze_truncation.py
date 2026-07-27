"""
analyze_truncation.py

Quantify the bias of the 1,048,575-row NGO extract against the now-committed
full 3,420,024-row table. CP2 and CP3 disclosed the extract as an ordered,
truncated, non-random cut (the Excel export row limit, EIN-sorted); with the
full table in hand the bias stops being a caveat and becomes a measurement:

  * per-state coverage: extract rows / full rows for every state, showing the
    EIN-prefix cut is geographically structured (pre-2001 EIN prefixes encode
    the IRS district that issued them, and every EIN sorting above the cut
    point is absent wholesale);
  * sector skew: the food category's coverage vs the overall coverage;
  * the raw cut facts (row counts, EIN range, sortedness) machine-recorded.

Writes data/output/truncation_analysis.json and
data/output/figures/truncation_bias.png. Deterministic, offline, no LLM.

Usage:
    python scripts/analyze_truncation.py [--output-dir data/output]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from load_data import DataLoader  # noqa: E402
from make_plots import BLUE, GRID, INK, INK_2, MUTED, RED, SURFACE, _save  # noqa: E402

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "output"
FOOD_LABEL = "Food, Agriculture and Nutrition"


def state_coverage(extract: pd.DataFrame, full: pd.DataFrame) -> pd.DataFrame:
    ex = extract["state"].astype("string").str.upper().value_counts()
    fu = full["state"].astype("string").str.upper().value_counts()
    df = pd.DataFrame({"extract_rows": ex, "full_rows": fu}).fillna(0).astype(int)
    df = df[df["full_rows"] >= 1_000]        # ignore territories/noise codes
    df["coverage"] = df["extract_rows"] / df["full_rows"]
    return df.sort_values("coverage")


def plot_coverage(cov: pd.DataFrame, overall: float, out_dir: Path) -> Path:
    fig, ax = plt.subplots(figsize=(8.4, 0.24 * len(cov) + 1.6), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    colors = [RED if c < overall * 0.5 else BLUE for c in cov["coverage"]]
    ax.barh(cov.index.astype(str), cov["coverage"], color=colors, height=0.62,
            zorder=3)
    ax.axvline(overall, color=INK_2, linewidth=1.1, linestyle=(0, (4, 3)),
               zorder=4)
    ax.text(overall, len(cov) - 0.2, f" overall {overall:.0%}", color=INK_2,
            fontsize=8, va="top")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=7)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_xlabel("share of the state's full-table NGOs present in the extract",
                  color=INK_2, fontsize=9)
    ax.set_title("The truncated extract was not a random sample: per-state "
                 "coverage of the EIN-sorted cut", color=INK, fontsize=11,
                 loc="left", pad=10)
    return _save(fig, out_dir, "truncation_bias.png")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Extract-vs-full truncation bias")
    ap.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = ap.parse_args(argv)
    output_dir = Path(args.output_dir)

    print("[1/3] Loading extract and full NGO tables ...")
    extract = DataLoader(ngo_source="extract").load_ngos()
    full = DataLoader(ngo_source="full").load_ngos()
    ex_eins = extract["ein"].astype(str)

    print("[2/3] Measuring the cut ...")
    cov = state_coverage(extract, full)
    overall = len(extract) / len(full)
    food_ex = int((extract["category"] == FOOD_LABEL).sum())
    food_fu = int((full["category"] == FOOD_LABEL).sum())
    report = {
        "extract_rows": int(len(extract)),
        "full_rows": int(len(full)),
        "overall_coverage": round(overall, 4),
        "extract_ein_sorted": bool(ex_eins.is_monotonic_increasing),
        "extract_ein_max": ex_eins.max(),
        "cut_interpretation": (
            "The extract is the first 1,048,575 rows (the Excel export limit) "
            "of the EIN-lexicographically-sorted table; every EIN sorting "
            "above the cut point is absent wholesale, and pre-2001 EIN "
            "prefixes encode IRS district geography, so the cut is "
            "geographically structured rather than random."),
        "food_category": {
            "extract": food_ex, "full": food_fu,
            "coverage": round(food_ex / food_fu, 4),
            "note": ("food-sector coverage vs overall coverage shows the cut "
                     "under-sampled the food sector"),
        },
        "llm_flag_nonnull": {
            "extract": int(extract["is_category_llm_generated"].notna().sum()),
            "full": int(full["is_category_llm_generated"].notna().sum()),
            "note": ("is_category_LLM_generated is null on every row of BOTH "
                     "files: upstream category provenance is unverifiable"),
        },
        "state_coverage": {
            st: {"extract_rows": int(r["extract_rows"]),
                 "full_rows": int(r["full_rows"]),
                 "coverage": round(float(r["coverage"]), 4)}
            for st, r in cov.iterrows()
        },
        "worst_covered_states": [
            {"state": st, "coverage": round(float(c), 4)}
            for st, c in cov["coverage"].head(8).items()
        ],
        "best_covered_states": [
            {"state": st, "coverage": round(float(c), 4)}
            for st, c in cov["coverage"].tail(3).items()
        ],
    }

    print("[3/3] Writing artifacts ...")
    out_json = output_dir / "truncation_analysis.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2))
    fig_path = plot_coverage(cov, overall, output_dir / "figures")
    print(f"      -> {out_json}")
    print(f"      -> {fig_path}")
    print(f"      overall coverage {overall:.1%}; food coverage "
          f"{food_ex / food_fu:.1%}; worst state "
          f"{report['worst_covered_states'][0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
