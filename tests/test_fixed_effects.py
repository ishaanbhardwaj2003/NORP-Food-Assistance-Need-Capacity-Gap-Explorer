"""
Tests for the state fixed-effects estimator (offline, deterministic).

Ports the TA benchmark branch's slope-recovery and guard tests and adds the
adaptations that matter for our version: LSDV equivalence (the within
transform must agree with an explicit dummy-variable regression), determinism,
and the signed-log outcome transform metadata.
"""

import numpy as np
import pandas as pd
import pytest

from fixed_effects import DEFAULT_SPECS, fit_state_fixed_effects, run_all

STATES = [1, 6, 48]  # AL, CA, TX -- distinct 2-digit FIPS


def _panel(y_of):
    rows = []
    for s in STATES:
        for k in range(12):
            rows.append({"county_fips": f"{s:02d}{2 * k + 1:03d}",
                         "x": float(k), "y": float(y_of(s, k))})
    return pd.DataFrame(rows)


def test_fe_recovers_within_state_slope():
    # y = state_intercept + 2*x within every state -> FE slope must be 2.
    res = fit_state_fixed_effects(_panel(lambda s, k: 100 * s + 2 * k),
                                  "y", "x", y_transform="none")
    assert res["n"] == 36 and res["n_states"] == 3
    assert "error" not in res
    assert res["fe_slope"] == pytest.approx(2.0, abs=1e-6)


def test_fe_flags_no_within_variation():
    # x constant within each state (varies only between) -> FE undefined.
    panel = _panel(lambda s, k: k).assign(
        x=lambda d: d["county_fips"].str[:2].astype(int))
    res = fit_state_fixed_effects(panel, "y", "x", y_transform="none")
    assert "error" in res


def test_fe_matches_lsdv_dummy_regression():
    rng = np.random.default_rng(7)
    panel = _panel(lambda s, k: 50 * s + 1.7 * k)
    panel["y"] = panel["y"] + rng.normal(0, 3.0, len(panel))

    res = fit_state_fixed_effects(panel, "y", "x", y_transform="none")

    # Explicit LSDV: regress y on [x, one dummy per state], no intercept.
    state = panel["county_fips"].str[:2]
    dummies = pd.get_dummies(state).to_numpy(float)
    X = np.column_stack([panel["x"].to_numpy(float), dummies])
    beta, *_ = np.linalg.lstsq(X, panel["y"].to_numpy(float), rcond=None)
    assert res["fe_slope"] == pytest.approx(float(beta[0]), abs=1e-6)


def test_fe_deterministic_and_se_positive():
    rng = np.random.default_rng(3)
    panel = _panel(lambda s, k: 10 * s + 0.5 * k)
    panel["y"] = panel["y"] + rng.normal(0, 1.0, len(panel))
    a = fit_state_fixed_effects(panel, "y", "x", y_transform="none")
    b = fit_state_fixed_effects(panel, "y", "x", y_transform="none")
    assert a == b
    assert a["fe_slope_cluster_se"] > 0
    assert 0 <= a["fe_p_value"] <= 1
    assert a["fe_df"] == len(STATES) - 1


def test_signed_log_transform_recorded_and_compresses():
    # A single extreme y should not dominate under the signed-log transform.
    panel = _panel(lambda s, k: 2 * k)
    panel.loc[0, "y"] = 1e9
    res = fit_state_fixed_effects(panel, "y", "x")  # default signed_log
    assert res["y_transform"] == "signed_log"
    assert "error" not in res
    assert abs(res["fe_slope"]) < 10  # raw-scale fit would be ~1e7 per unit x


def test_run_all_structure():
    rng = np.random.default_rng(11)
    panel = _panel(lambda s, k: 5 * s + k)
    panel["med_household_income"] = 40_000 + 2_000 * panel["x"] + rng.normal(0, 500, len(panel))
    panel["revenue_per_capita"] = 100 + 30 * panel["x"] + rng.normal(0, 10, len(panel))
    panel["poverty_rate"] = 20 - panel["x"] + rng.normal(0, 0.5, len(panel))
    panel["ngo_per_10k"] = 30 + panel["x"] + rng.normal(0, 1, len(panel))
    panel["unemployment"] = 8 - 0.2 * panel["x"] + rng.normal(0, 0.2, len(panel))

    report = run_all(panel)
    assert report["n_specs"] == len(DEFAULT_SPECS) == 4
    assert report["headline_pair"] == "med_household_income -> revenue_per_capita"
    labels = [e["label"] for e in report["estimates"]]
    assert any("sensitivity" in lbl for lbl in labels)
    head = report["estimates"][0]
    assert head["survives_fe"] is True and head["fe_slope"] > 0
    assert report["headline_survives_state_fe"] is True
