# CLAUDE.md

Guidance for working in this repository.

## What this project is

An **agentic data-exploration pipeline** answering: *where does food-related
community need outpace nonprofit capacity?* It joins nonprofit data with
county-level need indicators, profiles/gates the data automatically, and computes
an explainable per-county **gap score**. Unit of analysis: **county (5-digit FIPS)**.
Python is the source of truth for all statistics.

Course context: CS 6365 group project (Ishaan Bhardwaj & Gowtam Kommi).
Checkpoint 2 is the current state. Checkpoint 3 adds the LLM correlation agent,
plots, and a findings summary.

## Architecture / pipeline

```
load_data → profile_data (+ gate) → [gate check] → build_capacity_table
          → build_need_table → join_logic (inner join + gap score) → data/output/
```

| File | Role |
|---|---|
| `src/load_data.py` | `DataLoader`: 6 raw files, snake_case, `.gz`, `sample_mode` |
| `src/profile_data.py` | profiler + `proceed/proceed_with_warning/stop` gate |
| `src/crosswalk.py` | county-name → FIPS normalization (no manual patches) |
| `src/build_capacity_table.py` | NGO + F9 → county capacity metrics (+ mock) |
| `src/build_need_table.py` | DAC + poverty + NCCS → county need metrics (+ mock) |
| `src/join_logic.py` | inner join + need/capacity/gap scores |
| `scripts/run_pipeline.py` | orchestration; CLI flags |

## Run / test

```bash
python scripts/run_pipeline.py --verbose            # full real run (~15s, loads 1M NGO rows)
python scripts/run_pipeline.py --sample --mock      # fast smoke test
python -m py_compile src/*.py scripts/*.py           # compile check
```

Outputs (committed as evidence, **not** gitignored): `data/output/joined_county_panel.csv`,
`data/output/profiler_log.json`.

## Conventions & key facts

- **Commit authorship: NEVER list Claude/AI as an author or co-author.** Only the
  human authors (Ishaan Bhardwaj, co-author Gowtam Kommi `<gkommi@users.noreply.github.com>`).
  Git has no local identity configured — set it inline:
  `git -c user.name="Ishaan Bhardwaj" -c user.email="ishaanbhardwaj2003@gmail.com" commit ...`.
- **`snake_case` from `DataLoader` is the single source of truth** for column names
  (e.g. `F9 01 Rev Tot Cy` → `f9_01_rev_tot_cy`, `Dac Status` → `dac_status`).
  Reference post-normalization names everywhere downstream.
- **Identifiers are zero-padded strings.** FIPS → 5 digits, EIN → 9 digits.
  Never let pandas read them as ints (loses leading zeros, e.g. FIPS `01001`).
- **No manual geographic patching.** FL is absent from `county_fips_lookup`; CT
  nonprofits use planning-region names. These auto-drop and are logged — do not
  hardcode FIPS for them. This is a deliberate response to grading feedback.
- **Data artifacts belong in git.** `data/output/` is intentionally committed so the
  pipeline's results are self-contained evidence.

## Gap-score methodology

- `need_score` = mean z-score of need indicators (`poverty_rate`,
  `avg_food_desert_pct`, `avg_housing_burden`) — bounded %, scored linearly.
- `capacity_score` = mean z-score of per-capita capacity indicators
  (`ngo_per_10k`, `revenue_per_capita`, `assets_per_capita`), each first put
  through a **signed-log transform** `sign(x)·log1p(|x|)` so financial outliers
  (asset-per-capita skew ~20) don't dominate. Raw per-capita columns are kept in
  the panel for interpretability.
- `gap_score = need_score − capacity_score`. High = need outpaces capacity. It is a
  **triage signal, not a causal claim**.

## Gotchas

- `dac_status` holds the **strings** `'true'`/`'false'`, not booleans.
- `nccs_crosswalk_economic.geoid_2010` is **not** zero-padded (`1001` → pad to `01001`).
- `food_desert_pct` has empty-string nulls → coerce to NaN before weighting.
- The F9 990 join is **sparse** (~3% of NGOs have a filing); counties with no
  filer correctly get `total_revenue/assets = 0`, not NaN.
- Exact food category label: `'Food, Agriculture and Nutrition'`.

## Validating changes

A standalone validation script (independent raw recomputes, gap-score math,
crosswalk collisions, face validity) lives in the session scratchpad. When
changing the scoring or builders, re-run the pipeline and confirm: panel = 3,027
counties, no FL/CT, gap math reproduces, and top-gap counties remain poor rural
counties.
