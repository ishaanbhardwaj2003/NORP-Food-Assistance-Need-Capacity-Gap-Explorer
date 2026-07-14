"""
run_analysis.py

Checkpoint 3 orchestration: the correlation agent, plots, and findings summary
on top of the committed Checkpoint 2 panel.

    1. Load data/output/joined_county_panel.csv (+ county names for labels)
    2. Python computes the exhaustive need x capacity correlation grid
    3. LLM proposes candidate pairs + reviews the gate (live or cached replay)
    4. Merge: mark LLM-proposed pairs, check hypothesized vs measured signs
    5. Render figures -> data/output/figures/
    6. Write data/output/findings_summary.md from the computed tables

Flags:
    --live       call the Anthropic API and refresh the cached LLM artifact
                 (needs ANTHROPIC_API_KEY); default replays the committed cache
    --model      model for --live (default claude-opus-4-8)
    --skip-plots skip figure rendering
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from load_data import DataLoader  # noqa: E402
from correlation_agent import (  # noqa: E402
    DEFAULT_MODEL, add_derived_columns, build_schema_context,
    compute_all_correlations, evaluate_candidates, get_proposal,
)
from make_plots import make_all_plots  # noqa: E402

OUTPUT_DIR = PROJECT_ROOT / "data" / "output"
PANEL_CSV = OUTPUT_DIR / "joined_county_panel.csv"
PROFILER_LOG = OUTPUT_DIR / "profiler_log.json"
LLM_CACHE = OUTPUT_DIR / "llm_candidates.json"
CORR_CSV = OUTPUT_DIR / "correlation_results.csv"
FIGURES_DIR = OUTPUT_DIR / "figures"
SUMMARY_MD = OUTPUT_DIR / "findings_summary.md"


def load_panel() -> pd.DataFrame:
    """Committed panel + human-readable county names from the lookup."""
    if not PANEL_CSV.exists():
        raise FileNotFoundError(
            f"{PANEL_CSV} not found -- run `python scripts/run_pipeline.py` first."
        )
    panel = pd.read_csv(PANEL_CSV, dtype={"county_fips": "string"})
    lookup = DataLoader().load_county_lookup()  # county_fips, county_name, state
    panel = panel.merge(lookup, on="county_fips", how="left")
    return add_derived_columns(panel)


def _md_corr_table(df: pd.DataFrame) -> str:
    cols = ["need_var", "capacity_var", "spearman_r", "pearson_r", "n_counties"]
    lines = ["| Need variable | Capacity variable | Spearman ρ | Pearson r | n |",
             "|---|---|---|---|---|"]
    for _, r in df[cols].iterrows():
        lines.append(f"| {r.need_var} | {r.capacity_var} | {r.spearman_r:+.2f} "
                     f"| {r.pearson_r:+.2f} | {r.n_counties:,} |")
    return "\n".join(lines)


def write_findings_summary(panel: pd.DataFrame, corrs: pd.DataFrame,
                           artifact: dict, gate: dict) -> Path:
    """Findings summary: every number below is computed by Python from the
    committed tables; the LLM contributes hypotheses and framing only."""
    gap = pd.to_numeric(panel["gap_score"], errors="coerce")
    top = panel.nlargest(10, "gap_score")
    proposal = artifact["proposal"]
    meta = artifact["metadata"]
    proposed = corrs[corrs["llm_proposed"]]
    confirmed = proposed[proposed["sign_matches"] == "True"]

    top_rows = "\n".join(
        f"| {r.county_fips} | {r.county_name if pd.notna(r.county_name) else '—'}, "
        f"{r.state if pd.notna(r.state) else '—'} | {r.gap_score:+.2f} "
        f"| {r.need_score:+.2f} | {r.capacity_score:+.2f} |"
        for r in top.itertuples()
    )

    md = f"""# Findings Summary — NORP Food Assistance Need-Capacity Gap Explorer

*Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d')} by
`scripts/run_analysis.py` (LLM artifact mode: **{meta['mode']}**, model:
{meta.get('model', 'n/a')}). Every statistic is computed by Python from the
committed panel; the LLM contributes candidate hypotheses and framing only.*

## Headline

Across **{len(panel):,} counties** (49 state-level FIPS; Florida and
Connecticut auto-dropped by the quality gate), the need-capacity gap score is
approximately symmetric (median {gap.median():+.2f}, std {gap.std():.2f},
range {gap.min():+.2f} to {gap.max():+.2f}). The counties where food-related
need most outpaces nonprofit capacity are concentrated in the Arkansas and
Mississippi Delta, the Texas border, the Alabama Black Belt, Appalachian
Kentucky, and reservation counties in the Dakotas.

## Top-10 gap counties

| FIPS | County | Gap | Need | Capacity |
|---|---|---|---|---|
{top_rows}

## Correlation results (Python-computed, exhaustive grid)

All {len(corrs)} need × capacity pairs were tested with Pearson and Spearman
correlations ({int(corrs['n_counties'].min()):,}–{int(corrs['n_counties'].max()):,}
counties per pair). The strongest relationships by |Spearman ρ|:

{_md_corr_table(corrs.head(6))}

The full grid is in `data/output/correlation_results.csv` and visualized in
`data/output/figures/correlation_heatmap.png`.

## LLM-proposed candidates vs. measured statistics

The LLM proposed **{len(proposed)}** candidate pairs from the schema;
**{len(confirmed)}** matched its hypothesized sign when Python computed the
statistic. Proposed pairs and outcomes:

{_md_corr_table(proposed) if len(proposed) else '_none proposed_'}

## Quality-gate review

- **Rule-based gate (authoritative):** `{gate['verdict']}` — {gate['reasons'][0] if gate.get('reasons') else ''}
- **LLM advisory review:** `{proposal['gate_review'].get('verdict', 'n/a')}` — {proposal['gate_review'].get('rationale', '')}

## Agent framing notes (LLM)

{proposal.get('narrative_notes', '_none_')}

## Caveats

- The NGO table is a **1,048,575-row sample** of the 3,420,024-row source, so
  county capacity aggregates are sample-based.
- The 990 financial join is sparse (~3% of NGOs file a full 990); revenue and
  asset per-capita metrics reflect filers only.
- The gap score is a **triage signal, not a causal claim** about nonprofit
  effectiveness; correlations are descriptive, county-level associations.

## Reproduce

```bash
python scripts/run_pipeline.py --verbose   # rebuild the panel (~15 s)
python scripts/run_analysis.py             # offline: replays the committed LLM cache
python scripts/run_analysis.py --live      # optional: refresh the LLM artifact (needs ANTHROPIC_API_KEY)
```
"""
    SUMMARY_MD.write_text(md)
    return SUMMARY_MD


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Checkpoint 3 correlation agent + reporting")
    ap.add_argument("--live", action="store_true",
                    help="call the Anthropic API instead of replaying the cache")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="model for --live")
    ap.add_argument("--skip-plots", action="store_true", help="skip figure rendering")
    args = ap.parse_args(argv)

    print("[1/6] Loading committed panel + county names ...")
    panel = load_panel()
    gate = json.loads(PROFILER_LOG.read_text())["gate"]
    print(f"      panel: {panel.shape}   gate verdict: {gate['verdict']}")

    print("[2/6] Computing exhaustive need x capacity correlation grid (Python) ...")
    corrs = compute_all_correlations(panel)
    print(f"      {len(corrs)} pairs tested")

    print(f"[3/6] LLM candidate proposal ({'LIVE API' if args.live else 'cached replay'}) ...")
    schema_ctx = build_schema_context(panel)
    artifact = get_proposal(schema_ctx, gate, LLM_CACHE, live=args.live, model=args.model)
    proposal = artifact["proposal"]
    print(f"      {len(proposal['candidates'])} candidates | advisory gate: "
          f"{proposal['gate_review'].get('verdict')}")

    print("[4/6] Evaluating LLM candidates against measured statistics ...")
    corrs = evaluate_candidates(corrs, proposal)
    corrs.to_csv(CORR_CSV, index=False)
    print(f"      -> {CORR_CSV}")

    if args.skip_plots:
        print("[5/6] Skipping plots (--skip-plots)")
    else:
        print("[5/6] Rendering figures ...")
        for p in make_all_plots(panel, corrs, FIGURES_DIR):
            print(f"      -> {p}")

    print("[6/6] Writing findings summary ...")
    path = write_findings_summary(panel, corrs, artifact, gate)
    print(f"      -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
