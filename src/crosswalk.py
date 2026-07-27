"""
crosswalk.py

Automated, rules-based county-name -> FIPS resolution. No manual geographic
patches (per Checkpoint 1 grading feedback): we apply general normalization
rules and let the profiler log + auto-drop whatever doesn't match.

Final-checkpoint revision: exact-first, two-stage resolution
------------------------------------------------------------
The Checkpoint 3 resolver stripped a fixed suffix list and keyed on the
stripped name. Auditing the TA benchmark branch (ai-suggestions/cp4, commit
c26faba) surfaced the real Virginia failure mode: the lookup stores most VA
independent cities as BARE names ("Alexandria", "Virginia Beach") while the
NGO table says "Alexandria City" -- a case neither the old resolver nor the
benchmark's exact-only pass could bridge, which silently dropped all 34
independent cities (5,287 rows). The two-stage design below fixes it:

1. EXACT: match (state, folded_full_name) against the lookup with NO suffix
   stripping. This keeps same-stem pairs apart ("Fairfax City" 51600 vs
   "Fairfax" county 51059; same for Richmond/Franklin/Roanoke) and resolves
   the two genuine "... City" counties (Charles City 51036, James City 51095)
   verbatim. The exact-first concept and the collision audit
   (va_collision_pairs) are adapted from the benchmark branch.
2. FALLBACK: strip at most ONE trailing geographic suffix -- now including
   bare "city" -- and rematch against the same index. "Alexandria City" ->
   "alexandria" -> 51510. Because every ambiguous "... City" form exists
   verbatim in the lookup, the exact stage always wins before the strip can
   misdirect one (machine-checked by the verifier).

Text folding (applied to BOTH sides before any matching):
* lowercase + whitespace collapse;
* mojibake repair: county_fips_lookup itself contains UTF-8-read-as-Latin-1
  damage ("DoÃ±a Ana"); a conservative latin-1 -> utf-8 round-trip repairs it
  only when the round-trip succeeds AND changes the string;
* Unicode NFKD accent folding ("Doña Ana" -> "dona ana"), so the repaired
  lookup and the clean NGO spelling meet at the same key.

Known non-matches (intentionally NOT patched):
* Florida -- absent from county_fips_lookup entirely.
* Connecticut -- lookup holds the old county names while NGOs use
  planning-region names; different strings, so CT auto-drops.
"""

from __future__ import annotations

import re
import unicodedata

import pandas as pd

# Suffix tokens removed by the FALLBACK stage only (longest first so multi-word
# matches win; "city and borough" must stay ahead of bare "city").
_SUFFIXES = [
    "city and borough",
    "census area",
    "municipality",
    "borough",
    "parish",
    "county",
    "city",
]

EXACT, NORMALIZED, UNMATCHED = "exact", "normalized", "unmatched"

# Genuine counties whose own name ends in "City" (they are NOT independent
# cities); used by the va_collision_pairs audit, never by resolution itself.
_CITY_NAMED_COUNTIES = {"charles city", "james city"}
_CITY_SUFFIX = " city"


def _repair_mojibake(s: str) -> str:
    """Undo UTF-8-bytes-read-as-Latin-1 damage ("DoÃ±a" -> "Doña").

    Conservative: the repair is kept only when the latin-1 encode AND utf-8
    decode both succeed and the result differs. Pure-ASCII strings round-trip
    unchanged; genuine Latin-1 text ("Café") fails the utf-8 decode and is
    left alone.
    """
    try:
        repaired = s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s
    return repaired if repaired != s else s


def fold_name(name: object) -> str:
    """Canonical text form: mojibake repair, accent fold, lowercase, collapse
    whitespace. NO suffix stripping (that is the fallback stage's job)."""
    if not isinstance(name, str):
        return ""
    s = _repair_mojibake(name)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.strip().lower()
    return re.sub(r"\s+", " ", s)


def strip_suffix(folded: str) -> str:
    """Remove at most one trailing geographic suffix from an already-folded
    name ("alexandria city" -> "alexandria"; "charles city county" ->
    "charles city")."""
    for suf in _SUFFIXES:
        if folded.endswith(" " + suf):
            return folded[: -(len(suf) + 1)]
    return folded


def normalize_county_name(name: object) -> str:
    """Folded + one-suffix-stripped form (the fallback-stage key)."""
    return strip_suffix(fold_name(name))


def zero_pad_fips(series: pd.Series, width: int = 5) -> pd.Series:
    """Coerce a FIPS/GEOID column to zero-padded strings of `width` digits."""
    out = series.astype("string").str.strip()
    # Drop any trailing '.0' if a value was read as float somewhere upstream.
    out = out.str.replace(r"\.0$", "", regex=True)
    return out.str.zfill(width)


def build_lookup_index(lookup_df: pd.DataFrame) -> dict[tuple[str, str], str]:
    """(state_abbrev, folded_full_county_name) -> zero-padded county_fips.

    No suffix stripping in the index: bare "Alexandria" stays bare and
    "Fairfax City" stays distinct from "Fairfax". Raises ValueError if two
    lookup rows fold to the same key with different FIPS (currently zero;
    a collision would make resolution ambiguous and must fail loudly).
    """
    df = lookup_df.copy()
    df["_fips"] = zero_pad_fips(df["county_fips"])
    df["_state"] = df["state"].astype("string").str.strip().str.upper()
    df["_norm"] = df["county_name"].map(fold_name)
    index: dict[tuple[str, str], str] = {}
    collisions: dict[tuple[str, str], set[str]] = {}
    for st, nm, fips in zip(df["_state"], df["_norm"], df["_fips"]):
        if not nm:
            continue
        key = (st, nm)
        if key in index and index[key] != fips:
            collisions.setdefault(key, {index[key]}).add(fips)
        index[key] = fips
    if collisions:
        detail = "; ".join(f"{k} -> {sorted(v)}" for k, v in sorted(collisions.items()))
        raise ValueError(f"county_fips_lookup has ambiguous folded keys: {detail}")
    return index


def resolve_county_to_fips(ngo_df: pd.DataFrame,
                           lookup_df: pd.DataFrame) -> pd.DataFrame:
    """
    Return a copy of `ngo_df` with `county_fips` and `_match_stage` columns.

    Stage 1 (exact): (state, fold_name(county)) against the lookup index.
    Stage 2 (normalized): same key with one trailing suffix stripped.
    Rows that resolve at neither stage get <NA> / 'unmatched' (the profiler
    logs them; dropping is the profiler/builder's job, not this module's).
    """
    index = build_lookup_index(lookup_df)
    df = ngo_df.copy()
    state = df["state"].astype("string").str.strip().str.upper()
    folded = df["county"].map(fold_name)

    exact_keys = pd.Series(list(zip(state, folded)), index=df.index)
    fips = exact_keys.map(index).astype("string")
    stage = pd.Series(EXACT, index=df.index, dtype="string").where(
        fips.notna(), UNMATCHED)

    miss = fips.isna()
    if miss.any():
        stripped_keys = pd.Series(
            list(zip(state[miss], folded[miss].map(strip_suffix))),
            index=df.index[miss])
        fallback = stripped_keys.map(index).astype("string")
        fips.loc[miss] = fallback
        stage.loc[miss & fips.notna()] = NORMALIZED

    df["county_fips"] = fips
    df["_match_stage"] = stage
    return df


def va_collision_pairs(lookup_df: pd.DataFrame) -> list[dict]:
    """Virginia independent-city / same-stem-county pairs that exact-first
    matching keeps apart (audit evidence; adapted from the TA benchmark
    branch ai-suggestions/cp4, commit c26faba)."""
    va = lookup_df[lookup_df["state"].astype("string").str.upper() == "VA"].copy()
    va["_fips"] = zero_pad_fips(va["county_fips"])
    va["_name"] = va["county_name"].map(fold_name)
    cities = {n[: -len(_CITY_SUFFIX)]: (n, f)
              for n, f in zip(va["_name"], va["_fips"])
              if n.endswith(_CITY_SUFFIX) and n not in _CITY_NAMED_COUNTIES}
    counties = {n: f for n, f in zip(va["_name"], va["_fips"])
                if not n.endswith(_CITY_SUFFIX)}
    pairs = []
    for stem, (city_name, city_fips) in sorted(cities.items()):
        if stem in counties:
            pairs.append({
                "stem": stem,
                "independent_city": city_name, "city_fips": city_fips,
                "county": stem, "county_fips": counties[stem],
            })
    return pairs


def match_report(resolved_df: pd.DataFrame, top_n: int = 10) -> dict:
    """Summarize the resolution outcome for the profiler / gate."""
    total = len(resolved_df)
    matched = int(resolved_df["county_fips"].notna().sum())
    unmatched = resolved_df[resolved_df["county_fips"].isna()]
    by_state = (
        unmatched["state"].astype("string").str.upper()
        .value_counts().head(top_n).to_dict()
    )
    report = {
        "total_rows": total,
        "matched_rows": matched,
        "unmatched_rows": total - matched,
        "match_rate": round(matched / total, 4) if total else 0.0,
        "top_unmatched_states": {k: int(v) for k, v in by_state.items()},
    }
    if "_match_stage" in resolved_df.columns:
        stage = resolved_df["_match_stage"]
        report["by_stage"] = {s: int((stage == s).sum())
                              for s in (EXACT, NORMALIZED, UNMATCHED)}
    return report
