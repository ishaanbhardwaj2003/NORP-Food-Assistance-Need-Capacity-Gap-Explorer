"""
Tests for the Checkpoint 4 benchmark modules (offline, deterministic):
  * fixed_effects  -- state-FE slope recovery + no-within-variation guard
  * va_crosswalk   -- exact-first Virginia independent-city disambiguation
  * make_maps      -- state gap aggregation + non-overlapping tile grid
"""

import pandas as pd
import pytest

from fixed_effects import fit_state_fixed_effects
from va_crosswalk import (
    resolution_report,
    resolve_with_va_cities,
    va_collision_pairs,
)
from make_maps import state_gap_means, _tile_grid


STATES = [1, 6, 48]  # AL, CA, TX -- distinct 2-digit FIPS


def _panel(y_of):
    rows = []
    for s in STATES:
        for k in range(12):
            rows.append({"county_fips": f"{s:02d}{2 * k + 1:03d}",
                         "x": float(k), "y": float(y_of(s, k))})
    return pd.DataFrame(rows)


def test_fe_recovers_within_state_slope():
    # y = state_intercept + 2*x within every state -> FE slope must be 2.
    res = fit_state_fixed_effects(_panel(lambda s, k: 100 * s + 2 * k), "y", "x")
    assert res["n"] == 36 and res["n_states"] == 3
    assert "error" not in res
    assert res["fe_slope"] == pytest.approx(2.0, abs=1e-6)


def test_fe_flags_no_within_variation():
    # x constant within each state (varies only between) -> FE undefined.
    res = fit_state_fixed_effects(_panel(lambda s, k: k).assign(x=lambda d:
                                  d["county_fips"].str[:2].astype(int)), "y", "x")
    assert "error" in res


def _va_fixtures():
    lookup = pd.DataFrame({
        "county_fips": ["51760", "51159", "51600", "51059", "51036"],
        "county_name": ["Richmond City", "Richmond", "Fairfax City",
                        "Fairfax", "Charles City"],
        "state": ["VA", "VA", "VA", "VA", "VA"],
    })
    ngos = pd.DataFrame({
        "state": ["VA", "VA", "VA", "VA", "VA"],
        "county": ["Richmond city", "Richmond County", "Fairfax city",
                   "Fairfax", "Charles City County"],
    })
    return lookup, ngos


def test_va_exact_first_disambiguation():
    lookup, ngos = _va_fixtures()
    resolved = resolve_with_va_cities(ngos, lookup)
    fips = dict(zip(ngos["county"], resolved["county_fips"]))
    assert fips["Richmond city"] == "51760"          # independent city
    assert fips["Richmond County"] == "51159"         # same-stem county
    assert fips["Fairfax city"] == "51600"
    assert fips["Fairfax"] == "51059"
    assert fips["Charles City County"] == "51036"     # a real "...City" county


def test_va_collision_report():
    lookup, ngos = _va_fixtures()
    resolved = resolve_with_va_cities(ngos, lookup)
    assert {p["stem"] for p in va_collision_pairs(lookup)} == {"richmond", "fairfax"}
    rep = resolution_report(resolved, lookup)
    assert rep["by_stage"]["exact"] == 3
    assert rep["by_stage"]["normalized"] == 2
    assert rep["va_rows_resolved_to_independent_city"] == 2


def test_state_gap_means_and_tile_grid():
    panel = pd.DataFrame({
        "county_fips": ["01001", "01003", "06001"],
        "gap_score": [1.0, 3.0, -1.0],
        "food_gap_score": [0.5, 1.5, -0.5],
    })
    means = state_gap_means(panel)
    assert means.loc["AL", "gap_score"] == pytest.approx(2.0)
    assert means.loc["CA", "gap_score"] == pytest.approx(-1.0)

    grid = _tile_grid()
    assert len(set(grid.values())) == len(grid)   # every tile is unique
    assert "AK" in grid and "HI" in grid
