# Evidence-Based Curriculum Gap Classification

## Purpose

Turns already-computed industry demand + curriculum coverage (+ optionally
historical trend and curriculum drift) evidence into one of four transparent,
descriptive classifications per canonical skill. This is a **classification
layer**, not a recommendation engine — it names a state and explains why,
and stops there.

## Terminology

- **OBSERVED DATA**: a raw fact (e.g. "12 postings mention Python").
- **CALCULATED METRIC**: a deterministic function of observed data (e.g. `demand_percentage`).
- **DESCRIPTIVE CLASSIFICATION**: a label derived from calculated metrics via transparent rules (`MISSING`, `PARTIAL`, `COVERED`, `INSUFFICIENT_EVIDENCE`, and separately `trend_label`, `drift_status`).
- **INTERPRETATION**: this document's prose — never the API's output.

## The four classifications

Computed by `app/analytics/gap_classification.py::classify_skill_gap()`
(pure, deterministic, no DB):

| Classification | Condition |
|---|---|
| `MISSING` | Industry demand is real and **non-zero**; curriculum coverage is **genuinely zero**. |
| `PARTIAL` | Curriculum coverage is real but **below** `partial_coverage_threshold` (default 40%). |
| `COVERED` | Curriculum coverage **meets/exceeds** the threshold, **OR** industry demand is genuinely zero. |
| `INSUFFICIENT_EVIDENCE` | Either side's population/evidence was unavailable (`None`). |

**Why "zero industry demand" resolves to COVERED, not MISSING:** per the
project's explicit principle, *"a skill absent from the curriculum is not
automatically a meaningful gap unless there is sufficient industry
evidence."* If a real population of postings existed and genuinely none of
them mentioned the skill, there is no unmet industry need — so the curriculum
not teaching it isn't a gap worth flagging, regardless of its own coverage
number. This is intentional, not an oversight.

## None vs. zero — reused, not reinvented

Exactly the same discipline as `docs/analytics_methodology.md`:
`resolve_evidence_value()` (already built for skill-set alignment) decides,
per skill, whether an absent `SkillDemand`/`CurriculumSkillCoverage` row
means "population existed, skill genuinely unmentioned" (→ `0.0`, a real
measurement) or "no population at all this run" (→ `None`, missing
evidence) — using each side's population size, itself read from
`AnalysisRun.record_counts_json`. `classify_skill_gap()` never performs a
`value or 0.0` substitution; a `None` on either side always yields
`INSUFFICIENT_EVIDENCE`.

## Thresholds — reused, not reinvented

Both thresholds already existed in `app/core/config.py` from the project's
earliest scaffold, unused until this phase:

| Setting | Default | Applies to |
|---|---|---|
| `high_demand_threshold` | `0.15` (15%) | Flags `high_demand = True` when industry demand ≥ this — same threshold already used for demand/coverage classification in the non-gap alignment phase. |
| `partial_coverage_threshold` | `0.4` (40%) | The PARTIAL/COVERED boundary — below it, coverage is judged inadequate relative to the population; at/above it, adequate. |

No new threshold was introduced for this phase. Both are configurable via
`.env` and every `SkillGap` row stores the exact values used
(`thresholds_used_json`), so a later config change never makes a past
result ambiguous.

## Trend and drift are separate evidence dimensions — never folded in

A skill's `trend_label` (`TRENDING_UP`/`TRENDING_DOWN`/`STABLE`/
`INSUFFICIENT_DATA`, from the latest period of the most recent
`industry_skill_trends` run) and `drift_status` (from the most recent
`curriculum_drift` run, if one exists for the relevant curriculum versions)
are attached to every `SkillGap` row **alongside** the classification, never
merged into it. All of these are valid, independently meaningful
combinations:

```
MISSING  + TRENDING_UP     MISSING  + INSUFFICIENT_DATA
PARTIAL  + TRENDING_UP     COVERED  + TRENDING_DOWN
COVERED  + COVERAGE_DECREASED   <-- still COVERED, never "OUTDATED"
```

**`COVERAGE_DECREASED` is never reinterpreted as "outdated."** The
classification logic has no branch that reads `drift_status` at all — it is
purely a passthrough field for the reader's own judgment.

## High-demand / trend signal flags

`high_demand` (bool) and `demand_trend_signal` (`INCREASING_DEMAND` /
`DECREASING_DEMAND` / `STABLE_DEMAND` / `INSUFFICIENT_TREND_DATA`) are
descriptive flags derived trivially from already-computed values — not
persisted as independent facts, not new analytical claims, just readable
relabelings of `industry_demand`/`trend_label` for API consumers.

## No numeric gap score

The project explicitly forbids inventing a score to rank these states.
`SkillGap.gap_score` exists as a column (backward-compatible with an older
unused scaffold) but is **left `NULL`** this phase — no code path populates
it. If a validated scoring methodology is ever wanted, it must be designed
and justified separately, not backed into this phase.

## Course-level scope — documented limitation, not fabrication

Industry demand in this project is programme/dataset-level; there is no
per-course industry population to classify against. So course-level output
is intentionally lighter-weight: for each classified skill, `SkillGap`
artifacts include `courses_with_evidence` — the list of course codes where
`ExtractedSkill` evidence for that skill actually exists (via course title,
topic, or learning outcome). This answers *"which course, if any, currently
touches this skill"* honestly, without pretending course-level industry
demand exists.

## Programme-level aggregation — counts only, no composite score

`aggregate_gap_counts()` produces transparent counts (`missing_count`,
`partial_count`, `covered_count`, `insufficient_evidence_count`,
`high_demand_missing_count`, `increasing_demand_partial_count`, etc.) — every
number is a direct filter over the underlying skill-level records, never an
opaque weighted score.

## Explainability

Every `SkillGap` row carries `reasons_json` — a plain-English list explaining
exactly why that classification was reached (e.g. *"Industry demand is 42.0%
(real, non-zero) but measured curriculum coverage is genuinely zero."*) — plus
full provenance: `source_demand_run_id`, `source_coverage_run_id`,
`source_trend_run_id`, `source_drift_run_id`, all pointing at the exact
`AnalysisRun` rows the classification was built from.

## GOLD artifact

```
data/gold/skill_gap_classification/<run_id>/records.jsonl
```

## API

`GET /api/v1/analytics/skill-gaps` — filters: `classification`,
`high_demand`, `skill_id`. Returns an honest `pending` state if no
`skill_gap_classification` run has ever succeeded. Never returns a
fabricated/hardcoded result.

## Limitations

- Trend/drift integration uses whatever the *latest successful* run of each
  type is — if that run doesn't correspond to the same programme/population
  as the demand/coverage runs being classified, the combination may be
  loosely aligned. This matters more once multiple programmes/institutions
  are loaded; document/verify alignment before trusting cross-referenced
  trend/drift on a specific skill.
- Course-level evidence is presence-only (a list of course codes), not a
  full course-level classification (see "Course-level scope" above).
- `partial_coverage_threshold`'s single global cutoff (40%) is a starting
  default, not derived from real data — revisit once real coverage
  distributions are known.
- **REAL DATA EXECUTION: PENDING.** Every function is unit-tested with small
  fixtures only; nothing has run against a real database or real
  ESCO/Naukri/curriculum data.

## Example

```
Skill: "Docker (software)"
industry_demand_percentage: 42.0   (real: 420 of 1000 eligible postings)
curriculum_coverage_percentage: 0.0  (real: 0 of 40 eligible courses)
classification: MISSING
evidence_state: BOTH_MEASURED
high_demand: True
trend_label: TRENDING_UP
demand_trend_signal: INCREASING_DEMAND
drift_status: null
reasons: [
  "Industry demand is 42.0% (real, non-zero) but measured curriculum coverage is genuinely zero.",
  "Industry demand (42.0%) meets or exceeds the high-demand threshold (15%).",
  "Demand trend signal: INCREASING_DEMAND (trend_label=TRENDING_UP)."
]
```

## Curriculum scope (2026-10-11)

A gap is a claim about a whole programme. Before a gap is treated as actionable, the pipeline checks whether the
target curriculum covers the whole programme (`backend/app/knowledge_engine/curriculum_scope.py`):

- **Expected span.** The largest last semester reached by at least `curriculum_scope.min_agreeing_documents` (2) other
  curricula in the analysis. They must share the target's discipline (and degree level, when both state one) and have
  semester labels starting at semester 1.
  - Nothing is hard-coded: neither a discipline nor a number of semesters.
  - A single curriculum cannot set the span, and a partial one (an earlier version that stops at semester IV) cannot
    lower it.
- **Status.**
  - `COMPLETE`: the target covers every expected semester.
  - `INCOMPLETE`: some semesters are missing, and they are listed.
  - `UNDETERMINED`: the target has no semester labels, or no span is supported. It changes nothing.
  - `NOT_ASSESSED`: a run made before this check. It is never recomputed.
- **Effect.** In an INCOMPLETE curriculum, every PARTIAL or MISSING gap keeps its classification, coverage level and
  reason, and gains `scope_limited: true` and `review.code = CURRICULUM_SCOPE_INCOMPLETE` (`evidence_status =
  REVIEW_REQUIRED`).
  - It is therefore not a confirmed (`actionable`) gap.
  - Its recommendation is withheld with `CURRICULUM_SCOPE_REVIEW_REQUIRED`.
  - A more specific review, such as a course named after the skill, keeps its own code, and the scope limit is still
    stated.
- **Recorded in.** `run_report.json` (`curriculum_scope`), `intelligence/curriculum_scope.json`, every
  `skill_gaps_v2.jsonl` row (`curriculum_scope`, `scope_limited`, `actionable`), the API envelope
  (`scope.curriculum_scope`) and the overview (`curriculum_scope`, `gap_line.review_required`,
  `gap_line.scope_limited`).
- **In the app.** The overview and skill-gap pages show a warning above every gap figure.

Example: the R26 CSE (AIML) upload covers semesters I–II, and three other curricula in the analysis reach semester
VIII. It keeps its 24 MISSING classifications, all marked for review: 0 confirmed gaps and 24 recommendations withheld.
The R22A release covers I–VIII and is COMPLETE, so its 11 confirmed gaps are unchanged.
