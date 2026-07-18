"""
fixed_effects.py

Checkpoint 4 deliverable #1: a state-fixed-effects estimate of the
wealth-capacity relationship.

Checkpoint 3 left the strongest surviving finding as
    med_household_income (need-side context) ~ revenue_per_capita (capacity)
    Spearman rho = +0.25, clears BH-FDR + the within-state permutation test.

The Checkpoint 3 statistical_critic already established (via a state-stratified
permutation null) that several correlations are pure between-state artifacts --
most bluntly poverty_rate ~ ngo_per_10k, whose permutation p was 1.0. The
regression analogue of that permutation test is a *state fixed-effects* OLS: it
absorbs every additive state-level shift (cost of living, filing coverage,
tax-form geography) and re-estimates the slope using ONLY within-state variation
across counties. If the wealth-capacity slope survives the FE absorption with a
cluster-robust standard error, it is a genuinely within-state relationship, not
a compositional one.

Everything here is deterministic Python (NumPy linear algebra + SciPy for the
t / F reference distributions). No LLM computes any statistic, consistent with
the project's "Python is the source of truth" contract.

Estimator
---------
For outcome y and regressor(s) x with state groups g (county_fips[:2]):

    within-transform:  y~_i = y_i - mean_g(y),   x~_i = x_i - mean_g(x)
    beta_FE          = (X~'X~)^-1 X~'y~            (the LSDV slope, FE absorbed)

Inference uses a cluster-robust (CR1) sandwich variance clustered at the state
level -- the same level the FE are absorbed at -- because county errors within a
state are not independent:

    V = (X~'X~)^-1 [ sum_g X~_g' e_g e_g' X~_g ] (X~'X~)^-1 * c
    c = G/(G-1) * (N-1)/(N-K),  K = k_slopes + G  (params incl. absorbed FE)

with t-tests on G-1 degrees of freedom. A pooled (no-FE) OLS on the identical
estimation sample is reported alongside so the FE-vs-pooled attenuation is
visible.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

# The Checkpoint 3 critic's own "supported" / most-defensible pairs, expressed
# as (outcome y = capacity, regressor x = need-side context). Each is estimated
# with state FE below; the first is the headline wealth-capacity relationship.
DEFAULT_PAIRS = [
    ("revenue_per_capita", "med_household_income"),  # capacity tracks wealth
    ("revenue_per_capita", "poverty_rate"),          # capacity vs need (inverse)
    ("ngo_per_10k", "unemployment"),                 # density vs need (inverse)
]


def _state_of(fips: pd.Series) -> pd.Series:
    """Two-digit state FIPS from the 5-digit county_fips (the FE group key)."""
    return fips.astype("string").str.zfill(5).str[:2]


def _ols(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Plain least-squares coefficients for design matrix X."""
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    return beta


def fit_state_fixed_effects(panel: pd.DataFrame, y_col: str, x_col: str,
                            standardize: bool = True) -> dict:
    """State-FE OLS of `y_col` on `x_col`, cluster-robust by state.

    Returns a JSON-serializable dict with the FE slope, its cluster-robust SE,
    t, two-sided p, within-R^2, the pooled (no-FE) slope on the same sample, and
    the standardized FE slope (z-scored x and y) so the coefficient is
    comparable across the panel's very different units ($ income vs $/capita).
    """
    fips = panel["county_fips"].astype("string")
    state = _state_of(fips)
    x = pd.to_numeric(panel[x_col], errors="coerce")
    y = pd.to_numeric(panel[y_col], errors="coerce")

    ok = x.notna() & y.notna() & state.notna()
    x, y, state = x[ok].to_numpy(float), y[ok].to_numpy(float), state[ok].to_numpy()
    n = x.size
    result = {
        "y": y_col, "x": x_col, "n": int(n),
        "n_states": int(np.unique(state).size),
    }
    if n < 30 or np.unique(state).size < 3:
        result["error"] = "too few counties or states for a stable FE estimate"
        return result

    # --- pooled OLS (intercept + x) on the identical sample, for contrast ---
    Xp = np.column_stack([np.ones(n), x])
    beta_pooled = _ols(Xp, y)
    result["pooled_slope"] = round(float(beta_pooled[1]), 6)

    # --- within (state-demeaned) transform ---
    def _demean(v: np.ndarray) -> np.ndarray:
        s = pd.Series(v)
        return (s - s.groupby(state).transform("mean")).to_numpy()

    xw, yw = _demean(x), _demean(y)
    if np.allclose(xw.std(), 0.0):
        result["error"] = "no within-state variation in x; FE slope undefined"
        return result

    Xw = xw.reshape(-1, 1)                      # no intercept: absorbed by FE
    XtX_inv = np.linalg.inv(Xw.T @ Xw)
    beta = (XtX_inv @ Xw.T @ yw)                # shape (1,)
    resid = yw - Xw @ beta

    # cluster-robust (CR1) meat, clustered at the state level
    groups = np.unique(state)
    meat = np.zeros((1, 1))
    for g in groups:
        idx = state == g
        Xg, eg = Xw[idx], resid[idx]
        sg = Xg.T @ eg
        meat += np.outer(sg, sg)
    G = groups.size
    K = 1 + G                                   # slope + absorbed state FE
    c = (G / (G - 1)) * ((n - 1) / (n - K)) if n > K else 1.0
    V = XtX_inv @ meat @ XtX_inv * c
    se = float(np.sqrt(V[0, 0]))
    slope = float(beta[0])
    t = slope / se if se > 0 else float("nan")
    df = G - 1
    p = float(2 * stats.t.sf(abs(t), df)) if np.isfinite(t) else float("nan")

    ss_res = float(resid @ resid)
    ss_tot = float(yw @ yw)
    within_r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")

    # standardized FE slope: z-score x and y over the estimation sample so the
    # coefficient is a partial correlation on comparable scales.
    xz = (x - x.mean()) / x.std(ddof=0)
    yz = (y - y.mean()) / y.std(ddof=0)
    xzw = _demean(xz)
    if not np.allclose(xzw.std(), 0.0):
        std_slope = float(_ols(xzw.reshape(-1, 1), _demean(yz))[0])
    else:
        std_slope = float("nan")

    result.update({
        "fe_slope": round(slope, 6),
        "fe_slope_cluster_se": round(se, 6),
        "fe_t": round(float(t), 4),
        "fe_p_value": p,
        "fe_df": int(df),
        "within_r2": round(float(within_r2), 6),
        "fe_slope_standardized": round(std_slope, 6),
        "pooled_minus_fe_slope": round(float(beta_pooled[1] - slope), 6),
        "survives_fe": bool(np.isfinite(p) and p < 0.05
                            and np.sign(slope) == np.sign(beta_pooled[1])),
        "interpretation": (
            f"Within states, a 1-unit rise in {x_col} moves {y_col} by "
            f"{slope:+.4g} (cluster-robust p={p:.3g}); standardized "
            f"partial slope {std_slope:+.3f}."
        ),
    })
    return result


def run_all(panel: pd.DataFrame, pairs=DEFAULT_PAIRS) -> dict:
    """Estimate every (y, x) pair and return a report dict for JSON dumping."""
    estimates = [fit_state_fixed_effects(panel, y, x) for y, x in pairs]
    headline = estimates[0]
    return {
        "estimator": "state fixed-effects OLS, cluster-robust (CR1) by state",
        "n_pairs": len(estimates),
        "headline_pair": f"{headline.get('x')} -> {headline.get('y')}",
        "headline_survives_state_fe": headline.get("survives_fe"),
        "estimates": estimates,
    }
