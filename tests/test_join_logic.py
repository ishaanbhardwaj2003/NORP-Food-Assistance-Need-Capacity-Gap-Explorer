"""Scoring: gap math, food-specific gap, component counts, NaN handling."""

import numpy as np
import pandas as pd

from join_logic import score_panel


def _panel():
    return pd.DataFrame({
        "county_fips": pd.array(["01001", "01003", "01005", "01007"], dtype="string"),
        "population": [10_000, 20_000, 30_000, 40_000],
        "ngo_count": [10, 40, 90, 160],
        "food_ngo_count": [1, 4, 9, 16],
        "total_revenue": [1e6, np.nan, 3e6, 0.0],
        "total_assets": [2e6, np.nan, 6e6, 8e6],
        "poverty_rate": [10.0, 20.0, np.nan, 40.0],
        "avg_food_desert_pct": [0.1, 0.2, 0.3, 0.4],
        "avg_housing_burden": [15.0, 25.0, 35.0, 45.0],
    })


def test_gap_is_need_minus_capacity():
    df = score_panel(_panel())
    for gap, cap in (("gap_score", "capacity_score"),
                     ("food_gap_score", "food_capacity_score")):
        err = (df[gap] - (df["need_score"] - df[cap])).abs().max()
        assert err < 1e-12


def test_per_capita_columns():
    df = score_panel(_panel())
    assert float(df["ngo_per_10k"].iloc[0]) == 10.0
    assert float(df["food_ngo_per_10k"].iloc[0]) == 1.0
    assert float(df["revenue_per_capita"].iloc[0]) == 100.0


def test_nan_revenue_propagates_not_zero():
    df = score_panel(_panel())
    assert np.isnan(df["revenue_per_capita"].iloc[1])
    # County with a genuine reported zero is different from unobserved.
    assert float(df["revenue_per_capita"].iloc[3]) == 0.0


def test_component_counts():
    df = score_panel(_panel())
    assert df["need_component_count"].tolist() == [3, 3, 2, 3]  # one missing poverty
    assert df["capacity_component_count"].tolist() == [3, 1, 3, 3]  # NaN financials


def test_scores_computed_where_components_partial():
    df = score_panel(_panel())
    # The county missing financials still gets a capacity score from ngo_per_10k.
    assert not np.isnan(df["capacity_score"].iloc[1])
