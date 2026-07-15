"""
build_capacity_table.py

County-level nonprofit *capacity* table.

Output schema (one row per county_fips):
    county_fips         : 5-digit zero-padded FIPS (str)
    ngo_count           : number of nonprofits in the county
    food_ngo_count      : nonprofits with category 'Food, Agriculture and Nutrition'
    matched_filer_count : NGOs with a matched 990/990EZ/990PF filing
    filer_coverage_rate : matched_filer_count / ngo_count
    total_revenue       : sum of filing current-year total revenue (NaN if no filer)
    total_assets        : sum of filing end-of-year net assets (NaN if no filer)

Build steps:
    1. Resolve NGO county names to county_fips via `crosswalk_fn` (no manual
       patches); drop rows that don't resolve (FL/CT etc. -- logged by profiler).
    2. Reduce the F9 summary to ONE filing per EIN: the file mixes tax years
       (2019/2020/2022) and holds 539 duplicated-EIN groups, so we keep the
       latest tax year and break remaining ties by largest total revenue (a
       proxy for the amended / most complete return). Returns are 990, 990EZ,
       and 990PF -- not exclusively "full 990s".
    3. Left-join filings to NGOs on a 9-digit zero-padded EIN. The join is
       sparse (~3.6% of NGOs match a filing), so financial sums use
       min_count=1: a county with no matched filer gets NaN (unobserved), NOT
       a fabricated zero. A genuine reported zero survives as 0.
    4. Aggregate to county level with match-coverage columns so downstream
       consumers can see how much filing evidence each county's financials
       rest on.

`mock_capacity_table()` provides a synthetic table for fast `--mock` test runs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

FOOD_CATEGORY = "Food, Agriculture and Nutrition"

REV_COL, ASSETS_COL = "f9_01_rev_tot_cy", "f9_01_nafb_tot_eoy"


def _pad_ein(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip().str.zfill(9)


def select_one_filing_per_ein(f9_df: pd.DataFrame) -> pd.DataFrame:
    """One row per EIN: latest tax_year, ties broken by largest total revenue.

    Sorting with na_position='first' means a record with a missing year or
    revenue is only kept when the EIN has nothing better.
    """
    f9 = f9_df.copy()
    f9["org_ein"] = _pad_ein(f9["org_ein"])
    f9 = f9[f9["org_ein"].notna()]
    f9["_tax_year"] = pd.to_numeric(f9.get("tax_year"), errors="coerce")
    for c in (REV_COL, ASSETS_COL):
        f9[c] = pd.to_numeric(f9[c], errors="coerce")
    return (
        f9[["org_ein", "_tax_year", REV_COL, ASSETS_COL]]
        .sort_values(["org_ein", "_tax_year", REV_COL], na_position="first")
        .drop_duplicates(subset="org_ein", keep="last")
        .drop(columns="_tax_year")
    )


def build_capacity_table(ngos_df: pd.DataFrame, f9_df: pd.DataFrame,
                         crosswalk_fn) -> pd.DataFrame:
    # 1. resolve counties -> FIPS, keep only resolved rows
    ngos = crosswalk_fn(ngos_df)
    ngos = ngos[ngos["county_fips"].notna()].copy()
    ngos["ein"] = _pad_ein(ngos["ein"])

    # 2-3. one filing per EIN, then left-join as an enrichment layer
    f9_small = select_one_filing_per_ein(f9_df)
    merged = ngos.merge(f9_small, left_on="ein", right_on="org_ein", how="left")

    # 4. aggregate to county level; min_count=1 keeps unobserved financials NaN
    merged["_is_food"] = (merged["category"] == FOOD_CATEGORY).astype(int)
    merged["_matched"] = merged["org_ein"].notna().astype(int)
    out = merged.groupby("county_fips").agg(
        ngo_count=("ein", "size"),
        food_ngo_count=("_is_food", "sum"),
        matched_filer_count=("_matched", "sum"),
        total_revenue=(REV_COL, lambda s: s.sum(min_count=1)),
        total_assets=(ASSETS_COL, lambda s: s.sum(min_count=1)),
    ).reset_index()
    out["filer_coverage_rate"] = out["matched_filer_count"] / out["ngo_count"]
    out["county_fips"] = out["county_fips"].astype("string")
    return out


def mock_capacity_table(n: int = 50, seed: int = 0) -> pd.DataFrame:
    """Synthetic capacity table over real-looking FIPS for --mock runs."""
    rng = np.random.default_rng(seed)
    fips = [f"{rng.integers(1, 56):02d}{rng.integers(1, 200):03d}" for _ in range(n)]
    fips = sorted(set(fips))
    m = len(fips)
    ngo_count = rng.integers(5, 2000, m)
    matched = np.minimum(rng.integers(0, 80, m), ngo_count)
    df = pd.DataFrame({
        "county_fips": pd.array(fips, dtype="string"),
        "ngo_count": ngo_count,
        "food_ngo_count": rng.integers(0, 100, m),
        "matched_filer_count": matched,
        "total_revenue": rng.integers(0, 50_000_000, m).astype(float),
        "total_assets": rng.integers(0, 80_000_000, m).astype(float),
    })
    # Mirror the real semantics: no matched filer means unobserved (NaN), not 0.
    df.loc[df["matched_filer_count"] == 0, ["total_revenue", "total_assets"]] = np.nan
    df["filer_coverage_rate"] = df["matched_filer_count"] / df["ngo_count"]
    return df
