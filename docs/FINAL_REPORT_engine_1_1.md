# Skill-Gap & Curriculum Drift Intelligence — Final Report (industry + ESCO activated)

> **Historical report** (run `6472ec43cba27593`), kept unchanged. The current release is `c066b227857f9eaf`, baseline `84d7737ccb8e4d87`: see [FINAL_RELEASE_REPORT.md](FINAL_RELEASE_REPORT.md).

Final run **`6472ec43cba27593`** · pipeline `knowledge-engine-1.1.0` · parser fingerprint `a7f6801a5ad88f49` · code fingerprint `889d95730b7af071` · config 1.2.0 · content digest `488fd701…8d46` · 2026-09-27.
This revision adds the generic alias-sense correction (section R), the semantic-layer status (S) and the frozen human-review workflow (T); earlier run `81c8820d2bdaa681` is kept unchanged.
Every number here comes from that run's GOLD files, its PostgreSQL load or the test log. Method details:
`docs/knowledge_engine.md` (curriculum), `docs/industry_layer.md` (industry/ESCO), `docs/semantic_layer_engine1.md`
(semantic layer + alias sense), `docs/human_validation_review_set_v1.md` (review workflow); evidence chains: `docs/evidence_chains.md`.

> **These results describe the supplied job-posting dataset and are not necessarily representative of the entire
> labour market.** 100 postings · 4 files · posted 2026-09-22 (single day) · country code IN · 95 companies · 97 titles.

## A. Job dataset scope

| | |
|---|---|
| Files | `jobs_20260922_054207_ac078854.xlsx`, `…054558_98aee052`, `…054917_2245fba5`, `…054942_367730fd` (25 rows each; SHA-256 verified) |
| Postings | 100 read, 100 eligible |
| Dates | earliest = latest = 2026-09-22 (1 month period) |
| Geography | IN 100 (locations: 47 distinct strings) |
| Companies | 95 distinct (5 companies with 2 postings); company industry given for 35 postings, 22 values |
| Titles | 97 distinct; mostly non-software roles (HR, accounts, sales, teaching, engineering, front office) alongside developer/cloud/security roles |
| Platforms (from URLs) | Naukri 46, LinkedIn 32, Indeed 20, company sites 2 |

## B. ESCO dataset scope

`ESCO dataset - v1.2.1 - delta` ZIP → one `delta.csv`, **163,559 rows** (Added 106,095 / Removed 52,465 /
Updated 4,999), 29 languages, 14,163 URIs (occupation rows 88,632, skill 70,857, skill-group 40, NACE 4,030).
It is a **change log, not a taxonomy**. Reconstructed with delta semantics: **9,298 skill concepts** (current English
prefLabel), 2,283 active English altLabels, 1,058 retired altLabels; 0 English skill concepts added or removed as a
whole; unchanged-baseline count **unknown**. Skill type known for 2 concepts. Scope everywhere: `PARTIAL_DELTA_SUBSET`.

## C. Posting ingestion

RAW (hash-verified) → BRONZE (standardized rows, hiring-manager personal columns dropped) → SILVER. Identity from URL
(98) or canonical URL (2). **ACCEPTED 100 · DUPLICATE 0 · REJECTED 0 · QUARANTINED 0**; duplicate rate 0.0; missing
descriptions 0; provenance (file, row, URL, date, file hash) complete for 100/100.

## D. Skill extraction

339 mentions (with character spans) in the postings: 319 skill-role, 20 in education requirements
(QUALIFICATION_REQUIREMENT, e.g. "degree in Computer Science" in 8 postings — not demand). By method: exact label 207,
normalized label 73, ESCO altLabel 40, curated technical token 19. Sense states: ESTABLISHED 315, ESTABLISHED_BY_CONTEXT 6,
ALIAS_SENSE_REVIEW_REQUIRED 16, ACRONYM_SENSE_REVIEW_REQUIRED 2. 136 normalized skills; 86 analytics-eligible;
145 mentions in 59 of 100 postings counted as demand. Categories: TECHNOLOGY_TOOL 8; 128 UNCATEGORIZED because ESCO skill
type is not in the delta (no category invented). 807 skill mentions found in curriculum topic text.

## E. ESCO normalization

| Status | Skills |
|---|---|
| EXACT | 58 |
| NORMALIZED (case/whitespace, spelling-variant altLabel, altLabel established by context) | 20 |
| ALIAS_SENSE_REVIEW_REQUIRED (taxonomy alias, meaning not established by the text) | 6 — ".NET"→Visual Basic, "MS Excel"→use spreadsheets software, "resolve technical issues", "Google Search", "data collection"→statistics, "SAP"→SAP Data Services |
| SEMANTIC_MATCH | 0 |
| AMBIGUOUS | 1 ("solving problems": two ESCO concepts) |
| UNMAPPED (not in the delta subset) | 8 — aws, azure, docker, gcp, kubernetes, node.js, react.js, tensorflow |
| INSUFFICIENT_EVIDENCE (single ordinary word / bare qualified word / 1 character) | 43 — e.g. communication (52 postings), plan (12), accounting (8), agile (6) |

ESCO mapping yield 78/86 eligible skills = 0.907. No similarity is called confidence.

## F. Industry demand

82 skills with demand. Support: SUPPORTED 4 · OBSERVED 14 · INSUFFICIENT_EVIDENCE 64 · HIGH_SUPPORT 0.

| Skill | Postings (of 100) | Companies (of 95) | Support |
|---|---|---|---|
| SQL | 6 (6.0 %) | 6 (6.32 %) | SUPPORTED |
| customer service · quality standards · azure (unmapped) | 5 each | 5 each | SUPPORTED |
| C# · DevOps · JavaScript · aws (unmapped) | 4 each | 4 each | OBSERVED |

Observed prevalence only — not importance. No skill reaches the existing 15 % high-demand threshold. Trend:
**INSUFFICIENT_EVIDENCE** (one period). Segments: 8 data-driven clusters (silhouette 0.013 — no real structure),
sizes 19–3, all below 30 postings → no segment-level gaps.

## G. Curriculum coverage

From topic text only (never course titles), per document: target R22A (113 courses), previous R22 (36), reference
AICTE (40). Coverage rows for demanded skills: target 20, reference 7, previous version 5. Example: SQL in 4 of 113
target courses (3.54 %: 22CSC11N DBMS, 22CSE05 Advanced Database Systems, 22CSE32 Cyber Security "SQL Injection",
22CSO02). Direct-textual vs normalized-only course counts, concept links and reference coverage are kept separate.

## H. Skill gaps

82 gaps: **MISSING 1 · PARTIAL 19 · COVERED 0 · INSUFFICIENT_EVIDENCE 62**. All 62 insufficient ones are
DISCIPLINE_RELEVANCE_UNESTABLISHED: the skill is named in no curriculum document of the discipline and the postings
are mixed-occupation, so its absence is not treated as a gap (e.g. customer service, quality standards, azure — the 3
SUPPORTED ones are in the review queue). The one MISSING gap ("solving problems", 1 posting) has an ambiguous ESCO
mapping. PARTIAL uses the existing 40 %-of-courses threshold, so any skill in fewer than 46 of 113 courses is PARTIAL.
Each gap row carries industry population/count/prevalence, curriculum population/count/coverage, evidence state,
reasons, scope and run id.

## I. Recommendations

**1 recommendation:** SQL → EXPAND_EXISTING_TOPIC in 22CSC11N, 22CSE05, 22CSE32, 22CSO02 (MODEL_SUGGESTED;
uncertainty: BORDERLINE_SUPPORT) — unchanged by the alias correction (ESCO EXACT, 6/100 postings). **81 suppressed**,
each with structured reasons (a gap can have several): INDUSTRY_SUPPORT_BELOW_THRESHOLD 78 · GAP_INSUFFICIENT_EVIDENCE 62 ·
ESCO_MAPPING_AMBIGUOUS 1. Recommendations are derived outputs (`is_source_evidence = false`) and are refused as evidence.

## J. Evidence chains (manual acceptance test, `docs/evidence_chains.md`)

* **SQL (recommendation):** 6 postings (e.g. `posting:25607dc750736b1d`, row 4 of `…054942…`, "…Entity Framework,
  and SQL…" chars 451–454) → skill `skill:6ea784d1559c39f0` → ESCO EXACT `…/skill/598de5b0-…` "SQL" → 6/100 postings,
  6/95 companies, SUPPORTED → target topics p.76 "SQL: Data Types", p.136, p.175 (4 courses, 3.54 %), reference CS-505
  p.120 → PARTIAL → EXPAND_EXISTING_TOPIC.
* **JavaScript (no recommendation):** 4 postings, ESCO EXACT, 3 target courses (Web Programming p.80 …) → PARTIAL →
  suppressed: 4 postings = OBSERVED, below SUPPORTED.
* **aws (no recommendation):** now 4 established postings (the EY service-line mention is ACRONYM_SENSE_REVIEW_REQUIRED;
  the Cohesity investor-list mention still counts — a limitation), UNMAPPED in the delta subset, named in no curriculum
  document → INSUFFICIENT_EVIDENCE / DISCIPLINE_RELEVANCE_UNESTABLISHED.
* **.NET (no demand):** 5 postings, ESCO altLabel of "Visual Basic"; no posting names Visual Basic → ALIAS_SENSE_REVIEW_REQUIRED,
  excluded from demand, in the review set (v1-042).
* The test also exposed a word-sense error ("Angular" matching "Angular momentum" in AICTE Physics) that was fixed
  generically before the final run.

## K. Representativeness limitations

100 postings on one day, mostly outside software; 5–7 postings behind every SUPPORTED skill; ESCO is a partial
subset; exact matching without a context model (company-description mentions, word senses: 4 of 28 sampled counted
mentions had the wrong sense); the label evidence rule holds back genuine skills (communication, accounting);
no trend; segments without structure. None of this describes the Indian labour market.

## L. Evaluation

| Evaluation | n | Result | Labels |
|---|---|---|---|
| Industry mention sample | 60 | counted-as-demand precision 0.964 (27/28), recall 0.628 (27/43); sense correct 22/25 | assistant; one rule widened after labelling (disclosed) |
| ESCO mapping / semantic benchmark | 54 frozen items | **0 labelled** — human review pending (section T) | — |
| Golden curriculum pages | 4 pages / 36 topics | recall 1.0 each, 0 misattributed | assistant |
| Topic noise filter | 75 | accuracy 0.827; noise leakage 0.164 | assistant |
| Topic mapping relationships | 45 | accuracy 0.578; link precision 0.733 | assistant |
| Semantic hard negatives | 12 cases | 8 handled, 1 handled conservatively, 1 known failure, 2 known limitations | expected behaviour, not a metric |

No human validation anywhere. No threshold tuned on any sample.

## M. Health-gate results

Curriculum documents: AICTE PASS, R22 PASS, R22A PASS. Industry: **PASS** — hashes 4/4, postings 100, duplicate
rate 0.0, missing descriptions 0.0, eligible 100, extraction yield 0.59, eligible skills 86, ESCO yield 0.907,
ambiguous ratio 0.007, provenance 1.0, ESCO concepts 9,298. The alias correction lowered counts against the previous
baseline by at most 11 % (mentions), below the 20 % limit; the baseline was then re-recorded. Gates: concept_discovery,
reference_mapping, concept_drift, skill_taxonomy (scope PARTIAL_DELTA_SUBSET), industry_demand, industry_gap,
recommendations — all ALLOWED. A simulated extraction collapse FAILs the industry gate and blocks demand, gaps and
recommendations (tested).

## N. Database validation (PostgreSQL 16.13, via psql)

Fresh database, first load: pipeline_run 1, document 3, course 189, unit 662, topic 8,982, concept 1,337,
edge 4,366, topic_mapping 4,426, concept_drift 782, review_item 1,337, population_scope 1, job_posting 100,
esco_concept 180, skill 136, skill_mention 339, industry_demand 82, skill_gap 82, recommendation 82 (1 supported +
81 suppressed). Second load: **0 rows inserted in every table**. 27 foreign keys, 28 primary/unique constraints.
Integrity queries (all 0): duplicate postings by URL, duplicate skill keys, mentions without posting, demand count
mismatch, **demand exceeding established mentions, demand for alias-review skills**, demand without scope warning,
recommendations without gap / on INSUFFICIENT_EVIDENCE gaps / marked as source evidence, mapped skills without ESCO
concept, calibrated scores claimed, human validation without decision, plus the curriculum checks. The 6
alias-review skills have NULL `esco_uri` and their ESCO concept in `taxonomy_candidate_uri`; mention sense states are
stored per mention. Schema change is additive (one CHECK widened, three nullable columns).

## O. API validation

FastAPI is still not installable here (package index returns no distribution), so the app was **not run**. Routes
compile; no path collisions. New read-only routes under `/api/v1/industry/`: scope, health, esco-audit, demand,
skills, segments, gaps, recommendations, why-no-recommendation, evidence-trace, review-queue (plus the 12
`/api/v1/curriculum/` routes). The service layer they call is unit-tested: every industry response carries the
population scope and warning; blocked gates return no items; why-no-recommendation is structured; evidence traces
are available for every demanded skill.

## P. Flutter validation

Flutter SDK unavailable: nothing was compiled, analysed or tested. No industry/knowledge screens exist in the app;
the existing screens show only real API data and the unbuilt ones say so. No Flutter claim is made.

## Q. Remaining blockers

1. **Human review of the frozen set `data/human_validation/v1/review_file.xlsx` (54 items, 0 labelled).** Nothing can
   be promoted to HUMAN_VALIDATED, and no semantic accuracy can be reported, before this.
2. An environment where an embedding model can run (sentence-transformers + a local model, or an embedding API):
   PyPI has no distribution here and huggingface.co is denied by the egress policy.
3. The full ESCO v1.2.x baseline (not only the delta) and more postings over several periods.
4. FastAPI and the Flutter SDK, to run the API and build the app.

## R. Alias-sense correction (generic)

An ESCO altLabel establishes a taxonomy relationship, not the meaning of arbitrary job text. Details and every changed
number in `docs/semantic_layer_engine1.md` §3. Summary (run 81c8820d → 6472ec43): mentions counted 163 → 145;
eligible skills 93 → 86; ESCO-mapped eligible 84 → 78; demand rows 89 → 82 (Visual Basic, spreadsheets, solve technical
problems, search engines, statistics, SAP Data Services, gcp removed; aws 5 → 4); gaps 89 → 82 (statistics PARTIAL and
six INSUFFICIENT removed, no classification changed); recommendations 1 → 1 (SQL, identical); suppressions 88 → 81;
industry review items 14 → 28.

## S. Semantic layer

Backend used: **TF-IDF** (lexical). Embedding backends implemented behind the same interface (`EmbeddingBackend`,
cache keyed by model + configuration + text hash, contextual input from document/course/unit/neighbour metadata) but
**unavailable**: no torch / transformers / sentence-transformers / tokenizers, no local embedding model, PyPI returns
no distribution, huggingface.co 403 by policy. So no embedding model was selected, no before/after model comparison
exists, concept clustering is unchanged (silhouette 0.110), and no claim of semantic understanding is made. New:
separate `lexical_similarity` / `context_similarity` / `semantic_similarity = null` / `taxonomy_similarity = null`
signals with provenance on all 440 linked mappings (no composite score); 12 hard-negative regression cases; a
per-mention alias- and acronym-sense rule. Cost: 186 s cached run on 2 CPUs, peak RSS 296 MB, embedding cache 0 bytes.

## T. Human-validation workflow

`scripts/review/build_review_set.py` froze 54 items (40 curriculum, 14 industry/ESCO; HIGH 28, MEDIUM 26;
DEVELOPMENT 17 / VALIDATION 17 / FINAL_TEST 20) from run 6472ec43 with a manifest of run id, digest, code fingerprint,
config hash and per-item hashes. `scripts/review/ingest_human_review.py` validates a returned file (ids, labels A–H,
reviewer, unedited model columns, unchanged engine), stores decisions with model and dataset versions, builds
`gold_semantic_validation.json` from human-labelled items only, and evaluates Version 1 per split. Schema:
`docs/human_validation_schema.json`. **Status: 0 labels — workflow stopped here, awaiting the reviewer.**

### Evidence classes in the final run

| Class | Records |
|---|---|
| DIRECTLY EXTRACTED | 100 postings; 339 posting mentions with spans (315 meaning established directly); 807 curriculum mentions; 189 courses, 8,982 topic fragments |
| NORMALIZED | 20 ESCO-NORMALIZED skills; 8 curated-token skills (UNMAPPED to ESCO) |
| TAXONOMY_ALIAS_MATCH + REVIEW_REQUIRED | 6 skills / 16 mentions (plus 2 acronym mentions under review) |
| REFERENCE-MAPPED | 58 ESCO EXACT skills; 53 curriculum topic mappings by text identity |
| SEMANTICALLY INFERRED (MODEL_SUGGESTED) | 0 embedding or ESCO semantic matches; 1,337 concepts; 82 gaps; 1 recommendation |
| HUMAN-VALIDATED | 0 |
| INSUFFICIENT_EVIDENCE | 43 skills (label rule); 62 gaps; 64 demand rows below OBSERVED; trend; 8 segments; 81 suppressed recommendations |
| BLOCKED | none in this run (all gates ALLOWED); embedding backends UNAVAILABLE |

### Tests and idempotency

498 tests passed, 0 failed (36 modules). Idempotency: runs 2–5 of the final sequence produced the identical digest
`488fd701…8d46` with the same run id (run 1 differed only because it recorded the baselines); the second PostgreSQL
load inserted 0 rows in every table. Static generalization audit: 0 forbidden conditionals.
