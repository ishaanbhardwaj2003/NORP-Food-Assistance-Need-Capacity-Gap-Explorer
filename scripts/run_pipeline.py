"""
run_pipeline.py

End-to-end orchestration for the Need-Capacity Gap Explorer.

    1. Load all raw data                         (load_data)
    2. Profile each table + validate joins        (profile_data)
    3. Render the proceed/proceed_with_warning/stop gate; halt if 'stop'
    4. Build the county capacity table            (build_capacity_table)
    5. Build the county need table                (build_need_table)
    6. Inner-join + gap score                      (join_logic)
    7. Save data/output/{profiler_log.json, joined_county_panel.csv}

Flags:
    --sample   load only 10k rows per file (fast iteration)
    --mock     use synthetic capacity/need tables instead of full aggregation
    --verbose  print detailed profiler / scoring output
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

# Make the sibling src/ package importable whether run as a script or module.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC))

from load_data import DataLoader  # noqa: E402
from crosswalk import resolve_county_to_fips, match_report, zero_pad_fips  # noqa: E402
from profile_data import DataProfiler, STOP  # noqa: E402
from build_capacity_table import build_capacity_table, mock_capacity_table  # noqa: E402
from build_need_table import build_need_table, mock_need_table  # noqa: E402
from join_logic import PanelBuilder  # noqa: E402

OUTPUT_DIR = PROJECT_ROOT / "data" / "output"
PROFILER_LOG = OUTPUT_DIR / "profiler_log.json"
PANEL_CSV = OUTPUT_DIR / "joined_county_panel.csv"

# Declared join keys per table (drives the profiler's null/completeness audit).
KEY_COLS = {
    "ngos": ["ein", "county", "state"],
    "f9": ["org_ein"],
    "disadvantaged": ["county_fips"],
    "county_lookup": ["county_fips", "county_name", "state"],
    "poverty": ["fips_code"],
    "nccs": ["geoid_2010"],
}


def _fips_set(series: pd.Series) -> set[str]:
    return set(zero_pad_fips(series).dropna())


def profile_everything(frames: dict, profiler: DataProfiler) -> None:
    # Per-table schema / null audit.
    for name, df in frames.items():
        profiler.profile_table(name, df, KEY_COLS.get(name))

    # Capacity-side join: NGO county-name -> FIPS (FL/CT auto-drop happens here).
    resolved = resolve_county_to_fips(frames["ngos"], frames["county_lookup"])
    rpt = match_report(resolved)
    profiler.record_join(
        "ngo_county_to_fips", "capacity", rpt["match_rate"],
        rpt["matched_rows"], rpt["unmatched_rows"], detail=rpt,
    )

    # Need-side joins: do poverty / nccs cover the disadvantaged-community counties?
    dac_fips = _fips_set(frames["disadvantaged"]["county_fips"])
    for name, col in (("poverty", "fips_code"), ("nccs", "geoid_2010")):
        other = _fips_set(frames[name][col])
        matched = len(dac_fips & other)
        rate = matched / len(dac_fips) if dac_fips else 0.0
        profiler.record_join(
            f"dac_to_{name}", "need", rate, matched, len(dac_fips) - matched,
            detail={"dac_counties": len(dac_fips), "other_counties": len(other)},
        )


def build_tables(frames: dict, use_mock: bool):
    if use_mock:
        capacity = mock_capacity_table()
        need = mock_need_table(fips=capacity["county_fips"].tolist())
        return capacity, need

    def crosswalk_fn(df):
        return resolve_county_to_fips(df, frames["county_lookup"])

    capacity = build_capacity_table(frames["ngos"], frames["f9"], crosswalk_fn)
    need = build_need_table(frames["disadvantaged"], frames["poverty"], frames["nccs"])
    return capacity, need


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Need-Capacity Gap Explorer pipeline")
    ap.add_argument("--sample", action="store_true", help="10k rows/file")
    ap.add_argument("--mock", action="store_true", help="synthetic capacity/need tables")
    ap.add_argument("--verbose", action="store_true", help="detailed output")
    args = ap.parse_args(argv)

    print(f"[1/7] Loading raw data (sample={args.sample}) ...")
    frames = DataLoader(sample_mode=args.sample).load_all()
    for name, df in frames.items():
        print(f"      {name:14s} {df.shape}")

    print("[2/7] Profiling tables and validating joins ...")
    profiler = DataProfiler()
    profile_everything(frames, profiler)

    print("[3/7] Quality gate ...")
    gate = profiler.gate()
    profiler.save(PROFILER_LOG)
    print(f"      verdict: {gate['verdict'].upper()}")
    if args.verbose:
        for r in gate["reasons"]:
            print(f"        - {r}")
    if gate["verdict"] == STOP:
        print("      STOP: a need-side table/join failed the quality gate. Halting.")
        print(f"      See {PROFILER_LOG}")
        return 1

    print(f"[4-5/7] Building capacity + need tables (mock={args.mock}) ...")
    capacity, need = build_tables(frames, args.mock)
    print(f"        capacity: {capacity.shape}   need: {need.shape}")

    print("[6/7] Joining + scoring ...")
    builder = PanelBuilder()
    panel = builder.build(capacity, need)
    desc = builder.describe(panel)

    print("[7/7] Saving outputs ...")
    builder.save(panel, PANEL_CSV)
    # Fold the join summary + scoring stats into the profiler log for evidence.
    log = json.loads(PROFILER_LOG.read_text())
    log["panel"] = desc
    log["panel"]["rows"] = int(len(panel))
    PROFILER_LOG.write_text(json.dumps(log, indent=2))

    print(f"      panel rows: {len(panel)}  ->  {PANEL_CSV}")
    print(f"      profiler log ->  {PROFILER_LOG}")
    if args.verbose:
        print("      join summary:", json.dumps(desc["summary"]))
        print("      score stats :", json.dumps(desc["stats"]))
        print("      top gap     :", json.dumps(desc["top_gap_counties"][:5]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
