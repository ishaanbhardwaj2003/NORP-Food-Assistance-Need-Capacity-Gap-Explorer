# Checkpoint 3 Revision Notes — what changed and why

Working-tree summary for the team (Ishaan & Gowtam). **Nothing here is committed
yet** — see "Committing" at the bottom. Generated 2026-07-15 from the rebuilt
outputs; every number below is re-checkable via `python scripts/verify_outputs.py`.

## Why this revision exists

1. The CP2 TA feedback asked us to **commit the validation itself**
   (correlation-direction checks, crosswalk-collision checks) instead of
   describing it.
2. The TA benchmark branch (`ai-suggestions/cp3`, commit `dbaf847`) has a
   permutation-based verification step; we had only a sign check.
3. Our own audit found data-validity problems that changed conclusions once
   fixed (duplicate 990 filings summed, missing financials fabricated as zeros,
   a gap score that compared food need to *general* capacity, an NGO "sample"
   that is actually an ordered truncated extract).

## What was added

| Area | Delivered | Where |
|---|---|---|
| Committed verification | 13 machine-checked assertions + `validation_report.json` (incl. all 115 omitted counties by state: 67 FL, 8 CT, 34 VA, 2 AK, 1 each HI/ND/NM/TX) | `scripts/verify_outputs.py` |
| Statistical critic | BH FDR across all 28 tests + fixed-seed **state-stratified** permutation test (2,000 shuffles) per proposed pair + documented `supported/weak_direction/unsupported` ruling (effect floor \|ρ\| ≥ 0.10, a team choice) | `src/statistical_critic.py` |
| F9 correctness | One filing per EIN (latest tax year, revenue tie-break); mixed 2019/2020/2022 years and 539 duplicate-EIN groups no longer summed | `src/build_capacity_table.py` |
| Missing ≠ zero | 803 counties with no matched filer now get NaN financials (was 0); genuine zeros survive; `matched_filer_count`/`filer_coverage_rate` added; NGO→990 join (3.59%) now profiled | builder + `src/profile_data.py` |
| Food-specific gap | `food_ngo_per_10k`, `food_capacity_score`, `food_gap_score`; original `gap_score` kept as the general gap | `src/join_logic.py` |
| Score completeness | `need_component_count` / `capacity_component_count` (99 counties lack poverty; ~800 lack financials) | `src/join_logic.py` |
| LLM safeguards | candidate dedup + count enforcement, constant-column guard, schema-constrained structured output (`--live`), cache hash-bound to schema+gate with stale-replay rejection | `src/correlation_agent.py` |
| Tests | 34 pytest tests, no API key, no large files | `tests/` |
| Evidence isolation | `--output-dir` on both scripts; smoke runs can't overwrite committed outputs | `scripts/` |
| Docs | README (ordered-truncated-extract framing, 990/990EZ/990PF), CHANGELOG, CLAUDE.md, requirements (+pytest) | repo root |
| Report | Brand-new `CS6365_Checkpoint3_Report.docx` from the course template, with a TA-feedback-response table and the corrected findings | repo root |

## Before → after (committed evidence)

| Metric | Frozen CP3 (2026-07-14) | Rebuilt (2026-07-15) |
|---|---|---|
| Panel counties | 3,027 | 3,027 (unchanged) |
| Gap range | −3.74 … +4.42 | −4.38 … +5.03 |
| Gap median / std | +0.10 / 1.10 | +0.11 / 1.17 |
| Zero-revenue counties | 815 (fabricated) | 0 fabricated (806 NaN = unobserved) |
| Top-10 gap overlap | — | 4/10 kept; #1–3 unchanged (Lee AR, Zapata TX, Zavala TX) |
| LLM signs matched | 7/7 ("all confirmed") | **6/7**, graded **3 supported / 2 weak / 2 unsupported** |

Per-pair Spearman ρ (old → new) and critic verdict:

| Pair | ρ old → new | Verdict |
|---|---|---|
| unemployment ~ ngo_per_10k | −0.310 → −0.310 | supported |
| med_household_income ~ revenue_per_capita | +0.331 → +0.248 | supported |
| poverty_rate ~ revenue_per_capita | −0.285 → −0.241 | supported |
| poverty_rate ~ ngo_per_10k | −0.230 → −0.230 | **weak** (permutation p = 1.0 → between-state artifact) |
| avg_food_desert_pct ~ food_ngo_per_10k | −0.092 → −0.092 | weak (below \|ρ\| ≥ 0.10 floor) |
| avg_housing_burden ~ assets_per_capita | +0.117 → −0.041 | **unsupported** (sign flipped after missing-vs-zero fix) |
| dac_tract_pct ~ food_ngo_per_10k | −0.020 → −0.020 | unsupported (not significant after BH) |

**Does "capacity tracks wealth, not need" survive?** Weakened but yes: the
income~revenue correlation drops from +0.33 to +0.25 once fabricated zeros are
removed, and it passes all three critic layers (BH q ≈ 1e−31, stratified
permutation p = 0.0005, above the effect floor). The poverty~NGO-density pair,
by contrast, is exposed as a pure between-state artifact — a claim the old
sign-check would have endorsed.

**General vs food gap: they are not interchangeable.** Rank ρ = 0.61 and only
2/10 top-10 overlap (recomputed in `findings_summary.md` each run). This
vindicates the audit's point that the old `gap_score` was answering a
different question than the project title asks — food-sector triage should
read `food_gap_score`.

## Verified state (all green, 2026-07-15)

```
python -m py_compile src/*.py scripts/*.py   # clean
python -m pytest -q                          # 34 passed
python scripts/run_pipeline.py --verbose     # 3,027 counties, no FL/CT
python scripts/run_analysis.py               # 28 pairs, critic columns filled
python scripts/verify_outputs.py             # 13/13 checks passed
# smoke isolation: --sample --mock --output-dir <scratch> leaves data/output untouched
```

## Deliberately NOT done (deferred with reasons)

- Streamlit / choropleth / partial-correlation models — final-report material,
  not CP3 blockers (choropleth + state-fixed-effects sensitivity are listed as
  final-report suggestions in the new DOCX).
- VA independent-city crosswalk fix — kept report-only per team decision; the
  34 lost VA counties are enumerated in `validation_report.json`.
- Full 3.42M-row NGO rerun — blocked on export availability; the input is now
  honestly framed and machine-verified as an ordered truncated extract.

## Committing (when ready — nothing has been committed)

Per repo convention: human authors only, never AI. Suggested:

```bash
git -c user.name="Ishaan Bhardwaj" -c user.email="ishaanbhardwaj2003@gmail.com" \
  add -A && \
git -c user.name="Ishaan Bhardwaj" -c user.email="ishaanbhardwaj2003@gmail.com" \
  commit -m "CP3 revision: committed verification, statistical critic, F9/gap-score validity fixes

Responds to CP2 TA feedback and the ai-suggestions/cp3 benchmark: adds
scripts/verify_outputs.py (13 checks) + validation_report.json, a BH+
state-stratified-permutation critic grading every LLM hypothesis, one-filing-
per-EIN 990 handling, NaN-vs-zero financials with coverage columns, a food-
specific gap score, cache integrity hashes, 34 tests, and --output-dir
isolation. Corrected findings: 6/7 signs match; 3 supported / 2 weak / 2
unsupported.

Co-authored-by: Gowtam Kommi <gkommi@users.noreply.github.com>"
```
