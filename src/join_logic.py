"""
join_logic.py

Joins the county-level capacity and need tables into a single panel and computes
the explainable gap score.

    need_score     = mean z-score of available need indicators
    capacity_score = mean z-score of available (per-capita) capacity indicators
    gap_score      = need_score - capacity_score

A high gap_score means need outpaces capacity -- a triage signal, not a causal
claim. The join is an inner join on `county_fips`: counties present on only one
side (e.g. FL/CT capacity gaps already auto-dropped upstream) fall out here.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import zscore

NEED_INDICATORS = ["poverty_rate", "avg_food_desert_pct", "avg_housing_burden"]
# Capacity indicators are computed per-capita below before scoring.
CAPACITY_INDICATORS = ["ngo_per_10k", "revenue_per_capita", "assets_per_capita"]


def _signed_log(s: pd.Series) -> pd.Series:
    """sign(x)*log1p(|x|): compress the heavy right tail of the per-capita
    capacity metrics while preserving negative net assets. Without this, a few
    counties hosting a single huge nonprofit (asset-per-capita skew > 20) produce
    z-scores near 38 and dominate the gap score; the signed log makes the score
    robust without changing its meaning."""
    s = pd.to_numeric(s, errors="coerce")
    return np.sign(s) * np.log1p(np.abs(s))


def _zmean(df: pd.DataFrame, cols: list[str]) -> pd.Series:
    """Row-wise mean of per-column z-scores, ignoring NaN/constant columns."""
    cols = [c for c in cols if c in df.columns]
    if not cols:
        return pd.Series(np.nan, index=df.index)
    z = pd.DataFrame(index=df.index)
    for c in cols:
        col = pd.to_numeric(df[c], errors="coerce")
        std = col.std(ddof=0)
        if pd.isna(std) or std == 0:
            continue  # no information in a constant/empty column
        z[c] = zscore(col, nan_policy="omit")
    return z.mean(axis=1, skipna=True) if not z.empty else pd.Series(np.nan, index=df.index)


def score_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """Add per-capita capacity columns and need/capacity/gap scores."""
    df = panel.copy()
    pop = pd.to_numeric(df.get("population"), errors="coerce").replace(0, np.nan)

    df["ngo_per_10k"] = pd.to_numeric(df.get("ngo_count"), errors="coerce") / pop * 10_000
    df["revenue_per_capita"] = pd.to_numeric(df.get("total_revenue"), errors="coerce") / pop
    df["assets_per_capita"] = pd.to_numeric(df.get("total_assets"), errors="coerce") / pop

    # Raw per-capita columns are kept in the output for interpretability, but the
    # capacity score is computed on their signed-log transform so a few financial
    # outliers can't dominate (see _signed_log). Need indicators are bounded
    # percentages with low skew, so they are scored linearly.
    log_cols = []
    for c in CAPACITY_INDICATORS:
        lc = f"_log_{c}"
        df[lc] = _signed_log(df[c])
        log_cols.append(lc)

    df["need_score"] = _zmean(df, NEED_INDICATORS)
    df["capacity_score"] = _zmean(df, log_cols)
    df["gap_score"] = df["need_score"] - df["capacity_score"]
    return df.drop(columns=log_cols)


class PanelBuilder:
    """Inner-joins capacity + need on county_fips and scores the result."""

    def build(self, capacity_df: pd.DataFrame, need_df: pd.DataFrame) -> pd.DataFrame:
        cap = capacity_df.copy()
        need = need_df.copy()
        cap["county_fips"] = cap["county_fips"].astype("string")
        need["county_fips"] = need["county_fips"].astype("string")

        panel = cap.merge(need, on="county_fips", how="inner", validate="1:1")
        self.summary = {
            "capacity_counties": int(cap["county_fips"].nunique()),
            "need_counties": int(need["county_fips"].nunique()),
            "joined_counties": int(panel["county_fips"].nunique()),
            "capacity_only": int(
                (~cap["county_fips"].isin(need["county_fips"])).sum()),
            "need_only": int(
                (~need["county_fips"].isin(cap["county_fips"])).sum()),
        }
        return score_panel(panel)

    def save(self, panel: pd.DataFrame, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        panel.to_csv(path, index=False)
        return path

    def describe(self, panel: pd.DataFrame, top_n: int = 10) -> dict:
        metrics = ["need_score", "capacity_score", "gap_score"]
        stats = {
            m: {
                "mean": round(float(panel[m].mean()), 4),
                "median": round(float(panel[m].median()), 4),
                "std": round(float(panel[m].std()), 4),
            }
            for m in metrics if m in panel
        }
        top_gap = (
            panel.dropna(subset=["gap_score"])
            .nlargest(top_n, "gap_score")[["county_fips", "gap_score"]]
            .to_dict("records")
        )
        return {"summary": self.summary, "stats": stats, "top_gap_counties": top_gap}
