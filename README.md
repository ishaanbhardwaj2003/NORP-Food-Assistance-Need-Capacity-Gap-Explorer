# NORP Food Assistance Need-Capacity Gap Explorer

An **agentic data-exploration pipeline** that asks: *where does food-related
community need outpace nonprofit capacity to address it?* It joins nonprofit
financial/category data with county-level need indicators, profiles and gates
the data automatically, and computes an explainable **gap score** per U.S.
county.

The unit of analysis is the **county** (joined on 5-digit FIPS). Python is the
source of truth for all statistics. The LLM layer (correlation-candidate
generation, advisory gate review, and narrative framing) sits on top of the
deterministic pipeline and is fully reproducible offline via a committed
response cache.

## Where the agent acts

1. **Data-quality triage + gate (rule-based, authoritative).** The profiler
   classifies each table/join as `usable` / `usable_with_warning` / `drop` and
   the pipeline **acts on that classification without manual intervention** —
   auto-dropping a state from a join when its match rate is too low, then
   logging why, and emitting an overall
   `proceed / proceed_with_warning / stop` verdict that gates downstream steps.
2. **Correlation-candidate generation (LLM, advisory).** The agent sees only
   the panel *schema* (column names + summary stats, never raw rows) and
   proposes need-vs-capacity pairs with hypotheses and expected signs. Python
   then computes Pearson + Spearman for the **exhaustive** need × capacity
   grid, so the LLM prioritizes but can never invent or skew a statistic.
3. **Gate review (LLM, advisory).** The agent issues a second opinion on the
   rule-based gate verdict. Disagreement is logged, never acted on — the
   rule-based verdict stays authoritative.

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
# 1) Full pipeline → data/output/joined_county_panel.csv + profiler_log.json
python scripts/run_pipeline.py --verbose

# 2) Checkpoint 3 analysis → correlations, figures, findings summary
#    (offline by default: replays the committed LLM cache, no API key needed)
python scripts/run_analysis.py

# Optional: refresh the LLM artifact through the Anthropic API
ANTHROPIC_API_KEY=... python scripts/run_analysis.py --live

# Fast pipeline iteration: 10k rows/file, synthetic capacity/need tables
python scripts/run_pipeline.py --sample --mock --verbose
```

`run_pipeline.py` flags: `--sample` (10k rows/file), `--mock` (synthetic
capacity/need tables), `--verbose`. `run_analysis.py` flags: `--live` (call the
Anthropic API and rewrite `data/output/llm_candidates.json`), `--model`
(default `claude-opus-4-8`), `--skip-plots`.

## Pipeline stages

```
load_data → profile_data (+ gate) → [gate check] → build_capacity_table
          → build_need_table → join_logic (inner join + gap score) → output/
          → correlation_agent (LLM candidates + Python-computed grid)
          → make_plots (figures) → findings_summary.md
```

`gap_score = need_score − capacity_score`, where each score is the mean of the
available indicators' z-scores. Need indicators (bounded percentages) are scored
linearly; the per-capita capacity indicators are signed-log transformed first so
a few financial outliers can't dominate. A high gap is a **triage signal**
("worth investigating"), not a causal claim about nonprofit effectiveness.

## Layout

```
src/
  load_data.py            # DataLoader: all 6 raw files, snake_case, .gz, sample mode
  profile_data.py         # profiler, quality gate, proceed/stop verdict
  crosswalk.py            # automated county-name normalization (no manual patches)
  build_capacity_table.py # NGO + F9 → county capacity metrics
  build_need_table.py     # DAC + poverty + NCCS → county need metrics
  join_logic.py           # county panel inner join + gap score
  correlation_agent.py    # LLM candidate proposals + exhaustive Python correlations
  make_plots.py           # top-gap / scatter / distribution / heatmap figures
scripts/
  run_pipeline.py         # pipeline orchestration (Checkpoint 2)
  run_analysis.py         # analysis orchestration (Checkpoint 3)
data/
  raw/                    # committed inputs
  output/                 # generated evidence (committed, see below)
```

## Output

All committed to `data/output/` as self-contained evidence:

- `joined_county_panel.csv` — one row per county with capacity metrics, need
  metrics, and `need_score` / `capacity_score` / `gap_score`.
- `profiler_log.json` — per-table schema and null audit, per-join match rates,
  and the overall gate verdict with reasons.
- `correlation_results.csv` — the exhaustive need × capacity Pearson/Spearman
  grid, annotated with the LLM's proposed pairs and sign checks.
- `llm_candidates.json` — the cached LLM artifact (schema context, candidate
  hypotheses, advisory gate review); replayed by offline runs.
- `figures/` — the four Checkpoint 3 figures.
- `findings_summary.md` — the generated findings summary (Python-computed
  numbers, LLM framing).
