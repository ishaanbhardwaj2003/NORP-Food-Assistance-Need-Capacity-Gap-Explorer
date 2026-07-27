# CS 4365/6365 Final Report Draft

Paste-ready content for the course template. Every number below is read from
the committed artifacts in `data/output/` (regenerate with the Reproduce
commands and the numbers regenerate with them). Fill the video link at the
end after recording.

---

**Group:** 4
**Name(s):** Ishaan Bhardwaj and Gowtam Kommi
**Project Name:** NORP Food Assistance Need-Capacity Gap Explorer

## Context and Related Work

Prior NORP semesters built NL2SQL/RAG chatbots so non-technical researchers
could query nonprofit data, and consistently drifted into SQL-generation
benchmarking instead of surfacing sociological insight. This semester's
direction is an agentic data-exploration layer that cleans real data, verifies
its own work, and computes correlations. Our project applies that to one
concrete question: where does food-related community need outpace nonprofit
capacity to address it?

Checkpoint 1 verified the data plan against the live NORP Metabase.
Checkpoint 2 turned the plan into a working pipeline that loads six raw
tables, profiles and gates them automatically, and joins them into a scored
county panel. Checkpoint 3 added the LLM correlation-candidate agent, a
deterministic statistical critic, committed verification, and an honest
self-audit that corrected two data-validity errors. The final checkpoint
closes the one gap every prior review flagged: the analysis now runs on the
full 3,420,024-row nonprofit table rather than a truncated extract, and adds
the three deliverables we scoped in the CP3 report (a state fixed-effects
estimate, county choropleths, and an automated Virginia crosswalk), each
taken further than the TA benchmark version of the same idea.

## Project Plan (Plan)

Research question: can an agentic workflow identify U.S. counties where
food-related need is high but nonprofit food/human-service capacity is
relatively low? Secondary question: which indicators correlate most strongly
with nonprofit capacity across counties? Unit of analysis: county, joined on
5-digit FIPS. Python computes every statistic; the LLM proposes hypotheses
and writes framing only.

### Where the agent acts

1. Data-quality triage and gate (rule-based, authoritative): the profiler
   classifies every table and join, then issues a single proceed /
   proceed_with_warning / stop verdict the pipeline obeys without manual
   intervention. On the final run it returned proceed_with_warning at a
   93.22% county-name match rate and auto-dropped 231,927 unmatched NGO rows,
   99.3% of them Florida (188,675) and Connecticut (41,739), whose counties
   cannot be mapped in the committed FIPS lookup.
2. Correlation-candidate generation (LLM, advisory): the agent reads only the
   panel schema (never raw rows) and proposes need-vs-capacity pairs with
   expected signs; Python computes the exhaustive 28-pair grid regardless.
3. Gate review (LLM, advisory): a logged second opinion that can never
   override the rule-based verdict.
4. Statistical critic (deterministic): every proposed pair must clear
   Benjamini-Hochberg FDR across all 28 tests, a fixed-seed state-stratified
   permutation test (2,000 within-state shuffles), and a documented
   effect-size floor before it may be called supported.
5. State fixed-effects estimator (deterministic, new): the surviving
   wealth-capacity relationship is re-estimated with all state-level shifts
   absorbed and cluster-robust standard errors at the state level.

### Data

Capacity side: the full NGOs_with_categories table (3,420,024 organizations
with EIN, county, and NTEE category; committed as four gzipped parts because
the single 162 MB export exceeds GitHub's file cap) joined by EIN to 131,587
IRS 990/990EZ/990PF 2022 summary filings, deduplicated to one filing per EIN.
Need side: 72,742 disadvantaged-community census tracts aggregated to county
(food-desert share, housing burden, DAC score), county poverty rates, and
ACS income and unemployment. County geometry for the maps is committed with
provenance. Gap score: need z minus capacity z, with the per-capita capacity
indicators passed through a signed-log transform so financial outliers cannot
dominate; a separate food_gap_score scores food-sector density. Both are
triage signals, not causal claims. Non-goals unchanged: no chatbot, no NL2SQL
benchmarking, no causal claims, no forcing of unreliable joins.

## Project Deliverables

| Deliverable | Description | Technical Stack |
|---|---|---|
| Profiler & Quality Gate | Classifies every table/join and decides proceed / proceed_with_warning / stop on its own | Python, pandas |
| County Capacity & Need Tables | Aggregates the full NGO table + 990 filings, and tract-level need data, to county level | Python, pandas |
| Joined Gap-Score Panel | 3,066-county FIPS join with need/capacity/gap and food-specific scores | Python, scipy |
| Correlation Agent & Critic | LLM proposes pairs; Python computes the exhaustive grid; a deterministic critic grades every proposal | Python, LLM API (offline-replayable cache) |
| State Fixed-Effects Estimate | Wealth-capacity slope with state FE absorbed, cluster-robust SEs, signed-log scale | Python, numpy/scipy |
| County Choropleths & Cartogram | True county-polygon gap maps (general + food) plus a state tile overview, no GIS dependencies | Python, matplotlib |
| Full-Data Integration & Bias Audit | Full 3,420,024-row table committed and loaded; the retired extract's bias measured; conclusion changes itemized | Python, pandas |
| Committed Verification & Tests | 17 machine-checked assertions over every committed claim; 66 offline tests | Python, pytest |

## Project Milestones

| Checkpoint | Milestone | Technical Scope & Deliverables | Work Splitup | Status |
|---|---|---|---|---|
| Checkpoint 1 | Scope project, verify Metabase sources, test county join feasibility | Repo structure, Metabase verification | Both | Complete |
| Checkpoint 2 | Profiler, capacity/need tables, automated crosswalk, scored panel | Ishaan: profiler, join logic, orchestration. Gowtam: table builders, crosswalk | Both | Complete |
| Checkpoint 3 | LLM correlation agent, top-gap figures, findings summary, statistical critic, committed verification | Ishaan: pipeline automation, verification. Gowtam: scoring refinement, correlation agent, summary | Both | Complete |
| Final | Full-data rerun, crosswalk v2 (VA cities), state-FE estimate, choropleths, truncation-bias audit, report + presentation | Ishaan: crosswalk v2, full-data integration, verification, deck. Gowtam: FE analysis, maps, truncation audit, narration | Both | Complete (this report) |

## Current Progress Report (Match)

**The data gap is closed.** Both CP2 and CP3 feedback asked us to rerun on the
full NGOs_with_categories table before the final report. We requested and
received the full export this week, validated it against the two numbers
Checkpoint 1 had verified on Metabase (3,420,024 rows exactly; 40,086 food
organizations vs the ~40,080 verified then), split it into four
GitHub-committable parts with a validation script, and taught the loader to
read the parts transparently while recording which source it used in the
profiler log. The retired extract stays committed, because its bias is now a
measurement rather than a caveat: it covered 30.7% of rows but only 26.2% of
food nonprofits and 16.1% of Alaska's, and on the full data two food-sector
correlations reverse sign, direct evidence the EIN-sorted cut was not random.

**We audited the TA benchmark branch the way CP3 audited our own outputs, and
found its headline fix does not work.** The ai-suggestions/cp4 branch (kept
in our repository for auditability) implements the three deliverables we had
scoped. Running its Virginia crosswalk on the real data recovers zero of the
5,291 dropped VA rows: its exact pass only helps names that exist verbatim in
the lookup, and its test fixtures only exercise those names. The real failure
mode is that the lookup stores most VA independent cities bare (Alexandria)
while NGO rows say Alexandria City. Our rebuilt resolver keeps the
benchmark's good ideas with credit (exact-first matching so Fairfax City
never folds into Fairfax County, plus its collision audit) and adds the
missing general rules: a city-suffix fallback and text folding with a
conservative encoding repair, which also fixed corrupted bytes we discovered
in the course's own lookup file (DoÃ±a Ana). All 34 VA independent cities and
Dona Ana NM enter the panel; no other state's match rate declines; a
dedicated verifier check asserts all of it.

**The three scoped deliverables are integrated, not bolted on.** The
fixed-effects estimator (benchmark core, adopted with credit) runs on the
panel's signed-log scale, writes committed results, appears in the findings
summary, and is re-derived by the verifier. The county choropleths render
from committed public-domain geometry with matplotlib alone, removing the
geopandas dependency and missing geometry file that kept the benchmark at a
state cartogram (which we kept as an overview figure). Everything runs inside
the existing two orchestration scripts.

**Findings on the full data.** The panel grows from 3,027 to 3,066 counties.
The headline geography holds: the counties where food-related need most
outpaces capacity remain the Texas border (Zapata +4.17, Zavala +4.13,
Starr), the Arkansas and Mississippi Delta (Lee, St. Francis), Appalachian
Kentucky (Martin), and the Black Belt (Bullock AL), with recovered Manassas
Park VA entering the top ten, a small-denominator observation we report
rather than filter. The critic now grades the same seven CP3 hypotheses
(re-tested unchanged so verdict changes are attributable to data) as 4
supported / 2 weak-direction / 1 unsupported: dac_tract_pct ~
food_ngo_per_10k strengthens from rho -0.02 (unsupported) to -0.24
(supported), a food-sector signal the truncated extract had buried, while
poverty ~ nonprofit density remains a between-state artifact (permutation
p = 1.0) despite q = 7.7e-36. The wealth-capacity headline survives its
hardest test yet: within states, signed-log filer revenue per capita rises
+0.132 per $10,000 of median household income (cluster-robust p = 4.2e-09,
2,939 counties, 49 states), and the pooled slope (+0.194) attenuates only
modestly under FE absorption. The raw-scale sensitivity fit does not survive
(p = 0.61), confirming that outlier-robust scaling is what makes the
relationship estimable, exactly the lesson CP3's signed-log fix taught.

**Changes to the original plan.** The full export arrived mid-checkpoint, so
the planned interim truncation-bias analysis became a ground-truth
measurement and the full rerun became the committed evidence. Commit
authorship switched to the email registered with GitHub so contributions
attribute correctly. Nothing was dropped.

## Supporting Evidence (Factual)

Team GitHub Repository:
https://github.com/ishaanbhardwaj2003/NORP-Food-Assistance-Need-Capacity-Gap-Explorer
(the TA benchmark branch is preserved as `ai-suggestions/cp4` for side-by-side
audit).

New or reworked code this checkpoint:
- `src/crosswalk.py`: exact-first two-stage resolution, encoding repair,
  collision audit; `tests/test_crosswalk.py` includes the bare-lookup city
  case the benchmark never tested.
- `src/load_data.py` + `scripts/assemble_ngo_parts.py`: multi-part full-table
  loading with recorded provenance and anchored validation.
- `src/fixed_effects.py`: state-FE OLS with CR1 cluster-robust SEs, LSDV
  equivalence tested; wired into `scripts/run_analysis.py`.
- `src/make_maps.py` + `data/reference/`: county choropleths and cartogram
  from committed geometry with provenance notes.
- `scripts/analyze_truncation.py`, `scripts/compare_extract_vs_full.py`,
  `scripts/regen_offline_cache.py`.
- `scripts/verify_outputs.py`: 13 to 17 checks.

Committed evidence (all in `data/output/`): `joined_county_panel.csv` (3,066
counties), `profiler_log.json` (gate verdict + NGO source), 
`correlation_results.csv` (28-pair grid, q-values, permutation p, verdicts),
`fixed_effects_results.json`, `llm_candidates.json` (hash-bound offline
artifact), `truncation_analysis.json`, `full_vs_extract_comparison.json`,
`validation_report.json` (17/17 checks pass), `findings_summary.md`, and 8
figures including both county choropleths and the truncation-bias chart.

Selected verified figures from the final run:
- Gate: proceed_with_warning; NGO-to-FIPS match rate 0.9322 on 3,420,024
  rows; drops are 99.3% FL/CT (lookup limitation, disclosed).
- Panel: 3,068 capacity counties, 3,142 need counties, 3,066 joined; the 76
  need-only counties are 67 FL, 8 CT, 1 AK, enumerated in the validation
  report.
- Critic: 6/7 signs matched; 4 supported / 2 weak-direction / 1 unsupported.
- Fixed effects: +0.132 per $10k (SE 0.018, p 4.2e-09, within-R2 0.016);
  raw-scale sensitivity p 0.61 (correctly not significant).
- Extract vs full: gap rank correlation 0.733 on common counties, 3/10
  top-ten overlap, max correlation shift 0.365, three sign flips, one critic
  verdict upgrade.

Reproduce (offline, no API key):

```
python scripts/run_pipeline.py --verbose
python scripts/run_analysis.py
python scripts/analyze_truncation.py
python scripts/verify_outputs.py        # 17/17
python -m pytest -q                     # 66 passed
```

## Skill Learning Report

- Panel econometrics: implementing within-transform fixed effects and
  cluster-robust (CR1) inference from first principles, verifying against an
  explicit dummy-variable regression, and learning why the FE-vs-pooled
  contrast and the raw-vs-transformed sensitivity are the honest way to
  present a slope.
- Auditing AI-generated code: treating a benchmark implementation as a claim
  to verify, not a patch to merge; the zero-recovery finding came from
  running it on real data and reading its fixtures critically.
- Data forensics at scale: measuring truncation bias against ground truth,
  diagnosing double-encoded text in a provided lookup, and validating a
  3.4M-row delivery against externally verified anchors.
- Geospatial rendering without GIS dependencies: parsing GeoJSON and drawing
  county polygons with matplotlib primitives, with machine-checked county
  accounting instead of visual trust.
- Reproducibility engineering: hash-bound offline LLM artifacts, provenance
  recording, and a verification suite that re-derives every reported number.

## Self-Evaluation

- Plan: 100%
- Match: 100%
- Factual: 100%

Every milestone scoped at CP3 is delivered, the full-data rerun the feedback
asked for twice is committed evidence, every headline number is re-derivable
offline by committed scripts, and the remaining limitations (FL/CT lookup
coverage, sparse filings, unverifiable upstream category labels, two
counties without 2010-vintage geometry) are disclosed and machine-enumerated
rather than hidden.

## Automated Review Feedback

- Project Plan (Plan): The plan held its shape across four checkpoints and
  closed exactly the risk the reviews kept naming; the final scope centers on
  the data-access gap rather than new surface area, as directed.
- Progress Report (Match): The three stated deliverables shipped, integrated
  into the existing pipeline and verifier rather than as side scripts, and
  the benchmark audit extends the CP3 self-audit pattern to AI-suggested
  code.
- Supporting Evidence (Factual): Every claim above maps to a committed
  artifact or a verifier check; the conclusion changes caused by the full
  data are itemized in a committed comparison file rather than narrated.

Actionable Suggestions:
- Obtain an authoritative FL county mapping and a CT planning-region
  crosswalk so the last 75 counties can enter the panel through general
  rules.
- Add a second year of 990 filings to turn the panel into a two-period
  temporal comparison.
- Publish the top-gap triage list with the small-denominator caveat attached
  per county.

## Presentation

Slides: `presentation/NORP_Final_Presentation.pptx` (14 slides; speaker tags
alternate between both members). Narration script with per-slide timings:
`presentation/NARRATION_SCRIPT.md`.

Presentation video: [LINK HERE after upload, YouTube unlisted or Drive]
