# Final Presentation Narration Script

Target: about 13 minutes total (12 to 15 is the allowed range). Word counts
per slide assume a comfortable 130 words per minute; the seconds are a
guide, not a stopwatch. Speakers alternate so both members clearly take part
(course requirement).

## Recording logistics (read once, then delete from your head)

1. Open `presentation/NORP_Final_Presentation.pptx` full-screen.
2. Record with Zoom (share screen, record to computer) or QuickTime screen
   recording while on a call together; both voices must appear.
3. One take is fine; small stumbles are fine. If a slide goes long, trim on
   the verification slide, never on slides 12 and 13.
4. Export mp4, upload to YouTube as UNLISTED (or Google Drive with
   link-sharing on).
5. Paste the link at the end of the report docx AND in
   `FINAL_REPORT_DRAFT.md`, commit, push.

---

## Slide 1 - Title (Ishaan, ~30s)

Hi, we're Group 4. I'm Ishaan Bhardwaj, and together with Gowtam Kommi we
built the NORP Food Assistance Need-Capacity Gap Explorer. This is our final
presentation for CS 6365, and we want to show you a pipeline that doesn't
just query nonprofit data, it explores it, checks its own work, and tells
you honestly what it can and cannot conclude.

## Slide 2 - The question (Ishaan, ~55s)

Past NORP semesters built chatbots that turn natural language into SQL, and
the reviews kept saying the same thing: the projects drifted into benchmark
tuning and never surfaced actual sociological insight. So this semester the
course asked for something different: an agentic exploration layer over real
data. Our concrete question is simple to say and hard to answer: in which US
counties does food-related community need outpace the nonprofit capacity
that exists to address it? We answer it at the county level, across about
three thousand counties, and one rule governs everything: Python computes
every statistic; the language model only proposes hypotheses and writes
framing. No number in this project depends on a model being right.

## Slide 3 - The data (Gowtam, ~60s)

We join six raw tables. On the capacity side, the full nonprofit registry:
three point four two million organizations with their county and category,
which we obtained in full this week, joined to about a hundred thirty
thousand IRS 990 filings for revenue and assets. On the need side, seventy
two thousand census tracts with food-desert shares, housing burden, and
disadvantage scores, plus county poverty, income, and unemployment. Three
hazards shaped the whole design. First, the capacity side identifies counties by text
name while the need side uses numeric FIPS codes, and those names are an
unreliable join key: spellings and suffixes vary, and the same name recurs
across different states. Second, only about
four percent of nonprofits have a matched filing, so financial data is
sparse and has to be treated as missing, never as zero. And third, until
this week we only had a truncated extract of the nonprofit table, cut at the
Excel row limit. Keep that third one in mind, because it becomes the story
of this checkpoint.

## Slide 4 - Architecture (Ishaan, ~55s)

The pipeline is not a fixed script. It loads and profiles the data, then a
quality gate decides on its own whether to proceed, proceed with a warning,
or stop. The capacity and need tables get joined into a scored county panel.
Then a language model reads only the schema, never raw rows, and proposes
which need-versus-capacity pairs are worth testing. Python computes the
exhaustive correlation grid regardless, all twenty-eight pairs, so the model
can prioritize but can never hide or invent a statistic. A deterministic
critic then re-tests every proposal, and this checkpoint adds a fixed-effects
estimator and county maps on top. Finally, a committed verification script
re-derives every number we report. Seventeen machine checks, and all
seventeen pass.

## Slide 5 - The gate acting (Gowtam, ~50s)

Here's the gate doing its job on the full run. Verdict: proceed with
warning, at a ninety-three percent match rate. Florida and Connecticut drop
out entirely, almost two hundred thirty one thousand rows, ninety-nine point
three percent of everything dropped, because the course's county lookup
simply cannot map their counties. Checkpoint 1 feedback told us not to
hand-patch geography, and we deleted our planned manual fix in response. That
rule survived all the way to the final run: everything the pipeline drops is
logged with a reason, and everything it keeps got there through a general
rule, not a hardcoded exception.

## Slide 6 - The gap score (Gowtam, ~55s)

The gap score is deliberately explainable: the average z-score of a county's
need indicators minus the average z-score of its capacity indicators.
Positive means need outpaces capacity. Two design choices matter. First,
capacity metrics pass through a signed-log transform, because we learned at
Checkpoint 2 that a single large nonprofit can otherwise dominate an entire
county's score. Second, we publish two gaps: the general gap against all
nonprofit capacity, and a food-specific gap against food-sector density,
because they disagree more than you'd expect. And when a county has no
matched filing, its financials stay missing. We never fabricate a zero. The
distribution you see is nearly symmetric, so the counties in the tail are
genuine outliers, not artifacts of skew.

## Slide 7 - The answer (Ishaan, ~50s)

This is the answer to our research question: a triage list. The counties
where food-related need most outpaces nonprofit capacity are Zapata and
Zavala on the Texas border, Martin County in Appalachian Kentucky, Lee and
St. Francis in the Arkansas Delta, Bullock in the Alabama Black Belt. These
are exactly the places a domain expert would expect to see, which matters, because
face validity is the first check a triage signal has to pass. One newcomer:
Manassas Park, Virginia, a small independent city our new crosswalk
recovered. Small denominators can amplify a city like that, so we report it
with that caveat attached rather than filtering it away.

## Slide 8 - The map (Ishaan, ~40s)

This is the same result, expressed geographically. Red is need outpacing capacity: the Delta, the
Texas border, the Black Belt, Appalachia. Blue is the Northeast and upper
Midwest, where capacity outpaces need. The grey states are Florida and
Connecticut, absent by an honest rule rather than silently missing. This is
a true county-polygon map rendered with matplotlib alone from committed
public-domain geometry, and a sidecar file machine-checks that every one of
the three thousand sixty-six counties is either drawn or accounted for.

## Slide 9 - LLM proposes, Python disposes (Gowtam, ~40s)

The language model proposed seven hypotheses from the schema, things like
wealthier counties host better-funded nonprofits. Python tested all
twenty-eight need-by-capacity pairs exhaustively, so the seven proposals sit
inside a complete grid and nothing is cherry-picked. The strongest raw
signals: nonprofit density falls as unemployment and disadvantage rise, and
filer revenue per capita tracks median income. But raw correlation is where
the analysis starts, not where it ends.

## Slide 10 - The critic (Gowtam, ~55s)

Every proposal faces a deterministic critic with three layers: false
discovery control across the whole grid, a permutation test that shuffles
capacity within each state two thousand times with a fixed seed, and a
minimum effect size we committed to in advance. The permutation layer is the
interesting one: a correlation that only exists because states differ
survives the shuffle, and therefore fails the test. Poverty versus nonprofit
density is exactly that: a q-value of ten to the minus thirty-six, and a
permutation p of one point zero. Statistically significant, and still an
artifact. The final tally on the full data: four supported, two
weak-direction, one unsupported. And treating that null as a finding is,
we'd argue, the most defensible thing this pipeline does.

## Slide 11 - Fixed effects (Ishaan, ~55s)

New this checkpoint, we gave our headline finding its hardest test. If
capacity tracks wealth, that could just be composition: rich states versus
poor states. So we absorb state fixed effects entirely and re-estimate the
slope from within-state variation only, with cluster-robust standard errors.
The result: within states, signed-log filer revenue per capita rises zero
point one three per ten thousand dollars of median income, with p around
four times ten to the minus nine, across two thousand nine hundred
thirty-nine counties in forty-nine states. The pooled slope barely
attenuates. One more detail we're proud of: on the raw dollar scale the same
regression finds nothing, p of point six one, which is precisely why the
signed-log transform exists. The relationship is real, and it's within
states, not between them.

## Slide 12 - Auditing the benchmark (Ishaan, ~65s)

At Checkpoint 3 we audited our own outputs and corrected two validity
errors. This checkpoint we applied the same standard to the TA's AI-generated
benchmark branch. It shipped an exact-first Virginia crosswalk, and on the
real data it recovers zero of the five thousand two hundred ninety-one
dropped Virginia rows. Its tests pass because its fixtures only use names
that already exist verbatim in the lookup. The actual failure is that the
lookup stores Alexandria bare while the nonprofit table says Alexandria
City. Our rebuilt resolver keeps the benchmark's genuinely good ideas, with
credit: exact-first matching so Fairfax City never collapses into Fairfax
County. Then it adds the missing general rules: a city-suffix fallback and
an encoding repair that fixed corrupted bytes we found in the course's own
lookup file. Result: all thirty-four Virginia independent cities plus Dona
Ana, New Mexico enter the panel, taking it from three thousand twenty-seven
to three thousand sixty-six counties, every recovery machine-verified.

## Slide 13 - The data gap, closed (Gowtam, ~60s)

Every review since Checkpoint 2 flagged the same limitation: the analysis
ran on a truncated extract. This week we obtained the full table, and
instead of quietly swapping it in, we measured what the truncation had been
doing. The extract held thirty-one percent of rows but only twenty-six
percent of food nonprofits and sixteen percent of Alaska's, because the
Excel cut sliced an EIN-sorted file, and EIN prefixes encode geography. On
the full data, two food-sector correlations reverse sign, and one hypothesis
the critic had rejected, food nonprofits concentrating in disadvantaged
counties, flips to supported. The gap rankings correlate at zero point seven
three with the old panel, so the headline geography was robust, but the
sector-level conclusions genuinely changed. That's the difference between
disclosing a bias and measuring it.

## Slide 14 - Close (both, ~45s)

**Gowtam:** Everything we've shown you re-derives from the repository with
no API key: seventeen committed verification checks, sixty-six tests, and a
findings summary whose every number comes from committed artifacts.
**Ishaan:** The honest accounting is the product: Florida and Connecticut's
absence, sparse filings, unverifiable upstream labels, all enumerated, never
hidden. Next steps would be an authoritative Florida mapping, a second
filing year for temporal comparison, and publishing the triage list. The
repository link is on screen. Thank you.

---

Total: roughly 1,750 words, about 13.5 minutes at a natural pace.
