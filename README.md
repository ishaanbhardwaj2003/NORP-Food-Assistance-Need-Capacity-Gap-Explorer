# NORP Food Assistance Need-Capacity Gap Explorer

An **agentic data-exploration pipeline** that asks: *where does food-related
community need outpace nonprofit capacity to address it?* It joins nonprofit
financial/category data with county-level need indicators, profiles and gates
the data automatically, and computes an explainable **gap score** per U.S.
county.

The unit of analysis is the **county** (joined on 5-digit FIPS). Python is the
source of truth for all statistics. An LLM layer (correlation-candidate
generation + summarization) is planned as a later phase; the pipeline in this
repository is fully deterministic.

## Where the agent acts

The profiler classifies each table/join as `usable` / `usable_with_warning` /
`drop` and the pipeline **acts on that classification without manual
intervention** — auto-dropping a state from a join when its match rate is too
low, then logging why, and emitting an overall
`proceed / proceed_with_warning / stop` verdict that gates downstream steps.

> [!IMPORTANT]
> **No manual geographic patching.** Florida is absent from `county_fips_lookup`
> and Connecticut nonprofits use planning-region names instead of counties.
> Rather than hand-patching these, the profiler logs them and the pipeline
> auto-drops them — 48+ other states remain for automated exploration.

## Data

All raw inputs live in `data/raw/`.

| File | Rows | Role |
|---|---|---|
| `NGOs_with_categories_1MILLION_rows.csv.gz` | 1,048,575 | Nonprofit capacity (EIN, county, NTEE category) |
| `F9_P01_T00_SUMMARY_2022.csv` | 131,587 | IRS Form 990 financials (revenue, net assets) |
| `disadvantaged_communities.csv` | 72,742 | Census-tract need (food desert, housing burden, DAC) |
| `county_fips_lookup.csv` | 3,076 | County-name → FIPS crosswalk |
| `Poverty_Rates_2023.csv` | 2,998 | County poverty rate |
| `nccs_crosswalk_economic.csv` | 3,142 | County income / poverty / unemployment |

> [!NOTE]
> `NGOs_with_categories_1MILLION_rows.csv.gz` is a **1,048,575-row sample** of
> the **3,420,024-row** `NGOs_with_categories` source table. Category counts
> scale accordingly (the sample has **10,507** `Food, Agriculture and Nutrition`
> orgs vs ~40,080 in the full table), so all county aggregates here are
> **sample-based**.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
# Full pipeline → data/output/joined_county_panel.csv + profiler_log.json
python scripts/run_pipeline.py --verbose

# Fast iteration: 10k rows/file, synthetic capacity/need tables
python scripts/run_pipeline.py --sample --mock --verbose
```

Flags: `--sample` (10k rows/file), `--mock` (synthetic capacity/need tables to
exercise the pipeline without the full aggregation), `--verbose`.

## Pipeline stages

```
load_data → profile_data (+ gate) → [gate check] → build_capacity_table
          → build_need_table → join_logic (inner join + gap score) → output/
```

`gap_score = need_score − capacity_score`, where each score is the mean of the
available indicators' z-scores. A high gap is a **triage signal** ("worth
investigating"), not a causal claim about nonprofit effectiveness.

## Layout

```
src/
  load_data.py            # DataLoader: all 6 raw files, snake_case, .gz, sample mode
  profile_data.py         # profiler, quality gate, proceed/stop verdict
  crosswalk.py            # automated county-name normalization (no manual patches)
  build_capacity_table.py # NGO + F9 → county capacity metrics
  build_need_table.py     # DAC + poverty + NCCS → county need metrics
  join_logic.py           # county panel inner join + gap score
scripts/
  run_pipeline.py         # end-to-end orchestration
data/
  raw/                    # committed inputs
  output/                 # generated: joined_county_panel.csv, profiler_log.json
```

## Output

`data/output/joined_county_panel.csv` — one row per county with capacity
metrics, need metrics, and `need_score` / `capacity_score` / `gap_score`.

`data/output/profiler_log.json` — per-table schema and null audit, per-join
match rates, and the overall gate verdict with reasons.
