# Testing & Data Provenance Guide

## Release-candidate validation (current, 2026-10-10)

Earlier sections of this file describe early phases and are kept as history. The current procedure:

| Layer | Command | Gate |
|---|---|---|
| Backend tests (74 modules) | `cd backend && env -u SEMANTIC_MODE ../.venv/bin/pytest tests -q -rs` | 0 failures and 0 errors; every skip printed with its reason |
| Static Flutter check | `python3 scripts/frontend/static_validate_flutter.py` | screens, routes and const maps |
| Full release candidate | `bash scripts/mac/rc_validation.sh` | every gate below; last line `RC VERDICT: PASS` or `FAIL` |

**`rc_validation.sh` gates:**
- backend tests;
- pipeline exit 0, database publish PASS, semantic mode REPLAY_VERIFIED_RUN, lineage;
- the agents' experimental layers COMPLETE;
- protected release `c066` unchanged;
- the cross-machine reproducibility gate (`scripts/audit/reproducibility_gate.py`);
- database dump, migration-cycle integrity, database integrity;
- release gap QA held=0;
- Flutter analyze, tests and web build;
- readiness READY with data HEALTHY;
- full API validation; the Flutter data layer against the live API; the agents endpoints.

The comparison against the protected release (`compare_c066.json`) is reported separately. It covers different code, so
it is reviewed by hand and is not a gate.

**Semantic mode in tests.** `SEMANTIC_MODE=replay` is set only on the pipeline and agent commands. Tests that depend on
the mode set it themselves (`test_live_cache_isolation.semantic_mode`), so the suite gives the same result whether or not
the parent shell exports it. Container results (2026-10-10): 867 passed, 0 failed, 1 skipped, both with and without
`SEMANTIC_MODE=replay` exported.

**Tests added in the release-candidate fixes:**

| File | What it guards |
|---|---|
| `test_live_cache_isolation.py` | `test_malformed_replay_entry_is_rejected_not_raised`: a replay entry without `cache_file`, `gate_file` or a hash is reported in `replay_rejected`, never a `KeyError` |
| `test_deterministic_ordering.py` (9 tests) | tied TF-IDF weights (every column order); review-queue related-concept order; `concepts.csv` and `recommendations.csv` export order; peer top-k ties; numeric environment in the run report |
| `test_reproducibility_gate.py` (8 tests) | identical runs pass; a label difference passes and is reported; membership, SAME_CONCEPT, out-of-bound, unlisted-file, added-file and identity differences fail; every policy rule is narrow |

**Known skips on the Mac** (reported by `pytest -rs`):
- 3 database tests skip when their PostgreSQL role or database is absent at test time;
- 1 test skips when `node` is not installed.

They are environment-dependent and listed in `artifacts/rc/validation.log`.

This file exists specifically to prevent an easy mistake: confusing a test
that runs against the bundled DEMO/TEST fixture with a test that runs against
real data, and confusing "the code compiles" with "the code works."

## What has and hasn't been executed

| Category | What it means | Status in this repo |
|---|---|---|
| **Unit tested** | Pure-Python logic (no DB, no network) executed directly in a sandbox with no internet access and no SQLAlchemy/FastAPI installed. | 498/498 passing across 36 test modules (latest full run). |
| **Integration tested** | The DB-backed ingestion functions (`ingest_job_postings_file`, `ingest_curriculum_document`, etc.) executed against a real (even if SQLite) database, end to end. | **NOT executed.** SQLAlchemy is not installable in the environment this was built in (no internet access). Needs to be run on your machine — see `README.md` quickstart. |
| **Real-data tested** | The pipeline run against real data, not the fixture. | **Curricula: executed** (AICTE, CBIT R22, CBIT R22A PDFs, RAW→GOLD). **Job postings + ESCO: executed** on the 100 supplied postings and the ESCO v1.2.1 delta (`docs/industry_layer.md`). |
| **DB tested** | A live PostgreSQL instance, actually queried afterward to confirm rows landed correctly. | **Knowledge engine only:** GOLD run loaded into PostgreSQL 16.13 through `psql`; second load inserted 0 rows; SQL integrity checks 0 violations. The SQLAlchemy-based ingestion paths remain **NOT executed** (no driver installable). |
| **Frontend tested** | `flutter analyze` / `flutter build web` actually run. | **NOT executed. Flutter SDK unavailable in this environment.** Dart files have only been hand-reviewed, never compiled. |

## Fixture data vs real data — do not confuse these

Everything under `data/external/demo_fixture/` is synthetic or a tiny
hand-written illustrative subset (see that folder's own `README.md`). Tests
and dry-runs against it prove the *code path* works — they are not evidence
about real-world data quality, real column names, or real skill distributions.
**No fixture result has ever been reported as if it were a real-dataset
result in this project's history**, and it should stay that way: if you see a
number in a report, check whether it says "fixture" or "real dataset" before
trusting it for anything analytical.

## Current known limitations (carried forward from Phase-1 hardening)

- **Near-duplicate detection is batch-local only.** `find_near_duplicates()`
  only compares postings within the single file/batch being ingested right
  now, bucketed by exact (job_title, company_name) match. It has no
  visibility into postings already in the database from a previous run, and
  two postings for the same role under slightly different titles (e.g. "ML
  Engineer" vs "Machine Learning Engineer") will not be bucketed together.
  Cross-run protection exists only for **exact** text matches (via
  `clean_description_hash`), not near-duplicates. Extending near-duplicate
  detection across runs (e.g. via MinHash/LSH against the whole table) is
  out of scope for Phase 1.
- **Naukri column headers are unverified.** `COLUMN_MAP_PRESETS["naukri"]` in
  `app/pipelines/ingestion/job_postings.py` is my best inference from the
  Kaggle dataset page's human-readable field list, not a verified read of the
  literal CSV header row. Run `df.columns.tolist()` on the actual downloaded
  file before trusting it (the ingestion CLI will also warn loudly if the
  mapped columns aren't found).
- **Curriculum `.csv` is not supported.** By design (see
  `app.pipelines.preprocessing.curriculum_structuring.resolve_extraction_method`)
  — it was previously silently read as one plain-text blob, which is not real
  parsing, so it was removed rather than misrepresented as supported.
- **GOLD-layer artifacts do not exist yet.** RAW/BRONZE/SILVER are implemented
  for jobs and curricula; GOLD (skill-level analytical entities) is explicitly
  out of scope until the ESCO/skill-extraction phase.

## Skill extraction + normalization (current phase)

**Methodology:**
- **Normalization** (`app/pipelines/preprocessing/skill_normalization.py`): lowercase + whitespace collapse ONLY -- punctuation in technical tokens (C++, .NET, Node.js) is never stripped.
- **Extraction** (`app/pipelines/preprocessing/skill_extraction.py`, pure): whole-token, boundary-safe matching against (a) ESCO preferred labels, (b) ESCO aliases, (c) a curated technical-token list -- never blind fuzzy matching, never a transformer model. Longest-match-first with span-consumption prevents overlapping/redundant mentions (e.g. "machine learning" and a bare "learning" entry both firing on the same text).
- **ESCO mapping honesty**: a mention only gets `mapping_status = "mapped"` if it resolves via exact_label / alias / normalized_label. A recognized technical token with no ESCO match stays `unmapped` -- this is correct, expected behavior with a small ESCO fixture, not a bug (see the tests in `test_skill_extraction.py` for a documented real example: a bare "Python" tag doesn't match ESCO's disambiguated "Python (computer programming)" label unless an alias covers the short form).
- **Idempotency**: `mention_hash_for(source_type, source_id, normalized_text, method)` -- re-running extraction on the same source is safe; verified via `test_orchestration_idempotency_simulated_two_runs`, which simulates two full runs against a pure (DB-free) partition function, not just the hash function in isolation.
- **SKILL vs SKILL MENTION**: `Skill` (canonical taxonomy) and `ExtractedSkill` (evidence a source mentioned something) are deliberately different tables -- an unmapped mention is still persisted, never discarded.

**Status: unit-tested, NOT yet run against real data.** `scripts/extraction/extract_skills.py` exists and is syntax-verified but has never been executed against a live database (SQLAlchemy is not installable in this environment) or real ESCO/Naukri data (not downloaded here). See the main testing table above for the same caveat pattern.

## DB-free test files in this repo

- `backend/tests/test_text_cleaning.py` — HTML/URL/email stripping, technical-token preservation, boilerplate removal, determinism
- `backend/tests/test_deduplication.py` — Jaccard near-dup logic, idempotency partition logic
- `backend/tests/test_validation.py` — job posting + curriculum document validation rules
- `backend/tests/test_curriculum_structuring.py` — course/module/topic/outcome extraction, including the Course-A/Course-B "Unit 1" collision regression test, and the `.csv`-rejection tests
- `backend/tests/test_artifact_writer.py` — RAW/BRONZE/SILVER file writing: determinism, no cross-run overwrite, JSONL round-trip
- `backend/tests/test_data_quality.py` — quality-metric computation, including `already_ingested_records` and skill-mention metrics
- `backend/tests/test_skill_normalization.py` — case/whitespace normalization, technical-token preservation
- `backend/tests/test_skill_extraction.py` — vocabulary matching, alias matching, technical-token boundaries, tag-field parsing, mention deduplication, idempotency simulation (two-run test)
- `backend/tests/test_industry_demand.py` — per-posting dedup, denominator handling, unmapped exclusion
- `backend/tests/test_curriculum_coverage.py` — per-course/topic/outcome dedup, denominator handling
- `backend/tests/test_skill_set_alignment.py` — Jaccard alignment, threshold classification (boundary cases)
- `backend/tests/test_tfidf_alignment.py` — cosine similarity, determinism, empty-doc handling, config storage
- `backend/tests/test_run_selection.py` — GOLD versioned-snapshot re-run semantics (latest-successful-run selection)
- `backend/tests/test_temporal.py` — date bucketing (month/quarter/year), period bounds, missing-date handling
- `backend/tests/test_historical_demand.py` — per-period demand, dated/undated posting tracking
- `backend/tests/test_trend_analysis.py` — absolute/percentage-point/relative change, trend sufficiency, never forcing a direction from weak evidence
- `backend/tests/test_curriculum_drift.py` — descriptive version-comparison statuses, course-level drift, never labeling a decrease "outdated"
- `backend/tests/test_gap_classification.py` — MISSING/PARTIAL/COVERED/INSUFFICIENT_EVIDENCE classification, None-vs-zero, threshold boundaries, trend/drift passthrough never affecting classification, programme-level aggregation
- `backend/tests/test_run_compatibility.py` — evidence-run compatibility verdicts (COMPATIBLE/INCOMPATIBLE_SCOPE/UNKNOWN_SCOPE/NO_RUN), never invents compatibility from missing scope data
- `backend/tests/test_recommendation_engine.py` — all 26 letters (A-Z) of recommendation-engine scenarios: action selection, evidence sufficiency gating, course targeting, multi-skill grouping, drift never becoming "outdated"
- `backend/tests/test_programme_isolation.py` — proves AI&DS/ECE/Mechanical/Civil data cannot leak across programmes, institutions, or curriculum versions
- `backend/tests/test_core_knowledge_mapping.py` — deterministic matching, AMBIGUOUS/NO_MATCH never silently resolved, discipline isolation by data, inactive exclusion, mapping-target validity, evidence authority, duplicate detection, NULL-vs-zero confidence
- `backend/tests/test_core_knowledge_loaders.py` — CSV/JSON loaders on real fixture files, invalid-record rejection, content-fingerprint idempotency key, fixtures visibly labelled FIXTURE
- `backend/tests/test_term_normalization_taxonomy.py` — full matching taxonomy (exact/normalized/abbreviation/synonym/compound), the spec's own DBMS/OS/DS/CN/AI examples, and both critical negative cases ("Advanced Data Structures" and "Data Structures and Algorithms" are never silently treated as "Data Structures")
- `backend/tests/test_curriculum_structuring.py` (extended) — PART headings, COURSE CONTENT label, CO/CLO/Course-Outcome/Learning-Outcome/bare-numeral outcome labeling
- `backend/tests/test_data_quality.py` (extended) — curriculum ingestion quality gates (course/topic counts, duplicates, empty entries, malformed codes, extraction volume)
- `backend/tests/test_curriculum_structuring.py` (extended, this phase) — 9 new regression tests reproducing exact real-world patterns found auditing the actual AICTE UG CSE Model Curriculum and CBIT R22 B.E. CSE syllabus PDFs: digit-year-prefix course codes, a year-reference false positive, module content with no explicit "Topics:" label, outcomes-label lead-in text, and a lowercase line-wrap false positive

**Core knowledge DB orchestration and API are NOT DB-tested** (no SQLAlchemy/FastAPI runtime in the build environment) — only their pure logic is unit-tested.

See `docs/analytics_methodology.md` for industry-demand/coverage/alignment, `docs/temporal_methodology.md` for trends/drift, `docs/gap_classification_methodology.md` for gap classification, `docs/recommendation_methodology.md` for recommendations, and `docs/generalization_methodology.md` for the programme-agnostic domain model.

None of these import `sqlalchemy`, `fastapi`, or `pydantic` — that's
deliberate, so they can run in a minimal Python environment as a fast
first-line check, separate from the full integration suite you'd run with
the real dependencies installed.

- `backend/tests/test_concept_semantic_matching.py` -- TF-IDF+rule-based semantic layer (Stage 2/3): the brief's own validation examples (Searching, Deadlock Management, Database Normalization), critical disambiguation (Neural vs Computer Networks, Process vs Project Scheduling), stopword-collision regression, ambiguity detection, concept discovery. See docs/semantic_concept_matching.md for the full honest capability statement (no transformer models available in this environment).

- `backend/tests/test_layout_aware_extraction.py` -- pdfplumber table-column isolation, math-glyph stripping, corpus-wide boilerplate detection (with the critical structural-marker exclusion fix), real-PDF regression test against the actual AICTE document.
- `backend/tests/test_corpus_clustering.py` -- TF-IDF+KMeans clustering, provenance preservation, determinism, multi-document filtering, and a structural guard proving no 'promote'/'accept' function exists in this module's public API.


## Knowledge-engine regression layers (added in the hardening pass)

| Layer | File | What it guards |
|---|---|---|
| Golden pages | `backend/tests/test_golden_regression.py` + `backend/tests/fixtures/golden/*.json` | 4 real pages (R22A Operating Systems, R22 Data Structures, AICTE Programming for Problem Solving, AICTE IDEA Lab table page): course, title, units, prerequisite, 36 expected topics attributed to the right course, listed non-topics rejected. Fixtures are the exact BRONZE text; rebuild with `scripts/evaluation/build_golden_fixtures.py` only for an intended extraction change. |
| Parser structural rules | `test_parser_structural_rules.py`, `test_layout_reading_order.py` | header vs mention, prerequisites, semesters, wrapped titles, boundaries, reading order, table continuation |
| Engine units | `test_knowledge_engine.py` | contracts + quarantine, noise labels, backend swap/unavailability, SILVER validity, health gate incl. simulated 349→31 unit collapse, gates, drift, skills, review/versioning, digest determinism, NULL vs '' in DB CSV, observability, config hashing, evaluation metrics |
| API service | `test_knowledge_service.py` | BLOCKED gates return no items, None stays None, provenance attached |
| Pipeline health (runtime) | `health.json` in every GOLD run | per-document checks and baseline regression; analytics BLOCKED on FAIL |

Evaluation files in `data/evaluation/` are assistant-labelled (`human_validated: false`); see `docs/knowledge_engine.md` §6 for the results and their sample sizes.
| Industry / ESCO | `test_industry_layer.py`, industry part of `test_knowledge_service.py` | ESCO delta semantics (Added/Updated/Removed, retired labels never matched, skill groups), indexed extractor = reference extractor, label evidence and qualification rules, mapping states, posting identity and ingestion statuses, posting vs company prevalence, no trend from one period, gap discipline guard and None vs zero, every gap gets a recommendation or a structured suppression, **recommendations cannot become source evidence**, industry health gate blocks analytics on a simulated collapse, scope warning on every API result |
| Semantic sense + hard negatives | `test_semantic_sense.py` | alias-sense (A–H), acronym sense, spelling-variant aliases, hard-negative pins incl. the known "version control systems" failure, family-scoped "Stack", separate similarity signals with provenance, embedding cache and contextual input, unavailable embedding backends reported not faked |
| Human review workflow | `test_human_review.py` | fresh items have no human labels; ingest rejects duplicates, missing ids, invalid labels, missing reviewer, edited model columns, engine changes; verdicts and error categories derive only from human labels |
