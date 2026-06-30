"""
crosswalk.py

Automated, rules-based county-name -> FIPS resolution. No manual geographic
patches (per Checkpoint 1 grading feedback): we apply general normalization
rules and let the profiler log + auto-drop whatever doesn't match.

Resolution strategy
-------------------
1. Suffix stripping: drop "County", "Parish", "Borough", "Census Area",
   "Municipality", "City and Borough" from the NGO county names so they match
   the bare names in county_fips_lookup.
2. Case folding: lowercase both sides before matching.
3. Key on (state_abbrev, normalized_name) so same-named counties in different
   states don't collide.
4. FIPS zero-padding to 5 digits everywhere.

Known non-matches (intentionally NOT patched):
* Florida -- absent from county_fips_lookup entirely.
* Connecticut -- lookup holds the old county names while NGOs use planning-region
  names ("South Central Connecticut Planning Region"); these are different
  strings, so stripping a suffix cannot rescue them. CT auto-drops.
"""

from __future__ import annotations

import re

import pandas as pd

# Suffix tokens removed from county names (longest first so multi-word matches
# win). "Planning Region" is intentionally excluded: it does not help CT match.
_SUFFIXES = [
    "city and borough",
    "census area",
    "municipality",
    "borough",
    "parish",
    "county",
]


def normalize_county_name(name: object) -> str:
    """Lowercase, strip a known geographic suffix, collapse whitespace."""
    if not isinstance(name, str):
        return ""
    s = name.strip().lower()
    for suf in _SUFFIXES:
        if s.endswith(" " + suf):
            s = s[: -(len(suf) + 1)]
            break
    return re.sub(r"\s+", " ", s).strip()


def zero_pad_fips(series: pd.Series, width: int = 5) -> pd.Series:
    """Coerce a FIPS/GEOID column to zero-padded strings of `width` digits."""
    out = series.astype("string").str.strip()
    # Drop any trailing '.0' if a value was read as float somewhere upstream.
    out = out.str.replace(r"\.0$", "", regex=True)
    return out.str.zfill(width)


def build_lookup_index(lookup_df: pd.DataFrame) -> dict[tuple[str, str], str]:
    """(state_abbrev, normalized_county_name) -> zero-padded county_fips."""
    df = lookup_df.copy()
    df["_fips"] = zero_pad_fips(df["county_fips"])
    df["_state"] = df["state"].astype("string").str.strip().str.upper()
    df["_norm"] = df["county_name"].map(normalize_county_name)
    return {
        (st, nm): fips
        for st, nm, fips in zip(df["_state"], df["_norm"], df["_fips"])
        if nm
    }


def resolve_county_to_fips(ngo_df: pd.DataFrame,
                           lookup_df: pd.DataFrame) -> pd.DataFrame:
    """
    Return a copy of `ngo_df` with a `county_fips` column added.

    Rows that cannot be resolved get <NA> in `county_fips` (the profiler logs
    them; dropping is the profiler/builder's job, not this module's).
    """
    index = build_lookup_index(lookup_df)
    df = ngo_df.copy()
    state = df["state"].astype("string").str.strip().str.upper()
    norm = df["county"].map(normalize_county_name)
    keys = pd.Series(list(zip(state, norm)), index=df.index)
    df["county_fips"] = keys.map(index).astype("string")
    return df


def match_report(resolved_df: pd.DataFrame, top_n: int = 10) -> dict:
    """Summarize the resolution outcome for the profiler / gate."""
    total = len(resolved_df)
    matched = int(resolved_df["county_fips"].notna().sum())
    unmatched = resolved_df[resolved_df["county_fips"].isna()]
    by_state = (
        unmatched["state"].astype("string").str.upper()
        .value_counts().head(top_n).to_dict()
    )
    return {
        "total_rows": total,
        "matched_rows": matched,
        "unmatched_rows": total - matched,
        "match_rate": round(matched / total, 4) if total else 0.0,
        "top_unmatched_states": {k: int(v) for k, v in by_state.items()},
    }
