"""BH correction, claim classification, and permutation-test behavior."""

import numpy as np
import pandas as pd

from statistical_critic import (
    ALPHA, EFFECT_FLOOR, SUPPORTED, UNSUPPORTED, WEAK,
    apply_critic, bh_adjust, classify_claim, state_stratified_permutation_p,
)


def test_bh_adjust_known_values():
    # Classic worked example: p = (0.01, 0.02, 0.03, 0.04) with m=4
    # q_i = p_(i) * m / i, monotone-adjusted from the top.
    q = bh_adjust([0.01, 0.04, 0.03, 0.02])
    assert np.allclose(q, [0.04, 0.04, 0.04, 0.04])
    # Order preserved and identity on a single test.
    assert np.allclose(bh_adjust([0.5]), [0.5])
    q2 = bh_adjust([0.001, 0.9])
    assert q2[0] < q2[1] and q2[1] <= 1.0


def test_classify_boundaries():
    assert classify_claim("negative", -0.3, 1e-10, 0.001)[0] == SUPPORTED
    # Sign mismatch dominates everything else.
    assert classify_claim("positive", -0.3, 1e-10, 0.001)[0] == UNSUPPORTED
    # Not significant after BH.
    assert classify_claim("negative", -0.3, 0.2, 0.001)[0] == UNSUPPORTED
    # Significant but fails the stratified permutation test.
    assert classify_claim("negative", -0.3, 1e-10, 0.9)[0] == WEAK
    # Significant but below the team effect-size floor.
    small = EFFECT_FLOOR - 0.01
    assert classify_claim("negative", -small, 1e-10, 0.001)[0] == WEAK
    # No usable sign.
    assert classify_claim("unspecified", -0.3, 1e-10, 0.001)[0] == UNSUPPORTED
    # Exactly at alpha is NOT significant (strict inequality).
    assert classify_claim("negative", -0.3, ALPHA, 0.001)[0] == UNSUPPORTED


def _states(n, k=5):
    return np.repeat([f"{i:02d}" for i in range(1, k + 1)], n // k)


def test_permutation_deterministic():
    rng = np.random.default_rng(42)
    x = rng.normal(size=200)
    y = x * 0.5 + rng.normal(size=200)
    s = _states(200)
    p1 = state_stratified_permutation_p(x, y, s, n_permutations=200, seed=0)
    p2 = state_stratified_permutation_p(x, y, s, n_permutations=200, seed=0)
    assert p1 == p2


def test_permutation_detects_signal_and_noise():
    rng = np.random.default_rng(7)
    x = rng.normal(size=500)
    s = _states(500)
    y_signal = x + 0.3 * rng.normal(size=500)
    y_noise = rng.normal(size=500)
    assert state_stratified_permutation_p(x, y_signal, s,
                                          n_permutations=500, seed=1) < 0.01
    assert state_stratified_permutation_p(x, y_noise, s,
                                          n_permutations=500, seed=1) > 0.05


def test_permutation_kills_pure_state_level_artifact():
    # y depends ONLY on the state mean of x: within states there is no
    # association, so the stratified null should NOT be beaten.
    rng = np.random.default_rng(3)
    s = _states(500)
    state_effect = {st: rng.normal() for st in np.unique(s)}
    x = np.array([state_effect[st] for st in s]) + 0.1 * rng.normal(size=500)
    y = np.array([state_effect[st] for st in s]) + 0.1 * rng.normal(size=500)
    p = state_stratified_permutation_p(x, y, s, n_permutations=500, seed=2)
    assert p > 0.05


def test_apply_critic_annotates_proposed_rows():
    rng = np.random.default_rng(11)
    n = 300
    panel = pd.DataFrame({
        "county_fips": pd.array([f"{(i % 5) + 1:02d}{i:03d}" for i in range(n)],
                                dtype="string"),
        "poverty_rate": rng.normal(20, 5, n),
    })
    panel["ngo_per_10k"] = -0.5 * panel["poverty_rate"] + rng.normal(0, 2, n)
    corrs = pd.DataFrame([{
        "need_var": "poverty_rate", "capacity_var": "ngo_per_10k",
        "spearman_r": -0.6, "spearman_p": 1e-12,
        "llm_proposed": True, "expected_sign": "negative",
        "sign_matches": "True",
    }, {
        "need_var": "poverty_rate", "capacity_var": "ngo_per_10k",
        "spearman_r": 0.01, "spearman_p": 0.8,
        "llm_proposed": False, "expected_sign": "", "sign_matches": "",
    }])
    out = apply_critic(corrs, panel, n_permutations=200, seed=0)
    assert "spearman_q_bh" in out.columns
    assert out["claim_status"].iloc[0] in (SUPPORTED, WEAK, UNSUPPORTED)
    assert out["claim_status"].iloc[1] == ""          # untouched non-proposed row
    assert not np.isnan(out["permutation_p"].iloc[0])
    assert np.isnan(out["permutation_p"].iloc[1])
