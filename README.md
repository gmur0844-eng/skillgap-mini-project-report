# Skill-Gap & Curriculum Drift Intelligence for Universities

> **RELEASE CANDIDATE `0534d6e1d06a617f`** (2026-10-10), lineage parent and protected release `c066b227857f9eaf`.
> The candidate becomes the current release when `scripts/mac/rc_validation.sh` ends with `RC VERDICT: PASS` on the
> Mac. Until then `c066b227857f9eaf` is the current release.
> Full report: [`docs/FINAL_RELEASE_REPORT.md`](docs/FINAL_RELEASE_REPORT.md).
> Progress and decisions: [`docs/COMPLETION_AUDIT.md`](docs/COMPLETION_AUDIT.md).

## Quick start (local, from a clone)

```
bash scripts/local/setup.sh    # once: .venv, dependencies, Flutter packages
bash scripts/local/test.sh     # every check CI runs
bash scripts/local/run.sh      # http://localhost:8000/app/   (stop: bash scripts/local/stop.sh)
```

Evidence (curricula, job postings, analysis runs) is not in Git; a fresh clone starts with "No analysis yet". See
[`docs/LOCAL_DEVELOPMENT.md`](docs/LOCAL_DEVELOPMENT.md).

## Current release in brief

The system compares a university curriculum with the skills employers ask for. It finds where coverage is partial or
missing while demand is supported, and recommends changes. Every result is traced to a job posting and a curriculum
page. The software is discipline-agnostic; this release analyses CBIT B.E. Computer Science and Engineering (R22A).

| | Release candidate `0534d6e1d06a617f` | Status |
|---|---|---|
| Job postings | 498 eligible, 106 companies, India: a supplied export plus 11 employers' own job boards read through documented public APIs | VERIFIED |
| Skills with enough demand to judge | 68 (41 high support, 27 supported) | VERIFIED |
| Evidence-supported skill gaps | 11 confirmed; 5 gaps carry a review flag (`compare_runs.py`: `gaps_needing_review`) | VERIFIED |
| Recommendations | 11 issued · 14 withheld for review · 218 not recommended, each with a reason | VERIFIED |
| Analysis agents | 5 pipeline agents (curriculum understanding, discipline-to-industry relevance, skill intelligence, skill-gap reasoning, curriculum recommendation); experimental layers labelled EXPERIMENTAL | VERIFIED (container); Mac PENDING |
| Peer curricula | 3 of 6 requested (IIT Kanpur, NIT Warangal, NIT Tiruchirappalli) | PARTIAL |
| Occupation mapping | 61 of 498 postings | PARTIAL |
| Industry trends | one snapshot period; additional dated evidence is required to establish a trend | NOT ESTABLISHED |
| Semantic AI | advisory only (Safe Mode), replay of a hash-verified recording | ADVISORY |
| NIRF comparison (Phase 9) | the NIRF ranking page and department syllabi are not available | INCOMPLETE |
| Independent human validation (Phase 11) | blind 58-gap review set ready; 0 reviewer labels | INCOMPLETE |
| Reproducibility | run id from code, inputs, config and semantic identity; a cross-machine gate with a documented allow-list (`scripts/audit/reproducibility_policy.json`) | Mac PENDING |

Industry figures describe the supplied and acquired posting population, not the entire labour market. Nothing in this
release is human-validated.

### Run it

**Requirements:** Python 3.11+ (validated on 3.11 and 3.14), PostgreSQL 16, Flutter 3.x.

```
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.lock   # the validated Mac environment
bash scripts/mac/rc_validation.sh        # tests, pipeline (replay), agents, gates, database, Flutter build, API checks;
                                         # leaves the app running at http://localhost:8000/app/
bash scripts/mac/finalize_release.sh stage    # after RC VERDICT: PASS: stage the source for review
bash scripts/mac/finalize_release.sh commit   # commit and package the release zip
```

**Local development** (`--reload`). The intended database is PostgreSQL: the release database that
`rc_validation.sh` publishes, `skillgap_<run_id>`.

```
cd backend
export DATABASE_URL=postgresql+psycopg2://localhost/skillgap_$(python3 -c "import json;print(json.load(open('../data/gold/knowledge/latest_run.json'))['run_id'])")
../.venv/bin/uvicorn app.main:app --reload       # http://localhost:8000/api/v1/overview
```

To keep the setting, put the same `DATABASE_URL` in `backend/.env` (start from `.env.example`).

Without a reachable database, the API still starts:
- the knowledge endpoints (`/api/v1/overview`, `/api/v1/agents`, …) are served from the GOLD files;
- database routes answer `503 DATABASE_UNAVAILABLE`;
- `/ready` reports `NOT_READY: DATABASE_UNAVAILABLE`;
- the log says what to set.

SQLite (`sqlite:///./data/skillgap_dev.db`, relative to the working directory) is only a lightweight fallback for the
older ingestion paths. It holds none of the release data.

To start only the API and app against an existing database:

```
cd backend && DATABASE_URL=postgresql+psycopg2://localhost/skillgap_<run_id> \
  WEB_DIR="$PWD/../flutter_app/build/web" ../.venv/bin/uvicorn app.main:app --port 8000
```

### Reproduce it with legitimately obtained evidence

1. **Evidence.**
   * Curricula and the supplied export are listed with their SHA-256 in `data/metadata/curriculum_sources.json`.
   * Peer curriculum PDFs and raw job-board files are not redistributed. Re-acquire them from the official publishers
     with `bash scripts/mac/acquire_official_evidence.sh`; the sources are listed in `data/metadata/official_sources.json`.
   * Job boards list the postings open *on the day*, so re-acquisition yields a new snapshot and a new run.
2. **Run.** `python3 scripts/acquisition/recompute.py` builds a new run with lineage.
3. **Verify.** Run the audits in `scripts/audit/`: `full_consistency_audit.py`, `topic_concept_mapping_audit.py`,
   `generalization_audit.py`, `release_gap_qa.py` and `compare_runs.py`.
4. **Human validation.** Run the Google Form script `scripts/evaluation/create_semantic_validation_form.gs`, then
   `scripts/evaluation/semantic_validation.py import-form`. Details: `docs/SEMANTIC_HUMAN_VALIDATION_FORM.md`.

---

## Development history (historical — superseded by the release section above)

The text below records how the system was built, phase by phase. Its counts and statuses describe the build at the time
each phase was written; for example, "498/498 tests" was the DB-free suite of an early phase, not the postings count.
Current figures are in the release section above.

A real-data pipeline + analytics system that measures how well a university curriculum
aligns with actual industry skill demand, tracks the gap over time, and generates
evidence-based curriculum recommendations.

This is **not** a synthetic demo. The system is built to run against:
- **ESCO** (EU skills/occupations taxonomy) — primary skill ontology
- **O\*NET** (US occupational database) — secondary occupation/skill reference
- **Real job-posting data** (dated, real postings — see `docs/data_sources.md`)
- **Real, publicly published university curricula** (PDF or TXT you supply, or that we
  source from public program pages — `.csv` is intentionally NOT supported for
  curriculum ingestion; see `app/pipelines/preprocessing/curriculum_structuring.py`)

## Status of this build

This repository is being built **phase by phase**, per the development order below.
Each phase is validated before the next begins — do not assume unimplemented phases
exist just because their folders/models do.

Status legend: **IMPLEMENTED** (code exists, compiles) / **UNIT-TESTED** (DB-free tests genuinely pass) / **REAL-DATA-VALIDATED** (run against real ESCO/Naukri/curriculum data) / **RUNTIME-VALIDATED** (FastAPI/PostgreSQL actually started) / **PENDING**.

| Phase | Status |
|---|---|
| 1. Real data acquisition | Documented (see `docs/data_sources.md`) — primary job-postings source is the India-focused Naukri.com dataset; O*NET is secondary/backup. Datasets themselves: **PENDING** (no internet access in this environment) |
| 2. Raw/Bronze/Silver/Gold pipeline | **IMPLEMENTED + UNIT-TESTED**: validation -> cleaning -> deduplication -> persistence -> quality metrics, every run tracked as an `AnalysisRun`, every rejection explained via `IngestionRejection` |
| 3. Curriculum PDF extraction | **IMPLEMENTED + UNIT-TESTED**: pdfplumber extraction + course/module/topic/outcome/learning-outcome structuring, correct even when two courses share a heading like "Unit 1" (regression-tested) |
| 4. Job-posting preprocessing | **IMPLEMENTED + UNIT-TESTED**: HTML/URL/email stripping, boilerplate removal, technical-token preservation, exact + near-duplicate detection (within-batch and cross-run) |
| 5. ESCO/O*NET ingestion | **IMPLEMENTED + UNIT-TESTED** (idempotent, provenance-tracked). **REAL-DATA: PENDING** — not yet run against the full official ESCO/O*NET downloads (needs internet access this environment doesn't have) |
| 6. Skill mention extraction + normalization | **IMPLEMENTED + UNIT-TESTED**: controlled-vocabulary + alias + technical-token matching (no fuzzy matching, no transformer), honest unmapped handling, idempotent re-extraction |
| 7. GOLD analytics: industry demand, curriculum coverage, skill-set (Jaccard) alignment, TF-IDF text alignment | **IMPLEMENTED + UNIT-TESTED** — see `docs/analytics_methodology.md` for exact formulas/denominators and the None-vs-zero evidence semantics |
| 8. Historical industry trends, curriculum versioning + drift, temporal industry-curriculum comparison | **IMPLEMENTED + UNIT-TESTED** — see `docs/temporal_methodology.md`. Real bug found and fixed here: curriculum re-ingestion previously created a duplicate `CurriculumVersion` on every run |
| 9. Evidence-based curriculum gap classification (MISSING/PARTIAL/COVERED/INSUFFICIENT_EVIDENCE) | **IMPLEMENTED + UNIT-TESTED** — see `docs/gap_classification_methodology.md`. No numeric gap score computed; trend/drift kept as separate evidence dimensions, never folded into the classification |
| 10. Evidence-consistency hardening (run/population-scope compatibility) | **IMPLEMENTED + UNIT-TESTED** — see `docs/gap_classification_methodology.md`. Real bug found and fixed: incompatible-scope evidence (e.g. a programme-scoped drift status attached to a global gap classification) is now flagged, not silently combined |
| 11. Deterministic evidence-based recommendations | **IMPLEMENTED + UNIT-TESTED** — see `docs/recommendation_methodology.md`. Controlled 6-action vocabulary, no LLM, no numeric priority score |
| 12. Programme-agnostic generalization (Discipline/Department, programme-scoped analytics, multi-programme isolation) | **IMPLEMENTED + UNIT-TESTED** — see `docs/generalization_methodology.md`. Repo-wide audit found zero branch-specific hardcoding; a real API bug (scoped runs silently shadowing global ones) was found and fixed during this phase |
| 13. Core Discipline Knowledge Layer (Discipline -> Domain -> Topic -> Subtopic -> Skill, provenance, curriculum/skill mappings) | **IMPLEMENTED + UNIT-TESTED (pure logic only); NOT DB-TESTED** — see `docs/core_knowledge_methodology.md`. Framework only: no real core-knowledge data imported |
| 14. Cross-university curriculum normalization hardening (abbreviation/synonym/compound matching taxonomy, PART/CO-CLO structural parsing, quality gates) | **IMPLEMENTED + UNIT-TESTED** — see `docs/curriculum_normalization_methodology.md`. NCS and Jooble real-data acquisition are separately blocked (see their own docs) and unaffected by this phase |
| 15. Real curriculum data acquisition (AICTE UG CSE Model Curriculum + CBIT R22 B.E. CSE syllabus, real PDFs) | **REAL FILES ACQUIRED AND STRUCTURALLY PARSED** — see "Real-document findings" in `docs/curriculum_normalization_methodology.md`. Found and fixed 4 genuine, generic parser bugs using real data (course-code format gap, a year-reference false positive, a missing module-content fallback that caused 0 topics to be extracted from either real document, and an outcomes-label edge case). NOT DB-tested — no live database in this build environment |
| 16. Curriculum knowledge engine RAW→BRONZE→SILVER→GOLD (`backend/app/knowledge_engine/`, `docs/knowledge_engine.md`) | **REAL-DATA-VALIDATED** on the three real PDFs (AICTE, CBIT R22, CBIT R22A): stage contracts + quarantine, health gate that BLOCKS analytics on degraded extraction, subject-agnostic concept discovery, R22A→AICTE mapping with explanations, R22→R22A drift, review queue (no human decisions yet), observability, idempotent reruns (identical content digest) |
| 17. PostgreSQL publish of the knowledge GOLD run (`backend/app/db/knowledge_schema.sql`) | **DB-VALIDATED** on a live PostgreSQL 16 via `psql` (no Python driver installable): first load inserts, second load inserts 0 rows, SQL integrity checks 0 violations |
| 18. Curriculum knowledge API (`/api/v1/curriculum/*`) | **IMPLEMENTED + service UNIT-TESTED**; FastAPI not installable here, routes compile-checked only |
| 19. Industry / ESCO layer on real data (`docs/industry_layer.md`) | **REAL-DATA-VALIDATED + DB-VALIDATED** on the 100 supplied postings (one day, IN, 95 companies) and the ESCO v1.2.1 **delta** (partial subset: 9,298 skill concepts). Demand, coverage, gaps and 1 recommendation produced; results describe the supplied postings only, not the labour market |
| 20. Flutter screens for the knowledge engine | **Not built.** Existing screens show only real API data; unbuilt views say so |
| 21. Semantic layer (`docs/semantic_layer_engine1.md`) | Embedding backends + cache + contextual input **IMPLEMENTED but UNAVAILABLE here** (no torch/transformers/model; PyPI and huggingface.co blocked). TF-IDF stays the only similarity; separate lexical/context signals recorded; generic alias-/acronym-sense validation; 12 hard-negative regressions |
| 22. Human validation (`docs/human_validation_review_set_v1.md`) | Frozen review set v1 (54 items) + validated ingest workflow. **0 human labels** — nothing is HUMAN_VALIDATED |

**What is and is not validated.** The curriculum knowledge engine and the industry/ESCO layer (phases 16–19) have been run end to end on the real curriculum PDFs and loaded into a live PostgreSQL 16. The older SQLAlchemy-based job/ESCO/O*NET ingestion paths are still **not** run (no driver installable), and the SQLAlchemy/FastAPI application has never been started (packages not installable here). Full test suite: 498/498 passing (DB-free).

Reproduce the knowledge pipeline:

```bash
python scripts/pipeline/run_knowledge_pipeline.py               # RAW -> GOLD (data/gold/knowledge/<run_id>)
python scripts/pipeline/run_knowledge_pipeline.py --publish     # + load into local PostgreSQL (schema `knowledge`)
python scripts/pipeline/run_knowledge_pipeline.py --record-baseline   # after reviewing a healthy run
```

## Stack

- **Backend:** Python, FastAPI, SQLAlchemy, Pydantic, PostgreSQL (SQLite supported for dev)
- **Frontend:** Flutter (desktop/web target), hitting the FastAPI backend over HTTP
- **NLP/ML:** sentence-transformers (embeddings), scikit-learn (TF-IDF), spaCy (text
  preprocessing) — introduced starting Phase 6
- **Orchestration:** simple background-task pipeline runner for the MVP (no Celery/Redis
  unless a real bottleneck justifies it)

## Running locally

This project assumes you run it **on your own machine**, where you have real internet
access to download ESCO/O*NET/job-posting data (the assistant that generated this
scaffold does not have internet access in its execution sandbox, so it cannot download
these datasets for you — see `docs/data_sources.md` for exact download steps).

```bash
# 1. Start Postgres
docker compose -f docker/docker-compose.yml up -d db

# 2. Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env   # edit DATABASE_URL etc. (current setup: see "Local development" at the top)
alembic upgrade head       # (once migrations are added — Phase 2 uses create_all for now)
uvicorn app.main:app --reload

# 3. Fetch real reference data (see docs/data_sources.md for manual download steps first)
python scripts/ingestion/ingest_esco.py --input-dir ../data/raw/esco
python scripts/ingestion/ingest_onet.py --input-dir ../data/raw/onet
python scripts/ingestion/ingest_job_postings.py --input-file ../data/raw/jobs/naukri_jobs.csv --dataset naukri

# 4. Flutter app
cd flutter_app
flutter pub get
flutter run -d chrome   # or -d macos / -d windows / -d linux
```

## Project structure

See `docs/architecture_data_flow.md` for the full data-flow diagram and rationale for the
bronze/silver/gold layering, provenance model, and why ESCO and O*NET are kept as
separate ID spaces with an explicit crosswalk rather than merged.

## Important: no fake results

Per the project requirements, no skill percentages, alignment scores, demand figures,
or recommendations in this system are hardcoded or synthetically generated for the
main analytical pipeline. Where a real dataset is not yet loaded, the relevant API
endpoints and dashboard views return an explicit "insufficient data" state rather than
fabricated numbers. A small labeled DEMO/TEST fixture (`data/external/demo_fixture/`)
exists only for pipeline smoke-testing and is never used as the analytical dataset.
