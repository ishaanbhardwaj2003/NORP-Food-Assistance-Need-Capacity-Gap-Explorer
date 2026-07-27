# Findings Summary — NORP Food Assistance Need-Capacity Gap Explorer

*Generated 2026-07-27 by
`scripts/run_analysis.py` (LLM artifact mode: **cached**, model:
claude-fable-5). Every statistic is computed by Python from the
committed panel; the LLM contributes candidate hypotheses and framing only.
Verification: `python scripts/verify_outputs.py` re-checks every headline
number below; `pytest -q` covers the scoring, critic, and validation logic.*

## Headline

Across **3,066 counties** (49 state-level FIPS; Florida and
Connecticut auto-dropped by the quality gate), the need-capacity gap score is
approximately symmetric (median -0.01, std 1.09,
range -4.56 to +4.17). The counties where food-related
need most outpaces nonprofit capacity are concentrated in the Arkansas and
Mississippi Delta, the Texas border, the Georgia Black Belt, and Appalachian
Kentucky.

`gap_score` measures food-related need against **all** nonprofit capacity;
`food_gap_score` measures it against food-sector nonprofit density
specifically. The two rankings are related but **meaningfully different**
(rank ρ = 0.58; only 0/10 top-10
overlap) — a county can look under-served in general and still host food
nonprofits, or vice versa — so both are reported, and food-sector triage
should read `food_gap_score`.

## Top-10 gap counties

| FIPS | County | Gap | Need | Capacity | Food gap |
|---|---|---|---|---|---|
| 48505 | Zapata, TX | +4.17 | +2.22 | -1.94 | +2.70 |
| 48507 | Zavala, TX | +4.13 | +1.86 | -2.27 | +2.16 |
| 21159 | Martin, KY | +3.84 | +1.44 | -2.39 | +1.72 |
| 05077 | Lee, AR | +3.61 | +2.91 | -0.70 | +1.79 |
| 05123 | St. Francis, AR | +3.45 | +1.60 | -1.85 | +1.75 |
| 01011 | Bullock, AL | +3.30 | +2.21 | -1.09 | +3.00 |
| 48427 | Starr, TX | +3.21 | +1.32 | -1.89 | +2.01 |
| 40023 | Choctaw, OK | +3.21 | +0.92 | -2.29 | +0.42 |
| 51685 | Manassas Park, VA | +3.15 | +0.99 | -2.17 | +2.88 |
| 35047 | San Miguel, NM | +3.13 | +1.89 | -1.24 | +2.60 |

## Correlation results (Python-computed, exhaustive grid)

All 28 need × capacity pairs were tested with Pearson and Spearman
correlations (2,818–3,066
counties per pair). The strongest relationships by |Spearman ρ|:

| Need variable | Capacity variable | Spearman ρ | Pearson r | n |
|---|---|---|---|---|
| unemployment | ngo_per_10k | -0.38 | -0.29 | 3,064 |
| avg_dac_score | ngo_per_10k | -0.37 | -0.33 | 3,066 |
| avg_housing_burden | ngo_per_10k | -0.28 | -0.25 | 3,066 |
| avg_dac_score | revenue_per_capita | -0.28 | -0.03 | 2,941 |
| med_household_income | revenue_per_capita | +0.27 | -0.01 | 2,939 |
| unemployment | food_ngo_per_10k | -0.27 | -0.22 | 3,064 |

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
of which **4 supported**,
**2 weak-direction**, and
**1 unsupported** under the critic's criteria:

| Need variable | Capacity variable | Spearman ρ | BH q | Perm. p | Sign | Verdict |
|---|---|---|---|---|---|---|
| unemployment | ngo_per_10k | -0.38 | 6.4e-103 | 0.0005 | ✓ | **supported** |
| med_household_income | revenue_per_capita | +0.27 | 6.3e-50 | 0.0005 | ✓ | **supported** |
| poverty_rate | revenue_per_capita | -0.26 | 1.8e-45 | 0.0005 | ✓ | **supported** |
| dac_tract_pct | food_ngo_per_10k | -0.24 | 7.9e-41 | 0.0005 | ✓ | **supported** |
| poverty_rate | ngo_per_10k | -0.23 | 7.7e-36 | 1.0000 | ✓ | **weak_direction** |
| avg_food_desert_pct | food_ngo_per_10k | -0.05 | 1.4e-02 | 0.9990 | ✓ | **weak_direction** |
| avg_housing_burden | assets_per_capita | -0.04 | 5.3e-02 | 0.9840 | ✗ | **unsupported** |

## State fixed-effects check (deterministic)

The strongest surviving finding (capacity tracks wealth) is re-estimated with
state fixed effects absorbed and cluster-robust (CR1) standard errors at the
state level. Outcomes use the panel's signed-log scale so financial outliers
cannot dominate the slope; a raw-scale sensitivity fit is reported alongside.
Full numbers in `fixed_effects_results.json`.

| Specification | FE slope | Cluster SE | p | Pooled slope | n | States |
|---|---|---|---|---|---|---|
| headline: filer revenue per capita ~ median household income ($10k) | +0.1322 | 0.0185 | 4.2e-09 | +0.1942 | 2,939 | 49 |
| filer revenue per capita ~ poverty rate | -0.0379 | 0.0098 | 0.00033 | -0.0585 | 2,818 | 46 |
| nonprofit density ~ unemployment | -1.8211 | 0.5930 | 0.0035 | -5.6434 | 3,064 | 49 |
| sensitivity: headline pair on the raw outcome scale | -13.5658 | 26.4342 | 0.61 | -7.3004 | 2,939 | 49 |

Within states, counties with higher median household income have higher signed-log filer revenue per capita (slope +0.1322 per $10k, cluster-robust p = 4.2e-09, 2,939 counties, 49 states). The slope survives absorbing every state-level shift, consistent with the critic's stratified permutation result: the wealth-capacity association is a within-state relationship, not a compositional artifact.


## Quality-gate review

- **Rule-based gate (authoritative):** `proceed_with_warning` — capacity-side join 'ngo_county_to_fips' match_rate=0.9322 (usable) -> auto-drop unmatched (231927 rows); top states: {'FL': 188675, 'CT': 41739, 'CA': 205, 'OH': 88, 'TX': 80, 'IL': 77, 'AK': 75, 'NY': 72, 'AR': 68, 'WA': 64}
- **LLM advisory review:** `proceed_with_warning` — Need-side tables and joins are all usable, so the panel's denominators are sound. On the full 3,420,024-row table the capacity-side drop is now almost entirely Florida and Connecticut, whose counties are unmappable in the committed lookup; that absence is logged, non-fatal, and must stay disclosed in any national claim.

## Agent framing notes (LLM)

Frame the gap score as a triage map, not a performance ranking: high-gap counties are places worth investigating, not evidence that local nonprofits underperform. Lead with the geography of the top-gap counties, then use the correlation grid to show that capacity tracks wealth rather than need. Note that the analysis now runs on the full table rather than the truncated extract, with Virginia's independent cities recovered by the exact-first crosswalk. Flag the sparse 990 filer join wherever financial metrics appear, and keep Florida and Connecticut's lookup-driven absence visible in every county count.

## Caveats

- The panel is built from the **full 3,420,024-row** NGOs_with_categories table (committed as 4 gzipped parts in `data/raw/ngos_full/`), closing the truncated-extract gap flagged at CP2/CP3. The old extract's bias is quantified in `truncation_analysis.json`; conclusion changes are itemized in `full_vs_extract_comparison.json`.
- The financial join matches 990/990EZ/990PF summary filings for ~4% of
  NGOs (median county filer coverage 3.7%).
  124 counties have **no matched filer**: their revenue/assets
  are reported as *missing* (NaN), never as zero, and their capacity score
  averages the remaining indicators (`capacity_component_count` records this).
- 135 counties lack poverty data; `need_component_count` marks them.
- Sources span vintages (2015–2019 tract indicators, 2022 filings, 2023
  poverty); `med_household_income` is an inverse-need/context measure.
- The gap scores are **triage signals, not causal claims** about nonprofit
  effectiveness; correlations are descriptive, county-level associations.

## Reproduce

```bash
python scripts/run_pipeline.py --verbose   # rebuild the panel (full parts auto-detected)
python scripts/run_analysis.py             # offline: replays the committed LLM cache
python scripts/analyze_truncation.py       # extract-vs-full truncation bias
python scripts/verify_outputs.py           # re-verify every claim above
pytest -q                                  # unit tests (no API key, no big files)
python scripts/run_analysis.py --live      # optional: refresh the LLM artifact (needs ANTHROPIC_API_KEY)

# smoke-test without touching committed evidence:
python scripts/run_pipeline.py --sample --mock --output-dir /tmp/norp-smoke
python scripts/run_analysis.py --output-dir /tmp/norp-smoke --allow-stale-cache
```
