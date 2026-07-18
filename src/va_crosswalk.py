"""
va_crosswalk.py

Checkpoint 4 deliverable #2: an automated *exact-first* county-name -> FIPS
crosswalk for Virginia's independent cities.

Why Virginia is special
-----------------------
Virginia has 38 "independent cities" that are county-equivalents with their own
5-digit FIPS, and several of them share a stem with an ordinary county in the
same state. In the committed county_fips_lookup these collide by stem:

    Richmond City   51760   vs.  Richmond (County)  51159
    Fairfax City    51600   vs.  Fairfax  (County)  51059
    Franklin City   51620   vs.  Franklin (County)  51067
    Roanoke City    51770   vs.  Roanoke  (County)  51161

and two genuine counties carry a "City" token in their own name and must NOT be
treated as independent cities:

    Charles City (County)   51036
    James City   (County)   51095

The Checkpoint 3 crosswalk (src/crosswalk.py) normalizes by stripping a fixed
suffix list and keying on (state, normalized_name). That is safe today only
because bare "city" is deliberately left out of the suffix list; the moment any
future edit adds "city" to that list, all four independent cities silently fold
into their same-stem county and corrupt the Virginia aggregates.

Strategy (exact-first, then fall back)
--------------------------------------
1. EXACT: match the full, un-stripped (state, collapsed_name) against the
   lookup first. This resolves "Richmond City" -> 51760 and "Charles City" ->
   51036 verbatim, independent of any suffix policy, and never confuses a
   "... City" name with its same-stem county.
2. NORMALIZED FALLBACK: for anything the exact pass misses, defer to the
   Checkpoint 3 rules-based resolver (suffix stripping + (state, name) key).
3. AUDIT: every row is tagged exact / normalized / unmatched, and a Virginia
   report lists the independent-city vs county collision pairs that the exact
   pass disambiguated, so the gate/verifier can machine-check the fix.

Deterministic and offline; reuses src/crosswalk.py so there is one source of
truth for normalization. No statistics and no LLM are involved.
"""

from __future__ import annotations

import re

import pandas as pd

from crosswalk import (
    build_lookup_index,
    normalize_county_name,
    resolve_county_to_fips,
    zero_pad_fips,
)

# Independent cities carry these tokens; genuine "... City" counties are held
# out by exact matching (they resolve to their own verbatim lookup entry first).
_INDEPENDENT_CITY_COUNTIES = {"charles city", "james city"}  # NOT cities

EXACT, NORMALIZED, UNMATCHED = "exact", "normalized", "unmatched"


def collapse_name(name: object) -> str:
    """Lowercase + whitespace-collapse WITHOUT stripping any suffix, so
    'Richmond City' and 'Richmond' stay distinct keys."""
    if not isinstance(name, str):
        return ""
    return re.sub(r"\s+", " ", name.strip().lower())


def build_exact_index(lookup_df: pd.DataFrame) -> dict[tuple[str, str], str]:
    """(state_abbrev, collapsed_full_name) -> zero-padded county_fips, with no
    suffix stripping. Distinguishes independent cities from their counties."""
    df = lookup_df.copy()
    fips = zero_pad_fips(df["county_fips"])
    state = df["state"].astype("string").str.strip().str.upper()
    name = df["county_name"].map(collapse_name)
    return {(s, n): f for s, n, f in zip(state, name, fips) if n}


def va_collision_pairs(lookup_df: pd.DataFrame) -> list[dict]:
    """From the real lookup, list Virginia independent-city / same-stem-county
    pairs that exact-first matching keeps apart (audit evidence)."""
    va = lookup_df[lookup_df["state"].astype("string").str.upper() == "VA"].copy()
    va["_fips"] = zero_pad_fips(va["county_fips"])
    va["_name"] = va["county_name"].map(collapse_name)
    cities = {re.sub(r"\s+city$", "", n): (n, f)
              for n, f in zip(va["_name"], va["_fips"]) if n.endswith(" city")}
    counties = {n: f for n, f in zip(va["_name"], va["_fips"])
                if not n.endswith(" city") and n not in _INDEPENDENT_CITY_COUNTIES}
    pairs = []
    for stem, (city_name, city_fips) in sorted(cities.items()):
        if stem in counties:
            pairs.append({
                "stem": stem,
                "independent_city": city_name, "city_fips": city_fips,
                "county": stem, "county_fips": counties[stem],
            })
    return pairs


def resolve_with_va_cities(ngo_df: pd.DataFrame,
                           lookup_df: pd.DataFrame) -> pd.DataFrame:
    """Return `ngo_df` + `county_fips` + `_match_stage`, resolving exact full
    names first (independent cities / '...City' counties) and deferring the
    remainder to the Checkpoint 3 normalized resolver."""
    exact = build_exact_index(lookup_df)
    df = ngo_df.copy()
    state = df["state"].astype("string").str.strip().str.upper()
    full = df["county"].map(collapse_name)
    keys = pd.Series(list(zip(state, full)), index=df.index)

    fips = keys.map(exact).astype("string")
    stage = pd.Series(EXACT, index=df.index).where(fips.notna(), UNMATCHED)

    # Fallback: normalized resolver for the exact-miss rows only.
    miss = fips.isna()
    if miss.any():
        fallback = resolve_county_to_fips(df.loc[miss, ["state", "county"]],
                                          lookup_df)["county_fips"]
        fips.loc[miss] = fallback.values
        stage.loc[miss & fips.notna()] = NORMALIZED

    df["county_fips"] = fips
    df["_match_stage"] = stage.where(fips.notna(), UNMATCHED)
    return df


def resolution_report(resolved_df: pd.DataFrame,
                      lookup_df: pd.DataFrame) -> dict:
    """Stage counts overall + for Virginia, plus the collision pairs kept apart.
    `resolved_df` must carry `state`, `county_fips`, and `_match_stage`."""
    stage = resolved_df["_match_stage"]
    is_va = resolved_df["state"].astype("string").str.upper() == "VA"
    va_city_fips = {p["city_fips"] for p in va_collision_pairs(lookup_df)}
    return {
        "total_rows": int(len(resolved_df)),
        "by_stage": {s: int((stage == s).sum())
                     for s in (EXACT, NORMALIZED, UNMATCHED)},
        "va_rows": int(is_va.sum()),
        "va_by_stage": {s: int(((stage == s) & is_va).sum())
                        for s in (EXACT, NORMALIZED, UNMATCHED)},
        "va_rows_resolved_to_independent_city": int(
            resolved_df["county_fips"].isin(va_city_fips).sum()),
        "collision_pairs_disambiguated": va_collision_pairs(lookup_df),
    }
