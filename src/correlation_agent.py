"""
correlation_agent.py

Checkpoint 3: the LLM-assisted analysis layer on top of the deterministic panel.

Two LLM touchpoints, both strictly advisory (Python remains the source of truth
for every statistic):

1. Correlation-candidate generation -- the LLM reads the panel *schema*
   (column names + descriptive stats, never raw rows) and proposes
   need-vs-capacity variable pairs with hypotheses and expected signs.
   Python then computes Pearson + Spearman for EVERY need x capacity pair
   (exhaustive grid), so the LLM only prioritizes and hypothesizes -- it
   cannot invent, skip, or skew a statistic.

2. Gate review -- the LLM reads the profiler log and issues an advisory
   second-opinion on the rule-based proceed/proceed_with_warning/stop gate.
   The rule-based verdict remains authoritative; disagreement is logged,
   never acted on.

Reproducibility: every LLM response is cached to
data/output/llm_candidates.json (committed to the repo). Offline mode (the
default) replays the cached artifact, so the full Checkpoint 3 analysis
re-runs end-to-end without an API key. The cache carries canonical hashes of
the schema context and gate it was generated against; a replay against a
changed panel/gate is rejected as stale (override with allow_stale for scratch
runs). `--live` regenerates the cache through the Anthropic API.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

import pandas as pd
from scipy.stats import pearsonr, spearmanr

DEFAULT_MODEL = "claude-opus-4-8"
PROMPT_VERSION = "2"
MIN_CANDIDATES, MAX_CANDIDATES = 5, 8

# The need/capacity split of the panel's analyzable columns. Per-capita
# capacity variables are used (raw totals just proxy population size).
NEED_VARS = {
    "poverty_rate": "county poverty rate, % (Poverty_Rates_2023)",
    "avg_food_desert_pct": ("population-weighted share of residents in "
                            "food-desert tracts, 0-1 scale"),
    "avg_housing_burden": "population-weighted mean tract housing-cost burden, %",
    "dac_tract_pct": "share of tracts flagged as disadvantaged communities",
    "avg_dac_score": "population-weighted mean DAC score",
    "med_household_income": ("median household income, $ (NCCS/ACS) -- an "
                             "INVERSE-need/context measure: high income = low need"),
    "unemployment": "unemployment rate (NCCS/ACS)",
}
CAPACITY_VARS = {
    "ngo_per_10k": ("registered nonprofits per 10k residents (ordered, "
                    "truncated ~1M-row NGO extract)"),
    "food_ngo_per_10k": "'Food, Agriculture and Nutrition' nonprofits per 10k residents",
    "revenue_per_capita": ("990/990EZ/990PF-filer total revenue per capita, $ "
                           "(sparse ~3.6% filer match; NaN where no filer)"),
    "assets_per_capita": ("990/990EZ/990PF-filer net assets per capita, $ "
                          "(sparse ~3.6% filer match; NaN where no filer)"),
}


def add_derived_columns(panel: pd.DataFrame) -> pd.DataFrame:
    """Backfill food_ngo_per_10k for panels built before it was native."""
    df = panel.copy()
    if "food_ngo_per_10k" not in df.columns:
        pop = pd.to_numeric(df["population"], errors="coerce").replace(0, pd.NA)
        df["food_ngo_per_10k"] = (
            pd.to_numeric(df["food_ngo_count"], errors="coerce") / pop * 10_000
        )
    return df


def build_schema_context(panel: pd.DataFrame) -> dict:
    """Column-level descriptive stats for the LLM prompt. No raw rows leave
    the machine -- only names, descriptions, and five summary numbers."""
    ctx = {"need_vars": {}, "capacity_vars": {}, "n_counties": int(len(panel))}
    for group, vars_ in (("need_vars", NEED_VARS), ("capacity_vars", CAPACITY_VARS)):
        for col, desc in vars_.items():
            s = pd.to_numeric(panel[col], errors="coerce")
            ctx[group][col] = {
                "description": desc,
                "n_nonnull": int(s.notna().sum()),
                "mean": round(float(s.mean()), 3),
                "median": round(float(s.median()), 3),
                "min": round(float(s.min()), 3),
                "max": round(float(s.max()), 3),
            }
    return ctx


def compute_all_correlations(panel: pd.DataFrame) -> pd.DataFrame:
    """Pearson + Spearman for the full need x capacity grid. This is the
    authoritative statistics table; the LLM never computes a number."""
    rows = []
    for need_var, cap_var in product(NEED_VARS, CAPACITY_VARS):
        x = pd.to_numeric(panel[need_var], errors="coerce")
        y = pd.to_numeric(panel[cap_var], errors="coerce")
        ok = x.notna() & y.notna()
        n = int(ok.sum())
        if n < 30:  # too few counties for a meaningful estimate
            continue
        if x[ok].std(ddof=0) == 0 or y[ok].std(ddof=0) == 0:
            continue  # constant column: correlation undefined, never call SciPy
        pr, pp = pearsonr(x[ok], y[ok])
        sr, sp = spearmanr(x[ok], y[ok])
        rows.append({
            "need_var": need_var,
            "capacity_var": cap_var,
            "pearson_r": round(float(pr), 4),
            "pearson_p": float(pp),
            "spearman_r": round(float(sr), 4),
            "spearman_p": float(sp),
            "n_counties": n,
        })
    out = pd.DataFrame(rows)
    return out.reindex(out["spearman_r"].abs().sort_values(ascending=False).index)


# -- LLM layer (live) --------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are the correlation-candidate agent in a county-level data pipeline "
    "that maps where food-related community need outpaces nonprofit capacity. "
    "You are given only a schema (column names, descriptions, summary stats) -- "
    "never raw data. Python computes every statistic; your job is to propose "
    "which need-vs-capacity variable pairs are most sociologically interesting "
    "to test, with a hypothesis and an expected correlation sign for each, and "
    "to review the data-quality gate verdict. Respond with JSON only."
)


def _proposal_prompt(schema_ctx: dict, gate: dict) -> str:
    return (
        "Panel schema (need-side and capacity-side variables over "
        f"{schema_ctx['n_counties']} US counties):\n"
        + json.dumps(schema_ctx, indent=2)
        + "\n\nRule-based profiler gate verdict for this run:\n"
        + json.dumps(gate, indent=2)
        + "\n\nReturn a JSON object with exactly these keys:\n"
        '  "candidates": 5-8 objects, each {"need_var": <need column>, '
        '"capacity_var": <capacity column>, "hypothesis": <=40 words, '
        '"expected_sign": "positive"|"negative"}\n'
        '  "gate_review": {"verdict": "proceed"|"proceed_with_warning"|"stop", '
        '"rationale": <=60 words}  (advisory second opinion on the gate)\n'
        '  "narrative_notes": <=120 words of analysis guidance for the findings '
        "summary (plain text, no numbers -- Python fills in all statistics).\n"
        "Use only column names that appear in the schema."
    )


def _extract_json(text: str) -> dict:
    """Parse the model's JSON, tolerating a ```json fence."""
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    return json.loads(m.group(1) if m else text)


def _proposal_schema() -> dict:
    """JSON Schema for schema-constrained structured output on --live calls.
    Column names and signs are enum-constrained so the model cannot emit an
    unknown column; validate_proposal() still re-checks everything after."""
    return {
        "type": "object",
        "properties": {
            "candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "need_var": {"type": "string", "enum": list(NEED_VARS)},
                        "capacity_var": {"type": "string", "enum": list(CAPACITY_VARS)},
                        "hypothesis": {"type": "string"},
                        "expected_sign": {"type": "string",
                                          "enum": ["positive", "negative"]},
                    },
                    "required": ["need_var", "capacity_var", "hypothesis",
                                 "expected_sign"],
                    "additionalProperties": False,
                },
            },
            "gate_review": {
                "type": "object",
                "properties": {
                    "verdict": {"type": "string",
                                "enum": ["proceed", "proceed_with_warning", "stop"]},
                    "rationale": {"type": "string"},
                },
                "required": ["verdict", "rationale"],
                "additionalProperties": False,
            },
            "narrative_notes": {"type": "string"},
        },
        "required": ["candidates", "gate_review", "narrative_notes"],
        "additionalProperties": False,
    }


def propose_candidates_live(schema_ctx: dict, gate: dict,
                            model: str = DEFAULT_MODEL) -> dict:
    """One Anthropic API call proposing candidates + gate review + notes.
    Raises a RuntimeError with a clear message when no API credential exists."""
    try:
        import anthropic
    except ImportError as e:
        raise RuntimeError("pip install anthropic (required for --live)") from e

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=_SYSTEM_PROMPT,
            output_config={"format": {"type": "json_schema",
                                      "schema": _proposal_schema()}},
            messages=[{"role": "user", "content": _proposal_prompt(schema_ctx, gate)}],
        )
    except anthropic.AuthenticationError as e:
        raise RuntimeError(
            "Anthropic API key invalid. Set ANTHROPIC_API_KEY or run offline "
            "(default) to replay the committed cache."
        ) from e
    except Exception as e:  # missing key raises at construction time
        raise RuntimeError(
            f"Live LLM call failed ({e}). Set ANTHROPIC_API_KEY, or run "
            "without --live to replay data/output/llm_candidates.json."
        ) from e

    text = next(b.text for b in response.content if b.type == "text")
    return _extract_json(text)


def validate_proposal(proposal: dict) -> dict:
    """Hard-validate the LLM output: drop any candidate naming an unknown
    column, deduplicate repeated pairs, normalize expected_sign, and enforce
    the requested candidate count (truncate above MAX_CANDIDATES; flag below
    MIN_CANDIDATES). The agent can suggest, not inject. A `validation` block
    records what was cleaned so the cleanup itself is auditable."""
    raw = proposal.get("candidates", [])
    seen, clean, dropped_unknown, dropped_dupes = set(), [], 0, 0
    for c in raw:
        if not (c.get("need_var") in NEED_VARS and c.get("capacity_var") in CAPACITY_VARS):
            dropped_unknown += 1
            continue
        key = (c["need_var"], c["capacity_var"])
        if key in seen:
            dropped_dupes += 1
            continue
        seen.add(key)
        sign = str(c.get("expected_sign", "")).lower()
        c["expected_sign"] = sign if sign in ("positive", "negative") else "unspecified"
        clean.append(c)
    truncated = max(0, len(clean) - MAX_CANDIDATES)
    clean = clean[:MAX_CANDIDATES]
    proposal["candidates"] = clean
    proposal["validation"] = {
        "n_raw": len(raw),
        "n_valid": len(clean),
        "dropped_unknown_columns": dropped_unknown,
        "dropped_duplicate_pairs": dropped_dupes,
        "truncated_over_max": truncated,
        "count_in_range": MIN_CANDIDATES <= len(clean) <= MAX_CANDIDATES,
    }
    review = proposal.get("gate_review", {})
    if review.get("verdict") not in ("proceed", "proceed_with_warning", "stop"):
        review["verdict"] = "unspecified"
    proposal["gate_review"] = review
    return proposal


def canonical_hash(obj: dict) -> str:
    """SHA-256 of the canonical (sorted-key, minified) JSON serialization."""
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _integrity_metadata(schema_ctx: dict, gate: dict) -> dict:
    return {
        "prompt_version": PROMPT_VERSION,
        "schema_context_sha256": canonical_hash(schema_ctx),
        "gate_sha256": canonical_hash(gate),
    }


def check_cache_integrity(artifact: dict, schema_ctx: dict, gate: dict) -> list[str]:
    """Compare the cache's recorded hashes against the CURRENT panel schema
    and gate. Returns a list of mismatch descriptions (empty = fresh)."""
    meta = artifact.get("metadata", {})
    expected = _integrity_metadata(schema_ctx, gate)
    problems = []
    for key, want in expected.items():
        have = meta.get(key)
        if have != want:
            problems.append(f"{key}: cache has {have!r}, current run is {want!r}")
    return problems


def get_proposal(schema_ctx: dict, gate: dict, cache_path: str | Path,
                 live: bool = False, model: str = DEFAULT_MODEL,
                 allow_stale: bool = False) -> dict:
    """Live: call the API and (re)write the cache. Offline: replay the cache,
    rejecting it if it was generated against a different panel schema or gate
    (pass allow_stale=True only for scratch/smoke runs)."""
    cache_path = Path(cache_path)
    if live:
        raw = propose_candidates_live(schema_ctx, gate, model)
        artifact = {
            "metadata": {
                "mode": "live",
                "source": "live_api",
                "model": model,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                **_integrity_metadata(schema_ctx, gate),
                "note": "LLM proposals are advisory; Python computes all statistics.",
            },
            "schema_context": schema_ctx,
            "proposal": validate_proposal(raw),
        }
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(artifact, indent=2))
        return artifact
    if not cache_path.exists():
        raise FileNotFoundError(
            f"No cached LLM artifact at {cache_path}. Run with --live (needs "
            "ANTHROPIC_API_KEY) or restore the committed cache from git."
        )
    artifact = json.loads(cache_path.read_text())
    problems = check_cache_integrity(artifact, schema_ctx, gate)
    if problems:
        msg = ("Cached LLM artifact is STALE for this panel/gate:\n  - "
               + "\n  - ".join(problems))
        if not allow_stale:
            raise RuntimeError(
                msg + "\nRegenerate with --live, restore matching outputs from "
                      "git, or pass --allow-stale-cache for a scratch run."
            )
        print(f"      WARNING: {msg}\n      proceeding (--allow-stale-cache)")
    artifact["proposal"] = validate_proposal(artifact["proposal"])
    return artifact


# -- merging the LLM's candidates with the authoritative grid ----------------

def evaluate_candidates(all_corrs: pd.DataFrame, proposal: dict) -> pd.DataFrame:
    """Annotate the exhaustive grid with which pairs the LLM proposed and
    whether the measured sign matches its expected sign."""
    out = all_corrs.copy()
    out["llm_proposed"] = False
    out["expected_sign"] = ""
    out["hypothesis"] = ""
    out["sign_matches"] = ""
    for c in proposal.get("candidates", []):
        mask = (out["need_var"] == c["need_var"]) & (out["capacity_var"] == c["capacity_var"])
        if not mask.any():
            continue
        out.loc[mask, "llm_proposed"] = True
        out.loc[mask, "expected_sign"] = c["expected_sign"]
        out.loc[mask, "hypothesis"] = c.get("hypothesis", "")
        measured = "positive" if float(out.loc[mask, "spearman_r"].iloc[0]) >= 0 else "negative"
        if c["expected_sign"] in ("positive", "negative"):
            out.loc[mask, "sign_matches"] = str(measured == c["expected_sign"])
    return out
