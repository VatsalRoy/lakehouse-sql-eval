# Hypotheses (pre-registered)

**Written:** November 12, 2026, before generating any data or running any evaluation.
**Why write this first:** Predictions recorded up front keep the analysis honest. If a result surprises me, I report the surprise rather than quietly reframing the question.

---

## Research question

On the same 60 business questions and the same LLM, how much does grounding text-to-SQL in a Unity Catalog **metric view** improve **execution accuracy** (the query returns the correct number), compared with:

- **A: raw schema.** The model sees table and column names only.
- **B: schema plus comments.** The model also sees Unity Catalog table and column descriptions.
- **C: metric view.** The model sees governed measure definitions, dimensions, and synonyms.

I also want to know where it still fails.

## Setup assumptions

- 60 questions, 15 in each category: **lookup**, **aggregation**, **business definition**, **time/fiscal**.
- Same model, same temperature, 3 seeds per question per condition.
- Primary metric: execution match against hand-written gold SQL, with 0.5% numeric tolerance.
- The dataset contains deliberate traps: about 8% refunds, a fiscal year starting Feb 1, multiple currencies, soft-deleted customers, and test accounts.

---

## H1: The gain is concentrated where business definitions matter

**Claim:** Metric-view grounding (C) improves execution accuracy most on *business definition* and *time/fiscal* questions. It barely helps on simple *lookups*.

**Reasoning:** A lookup such as "How many products are in Electronics?" has one obvious SQL answer. A question such as "What was net revenue?" or "What was the refund rate in fiscal Q2?" forces the model to guess at refunds, test accounts, and fiscal calendars. The metric view removes that guesswork.

**Predicted execution accuracy:**

| Category | A: raw | B: + comments | C: metric view |
|---|---|---|---|
| Lookup | ~85% | ~90% | ~90% |
| Aggregation | ~65% | ~75% | ~85% |
| Business definition | ~30% | ~50% | ~85% |
| Time / fiscal | ~25% | ~45% | ~80% |
| **Overall** | **~50%** | **~65%** | **~85%** |

**Supported if:** the C − A gap on business-definition questions is at least 2× the C − A gap on lookups, and the 95% bootstrap confidence intervals don't overlap.

**Refuted if:** gains are roughly equal across categories, or C doesn't beat B on business-definition questions. A failure of C to beat B would mean good column comments are enough on their own.

---

## H2: Raw-schema failures are mostly silent, so LLM judges are overconfident

**Claim:** When condition A gets an answer wrong, the query usually *runs successfully and returns a plausible number*. It rarely errors out. Because the SQL looks reasonable, an LLM judge will rate many of these wrong queries as correct.

**Reasoning:** Modern LLMs rarely write SQL with syntax errors. Their mistakes are semantic: they forget to subtract refunds, use calendar quarters instead of fiscal ones, or leave in test accounts. These mistakes produce valid SQL with wrong numbers.

**Predictions:**
- At least 70% of condition-A failures are "silent wrong" (the query ran and returned rows, but the number is wrong). The rest are errors or empty results.
- The LLM judge agrees with execution match on only about 70% of all generations.
- The judge's false-positive rate on silent-wrong queries (calling a wrong query correct) is at least 40%.
- Condition C has the lowest silent-wrong rate. Its failures lean toward visible errors instead, such as `MEASURE()` syntax problems.

**Supported if:** silent wrong accounts for at least 60% of A's failures, and the judge's agreement with execution is meaningfully below its agreement on clearly erroring queries.

**Refuted if:** most failures are runtime errors, or the judge tracks execution match closely (agreement of 90% or higher).

---

## H3: Synonyms and agent metadata fix most remaining wording failures

**Claim:** Removing synonyms and agent metadata from the metric view (ablation **C−**) noticeably lowers accuracy on questions that use informal wording ("sales", "income", "how much did we make"). It barely affects questions that use the exact measure name.

**Predictions:**
- C− is 5 to 15 percentage points below full C overall.
- Most of that drop falls on questions I tag as using a *synonym* instead of the canonical measure name.
- Full C resolves at least half of the wording failures that C− makes.

**Supported if:** the C − C− gap on synonym-worded questions is clearly larger than on canonically worded ones.

**Refuted if:** C and C− perform about the same. That would mean modern LLMs already map "sales" to `net_revenue` from the measure's name and description alone.

---

## H4 (secondary): The semantic layer is also cheaper

**Claim:** Condition C uses fewer prompt tokens per question than condition B, because a compact list of measures and dimensions replaces long table and column descriptions.

**Prediction:** C uses about 30–50% fewer input tokens than B, and about the same as or slightly more than A.

**Refuted if:** C's prompt is the largest. If so, I'll report the accuracy-per-token trade-off honestly.

---

## Failure taxonomy (coding scheme, fixed in advance)

Every failed generation gets exactly one primary label:

1. **Wrong definition.** Example: gross instead of net, test accounts included.
2. **Wrong time grain or calendar.** Example: calendar quarter used instead of fiscal quarter.
3. **Wrong filter.** Example: missing region or status filter, soft-deleted rows included.
4. **Wrong join.** Example: fan-out double-counting, wrong key.
5. **Wrong aggregation.** Example: AVG instead of SUM, ratio of sums vs sum of ratios.
6. **Syntax or runtime error.**
7. **Empty result.**

**Expected distribution in condition A:** wrong definition and wrong time grain together account for more than half of failures.

---

## Threats to validity (things that could make these results misleading)

- **I wrote both the questions and the metric view.** Without meaning to, I might phrase questions so they match my measure names, which would inflate C. To reduce this, I'll write all 60 questions *before* finalizing the metric-view synonyms and tag each question's wording type.
- **Synthetic data.** Real enterprise schemas are messier than mine, so absolute accuracy numbers won't transfer. The *relative* gaps between conditions are the finding.
- **One model.** The results may not hold for stronger or weaker LLMs. If quota allows, I'll repeat the run with a second endpoint.
- **Small sample.** 15 questions per category gives wide confidence intervals. I'll always report CIs and avoid over-claiming small differences.
- **Gold SQL bugs.** I validate gold SQL against the metric view. Any mismatch is investigated and documented, not silently fixed.

---

## Results log (fill in after evaluation)

| Hypothesis | Predicted | Observed | Verdict |
|---|---|---|---|
| H1 | C − A largest on business/fiscal | | |
| H2 | ≥70% of A failures silent; judge agreement ~70% | | |
| H3 | C − C− = 5–15 pts, concentrated on synonyms | | |
| H4 | C uses 30–50% fewer tokens than B | | |