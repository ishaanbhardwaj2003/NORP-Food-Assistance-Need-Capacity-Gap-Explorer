"""
verify_outputs.py

Committed, standalone verification of every headline claim in the pipeline's
outputs -- the "commit the validation itself" ask from the Checkpoint 2
feedback. Needs no API key. Exits 0 only if every check passes and writes a
machine-readable report to data/output/validation_report.json (no timestamp,
so re-running on unchanged outputs is a no-op for git).

Checks:
    panel_fips            unique, 5-digit, zero-padded, valid state prefixes
    no_fl_ct              Florida (12) / Connecticut (09) absent (auto-dropped)
    crosswalk_collisions  zero (state, normalized-name) collisions in the lookup
    county_accounting     need/capacity/joined counts match the profiler log;
                          every one of the need-only counties is enumerated by
                          state (the panel's documented losses)
    gap_math              gap_score == need_score - capacity_score (and food)
    score_reproduction    re-scoring the panel's base columns reproduces the
                          committed scores exactly
    correlation_grid      exactly 28 unique need x capacity pairs; every
                          LLM-proposed pair carries a critic verdict
    correlation_directions gap~poverty positive, gap~ngo_per_10k negative
    ngo_extract           1,048,575 rows, all-unique lexicographically sorted
                          EINs (an ordered, truncated extract -- NOT a random
                          sample)                             [--skip-raw hides]
    f9_provenance         row/EIN/duplicate counts, tax-year mix, return types,
                          NGO->F9 match coverage              [--skip-raw hides]

Usage:
    python scripts/verify_outputs.py [--skip-raw] [--output-dir data/output]
"""

from __future__ import annotations

import argparse
import json
import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from load_data import DataLoader  # noqa: E402
from crosswalk import build_lookup_index, normalize_county_name, zero_pad_fips  # noqa: E402
from join_logic import score_panel  # noqa: E402
from correlation_agent import NEED_VARS, CAPACITY_VARS  # noqa: E402

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "output"

# 50 states + DC state FIPS prefixes (FL=12 and CT=09 are valid prefixes but
# asserted absent from the panel by the dedicated no_fl_ct check).
VALID_STATE_FIPS = {
    "01", "02", "04", "05", "06", "08", "09", "10", "11", "12", "13", "15",
    "16", "17", "18", "19", "20", "21", "22", "23", "24", "25", "26", "27",
    "28", "29", "30", "31", "32", "33", "34", "35", "36", "37", "38", "39",
    "40", "41", "42", "44", "45", "46", "47", "48", "49", "50", "51", "53",
    "54", "55", "56",
}


class Verifier:
    def __init__(self):
        self.checks: list[dict] = []

    def check(self, name: str, passed: bool, detail) -> bool:
        self.checks.append({"name": name, "passed": bool(passed), "detail": detail})
        mark = "PASS" if passed else "FAIL"
        print(f"  [{mark}] {name}")
        if not passed:
            print(f"         {detail}")
        return passed

    @property
    def all_passed(self) -> bool:
        return all(c["passed"] for c in self.checks)


def verify_panel(v: Verifier, panel: pd.DataFrame) -> None:
    fips = panel["county_fips"].astype("string")
    well_formed = fips.str.fullmatch(r"\d{5}").fillna(False)
    prefixes = set(fips.str[:2].dropna())
    v.check("panel_fips", bool(well_formed.all()) and fips.is_unique
            and prefixes <= VALID_STATE_FIPS,
            {"rows": int(len(panel)), "unique": bool(fips.is_unique),
             "malformed": int((~well_formed).sum()),
             "unknown_prefixes": sorted(prefixes - VALID_STATE_FIPS)})
    v.check("no_fl_ct", not (prefixes & {"12", "09"}),
            {"fl_counties": int(fips.str.startswith("12").sum()),
             "ct_counties": int(fips.str.startswith("09").sum())})

    for base, minuend, subtrahend in (
        ("gap_score", "need_score", "capacity_score"),
        ("food_gap_score", "need_score", "food_capacity_score"),
    ):
        diff = (pd.to_numeric(panel[base]) -
                (pd.to_numeric(panel[minuend]) - pd.to_numeric(panel[subtrahend])))
        v.check(f"gap_math:{base}", bool((diff.abs().fillna(0) < 1e-9).all()),
                {"max_abs_error": float(diff.abs().max())})

    # Full re-scoring from the panel's base columns must reproduce the scores.
    base_cols = [c for c in panel.columns if c not in {
        "ngo_per_10k", "food_ngo_per_10k", "revenue_per_capita",
        "assets_per_capita", "need_score", "capacity_score", "gap_score",
        "food_capacity_score", "food_gap_score", "need_component_count",
        "capacity_component_count", "county_name", "state"}]
    rescored = score_panel(panel[base_cols].copy())
    errs = {}
    for c in ("need_score", "capacity_score", "gap_score", "food_gap_score"):
        errs[c] = float((pd.to_numeric(rescored[c]) - pd.to_numeric(panel[c]))
                        .abs().max())
    v.check("score_reproduction", all(e < 1e-9 for e in errs.values()), errs)


def verify_crosswalk(v: Verifier, lookup: pd.DataFrame) -> None:
    df = lookup.copy()
    df["_key"] = list(zip(df["state"].astype("string").str.strip().str.upper(),
                          df["county_name"].map(normalize_county_name)))
    dupe_keys = df[df.duplicated("_key", keep=False)]
    collisions = {
        str(k): sorted(zero_pad_fips(g["county_fips"]))
        for k, g in dupe_keys.groupby("_key")
        if g["county_fips"].nunique() > 1
    }
    index = build_lookup_index(lookup)
    v.check("crosswalk_collisions", len(collisions) == 0,
            {"lookup_rows": int(len(lookup)), "index_keys": len(index),
             "colliding_keys": collisions})


def verify_county_accounting(v: Verifier, panel: pd.DataFrame,
                             profiler_log: dict, lookup: pd.DataFrame,
                             need_fips: set[str]) -> None:
    summary = profiler_log["panel"]["summary"]
    panel_fips = set(panel["county_fips"].astype(str))
    need_only = sorted(need_fips - panel_fips)
    by_state = {}
    state_names = dict(zip(zero_pad_fips(lookup["county_fips"]).str[:2],
                           lookup["state"]))
    state_names.setdefault("12", "FL")  # FL is absent from the lookup entirely
    for f in need_only:
        st = state_names.get(f[:2], f[:2])
        by_state.setdefault(st, []).append(f)
    counts_ok = (summary["joined_counties"] == len(panel)
                 and summary["need_counties"] == len(need_fips)
                 and summary["need_only"] == len(need_only))
    v.check("county_accounting", counts_ok,
            {"profiler_summary": summary,
             "need_only_total": len(need_only),
             "need_only_by_state": {k: {"n": len(fs), "fips": fs}
                                    for k, fs in sorted(by_state.items())}})


def verify_correlations(v: Verifier, corrs: pd.DataFrame,
                        panel: pd.DataFrame) -> None:
    pairs = set(zip(corrs["need_var"], corrs["capacity_var"]))
    expected = set(product(NEED_VARS, CAPACITY_VARS))
    v.check("correlation_grid",
            len(corrs) == 28 and pairs == expected,
            {"rows": int(len(corrs)), "unique_pairs": len(pairs),
             "missing": sorted(map(str, expected - pairs)),
             "unexpected": sorted(map(str, pairs - expected))})

    proposed = corrs[corrs["llm_proposed"] == True]  # noqa: E712
    has_verdict = proposed["claim_status"].astype(str).isin(
        ["supported", "weak_direction", "unsupported"])
    v.check("critic_coverage", bool(has_verdict.all()) and len(proposed) > 0,
            {"proposed": int(len(proposed)),
             "with_verdict": int(has_verdict.sum()),
             "verdicts": proposed["claim_status"].value_counts().to_dict()})

    gap = pd.to_numeric(panel["gap_score"], errors="coerce")
    directions = {}
    for col, want_positive in (("poverty_rate", True), ("ngo_per_10k", False)):
        rho = float(gap.corr(pd.to_numeric(panel[col], errors="coerce"),
                             method="spearman"))
        directions[f"gap~{col}"] = round(rho, 4)
        v.check(f"direction:gap~{col}",
                (rho > 0) if want_positive else (rho < 0),
                {"spearman_rho": round(rho, 4),
                 "expected": "positive" if want_positive else "negative"})


def verify_raw_provenance(v: Verifier, loader: DataLoader) -> None:
    ngos = loader.load_ngos()
    eins = ngos["ein"].astype(str)
    v.check("ngo_extract",
            len(ngos) == 1_048_575 and eins.is_unique
            and bool(eins.is_monotonic_increasing),
            {"rows": int(len(ngos)), "unique_eins": int(eins.nunique()),
             "lexicographically_sorted": bool(eins.is_monotonic_increasing),
             "interpretation": "ordered, truncated extract (Excel row limit); "
                               "NOT a random sample of the 3,420,024-row source"})

    f9 = loader.load_f9()
    ein = f9["org_ein"].dropna()
    years = pd.to_numeric(f9["tax_year"], errors="coerce")
    ngo_eins = eins.str.zfill(9)
    f9_eins = set(ein.astype(str).str.zfill(9))
    matched = int(ngo_eins.isin(f9_eins).sum())
    detail = {
        "rows": int(len(f9)),
        "non_null_ein": int(len(ein)),
        "unique_eins": int(ein.nunique()),
        "duplicated_ein_groups": int((ein.value_counts() > 1).sum()),
        "tax_years": {str(int(k)): int(c) for k, c in
                      years.value_counts().items()},
        "return_types": f9["return_type"].value_counts().to_dict(),
        "ngo_to_f9_matched": matched,
        "ngo_to_f9_coverage": round(matched / len(ngos), 4),
    }
    v.check("f9_provenance",
            detail["rows"] == 131_587 and detail["unique_eins"] == 131_027
            and detail["duplicated_ein_groups"] == 539,
            detail)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Verify committed pipeline outputs")
    ap.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    ap.add_argument("--skip-raw", action="store_true",
                    help="skip the raw-file provenance checks (fast mode; "
                         "avoids loading the 1M-row NGO extract)")
    args = ap.parse_args(argv)
    output_dir = Path(args.output_dir)

    print("Verifying pipeline outputs ...")
    panel = pd.read_csv(output_dir / "joined_county_panel.csv",
                        dtype={"county_fips": "string"})
    corrs = pd.read_csv(output_dir / "correlation_results.csv")
    profiler_log = json.loads((output_dir / "profiler_log.json").read_text())

    loader = DataLoader()
    lookup = loader.load_county_lookup()
    dac = loader.load_disadvantaged()
    need_fips = set(zero_pad_fips(dac["county_fips"]).dropna())

    v = Verifier()
    verify_panel(v, panel)
    verify_crosswalk(v, lookup)
    verify_county_accounting(v, panel, profiler_log, lookup, need_fips)
    verify_correlations(v, corrs, panel)
    if args.skip_raw:
        print("  [skip] ngo_extract / f9_provenance (--skip-raw)")
    else:
        verify_raw_provenance(v, loader)

    n_pass = sum(c["passed"] for c in v.checks)
    if args.skip_raw:
        # Partial run: never overwrite the committed full-coverage report.
        print(f"\n{n_pass}/{len(v.checks)} checks passed (partial run, "
              "report not written)")
    else:
        report = {"all_passed": v.all_passed, "checks": v.checks}
        report_path = output_dir / "validation_report.json"
        report_path.write_text(json.dumps(report, indent=2))
        print(f"\n{n_pass}/{len(v.checks)} checks passed -> {report_path}")
    return 0 if v.all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
