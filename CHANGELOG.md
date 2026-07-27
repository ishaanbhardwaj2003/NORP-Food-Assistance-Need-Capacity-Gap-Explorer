# Changelog

All notable changes to the NORP Food Assistance Need-Capacity Gap Explorer.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## Final checkpoint — full data, crosswalk v2, FE estimate, maps — 2026-07-26

Closes the data-access gap the CP2 and CP3 feedback flagged, audits the TA's
`ai-suggestions/cp4` benchmark branch the same way CP3 audited our own
outputs, and ships the three deliverables named in the CP3 report plus the
measurement layer around them. Every conclusion change is itemized in
committed artifacts.

### Added
- **Full 3,420,024-row `NGOs_with_categories` table** committed as four
  gzipped parts (`data/raw/ngos_full/`; GitHub's 100 MB cap forces the split),
  with `scripts/assemble_ngo_parts.py` to validate/split a delivery and a
  multi-part-aware `DataLoader` (`--ngo-source {auto,full,extract}`;
  provenance recorded in `profiler_log.json`). Validation anchors: exact CP1
  row count, unique EINs, food count 40,086 vs the CP1 ~40,080.
- **Crosswalk v2** (`src/crosswalk.py`): exact-first resolution + one-suffix
  fallback now including bare "city", plus text folding with a conservative
  encoding-repair rule (the lookup itself stores "DoÃ±a Ana"). Recovers all
  34 VA independent cities and Doña Ana NM; the TA benchmark's version
  recovered zero rows on the real data (verified; its fixtures only tested
  lookup-verbatim names). Its exact-first concept and `va_collision_pairs`
  audit are adopted with credit.
- **`src/fixed_effects.py`** — state-FE OLS of the wealth-capacity headline
  with CR1 cluster-robust SEs (estimator core adapted from the benchmark),
  moved onto the panel's signed-log scale with a raw-scale sensitivity fit;
  wired into `run_analysis.py`, `findings_summary.md`, and a
  `fe_reproduction` verifier check. Headline survives: slope +0.132 per $10k,
  cluster p = 4.2e-09.
- **`src/make_maps.py`** — true county choropleths (general + food gap) in
  pure matplotlib from committed public-domain geometry
  (`data/reference/us_counties_geo.json` + PROVENANCE), CONUS + AK/HI insets,
  no-data grey for FL/CT, `choropleth_meta.json` accounting; the benchmark's
  state tile cartogram kept as the overview figure.
- **`scripts/analyze_truncation.py`** — the retired extract's bias, measured:
  30.7% of rows but 26.2% of food NGOs and 16.1% of AK; per-state coverage
  figure + JSON.
- **`scripts/compare_extract_vs_full.py`** — CP3 panel vs extract+crosswalk-v2
  vs full-data panel, isolating what the crosswalk fix changed vs what the
  full data changed: 3,027 → 3,062 → 3,066 counties, top-10 overlap 3/10 vs
  CP3, two food-sector correlation sign flips, and
  `dac_tract_pct ~ food_ngo_per_10k` moving unsupported → supported.
- **`scripts/regen_offline_cache.py`** — rebuilds the hash-bound LLM artifact
  against the current panel/gate with the same guardrails as a live call
  (honestly labeled offline authorship). The final artifact re-tests the same
  7 CP3 hypotheses so verdict changes are attributable to data, not prompts.
- **`scripts/make_slides.py` + `presentation/`** — the final deck built from
  committed evidence (python-pptx, presentation-only dependency).
- **32 new pytest tests** (66 total): crosswalk v2 incl. the bare-lookup city
  case, loader source selection and header-casing robustness, FE estimator
  (incl. LSDV equivalence), map parsing/accounting.

### Changed
- Panel: 3,027 → **3,066 counties**; need-only losses 115 → 76 (now 99.3%
  pure FL/CT lookup gaps). No-filer counties 803 → 124. Critic verdicts:
  3/2/2 → **4 supported / 2 weak / 1 unsupported**. Top-gap geography holds
  (Zapata TX, Zavala TX, Martin KY, Lee AR, St. Francis AR); recovered
  Manassas Park VA enters the top 10.
- `verify_outputs.py`: 13 → **17 checks** (crosswalk_recovery,
  fe_reproduction, choropleth_meta, truncation_analysis; ngo provenance is
  source-aware).
- `findings_summary.md` caveats are source-aware; poverty-missing and
  no-filer counts computed from the panel instead of frozen.
- Commit author identity switched to the address registered with GitHub.

## Checkpoint 3 revision — data validity + statistical critic — 2026-07-15

A validity-first revision responding to the Checkpoint 2 TA feedback ("commit
the validation itself") and to an internal audit against the TA's
`ai-suggestions/cp3` benchmark. Committed evidence was regenerated; headline
conclusions changed and the report says so.

### Added
- **`scripts/verify_outputs.py` + `data/output/validation_report.json`** — the
  committed verification the TA asked for: panel FIPS integrity, FL/CT absence,
  crosswalk-collision count, county accounting (with the full enumeration of
  the 115 need-side counties absent from the panel: 67 FL, 8 CT, 34 VA
  independent cities, 2 AK, 1 each HI/ND/NM/TX), gap-score math reproduction,
  full re-scoring, exact 28-pair grid coverage, correlation-direction checks
  (gap~poverty positive, gap~NGO-density negative), and raw-file provenance
  (NGO extract ordering/uniqueness, F9 duplicate/year/return-type stats).
- **`src/statistical_critic.py`** — a deterministic Critic that goes beyond
  the naive sign check *and* beyond the TA benchmark's single-pair permutation
  test: Benjamini-Hochberg FDR across all 28 grid tests, a fixed-seed
  **state-stratified permutation test for every LLM-proposed pair** (2,000
  within-state shuffles), and a documented `supported` / `weak_direction` /
  `unsupported` classification with a team-defined |ρ| ≥ 0.10 effect floor.
  New `correlation_results.csv` columns: `spearman_q_bh`, `permutation_p`,
  `claim_status`, `critic_reason`.
- **Food-specific gap** — `food_ngo_per_10k`, `food_capacity_score`, and
  `food_gap_score` (need vs food-sector nonprofit density). The original
  `gap_score` is unchanged in meaning and now explicitly documented as the
  *general*-capacity gap. Rankings correlate strongly (rank ρ reported in the
  findings summary) but are not identical.
- **Filing coverage columns** — `matched_filer_count` and
  `filer_coverage_rate` per county; the sparse NGO→990 enrichment join is now
  recorded by the profiler (coverage 3.59%) instead of being invisible.
- **Score completeness** — `need_component_count` / `capacity_component_count`
  mark the 99 counties without poverty data and the ~800 without financials.
- **`tests/` (34 pytest tests)** — F9 filing selection, missing-vs-zero
  financials, gap math, component counts, BH values, critic classification
  boundaries, permutation determinism and state-artifact behavior, LLM-output
  dedup/truncation/sign normalization, constant-column safety, cache staleness.
- **LLM cache integrity** — `llm_candidates.json` now carries a
  `prompt_version`, SHA-256 hashes of the exact schema context and gate it was
  generated against, and an explicit `source` (`live_api` vs
  `offline_development_session`); offline replay against a changed panel or
  gate is rejected as stale (`--allow-stale-cache` for scratch runs only).
- **`--output-dir` on both scripts** — `--sample --mock` smoke runs can no
  longer overwrite the committed real-run evidence.

### Fixed
- **F9 filings were being summed per EIN.** The 2022 summary file mixes tax
  years (131,376×2022, 123×2019, 86×2020) and holds 539 duplicated-EIN groups;
  the old code summed all of an EIN's returns. Now exactly one filing per EIN
  is kept (latest tax year, largest-revenue tie-break, documented in
  `select_one_filing_per_ein`).
- **Missing financials were reported as zero.** Counties with no matched filer
  (803 of 3,029) previously got `total_revenue/assets = 0`; they are now NaN
  (unobserved), and a genuine reported zero survives as 0. Capacity scores for
  those counties average their remaining indicators.
- **Terminology** — the filings are 990/990EZ/990PF (72,985 / 58,513 / 87),
  not "full 990s"; the NGO file is an **ordered, truncated extract** (Excel
  row limit, EIN-sorted), not a random "sample"; `avg_food_desert_pct` is a
  0–1 population share (mock generator aligned); `med_household_income` is
  labeled an inverse-need/context measure.

### Changed findings (honest correction)
On the corrected panel, the LLM's 7 proposed signs no longer all match: **6/7
match**, and the critic grades them **3 supported, 2 weak-direction, 2
unsupported**. Notably, `poverty_rate ~ ngo_per_10k` — hugely "significant" by
q-value — fails the state-stratified permutation test outright (p = 1.0): the
association is a between-state artifact, not a within-state pattern. The
wealth-capacity result (`med_household_income ~ revenue_per_capita`) weakens
from ρ = +0.33 to +0.25 after the missing-vs-zero correction but survives the
critic. The former blanket claim "all 7 hypothesized signs were confirmed"
should be read through this revision.

## Checkpoint 3 — 2026-07-14

The LLM-assisted analysis layer on top of the deterministic Checkpoint 2 panel:
correlation agent, figures, and a findings summary. Python remains the source
of truth for every statistic; the LLM only proposes candidates, reviews the
gate, and frames the narrative.

### Added
- **`src/correlation_agent.py`** — the Checkpoint 3 agent. Builds a schema-only
  context (column names + summary stats, never raw rows), asks the LLM for 5–8
  candidate need-vs-capacity pairs with hypotheses/expected signs plus an
  **advisory gate review**, and hard-validates the response (unknown columns are
  dropped). Python then computes Pearson + Spearman for the **exhaustive
  need × capacity grid** and checks each LLM hypothesis against the measured sign.
- **Reproducible LLM caching** — every LLM response is cached to
  `data/output/llm_candidates.json` (committed). The default offline mode
  replays the cache byte-for-byte so the whole analysis reruns **without an API
  key**; `--live` regenerates it through the Anthropic API.
- **`src/make_plots.py`** — four figures in `data/output/figures/`:
  `top_gap_counties.png`, `need_vs_capacity.png`, `gap_distribution.png`,
  `correlation_heatmap.png` (headless matplotlib, committed as evidence).
- **`scripts/run_analysis.py`** — Checkpoint 3 orchestration
  (`--live`, `--model`, `--skip-plots`): panel → correlation grid → LLM
  candidates → evaluation → figures → findings summary.
- **`data/output/correlation_results.csv`** — the authoritative 28-pair grid
  annotated with which pairs the LLM proposed and whether its sign held.
- **`data/output/findings_summary.md`** — generated findings summary; every
  number is Python-computed, the LLM contributes hypotheses/framing only.

### Findings (from the committed run)
- Nonprofit capacity tracks **wealth, not need**: `med_household_income` vs
  `revenue_per_capita` ρ=+0.33, while `poverty_rate` vs `revenue_per_capita`
  ρ=−0.29 and `unemployment` vs `ngo_per_10k` ρ=−0.31.
- All 7 LLM-hypothesized signs were confirmed by the Python-computed statistics
  (two of them — the food-desert pairs — are directionally right but weak).
- The LLM's advisory gate review agreed with the rule-based
  `proceed_with_warning` verdict; the rule-based gate remains authoritative.

### Removed
- `CLAUDE.md` (local development notes) removed from the repository.

## Checkpoint 2 — 2026-06-30

The first real pipeline: load → profile (+ gate) → build tables → join + score.

### Added
- **`src/load_data.py`** — `DataLoader` for all six raw files: transparent `.gz`
  decompression, `snake_case` column normalization as the single source of truth,
  identifier columns (EIN/FIPS/GEOID) preserved as zero-padded strings, and a
  `sample_mode` (10k rows/file) for fast iteration.
- **`src/profile_data.py`** — automated profiler: per-table schema/null audit,
  per-join match-rate validation, `usable / usable_with_warning / drop` verdicts,
  and an overall **`proceed / proceed_with_warning / stop` self-verification gate**
  that the pipeline checks before running downstream steps.
- **`src/crosswalk.py`** — automated, rules-based county-name → FIPS resolution
  (suffix stripping, case folding, FIPS zero-padding), keyed on `(state, name)`.
  **No manual FL/CT patches** — unresolved rows are flagged and auto-dropped.
- **`src/build_capacity_table.py`** — NGO + F9 990 aggregation to county-level
  capacity metrics (`ngo_count`, `food_ngo_count`, `total_revenue`, `total_assets`),
  with a synthetic `mock_capacity_table()` for `--mock` runs.
- **`src/build_need_table.py`** — DAC + poverty + NCCS aggregation to county-level
  need metrics (population-weighted food desert / housing burden / DAC score,
  poverty rate, income, unemployment), with a `mock_need_table()`.
- **`src/join_logic.py`** — inner join of capacity + need on `county_fips` and the
  gap score: `gap_score = need_score − capacity_score`.
- **`scripts/run_pipeline.py`** — end-to-end orchestration with `--sample`,
  `--mock`, `--verbose`; halts when the gate verdict is `stop`.
- **Project config** — `requirements.txt` (pandas, numpy, matplotlib, scipy),
  `README.md`, and `.gitignore` (output artifacts intentionally **not** ignored).
- **`data/output/` evidence** — committed `joined_county_panel.csv` (3,027 counties)
  and `profiler_log.json` (verdicts + gate + panel summary).

### Verified (CP2 validation pass)
- Independent raw recomputes of capacity (Cook County `ngo=15965, food=71`) and
  need (population-weighted means) match the panel **exactly**.
- Gap-score math reproduces to ~1e-16; direction confirmed
  (`corr(gap, poverty)=+0.59`, `corr(gap, ngo_per_10k)=−0.61`).
- Crosswalk has **zero** `(state, name)` collisions; no FL/CT leak into the panel.
- DAC-summed population is within 0.98–1.03× of known county populations.
- Top-gap counties are face-valid (Mississippi Delta, Texas border, Appalachian
  KY, reservation counties).

### Changed
- **Gap score robustness** — capacity indicators (`ngo_per_10k`,
  `revenue_per_capita`, `assets_per_capita`) are now standardized on a
  **signed-log transform** (`sign(x)·log1p(|x|)`) rather than raw values.
  Found during validation: `assets_per_capita` skew was ~20, letting a single
  county with a large nonprofit (z ≈ 38) dominate the score and push its gap to
  −15. The transform tightens the gap distribution to a sane, near-symmetric
  `[−3.7, +4.4]` while preserving (and sharpening) the high-gap rankings. Raw
  per-capita columns are still written to the panel for interpretability.

### Notes
- `NGOs_with_categories_1MILLION_rows.csv.gz` is a **1,048,575-row sample** of the
  3,420,024-row source table; all county aggregates are sample-based.
- LLM correlation-candidate generation and the LLM-assisted gate remain
  **Checkpoint 3** scope; the rule-based gate and architecture hook are in place.
