"""
Tests for the exact-first, two-stage crosswalk (final-checkpoint revision).

The fixture deliberately includes the case the TA benchmark branch never
tested: a VA independent city stored BARE in the lookup ("Alexandria") while
the NGO side says "Alexandria City". That is the real shape of the committed
county_fips_lookup and the reason 34 VA cities were dropped through CP3.
"""

import pandas as pd
import pytest

from crosswalk import (
    EXACT,
    NORMALIZED,
    UNMATCHED,
    build_lookup_index,
    fold_name,
    match_report,
    normalize_county_name,
    resolve_county_to_fips,
    strip_suffix,
    va_collision_pairs,
)


def _lookup():
    rows = [
        ("51510", "Alexandria", "VA"),      # independent city stored BARE
        ("51600", "Fairfax City", "VA"),    # ambiguous pair: city ...
        ("51059", "Fairfax", "VA"),         # ... vs same-stem county
        ("51760", "Richmond City", "VA"),
        ("51159", "Richmond", "VA"),
        ("51036", "Charles City", "VA"),    # a genuine "... City" COUNTY
        ("01001", "Autauga", "AL"),
        ("22001", "Acadia", "LA"),
        ("35013", "DoÃ±a Ana", "NM"),       # mojibake exactly as committed
        ("09003", "Hartford", "CT"),        # old CT county name
    ]
    return pd.DataFrame(rows, columns=["county_fips", "county_name", "state"])


def _resolve(pairs):
    ngos = pd.DataFrame(pairs, columns=["state", "county"])
    return resolve_county_to_fips(ngos, _lookup())


# -- text folding ------------------------------------------------------------

def test_fold_name_repairs_mojibake_and_accents():
    assert fold_name("DoÃ±a Ana") == "dona ana"      # lookup's damaged form
    assert fold_name("Doña Ana") == "dona ana"       # NGO file's clean form


def test_fold_name_leaves_ascii_alone():
    assert fold_name("Virginia  Beach City") == "virginia beach city"
    assert fold_name(None) == ""


def test_strip_suffix_one_pass_longest_first():
    assert strip_suffix("alexandria city") == "alexandria"
    assert strip_suffix("charles city county") == "charles city"
    assert strip_suffix("juneau city and borough") == "juneau"
    assert strip_suffix("acadia parish") == "acadia"
    assert normalize_county_name("Doña Ana County") == "dona ana"


# -- resolution: the real VA failure mode ------------------------------------

def test_bare_lookup_city_recovered_via_fallback():
    res = _resolve([("VA", "Alexandria City")])
    assert res["county_fips"].iloc[0] == "51510"
    assert res["_match_stage"].iloc[0] == NORMALIZED


def test_exact_first_keeps_city_county_pairs_apart():
    res = _resolve([
        ("VA", "Fairfax City"), ("VA", "Fairfax County"), ("VA", "Fairfax"),
        ("VA", "Richmond City"), ("VA", "Richmond County"),
    ])
    got = dict(zip(res["county"], res["county_fips"]))
    assert got["Fairfax City"] == "51600"
    assert got["Fairfax County"] == "51059"
    assert got["Fairfax"] == "51059"
    assert got["Richmond City"] == "51760"
    assert got["Richmond County"] == "51159"
    stages = dict(zip(res["county"], res["_match_stage"]))
    assert stages["Fairfax City"] == EXACT
    assert stages["Fairfax County"] == NORMALIZED


def test_city_named_county_resolves_to_county():
    res = _resolve([("VA", "Charles City County"), ("VA", "Charles City")])
    assert list(res["county_fips"]) == ["51036", "51036"]


def test_mojibake_lookup_meets_clean_ngo_spelling():
    res = _resolve([("NM", "Doña Ana County")])
    assert res["county_fips"].iloc[0] == "35013"


def test_regressions_suffix_states_still_match():
    res = _resolve([("AL", "Autauga County"), ("LA", "Acadia Parish")])
    assert list(res["county_fips"]) == ["01001", "22001"]


def test_ct_planning_region_still_auto_drops():
    res = _resolve([("CT", "South Central Connecticut Planning Region")])
    assert res["county_fips"].isna().all()
    assert res["_match_stage"].iloc[0] == UNMATCHED


# -- index integrity + audit -------------------------------------------------

def test_lookup_index_is_fold_only_and_unique():
    index = build_lookup_index(_lookup())
    assert index[("VA", "alexandria")] == "51510"
    assert index[("VA", "fairfax city")] == "51600"
    assert index[("NM", "dona ana")] == "35013"
    assert len(index) == len(_lookup())


def test_colliding_folded_keys_raise():
    bad = pd.concat([
        _lookup(),
        pd.DataFrame([("51999", "  ALEXANDRIA ", "VA")],
                     columns=["county_fips", "county_name", "state"]),
    ])
    with pytest.raises(ValueError, match="ambiguous folded keys"):
        build_lookup_index(bad)


def test_va_collision_pairs_audit():
    pairs = va_collision_pairs(_lookup())
    stems = {p["stem"] for p in pairs}
    assert stems == {"fairfax", "richmond"}          # charles city held out
    by_stem = {p["stem"]: p for p in pairs}
    assert by_stem["fairfax"]["city_fips"] == "51600"
    assert by_stem["fairfax"]["county_fips"] == "51059"


def test_match_report_carries_stages():
    res = _resolve([
        ("VA", "Fairfax City"),        # exact
        ("VA", "Alexandria City"),     # normalized
        ("CT", "Capitol Planning Region"),  # unmatched
    ])
    rpt = match_report(res)
    assert rpt["total_rows"] == 3
    assert rpt["matched_rows"] == 2
    assert rpt["by_stage"] == {EXACT: 1, NORMALIZED: 1, UNMATCHED: 1}
    assert rpt["top_unmatched_states"] == {"CT": 1}
