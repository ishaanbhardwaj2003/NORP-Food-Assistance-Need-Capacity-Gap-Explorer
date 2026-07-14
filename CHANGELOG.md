# Changelog

All notable changes to the NORP Food Assistance Need-Capacity Gap Explorer.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

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
