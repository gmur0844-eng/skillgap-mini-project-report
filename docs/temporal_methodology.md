# Temporal Methodology: Historical Trends, Curriculum Versioning & Drift

This phase turns dated evidence into time-aware GOLD metrics. As in
`docs/analytics_methodology.md`, every number is one of: **OBSERVED DATA**,
**CALCULATED METRIC**, **DESCRIPTIVE CLASSIFICATION**, or **INTERPRETATION**
(this document's prose). Keep them distinct when reading results.

> **Status in release candidate `0534d6e1d06a617f` (2026-10-10).**
>
> The knowledge engine applies these rules per posting population (`industry_v2/temporal_populations.json`).
>
> | Population | Eligible postings | Period |
> |---|---|---|
> | `CURRENT_JOB_DATASET_2026_09` (the supplied export) | 100 | one weekly period, 2026-W39 |
> | `EMPLOYER_JOB_BOARDS_IN` (11 employer job boards) | 398 | one weekly period, 2026-W40 |
>
> A trend needs at least two periods with at least 30 eligible postings each. Both populations have
> `trend_status = INSUFFICIENT_DATA`, so **no industry trend is established or reported**.
>
> Curriculum drift (CBIT R22 → R22A) is computed at concept and course level (`concept_drift.jsonl`,
> `exports/course_drift.csv`). The "REAL-DATA TEMPORAL ANALYSIS PENDING" note under *Limitations* describes the early
> SQLAlchemy phase and is superseded by this status.

## Date precedence

`JobPosting.posted_date` is populated from the source dataset's own date
column (e.g. Naukri's `postdate`) during ingestion — **never** from
`JobPosting.ingested_at` or any other ingestion timestamp. Every temporal
function in this phase (`bucket_date`, `compute_historical_skill_demand`,
`run_historical_industry_demand`) reads only `posted_date`. A posting with no
usable source date has `posted_date = NULL` and is excluded from every
period bucket — it is never assigned to "now" or to any other fallback date.

For curricula, `CurriculumVersion.effective_period` is a free-text field
populated from whatever academic-year/effective-date information the source
document states (or left `NULL` if the document doesn't say). Ingestion date
is never substituted for this either.

## Temporal granularity

`bucket_date(dt, granularity)` (`app/analytics/temporal.py`) supports
`"month"`, `"quarter"`, `"year"`, is pure (no DB, no current-date dependency)
and deterministic:

| Date | month | quarter | year |
|---|---|---|---|
| 2026-01-15 | `2026-01` | `2026-Q1` | `2026` |
| 2026-02-15 | `2026-02` | `2026-Q1` | `2026` |

`period_bounds(bucket_label, granularity)` is the exact inverse, returning
`(period_start, period_end)` datetimes — used to populate
`SkillDemand.period_start`/`period_end` so the precise date range behind any
bucket label is always reconstructable, including correct year-boundary
handling (`2026-Q4` → Oct 1–Dec 31; `2026-12` → Dec 1–Dec 31).

## Missing-date handling

`compute_historical_skill_demand` explicitly partitions the eligible
population into `dated_posting_ids` and `undated_posting_ids` — the counts
are always reported (`compute_temporal_industry_quality_metrics`), never
silently dropped. A mention on an undated posting cannot contribute to any
period's demand calculation (there is no bucket to put it in), but the
posting itself is still counted in `undated_postings`.

## Historical industry demand

Same core formula as the non-temporal case (`docs/analytics_methodology.md`),
applied **per period**:
```
demand_percentage(period) = distinct dated postings mentioning the skill in that period
                             / eligible dated postings in that period * 100
```
The denominator is **per-period**, not global — a skill's June demand is
measured against June's eligible postings only. As before, repeated mentions
of a skill within one posting count that posting once.

## Trend calculation — three different numbers, not one

Given a skill's demand in two periods (e.g. 5% → 8%):

| Function | Result for 5%→8% | Meaning |
|---|---|---|
| `compute_absolute_change` / `compute_percentage_point_change` | **+3** | The raw difference in percentage points. |
| `compute_relative_change` | **+60%** | `(8-5)/5 * 100` — how much bigger the new value is, relative to the old one. |

These are **never** interchangeable, and the code never confuses them.
`compute_relative_change` returns `None` (not infinity, not a guessed
number) when the previous value is exactly `0` — relative change from a zero
base is mathematically undefined.

## Trend sufficiency — never force a direction from weak evidence

`assess_trend_sufficiency()` requires ALL of (thresholds in
`app/core/config.py`, never hardcoded):
- at least `min_periods_for_trend` periods observed (default 2),
- every period's eligible population ≥ `min_eligible_postings_per_period` (default 30),
- the skill's total posting count across periods ≥ `min_skill_postings_for_trend` (default 5).

If any rule fails, `compute_trend_label()` returns `"INSUFFICIENT_DATA"` —
**never** `TRENDING_UP`/`TRENDING_DOWN` from inadequate evidence. These
default thresholds are illustrative starting points, not derived from any
real dataset; revisit them once real data volume is known.

`run_historical_industry_demand()` writes each skill's trend (relative
change + label) onto its **most recent period's** `SkillDemand` row, reusing
the existing `growth_rate`/`trend_label` columns rather than a new model. A
skill observed in only one period gets `trend_label = "INSUFFICIENT_DATA"`
with no `growth_rate` (there is nothing to compare against).

## Curriculum version identity — a real bug found and fixed

**Before this phase**, `ingest_curriculum_document()` created a **new**
`CurriculumVersion` row on every single ingestion run, even when
re-ingesting the identical (programme, version_label). This broke the
premise that "two ingestion runs of the same curriculum ≠ two curriculum
versions." **Fixed**: it now looks up an existing `CurriculumVersion` by
`(programme_id, version_label)` and reuses it (updating `document_id`/
`source_id` to point at the latest ingestion) instead of duplicating it.

**Known limitation, not fixed this phase**: re-ingesting the *same* version
does not yet deduplicate the `Course`/`Module`/`CurriculumTopic` rows created
under it — full course-level re-ingestion idempotency for curricula is a
separate concern from version identity and remains open.

## Curriculum drift (skill-level)

`compare_curriculum_versions(previous_coverage, current_coverage)` — both
inputs are `{skill_id: percentage_or_None}`, with `None` meaning "no
curriculum evidence at all for this version" (**already resolved** by the
caller via `resolve_evidence_value`, using each version's own course count
as the population — the same None-vs-zero discipline as
`docs/analytics_methodology.md`). Six purely **DESCRIPTIVE** statuses:

| Status | Meaning |
|---|---|
| `SKILL_ADDED` | No evidence in the previous version, real coverage in the current one. |
| `SKILL_REMOVED` | Real coverage in the previous version, no evidence in the current one. |
| `COVERAGE_INCREASED` / `COVERAGE_DECREASED` | Both versions have real (possibly zero) coverage; it changed. |
| `UNCHANGED` | Both versions have identical real coverage. |
| `INSUFFICIENT_DATA` | Neither version has any evidence for this skill. |

**A decrease is never labeled "outdated"** — that would be an interpretation,
not a description, and this project does not make that claim.

## Course-level drift

`compare_courses(prev_codes, curr_codes)` reports courses added/removed/
unchanged by `course_code`. `compare_course_skills(prev, curr)` reports,
**only for courses present in both versions**, which skills were added or
removed within that specific course — a course that was itself added or
removed is reported once by `compare_courses`, not double-counted here.
**Scope decision**: course-level drift is written only to the GOLD artifact
(`data/gold/curriculum_drift_courses/<run_id>/records.jsonl`), not a
dedicated DB table — `CurriculumSkillDrift` already captures the
programme-level skill drift that matters for querying/filtering via the API;
adding a third near-duplicate table for course-level detail was judged
unnecessary over-modeling given current data volume. This can be
revisited if course-level drift needs to be independently queryable later.

## Temporal industry ↔ curriculum comparison

`run_temporal_industry_curriculum_comparison(session, historical_demand_run_id, time_bucket, curriculum_version_id)`
combines **one specific industry period** with **one specific curriculum
version**, reusing the exact same `resolve_evidence_value` +
`classify_demand_coverage` logic as the non-temporal alignment (never a new
composite score — demand and coverage stay separate metrics). **Scope
decision**: also GOLD-artifact-only, not a dedicated DB table (see the
function's docstring) — `SkillAlignment`/`AlignmentResult` are scoped to
"overall" comparisons; a third table for every possible (period, version)
pair was judged unnecessary until real data shows this is actually queried
often enough to warrant it.

## No causation claims

This phase can observe "industry demand increased between period A and B"
and "curriculum coverage changed between version X and Y" as two independent
facts. It never claims one caused the other, and no code path combines them
into a causal or predictive statement.

## Snapshot / re-run semantics

Identical to `docs/analytics_methodology.md`: every successful call to
`run_historical_industry_demand`, `run_curriculum_version_comparison`, or
`run_temporal_industry_curriculum_comparison` creates a new `AnalysisRun`
and fresh GOLD rows/artifacts. Nothing is overwritten. The "current" answer
always resolves through `select_latest_successful_run()` (unit-tested,
including a three-run scenario — run 1 succeeds, run 2 succeeds, run 3 fails
— that confirms the failed run never shadows run 2).

## GOLD artifacts

```
data/gold/industry_skill_trends/<run_id>/records.jsonl
data/gold/curriculum_drift/<run_id>/records.jsonl
data/gold/curriculum_drift_courses/<run_id>/records.jsonl
data/gold/temporal_skill_comparison/<run_id>/records.jsonl
```

## Limitations

- Trend-sufficiency thresholds are illustrative defaults, not derived from real data volume.
- Course-level and temporal-comparison results are artifact-only, not yet independently queryable via a dedicated table (see scope decisions above).
- Curriculum re-ingestion of the *same* version does not yet deduplicate Course/Module/Topic rows (documented limitation carried over, not newly introduced).
- **REAL-DATA TEMPORAL ANALYSIS PENDING** — every function above is unit-tested with small fixtures only; none has run against real dated job postings or multiple real curriculum versions. `data/raw/{jobs,esco,onet,curricula}/`, `data/bronze/`, `data/silver/`, `data/gold/` all contain zero real files as of this writing.

## Test commands

```bash
cd backend
python3 -c "
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'tests')
mods = ['test_temporal','test_historical_demand','test_trend_analysis','test_curriculum_drift','test_run_selection']
for m in mods:
    mod = __import__(m)
    for n in dir(mod):
        if n.startswith('test_'): getattr(mod, n)()
print('ok')
"
```

## Real-data execution commands (once data is available)

```bash
python3 -c "
from app.db.session import SessionLocal
from app.analytics.run_temporal_analysis import (
    run_historical_industry_demand, run_curriculum_version_comparison, run_temporal_industry_curriculum_comparison,
)
session = SessionLocal()
demand_result = run_historical_industry_demand(session, granularity='month')
print(demand_result)
# once you have two real CurriculumVersion ids for the same programme:
# drift_result = run_curriculum_version_comparison(session, previous_version_id=1, current_version_id=2)
# comparison_result = run_temporal_industry_curriculum_comparison(session, demand_result['analysis_run_id'], '2026-01', curriculum_version_id=2)
"
```
