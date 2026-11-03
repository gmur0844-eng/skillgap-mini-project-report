# Final Report — Skill-Gap & Curriculum Drift Intelligence (Semantic Engine V3 release)

> **Historical report** (run `d658c97abebca9f5`), kept unchanged. The current release is `c066b227857f9eaf`, baseline `84d7737ccb8e4d87`: see [FINAL_RELEASE_REPORT.md](FINAL_RELEASE_REPORT.md).

**Final run:**
- Run id `d658c97abebca9f5`, pipeline `knowledge-engine-2.0.0`, code fingerprint `61177c817ea483bb`.
- Content digest `130548a2…f23b`. The run was repeated and the second run was byte-identical.

**Earlier reports:** `FINAL_REPORT_engine_2_0.md` and `FINAL_REPORT_engine_1_1.md`. Every earlier run is preserved.

**Evidence tags:**
- **[FACT]** read or counted from sources.
- **[MODEL]** model output.
- **[INFERENCE]** produced by a stated rule.
- **[HUMAN]** human validation. None exists.
- **[INSUFFICIENT]** the data does not decide.

> The job-posting results describe the supplied job-posting dataset and are not necessarily representative of
> the entire labour market.

---

## 1. Executive summary

- **What the system does:** it decodes curriculum PDFs into courses, units, topics and concepts. It maps job-posting skills to the full ESCO taxonomy and measures coverage, gaps and drift. It issues deterministic, evidence-backed recommendations, all exposed through a tested API and a compiled Flutter app.
- **Semantic Engine V3** puts a local LLM (qwen2.5:7b on your Mac) behind a deterministic evidence validator and a safety gate that was declared in advance.
  - V3 removed the V2 systemic failure: taxonomy metadata is no longer used as evidence, and lexical-collision rejection went from 0.24 to 0.75.
  - Its committed precision on the development gold set is still only 0.54, so **the gate failed**. Model decisions are recorded and visible but have **no effect** on the taxonomy, demand, gaps or the graph.
  - This is the intended safe outcome, not a malfunction.
- **Status by area:**

| Area | Status |
|---|---|
| Curriculum and industry pipeline | Production-ready: health PASS, publish PASS, 0 integrity violations, reproducible |
| API | 44/44 routes runtime-tested |
| Flutter | 22 screens; analyze clean, tests pass, web build succeeds |
| Semantic AI | Operating in safe mode |

## 2. Architecture

RAW → BRONZE → SILVER → HEALTH GATE → GOLD → PUBLISH (PostgreSQL) → read-only API → Flutter.

- Every stage has a contract, a quarantine and provenance.
- The run id is a hash of the code, config, parser, backend and source hashes.
- The semantic layer is pluggable:
  - LIVE provider;
  - replay of a hash-verified recorded run;
  - deterministic fallback.
- See `ARCHITECTURE.md`.

## 3. Data sources

[FACT] The sources are:
- AICTE model curriculum (REFERENCE);
- CBIT R22 (PREVIOUS_VERSION, semesters I–IV);
- CBIT R22A (TARGET);
- 100 supplied Indian job postings (4 files, 2026-09-22);
- ESCO v1.2.1 (13,939 skills).

No peer-institution curriculum was supplied, so peer status is **PEER_DATA_NOT_AVAILABLE**. See `DATA_QUALITY_REPORT.md`.

## 4. Curriculum decoding

[FACT] Counts: 189 courses, 662 units, 8,935 topics (7,625 clean) and 1,453 subtopics, each with a document, course, unit and page.

New in this release: a generic **ATTRIBUTION_CONFLICT** quarantine. It caught 47 mathematics topics and 5 outcomes that had been carried onto a lab course because a syllabus header code was unreadable.

## 5. Tokenization

[FACT] The tokenizer uses Unicode-aware word boundaries with curly and modifier apostrophes. Contraction tails (for example "We’re" → "re") are no longer skills. Skill mentions fell from 1,016 to 1,006, and 7 regression tests cover the change.

## 6. Concepts

[MODEL: TF-IDF] 1,318 lexical concepts inside course families. Family silhouette is 0.108, so separation is weak. This is disclosed in `DATA_QUALITY_REPORT.md` §5.

## 7. Semantic Engine V3

**Inputs are separated into:**
- SOURCE EVIDENCE: SOURCE_TEXT, COURSE_TITLE, UNIT_TITLE, LEARNING_OUTCOME, JOB_TITLE;
- CONCEPT DESCRIPTION: ESCO_DESCRIPTION, ESCO_HIERARCHY, ESCO_RELATION;
- CANDIDATE-GENERATION METADATA: TAXONOMY_METADATA, NORMALIZATION_METADATA. This is shown to the model and labelled "not evidence".

**The model** answers the question "Does LEFT mean, represent, teach or require RIGHT in THIS context?". Every citation must name an item {ref, source_type, quote}. The definitions and the rule that containment is never hierarchy are in the prompt (`semantic_v3.py`).

## 8. Evidence Validator V2 (authoritative)

The validator is deterministic and overrides the model. It checks:

| Check | Rule |
|---|---|
| Reference exists | UNKNOWN_REF |
| Quote is non-empty | EMPTY_QUOTE |
| Quote occurs in the cited item | QUOTE_NOT_IN_ITEM |
| Source type comes from our item, not from the model | SOURCE_TYPE_MISLABELLED |
| Metadata is never evidence | METADATA_CITED |
| Definite answers need source evidence | NO_SOURCE_EVIDENCE |
| Meaning relations also need concept evidence | NO_CONCEPT_EVIDENCE |
| Alias SAME_CONCEPT needs SOURCE_TEXT or JOB_TITLE | ALIAS_SAME_CONCEPT_WITHOUT_SOURCE_TEXT |
| PARENT/CHILD need a stated direction | NO_DIRECTION_JUSTIFICATION |

Outcomes are MODEL_SUPPORTED, MODEL_SUGGESTED, INSUFFICIENT_EVIDENCE or REVIEW_REQUIRED.

## 9. Qwen run (qwen-270-v3)

[FACT] Model and scale:
- qwen2.5:7b-instruct (Q4_K_M) on Ollama 0.34.4, MacBook Air M5.
- 283 frozen candidates: the 270-candidate pool plus 13 diagnostics.
- 50 min total; mean latency 10.6 s, p95 15.1 s.

[FACT] Quality of the run:
- 100% schema-valid.
- Consistency on re-ask: 20/20 same relationship, 17/20 byte-identical.
- Validated states: MODEL_SUPPORTED 133, INSUFFICIENT_EVIDENCE 135, REVIEW_REQUIRED 11, MODEL_SUGGESTED 4.

## 10. Semantic evaluation (development only)

[MODEL vs development gold labelled by the assistant — NOT human] Benchmark v1 has 88 cases and was frozen before V3 existed.

| System | Agreement | Precision when committed | Coverage |
|---|---|---|---|
| Baseline | 0.00 | — | 0.00 |
| V2 raw | 0.35 | 0.38 | 0.92 |
| V3 raw | 0.51 | 0.52 | 0.99 |
| V3 validated | 0.32 | 0.54 | 0.59 |

Further measures:
- Collision rejection: 0.24 (V2) → 0.79 (V3 raw) / 0.75 (V3 validated).
- The model never predicts CHILD: 0 predictions against 12 gold CHILD cases.

Full per-class metrics and the confusion matrix are in `SEMANTIC_EVALUATION_REPORT.md`.

## 11. Safety gate and promotion

The gate was declared in config before any V3 output existed. **Result: FAILED.**
- Alias SAME_CONCEPT support: 1, needed 8.
- Alias SAME_CONCEPT precision: 0.00.
- Lexical collisions supported as SAME_CONCEPT: 2, allowed 0.
- Alias UNRELATED precision: 0.846, needed 0.85.

Promotion states in the system:
- Decisions can be RULE_SUPPORTED, MODEL_SUPPORTED, MODEL_SUGGESTED, REVIEW_REQUIRED or HUMAN_VALIDATED.
- HUMAN_VALIDATED is never assigned to model output. It needs ingested human labels, and there are 0.
- Effects that did not happen because the gate failed:
  - 42 effects blocked;
  - 16 graph edges blocked;
  - 0 sense states changed.
- The database enforces `effect ⇒ MODEL_SUPPORTED`, and an integrity check that every ESTABLISHED_BY_MODEL mention has a decision behind it returns 0 violations.

## 12. Semantic replay

Decisions recorded on the Mac are replayed by exact cache key. The recorded file and the gate file are both SHA-256 verified, and `semantic_ai` is unchanged, so the cache key matches.

In the final run:
- 244 replayed.
- 30 REPLAY_MISS. Their topic-mapping contexts changed after the silver fix; they were recorded as not decided, with the model not called and no effect.

## 13. Industry intelligence

[FACT]
- Of 100 postings, 68 have at least one eligible skill.
- 1,006 skill mentions, of which 803 are established and 203 need a sense review.
- 106 skills are mapped to ESCO.
- 22/100 postings have an established occupation, and 64 titles are unmapped.

[INSUFFICIENT] Trends for all 115 skills (a single collection period).

## 14. Curriculum coverage

[INFERENCE] TARGET coverage levels across 115 demand skills:

| Level | Skills |
|---|---|
| SUBSTANTIAL | 10 |
| INTRODUCTORY | 13 |
| MENTION | 1 |
| ABSENT | 91 |

## 15. Skill gaps

[INFERENCE] Gap classification v2 across 115 skills:

| Classification | Skills |
|---|---|
| COVERED | 10 |
| PARTIAL | 13 |
| MISSING | 2 |
| INSUFFICIENT_EVIDENCE | 90 |

The 90 are insufficient because discipline relevance or industry support was not established with 100 postings.

## 16. Curriculum drift

**Concept level** [INFERENCE]:

| Category | Concepts |
|---|---|
| PERSISTENT | 283 |
| REWORDED | 185 |
| EXPANDED | 34 |
| REDUCED | 18 |
| ADDED | 46 |
| REMOVED | 18 |
| INSUFFICIENT | 160 |

RENAMED, MERGED, SPLIT and EVOLVED are INSUFFICIENT_EVIDENCE at concept level, with the reason recorded.

**Course level** (new: topic-match lineage):

| Status | Courses |
|---|---|
| RETAINED | 12 |
| RETAINED_RECODED | 6 |
| EVOLVED | 4 |
| ADDED | 15 |
| REMOVED | 14 |

The 4 EVOLVED pairs:
- Formal Language and Automata Theory → Theory of Computation
- Web Technologies → Web Programming
- DBMS → DBMS (new code)
- Data Structures → Data Structures using C++

No RENAMED, MERGED or SPLIT was detected. The lineage thresholds are not calibrated against labels.

## 17. Peer benchmarking

**PEER_DATA_NOT_AVAILABLE.** The IIT curriculum was requested but not supplied, and is listed in the manifest as NOT_SUPPLIED. The comparison shown is against the AICTE REFERENCE curriculum only, and it is labelled that way.

## 18. Recommendations

[INFERENCE] Recommendations are deterministic rules over the gap, support and coverage:
- 1 recommendation: SQL, EXPAND_EXISTING_TOPIC in 4 named courses, with rule reasons and uncertainty.
- 114 suppressed, each with coded reasons.
- `is_source_evidence` is always false.
- LAB and PROJECT rules are NOT_IMPLEMENTED. OUTDATED needs trends.

## 19. Knowledge graph

[FACT] 10,331 nodes and 15,689 edges.
- Consistency checks: 0 contradictions, 0 cycles, 0 dangling edges, 0 duplicates.
- Reported but not errors: 376 one-way parent/child mappings and 51 non-symmetric SAME_AS.
- Model edges enter the graph only when the gate passes. This release has 0.

## 20. Database

- PostgreSQL 16. Tables are additive and run-scoped (`skill_run`, `skill_mention_run`).
- New columns: `validated_state`, `validation_findings`, `effect`, plus a check constraint.
- A fresh publish passed, a republish inserted 0 rows, and integrity violations are 0.

## 21. API

**44/44 GET routes passed** on FastAPI 0.141.1 with a real uvicorn server on the Mac. Unknown ids never produce fabricated records. See `API_VALIDATION_REPORT.md`.

## 22. Flutter

22 data-driven knowledge screens plus 5 ingestion screens.
- `flutter analyze`: clean.
- `flutter test`: 3/3 pass (the tests found and fixed a real setState defect).
- `flutter build web`: OK.

See `FRONTEND_VALIDATION_REPORT.md`.

## 23. Tests and generalization

- **542 Python tests pass** across 41 modules. New modules cover lineage, attribution conflict, the promotion gate and replay hit/miss.
- The static generalization audit finds **0 forbidden executable conditionals**. The 8 literal hits are in a seed script's discipline descriptions, as data.
- There is no CBIT, CSE, skill, company or course-code logic in the engine.

## 24. Reproducibility

- Two consecutive full runs gave the same run_id and content digest; 63/63 files are identical.
- The semantic replay was identical: 244 hits, 30 misses, 0 model calls.
- See `REPRODUCIBILITY_REPORT.md`.

## 25. Limitations

- Model precision is too low for authoritative mappings, and the model is blind to hierarchy (CHILD).
- There are no human labels; the benchmark is assistant-labelled and its labeller saw V2.
- 100 postings from a single period: most gaps are INSUFFICIENT and there are no trends.
- Course families are weakly separated.
- The lineage thresholds are uncalibrated.
- One discipline and one institution.
- No peer data.
- 30 replay misses.
- The Flutter app was not click-tested against the live API.

## 26. Next steps

1. **Human labels.** A reviewer labels the 88-case benchmark independently (`HUMAN_VALIDATION.md`). This gives real precision numbers.
2. **A stronger model or a V4 prompt.** Try a larger or less quantised model, or a V4 prompt, evaluated on a NEW frozen benchmark v2. Never re-gate on v1.
3. **More data.** More postings over several periods would enable trends and lift INSUFFICIENT gaps. Supply the IIT curriculum for peer benchmarking.
4. **Re-run the 30 replay misses** live on the Mac as a new run id.

---

## Final acceptance checklist

| Requirement | Result |
|---|---|
| Immutable pre-V3 backup | ✔ `artifacts/archive/pre-v3/` |
| Unicode/apostrophe fix plus regression tests | ✔ |
| Frozen development benchmark (marked, not human) | ✔ sha 94b4e79c… |
| V3 separates evidence, concept and metadata; explicit source types | ✔ |
| Evidence validator authoritative over the LLM | ✔ |
| V3 run on the same frozen candidates, sequential, cached | ✔ 283/283 |
| BASELINE / V2 / V3 evaluated, labelled development-only | ✔ |
| Safety gate applied | ✔ FAILED, so no effects |
| Model output never HUMAN_VALIDATED; no silent taxonomy mappings | ✔ (DB constraint plus integrity checks) |
| Industry, coverage, gaps, drift, recommendations rebuilt | ✔ |
| Drift categories incl. RENAMED/MERGED/SPLIT/EVOLVED or INSUFFICIENT | ✔ course level implemented; concept level INSUFFICIENT with reason |
| Peer: PEER_DATA_NOT_AVAILABLE when absent | ✔ |
| Graph holds validated relationships only | ✔ |
| FastAPI runtime-tested | ✔ 44/44 |
| Flutter 20+ screens, real data, no placeholders, compiled | ✔ 22 screens; analyze, test and build OK |
| Generalization audit: 0 forbidden conditionals | ✔ |
| Two full runs reproducible | ✔ |
| No fabricated data, labels or accuracy claims | ✔ |
