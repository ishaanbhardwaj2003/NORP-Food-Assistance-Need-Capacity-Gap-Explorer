"""
fixed_effects.py

Final-checkpoint deliverable: a state-fixed-effects estimate of the
wealth-capacity relationship. Adapted from the TA benchmark branch
(ai-suggestions/cp4, commit c26faba); changes from the benchmark version:

* Outcomes are estimated on the panel's own signed-log transform
  (sign(x) * log1p(|x|), reused from join_logic) instead of raw per-capita
  dollars. Checkpoint 3 established that raw assets/revenue per capita are
  outlier-dominated (skew ~20, single-nonprofit counties); an OLS slope on the
  raw scale would inherit exactly that problem. A raw-outcome sensitivity fit
  of the headline pair is reported alongside so the transform is auditable.
* Integrated into scripts/run_analysis.py + verify_outputs.py + tests rather
  than a side script, so the estimate lands in the committed findings and is
  re-derived by the verifier.

Why this estimator: the Checkpoint 3 critic's state-stratified permutation
test showed some correlations are pure between-state artifacts (poverty ~
ngo_per_10k, permutation p = 1.0). The regression analogue is state
fixed-effects OLS: it absorbs every additive state-level shift (cost of
living, filing coverage, tax-form geography) and re-estimates the slope from
within-state variation only. If the wealth-capacity slope survives FE with a
cluster-robust standard error, it is a genuinely within-state relationship.

Estimator (deterministic NumPy/SciPy; no LLM computes any statistic):

    within-transform:  y~_i = y_i - mean_g(y),  x~_i = x_i - mean_g(x)
    beta_FE = (X~'X~)^-1 X~'y~                  (LSDV slope, FE absorbed)

Cluster-robust (CR1) sandwich variance clustered at the state level (the same
level the FE are absorbed at), t-tests on G-1 degrees of freedom:

    V = (X~'X~)^-1 [ sum_g X~_g' e_g e_g' X~_g ] (X~'X~)^-1 * c
    c = G/(G-1) * (N-1)/(N-K),  K = 1 + G

A pooled (no-FE) OLS on the identical estimation sample is reported alongside
so the FE-vs-pooled attenuation is visible.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from join_logic import _signed_log

# (y = capacity outcome, x = need-side context, x_scale divisor, y transform).
# The first row is the headline wealth-capacity relationship; the last is the
# raw-outcome sensitivity fit of the same pair.
DEFAULT_SPECS = [
    {"y": "revenue_per_capita", "x": "med_household_income",
     "x_scale": 10_000.0, "y_transform": "signed_log",
     "label": "headline: filer revenue per capita ~ median household income ($10k)"},
    {"y": "revenue_per_capita", "x": "poverty_rate",
     "x_scale": 1.0, "y_transform": "signed_log",
     "label": "filer revenue per capita ~ poverty rate"},
    {"y": "ngo_per_10k", "x": "unemployment",
     "x_scale": 1.0, "y_transform": "signed_log",
     "label": "nonprofit density ~ unemployment"},
    {"y": "revenue_per_capita", "x": "med_household_income",
     "x_scale": 10_000.0, "y_transform": "none",
     "label": "sensitivity: headline pair on the raw outcome scale"},
]


def _state_of(fips: pd.Series) -> pd.Series:
    """Two-digit state FIPS from the 5-digit county_fips (the FE group key)."""
    return fips.astype("string").str.zfill(5).str[:2]


def _ols(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Plain least-squares coefficients for design matrix X."""
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    return beta


def fit_state_fixed_effects(panel: pd.DataFrame, y_col: str, x_col: str,
                            y_transform: str = "signed_log",
                            x_scale: float = 1.0) -> dict:
    """State-FE OLS of `y_col` on `x_col`, cluster-robust by state.

    Returns a JSON-serializable dict with the FE slope, its cluster-robust SE,
    t, two-sided p, within-R^2, the pooled (no-FE) slope on the same sample,
    and the standardized FE slope (z-scored x and y) so the coefficient is
    comparable across the panel's very different units.
    """
    fips = panel["county_fips"].astype("string")
    state = _state_of(fips)
    x = pd.to_numeric(panel[x_col], errors="coerce") / x_scale
    y_raw = pd.to_numeric(panel[y_col], errors="coerce")
    y = _signed_log(y_raw) if y_transform == "signed_log" else y_raw

    ok = x.notna() & y.notna() & state.notna()
    x, y, state = x[ok].to_numpy(float), y[ok].to_numpy(float), state[ok].to_numpy()
    n = x.size
    result = {
        "y": y_col, "x": x_col, "y_transform": y_transform,
        "x_scale": x_scale, "n": int(n),
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
        sg = Xw[idx].T @ resid[idx]
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
    # coefficient is a partial association on comparable scales.
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
    })
    return result


def run_all(panel: pd.DataFrame, specs=None) -> dict:
    """Estimate every spec and return a report dict for JSON dumping."""
    specs = DEFAULT_SPECS if specs is None else specs
    estimates = []
    for s in specs:
        est = fit_state_fixed_effects(panel, s["y"], s["x"],
                                      y_transform=s.get("y_transform", "signed_log"),
                                      x_scale=s.get("x_scale", 1.0))
        est["label"] = s.get("label", f"{s['x']} -> {s['y']}")
        estimates.append(est)
    headline = estimates[0]
    return {
        "estimator": ("state fixed-effects OLS on signed-log outcomes, "
                      "cluster-robust (CR1) by state"),
        "n_specs": len(estimates),
        "headline_pair": f"{headline.get('x')} -> {headline.get('y')}",
        "headline_survives_state_fe": headline.get("survives_fe"),
        "estimates": estimates,
    }
