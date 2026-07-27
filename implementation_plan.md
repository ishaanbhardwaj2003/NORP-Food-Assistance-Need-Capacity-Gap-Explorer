# Checkpoint 2 Implementation Plan: NORP Food Assistance Need-Capacity Gap Explorer

## Background & Motivation

This plan is informed by a deep analysis of all 6 raw datasets now committed in `data/raw/`, and incorporates the **Checkpoint 1 grading feedback** which identified two critical issues:

1. **The repository was essentially empty** — no code skeleton, no meaningful structure despite claiming "in progress" status.
2. **Avoid the manual data-engineering trap** — we designed an automated profiler to handle unjoinable data, so we should **let it do its job** rather than manually patching FL/CT FIPS codes. If those states fail the quality gate, they get logged and auto-dropped. We have 48+ other states ready for automated sociological exploration.

> [!CAUTION]
> **Key Lesson from Checkpoint 1 Feedback**: The graders flagged that manually forcing joins (e.g., hardcoding FL FIPS patches) defeats the purpose of the automated profiler. The revised plan below removes all manual patching in favor of a robust, automated quality gate that handles edge cases programmatically.

---

## Data Landscape (From Deep Investigation)

Here is what I found by examining every file in `data/raw/`:

| Dataset | Rows | Key Columns | Notes |
|---|---|---|---|
| `NGOs_with_categories_1MILLION_rows.csv.gz` | 1,048,575 *(sample of 3.42M)* | `Ein`, `State`, `County`, `Category` | County has suffix (e.g., "Autauga **County**"), lookup does not. 9 CT planning regions instead of counties. **This file is a ~31% sample of the 3,420,024-row Metabase table from CP1 — see README disclaimer.** |
| `F9_P01_T00_SUMMARY_2022.csv` | 131,587 | `Org Ein`, `F9 01 Rev Tot Cy`, `F9 01 Nafb Tot Eoy` | IRS 990 filings. Only 28.7% of EINs overlap with NGOs (expected: not all orgs file 990s). |
| `disadvantaged_communities.csv` | 72,742 | `County Fips`, `Population`, `Food Desert Pct`, `Avg Housing Burden`, `Dac Score` | Census-tract level. 3,142 unique county FIPS. Already has clean FIPS. |
| `county_fips_lookup.csv` | 3,076 | `County Fips`, `County Name`, `State` | Missing **all 67 Florida counties** and 1 Alaska borough. County names are bare (no "County" suffix). |
| `Poverty_Rates_2023.csv` | 2,998 | `Fips Code`, `Poverty Percentage` | County-level, clean FIPS. |
| `nccs_crosswalk_economic.csv` | 3,142 | `Geoid 2010`, `Med Household Income Adj`, `Poverty Perc`, `Unemployment` | County-level economic indicators. |

### Critical Data Findings

> [!IMPORTANT]
> **Finding 1: County Name Mismatch** — NGOs use "Autauga **County**", "Acadia **Parish**", etc. The lookup uses bare names ("Autauga", "Acadia"). Simple suffix stripping (`County`, `Parish`, `Borough`, `Census Area`) resolves **95.1%** of NGO rows (997,319 of 1,048,575). This is automated normalization, not manual patching.

> [!IMPORTANT]
> **Finding 2: FL & CT account for 98% of unmatched rows** — After suffix stripping, 51,256 rows remain unmatched. Of these: FL = 38,915 (76%), CT = 11,352 (22%), other = 989 (2%). Per grader feedback, **the profiler should auto-flag and log these rather than us manually injecting FIPS mappings**.

> [!WARNING]
> **Finding 3: EIN Join is Sparse** — Only 37,622 EINs overlap between NGOs (1.05M unique) and F9 (131K unique). This is expected (many small nonprofits file 990-N, not full 990s). The capacity table should be built from NGOs as the base, with F9 financials **left-joined** as an enrichment layer.

> [!NOTE]
> **Finding 4: Need-Side Tables Are Clean** — `disadvantaged_communities`, `Poverty_Rates_2023`, and `nccs_crosswalk_economic` all use clean county FIPS codes. They align well (2,997 counties in common across all three). The need table can be built purely by aggregating `disadvantaged_communities` tracts to county level and joining to the other two by FIPS.

---

## Division of Labor

| Owner | Module | Description |
|---|---|---|
| **Ishaan** | `src/load_data.py` | Data loader for all 6 raw files |
| **Ishaan** | `src/profile_data.py` | Automated data-quality profiler with quality gate |
| **Ishaan** | `src/crosswalk.py` | Automated county name normalization (suffix stripping + case folding) — **no manual patches** |
| **Ishaan** | `src/join_logic.py` | County panel joiner with auto-drop for unmatched |
| **Ishaan** | `scripts/run_pipeline.py` | End-to-end orchestration script |
| **Ishaan** | Stubs for Gowtam | `build_capacity_table.py`, `build_need_table.py` with schemas, TODOs, and mock fallbacks |
| **Gowtam** | `src/build_capacity_table.py` | NGO + F9 aggregation to county-level capacity metrics |
| **Gowtam** | `src/build_need_table.py` | DAC + Poverty + NCCS aggregation to county-level need metrics |

---

## Proposed Changes

### Project Configuration

#### [NEW] [requirements.txt](file:///Users/ishaanbhardwaj/Desktop/CS%206375/NORP-Food-Assistance-Need-Capacity-Gap-Explorer/requirements.txt)
```
pandas>=2.0
numpy>=1.24
matplotlib>=3.7
scipy>=1.10
```
> `scipy` is used for the z-score based gap score (see `join_logic.py`). The LLM
> client is intentionally **not** added yet — the agentic correlation layer is CP3 scope.

#### [MODIFY] [README.md](file:///Users/ishaanbhardwaj/Desktop/CS%206375/NORP-Food-Assistance-Need-Capacity-Gap-Explorer/README.md)
- Add project description, data dictionary, setup instructions, pipeline execution guide.
- Include explicit "For Gowtam" section with step-by-step instructions.
- **Document the NGO sample (Factual axis):** state that `NGOs_with_categories_1MILLION_rows.csv.gz`
  is a **1,048,575-row sample** of the **3,420,024-row** Metabase table verified in Checkpoint 1.
  Reconcile category counts (sample `Food, Agriculture and Nutrition` = **10,507** vs full-table
  K* = 40,080) and frame all county aggregates as sample-based. The CP2 report should carry the
  same disclaimer so the repo numbers don't appear to contradict the CP1 report.

#### [MODIFY] [.gitignore](file:///Users/ishaanbhardwaj/Desktop/CS%206375/NORP-Food-Assistance-Need-Capacity-Gap-Explorer/.gitignore)
- Add `__pycache__/`, `*.pyc`, `.venv/`.
- **Do NOT gitignore `data/output/`.** The grader feedback explicitly asks for code *and* data
  artifacts committed to `main` as self-contained Supporting Evidence. Commit a generated
  `profiler_log.json` and `joined_county_panel.csv` so the pipeline's output is visible in the repo.
  (Ignore only transient files inside it if any, not the deliverable artifacts.)

---

### Core Pipeline (Ishaan's Modules)

#### [NEW] [src/__init__.py](file:///Users/ishaanbhardwaj/Desktop/CS%206375/NORP-Food-Assistance-Need-Capacity-Gap-Explorer/src/__init__.py)

#### [NEW] [src/load_data.py](file:///Users/ishaanbhardwaj/Desktop/CS%206375/NORP-Food-Assistance-Need-Capacity-Gap-Explorer/src/load_data.py)
- `DataLoader` class with methods to load each of the 6 raw files.
- Automatic `.gz` decompression for the NGOs file via pandas.
- `sample_mode` parameter (`nrows=10000`) for fast development iterations.
- Standardizes column names to `snake_case` on load. **This normalization is the single source of truth**: all downstream modules (profiler, crosswalk, table builders) reference the post-normalization names (e.g. `F9 01 Rev Tot Cy` → `f9_01_rev_tot_cy`, `Dac Status` → `dac_status`, `County Fips` → `county_fips`). The stub TODOs below use the raw display names for readability, but Gowtam should read the actual normalized columns the loader produces.

#### [NEW] [src/profile_data.py](file:///Users/ishaanbhardwaj/Desktop/CS%206375/NORP-Food-Assistance-Need-Capacity-Gap-Explorer/src/profile_data.py)

The **automated profiler** — the centerpiece deliverable. Implements:

1. **Schema Report**: For each loaded DataFrame, log shape, dtypes, column names.
2. **Null Audit**: Per-column null percentages, with special attention to join keys (`ein`, `county_fips`, `county`, `state`).
3. **Join Key Validation**: Before any join, measure the match rate between the two sides. Log the match rate.
4. **Quality Gate**: Classify each table and each join with a verdict:
   - `✅ USABLE` — ≥ 80% completeness/match rate
   - `⚠️ WARNING` — 50%–80%
   - `❌ DROP` — < 50%
5. **Auto-Drop with Logging**: When a join produces unmatched rows (e.g., FL, CT counties), log the unmatched records to `data/output/profiler_log.json` and auto-exclude them from the final panel. **No manual patches.**
6. **Self-Verification Gate** (CP2 deliverable per CP1 report): after profiling all tables/joins, emit a single overall verdict `proceed | proceed_with_warning | stop` that `run_pipeline.py` checks **before** running downstream steps. Rule-based for CP2:
   - any **need-side** table/join below the `❌ DROP` threshold → `stop` (pipeline halts);
   - **capacity-side** states auto-dropped (FL/CT) → `proceed_with_warning` (logged, pipeline continues);
   - otherwise → `proceed`.
   Write the verdict + reasons into `profiler_log.json`.

> [!NOTE]
> The CP1 report names three agent action points: (1) this profiler triage + gate, (2) an LLM correlation-candidate generator, and (3) an LLM-assisted self-verification gate. CP2 implements **(1)** as a rule-based gate so the agentic architecture and hook are demonstrably present now. The **LLM** elements of (2) and (3) remain **CP3 scope** — this is why no LLM client is in `requirements.txt` yet.

#### [NEW] [src/crosswalk.py](file:///Users/ishaanbhardwaj/Desktop/CS%206375/NORP-Food-Assistance-Need-Capacity-Gap-Explorer/src/crosswalk.py)

Automated, rules-based county name normalization:

1. **Suffix Stripping**: Remove `County`, `Parish`, `Borough`, `Census Area`, `Municipality`, `City and Borough` suffixes. (Stripping `Planning Region` is harmless but does **not** rescue CT: the lookup holds CT's *old county names*, while the NGOs use *planning-region names* — different strings entirely, so CT auto-drops regardless. Do not expect a CT match from suffix rules.)
2. **Case Folding**: Lowercase both sides before matching.
3. **FIPS Zero-Padding**: Ensure all FIPS codes are zero-padded to 5 digits (the lookup and all need-side tables already store them as 5-digit zero-padded strings, e.g. `01001`).
4. **`resolve_county_to_fips(ngo_df, lookup_df)`**: Returns the NGO DataFrame enriched with a `county_fips` column. Rows that don't match are flagged (not dropped here — that's the profiler's job).

> [!NOTE]
> This module does **not** hardcode FL or CT mappings. It applies general normalization rules. If FL counties are missing from the lookup entirely, the profiler detects this, logs it, and auto-drops those rows. This is the correct behavior per the grading feedback.

#### [NEW] [src/join_logic.py](file:///Users/ishaanbhardwaj/Desktop/CS%206375/NORP-Food-Assistance-Need-Capacity-Gap-Explorer/src/join_logic.py)

`PanelBuilder` class that:

1. Takes the capacity table and need table (both keyed on `county_fips`).
2. Performs an **inner join** on `county_fips`.
3. Logs summary: how many counties matched, how many were left-only or right-only.
4. **Computes a basic gap score** (`score_panel()` step) after the join:
   - `need_score` = mean of per-county z-scores (`scipy.stats.zscore`) of available need indicators: `poverty_rate`, `avg_food_desert_pct`, `avg_housing_burden`.
   - `capacity_score` = mean z-score of available capacity indicators, normalized per capita: `ngo_count` per 10k `population`, `total_revenue` per capita, `total_assets` per capita.
   - `gap_score = need_score − capacity_score` (higher = need outpaces capacity; a triage signal, not a causal claim, per the CP1 report).
5. Saves the final joined panel (with `need_score`, `capacity_score`, `gap_score`) to `data/output/joined_county_panel.csv`.
6. Outputs basic descriptive statistics (mean, median, std of each metric) and the top-gap counties.

---

### Table Builders (Gowtam's Stubs)

#### [NEW] [src/build_capacity_table.py](file:///Users/ishaanbhardwaj/Desktop/CS%206375/NORP-Food-Assistance-Need-Capacity-Gap-Explorer/src/build_capacity_table.py)

Fully documented stub with:

```python
def build_capacity_table(ngos_df, f9_df, crosswalk_fn):
    """
    Build county-level nonprofit capacity table.
    
    Steps (TODO for Gowtam):
    1. Use crosswalk_fn to resolve ngos_df counties to FIPS codes.
    2. Left-join ngos_df to f9_df on EIN (zero-padded to 9 digits).
    3. Group by county_fips and compute:
       - ngo_count: number of nonprofits
       - food_ngo_count: number with Category == 'Food, Agriculture and Nutrition'
       - total_revenue: sum of F9 01 Rev Tot Cy
       - total_assets: sum of F9 01 Nafb Tot Eoy
    4. Return DataFrame with schema: [county_fips, ngo_count, food_ngo_count, total_revenue, total_assets]
    """
    # MOCK FALLBACK (for Ishaan to test pipeline end-to-end)
    ...
```

**Expected output schema**: `county_fips`, `ngo_count`, `food_ngo_count`, `total_revenue`, `total_assets`

#### [NEW] [src/build_need_table.py](file:///Users/ishaanbhardwaj/Desktop/CS%206375/NORP-Food-Assistance-Need-Capacity-Gap-Explorer/src/build_need_table.py)

Fully documented stub with:

```python
def build_need_table(dac_df, poverty_df, nccs_econ_df):
    """
    Build county-level community need table.
    
    Steps (TODO for Gowtam):
    1. Aggregate dac_df from census-tract level to county level:
       - Group by county_fips
       - population: sum of Population
       - avg_food_desert_pct: population-weighted mean of Food Desert Pct
       - avg_housing_burden: population-weighted mean of Avg Housing Burden
       - dac_tract_pct: fraction of tracts with Dac Status == 'true'  # NOTE: string 'true'/'false', not a boolean
       - avg_dac_score: population-weighted mean of Dac Score
    2. Left-join poverty_df on FIPS (zero-padded to 5).
    3. Left-join nccs_econ_df on FIPS (zero-padded to 5).
    4. Return DataFrame with schema below.
    """
    # MOCK FALLBACK (for Ishaan to test pipeline end-to-end)
    ...
```

**Expected output schema**: `county_fips`, `population`, `avg_food_desert_pct`, `avg_housing_burden`, `dac_tract_pct`, `avg_dac_score`, `poverty_rate`, `med_household_income`, `unemployment`

---

### Orchestration Script

#### [NEW] [scripts/run_pipeline.py](file:///Users/ishaanbhardwaj/Desktop/CS%206375/NORP-Food-Assistance-Need-Capacity-Gap-Explorer/scripts/run_pipeline.py)

Master execution script. Workflow:

```
1. Load all raw data  (load_data.py)
2. Profile each table  (profile_data.py)  → logs to profiler_log.json, emits gate verdict
3. CHECK GATE  → if verdict == "stop", halt the pipeline and exit non-zero;
                 if "proceed_with_warning", log and continue; if "proceed", continue
4. Build capacity table  (build_capacity_table.py)  → uses mock if Gowtam hasn't finished
5. Build need table  (build_need_table.py)  → uses mock if Gowtam hasn't finished
6. Join capacity + need + score  (join_logic.py)  → inner join on county_fips, add gap_score
7. Save output  → data/output/joined_county_panel.csv  (committed as evidence, not gitignored)
```

CLI flags:
- `--sample` : Load only 10K rows per file for fast testing.
- `--mock` : Use mock table builders (for Ishaan to test before Gowtam finishes).
- `--verbose` : Print detailed profiler output to stdout.

---

## Final Repository Structure

```
NORP-Food-Assistance-Need-Capacity-Gap-Explorer/
├── README.md
├── requirements.txt
├── .gitignore
├── CS6365_Checkpoint1_Report.pdf
├── data/
│   ├── raw/
│   │   ├── NGOs_with_categories_1MILLION_rows.csv.gz
│   │   ├── F9_P01_T00_SUMMARY_2022.csv
│   │   ├── disadvantaged_communities.csv
│   │   ├── county_fips_lookup.csv
│   │   ├── Poverty_Rates_2023.csv
│   │   └── nccs_crosswalk_economic.csv
│   └── output/                      # committed as Supporting Evidence (NOT gitignored)
│       ├── joined_county_panel.csv  # final panel incl. need/capacity/gap scores
│       └── profiler_log.json        # per-table verdicts + overall proceed/stop gate
├── src/
│   ├── __init__.py
│   ├── load_data.py                 # Ishaan
│   ├── profile_data.py              # Ishaan
│   ├── crosswalk.py                 # Ishaan
│   ├── join_logic.py                # Ishaan
│   ├── build_capacity_table.py      # Gowtam (stub by Ishaan)
│   └── build_need_table.py          # Gowtam (stub by Ishaan)
└── scripts/
    └── run_pipeline.py              # Ishaan
```

---

## Verification Plan

### Automated Tests
```bash
# Full pipeline with mock tables (tests Ishaan's code end-to-end)
python scripts/run_pipeline.py --mock --verbose

# Fast pipeline with sample data
python scripts/run_pipeline.py --sample --mock --verbose
```

Expected success criteria:
- ✅ All 6 raw files load without errors.
- ✅ Profiler generates `profiler_log.json` with per-table schema, null audit, quality verdicts, **and an overall `proceed | proceed_with_warning | stop` gate verdict**.
- ✅ With FL/CT auto-dropped on the capacity side, the gate returns `proceed_with_warning` (not `stop`) and the pipeline continues.
- ✅ Profiler correctly auto-flags FL counties as unmatched (logged, not manually patched).
- ✅ Crosswalk suffix stripping achieves ≥ 95% NGO row match rate.
- ✅ `joined_county_panel.csv` is generated with correct schema (incl. `need_score`, `capacity_score`, `gap_score`) and ≥ ~2,900 counties.

### Manual Verification
- Review `profiler_log.json` to confirm FL/CT are properly logged as quality warnings and the overall gate verdict is present.
- Confirm the committed `data/output/` artifacts (panel + profiler log) are on `main` as self-contained Supporting Evidence.
- Spot-check the top-gap counties in the panel for face validity (high-need/low-capacity counties).
- Have Gowtam review his stub files and confirm the schemas and TODO instructions are clear.
- **Contribution visibility (two-person team):** ensure Gowtam authors and commits his `build_capacity_table.py` / `build_need_table.py` work to `main` under his own name, so `git log` shows both members contributing (the CP1 feedback stressed committing all artifacts to `main`).
