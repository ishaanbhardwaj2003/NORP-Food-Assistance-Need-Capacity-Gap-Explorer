"""F9 filing selection, missing-vs-zero financials, and coverage columns."""

import numpy as np
import pandas as pd

from build_capacity_table import (
    build_capacity_table, mock_capacity_table, select_one_filing_per_ein,
)


def _f9(rows):
    return pd.DataFrame(rows, columns=["org_ein", "tax_year",
                                       "f9_01_rev_tot_cy", "f9_01_nafb_tot_eoy"])


def _identity_crosswalk(fips_by_county):
    def fn(df):
        out = df.copy()
        out["county_fips"] = out["county"].map(fips_by_county).astype("string")
        return out
    return fn


def test_latest_tax_year_wins():
    f9 = _f9([("000000001", 2019, 100.0, 10.0),
              ("000000001", 2022, 200.0, 20.0)])
    one = select_one_filing_per_ein(f9)
    assert len(one) == 1
    assert float(one["f9_01_rev_tot_cy"].iloc[0]) == 200.0


def test_same_year_duplicate_keeps_largest_revenue():
    f9 = _f9([("000000001", 2022, 50.0, 5.0),
              ("000000001", 2022, 300.0, 30.0)])
    one = select_one_filing_per_ein(f9)
    assert len(one) == 1
    assert float(one["f9_01_rev_tot_cy"].iloc[0]) == 300.0
    # The whole ROW is kept, not per-column maxima.
    assert float(one["f9_01_nafb_tot_eoy"].iloc[0]) == 30.0


def test_duplicates_never_summed():
    f9 = _f9([("000000001", 2022, 100.0, 10.0),
              ("000000001", 2022, 100.0, 10.0)])
    one = select_one_filing_per_ein(f9)
    assert float(one["f9_01_rev_tot_cy"].iloc[0]) == 100.0  # not 200


def test_missing_financials_stay_nan_not_zero():
    ngos = pd.DataFrame({
        "ein": ["000000001", "000000002"],
        "county": ["alpha", "beta"],
        "category": ["Other", "Other"],
    })
    f9 = _f9([("000000001", 2022, 500.0, 50.0)])  # beta county: no filer
    cap = build_capacity_table(
        ngos, f9, _identity_crosswalk({"alpha": "01001", "beta": "01003"}))
    cap = cap.set_index("county_fips")
    assert float(cap.loc["01001", "total_revenue"]) == 500.0
    assert np.isnan(cap.loc["01003", "total_revenue"])   # unobserved != 0
    assert np.isnan(cap.loc["01003", "total_assets"])


def test_reported_zero_survives_as_zero():
    ngos = pd.DataFrame({"ein": ["000000001"], "county": ["alpha"],
                         "category": ["Other"]})
    f9 = _f9([("000000001", 2022, 0.0, 0.0)])
    cap = build_capacity_table(ngos, f9, _identity_crosswalk({"alpha": "01001"}))
    assert float(cap["total_revenue"].iloc[0]) == 0.0


def test_coverage_columns():
    ngos = pd.DataFrame({
        "ein": ["000000001", "000000002", "000000003", "000000004"],
        "county": ["alpha"] * 4,
        "category": ["Food, Agriculture and Nutrition", "Other", "Other", "Other"],
    })
    f9 = _f9([("000000001", 2022, 10.0, 1.0), ("000000003", 2022, 20.0, 2.0)])
    cap = build_capacity_table(ngos, f9, _identity_crosswalk({"alpha": "01001"}))
    row = cap.iloc[0]
    assert int(row["ngo_count"]) == 4
    assert int(row["food_ngo_count"]) == 1
    assert int(row["matched_filer_count"]) == 2
    assert float(row["filer_coverage_rate"]) == 0.5


def test_mock_capacity_table_semantics():
    mock = mock_capacity_table()
    unmatched = mock["matched_filer_count"] == 0
    assert mock.loc[unmatched, "total_revenue"].isna().all()
    assert (mock["matched_filer_count"] <= mock["ngo_count"]).all()
    assert set(mock.columns) >= {"county_fips", "ngo_count", "food_ngo_count",
                                 "matched_filer_count", "filer_coverage_rate",
                                 "total_revenue", "total_assets"}
