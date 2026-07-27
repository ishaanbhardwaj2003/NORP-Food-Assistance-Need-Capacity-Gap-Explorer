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
response cache. As of the final checkpoint the pipeline runs on the **full
3,420,024-row** `NGOs_with_categories` table, closing the truncated-extract
data gap flagged in the CP2 and CP3 feedback.

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
4. **Statistical critic (Python, deterministic).** Every LLM-proposed pair is
   re-tested before it may be called a finding: Benjamini-Hochberg FDR
   correction across the full 28-test grid, a fixed-seed **state-stratified
   permutation test** (2,000 within-state shuffles, so between-state artifacts
   don't count as signal), and a documented effect-size floor (|ρ| ≥ 0.10,
   a team choice). Verdicts are `supported` / `weak_direction` / `unsupported`
   — *"the sign matched" and "the claim is supported" are different things.*
5. **State fixed-effects estimator (Python, deterministic).** The headline
   wealth-capacity relationship is re-estimated with state fixed effects
   absorbed and cluster-robust (CR1) standard errors at the state level, on
   the panel's signed-log scale. The estimator core is adapted from the TA
   benchmark branch (`ai-suggestions/cp4`); see "Engaging the benchmark".

> [!IMPORTANT]
> **No manual geographic patching.** Florida is absent from `county_fips_lookup`
> and Connecticut nonprofits use planning-region names instead of counties.
> Rather than hand-patching these, the profiler logs them and the pipeline
> auto-drops them. On the full table that drop is 230,414 of the 231,927
> unmatched rows (99.3%); everything else resolves through the general
> crosswalk rules below.

## The final-checkpoint crosswalk (exact-first, two stages)

Auditing the TA benchmark branch showed its Virginia fix recovered **zero** of
the 5,291 dropped VA rows on the real data: the lookup stores most VA
independent cities as bare names ("Alexandria") while NGO rows say
"Alexandria City", and no stage bridged that. The rebuilt resolver
(`src/crosswalk.py`) is rules-based end to end:

1. **Exact stage**: match the folded full name, keeping same-stem pairs apart
   (Fairfax City 51600 vs Fairfax County 51059; Charles City / James City are
   genuine counties). Adapted from the benchmark's exact-first concept, with
   its collision audit (`va_collision_pairs`) kept as machine-checked evidence.
2. **Fallback stage**: strip at most one trailing geographic suffix — the list
   now includes bare "city" — and rematch ("Alexandria City" → 51510).

Text folding on both sides also repairs the lookup's own encoding damage
("DoÃ±a Ana" is UTF-8 read as Latin-1) and strips accents, recovering
Doña Ana NM (35013). Net effect: all 34 VA independent cities plus Doña Ana
enter the panel; no other state's match rate declines
(`verify_outputs.py::crosswalk_recovery` asserts all of it).

## Data

All raw inputs live in `data/raw/`.

| File | Rows | Role |
|---|---|---|
| `ngos_full/NGOs_with_categories.part1-4.csv.gz` | 3,420,024 | **Full** nonprofit table (EIN, county, NTEE category) |
| `NGOs_with_categories_1MILLION_rows.csv.gz` | 1,048,575 | The CP2/CP3 truncated extract (kept for the bias analysis) |
| `F9_P01_T00_SUMMARY_2022.csv` | 131,587 | IRS Form 990 financials (revenue, net assets) |
| `disadvantaged_communities.csv` | 72,742 | Census-tract need (food desert, housing burden, DAC) |
| `county_fips_lookup.csv` | 3,076 | County-name → FIPS crosswalk |
| `Poverty_Rates_2023.csv` | 2,998 | County poverty rate |
| `nccs_crosswalk_economic.csv` | 3,142 | County income / poverty / unemployment |

County geometry for the choropleths is committed at
`data/reference/us_counties_geo.json` (public-domain Census-derived GeoJSON;
see `data/reference/PROVENANCE.md`).

> [!NOTE]
> The full table ships as **four gzipped parts** (36–41 MB each) because the
> single 162 MB export exceeds GitHub's 100 MB file cap; `DataLoader`
> concatenates them transparently and records which source it read.
> `scripts/assemble_ngo_parts.py` validates and re-creates the parts from a
> single-file export. Validation anchors: 3,420,024 rows (the CP1-verified
> Metabase count), all EINs unique, and 40,086 `Food, Agriculture and
> Nutrition` orgs (CP1 verified ~40,080). The source's
> `is_category_LLM_generated` flag is null on **every** row, so upstream
> category provenance remains a disclosed caveat.

> [!NOTE]
> The retired extract was an **ordered, truncated, non-random cut** (exactly
> the Excel export limit, EIN-sorted). With the full table in hand the bias is
> now *measured*, not just disclosed: the extract covered 30.7% of rows but
> only 26.2% of food nonprofits and 16.1% of Alaska's; two food-sector
> correlations reverse sign on the full data. See
> `data/output/truncation_analysis.json` and
> `data/output/full_vs_extract_comparison.json`.

> [!NOTE]
> `F9_P01_T00_SUMMARY_2022.csv` contains **990, 990EZ, and 990PF** summary
> filings (not exclusively "full 990s") with mixed tax years (2019/2020/2022)
> and 539 duplicated-EIN groups. The pipeline keeps **one filing per EIN**
> (latest year, revenue tie-break). Only ~3.7% of NGOs match a filing;
> counties with **no matched filer get missing (NaN) financials, never a
> fabricated zero**, and carry `matched_filer_count` / `filer_coverage_rate`.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
# 1) Full pipeline → data/output/joined_county_panel.csv + profiler_log.json
#    (reads the committed full-table parts automatically)
python scripts/run_pipeline.py --verbose

# 2) Analysis → correlations, critic, fixed effects, figures, findings summary
#    (offline by default: replays the committed LLM cache, no API key needed)
python scripts/run_analysis.py

# 3) Truncation-bias measurement (extract vs full table)
python scripts/analyze_truncation.py

# 4) Verify every committed claim (also written to validation_report.json)
python scripts/verify_outputs.py

# 5) Unit tests (no API key, no large files)
python -m pytest -q

# Optional: refresh the LLM artifact through the Anthropic API
ANTHROPIC_API_KEY=... python scripts/run_analysis.py --live

# Optional: rebuild the panel from the retired extract (for comparisons)
python scripts/run_pipeline.py --ngo-source extract --output-dir /tmp/norp-extract
python scripts/compare_extract_vs_full.py --extract-panel /tmp/norp-extract/joined_county_panel.csv

# Fast smoke test in an isolated directory (never touches committed evidence)
python scripts/run_pipeline.py --sample --mock --output-dir /tmp/norp-smoke
python scripts/run_analysis.py --output-dir /tmp/norp-smoke --allow-stale-cache
```

`run_pipeline.py` flags: `--sample`, `--mock`, `--verbose`, `--output-dir`,
`--ngo-source {auto,full,extract}`. `run_analysis.py` flags: `--live`,
`--model`, `--skip-plots`, `--output-dir`, `--cache`, `--allow-stale-cache`.
The committed LLM cache carries SHA-256 hashes of the schema context and gate
it was generated against; replaying it against a changed panel is rejected as
stale unless explicitly overridden. After a panel-changing edit, regenerate it
with `--live` or `scripts/regen_offline_cache.py` (no key; the artifact's
metadata discloses its offline authorship).

## Pipeline stages

```
load_data → profile_data (+ gate) → [gate check] → build_capacity_table
          → build_need_table → join_logic (inner join + gap scores) → output/
          → correlation_agent (LLM candidates + Python-computed grid)
          → statistical_critic (BH FDR + stratified permutations + verdicts)
          → fixed_effects (state-FE + cluster-robust SEs, signed-log scale)
          → make_plots + make_maps (figures, county choropleths, cartogram)
          → findings_summary.md
          → analyze_truncation / compare_extract_vs_full (data-gap evidence)
          → verify_outputs (committed validation of every claim, 17 checks)
```

`gap_score = need_score − capacity_score`, where each score is the mean of the
available indicators' z-scores. Need indicators (bounded percentages) are scored
linearly; the per-capita capacity indicators are signed-log transformed first so
a few financial outliers can't dominate. Two gaps are reported: **`gap_score`**
compares food-related need against *all* nonprofit capacity, and
**`food_gap_score`** against food-sector nonprofit density specifically.
`need_component_count` / `capacity_component_count` record how many indicators
entered each county's score. A high gap is a **triage signal** ("worth
investigating"), not a causal claim about nonprofit effectiveness.

## Engaging the benchmark (`ai-suggestions/cp4`)

The TA-generated benchmark branch is kept in this repository for auditability.
What we adopted, with credit in the docstrings: the exact-first crosswalk
concept and collision audit, the fixed-effects estimator core (within
transform, CR1 cluster SEs, pooled-vs-FE contrast), and the state tile
cartogram. What we fixed: its VA crosswalk recovered zero rows on the real
data (its fixtures only tested lookup-verbatim names); its FE regressed raw
outlier-dominated dollars (ours uses the panel's signed-log scale with a
raw-scale sensitivity fit); its county choropleth required geopandas plus a
geometry file it did not ship; and none of it was wired into the pipeline,
findings, or verification. What we added beyond it: the encoding-repair rule,
the full-table integration, the truncation-bias measurement, and the
extract-vs-full conclusion audit.

## Layout

```
src/
  load_data.py            # DataLoader: 6 raw inputs, snake_case, multi-part full table
  profile_data.py         # profiler, quality gate, proceed/stop verdict
  crosswalk.py            # exact-first county-name resolution (no manual patches)
  build_capacity_table.py # NGO + F9 → county capacity metrics
  build_need_table.py     # DAC + poverty + NCCS → county need metrics
  join_logic.py           # county panel inner join + general & food gap scores
  correlation_agent.py    # LLM candidate proposals + exhaustive Python correlations
  statistical_critic.py   # BH FDR + state-stratified permutation critic
  fixed_effects.py        # state-FE OLS, cluster-robust SEs (benchmark-adapted)
  make_plots.py           # top-gap / scatter / distribution / heatmap figures
  make_maps.py            # county choropleths + state cartogram (no GIS deps)
scripts/
  run_pipeline.py         # pipeline orchestration (CP2; --ngo-source flag)
  run_analysis.py         # analysis orchestration (CP3 + final layers)
  verify_outputs.py       # committed verification: 17 machine checks
  assemble_ngo_parts.py   # validate/split the full NGO export into parts
  analyze_truncation.py   # extract-vs-full truncation bias measurement
  compare_extract_vs_full.py  # which conclusions survive the full data
  regen_offline_cache.py  # rebuild the hash-bound LLM artifact (no key)
  make_slides.py          # build the presentation deck from committed evidence
tests/                    # 66 pytest tests (offline, no API key, no big files)
data/
  raw/                    # committed inputs (incl. ngos_full/ parts)
  reference/              # county geometry + provenance
  output/                 # generated evidence (committed, see below)
presentation/             # final deck + narration script
```

## Output

All committed to `data/output/` as self-contained evidence:

- `joined_county_panel.csv` — **3,066 counties**, one row each: capacity
  metrics (including `matched_filer_count` / `filer_coverage_rate`), need
  metrics, `need_score` / `capacity_score` / `gap_score`, the food-specific
  `food_capacity_score` / `food_gap_score`, and per-county component counts.
- `profiler_log.json` — per-table schema and null audit, per-join match rates,
  the NGO source that was read (full parts vs extract), and the gate verdict.
- `correlation_results.csv` — the exhaustive need × capacity Pearson/Spearman
  grid with BH-adjusted q-values, and per-proposed-pair permutation p /
  `claim_status` / `critic_reason` from the statistical critic.
- `fixed_effects_results.json` — the state-FE estimates (headline + inverse
  and density specs + raw-scale sensitivity), cluster-robust inference.
- `llm_candidates.json` — the cached LLM artifact (schema context, candidate
  hypotheses, advisory gate review) with integrity hashes; replayed by offline
  runs, rejected if stale.
- `truncation_analysis.json` — the measured bias of the retired extract.
- `full_vs_extract_comparison.json` — CP3 panel vs extract+new-crosswalk vs
  full-data panel: what changed and why, including critic verdict changes.
- `validation_report.json` — machine-readable result of `verify_outputs.py`
  (17 checks), including the full enumeration of the 76 need-side counties
  absent from the panel (67 FL, 8 CT, 1 other).
- `figures/` — the four CP3 figures plus the two county choropleths, the
  state cartogram, and the truncation-bias chart (+ `choropleth_meta.json`).
- `findings_summary.md` — the generated findings summary (Python-computed
  numbers, LLM framing).
