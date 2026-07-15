"""
statistical_critic.py

The deterministic statistical Critic for Checkpoint 3. Python-only, fixed-seed,
no LLM involvement. It upgrades the naive "did the hypothesized sign match?"
check into an actual verification gate with three layers:

1. Multiple-testing control: Benjamini-Hochberg FDR adjustment of the Spearman
   p-values across the ENTIRE exhaustive need x capacity grid (all 28 tests,
   not just the pairs the LLM proposed), so no proposed pair benefits from
   being quietly tested alongside 27 unreported siblings.

2. State-stratified permutation test for EVERY LLM-proposed pair: the capacity
   column is shuffled *within* each state (county_fips[:2]) with a fixed seed.
   A correlation that exists only because states differ from each other (e.g.
   filing-coverage or cost-of-living geography) survives the shuffle and thus
   FAILS this test -- the observed statistic must beat a null that already
   contains all between-state structure.

3. Classification separating two claims that the summary previously blurred:
       sign matched   -- the measured direction agrees with the hypothesis
       supported      -- direction agrees AND q < ALPHA AND the pair beats the
                         stratified permutation null AND |rho| >= EFFECT_FLOOR
       weak_direction -- direction agrees and q < ALPHA, but the effect is
                         below the team floor or fails the permutation test
       unsupported    -- direction disagrees, or not significant after BH

EFFECT_FLOOR = 0.10 is a *team-defined* practical floor (documented choice,
not a universal standard); ALPHA = 0.05 likewise.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import rankdata

ALPHA = 0.05
EFFECT_FLOOR = 0.10   # team-defined minimum |Spearman rho| for "supported"
N_PERMUTATIONS = 2000
SEED = 0

SUPPORTED, WEAK, UNSUPPORTED = "supported", "weak_direction", "unsupported"


def bh_adjust(pvals) -> np.ndarray:
    """Benjamini-Hochberg FDR q-values, preserving input order."""
    p = np.asarray(pvals, dtype=float)
    m = p.size
    order = np.argsort(p)
    ranked = p[order] * m / np.arange(1, m + 1)
    # Enforce monotonicity from the largest p down, cap at 1.
    q_sorted = np.minimum.accumulate(ranked[::-1])[::-1]
    q_sorted = np.minimum(q_sorted, 1.0)
    q = np.empty(m, dtype=float)
    q[order] = q_sorted
    return q


def state_stratified_permutation_p(x, y, states,
                                   n_permutations: int = N_PERMUTATIONS,
                                   seed: int = SEED) -> float:
    """P(|Spearman rho_permuted| >= |rho_observed|) under within-state shuffles
    of y, with add-one smoothing. Deterministic for a fixed seed.

    Spearman rho is computed as the Pearson correlation of ranks; because a
    within-state permutation only reorders y, the global rank vector of y is
    permuted the same way, so ranks are computed once and reused.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    states = np.asarray(states)
    if x.size < 3:
        return float("nan")

    def _norm_ranks(v):
        r = rankdata(v)
        sd = r.std()
        if sd == 0:
            return None
        return (r - r.mean()) / sd

    rx, ry = _norm_ranks(x), _norm_ranks(y)
    if rx is None or ry is None:
        return float("nan")
    n = x.size
    observed = abs(float(np.dot(rx, ry) / n))

    groups = [np.flatnonzero(states == s) for s in np.unique(states)]
    rng = np.random.default_rng(seed)
    ry_perm = ry.copy()
    hits = 0
    for _ in range(n_permutations):
        for idx in groups:
            ry_perm[idx] = ry[idx][rng.permutation(idx.size)]
        if abs(float(np.dot(rx, ry_perm) / n)) >= observed:
            hits += 1
    return (hits + 1) / (n_permutations + 1)


def classify_claim(expected_sign: str, spearman_r: float,
                   q_value: float, permutation_p: float) -> tuple[str, str]:
    """Map one proposed pair's evidence to (claim_status, critic_reason)."""
    if expected_sign not in ("positive", "negative"):
        return UNSUPPORTED, "no valid expected sign was proposed"
    measured = "positive" if spearman_r >= 0 else "negative"
    if measured != expected_sign:
        return UNSUPPORTED, (f"measured sign is {measured}, hypothesis said "
                             f"{expected_sign}")
    if not (q_value < ALPHA):
        return UNSUPPORTED, (f"sign matches but not significant after BH FDR "
                             f"(q={q_value:.3g} >= {ALPHA})")
    if not (permutation_p < ALPHA):
        return WEAK, (f"sign matches, q={q_value:.2g}, but fails the "
                      f"state-stratified permutation test (p={permutation_p:.3g}) "
                      "-- the association may be a between-state artifact")
    if abs(spearman_r) < EFFECT_FLOOR:
        return WEAK, (f"sign matches and significant, but |rho|={abs(spearman_r):.3f} "
                      f"is below the team effect-size floor of {EFFECT_FLOOR}")
    return SUPPORTED, (f"sign matches; BH q={q_value:.2g}; state-stratified "
                       f"permutation p={permutation_p:.3g}; "
                       f"|rho|={abs(spearman_r):.2f} >= {EFFECT_FLOOR}")


def apply_critic(corrs: pd.DataFrame, panel: pd.DataFrame,
                 n_permutations: int = N_PERMUTATIONS,
                 seed: int = SEED) -> pd.DataFrame:
    """Annotate the correlation grid with q-values (all rows) and permutation
    p / claim_status / critic_reason (LLM-proposed rows). Deterministic."""
    out = corrs.copy()
    out["spearman_q_bh"] = bh_adjust(out["spearman_p"])
    out["permutation_p"] = np.nan
    out["claim_status"] = ""
    out["critic_reason"] = ""

    states = panel["county_fips"].astype("string").str[:2]
    for i in out.index[out["llm_proposed"] == True]:  # noqa: E712
        need_var, cap_var = out.at[i, "need_var"], out.at[i, "capacity_var"]
        x = pd.to_numeric(panel[need_var], errors="coerce")
        y = pd.to_numeric(panel[cap_var], errors="coerce")
        ok = x.notna() & y.notna() & states.notna()
        perm_p = state_stratified_permutation_p(
            x[ok].to_numpy(), y[ok].to_numpy(), states[ok].to_numpy(),
            n_permutations=n_permutations, seed=seed,
        )
        status, reason = classify_claim(
            out.at[i, "expected_sign"], float(out.at[i, "spearman_r"]),
            float(out.at[i, "spearman_q_bh"]), float(perm_p),
        )
        out.at[i, "permutation_p"] = perm_p
        out.at[i, "claim_status"] = status
        out.at[i, "critic_reason"] = reason
    return out


def summarize_verdicts(corrs: pd.DataFrame) -> dict:
    """Counts the findings summary needs: proposed / sign-matched / by status."""
    proposed = corrs[corrs["llm_proposed"] == True]  # noqa: E712
    return {
        "n_proposed": int(len(proposed)),
        "n_sign_matched": int((proposed["sign_matches"] == "True").sum()),
        "n_supported": int((proposed["claim_status"] == SUPPORTED).sum()),
        "n_weak_direction": int((proposed["claim_status"] == WEAK).sum()),
        "n_unsupported": int((proposed["claim_status"] == UNSUPPORTED).sum()),
    }
