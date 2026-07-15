"""LLM-output validation, the exhaustive grid, and constant-column safety."""

import numpy as np
import pandas as pd

from correlation_agent import (
    CAPACITY_VARS, MAX_CANDIDATES, NEED_VARS,
    compute_all_correlations, evaluate_candidates, validate_proposal,
)


def _candidate(need="poverty_rate", cap="ngo_per_10k", sign="negative"):
    return {"need_var": need, "capacity_var": cap,
            "hypothesis": "h", "expected_sign": sign}


def test_unknown_columns_dropped():
    p = validate_proposal({"candidates": [
        _candidate(), _candidate(need="not_a_column"),
        _candidate(cap="also_fake"),
    ]})
    assert len(p["candidates"]) == 1
    assert p["validation"]["dropped_unknown_columns"] == 2


def test_duplicate_pairs_deduplicated():
    p = validate_proposal({"candidates": [_candidate(), _candidate(),
                                          _candidate(sign="positive")]})
    assert len(p["candidates"]) == 1
    assert p["validation"]["dropped_duplicate_pairs"] == 2


def test_over_max_truncated():
    pairs = [(n, c) for n in NEED_VARS for c in CAPACITY_VARS]
    p = validate_proposal({"candidates": [
        _candidate(n, c) for n, c in pairs[:MAX_CANDIDATES + 4]]})
    assert len(p["candidates"]) == MAX_CANDIDATES
    assert p["validation"]["truncated_over_max"] == 4


def test_under_min_flagged_not_fatal():
    p = validate_proposal({"candidates": [_candidate()]})
    assert len(p["candidates"]) == 1
    assert p["validation"]["count_in_range"] is False


def test_sign_normalization():
    p = validate_proposal({"candidates": [_candidate(sign="NEGATIVE"),
                                          _candidate(cap="revenue_per_capita",
                                                     sign="sideways")]})
    signs = [c["expected_sign"] for c in p["candidates"]]
    assert signs == ["negative", "unspecified"]


def test_gate_review_verdict_whitelisted():
    p = validate_proposal({"candidates": [], "gate_review": {"verdict": "ship it"}})
    assert p["gate_review"]["verdict"] == "unspecified"


def _full_panel(n=100, constant_col=None):
    rng = np.random.default_rng(0)
    data = {"county_fips": pd.array([f"01{i:03d}" for i in range(n)], dtype="string")}
    for col in list(NEED_VARS) + list(CAPACITY_VARS):
        data[col] = rng.normal(size=n)
    df = pd.DataFrame(data)
    if constant_col:
        df[constant_col] = 1.0
    return df


def test_exhaustive_grid_is_28_unique_pairs():
    corrs = compute_all_correlations(_full_panel())
    assert len(corrs) == len(NEED_VARS) * len(CAPACITY_VARS) == 28
    assert not corrs.duplicated(["need_var", "capacity_var"]).any()
    assert corrs["pearson_r"].notna().all()


def test_constant_column_skipped_without_nan_rows():
    corrs = compute_all_correlations(_full_panel(constant_col="ngo_per_10k"))
    assert len(corrs) == 28 - len(NEED_VARS)  # every pair using it is skipped
    assert corrs["pearson_r"].notna().all()   # and none produced a NaN row


def test_evaluate_candidates_sign_matching():
    panel = _full_panel()
    panel["ngo_per_10k"] = -panel["poverty_rate"]  # perfect negative
    corrs = compute_all_correlations(panel)
    out = evaluate_candidates(corrs, {"candidates": [_candidate()]})
    row = out[(out["need_var"] == "poverty_rate")
              & (out["capacity_var"] == "ngo_per_10k")].iloc[0]
    assert row["llm_proposed"] and row["sign_matches"] == "True"
