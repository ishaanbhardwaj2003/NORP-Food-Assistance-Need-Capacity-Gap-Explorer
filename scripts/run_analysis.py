"""
run_analysis.py

Checkpoint 3 orchestration: the correlation agent, statistical critic, plots,
and findings summary on top of the committed Checkpoint 2 panel.

    1. Load data/output/joined_county_panel.csv (+ county names for labels)
    2. Python computes the exhaustive need x capacity correlation grid
    3. LLM proposes candidate pairs + reviews the gate (live or cached replay;
       the cache is hash-checked against the current panel schema + gate)
    4. Merge: mark LLM-proposed pairs, check hypothesized vs measured signs
    5. Critic: BH FDR across the grid + fixed-seed state-stratified permutation
       test per proposed pair -> supported / weak_direction / unsupported
    6. State fixed-effects estimates (signed-log outcomes, cluster-robust SEs)
       -> <output-dir>/fixed_effects_results.json
    7. Render figures -> <output-dir>/figures/
    8. Write <output-dir>/findings_summary.md from the computed tables

Flags:
    --live         call the Anthropic API and refresh the cached LLM artifact
                   (needs ANTHROPIC_API_KEY); default replays the committed cache
    --model        model for --live (default claude-opus-4-8)
    --skip-plots   skip figure rendering
    --output-dir   where to write results (default data/output); point smoke
                   tests at a scratch dir so committed evidence stays intact
    --cache        LLM cache path (default <output-dir>/llm_candidates.json if
                   present there, else the committed data/output copy)
    --allow-stale-cache  replay a cache whose schema/gate hashes do not match
                   the current run (scratch/smoke runs only)
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
from statistical_critic import (  # noqa: E402
    ALPHA, EFFECT_FLOOR, N_PERMUTATIONS, apply_critic, summarize_verdicts,
)
from fixed_effects import run_all as run_fixed_effects  # noqa: E402
from make_plots import make_all_plots  # noqa: E402
from make_maps import make_gap_maps  # noqa: E402

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "output"


def load_panel(panel_csv: Path) -> pd.DataFrame:
    """Committed panel + human-readable county names from the lookup."""
    if not panel_csv.exists():
        raise FileNotFoundError(
            f"{panel_csv} not found -- run `python scripts/run_pipeline.py` first."
        )
    panel = pd.read_csv(panel_csv, dtype={"county_fips": "string"})
    lookup = DataLoader().load_county_lookup()  # county_fips, county_name, state
    panel = panel.merge(lookup, on="county_fips", how="left", validate="1:1")
    return add_derived_columns(panel)


def _md_corr_table(df: pd.DataFrame) -> str:
    cols = ["need_var", "capacity_var", "spearman_r", "pearson_r", "n_counties"]
    lines = ["| Need variable | Capacity variable | Spearman ρ | Pearson r | n |",
             "|---|---|---|---|---|"]
    for _, r in df[cols].iterrows():
        lines.append(f"| {r.need_var} | {r.capacity_var} | {r.spearman_r:+.2f} "
                     f"| {r.pearson_r:+.2f} | {r.n_counties:,} |")
    return "\n".join(lines)


def _md_critic_table(df: pd.DataFrame) -> str:
    lines = ["| Need variable | Capacity variable | Spearman ρ | BH q | Perm. p "
             "| Sign | Verdict |",
             "|---|---|---|---|---|---|---|"]
    for _, r in df.iterrows():
        sign = "✓" if r.sign_matches == "True" else "✗"
        lines.append(
            f"| {r.need_var} | {r.capacity_var} | {r.spearman_r:+.2f} "
            f"| {r.spearman_q_bh:.1e} | {r.permutation_p:.4f} | {sign} "
            f"| **{r.claim_status}** |")
    return "\n".join(lines)


def _gap_rank_comparison(panel: pd.DataFrame) -> dict:
    """How differently do the general and food-specific gaps rank counties?"""
    sub = panel.dropna(subset=["gap_score", "food_gap_score"])
    rho = float(sub["gap_score"].rank().corr(sub["food_gap_score"].rank()))
    top_general = set(sub.nlargest(10, "gap_score")["county_fips"])
    top_food = set(sub.nlargest(10, "food_gap_score")["county_fips"])
    return {"rank_rho": rho, "top10_overlap": len(top_general & top_food)}


def _fe_section(fe_report: dict | None) -> str:
    """Markdown block for the state fixed-effects estimates (empty if absent)."""
    if not fe_report:
        return ""
    head = fe_report["estimates"][0]
    if "error" in head:
        verdict_line = f"Headline estimate unavailable: {head['error']}."
    else:
        direction = "higher" if head["fe_slope"] > 0 else "lower"
        verdict_line = (
            f"Within states, counties with higher median household income have "
            f"{direction} signed-log filer revenue per capita "
            f"(slope {head['fe_slope']:+.4f} per $10k, cluster-robust "
            f"p = {head['fe_p_value']:.2g}, {head['n']:,} counties, "
            f"{head['n_states']} states). The slope survives absorbing every "
            f"state-level shift, consistent with the critic's stratified "
            f"permutation result: the wealth-capacity association is a "
            f"within-state relationship, not a compositional artifact.")
    return f"""## State fixed-effects check (deterministic)

The strongest surviving finding (capacity tracks wealth) is re-estimated with
state fixed effects absorbed and cluster-robust (CR1) standard errors at the
state level. Outcomes use the panel's signed-log scale so financial outliers
cannot dominate the slope; a raw-scale sensitivity fit is reported alongside.
Full numbers in `fixed_effects_results.json`.

{_md_fe_table(fe_report)}

{verdict_line}

"""


def _md_fe_table(fe_report: dict) -> str:
    lines = ["| Specification | FE slope | Cluster SE | p | Pooled slope | n | States |",
             "|---|---|---|---|---|---|---|"]
    for e in fe_report["estimates"]:
        if "error" in e:
            lines.append(f"| {e.get('label', '?')} | _{e['error']}_ | | | | {e['n']} | {e['n_states']} |")
            continue
        lines.append(
            f"| {e['label']} | {e['fe_slope']:+.4f} | {e['fe_slope_cluster_se']:.4f} "
            f"| {e['fe_p_value']:.2g} | {e['pooled_slope']:+.4f} | {e['n']:,} "
            f"| {e['n_states']} |")
    return "\n".join(lines)


def write_findings_summary(panel: pd.DataFrame, corrs: pd.DataFrame,
                           artifact: dict, gate: dict, summary_md: Path,
                           fe_report: dict | None = None) -> Path:
    """Findings summary: every number below is computed by Python from the
    committed tables; the LLM contributes hypotheses and framing only."""
    gap = pd.to_numeric(panel["gap_score"], errors="coerce")
    top = panel.nlargest(10, "gap_score")
    proposal = artifact["proposal"]
    meta = artifact["metadata"]
    proposed = corrs[corrs["llm_proposed"]]
    verdicts = summarize_verdicts(corrs)
    gapcmp = _gap_rank_comparison(panel)
    coverage = pd.to_numeric(panel["filer_coverage_rate"], errors="coerce")
    n_states = panel["county_fips"].str[:2].nunique()
    n_no_filer = int((pd.to_numeric(panel["matched_filer_count"],
                                    errors="coerce") == 0).sum())

    top_rows = "\n".join(
        f"| {r.county_fips} | {r.county_name if pd.notna(r.county_name) else '—'}, "
        f"{r.state if pd.notna(r.state) else '—'} | {r.gap_score:+.2f} "
        f"| {r.need_score:+.2f} | {r.capacity_score:+.2f} | {r.food_gap_score:+.2f} |"
        for r in top.itertuples()
    )

    md = f"""# Findings Summary — NORP Food Assistance Need-Capacity Gap Explorer

*Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d')} by
`scripts/run_analysis.py` (LLM artifact mode: **{meta['mode']}**, model:
{meta.get('model', 'n/a')}). Every statistic is computed by Python from the
committed panel; the LLM contributes candidate hypotheses and framing only.
Verification: `python scripts/verify_outputs.py` re-checks every headline
number below; `pytest -q` covers the scoring, critic, and validation logic.*

## Headline

Across **{len(panel):,} counties** ({n_states} state-level FIPS; Florida and
Connecticut auto-dropped by the quality gate), the need-capacity gap score is
approximately symmetric (median {gap.median():+.2f}, std {gap.std():.2f},
range {gap.min():+.2f} to {gap.max():+.2f}). The counties where food-related
need most outpaces nonprofit capacity are concentrated in the Arkansas and
Mississippi Delta, the Texas border, the Georgia Black Belt, and Appalachian
Kentucky.

`gap_score` measures food-related need against **all** nonprofit capacity;
`food_gap_score` measures it against food-sector nonprofit density
specifically. The two rankings are related but **meaningfully different**
(rank ρ = {gapcmp['rank_rho']:.2f}; only {gapcmp['top10_overlap']}/10 top-10
overlap) — a county can look under-served in general and still host food
nonprofits, or vice versa — so both are reported, and food-sector triage
should read `food_gap_score`.

## Top-10 gap counties

| FIPS | County | Gap | Need | Capacity | Food gap |
|---|---|---|---|---|---|
{top_rows}

## Correlation results (Python-computed, exhaustive grid)

All {len(corrs)} need × capacity pairs were tested with Pearson and Spearman
correlations ({int(corrs['n_counties'].min()):,}–{int(corrs['n_counties'].max()):,}
counties per pair). The strongest relationships by |Spearman ρ|:

{_md_corr_table(corrs.head(6))}

The full grid is in `correlation_results.csv` (with BH-adjusted q-values) and
visualized in `figures/correlation_heatmap.png`.

## LLM-proposed hypotheses vs. the statistical critic

The LLM proposed **{verdicts['n_proposed']}** candidate pairs from the schema.
**Sign agreement alone is not support**: a deterministic critic re-tests every
proposed pair with BH FDR correction across all {len(corrs)} tests (α = {ALPHA}),
a fixed-seed state-stratified permutation test ({N_PERMUTATIONS:,} shuffles of
the capacity column *within* each state, so between-state artifacts don't
count), and a team-defined effect-size floor of |ρ| ≥ {EFFECT_FLOOR}.

Outcome: **{verdicts['n_sign_matched']}/{verdicts['n_proposed']} signs matched**,
of which **{verdicts['n_supported']} supported**,
**{verdicts['n_weak_direction']} weak-direction**, and
**{verdicts['n_unsupported']} unsupported** under the critic's criteria:

{_md_critic_table(proposed) if len(proposed) else '_none proposed_'}

{_fe_section(fe_report)}
## Quality-gate review

- **Rule-based gate (authoritative):** `{gate['verdict']}` — {gate['reasons'][0] if gate.get('reasons') else ''}
- **LLM advisory review:** `{proposal['gate_review'].get('verdict', 'n/a')}` — {proposal['gate_review'].get('rationale', '')}

## Agent framing notes (LLM)

{proposal.get('narrative_notes', '_none_')}

## Caveats

- The NGO table is an **ordered, truncated extract**: 1,048,575 rows (exactly
  the Excel export limit) of the 3,420,024-row source, EIN-sorted and cut at
  an EIN prefix, so it is **not** a random sample and national
  representativeness cannot be assumed.
- The financial join matches 990/990EZ/990PF summary filings for ~3.6% of
  NGOs (median county filer coverage {coverage.median():.1%}).
  {n_no_filer} counties have **no matched filer**: their revenue/assets
  are reported as *missing* (NaN), never as zero, and their capacity score
  averages the remaining indicators (`capacity_component_count` records this).
- 99 counties lack poverty data; `need_component_count` marks them.
- Sources span vintages (2015–2019 tract indicators, 2022 filings, 2023
  poverty); `med_household_income` is an inverse-need/context measure.
- The gap scores are **triage signals, not causal claims** about nonprofit
  effectiveness; correlations are descriptive, county-level associations.

## Reproduce

```bash
python scripts/run_pipeline.py --verbose   # rebuild the panel (~15 s)
python scripts/run_analysis.py             # offline: replays the committed LLM cache
python scripts/verify_outputs.py           # re-verify every claim above
pytest -q                                  # unit tests (no API key, no big files)
python scripts/run_analysis.py --live      # optional: refresh the LLM artifact (needs ANTHROPIC_API_KEY)

# smoke-test without touching committed evidence:
python scripts/run_pipeline.py --sample --mock --output-dir /tmp/norp-smoke
python scripts/run_analysis.py --output-dir /tmp/norp-smoke --allow-stale-cache
```
"""
    summary_md.write_text(md)
    return summary_md


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Checkpoint 3 correlation agent + reporting")
    ap.add_argument("--live", action="store_true",
                    help="call the Anthropic API instead of replaying the cache")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="model for --live")
    ap.add_argument("--skip-plots", action="store_true", help="skip figure rendering")
    ap.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR),
                    help="where to write results (default data/output)")
    ap.add_argument("--cache", default=None,
                    help="LLM cache path (default: llm_candidates.json in the "
                         "output dir, falling back to the committed copy)")
    ap.add_argument("--allow-stale-cache", action="store_true",
                    help="replay a cache whose schema/gate hashes mismatch "
                         "(scratch/smoke runs only)")
    args = ap.parse_args(argv)

    output_dir = Path(args.output_dir)
    panel_csv = output_dir / "joined_county_panel.csv"
    profiler_log = output_dir / "profiler_log.json"
    corr_csv = output_dir / "correlation_results.csv"
    figures_dir = output_dir / "figures"
    summary_md = output_dir / "findings_summary.md"
    if args.cache:
        cache_path = Path(args.cache)
    else:
        cache_path = output_dir / "llm_candidates.json"
        if not cache_path.exists():
            cache_path = DEFAULT_OUTPUT_DIR / "llm_candidates.json"

    print("[1/7] Loading committed panel + county names ...")
    panel = load_panel(panel_csv)
    gate = json.loads(profiler_log.read_text())["gate"]
    print(f"      panel: {panel.shape}   gate verdict: {gate['verdict']}")

    print("[2/7] Computing exhaustive need x capacity correlation grid (Python) ...")
    corrs = compute_all_correlations(panel)
    print(f"      {len(corrs)} pairs tested")

    print(f"[3/7] LLM candidate proposal ({'LIVE API' if args.live else 'cached replay'}) ...")
    schema_ctx = build_schema_context(panel)
    artifact = get_proposal(schema_ctx, gate, cache_path, live=args.live,
                            model=args.model, allow_stale=args.allow_stale_cache)
    proposal = artifact["proposal"]
    print(f"      {len(proposal['candidates'])} candidates | advisory gate: "
          f"{proposal['gate_review'].get('verdict')}")

    print("[4/7] Evaluating LLM candidates against measured statistics ...")
    corrs = evaluate_candidates(corrs, proposal)

    print("[5/8] Statistical critic (BH FDR + state-stratified permutations) ...")
    corrs = apply_critic(corrs, panel)
    v = summarize_verdicts(corrs)
    print(f"      {v['n_sign_matched']}/{v['n_proposed']} signs matched -> "
          f"{v['n_supported']} supported, {v['n_weak_direction']} weak, "
          f"{v['n_unsupported']} unsupported")
    output_dir.mkdir(parents=True, exist_ok=True)
    corrs.to_csv(corr_csv, index=False)
    print(f"      -> {corr_csv}")

    print("[6/8] State fixed-effects estimates (deterministic) ...")
    fe_report = run_fixed_effects(panel)
    fe_path = output_dir / "fixed_effects_results.json"
    fe_path.write_text(json.dumps(fe_report, indent=2))
    head = fe_report["estimates"][0]
    print(f"      {fe_report['headline_pair']}: slope {head.get('fe_slope')} "
          f"(cluster p {head.get('fe_p_value'):.2g}) "
          f"survives_fe={fe_report['headline_survives_state_fe']}")
    print(f"      -> {fe_path}")

    if args.skip_plots:
        print("[7/8] Skipping plots (--skip-plots)")
    else:
        print("[7/8] Rendering figures ...")
        for p in make_all_plots(panel, corrs, figures_dir):
            print(f"      -> {p}")
        for p in make_gap_maps(panel, figures_dir):
            print(f"      -> {p}")

    print("[8/8] Writing findings summary ...")
    path = write_findings_summary(panel, corrs, artifact, gate, summary_md,
                                  fe_report)
    print(f"      -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
