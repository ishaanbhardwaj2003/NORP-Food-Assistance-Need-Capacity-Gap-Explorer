"""
build_capacity_table.py

County-level nonprofit *capacity* table.

Output schema (one row per county_fips):
    county_fips        : 5-digit zero-padded FIPS (str)
    ngo_count          : number of nonprofits in the county
    food_ngo_count     : nonprofits with category 'Food, Agriculture and Nutrition'
    total_revenue      : sum of F9 current-year total revenue (matched orgs)
    total_assets       : sum of F9 end-of-year net assets (matched orgs)

Build steps:
    1. Resolve NGO county names to county_fips via `crosswalk_fn` (no manual
       patches); drop rows that don't resolve (FL/CT etc. -- logged by profiler).
    2. Left-join NGOs to F9 financials on a 9-digit zero-padded EIN. F9 is an
       enrichment layer; only ~3% of NGOs have a 990 filing, so most revenue/
       assets are NaN and sum as 0.
    3. Aggregate to county level.

`mock_capacity_table()` provides a synthetic table for fast `--mock` test runs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

FOOD_CATEGORY = "Food, Agriculture and Nutrition"


def _pad_ein(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip().str.zfill(9)


def build_capacity_table(ngos_df: pd.DataFrame, f9_df: pd.DataFrame,
                         crosswalk_fn) -> pd.DataFrame:
    # 1. resolve counties -> FIPS, keep only resolved rows
    ngos = crosswalk_fn(ngos_df)
    ngos = ngos[ngos["county_fips"].notna()].copy()
    ngos["ein"] = _pad_ein(ngos["ein"])

    # 2. left-join F9 financials (collapse F9 to one row per EIN first)
    f9 = f9_df.copy()
    f9["org_ein"] = _pad_ein(f9["org_ein"])
    rev_col, assets_col = "f9_01_rev_tot_cy", "f9_01_nafb_tot_eoy"
    f9_small = (
        f9[["org_ein", rev_col, assets_col]]
        .apply(lambda c: pd.to_numeric(c, errors="coerce") if c.name != "org_ein" else c)
        .groupby("org_ein", as_index=False)
        .sum(numeric_only=True)
    )
    merged = ngos.merge(f9_small, left_on="ein", right_on="org_ein", how="left")

    # 3. aggregate to county level
    merged["_is_food"] = (merged["category"] == FOOD_CATEGORY).astype(int)
    out = merged.groupby("county_fips").agg(
        ngo_count=("ein", "size"),
        food_ngo_count=("_is_food", "sum"),
        total_revenue=(rev_col, "sum"),
        total_assets=(assets_col, "sum"),
    ).reset_index()
    out["county_fips"] = out["county_fips"].astype("string")
    return out


def mock_capacity_table(n: int = 50, seed: int = 0) -> pd.DataFrame:
    """Synthetic capacity table over real-looking FIPS for --mock runs."""
    rng = np.random.default_rng(seed)
    fips = [f"{rng.integers(1, 56):02d}{rng.integers(1, 200):03d}" for _ in range(n)]
    fips = sorted(set(fips))
    m = len(fips)
    return pd.DataFrame({
        "county_fips": pd.array(fips, dtype="string"),
        "ngo_count": rng.integers(5, 2000, m),
        "food_ngo_count": rng.integers(0, 100, m),
        "total_revenue": rng.integers(0, 50_000_000, m),
        "total_assets": rng.integers(0, 80_000_000, m),
    })
