# Full consistency audit

Every headline number of the Overview was recomputed independently at each layer it passes through: GOLD files of
the run, the published PostgreSQL database, the API service, the label the UI shows, and the documentation. Each
difference was given exactly one classification and a cause. Fixes were made only where the classification was
`TRUE_BUG` or `DISPLAY_LABEL_PROBLEM`; scope differences were made explicit in the labels, not "corrected".

| | |
|---|---|
| Audit tool | `scripts/audit/full_consistency_audit.py` (`--run`, `--db`, `--out`) |
| Audited before the fixes | run `c8ecd067bb733f58`, database `skillgap_knowledge_improve` |
| Audited after the fixes | run `84d7737ccb8e4d87`, databases `skillgap_knowledge_final` (fresh) and `skillgap_knowledge_improve` (three runs) |
| Results | `data/evaluation/full_consistency_audit.json` (final run) · `full_consistency_audit_before_c8ecd067bb733f58.json` (first audit, kept unchanged) · `full_consistency_audit_c8ecd067bb733f58_final_audit_code.json` (old run, final audit code) |
| Classifications | TRUE_BUG · SCOPE_DIFFERENCE · DERIVED_METRIC · STALE_DOCUMENTATION · DISPLAY_LABEL_PROBLEM · ROUNDING_ONLY · EXPECTED_DIFFERENCE · UNRESOLVED |

## Result

| | before (c8ecd067) | after (84d7737c) |
|---|---|---|
| checks | 15 | 15 |
| inconsistent | **gaps (v2)** — DISPLAY_LABEL_PROBLEM · **recommendations** — TRUE_BUG · **graph in the database** — TRUE_BUG (found by the audit code of this release) | none |
| scope differences (labelled, not errors) | 5 | 5 |
| expected differences | 1 | 1 |
| stale documentation | 1 | 1 (annotated) |

## The Overview numbers, reconciled

| Overview figure | Value | What it counts (scope) | Other numbers you may see for "the same" thing | Classification |
|---|---|---|---|---|
| Target-curriculum courses | 113 | every course extracted from the TARGET document (CBIT R22A) | 79 = target courses with at least one clean topic (the scope of the peer benchmark); 189 = courses of all non-peer documents (TARGET 113 + PREVIOUS_VERSION 36 + REFERENCE 40) | SCOPE_DIFFERENCE |
| Target-curriculum topics | 4,426 | clean TARGET topics with page provenance | 8,935 = every extracted topic item of non-peer documents including noise (bibliography lines, fragments) | SCOPE_DIFFERENCE |
| Target-curriculum concepts | 1,093 | concept clusters that contain at least one TARGET topic | 1,318 = concepts across all non-peer curricula (the database's `concept_run`); 1,337 = the count of runs up to `d140f830ab26adeb`, before topic cleaning changed in `f173ee4fff47e2a6` | SCOPE_DIFFERENCE · STALE_DOCUMENTATION (annotated) |
| Industry postings | 100 | distinct eligible postings of population CURRENT_JOB_DATASET_2026_09 (India, one week) | — (GOLD = DB = API = UI) | consistent |
| Normalized industry skills eligible for analysis | 120 | normalized skills eligible for analytics | 357 = all normalized skills; 115 = demand rows (5 eligible skills occur only as qualifications: computer science, computer technology, electrical engineering, fine arts, think innovatively); 106 / 101 = eligible / demand skills with an ESCO URI | SCOPE_DIFFERENCE |
| Evidence-supported gaps | 0 (was shown as 13) | PARTIAL or MISSING coverage **with SUPPORTED/HIGH_SUPPORT demand** | 13 = PARTIAL coverage (none with supported demand); 10 COVERED; 0 MISSING; 92 not enough evidence | was DISPLAY_LABEL_PROBLEM — fixed |
| Recommendations issued | 0 (was 1) | recommendations whose gap classifications agree | 1 = SQL, now *withheld for review* (below); 114 suppressed with coded reasons | was TRUE_BUG — fixed |

The demand denominator was checked separately: posting_count is the number of distinct postings with an established
SKILL mention; 29 skill/posting pairs mention a skill more than once and count once. No recomputation mismatch.

## Findings and what was done

### 1. Recommendation contradicted the gap classification — TRUE_BUG (fixed)

Recommendations are produced in the industry stage from gap **v1** (breadth: share of target courses that name the
skill). Gap **v2** (depth: direct/partial topics per unit) is computed later and was never fed back. For SQL, v1 said
PARTIAL (4 of 113 courses = 3.54 %) and produced `EXPAND_EXISTING_TOPIC`, while v2 said COVERED (SUBSTANTIAL: 2 direct
topics in 2 units). The Skill gaps and Recommendations screens therefore disagreed about the same skill.

Fix (`intelligence_stage.reconcile_recommendations`): after gap v2 is computed, a recommendation whose v2 class is not
PARTIAL/MISSING is moved to the suppressions with reason `CLASSIFICATION_CONFLICT_REVIEW_REQUIRED`, evidence status
`REVIEW_REQUIRED`, and both classifications plus the withheld action attached; evidence traces are updated. The API
lists it as `withheld_for_review`, and the UI shows it under "Withheld for review", never as an issued
recommendation. Nothing was decided on the reviewer's behalf: the candidate is kept, not deleted.

### 2. Headline gap figure described the wrong population — DISPLAY_LABEL_PROBLEM (fixed)

The headline 13 was PARTIAL (13) + MISSING (0), but the context line said "PARTIAL or MISSING with supported demand",
and none of the 13 has supported demand: v2 classifies PARTIAL/COVERED from curriculum depth alone. The number was
right; the sentence was false. Fix: the headline now counts evidence-supported gaps (0), and the context shows
covered / partial / missing / not-enough-evidence separately. The audit check is data-driven: it fails again if the
headline and the label ever disagree.

### 3. Database lost most graph edges of later runs — TRUE_BUG (fixed)

`knowledge.concept_relationship` had a primary key on `edge_id` alone. Edge ids are content-derived and repeat across
runs, so publishing a second run into the same database silently dropped the colliding edges: run `c8ecd067` has
15,689 edges in GOLD and 115 in the database. Fix: primary key `(run_id, edge_id)`
(`backend/app/db/knowledge_schema_consistency.sql`, idempotent; Alembic migration `0004_consistency_schema`).
Verified: the database `skillgap_knowledge_improve` now holds 15,689 edges for `405319df`, 15,689 for the final run
`84d7737c`, and still 115 for `c8ecd067` — that historical load is kept as it was published, not rewritten.

### 4. Two trend vocabularies — EXPECTED_DIFFERENCE

The v1 industry stage writes `INSUFFICIENT_EVIDENCE` at month granularity; v2 writes `INSUFFICIENT_DATA` after
trying week/month/quarter. Both mean "one period, no trend". The UI shows one human sentence for both: "Not enough
time periods for a trend".

### 5. Drift at two levels — SCOPE_DIFFERENCE

Course drift detects EVOLVED (4 courses, one-to-one topic-match lineage, MODEL_SUGGESTED). Concept drift does not
detect EVOLVED / MERGED / RENAMED / SPLIT; it reports ADDED / REMOVED / EXPANDED / REDUCED / RETAINED /
RETAINED_REWORDED / UNCERTAIN. This is a limitation of concept-level drift, stated on the drift screens; nothing was
invented to fill it.

### 6. Stale documentation — STALE_DOCUMENTATION (annotated)

`knowledge_engine.md`, `TOPIC_INTELLIGENCE.md`, `semantic_layer_engine1.md` and `KNOWLEDGE_GRAPH.md` quote 1,337
concepts and 10,394 graph nodes (runs up to `d140f830`). Each now carries a dated note naming the run its figures
describe and the current figures (1,318 / 1,093 concepts; 10,331 nodes, 15,689 edges). The text itself was not
rewritten; the release reports (`FINAL_REPORT_engine_*`) describe their own runs and were left untouched.

### Checked and consistent

Occupations (22 of 100 postings established; no title-contradicted posting is established), peer relations (4,067;
859 supported; 0 model-supported; peer topics never enter target concepts), semantic decisions (274 recorded, 0
applied, 42 effects blocked, 0 human-validated), topic mappings (4,426), postings, demand denominator.

## Three mapping problems, kept apart

The graph previously mixed three different mapping questions under shared relationship names. Every edge now carries
`mapping_kind` (GOLD, database column with a CHECK constraint, API, and the graph screen):

| mapping_kind | question it answers |
|---|---|
| TOPIC_TO_CONCEPT | which concept cluster does this topic belong to (clustering membership) |
| CURRICULUM_TO_REFERENCE | does a target topic correspond to a topic of a reference curriculum |
| SKILL_TO_TAXONOMY | which taxonomy (ESCO) concept is this industry skill |

plus DOCUMENT_STRUCTURE, TOPIC_HIERARCHY, PREREQUISITE, INDUSTRY_DEMAND, CURRICULUM_SKILL_MENTION, OCCUPATION,
TAXONOMY_HIERARCHY and SEMANTIC_DECISION. The semantic audit of the first three is in
[TOPIC_CONCEPT_MAPPING_AUDIT.md](TOPIC_CONCEPT_MAPPING_AUDIT.md).

## Changed outputs (run lineage)

`data/gold/knowledge/lineage/84d7737ccb8e4d87.json` (parent `c8ecd067bb733f58`): 10 of 79 outputs changed, 0 added,
0 removed — topic mappings (context gate), recommendations / suppressions / evidence traces / recommendation export
(reconciliation), graph edges, graph consistency and the intelligence report (`mapping_kind`, reconciliation report),
peer benchmark (ids). Two independent runs of the final code produced the same run id and content digest
(`ac31a3c5…`).

## Regression tests

`backend/tests/test_consistency_fixes.py`: context gate (4), recommendation reconciliation, schema key, edge kinds,
overview labels, withheld recommendations in the API, mapping-audit lookup, generalization audit;
`test_acquisition_recompute.test_integrity_sql_is_schema_aware`; Flutter: overview briefing, withheld candidates.
