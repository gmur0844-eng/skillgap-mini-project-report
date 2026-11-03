# Intelligence Improvement Release Report

> **Historical report** (run `c8ecd067bb733f58`), kept unchanged. The current release is `c066b227857f9eaf`, baseline `84d7737ccb8e4d87`: see [FINAL_RELEASE_REPORT.md](FINAL_RELEASE_REPORT.md).

| | |
|---|---|
| Baseline (parent, unmodified) | `5e2416e1ac2aa587` — code `13a3319b8eba1829`, digest `c23b2ec2…` |
| Final run (this release) | **`c8ecd067bb733f58`** — code `296bab4b76d47d8b`, config `70bf7d86…`, digest `a2918c174bae8706…` (see `artifacts/improvement_reproducibility.json`) |
| Intermediate run (kept) | `405319dfefb7f76c` — identical analytics; superseded because a verification-only change to `db_publish.py` changed the code fingerprint |
| Published database | `skillgap_knowledge_improve` (container) — publish PASS, 0 integrity violations; the baseline database `skillgap_knowledge` is untouched and still verifies PASS |

## 1. Summary

The release adds four intelligence layers, an evidence-acquisition and recomputation flow, and a redesigned Flutter frontend. It does this without rewriting working components and without changing any baseline output except where a change is intended and documented (§14).

**What the data supports today:**

- **Peer benchmarking:** PARTIAL. Two official peer curricula (IIT Kanpur, NIT Warangal) are decoded by the generic decoder and compared semantically; four requested peers are missing, each with a reason.
- **Temporal trends:** INSUFFICIENT_DATA. The one posting population spans a single day. The system says what is missing instead of drawing trends.
- **Occupation resolution:** 22 of 100 postings have an established ESCO occupation.
  - 21 by title, 1 by skill context.
  - 1 title match was contradicted by the posting's own skills and rejected.
  - The rest are CANDIDATE / AMBIGUOUS / UNMAPPED / INSUFFICIENT_EVIDENCE.
- **Semantic AI:** the machinery for independent evaluation is complete and gate v2 is declared. There are 0 independent labels, so the status is `PENDING_INDEPENDENT_LABELS` and the model stays in **SAFE_MODE**. No accuracy is claimed.

## 2. Baseline audit and immutable archive (Phase 0)

`artifacts/archive/baseline-5e2416e1ac2aa587/` is read-only. It contains:

- the GOLD tar;
- a code, config and docs tar;
- a semantic and evaluation tar;
- a database dump;
- `MANIFEST.json` with hashes, the baseline population and the regression status.

Release 5e2416e1ac2aa587 was not modified in place: every new output is a new run. All historical runs (`data/gold/knowledge/*`) are preserved. On the Mac, every file this release replaces is first copied to `artifacts/pre_improvement_backup_5e2416e1ac2aa587/`.

## 3. Dataset discovery (Phase 1) — `docs/DATASET_DISCOVERY_V2.md`

Each candidate source is classified USE / HOLD / REJECT with its licence, period, volume and fields.

- **Postings:**
  - no open, multi-period, posting-level India dataset was found;
  - the supplied snapshot is **USE** as population `CURRENT_JOB_DATASET_2026_09`;
  - NCS and Naukri JobSpeak are HOLD, as aggregate context only;
  - Hugging Face scrapes and mirrors are REJECT;
  - Jooble and Adzuna are HOLD, as registered but disabled connectors.
- **Peer curricula:**
  - NITW 2024-25 and IITK CoS 2024 are **USE** (official, topic-level);
  - IIT Madras and IIT Bombay 2022 are REJECT (codes and credits only);
  - IIT Delhi, NIT Trichy and others are HOLD.
- **Occupations:**
  - ESCO v1.2.1 occupation–skill relations are **USE**;
  - NCO-2015, O\*NET 31.0 and the ESCO–O\*NET crosswalk are HOLD.
- **No Kaggle.** Nothing was fabricated.

## 4. Industry and temporal intelligence (Phases 2–4)

- **Populations:** every posting belongs to an explicit population (`population_id` and definition in the source manifest). Populations are never merged, and India and non-India data are never mixed.
- **Denominator:** distinct eligible postings, with a skill counted once per posting.
- **Periods:** week, month and quarter are each evaluated.
  - A period qualifies with ≥ 30 eligible postings.
  - A trend needs ≥ 2 qualifying periods.
  - Per skill: ≥ 5 postings, change ≥ 5 pp and ≥ 25 % relative, and monotonic across periods. PERSISTENT means ≥ 10 % in every period.
  - Possible states: TRENDING_UP / TRENDING_DOWN / STABLE / EMERGING / DECLINING / PERSISTENT / INSUFFICIENT_DATA.
  - A missing value is `None`, never 0.
- **Segmentation:** occupation group, region, seniority and industry domain. Each segment is gated separately, and overall, occupation, geographic and temporal demand are kept separate.
- **Final run:** one qualifying period (2026-W39, 100 postings), so the population is `INSUFFICIENT_DATA` and all 115 skills are INSUFFICIENT_DATA. The `missing` block states what exists, what is required, why it matters, and which sources could provide it.
- **Industry intelligence per posting** covers occupation, industry, location, seniority, employment type and time distributions, plus mention-vs-posting counts.
- **Skill clusters** are co-occurrence associations (lift ≥ 2, ≥ 3 co-occurring postings) and never mean "same skill". In the final run 0 clusters pass, from 25 eligible skills.
- **Dashboard:** every trend view shows the date range, population, posting count, geography, occupation scope and evidence sufficiency. There is no unexplained arrow.

## 5. Peer curriculum benchmarking — semantic (Phases 5–7, 7B)

**Decoder.** Peers go through the generic decoder, with no institution branches. The added rules are generic:

- two more course-code shapes;
- "1st Semester" style headings;
- course-articulation-matrix handling;
- headerless course-row tables;
- L-T-P/credit rows;
- document-vocabulary rejoining of split words;
- a rule keeping single-occurrence courses that have ≥ 5 own topics.

The three baseline documents decode **byte-identically** (`BASELINE_SILVER_IDENTICAL`).

| Peer | Courses | Clean topics |
|---|---|---|
| NITW | 116 | 4,932 |
| IITK | 120 | 4,299 |

Peers are excluded from every target analytic (integrity check `peer_topics_in_target_analytics = 0`).

**Status.** `PEER_DATA_PARTIAL`. The badge sits at the top of the page and lists:

- the available peers, with version, year, source URL and retrieval date;
- the missing peers (IIT Bombay, IIT Delhi, IIT Madras, NIT Trichy), each with a reason;
- how to add a peer.

**Comparison rules.**

- Candidates are generated by topic-level TF-IDF plus shared DIRECT ESCO skills.
- A pair's relationship is one of SAME_CONCEPT / PARENT / CHILD / RELATED / PARTIAL_OVERLAP / UNRELATED / AMBIGUOUS / INSUFFICIENT_EVIDENCE, with evidence state SUPPORTED / MODEL_SUPPORTED / MODEL_SUGGESTED / REVIEW_REQUIRED / AMBIGUOUS / INSUFFICIENT_EVIDENCE.
- Shared words, title similarity, ESCO alias, containment or abbreviation are **never sufficient on their own**. SUPPORTED equality needs specific wording (≥ 2 content words) plus calibrated course context.
- Course context is the cosine similarity of topic text (titles excluded), with threshold 0.12. It was calibrated on course pairs of known identity: the lowest threshold with FPR ≤ 0.1 %, giving TPR 0.74 on 31 positives and 18,075 negatives. The Youden optimum would have been 0.06 (`artifacts/calibration/peer_course_context.json`). This is disclosed as a precision-first choice.
- "Network Security" is never matched to "Computer Networks" (a regression test).
- Qwen is not consulted for peer relations in SAFE_MODE. A relation where the model was consulted can never be SUPPORTED (database CHECK constraint).

**Coverage levels** are separate measures, never collapsed and never ranked. Values are for the target curriculum, CBIT R22A:

| Comparison | Exact lexical | Semantic concept | Semantic related | Review required | Skills shared / target | Depth (same / target deeper / comparison deeper) |
|---|---|---|---|---|---|---|
| NITW (peer) | 6.34 % | 4.67 % | 28.36 % | 40.26 % | 18 / 69 | 6 / 2 / 1 |
| IITK (peer) | 4.29 % | 1.46 % | 11.07 % | 47.12 % | 17 / 69 | 5 / 3 / 2 |
| AICTE (reference) | 2.68 % | 2.01 % | 18.48 % | 36.14 % | 13 / 69 | 2 / 1 / 0 |

**Relations and differences.**

- 4,067 relations. 859 are SUPPORTED: 91 SAME_CONCEPT, 767 RELATED and 1 PARTIAL_OVERLAP. The remaining 3,208 are REVIEW_REQUIRED (mostly AMBIGUOUS).
- Every comparison shows its evidence: topic text, page, course, course-context value and rule.
- Factual difference lists: shared, target-only and comparison-only concepts and skills, and depth differences.
- Industry alignment covers skills in demand that a peer teaches and the target does not, and the reverse.
- There is no "best university" score.

## 6. Occupation intelligence (Phases 8–9)

- **States:** EXACT / VARIANT / CANDIDATE / AMBIGUOUS / UNMAPPED / INSUFFICIENT_EVIDENCE.
- **Context support:** the posting's own skills are compared with ESCO occupation–skill profiles and recorded as CONFIRMED / NOT_ASSESSABLE / NEUTRAL / CONTRADICTED / NOT_CONFIRMED.
- **A title is not mapped when its context contradicts it.** For example, "Associate Process Manager" matches the ESCO alt label of *foundry manager*, but the posting's skills do not confirm it, so it is not established.
- **Final run:**

| State | Postings |
|---|---|
| EXACT | 18 |
| VARIANT | 3 |
| CANDIDATE | 11 |
| AMBIGUOUS | 4 |
| UNMAPPED | 19 |
| INSUFFICIENT_EVIDENCE | 45 |

  Established: 22 (21 by title, 1 by context). Title contradicted by context: 1.
- **Occupation-aware analysis:** demand, ESCO profile alignment with the target curriculum, and gaps per occupation and per ISCO group. Groups need ≥ 10 postings.
- **Evidence status:** `OCCUPATION_MAPPING = PARTIAL` (22 %, against the 50 % required).

## 7. Independent semantic AI evaluation (Phases 10–13)

See `docs/SEMANTIC_AI_EVALUATION_REPORT.md`.

- The 88-case benchmark is preserved and frozen.
- The pipeline is built: reviewer-blind export, label set, multiple reviewers, κ (Cohen / Fleiss), predefined adjudication, `semantic_gold_v1` freeze, and metrics (accuracy, macro P/R/F1, per class, confusion, error categories, baseline-vs-model 2×2).
- Gate v2 was declared before any independent label existed; the development preview was known and this is disclosed.
- Status: `PENDING_INDEPENDENT_LABELS` → SAFE_MODE. 274 decisions are recorded, 0 are applied, 42 are blocked by the gate, and 0 claim human validation.

## 8. Evidence acquisition and fallback (Phases 14–16)

- **Source Registry:** `data/metadata/source_registry.json`, with connectors for the drop folder with licence sidecar, credentialed APIs (disabled without a key; never faked) and local O\*NET files.
- **Escalation per requirement:** GOLD → SILVER → each registered source → model interpretation (never creates records) → human review → `INSUFFICIENT_EVIDENCE` reported.
- **New behaviour:**
  - `DUPLICATE_ACQUISITION` by SHA-256. Licence and provenance are checked first, so an unlicensed duplicate is still quarantined for its licence.
  - A peer requirement returns PARTIAL with the list of missing requested peers.
  - Curriculum registration keeps `retrieved_at` and `licence_note`.
  - Job files get a `population_id`.
- **Final evidence status:**

| Requirement | Status |
|---|---|
| TEMPORAL_TREND | PARTIAL |
| PEER_BENCHMARK | PARTIAL |
| OCCUPATION_MAPPING | PARTIAL |
| INDEPENDENT_SEMANTIC_LABELS | REVIEW_REQUIRED |

- The UI shows each of these states with the next action.

## 9. Automatic recomputation and provenance (Phases 17–18)

`scripts/acquisition/recompute.py` works in four steps:

1. Compare the sources now registered with those of the parent run.
2. Plan the affected analytics.
3. Rerun, creating a new run id; the parent directory is never touched. With `--new-run`, it can instead record an already produced run whose code fingerprint and sources match.
4. Write the lineage to `data/gold/knowledge/lineage/<new_run>.json`.

The lineage record holds: parent run, new run, source changes (with hashes), planned recomputation, code-fingerprint change, and changed outputs. Run ids and derived ids are normalised before comparing.

Lineage `5e2416e1ac2aa587 → c8ecd067bb733f58`:

- **Sources:** +2 (PEER), 0 removed, 0 changed; code changed.
- **Outputs:** 14 added, 6 changed, 59 unchanged, 0 removed.

Full provenance is kept per object: page, course, source sha256, method, thresholds and run.

## 10. Frontend (premium redesign)

See `docs/FRONTEND_REDESIGN_REPORT.md`. It covers the dark-first design system, the grouped collapsible shell with search, freshness and status, 12 redesigned screens, and loading, empty, error and not-produced states. Every original screen and test is kept.

## 11. Database and API

- **Schema:** `knowledge_schema_improvement.sql` plus Alembic `0003_improvement_schema`.
  - `document.role` now allows PEER.
  - New tables `peer_comparison`, `peer_relation`, `temporal_population`, `skill_trend` and `occupation_resolution`, each with CHECK constraints.
- **Integrity checks added:**
  - `peer_supported_without_context`;
  - `peer_relation_on_non_comparison_document`;
  - `trend_classified_without_temporal_evidence`;
  - `peer_topics_in_target_analytics`.

  All are 0. `dbtool verify` detects whether the improvement tables exist, so databases published before 0003 still verify with the base checks.
- **Rows published for the final run:** peer_comparison 3, peer_relation 4,067, temporal_population 1, skill_trend 115, occupation_resolution 100.
- **API:** `/api/v1/` gains `overview`, `search`, `peers/{status,benchmark,differences,relations,skills}`, `industry/{intelligence,temporal-trends,dimensions,clusters}`, `occupations/{resolution,analysis}`, `evaluation/semantic` and `lineage/recompute`.
  - Two names were chosen to avoid clashing with existing routes, which are unchanged: `industry/temporal-trends` and `lineage/recompute`.
  - `semantic/evidence` gains an additive `nodes` field with neighbour labels taken from the run's graph.

## 12. Tests and regression protection (Phase 19)

**Backend (container):**

- 582 function tests pass, 0 fail, 1 module skipped (FastAPI is not installed in the container; it runs on the Mac).
- 60 new unittest tests pass:

| Test file | Tests |
|---|---|
| peer decoder rules | 14 |
| temporal | 12 |
| semantic gold | 12 |
| peer benchmark | 8 |
| acquisition and recompute | 6 |
| occupation | 6 |
| replay-key stability | 2 |

- Plus a schema-aware integrity test and a graph-label test.

**Two tests were updated. Neither was weakened:**

- The migration head is now `0003`, and the test also asserts 0003 → 0002.

**Regression guards:**

- `BASELINE_SILVER_IDENTICAL` on all three baseline documents.
- The replay cache key is stable. The semantic-promotion config lives at the top level, because a key under `semantic_ai` once invalidated replay; a test pins this.
- The semantic decisions of the final run are identical to the baseline.
- Demand, gaps, recommendations, drift, graph and review outputs are unchanged (§14).

**Flutter:** 4 original and 13 new widget tests. The static validator passes: 23/23 screens, 22/22 new endpoints are real routes, and there are no placeholders.

## 13. Validation on the Mac (PostgreSQL 16, real FastAPI, Flutter)

_Filled in from `artifacts/mac_improve/` after `scripts/mac/improvement_mac_validation.sh`._

## 14. What changed versus the baseline

Output files compared with run ids and derived ids normalised:

| Output | Change | Why |
|---|---|---|
| `peers/*` (4 files), `industry_v2/*` (10 files) | added | new analytics |
| `health.json` | changed | two PEER documents are health-checked. They are WARN only because they have no regression baseline yet (first decode). |
| `quarantine.jsonl` | changed | +49 items, all from the peer documents |
| `intelligence/evidence_status.json`, `intelligence_report.json`, `intelligence/peer_benchmark.json` | changed | peer / temporal / occupation facts; the v1 benchmark status now says `PEER_DATA_PARTIAL` |
| `industry/evidence_traces.jsonl` | changed | **baseline bug fix.** The ESCO `taxonomy_scope` in traces was hard-coded as "PARTIAL_DELTA_SUBSET (ESCO v1.2.1 delta only)". It now comes from the mapping, which is `FULL_TAXONOMY` for this run (13,939 concepts reconstructed). |
| everything else (59 files) | unchanged | includes demand, gaps, recommendations, semantic decisions, drift, concepts, graph |

## 15. Reproducibility (Phase 20)

Two runs of the final code in the same container give the same run id `c8ecd067bb733f58` and content digest `a2918c17…`, and identical bytes for every GOLD file. The only exceptions are `run_report.*` and `observability.json`, which hold timings, and `publish_report.json`, which exists only for the published run.

Identity across platforms (Linux vs macOS) is **not** claimed.

## 16. Limitations, follow-ups and what is not claimed

- **No trends:** one day of postings. Trends need ≥ 2 qualifying periods of the same population.
- **Peers:** 2 of the 6 requested. IIT Madras and IIT Bombay publish codes and credits only; IIT Delhi and NIT Trichy are HOLD (see §3).
- **Semantic AI:** no accuracy until an independent reviewer labels the 88 cases; SAFE_MODE stays.
- **Skill clusters:** 0 pass the thresholds with 100 postings.
- **Occupations:** 22 % established; 45 postings have too little evidence.
- **Decoder follow-up:** "course contents" (plural) as a topics label was *not* added, because it would change the AICTE baseline decode (+32 topics). It needs a separately reviewed change.
- **Calibration:** threshold 0.12 is precision-first (TPR 0.74). The Youden optimum is 0.06.
- **Recompute diff:** `peers/peer_benchmark.json` lists example relations ordered by relation id, so two runs with different code fingerprints show it as "changed" even when the content is identical. This is cosmetic.
- **UX:** legacy database-backed screens (Data Sources, Ingestion, Pipeline Runs, Data Quality, Preprocessing) still render their own app bar inside the shell.
- **Distribution:** peer PDFs are official public documents without a licence statement. They are used for analysis with attribution and **not redistributed**, so they are excluded from the release zip.
- **Not claimed:** job postings, dates, trends, peer curricula or occupation mappings that the data does not contain; human labels; AI accuracy.

---

## Acceptance checklist (Phase 22)

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Baseline 5e2416e1ac2aa587 archived, not modified in place; history preserved | ✅ | §2, archive MANIFEST, new run ids only |
| 2 | Dataset discovery with USE/HOLD/REJECT | ✅ | DATASET_DISCOVERY_V2.md |
| 3 | Populations explicit; no mixing of geographies, periods, occupation populations or curriculum versions | ✅ | `population_id`; separate peer analytics; integrity 0 |
| 4 | Temporal analysis with week/month/quarter, thresholds, None ≠ 0 | ✅ | industry_v2; tests (12) |
| 5 | No trend without evidence; dashboard states what is missing | ✅ | INSUFFICIENT_DATA; "Temporal evidence required"; integrity `trend_classified_without_temporal_evidence` = 0 |
| 6 | Official peers through the generic decoder, no institution branches, baseline decode identical | ✅ | §5; BASELINE_SILVER_IDENTICAL |
| 7 | Peer benchmark only with peer evidence; no "best university" score; badge at top | ✅ | PEER_DATA_PARTIAL; UI test |
| 8 | Semantic (not lexical) peer relations with evidence; unsupported → REVIEW_REQUIRED | ✅ | §5; tests (8 + 14) |
| 9 | Occupation states; no title-only mapping when context contradicts | ✅ | §6; tests (6) |
| 10 | 88-case benchmark preserved; blind export; multi-reviewer; κ; adjudication; gold freeze; metrics | ✅ | §7; tests (12) |
| 11 | Promotion criteria declared before results; Qwen in SAFE_MODE unless the gate passes | ✅ | gate v2 sha pinned; 0 effects |
| 12 | Source registry, acquisition with fallback, UI evidence states | ✅ | §8 |
| 13 | Automatic recomputation with parent / source / new run and changed outputs | ✅ | lineage/c8ecd067bb733f58.json |
| 14 | Regression protection and new tests | ✅ | §12 |
| 15 | Two final runs, reproducible; no cross-platform identity claim | ✅ | §15 |
| 16 | Premium Flutter redesign; no fake data; existing screens and tests kept | ✅ (Mac validation §13) | FRONTEND_REDESIGN_REPORT.md |
| 17 | Nothing fabricated; no model result marked human-validated | ✅ | integrity checks; §16 |
