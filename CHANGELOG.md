# Changelog

All notable changes to the NORP Food Assistance Need-Capacity Gap Explorer.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

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
