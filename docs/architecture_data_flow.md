# Architecture (current state)

```
RAW (data/raw/*)             <- untouched downloads (ESCO CSV, O*NET txt, job postings CSV, curriculum PDFs)
   |
BRONZE (ingestion pipelines)  <- validated + standardized records, provenance recorded
   |
SILVER (preprocessing)        <- text_cleaning.py, deduplication.py, curriculum_structuring.py -> cleaned/deduped/structured records
   |
SILVER (skill mentions)       <- ExtractedSkill: skill_normalization.py + skill_extraction.py -> mapped-or-honestly-unmapped mentions
   |
GOLD (analytics)               <- SkillDemand, CurriculumSkillCoverage, SkillAlignment, AlignmentResult (TF-IDF + Jaccard)
   |
API (backend/app/api/v1)      <- FastAPI endpoints across ingestion, jobs, curricula, skills, skill-mentions, analytics
   |
DASHBOARD (flutter_app)       <- Flutter nav shell; Data Sources, Data Quality, Ingestion, Pipeline Runs, Preprocessing Preview wired to real API
```

**Status legend used below:** IMPLEMENTED (code exists, compiles) / UNIT-TESTED (DB-free tests genuinely pass) / REAL-DATA-VALIDATED (actually run against real ESCO/Naukri/curriculum data) / RUNTIME-VALIDATED (FastAPI/PostgreSQL actually started and exercised) / PENDING.

## Why ESCO and O*NET are separate ID spaces

`skills.taxonomy` is `"ESCO"` or `"ONET"` and `external_id` is only unique *within*
a taxonomy (`UniqueConstraint("taxonomy", "external_id")`). A skill named
"Python" in ESCO and a technology example "Python" in O*NET are two different
rows until `skill_crosswalk` explicitly links them with a method and a
confidence score. This is deliberate — merging them by string match alone would
silently produce false-equivalences the spec explicitly forbids (Section 10).

## Why raw + clean description are both stored

`JobPosting.raw_description` and `.clean_description` are separate columns so the
"raw -> clean -> extracted -> normalized -> taxonomy" per-record inspection view
required by spec Section 45/46 is possible without re-deriving anything — you can
always show exactly what changed and why.

## Skill vs Skill Mention

`Skill` (`app/models/skills.py`) is the canonical taxonomy entity (an ESCO or
O*NET concept). `ExtractedSkill` (`app/models/jobs.py`) is evidence that a
specific source (a job posting, a course title, a curriculum topic, a
learning outcome) actually mentioned something — it may or may not resolve to
a canonical `Skill` (`mapping_status`). These are deliberately different
tables; an unmapped mention is preserved, never discarded.

## GOLD layer: what each model represents

- `SkillDemand` — industry demand evidence for a canonical skill, computed from `ExtractedSkill` rows on real job postings. `docs/analytics_methodology.md` has the exact formula/denominator.
- `CurriculumSkillCoverage` — curriculum coverage evidence for a canonical skill, computed from `ExtractedSkill` rows on courses/topics/outcomes.
- `SkillAlignment` — per-skill comparison of the above two, with transparent threshold-based classification (never called a "recommendation").
- `AlignmentResult` — text/corpus-level alignment: TF-IDF cosine similarity (`tfidf_alignment`) and skill-set Jaccard overlap (`skill_set_alignment`), kept as separate columns, never combined into one score.

## What's real vs. not yet built

- **IMPLEMENTED + UNIT-TESTED (391/391 DB-free tests passing):** ingestion (ESCO/O*NET/job-postings/curriculum), preprocessing, curriculum PDF extraction and structuring, skill mention extraction + normalization + ESCO matching, RAW/BRONZE/SILVER/GOLD artifact writing, industry demand, curriculum coverage, skill-set (Jaccard) alignment, TF-IDF text alignment, historical industry trends, curriculum-version drift, temporal industry-curriculum comparison, evidence-based gap classification (MISSING/PARTIAL/COVERED/INSUFFICIENT_EVIDENCE, no numeric score), the full API surface (ingestion, jobs, curricula, skills, skill-mentions, analytics), and the None-vs-zero evidence semantics in skill classification.
- **IMPLEMENTED but NOT YET REAL-DATA-VALIDATED:** every DB-dependent orchestration function above — none has been run against a live database or real ESCO/Naukri/curriculum data (this sandbox has no internet access and cannot install PostgreSQL/FastAPI).
- **NOT IMPLEMENTED (by design, next phase):** curriculum drift, historical industry trends, embeddings, recommendation engine, the full analytics dashboard, Alembic migrations, Docker for Flutter.
- **Explicitly not attempted here:** downloading the actual ESCO/O*NET/job
  postings data into this repo — that requires real internet access and, for
  ESCO, an email-gated manual step. Run the ingestion scripts on your own
  machine once you've downloaded the source files per `docs/data_sources.md`.


## Core Discipline Knowledge Layer (lineage)

```
RAW  data/raw/core_knowledge/<run_id>/source.<ext>      (byte copy of the authoritative source file)
BRONZE data/bronze/core_knowledge/<run_id>/records.jsonl (parsed records, valid/invalid flagged)
SILVER data/silver/core_knowledge/<run_id>/records.jsonl (domains/topics/subtopics created this run)
DB   core_knowledge_domains -> core_topics -> core_subtopics  (each row: source_id -> data_sources)
MAP  curriculum_topic_core_topic_mappings (MATCHED only; AMBIGUOUS/NO_MATCH -> silver review artifact)
     core_knowledge_skill_mappings -> skills (ESCO provenance stays on the Skill's own DataSource)
```
Separate evidence dimensions (core knowledge / curriculum coverage / industry demand / ESCO) are never
merged into one field. See docs/core_knowledge_methodology.md. Status: framework only, not DB-tested.
