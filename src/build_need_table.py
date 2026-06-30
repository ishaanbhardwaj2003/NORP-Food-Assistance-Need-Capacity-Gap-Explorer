"""
build_need_table.py

County-level community *need* table.

Output schema (one row per county_fips):
    county_fips           : 5-digit zero-padded FIPS (str)
    population            : sum of tract population
    avg_food_desert_pct   : population-weighted mean of food_desert_pct
    avg_housing_burden    : population-weighted mean of avg_housing_burden
    dac_tract_pct         : fraction of tracts with dac_status == 'true'
    avg_dac_score         : population-weighted mean of dac_score
    poverty_rate          : county poverty percentage (Poverty_Rates_2023)
    med_household_income  : adjusted median household income (NCCS)
    unemployment          : unemployment rate (NCCS)

Build steps:
    1. Aggregate disadvantaged_communities tracts -> county (FIPS already clean).
    2. Left-join Poverty_Rates_2023 on 5-digit FIPS.
    3. Left-join nccs_crosswalk_economic on 5-digit FIPS (geoid_2010 -> county_fips).

NOTE: `dac_status` holds the *strings* 'true'/'false', not booleans.
`food_desert_pct` has empty-string nulls -> coerced to NaN before weighting.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from crosswalk import zero_pad_fips


def _wmean(values: pd.Series, weights: pd.Series) -> float:
    """Population-weighted mean that ignores NaN values and zero/NaN weights."""
    v = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    w = pd.to_numeric(weights, errors="coerce").to_numpy(dtype=float)
    mask = ~np.isnan(v) & ~np.isnan(w) & (w > 0)
    if not mask.any() or w[mask].sum() == 0:
        return np.nan
    return float(np.average(v[mask], weights=w[mask]))


def build_need_table(dac_df: pd.DataFrame, poverty_df: pd.DataFrame,
                     nccs_econ_df: pd.DataFrame) -> pd.DataFrame:
    dac = dac_df.copy()
    dac["county_fips"] = zero_pad_fips(dac["county_fips"])
    dac["population"] = pd.to_numeric(dac["population"], errors="coerce")
    dac["_dac_true"] = (dac["dac_status"].astype("string").str.lower() == "true")

    # 1. tract -> county aggregation
    rows = []
    for fips, g in dac.groupby("county_fips"):
        rows.append({
            "county_fips": fips,
            "population": float(g["population"].sum(min_count=1)),
            "avg_food_desert_pct": _wmean(g["food_desert_pct"], g["population"]),
            "avg_housing_burden": _wmean(g["avg_housing_burden"], g["population"]),
            "dac_tract_pct": float(g["_dac_true"].mean()),
            "avg_dac_score": _wmean(g["dac_score"], g["population"]),
        })
    need = pd.DataFrame(rows)

    # 2. poverty join (one row per county on the right -> validate 1:1)
    pov = poverty_df.copy()
    pov["county_fips"] = zero_pad_fips(pov["fips_code"])
    pov["poverty_rate"] = pd.to_numeric(pov["poverty_percentage"], errors="coerce")
    pov = pov.drop_duplicates("county_fips")
    need = need.merge(
        pov[["county_fips", "poverty_rate"]],
        on="county_fips", how="left", validate="1:1",
    )

    # 3. nccs economic join (one row per county on the right -> validate 1:1)
    nccs = nccs_econ_df.copy()
    nccs["county_fips"] = zero_pad_fips(nccs["geoid_2010"])
    nccs["med_household_income"] = pd.to_numeric(
        nccs["med_household_income_adj"], errors="coerce")
    nccs["unemployment"] = pd.to_numeric(nccs["unemployment"], errors="coerce")
    nccs = nccs.drop_duplicates("county_fips")
    need = need.merge(
        nccs[["county_fips", "med_household_income", "unemployment"]],
        on="county_fips", how="left", validate="1:1",
    )

    need["county_fips"] = need["county_fips"].astype("string")
    return need


def mock_need_table(n: int = 50, seed: int = 1,
                    fips: list[str] | None = None) -> pd.DataFrame:
    """Synthetic need table for --mock runs.

    Pass `fips` (e.g. the mock capacity table's counties) to guarantee overlap so
    the inner join is non-empty; otherwise random FIPS are generated.
    """
    rng = np.random.default_rng(seed)
    if fips is None:
        fips = [f"{rng.integers(1, 56):02d}{rng.integers(1, 200):03d}" for _ in range(n)]
    fips = sorted(set(fips))
    m = len(fips)
    return pd.DataFrame({
        "county_fips": pd.array(fips, dtype="string"),
        "population": rng.integers(1_000, 2_000_000, m),
        "avg_food_desert_pct": rng.uniform(0, 40, m),
        "avg_housing_burden": rng.uniform(10, 40, m),
        "dac_tract_pct": rng.uniform(0, 1, m),
        "avg_dac_score": rng.uniform(0, 30, m),
        "poverty_rate": rng.uniform(3, 35, m),
        "med_household_income": rng.integers(25_000, 120_000, m),
        "unemployment": rng.uniform(0.02, 0.15, m),
    })
