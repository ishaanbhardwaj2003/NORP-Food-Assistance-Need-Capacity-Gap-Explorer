# Review & Revision of Checkpoint 2 Implementation Plan

## Context

The user asked for a review of `implementation_plan.md` against the Checkpoint 1
grading feedback (`feedback.txt`) and the Checkpoint 1 report
(`CS6365_Checkpoint1_Report.pdf`), to surface anything off, missing, or
insufficient before execution.

The existing plan's **central move is correct**: replacing manual FL/CT FIPS
patching with automated normalization + auto-drop is exactly what the grader
demanded. Verified against the real committed data:
- NGO file = 1,048,575 rows; exact food label = `'Food, Agriculture and Nutrition'` (10,507 rows in sample).
- FL is genuinely absent from `county_fips_lookup` (0 rows); CT is present only under old county names, so its planning-region NGOs cannot match → auto-drop is the right behavior.
- All need-side tables use clean, zero-padded 5-digit FIPS.

The review found gaps that this revision addresses. Three were resolved by the user:
1. **Agentic layer** → add the rule-based proceed/stop verdict gate in CP2; defer LLM to CP3.
2. **NGO data** → keep the 1M file but document it as a sample of the 3.42M Metabase table.
3. **Gap score** → add a basic `gap_score` to the CP2 panel.

## Revisions to `implementation_plan.md`

### 1. Restore the self-verification gate (Profiler is a CP2 deliverable)
In `src/profile_data.py`, beyond per-table ✅/⚠️/❌ verdicts, add an overall
**rule-based gate** returning `proceed | proceed_with_warning | stop` that
`scripts/run_pipeline.py` checks before running downstream steps. Rules:
- any required join below the DROP threshold on a *need-side* table → `stop`;
- capacity-side states auto-dropped (FL/CT) → `proceed_with_warning` (logged);
- otherwise `proceed`.
Write the verdict + reasons into `profiler_log.json`. Note in the plan that the
LLM correlation agent and LLM-assisted gate remain CP3 scope, but the
architecture/hook is present now.

### 2. Add a basic gap score to the panel
In `src/join_logic.py` (or a small `score_panel()` step), after the inner join,
compute:
- `need_score` = mean z-score of available need indicators (poverty_rate, avg_food_desert_pct, avg_housing_burden);
- `capacity_score` = mean z-score of available capacity indicators (ngo_count per 10k population, total_revenue per capita, total_assets per capita);
- `gap_score = need_score − capacity_score`.
Append these columns to `joined_county_panel.csv`. Add `scipy>=1.10` to `requirements.txt`.

### 3. Document the NGO sample (Factual axis)
In `README.md` and the CP2 report, state explicitly that
`NGOs_with_categories_1MILLION_rows.csv.gz` is a **1,048,575-row sample** of the
3,420,024-row Metabase table, and reconcile category counts (sample food =
10,507 vs full K* = 40,080). Frame all county aggregates as sample-based.

### 4. Commit output artifacts as Supporting Evidence
Do **not** gitignore everything under `data/output/`. Commit a sample
`profiler_log.json` and the generated `joined_county_panel.csv` (or a `reports/`
copy) so the grader sees the pipeline actually ran — feedback explicitly asks
for code *and* data artifacts on `main`, self-contained evidence. Keep
`__pycache__/`, `.venv/`, `*.pyc` ignored.

### 5. Fix implementation nits in the stubs
- `src/build_need_table.py`: `Dac Status` values are strings `'true'`/`'false'`, not booleans — compare to `'true'`.
- Remove the implication that stripping `Planning Region` resolves CT; it does not (CT auto-drops regardless). Keep suffix stripping for the genuine `County`/`Parish`/`Borough`/`Census Area`/`Municipality` cases.
- Ensure the loader's `snake_case` standardization is the single source of truth, and the stub schemas reference the post-normalization column names consistently (e.g. `f9 01 rev tot cy` → `rev_tot_cy`).

### 6. Contribution visibility (two-person team)
Adjust the verification section: it currently asserts *all* commits are by
Ishaan. Gowtam's `build_capacity_table.py` / `build_need_table.py` commits
should land on `main` too, so both members' contributions are visible (feedback
stressed committing to `main`).

## Critical files
- `implementation_plan.md` — apply revisions 1–6 (this is the immediate deliverable).
- Downstream, when executing CP2: `src/profile_data.py`, `src/join_logic.py`, `src/build_need_table.py`, `scripts/run_pipeline.py`, `requirements.txt`, `README.md`, `.gitignore`.

## Verification
- Re-read the revised `implementation_plan.md` and confirm: verdict gate present, gap-score step present, NGO-sample documented, output artifacts committed (not ignored), nits fixed.
- Sanity-check the data claims already verified hold (FL absent, food label exact, FIPS zero-padded) — confirmed during review.
- When CP2 is later implemented: `python scripts/run_pipeline.py --mock --verbose` produces `profiler_log.json` (with a proceed/stop verdict) and `joined_county_panel.csv` (with `gap_score`, ≥ ~2,900 counties).
