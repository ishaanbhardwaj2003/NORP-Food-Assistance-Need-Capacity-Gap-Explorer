"""
compare_extract_vs_full.py

The final report's centerpiece table: which conclusions survive the move from
the truncated 1M-row extract to the full 3,420,024-row table?

Three panels are compared:
  A. CP3 committed panel  -- extract + Checkpoint 3 crosswalk (read from git)
  B. extract + crosswalk v2 -- isolates the crosswalk fix (built to a scratch
     dir with `run_pipeline.py --ngo-source extract`)
  C. full + crosswalk v2  -- the new committed panel (data/output)

For each: county count, gap distribution, top-10 gap counties. Pairwise vs C:
top-10 overlap, gap-score rank correlation on common counties, and the
exhaustive 28-pair Spearman grid recomputed per panel with per-pair deltas and
sign flips. The old committed correlation_results.csv is also read from git so
critic verdict changes on the 7 LLM-proposed pairs are listed.

Writes data/output/full_vs_extract_comparison.json. Deterministic, no LLM.

Usage:
    python scripts/compare_extract_vs_full.py \
        --extract-panel <scratch>/joined_county_panel.csv \
        [--baseline-ref 3a2e792] [--output-dir data/output]
"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from correlation_agent import add_derived_columns, compute_all_correlations  # noqa: E402

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "output"
CP3_REF = "3a2e792"   # "CP3 revision" commit: extract-based panel + verdicts


def _git_show(ref: str, path: str) -> str:
    return subprocess.run(
        ["git", "show", f"{ref}:{path}"], cwd=PROJECT_ROOT,
        capture_output=True, text=True, check=True).stdout


def _load_panel_text(text: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text), dtype={"county_fips": "string"})
    return add_derived_columns(df)


def _load_panel_file(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"county_fips": "string"})
    return add_derived_columns(df)


def summarize(panel: pd.DataFrame) -> dict:
    gap = pd.to_numeric(panel["gap_score"], errors="coerce")
    top = panel.nlargest(10, "gap_score")["county_fips"].astype(str).tolist()
    return {
        "counties": int(len(panel)),
        "gap_median": round(float(gap.median()), 3),
        "gap_std": round(float(gap.std()), 3),
        "gap_min": round(float(gap.min()), 3),
        "gap_max": round(float(gap.max()), 3),
        "top10_gap_fips": top,
    }


def compare_to_full(panel: pd.DataFrame, full: pd.DataFrame) -> dict:
    a = panel.set_index(panel["county_fips"].astype(str))["gap_score"]
    b = full.set_index(full["county_fips"].astype(str))["gap_score"]
    common = a.index.intersection(b.index)
    rank_rho = float(a[common].rank().corr(b[common].rank()))
    top_a = set(panel.nlargest(10, "gap_score")["county_fips"].astype(str))
    top_b = set(full.nlargest(10, "gap_score")["county_fips"].astype(str))

    ga = compute_all_correlations(panel).set_index(["need_var", "capacity_var"])
    gb = compute_all_correlations(full).set_index(["need_var", "capacity_var"])
    joined = ga[["spearman_r"]].join(gb[["spearman_r"]], how="inner",
                                     lsuffix="_this", rsuffix="_full")
    deltas = (joined["spearman_r_full"] - joined["spearman_r_this"]).abs()
    flips = [
        {"pair": f"{n} ~ {c}",
         "this": round(float(joined.loc[(n, c), "spearman_r_this"]), 3),
         "full": round(float(joined.loc[(n, c), "spearman_r_full"]), 3)}
        for (n, c) in joined.index
        if (joined.loc[(n, c), "spearman_r_this"] >= 0)
        != (joined.loc[(n, c), "spearman_r_full"] >= 0)
    ]
    return {
        "common_counties": int(len(common)),
        "counties_gained_by_full": int(len(set(b.index) - set(a.index))),
        "gap_rank_rho_on_common": round(rank_rho, 4),
        "top10_overlap_with_full": len(top_a & top_b),
        "corr_grid_max_abs_delta": round(float(deltas.max()), 4),
        "corr_grid_mean_abs_delta": round(float(deltas.mean()), 4),
        "corr_sign_flips": flips,
    }


def critic_verdict_changes(new_corrs_path: Path) -> list[dict]:
    old = pd.read_csv(io.StringIO(
        _git_show(CP3_REF, "data/output/correlation_results.csv")))
    new = pd.read_csv(new_corrs_path)
    changes = []
    old_p = old[old["llm_proposed"] == True]  # noqa: E712
    new_p = new[new["llm_proposed"] == True].set_index(["need_var", "capacity_var"])  # noqa: E712
    for _, r in old_p.iterrows():
        key = (r["need_var"], r["capacity_var"])
        if key not in new_p.index:
            changes.append({"pair": f"{key[0]} ~ {key[1]}",
                            "cp3": r["claim_status"], "final": "not proposed"})
            continue
        new_status = new_p.loc[key, "claim_status"]
        changes.append({"pair": f"{key[0]} ~ {key[1]}",
                        "cp3": r["claim_status"], "final": str(new_status),
                        "changed": str(new_status) != str(r["claim_status"])})
    return changes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Extract-vs-full panel comparison")
    ap.add_argument("--extract-panel", required=True,
                    help="panel built with --ngo-source extract (crosswalk v2)")
    ap.add_argument("--baseline-ref", default=CP3_REF)
    ap.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = ap.parse_args(argv)
    output_dir = Path(args.output_dir)

    print("[1/3] Loading the three panels ...")
    cp3 = _load_panel_text(_git_show(args.baseline_ref,
                                     "data/output/joined_county_panel.csv"))
    extract_v2 = _load_panel_file(Path(args.extract_panel))
    full = _load_panel_file(output_dir / "joined_county_panel.csv")

    print("[2/3] Comparing ...")
    report = {
        "panels": {
            "A_cp3_extract_crosswalk_v1": {"git_ref": args.baseline_ref,
                                           **summarize(cp3)},
            "B_extract_crosswalk_v2": summarize(extract_v2),
            "C_full_crosswalk_v2": summarize(full),
        },
        "A_vs_C": compare_to_full(cp3, full),
        "B_vs_C": compare_to_full(extract_v2, full),
        "critic_verdicts_cp3_to_final": critic_verdict_changes(
            output_dir / "correlation_results.csv"),
        "attribution_note": (
            "A->B isolates the crosswalk fix (34 VA cities + Dona Ana); "
            "B->C isolates the move from the truncated extract to the full "
            "3,420,024-row table."),
    }

    print("[3/3] Writing report ...")
    out = output_dir / "full_vs_extract_comparison.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"      -> {out}")
    ac = report["A_vs_C"]
    print(f"      CP3 vs final: top-10 overlap {ac['top10_overlap_with_full']}/10, "
          f"gap rank rho {ac['gap_rank_rho_on_common']}, "
          f"max grid delta {ac['corr_grid_max_abs_delta']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
