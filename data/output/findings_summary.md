# Findings Summary — NORP Food Assistance Need-Capacity Gap Explorer

*Generated 2026-07-15 by
`scripts/run_analysis.py` (LLM artifact mode: **cached**, model:
claude-fable-5). Every statistic is computed by Python from the
committed panel; the LLM contributes candidate hypotheses and framing only.
Verification: `python scripts/verify_outputs.py` re-checks every headline
number below; `pytest -q` covers the scoring, critic, and validation logic.*

## Headline

Across **3,027 counties** (49 state-level FIPS; Florida and
Connecticut auto-dropped by the quality gate), the need-capacity gap score is
approximately symmetric (median +0.11, std 1.17,
range -4.38 to +5.03). The counties where food-related
need most outpaces nonprofit capacity are concentrated in the Arkansas and
Mississippi Delta, the Texas border, the Alabama Black Belt, Appalachian
Kentucky, and reservation counties in the Dakotas.

`gap_score` measures food-related need against **all** nonprofit capacity;
`food_gap_score` measures it against food-sector nonprofit density
specifically. The two rankings are related but **meaningfully different**
(rank ρ = 0.61; only 2/10 top-10
overlap) — a county can look under-served in general and still host food
nonprofits, or vice versa — so both are reported, and food-sector triage
should read `food_gap_score`.

## Top-10 gap counties

| FIPS | County | Gap | Need | Capacity | Food gap |
|---|---|---|---|---|---|
| 05077 | Lee, AR | +5.03 | +2.93 | -2.10 | +3.67 |
| 48505 | Zapata, TX | +4.46 | +2.24 | -2.23 | +1.82 |
| 48507 | Zavala, TX | +3.84 | +1.87 | -1.97 | +2.61 |
| 28011 | Bolivar, MS | +3.70 | +2.25 | -1.45 | +2.39 |
| 13271 | Telfair, GA | +3.36 | +1.56 | -1.79 | +2.30 |
| 48489 | Willacy, TX | +3.22 | +1.08 | -2.14 | +1.82 |
| 28157 | Wilkinson, MS | +3.16 | +2.15 | -1.01 | +2.89 |
| 48247 | Jim Hogg, TX | +3.16 | +1.40 | -1.76 | +2.13 |
| 13101 | Echols, GA | +3.12 | +0.42 | -2.70 | +1.16 |
| 13141 | Hancock, GA | +3.07 | +1.90 | -1.17 | +2.64 |

## Correlation results (Python-computed, exhaustive grid)

All 28 need × capacity pairs were tested with Pearson and Spearman
correlations (2,160–3,027
counties per pair). The strongest relationships by |Spearman ρ|:

| Need variable | Capacity variable | Spearman ρ | Pearson r | n |
|---|---|---|---|---|
| unemployment | ngo_per_10k | -0.31 | -0.22 | 3,025 |
| avg_dac_score | ngo_per_10k | -0.30 | -0.23 | 3,027 |
| med_household_income | revenue_per_capita | +0.25 | +0.07 | 2,220 |
| poverty_rate | revenue_per_capita | -0.24 | -0.09 | 2,162 |
| poverty_rate | assets_per_capita | -0.23 | -0.09 | 2,160 |
| poverty_rate | ngo_per_10k | -0.23 | -0.20 | 2,928 |

The full grid is in `correlation_results.csv` (with BH-adjusted q-values) and
visualized in `figures/correlation_heatmap.png`.

## LLM-proposed hypotheses vs. the statistical critic

The LLM proposed **7** candidate pairs from the schema.
**Sign agreement alone is not support**: a deterministic critic re-tests every
proposed pair with BH FDR correction across all 28 tests (α = 0.05),
a fixed-seed state-stratified permutation test (2,000 shuffles of
the capacity column *within* each state, so between-state artifacts don't
count), and a team-defined effect-size floor of |ρ| ≥ 0.1.

Outcome: **6/7 signs matched**,
of which **3 supported**,
**2 weak-direction**, and
**2 unsupported** under the critic's criteria:

| Need variable | Capacity variable | Spearman ρ | BH q | Perm. p | Sign | Verdict |
|---|---|---|---|---|---|---|
| unemployment | ngo_per_10k | -0.31 | 6.9e-67 | 0.0005 | ✓ | **supported** |
| med_household_income | revenue_per_capita | +0.25 | 1.0e-31 | 0.0005 | ✓ | **supported** |
| poverty_rate | revenue_per_capita | -0.24 | 2.1e-29 | 0.0005 | ✓ | **supported** |
| poverty_rate | ngo_per_10k | -0.23 | 2.3e-35 | 1.0000 | ✓ | **weak_direction** |
| avg_food_desert_pct | food_ngo_per_10k | -0.09 | 5.6e-07 | 0.0080 | ✓ | **weak_direction** |
| avg_housing_burden | assets_per_capita | -0.04 | 6.7e-02 | 0.3578 | ✗ | **unsupported** |
| dac_tract_pct | food_ngo_per_10k | -0.02 | 2.9e-01 | 0.1634 | ✓ | **unsupported** |

## Quality-gate review

- **Rule-based gate (authoritative):** `proceed_with_warning` — capacity-side join 'ngo_county_to_fips' match_rate=0.9462 (usable) -> auto-drop unmatched (56373 rows); top states: {'FL': 38915, 'CT': 11352, 'VA': 5291, 'NM': 300, 'CA': 82, 'OH': 69, 'NY': 44, 'IL': 26, 'NJ': 22, 'ME': 19}
- **LLM advisory review:** `proceed_with_warning` — All need-side tables and joins are usable, so the panel's denominators are sound. The capacity-side auto-drop of Florida and Connecticut is logged and non-fatal, but the panel is not nationally exhaustive, which any national claim must disclose.

## Agent framing notes (LLM)

Frame the gap score as a triage map, not a performance ranking: high-gap counties are places worth investigating, not evidence that local nonprofits underperform. Lead with the geography of the top-gap counties, then use the correlation grid to show that capacity tracks wealth rather than need. Flag the sparse 990 join and the sampled NGO table wherever financial metrics appear, and keep Florida and Connecticut's absence visible in every county count.

## Caveats

- The NGO table is an **ordered, truncated extract**: 1,048,575 rows (exactly
  the Excel export limit) of the 3,420,024-row source, EIN-sorted and cut at
  an EIN prefix, so it is **not** a random sample and national
  representativeness cannot be assumed.
- The financial join matches 990/990EZ/990PF summary filings for ~3.6% of
  NGOs (median county filer coverage 3.0%).
  806 counties have **no matched filer**: their revenue/assets
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
