# Deterministic Evidence-Based Curriculum Recommendations

## Philosophy

A recommendation is a **traceable curriculum action derived from structured
evidence**, never generic advice. No LLM is used. No recommendation exists
"because a skill is popular" — every recommendation must pass through
gap classification first (`docs/gap_classification_methodology.md`), and
weak/insufficient evidence never produces a strong action.

## Action types (controlled vocabulary)

`ADD_NEW_SUBJECT`, `ADD_ELECTIVE`, `ADD_MODULE`, `UPDATE_EXISTING_TOPIC`,
`EXPAND_EXISTING_TOPIC`, `REVIEW_EXISTING_COURSE` — defined in
`app/analytics/recommendation_engine.py::VALID_ACTIONS`. Never invented
dynamically.

## Three recommendation states

| State | Meaning |
|---|---|
| `RECOMMENDATION_SUPPORTED` | A real action is warranted by the evidence. |
| `INSUFFICIENT_EVIDENCE` | The underlying gap classification itself is `INSUFFICIENT_EVIDENCE` — no action is proposed. |
| `NO_ACTION_INDICATED` | Evidence is sufficient (skill is `COVERED`) and no trend/drift signal indicates further action is needed. |

## Rule logic, by gap classification

- **INSUFFICIENT_EVIDENCE** -> `INSUFFICIENT_EVIDENCE`, no action, no target.
- **COVERED** + `INCREASING_DEMAND` trend + a known course teaching it -> `REVIEW_EXISTING_COURSE` (course-level). Otherwise -> `NO_ACTION_INDICATED`.
- **PARTIAL** -> if real course evidence exists, `EXPAND_EXISTING_TOPIC` (course-level); otherwise `ADD_MODULE` (programme-level, since no specific course can be honestly named).
- **MISSING** -> `ADD_NEW_SUBJECT` if `high_demand` is true, else `ADD_ELECTIVE`. Always programme-level, **never** course-level -- a `MISSING` classification means curriculum coverage is genuinely zero, so by construction there is no course to target.
- Multi-skill grouping (real `SkillRelationship` data only) overrides the single-skill action to `ADD_MODULE`.

Trend (`demand_trend_signal`) and drift (`drift_status`) are always appended
as **reasons**, never used to change the action type -- `MISSING +
TRENDING_DOWN` is still `MISSING`/`ADD_NEW_SUBJECT` or `ADD_ELECTIVE`;
`COVERAGE_DECREASED` is never read by the rule engine's branching logic at
all.

## None vs. zero -- reused unchanged

`generate_recommendation()` receives an already-resolved gap-classification
result. It never re-derives None-vs-zero itself.

## Course targeting

Only real `ExtractedSkill` evidence (via the gap-classification phase's
`courses_with_evidence` presence-only lookup) can name a target course.
`target_level = PROGRAMME` whenever no such evidence exists.

## Multi-skill grouping

`group_related_skills()` performs connected-components grouping over a
caller-supplied `{skill_id: set(related_skill_id)}` lookup built from real
`SkillRelationship` rows. **Honest current limitation**: no ingestion
pipeline in this project populates `SkillRelationship` yet, so this lookup
is empty today and every recommendation is single-skill (documented, not a
bug -- verified by a dedicated test).

## Provenance

Every `Recommendation` row stores `source_gap_classification_run_id` plus
the `source_demand_run_id`/`source_coverage_run_id` carried over from the
`SkillGap` row it was built from.

## Idempotency

`UniqueConstraint(analysis_run_id, skill_id)` on `Recommendation` prevents
one generation run from ever producing two rows for the same skill.
Versioned-snapshot semantics apply across runs (see `docs/analytics_methodology.md`).

## No numeric score

`Recommendation.priority` exists as a column (backward-compatible with an
old unused scaffold) but is **never populated** this phase.

## GOLD artifact

```
data/gold/curriculum_recommendations/<run_id>/records.jsonl
```

## API

`GET /api/v1/analytics/recommendations` -- filters: `action_type`,
`recommendation_state`, `skill_id`, `course_id`.

## Limitations

- Course targeting reuses the gap-classification phase's presence-only course lookup, not a full course-level industry-demand model.
- Multi-skill grouping is real, tested logic operating on empty data today.
- **REAL DATA EXECUTION: PENDING.** All 33 recommendation-engine tests use small fixtures only.

## Example

```
Skill: "Docker (software)"
Gap classification: MISSING, high_demand=True, trend_label=TRENDING_UP
-> recommendation_state: RECOMMENDATION_SUPPORTED
-> action_type: ADD_NEW_SUBJECT
-> target_level: PROGRAMME
-> reasons: [
    "Industry demand is 42.0% (real, non-zero) but measured curriculum coverage is genuinely zero.",
    "Industry demand meets the configured high-demand threshold, supporting a standalone new subject.",
    "Demand trend is INCREASING_DEMAND, strengthening the case for this recommendation."
  ]
```
