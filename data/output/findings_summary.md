# Findings Summary — NORP Food Assistance Need-Capacity Gap Explorer

*Generated 2026-07-14 by
`scripts/run_analysis.py` (LLM artifact mode: **cached**, model:
claude-fable-5). Every statistic is computed by Python from the
committed panel; the LLM contributes candidate hypotheses and framing only.*

## Headline

Across **3,027 counties** (49 state-level FIPS; Florida and
Connecticut auto-dropped by the quality gate), the need-capacity gap score is
approximately symmetric (median +0.10, std 1.10,
range -3.74 to +4.42). The counties where food-related
need most outpaces nonprofit capacity are concentrated in the Arkansas and
Mississippi Delta, the Texas border, the Alabama Black Belt, Appalachian
Kentucky, and reservation counties in the Dakotas.

## Top-10 gap counties

| FIPS | County | Gap | Need | Capacity |
|---|---|---|---|---|
| 05077 | Lee, AR | +4.42 | +2.93 | -1.49 |
| 48505 | Zapata, TX | +3.77 | +2.24 | -1.53 |
| 48507 | Zavala, TX | +3.32 | +1.87 | -1.45 |
| 22023 | Cameron, LA | +3.30 | +2.53 | -0.77 |
| 22119 | Webster, LA | +3.27 | +2.25 | -1.03 |
| 28011 | Bolivar, MS | +3.17 | +2.25 | -0.92 |
| 46137 | Ziebach, SD | +3.16 | +2.48 | -0.68 |
| 28163 | Yazoo, MS | +3.01 | +1.82 | -1.19 |
| 01105 | Perry, AL | +2.98 | +2.14 | -0.84 |
| 21051 | Clay, KY | +2.96 | +1.78 | -1.17 |

## Correlation results (Python-computed, exhaustive grid)

All 28 need × capacity pairs were tested with Pearson and Spearman
correlations (2,928–3,027
counties per pair). The strongest relationships by |Spearman ρ|:

| Need variable | Capacity variable | Spearman ρ | Pearson r | n |
|---|---|---|---|---|
| med_household_income | revenue_per_capita | +0.33 | +0.10 | 3,025 |
| med_household_income | assets_per_capita | +0.32 | +0.08 | 3,025 |
| unemployment | ngo_per_10k | -0.31 | -0.22 | 3,025 |
| avg_dac_score | ngo_per_10k | -0.30 | -0.23 | 3,027 |
| poverty_rate | revenue_per_capita | -0.29 | -0.10 | 2,928 |
| poverty_rate | assets_per_capita | -0.29 | -0.10 | 2,928 |

The full grid is in `data/output/correlation_results.csv` and visualized in
`data/output/figures/correlation_heatmap.png`.

## LLM-proposed candidates vs. measured statistics

The LLM proposed **7** candidate pairs from the schema;
**7** matched its hypothesized sign when Python computed the
statistic. Proposed pairs and outcomes:

| Need variable | Capacity variable | Spearman ρ | Pearson r | n |
|---|---|---|---|---|
| med_household_income | revenue_per_capita | +0.33 | +0.10 | 3,025 |
| unemployment | ngo_per_10k | -0.31 | -0.22 | 3,025 |
| poverty_rate | revenue_per_capita | -0.29 | -0.10 | 2,928 |
| poverty_rate | ngo_per_10k | -0.23 | -0.20 | 2,928 |
| avg_housing_burden | assets_per_capita | +0.12 | -0.00 | 3,027 |
| avg_food_desert_pct | food_ngo_per_10k | -0.09 | -0.01 | 3,027 |
| dac_tract_pct | food_ngo_per_10k | -0.02 | -0.06 | 3,027 |

## Quality-gate review

- **Rule-based gate (authoritative):** `proceed_with_warning` — capacity-side join 'ngo_county_to_fips' match_rate=0.9462 (usable) -> auto-drop unmatched (56373 rows); top states: {'FL': 38915, 'CT': 11352, 'VA': 5291, 'NM': 300, 'CA': 82, 'OH': 69, 'NY': 44, 'IL': 26, 'NJ': 22, 'ME': 19}
- **LLM advisory review:** `proceed_with_warning` — All need-side tables and joins are usable, so the panel's denominators are sound. The capacity-side auto-drop of Florida and Connecticut is logged and non-fatal, but the panel is not nationally exhaustive, which any national claim must disclose.

## Agent framing notes (LLM)

Frame the gap score as a triage map, not a performance ranking: high-gap counties are places worth investigating, not evidence that local nonprofits underperform. Lead with the geography of the top-gap counties, then use the correlation grid to show that capacity tracks wealth rather than need. Flag the sparse 990 join and the sampled NGO table wherever financial metrics appear, and keep Florida and Connecticut's absence visible in every county count.

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
