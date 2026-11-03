# Curriculum Knowledge Engine (RAW → GOLD) — methodology and safeguards

> **Counts in this document describe the runs they were written for (up to run d140f830ab26adeb).** From run f173ee4fff47e2a6 on, topic cleaning changed the concept population: 1,318 concepts across all non-peer curricula, of which 1,093 contain a target-curriculum topic; the current graph has 10,331 nodes and 15,689 edges (run 84d7737ccb8e4d87). Current figures, with their scope, are in `docs/FULL_CONSISTENCY_AUDIT.md`. Annotated 2026-10-01; the text below is unchanged.

Package: `backend/app/knowledge_engine/` · entry point: `scripts/pipeline/run_knowledge_pipeline.py`
Configuration: `backend/app/knowledge_engine/engine_config.json` · sources: `data/metadata/curriculum_sources.json`

This document describes what the engine does, how every number it publishes
is produced, and what it refuses to produce. Numbers quoted are from the run
`58aceadb87fa5199` over the three real PDFs (AICTE UG CSE model curriculum,
CBIT B.E. CSE R22 Sem I–IV, CBIT B.E. CSE R22A Sem I–VIII).

## 1. Flow

```
RAW (PDF, SHA-256 verified against the manifest)
 └─ BRONZE  page text; cached per (document hash, parser fingerprint)
     └─ SILVER  courses / units / topics / outcomes / prerequisites  ← stage contracts, quarantine
         └─ HEALTH GATE  per-document checks + baseline regression  → analytics gates
             └─ GOLD  course families → concepts → mappings → drift → skills → review queue
                 └─ PUBLISH (optional)  PostgreSQL schema `knowledge`, integrity verified by SQL
```

Nothing in the code names an institution, programme, discipline or subject.
Documents, their roles (TARGET / PREVIOUS_VERSION / REFERENCE) and their
discipline come from the manifest; scoped vocabularies declare the
disciplines they apply to (`_applies_to_disciplines`). A static AST audit
(`scripts/evaluation/static_generalization_audit.py`) fails on any
conditional that compares against an institution/subject literal
(current result: 0 conditionals, 7 literals in CLI help/seed data).

## 2. Extraction (BRONZE)

* `pdftotext -layout` for every page; `pdfplumber` table isolation only on
  pages with a detected Topics/Content table column (61 of 214 AICTE pages,
  0 CBIT pages).
* **Reading order:** table and prose blocks are ordered by their vertical
  position. (Previously all tables were emitted before all prose, which
  attributed a table below a new course header to the previous course.)
* **Page-break continuation:** a header-less first table on a page with the
  same column count as the previous page's trailing Topics table continues
  it (30 AICTE pages), unless its first row is a course header.
* A header cell must be a short label (≤ 6 words); a long data cell that
  merely contains the word "content" is not a header.
* Running headers/footers are removed corpus-wide, except structural lines
  (unit/module headings, labels, codes). Unit headings accept `-`, `:`, en
  dash and em dash (`UNIT–II` was being lost on 66 real headings).
* Cache: `data/bronze/curricula/<sha16>/pages.<parser-fingerprint>.json`.
  Re-running with unchanged inputs and parser is a CACHE_HIT.

## 3. Structuring (SILVER) and contracts

Generic parser rules (each regression-tested): course header vs. code
mention; non-course identifier prefixes from a data file (ISBN, DOI, SHA, …);
semester headings; prerequisite statements, lists and explicit "Nil";
wrapped title cells (above or below the code row); section boundaries
(text/reference books, references, online/MOOC resources, contributors,
CO-PO matrix, …); appendix headings end course scope; an inline unit title
("Module II: Arithmetic expressions and precedence.") is kept as topic
content unless a "Topics:" label follows; a table cell with several
sentences yields one topic per sentence.

Every record passes a pydantic contract (`contracts.py`: uid pattern,
page > 0, evidence status vocabulary, `score_is_calibrated` must be False,
unique concept members, …). A record that fails is **quarantined with the
reason**; the run continues. SILVER validity rules also quarantine rather
than fail:

| Reason | Count (final run) | Meaning |
|---|---|---|
| ORPHAN_ATTRIBUTION | 1132 | topic text after an appendix heading with no course code (AICTE appendix mathematics syllabi, pp. 200–214) |
| NO_STRUCTURAL_EVIDENCE | 2 | a code-shaped string seen once with no semester (R22A "PO10", "PO11") |
| UNRESOLVED_TITLE | 1 | R22 `22MTC04`: no occurrence carries a title |
| contract violations | 0 | |

Each topic has a noise label (TOPIC, NOISE_BIBLIOGRAPHY, NOISE_URL,
NOISE_LAYOUT_INTERLEAVED, NOISE_FRAGMENT, NOISE_ADMINISTRATIVE, …) and keeps
its source line, page, unit, course and document hash.

## 4. Health gate — fail safely

Per document (`health.py`, thresholds in config):

| Check | Threshold | Final run (AICTE / R22 / R22A) |
|---|---|---|
| raw_hash_verified | = manifest | PASS / PASS / PASS |
| ocr_required_page_ratio | ≤ 0.05 | 0.0 / 0.0299 / 0.0 |
| valid_courses | ≥ 5 | 40 / 36 / 113 |
| titled_course_ratio | ≥ 0.9 | 1.0 / 0.973 / 1.0 |
| topic_noise_ratio | ≤ 0.5 | 0.257 / 0.140 / 0.079 |
| contract_quarantine_ratio | ≤ 0.05 | 0 / 0 / 0 |
| provenance_completeness | = 1.0 | 1.0 / 1.0 / 1.0 |
| baseline_regression | drop ≤ 20 % vs. baseline for the same hash | PASS (baseline recorded) |

Analytics gates derived from document health: `concept_discovery`,
`reference_mapping`, `concept_drift`, `skill_taxonomy`, `industry_gap`,
`recommendations`. A BLOCKED gate writes `blocked/<name>.json` with its
reasons and **no numbers**; the API returns `{"status": "BLOCKED"}`.

The gate fired for real during this work: after the reading-order fix the
AICTE document's outcome count fell 41 %, the document FAILED
`baseline_regression` and `reference_mapping` was BLOCKED. Inspection showed
all removed "outcomes" were table fragments and page numbers captured while
an outcomes block was left open; the change was accepted with
`scripts/pipeline/accept_baseline_change.py`, which records reviewer, reason
and previous baseline, and refuses when any other check is not PASS.

## 5. GOLD analytics

* **Semantic backend** (`semantic_backend.py`): registry with `tfidf`
  (available), `sentence_transformer` and `api_embedding` (both registered,
  both report UNAVAILABLE with the reason; never faked). The resolution
  (requested / used / fallback reason) is stored in the run report.
* **Course families**: KMeans on course TF-IDF vectors per discipline,
  k chosen by cosine silhouette in [4, 24]. Final: k = 24, silhouette 0.110 —
  weak separation, and the chosen k is the upper bound of the range.
* **Concepts**: agglomerative clustering (cosine distance, average linkage,
  threshold 0.55, min support 2) inside each family; named by the most
  specific n-gram shared by ≥ half the members. 1337 concepts from 3302
  member topics; 393 REFERENCE_SUPPORTED, 944 TARGET_ONLY.
* **Edges**: BELONGS_TO_FAMILY 1337, CO_OCCURS_IN_UNIT 2788, PARENT (name
  containment within a family) 221, PREREQUISITE_OF 20 (only from explicit
  prerequisite statements; 59 statements stay unresolved as free text).
* **Topic mapping** (R22A → AICTE, family-scoped): SAME_CONCEPT 52, CHILD 152,
  PARENT 156, RELATED 28, PARTIAL_OVERLAP 52, AMBIGUOUS 11,
  NEW_DISCOVERED_UNMAPPED 1539, INSUFFICIENT_EVIDENCE 2436. Every unmapped
  topic carries the candidates considered, why each was rejected and the
  best out-of-scope candidate. `similarity_score` is TF-IDF cosine, never
  called confidence; None for unmapped topics.
* **Drift** R22 → R22A on comparable semesters I–IV: concepts RETAINED 311,
  RETAINED_REWORDED 200, EXPANDED 44, REDUCED 17, ADDED 34, REMOVED 17,
  UNCERTAIN 159 (all MODEL_SUGGESTED); courses by normalized title RETAINED
  12, RETAINED_RECODED 6, ADDED 19, REMOVED 18 (76 R22A courses outside
  Sem I–IV excluded).
* **Skills**: no taxonomy is present, so `skill_taxonomy` is BLOCKED; 306
  literal tool/acronym candidates (83 TOOL_OR_TECHNOLOGY, 223 ACRONYM) are
  published as MODEL_SUGGESTED / REVIEW_REQUIRED with `taxonomy_mapping = null`.
* **Industry gap and recommendations**: BLOCKED — zero real job postings.
* **Review**: 1337 queue items (HIGH 40, MEDIUM 771, LOW 526), every
  `review_decision = null`. Decisions go in `data/metadata/review_decisions.json`
  (ACCEPT / REJECT / RENAME) and are applied on the next run; the concept
  registry keeps every concept uid ever produced (2386 known, 1049 marked
  absent since a later run).

## 6. Evaluation (assistant-labelled, not ground truth)

All three files in `data/evaluation/` carry `labelled_by: "assistant"`,
`human_validated: false`.

| Evaluation | n | Result |
|---|---|---|
| Golden pages (4 real pages, 36 expected topics, attribution-aware) | 36 | recall 1.0 on all four; 0 topics attributed to another course |
| Topic noise filter (random 25 fragments per document) | 75 | accuracy 0.827; TOPIC P 0.836 / R 0.944; NOISE P 0.786 / R 0.524; noise leakage in kept topics 0.164 |
| Mapping relationships (30 pipeline links + 15 random pairs) | 45 | relationship accuracy 0.578, macro-F1 0.498; linked-vs-unrelated: precision of produced links 0.733 (22 of 30), all 15 random pairs correctly UNRELATED |

Main error sources seen in the benchmark: single-word fragments and
generic words ("sharing", "Advantages", "problems") linked by token
containment; conjunction references ("Eigenvalues and eigenvectors")
reversing PARENT/CHILD; paraphrases (Program vs process) scored below the
RELATED tier. Thresholds were **not** tuned on this sample.

## 7. Idempotency, observability, exports

* `run_id` = hash(pipeline version, parser fingerprint, config hash, backend
  used, document hashes, review-decisions hash); `content_digest` = SHA-256
  over all analytical GOLD files. Three consecutive reruns and two publish
  runs produced the identical digest `cd9245…d99f`.
* `observability.json`: per-stage duration, peak Python heap (tracemalloc)
  and RSS, plus the funnel pages 527 → courses 189 → units 662 → topics 8982
  → clean 7667 → in concepts 3302 → concepts 1337 → mappings 4426 (440
  linked) → skill candidates 306. Cached run: 41.6 s, peak heap 167 MB
  (concept clustering), RSS 233 MB.
* Exports: `exports/*.csv` (concepts, topic mappings, concept drift, course
  drift) and JSONL for every GOLD table.

## 8. Database

`backend/app/db/knowledge_schema.sql` (schema `knowledge`, 13 tables, FKs and
CHECKs). `db_publish.py` loads through `psql` (`\copy` into staging tables,
`INSERT … ON CONFLICT DO NOTHING RETURNING`), keeping NULL distinct from ''
(`NULL '\N'`), and then runs SQL integrity checks. Verified on PostgreSQL
16.13: first load inserted 8982 topics, 1337 concepts, 4366 edges, 4426
mappings …; the second load inserted 0 rows; integrity violations 0. Rows
are immutable per uid: a later pipeline version that changes an attribute
of an existing uid does not overwrite it (reset the database or add a
version column before relying on cross-version loads).

## 9. API

`app/api/v1/curriculum_knowledge.py` → `app/services/knowledge_service.py`
(read-only over GOLD + SILVER): `/api/v1/curriculum/topics`, `/concepts`,
`/concepts/{id}`, `/concepts/{id}/related`, `/concepts/{id}/evidence`,
`/concept-mappings`, `/knowledge-graph`, `/review-queue`, `/skill-candidates`,
`/knowledge-health`, `/blocked-analytics`, `/knowledge-runs/latest`.
The service is unit-tested; FastAPI itself is not installable here, so the
routes are compile-checked only.

## 10. Known limitations

* TF-IDF is lexical: polysemy and paraphrase are not handled; concept names
  are sometimes generic ("Features", "Introduction").
* Concept-level drift depends on cluster membership: e.g. "Stack" is ADDED
  (3 R22A topics) while R22 stack topics sit in "ADT Applications stack" —
  review before use.
* Course drift matches normalized titles only ("Data Structures" vs "Data
  Structures using C++" counts as REMOVED + ADDED).
* Continuation rows that pdfplumber does not detect as a table stay as
  layout text (most are labelled NOISE_LAYOUT_INTERLEAVED; some leak).
* The AICTE appendix syllabi (pp. 200–214) have no course codes and are
  quarantined, not analysed.
* No human has reviewed any concept; all labels used for evaluation are the
  assistant's.
