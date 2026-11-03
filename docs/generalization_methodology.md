# Programme-Agnostic Generalization

## Objective

Generalize from an implicitly AI&DS-oriented implementation into a
programme-agnostic platform supporting any engineering discipline (CSE,
AI&DS, IT, ECE, EEE, VLSI, Embedded Systems, Mechanical, Mechatronics,
Automobile, Manufacturing, Civil, Chemical, Biotechnology, and future
programmes) **without code changes** -- the system must be data/configuration
driven.

## Audit findings

A repo-wide grep for `AI&DS`, `CSE`, `ECE`, `EEE`, `Mechanical`, `Civil`,
`VLSI`, `Embedded`, `Chemical`, `Biotechnology`, `Automobile` and a search
for conditional branching on discipline/programme identity in
`app/analytics/` and `app/pipelines/` found **zero forbidden hardcoded
business logic**. Every occurrence is a docstring example, CLI help text, or
explicitly-labeled seed data (`scripts/seed/seed_disciplines.py`). The
system was already built generically -- curriculum ingestion always took
institution/programme names as caller-supplied parameters, never assumed
values.

## Domain model

```
Institution
  |
Department (new) --- Discipline (new, data-driven reference table)
  |
Programme (extended: department_id, programme_code, specialization,
           aliases_json, is_active)
  |
CurriculumVersion (unchanged)
  |
Course (unchanged)
  |
Module / CurriculumTopic / CourseLearningOutcome (unchanged)
  |
Skill (unchanged, ESCO-normalized)
```

`Discipline` is a **reference table**, not an enum: new rows can be
inserted at any time with zero code changes. The illustrative starting set
("Computing & Data", "Electronics & Electrical", "Mechanical &
Manufacturing", "Civil & Infrastructure", "Chemical & Process", "Life
Sciences", "Other Engineering") lives in `scripts/seed/seed_disciplines.py`
as data, never referenced by name anywhere in `app/analytics/`.

## Industry-side generalization

- `IndustryDomain`: same reference-table pattern as `Discipline`.
- `JobDiscipline`: many-to-many junction (a job can be relevant to multiple
  disciplines, per spec) with `method`/`confidence` columns for a FUTURE
  real classifier -- **not populated with fabricated classifications** by
  this phase. Querying it today correctly returns zero relationships,
  which is honest, not a bug.
- `JobPosting.industry_domain_id`: single-valued FK, also unpopulated.

## Curriculum ingestion generalization

`ingest_curriculum_document()` gained `department_name`, `discipline_name`,
`programme_code`, `degree_level`, `academic_year` -- all optional and purely
additive; omitting them reproduces the exact prior behavior byte-for-byte.
One real gap was found and fixed in passing: `CurriculumVersion.effective_period`
(academic year) had a column but was **never wired to any ingestion
parameter** before this phase.

## Programme-scoped analytics

The pure math (`compute_curriculum_coverage`, `compute_skill_demand`) was
**already population-agnostic** -- both accept arbitrary `eligible_*_ids`
sets. Only the orchestration layer always queried "everything." Fixed with
purely additive, backward-compatible parameters:

- `run_curriculum_coverage_analysis(session, programme_id=None)` -- `None` (default) preserves the exact prior "overall" behavior; a real `programme_id` filters `Course` by `programme_id` and tags the resulting `CurriculumSkillCoverage` rows with `level="programme", entity_id=programme_id`.
- `run_industry_demand_analysis(session, discipline_id=None)` -- same pattern, filtering via the new `JobDiscipline` join.

Formulas are **mathematically unchanged**:
```
demand_percentage = distinct postings mentioning skill / eligible postings * 100
coverage_percentage = distinct courses mentioning skill / eligible courses * 100
jaccard = |industry intersect curriculum| / |industry union curriculum|
```
TF-IDF and Jaccard remain separate, non-composite metrics, unchanged.

## A real bug found and fixed by this generalization

Once programme/discipline-scoped runs can coexist with global ones for the
**same** `dataset_name`, the existing "pick the latest successful run"
selection would silently pick whichever run is chronologically newest
**regardless of scope** -- a narrowly-scoped discipline run could silently
become "the" answer for a global API request, or vice versa. **Fixed**:
both `_latest_run` (API layer) and `_find_latest_run_id` (gap
classification) now accept an explicit `population_scope` filter, applied
before latest-run selection:
- `/analytics/industry-demand` and `/analytics/curriculum-coverage` default to `population_scope="global"` (preserving exact prior behavior) and accept an optional `discipline_id`/`programme_id` to request a scoped run instead.
- `/analytics/curriculum-drift` now **requires** `programme_id` (previously it had none at all, and drift runs are *always* programme-scoped -- the endpoint was silently unsafe the moment more than one programme's drift existed; making the parameter required is a deliberate breaking fix, not a casual change, given no real client exists yet).
- `run_skill_gap_classification`'s default demand/coverage/trend lookups now explicitly request `population_scope="global"`.

## Curriculum drift -- already correctly isolated

No change was needed here: an earlier hardening phase already made
`run_curriculum_version_comparison` derive its `population_scope` from the
actual `CurriculumVersion.programme_id` and raise a hard `ValueError` if the
two versions being compared belong to different programmes. This phase's
audit confirmed that protection is real and still in place.

## Peer-benchmarking / recommendation readiness

Not implemented this phase (per spec). The domain model now carries enough
identity (`programme_code`, `discipline_id` via `department_id`) to support
a future equivalent-programme benchmarking feature without further schema
changes. The recommendation engine remains entirely programme-independent --
its rule logic never references a discipline/programme name (verified: the
same repo-wide grep found zero such references in
`app/analytics/recommendation_engine.py`).

## Isolation guarantees (tested)

`backend/tests/test_programme_isolation.py` -- 7 tests, all passing --
prove, using the same pure functions the orchestration relies on:
- AI&DS and ECE course evidence cannot leak into each other's coverage results.
- Mechanical and Civil results stay isolated even across different institutions.
- The same skill (e.g. Python) can appear independently in two unrelated programmes without their counts merging unless explicitly combined.
- Two versions of the same programme compare cleanly without a third, unrelated programme's data appearing.
- An empty scope yields an empty result, never a silent fallback to a broader population.

## Data quality

No synthetic analytical results were introduced. `data/raw/{jobs,esco,onet,curricula}/`,
`data/bronze/`, `data/silver/`, `data/gold/` all remain empty (verified by
directory scan) -- **REAL DATA EXECUTION: PENDING**, unchanged from every
prior phase.

## Known limitations

- Historical trend/temporal analytics were NOT given discipline-scoping this phase -- they remain global-only. This is a scoped, honest gap: adding it follows the exact same pattern already established for demand/coverage and can be done in a follow-up pass.
- `SkillGap`/`Recommendation` do not yet carry an explicit `programme_id` column -- traceability today goes through `source_demand_run_id`/`source_coverage_run_id` -> `AnalysisRun.population_scope`, sufficient but one join deeper than a direct column would be.
- API endpoints for `industry-trends`, `temporal-comparison`, `skill-gaps`, and `recommendations` were not updated with scope-safety filters this phase (only `industry-demand`, `curriculum-coverage`, and `curriculum-drift` were) -- the same latent-bug pattern could reappear there once discipline-scoped historical/gap runs actually exist. Flagged as a follow-up, not fixed here.
