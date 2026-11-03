# Final report — curriculum intelligence engine 2.0

> **Historical report** (run `438ec2c0d5182dd4`), kept unchanged. The current release is `c066b227857f9eaf`, baseline `84d7737ccb8e4d87`: see [FINAL_RELEASE_REPORT.md](FINAL_RELEASE_REPORT.md).

Final run **`438ec2c0d5182dd4`** · pipeline `knowledge-engine-2.0.0` · config `2.0.0` (hash `7415d76e…`) · code
fingerprint `9da5e152b40604b3` · content digest `70c46d9b…5807` · 93 s on 2 CPUs. Previous report (engine 1.1):
`FINAL_REPORT_engine_1_1.md`. All earlier GOLD runs are kept under `data/gold/knowledge/`.

Every statement below is tagged with its evidence class:
**[FACT]** read or counted from sources / runs · **[MODEL]** output of a model (here only TF-IDF, lexical,
uncalibrated) · **[INFERENCE]** computed by a stated rule · **[HUMAN]** human validation — **none exists** ·
**[INSUFFICIENT]** the data does not allow a conclusion.

The job-posting results describe the supplied dataset of 100 postings and are not necessarily representative of the
entire labour market.

---

## 1. Executive summary

* [FACT] The full ESCO v1.2.1 English classification (13,939 skills, 3,039 occupations, 640 skill groups, 619 ISCO
  groups, 126,051 occupation-skill and 5,818 skill-skill relations) is audited, integrated as the current taxonomy,
  and the delta is kept as change information. The audit found 25 duplicate concept rows (differing only in
  `modifiedDate`), 0 dangling references, 0 hierarchy cycles, and that the delta-only method had been treating **336
  ESCO skill groups as skills**.
* [FACT] Engine 2.0 adds: occupation mapping of postings (22 of 100 established), ESCO skill-type / hierarchy
  context, subtopic hierarchy, coverage relation and depth, gap classification v2, trend / lag states, semantic drift
  categories, peer benchmark, a checked knowledge graph (10,394 nodes, 15,731 edges), a model-provider layer with
  decision records and cache, 4 new API route groups (19 new routes), 11 new DB tables, 17 Flutter screens.
* [FACT] **No language model and no embedding model was available** (container and linked Mac inspected). All 270
  adjudication candidates got the deterministic rule verdict (`AI_PROVIDER_UNAVAILABLE`). Nothing is described as
  semantic understanding; similarity is lexical.
* [FACT] **0 human labels.** Nothing is human-validated.
* [FACT] Three real defects were found and fixed during this pass: a lexical false match ("Azure" → ESCO *SQL
  Server* via the label "Azure SQL Database"), run-dependent skill state stored on run-invariant DB rows, and
  structural labels ("Module II:", "Topics:") treated as parent topics.
* [FACT] 515 tests pass; static audit 0 forbidden conditionals; publish PASS on a fresh database, identical reload
  inserts 0 rows, and a second run in the same database also passes all integrity checks.
* [INFERENCE] The single recommendation is unchanged (SQL, EXPAND_EXISTING_TOPIC in 22CSC11N, 22CSE05, 22CSE32,
  22CSO02). The new depth rule classifies SQL coverage as SUBSTANTIAL → gap v2 COVERED; the two rules disagree and
  both are reported (§12).

## 2. Original problem

Decide, from evidence, which skills demanded in job postings a curriculum covers, how deeply, how the curriculum
changed between versions, how it compares with a reference curriculum, and what to change — without subject-specific
code, invented numbers or unvalidated claims.

## 3. Architecture

See `ARCHITECTURE.md`. RAW → BRONZE → SILVER → HEALTH GATE → GOLD (structure, concepts, skills/ESCO, industry,
intelligence, evidence) → PostgreSQL → FastAPI → Flutter. Stages that fail their gate produce no numbers.

## 4. Curriculum decoder

See `CURRICULUM_DECODER.md`. [FACT] 3 PDFs (527 pages), all health PASS; 189 courses, 662 units, 8,982 topic
fragments, 7,667 clean topics, course outcomes extracted and used as depth evidence (80 outcome mentions of demand
skills). Decoder code unchanged in 2.0.

## 5. Topic extraction

See `TOPIC_INTELLIGENCE.md`. [FACT] Subtopic hierarchy from explicit `Head: items` lines: 448 lines → 1,458
subtopics; 2,121 lines have no head (never split); 284 rejected by shape; **216 rejected as structural labels**. The
first version accepted "Module II:" and "Topics:" as parent topics (found while building the real-world cases); a
head used in ≥ 5 different courses is now a layout label. [FACT] That threshold was chosen after looking at this
corpus's head-frequency distribution (layout labels 8–16 courses, real topic heads ≤ 3) — stated, not tuned on labels.
[INSUFFICIENT] Hierarchy precision is not measured (no labels).

## 6. Concept intelligence

[MODEL] Unchanged: 24 course families, 1,337 TF-IDF concepts (3,302 topics). Topic / subtopic / concept / skill /
technology / ESCO skill / course are separate entities (`TOPIC_INTELLIGENCE.md`). [FACT] Concepts exist without
ESCO: e.g. the concept "Linked List" (11 topics, 22CSC05 and 22ITC20N) has no ESCO-mapped mention.
[INSUFFICIENT] No AI concept discovery ran (no model).

## 7. Semantic intelligence

See `SEMANTIC_INTELLIGENCE.md`, `SEMANTIC_ENGINE_COMPARISON.md`.
* [FACT] Providers probed: Ollama and OpenAI-compatible endpoints → connection refused; transformers not installed;
  sentence-transformers not installable (PyPI no distribution; huggingface.co 403 by egress policy, not retried).
  Linked Mac (names-only listing, no folder connected): no Ollama / LM Studio app, no model in the HF cache; the
  device shell cannot reach the Mac's localhost.
* [FACT] Adjudication: 270 candidates (alias sense 212, ambiguous taxonomy label 36, ambiguous topic mapping 22) →
  270 decision records `RULE_VERDICT_NO_MODEL`, cached (second run: 270 cache hits, 0 model calls).
* [FACT] Contract tested with a fake provider: invalid JSON retried; still invalid → `REVIEW_REQUIRED`; decisions
  never marked human-validated or confidence.
* [FACT] New generic rules: prefLabel precedence; containment rule (surface words ⊂ longer label → RELATED, not the
  same concept); a TF-IDF match to an alt/hidden label must pass the alias-sense rule.

## 8. ESCO integration

See `ESCO_INTEGRATION.md`. [FACT] Delta vs full: 9,298 delta-reconstructed concepts = 8,901 skills + 336 skill groups
+ 61 absent from the full files; 5,038 full skills were never matchable before; 565 labels the delta retires are still
listed by the full taxonomy (kept, reported as conflicts). [INFERENCE] skill-skill relation direction (related skill
is essential/optional for the original skill) is read from column order and the model definition.

## 9. Knowledge graph

See `KNOWLEDGE_GRAPH.md`. [FACT] 10,394 nodes (8,115 topic nodes, 136 subtopic nodes, 1,337 concepts, 189 courses, 357 skills, ESCO skills
and groups, 17 occupations, 22 postings), 15,731 edges (CONTAINS 7,856; MAPS_TO 3,408; PARENT_OF 1,682; CHILD_OF
1,678; MENTIONS 818; DEMANDED_BY 115; RELATED_TO 79; SAME_AS 53; APPEARS_IN 22; PREREQUISITE_OF 20).
Checks: 0 duplicates, 0 dangling, 0 self-parent, 0 cycles (PARENT_OF, PREREQUISITE_OF), 0 contradictions;
53 SAME_AS and 308 PARENT/CHILD edges without stored inverse — one-directional reference mappings, reported not
repaired. Relationships USED_BY / REPLACED_BY / EVOLVED_TO are **not produced** (no data).

## 10. Industry intelligence

* [FACT] 100 postings (4 files, 95 companies, all posted 2026-09-22), health PASS (after recording the baseline for the
  new taxonomy input).
* [FACT] 1,016 posting mentions: established 764, established by context 39, alias sense under review 212, acronym
  sense under review 1; 41 qualification-context mentions. 357 normalized skills (EXACT 62, NORMALIZED 43,
  SEMANTIC_MATCH 1, AMBIGUOUS 10, UNMAPPED 5, ALIAS_SENSE_REVIEW_REQUIRED 80, INSUFFICIENT_EVIDENCE 156); 120
  analytics-eligible; 106 ESCO-mapped. Skill types from ESCO: KNOWLEDGE 132, SKILL_COMPETENCE 53.
* [FACT] Demand rows 115: SUPPORTED 5 (customer service 5/5, SQL 5/5, quality standards 5/5, solve problems 6/6,
  azure 5/5 postings/companies), OBSERVED 20, INSUFFICIENT_EVIDENCE 90.
* [FACT] Occupations: EXACT 19, VARIANT 3, CANDIDATE 11 (not used), AMBIGUOUS 3, UNMAPPED 64; 17 distinct
  occupations; ISCO major groups: Professionals 10, Managers 6, Technicians 4, Clerical 2. Established skill
  occurrences inside the occupation's ESCO profile 9, outside 24. Only "2 Professionals" reaches the 10-posting
  minimum for within-group comparison. [INSUFFICIENT] Occupation-level demand for the other groups.
* [INSUFFICIENT] Trends: one monthly period → all 115 skills `INSUFFICIENT_EVIDENCE`; no EMERGING / GROWING /
  DECLINING claim.

## 11. Curriculum coverage

[INFERENCE] For the 115 demand skills (TARGET R22A): ABSENT 91, MENTION 1, INTRODUCTORY 13, SUBSTANTIAL 10, ADVANCED
0; PREVIOUS (R22): ABSENT 109, MENTION 3, INTRODUCTORY 3; REFERENCE (AICTE): ABSENT 108, MENTION 3, INTRODUCTORY 2,
SUBSTANTIAL 2. [FACT] Real example: SQL in R22A — "SQL: Data Types" DIRECT, "Object Based Extensions to SQL…"
PARTIAL, "SQL Injection" RELATED, "SQL Queries" RELATED. [FACT] The last one shows the rule's limit: "SQL Queries" is
about SQL but the label is a modifier, so it is counted RELATED (conservative). Thresholds heuristic, uncalibrated.

## 12. Skill gaps

* [INFERENCE] v1 (unchanged rules): MISSING 1, PARTIAL 24, INSUFFICIENT_EVIDENCE 90.
* [INFERENCE] v2 (depth-aware): COVERED 10, PARTIAL 13, MISSING 2, INSUFFICIENT_EVIDENCE 90. 11 changed: 10 PARTIAL →
  COVERED (e.g. machine learning 13 topics in 6 units; SQL 2 topics in 2 units), "ml" PARTIAL → MISSING (only
  RELATED/INCIDENTAL mentions). OUTDATED / EMERGING / MISALIGNED: 0 — no trend data, no MISALIGNED detector.
* [INFERENCE] v1 recommends expanding SQL; v2 calls SQL covered at SUBSTANTIAL (2 units ≥ threshold 2). Both are
  published; v2 has not replaced v1 because its thresholds are not validated.

## 13. Curriculum drift

[MODEL] R22 → R22A concepts: PERSISTENT 311, REWORDED 200, EXPANDED 44, ADDED 34, REMOVED 17, REDUCED 17,
INSUFFICIENT_EVIDENCE 159. [FACT] Courses: ADDED 19, REMOVED 18, RETAINED 12, RETAINED_RECODED 6. RENAMED / MERGED /
SPLIT / EVOLVED are **not detected** (no detector; stated in the output). [INSUFFICIENT] Curriculum–industry lag: all
115 `INSUFFICIENT_EVIDENCE` (versions are dated 2022-23 / 2024-25, but there is no industry trend).

## 14. Peer benchmarking

[INFERENCE] Only the supplied reference (AICTE UG CSE model) is benchmarked, no ranking: AICTE covers (≥ INTRODUCTORY)
one demand skill that R22A covers only by mention ("ml"); R22A covers 20 that AICTE does not (e.g. SQL, JavaScript,
DevOps, docker, kubernetes, NoSQL, project management). [INSUFFICIENT] IIT Bombay / Delhi / Madras / Kanpur curricula
were not supplied → **BLOCKED**; nothing is claimed about them.

## 15. Recommendations

[INFERENCE] 1 supported (SQL, EXPAND_EXISTING_TOPIC; evidence status INFERRED; is_source_evidence false); 114
suppressions with structured reasons. INTRODUCE_PREREQUISITE: 0 — SQL has no ESCO essential skill-skill relation.
INTRODUCE_LAB / INTRODUCE_PROJECT: **not implemented** (lab hours and projects are not extracted).
REDUCE_OUTDATED_CONTENT: 0 (needs trend data).

## 16. Evidence chains

`/api/v1/intelligence/evidence-trace?skill_key=…` returns posting → raw mention (span, context) → normalized skill →
ESCO (status, URI, method) → demand → curriculum topics per role with coverage relation/level → gap v1 and v2 →
recommendation or structured why-not; `/intelligence/why-not` and `scripts/evaluation/trace_skill.py` too. Ten
real-world cases: `data/evaluation/results/real_world_cases.md` (same concept via alias established by context;
explicit parent/child; context-dependent word "communication" in 55 postings; alias ambiguity "IT" → *computer
technology*, 14 mentions under review; concept without ESCO; SQL with ESCO; azure without ESCO; partial coverage "ml";
"Data types" across 7 courses; emerging over time → INSUFFICIENT_EVIDENCE).

## 17. Evaluation

See `EVALUATION_REPORT.md`. [FACT, assistant labels — not human] Mention sample (60): counted-as-demand accuracy
0.717 → **0.750** with the full taxonomy; SKILL precision 0.964 → 0.967, recall 0.628 → 0.674; mapped-sense accuracy
22/25 → 24/27. Decoder and mapping metrics unchanged. [INSUFFICIENT] ESCO mapping, occupation, coverage, hierarchy
accuracy: not measured.

## 18. Automated validation

[FACT] 515 tests (38 modules) pass; static audit 0 forbidden conditionals; ESCO integrity (0 dangling, 0 cycles, 1
self relation reported); graph checks (§9); hard cases: 1 of 16 conflated at taxonomy level (.NET → Visual Basic,
handled per mention), 13 held back by the label rule, "network"/"neural network" → PARTIAL (known weakness); SQL
integrity after publish: all checks 0. This is automated validation, not human validation.

## 19. Human validation

[HUMAN] **None.** v1 review set (54 items) remains frozen against engine 1.1; ingest now offers
`--frozen-outputs-only` so labels can still evaluate the v1 outputs. See `HUMAN_VALIDATION.md`.

## 20. API

[FACT] New routers (FastAPI, read-only, every response has `scope` + `evidence_state`):
`/api/v1/semantic/{concepts,relationships,decisions,evidence,contradictions,review}`,
`/api/v1/curriculum/{topic-hierarchy,coverage,drift,benchmark}` (plus existing `topics`, `concepts`, …),
`/api/v1/industry/{occupations,trends,skill-taxonomy}` (plus existing `demand`, `skills`, …),
`/api/v1/intelligence/{gaps,recommendations,why-not,evidence-trace,lineage,system-health}`.
[FACT] FastAPI is not installed in this container (PyPI blocked), so routes were not served here; the service layer
behind them is tested against the real run (`test_intelligence_service.py`), including NOT_PRODUCED for engine-1.1 runs.

## 21. Flutter

[FACT] `flutter_app/lib/screens/knowledge_screens.dart`: one data-driven screen type over 17 endpoint specs (System
Health, Curriculum Explorer, Topic hierarchy, Concept Explorer, Knowledge Graph, Industry occupations, Skill
Intelligence, Coverage Depth, Skill Gap v2, Curriculum Drift, Peer Benchmarking, Recommendations, Semantic Decisions,
Contradictions, Optional Human Review, Data Lineage, Industry Trends) plus the 5 existing screens; shows evidence
state, scope warning, and rows as returned; `null` shown as "—", never 0; placeholder screens removed.
**NOT TESTED: no Flutter SDK here** (storage.googleapis.com and pub.dev unreachable; github.com 403). Course Detail is
covered by filtering Curriculum Explorer, not a dedicated screen.

## 22. Data quality

[FACT] Document health PASS ×3; industry health PASS (12 checks); quarantine 1,135 records with reasons (mostly AICTE
appendix topics without course codes); 0 contract violations; provenance complete for all postings.

## 23. Reproducibility

[FACT] run_id = hash of pipeline version, parser/code fingerprints, config, backend, all source hashes; identical
reruns give the same content digest; model decisions cached by model/prompt/config/input/context hash. PostgreSQL:
the derived database was rebuilt (engine-1.x rows stored run-dependent skill state on run-invariant rows); fresh load
PASS, identical reload 0 rows, a second run in the same database PASS (run-scoped `skill_run`,
`skill_mention_run`). Commands: `python3 scripts/pipeline/run_knowledge_pipeline.py [--publish]`.

## 24. Limitations

* No LLM, no embeddings: all semantics are rules + TF-IDF + taxonomy. Word sense of single words is not resolved (held
  back instead): recall cost ("Java", "Python", "communication skills").
* 212 alias mentions wait for review; the full taxonomy's many altLabels ("IT", "AWS") make this queue large.
* Coverage relation uses label position: "SQL Queries" counted RELATED; "network" in "neural network" counted PARTIAL.
* Coverage and gap-v2 thresholds, and the structural-head threshold, are heuristic and unvalidated.
* One month of postings: no trends, no lag, no EMERGING/OUTDATED.
* 100 postings, 64 titles without an ESCO occupation; occupation comparison possible for one ISCO group only.
* `topic_hierarchy` in the DB is keyed by run-invariant ids, so it holds the union of published runs (the GOLD file is
  per run); `version control systems` → ESCO *control systems* remains a pinned known failure.
* Peer curricula other than AICTE not supplied; lab/project evidence not extracted; Flutter and FastAPI not run here.

## 25. Future work

Supply a model endpoint (Ollama or OpenAI-compatible) and set the model name — adjudication runs on the same cached
candidates; freeze a v2 review set and collect human labels (then calibrate thresholds on DEVELOPMENT only);
multi-period postings for trends and lag; parse L-T-P hours; add IIT curricula; run-scope `topic_hierarchy`; compile
and test the Flutter app.

---

## Final acceptance checklist

| Item | Result |
|---|---|
| Supported PDFs structurally parsed; course/unit/topic hierarchy; provenance | ✔ (3 PDFs) |
| Topic fragments → concepts; concepts separate from skills, technologies, courses | ✔ (lexical concepts) |
| Context changes interpretation | ✔ rules (alias/acronym sense, qualification context, label position); no model |
| Parent/child/related work; same concept, different wording resolved | partial — explicit hierarchy + TF-IDF tiers; paraphrase only via ESCO aliases |
| Lexical collisions rejected | ✔ (label rule, containment rule, alias rule; one pinned failure) |
| Full ESCO integrated; hierarchy; occupation-skill relations; aliases context-validated | ✔ |
| Concepts without ESCO exist | ✔ |
| Postings "semantically understood" | ✘ — lexical + taxonomy + rules only; not claimed |
| Coverage concept-aware; demand scope-aware; drift concept-aware | ✔ / ✔ / ✔ (lexical concepts) |
| Peer benchmarking | partial — AICTE only; IIT BLOCKED |
| Gaps evidence-based; emerging/outdated only with evidence | ✔ / ✔ (none claimed) |
| Recommendations evidence-grounded; evidence chains; why-not | ✔ |
| Human validation optional; works without labels; without embeddings | ✔ |
| AI model used if available; outputs schema-validated; cannot become evidence | ✔ implemented + tested with a fake provider; no model was available |
| Graph consistency checked; no subject-specific rules | ✔ |
| Works across disciplines | not demonstrated (one discipline supplied); no discipline logic in code |
| PostgreSQL idempotent; APIs return real data | ✔ / service layer ✔, HTTP not served here |
| Flutter exposes real intelligence; no fake values | implemented, **not tested** |
| Full tests pass; real pipeline completes; report accurate | ✔ |

## COMPONENT | STATUS | EVIDENCE | LIMITATION

| Component | Status | Evidence | Limitation |
|---|---|---|---|
| Curriculum decoder | COMPLETE | 3 PDFs PASS; golden pages recall 1.0 (assistant labels) | no OCR; L-T-P not parsed |
| Subtopic hierarchy | PARTIAL | 1,458 subtopics; structural heads rejected | precision unmeasured; heuristic threshold |
| Concept discovery | PARTIAL | 1,337 TF-IDF concepts | lexical; no AI discovery |
| Full ESCO integration | COMPLETE | audit + store + integrity + tests | relation direction inferred |
| ESCO delta change tracking | COMPLETE | 2,251 labels annotated; 565 conflicts reported | — |
| Alias / acronym sense validation | COMPLETE | 212 + 1 mentions to review | recall cost |
| Occupation mapping | PARTIAL | 22/100 established | 64 unmapped titles; accuracy unmeasured |
| Coverage relation / depth | PARTIAL | levels for 115 skills × 3 documents | position heuristic; unvalidated thresholds |
| Gap classification v2 | PARTIAL | 115 gaps, 11 changed vs v1 | MISALIGNED not detected; disagrees with v1 on SQL |
| Industry trends / lag | BLOCKED | single-period data | needs ≥ 2 periods of ≥ 30 postings |
| Semantic drift categories | PARTIAL | 7 categories produced | RENAMED/MERGED/SPLIT/EVOLVED not detected |
| Peer benchmarking | PARTIAL | AICTE compared | IIT curricula not supplied |
| Recommendations (new types) | PARTIAL | INTRODUCE_PREREQUISITE rule (0 fired) | LAB/PROJECT not implemented; OUTDATED needs trends |
| SemanticModelProvider + decision records + cache | COMPLETE | 270 decisions; contract tests | no model available to run |
| LLM / embedding semantics | BLOCKED | probes: refused / not installed / 403 | environment |
| Knowledge graph + consistency | COMPLETE | 15,731 edges, checks 0 violations | inverses of one-way mappings not stored |
| PostgreSQL (additive tables, idempotency) | COMPLETE | fresh PASS, reload 0 rows, multi-run PASS | topic_hierarchy not run-scoped |
| API routes | PARTIAL | service layer tested on real run | FastAPI not installable here, routes not served |
| Flutter screens | PARTIAL | 17 data-driven screens written | not compiled or run (no SDK) |
| Human validation | NOT IMPLEMENTED (by design: needs a human) | 0 labels; tooling ready | — |
| Evaluation | PARTIAL | assistant-labelled samples | no human labels; several metrics NOT MEASURED |
| Generalization | COMPLETE | static audit 0; hard-case conditional test | only one discipline's data available |
