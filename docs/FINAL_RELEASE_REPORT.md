# Final release report — Skill-Gap & Curriculum Drift Intelligence

## Release candidate `0534d6e1d06a617f` (2026-10-10)

| | |
|---|---|
| **Release candidate** | **`0534d6e1d06a617f`**: code fingerprint `3e93f8153cad1edc`, parser `6d93cd03ca5098d9`, config `7668be94…`, semantic identity `REPLAY_VERIFIED_RUN · 8b81c19ed450357b · 1aa87473…` |
| Content digest (container reference build) | `1f4b2604d7c14e1cb435796181c6bcbcd3112a3bdd030a700ca3bf070166b7b8` |
| **Protected release** (unchanged, never regenerated) | **`c066b227857f9eaf`**: directory hash `305eb75bebb33a6b82e4c16124c9758b8d5f718c13a3f781041ed9246409855c` |
| Lineage parent | `c066b227857f9eaf` (`data/gold/knowledge/lineage/0534d6e1d06a617f.json`) |
| Canonical build platform | the owner's Mac (`scripts/mac/rc_validation.sh`); the container build of the same run id is the reproducibility reference |
| Release status | **MAC VALIDATION PENDING** (see the "Mac validation" table below). The candidate becomes the current release only when `rc_validation.sh` ends with `RC VERDICT: PASS`. Until then `c066b227857f9eaf` remains the current release. |

### What changed against `c066b227857f9eaf`

The release changes no analytical definition, threshold or evidence rule. Its changes are:

* **Phase 2 and 7 additions, validated earlier:**
  * the `programme_comparison` gate (NOT_APPLICABLE, in `health.json`);
  * the recommendation reasoning block (`intelligence/intelligence_report.json`, the new file
    `intelligence/recommendation_reasoning.jsonl`).
* **The five analysis agents' integration** (API `/api/v1/agents`, the Flutter screens "Analysis agents" and "Gap review
  (experimental)") and the Phase 4–6 experimental layers.
* **Phase 10.**
  * Live semantic decisions get their own cache namespace.
  * The model digest is part of the cache key.
  * The semantic identity is part of the run id.
  * The protected release is guarded.
* **Determinism fixes (2026-10-10)** for orders that previously depended on the NumPy build, the CPU or the run id:
  * family and segment names break exact TF-IDF ties by term (`semantic_backend.top_terms`);
  * `exports/concepts.csv` is written in `concept_uid` order;
  * review-queue related concepts are cut to six in (relation, name, uid) order;
  * peer candidates break equal similarities by topic order (`peer_stage`, a stable sort);
  * `industry/exports/recommendations.csv` lists suppressions by skill key instead of by a run-derived uid.
* **Replay hardening.**
  * A malformed replay registry entry is rejected (`replay_rejected`, with `missing_fields`) instead of raising.
  * `SEMANTIC_MODE=replay` is scoped to the pipeline and agent commands.
* **Reproducibility record.** `run_report.json` records the numeric environment: Python, NumPy, SciPy, scikit-learn,
  threadpoolctl and the BLAS libraries.

**Release comparison against `c066`** (`compare_runs.py`, container build): 68 files unchanged, 1 added, 11 changed.

* **All 21 authoritative metrics are identical:**
  * 498 postings from 106 companies;
  * 243 demand skills (41 HIGH_SUPPORT, 27 SUPPORTED);
  * gaps v2: 20 PARTIAL, 4 MISSING, 17 COVERED, 202 INSUFFICIENT_EVIDENCE;
  * 11 confirmed gaps;
  * 11 recommendations issued, 14 withheld for review, 218 not recommended;
  * 61 established occupations;
  * 1,318 concepts;
  * topic mappings.
* **The 11 changed files, explained:**

  | File | Change |
  |---|---|
  | `health.json`, `intelligence/intelligence_report.json` | Phase 2 and 7 additions |
  | `industry/exports/recommendations.csv`, `exports/concepts.csv` | Same rows, deterministic order |
  | `concept_families.jsonl` | 5 descriptive family names whose top-four terms were exact ties. Membership and uids are identical. |
  | `review_queue.jsonl`, `review_queue_high_priority.json` | Those family names, and the ordered related-concept lists |
  | `industry/segments.json` | 1 segment label tie ("pte ltd" → "glance inmobi"). Membership and sizes are identical. |
  | `peers/*` (3 files) | 4,940 → 4,791 peer relations. All 92 supported SAME_CONCEPT and PARTIAL_OVERLAP relations are identical. One review-required SAME_CONCEPT candidate ("Merge sort", NIT Warangal) became ambiguous; AMBIGUOUS 3,942 → 3,788; RELATED 770 → 776. Coverage percentages move by ≤ 0.1 points, and the supported same-concept coverage of every peer is unchanged. |

### Container validation of the candidate (2026-10-10)

| Check | Result |
|---|---|
| Backend tests (all 74 modules) | 867 passed, 0 failed, 1 skipped (`node` not on the test runner's path). Identical with `SEMANTIC_MODE=replay` exported in the parent shell. |
| Static Flutter check | 27/27 screens; 32/32 endpoints |
| Pipeline | exit 0, REPLAY_VERIFIED_RUN, publish PASS (fresh database) |
| Database integrity | PASS |
| Release gap QA | 0 held |
| Agents (`run_agents.py`) | COMPLETE. Outputs match the previous candidate's content, with only list order changing with the run id. |
| Protected release `c066` | unchanged (`305eb75b…455c`) |

### Mac validation (`bash scripts/mac/rc_validation.sh`)

PENDING: filled in from `artifacts/rc/validation.log` after the run on the Mac. Every check below is a release gate; the
script ends with `RC VERDICT: PASS` only if all of them pass.

| Gate | Result |
|---|---|
| Backend tests: no failures or errors (skips listed) | PENDING |
| Pipeline exit 0; database publish PASS; semantic mode REPLAY_VERIFIED_RUN | PENDING |
| Lineage recorded; agents COMPLETE | PENDING |
| Protected release c066 unchanged | PENDING |
| Cross-machine reproducibility gate (`reproducibility_gate.py`) | PENDING |
| Database dump, migration-cycle integrity, database integrity | PENDING |
| Release gap QA held=0 | PENDING |
| Flutter analyze, tests, web build | PENDING |
| Readiness READY with data HEALTHY; full API validation; Flutter data layer against the live API; agents endpoints | PENDING |

### Cross-machine reproducibility

The gate compares the Mac build with the container build of the **same run id** (same code, inputs, configuration and
semantic identity). Every GOLD file must be identical after run-id normalisation, except the outputs in
`scripts/audit/reproducibility_policy.json`:

* **Labels.**
  * descriptive family names (`concept_families.jsonl`, and `concept_family` in the review queue);
  * segment labels (`industry/segments.json`).
* **Peer relations.**
  * Only AMBIGUOUS and RELATED relations may change, by at most 5% (or 10) per peer curriculum, with at most a quarter
    of their records differing.
  * SAME_CONCEPT and every other relation must be identical record for record.
* **Peer benchmark (`peers/peer_benchmark.json`).**
  * Review-required and related counts, within the same count bounds;
  * their percentages, within ±0.5 points;
  * the capped example lists;
  * the peer concept count.

Any other difference fails the gate, and every allowed difference is listed in `artifacts/rc/reproducibility_gate.json`.
The previous Mac run (`a47ba76bfd6e24d9`) differed from its reference in 7 files. 3 were order defects, now fixed: family
names, `concepts.csv` order and the related-concept cut. The rest were the peer bounds above. Measured on those outputs,
the gate passes the peer changes and labels and fails the three order defects. It reports AMBIGUOUS relations moving by at
most 2.5%, and coverage percentages by at most 0.18 points.

**Numeric libraries.**

| | Container | Mac |
|---|---|---|
| Python | 3.11 | 3.14 |
| NumPy | 2.4.4 | 2.5.3 |
| SciPy | 1.17.1 | 1.18.1 |
| scikit-learn | 1.8.0 | 1.9.1 |
| BLAS | OpenBLAS (x86) | Apple Accelerate (arm64) |

The container versions publish macOS arm64 wheels for Python 3.14, so pinning them is possible, but it would not make the
peer outputs bit-identical:
* the macOS 14 wheels link Apple Accelerate, not OpenBLAS;
* even OpenBLAS uses different kernels on arm64 and x86.

The Mac keeps its validated `backend/requirements.lock`. The gate, not a pin, controls the difference.

### The five analysis agents

The agents are pipeline components with defined responsibilities, inputs and outputs, not five independent language
models. The language model (Qwen, via a verified replay) is advisory under Safe Mode in every agent.

| Agent | Authoritative layer (pipeline) | Experimental layer (`run_agents.py`) |
|---|---|---|
| 1 Curriculum Understanding | structure, topic hierarchy, concepts (`silver.py`, `concepts.py`) | course status and access (`curriculum_understanding.py`) |
| 2 Discipline-to-Industry Relevance | demand support and recommendation rules (`industry.py`) | programme relevance (`relevance.py`, run by `relevance_audit.py`) |
| 3 Skill Intelligence | extraction, ESCO mapping, demand (`industry.py`) | qualification and normalization (`skill_evidence_audit.py`, `skill_intelligence.py`) |
| 4 Skill-Gap Reasoning | gap classification v2 (authoritative) | gap states (`gap_reasoning.py`), shown as EXPERIMENTAL |
| 5 Curriculum Recommendation | existing-course-first recommendations and reasoning | none (runs inside the pipeline) |

API: `/api/v1/agents` (registry and output status per run) and `/api/v1/agents/gap-review` (experimental gap states
beside the authoritative classification). App: "Analysis agents" (System) and "Gap review (experimental)" (Evidence).

### Limitations stated plainly

* **Phase 9, NIRF comparison: INCOMPLETE.**
  * Missing: the NIRF Engineering ranking page, and the department syllabus PDFs of the institutions it names.
  * Neither the repository nor the Mac folder holds them; no `*nirf*` file exists.
  * No NIRF comparison is produced or claimed.
  * Peer benchmarking uses the 3 acquired official curricula (IIT Kanpur, NIT Warangal, NIT Tiruchirappalli).
* **Phase 11, independent human validation: INCOMPLETE.**
  * The blind 58-gap review set is prepared (`data/evaluation/gap_state_review_v1`).
  * No completed reviewer records exist: there are no reviewers, labels or agreement scores.
  * Nothing in this release is human-validated.
* **Industry trends: NOT ESTABLISHED.** The evidence is one snapshot period.
* **Peer coverage: PARTIAL.** 3 of 6 requested peer curricula.
* **Occupation mapping: PARTIAL.** 61 of 498 postings.
* **Transformer:** deferred and not implemented.

### Launch and demonstrate

```
cd ~/Sites/skillgap-final
bash scripts/mac/rc_validation.sh              # builds, validates and leaves the app running
open http://localhost:8000/app/                # the Flutter app
curl -s localhost:8000/ready                   # readiness
curl -s localhost:8000/api/v1/agents           # the five agents and their outputs for the run
bash scripts/mac/finalize_release.sh stage     # after RC VERDICT: PASS -- stage the source for review
bash scripts/mac/finalize_release.sh commit    # commit, then package the release zip (package_release.sh)
```

---

## Previous release `c066b227857f9eaf` (2026-10-02)

| | |
|---|---|
| **CURRENT RELEASE** | **`c066b227857f9eaf`** (content digest `b5d572db06f48d323b9e91e81e0ab6976c2b5ea19e2cff84d549c334bd029c8c`, code fingerprint `d2ca61a7b68aa478`) |
| **BASELINE** (previous verified release, unchanged) | **`84d7737ccb8e4d87`** (content digest `ac31a3c5332e0bab4072cdc55fe109205944b6ec38196d453d75eb9131166e45`) |
| Target curriculum | Chaitanya Bharathi Institute of Technology, B.E. Computer Science and Engineering, R22A (2024-25) |
| Date | 2026-10-02 |

Status words in this report:
* **VERIFIED**: checked on the release and passing.
* **PARTIAL**: present, with stated gaps.
* **PENDING**: prepared but not yet done.
* **NOT ESTABLISHED**: the evidence does not support a claim.

The validation and package-integrity results are in sections 15, 16 and 21. The release decision is at the end.

## 1. Executive summary

The system measures how far a university curriculum covers the skills employers ask for. Every conclusion traces back to a
job posting and a curriculum page.

The current release adds legitimately acquired industry evidence. 11 Indian employer job boards were read through their
publishers' documented public APIs. With them the release rests on:
* 498 eligible postings from 106 companies;
* 68 skills with enough demand to judge;
* 11 evidence-supported skill gaps and 11 recommendations;
* 3 peer curricula.

The release is reproducible: 3 builds gave an identical content digest.

What the release does **not** claim:
* industry trends, because the evidence is one snapshot period;
* complete peer coverage (3 of 6 requested);
* complete occupation mapping (61 of 498 postings);
* human-validated semantic relationships. The independent review is prepared but **PENDING**, and the AI layer is
  advisory.

## 2. System purpose

Universities revise curricula slowly; job markets move faster. The system answers four questions, each with its evidence:
1. Which skills do employers in the supplied posting population mention?
2. Where does the target curriculum teach them, and how deeply?
3. Where is coverage partial or missing while demand is supported?
4. What change is recommended, or why is it not?

It never ranks institutions, never invents data and never reports an inference as a source fact.

## 3. Architecture

* **Pipeline** (`backend/app/knowledge_engine`, engine `knowledge-engine-2.0.0`). Data flows RAW → BRONZE → SILVER →
  health gates → GOLD, one immutable directory per run (`data/gold/knowledge/<run>`):
  * curriculum PDF decoding, topic hierarchy and concept discovery;
  * industry posting ingestion, skill extraction, ESCO v1.2.1 mapping and demand;
  * coverage depth, gap classification v2 and recommendation reconciliation;
  * peer benchmark, course and concept drift, occupation resolution, the knowledge graph and evidence traces.

  A run is published to PostgreSQL 16 (schema `knowledge`, every row keyed by run).
* **API**: FastAPI, 87 GET routes in the validated set (`/api/v1/...`), each response scoped to a run and carrying the
  population scope.
* **Frontend**: Flutter (web), served at `/app/`, editorial design. Every page follows the order interpretation →
  evidence → explanation → technical details.
* **Reproducibility**: run id = f(code fingerprint, config hash, sources); content digest over all GOLD outputs; lineage
  record per run (`data/gold/knowledge/lineage/`).

Details: [ARCHITECTURE.md](ARCHITECTURE.md), [architecture_data_flow.md](architecture_data_flow.md).

## 4. Current evidence

| Evidence | Release c066b227 | Status |
|---|---|---|
| Target curriculum | CBIT R22A: 113 courses, 4,426 topics (plus the previous version R22 for drift) | VERIFIED |
| Reference curriculum | AICTE UG CSE model curriculum | VERIFIED |
| Peer curricula | IIT Kanpur, NIT Warangal, NIT Tiruchirappalli (official PDFs); IIT Bombay, IIT Delhi, IIT Madras not acquired | PARTIAL |
| Job postings | 498 eligible (100 from the supplied export, 2026-09-22; 398 from 11 employer job boards, snapshot 2026-10-01); 106 companies; India | VERIFIED |
| Skill taxonomy | ESCO v1.2.1 (13,939 skill concepts) | VERIFIED |

Source decisions and licences: [DATA_EXPANSION_AUDIT.md](DATA_EXPANSION_AUDIT.md), `data/metadata/official_sources.json`.

## 5. Industry intelligence

All figures below were read from the published database and GOLD (`data/evaluation/release_gap_qa_c066b227857f9eaf.json`).
GOLD and the database agree on every one.

| Measure | Value |
|---|---|
| Eligible postings | 498 (516 ingested; duplicates and ineligible rows removed by the health gates; duplicate rate 3.5 %) |
| Skill extraction yield | 0.90 of eligible postings have at least one analytics-eligible skill |
| Skills with demand | 243; **68 judgeable** (SUPPORTED 27 + HIGH_SUPPORT 41: ≥ 5 postings from ≥ 3 companies; high support ≥ 10 from ≥ 5) |
| Occupations | **61 of 498** postings resolved to an ESCO occupation (title and description context). The earlier title-only resolver gives 58; both are published. |
| Trends | **NOT ESTABLISHED**: each population has 1 qualifying period; a trend needs at least 2 |

Demand is *observed prevalence in the supplied and acquired postings*, not importance and not the labour market as a
whole. Every screen and API response carries that statement.

## 6. Curriculum intelligence

* Topic hierarchy decoded from the PDFs with page provenance.
* Concepts: 1,318, discovered by TF-IDF clustering, which is lexical, not semantic.
* Topic → reference mappings: 4,426, with a course-context gate.
* Coverage depth per skill: ABSENT / MENTION / INTRODUCTORY / SUBSTANTIAL / ADVANCED.
* Mapping audit: [TOPIC_CONCEPT_MAPPING_AUDIT.md](TOPIC_CONCEPT_MAPPING_AUDIT.md). The curriculum-side mappings are
  unchanged from the baseline.

## 7. Skill gaps

| Gap class (v2) | Skills |
|---|---|
| Covered | 17 |
| Partial | 20 |
| Missing | 4 |
| Not enough evidence | 202 |
| **Evidence-supported (confirmed)** | **11** |
| Held for review (supported demand, but a course title names the skill) | 2: data analytics, operating systems |

**Confirmed gap rule** (unchanged): partial or missing coverage, SUPPORTED or HIGH_SUPPORT demand, and no unresolved
disagreement in the evidence.

**Release QA** (`scripts/audit/release_gap_qa.py`). For each confirmed gap the full chain was re-derived from the
run's files and checked against the declared rules: posting → mention (span inside the posting text) → normalized
skill → taxonomy → demand counts and thresholds → curriculum evidence → class → evidence status → recommendation →
evidence trace (the API's own function). **All 11 satisfy the declared rules; none had to be held.**

| Skill | Eligible postings | Demand | Taxonomy | Curriculum coverage | Level | Gap | Evidence | Recommendation | Trace |
|---|---|---|---|---|---|---|---|---|---|
| make decisions | 498 | 89 / 5 companies (17.9 %)¹ | ESCO exact | 22CAO02, 1 span | MENTION | MISSING | INFERRED | issued | yes |
| SPARK | 498 | 26 / 5 (5.2 %) | ESCO normalized | 22CSE19, 2 spans | MENTION | MISSING | INFERRED | issued | yes |
| docker | 498 | 23 / 9 (4.6 %) | curated token (no ESCO label) | 22CSE25, 22ITE11, 9 spans | INTRODUCTORY | PARTIAL | INFERRED | issued | yes |
| lead others | 498 | 22 / 10 (4.4 %) | ESCO hidden label ("people management", "leadership skills") | none | ABSENT | MISSING | INFERRED | issued (elective) | yes |
| system design | 498 | 16 / 7 (3.2 %) | ESCO exact | 22ECO05, 2 spans | MENTION | MISSING | INFERRED | issued | yes |
| data models | 498 | 14 / 7 (2.8 %) | ESCO exact | 22CSC11N, 1 span | INTRODUCTORY | PARTIAL | INFERRED | issued | yes |
| node.js | 498 | 13 / 5 (2.6 %) | curated token | 22CSC42, 22CSO01N, 2 spans | INTRODUCTORY | PARTIAL | INFERRED | issued | yes |
| MySQL | 498 | 10 / 6 (2.0 %) | ESCO exact | 22CSC42, 1 span | INTRODUCTORY | PARTIAL | INFERRED | issued | yes |
| NoSQL | 498 | 10 / 5 (2.0 %) | ESCO exact | 22CSC42, 22CSE05, 22CSE28, 7 spans | INTRODUCTORY | PARTIAL | INFERRED | issued | yes |
| Agile development | 498 | 7 / 5 (1.4 %) | ESCO exact | 22CSC21N, 1 span | INTRODUCTORY | PARTIAL | INFERRED | issued | yes |
| financial analysis | 498 | 5 / 5 (1.0 %) | ESCO exact | 22MEO06, 1 span | INTRODUCTORY | PARTIAL | INFERRED | issued | yes |

¹ **Evidence-quality finding (not a rule violation).** 66 of the 89 postings mention *make decisions* only in one
sentence of an employer's standard text ("…our Leadership Commitment, guiding how and why we make decisions…"). That
sentence describes the employer's culture, not a skill requirement. Without it the skill still has 23 postings from 5
companies, which is still HIGH_SUPPORT, so the gap holds under the declared rules. But its displayed prevalence is
inflated about four times. The system has no declared rule for repeated employer text. Adding one now would change an
analytical definition, so it is documented here as a known limitation (section 18) and a next step instead. The other
10 gaps have no postings whose only evidence is repeated employer text.

## 8. Recommendations

**Counts:**
* 11 issued, each traceable to one of the 11 confirmed gaps.
* 14 withheld for review: two coverage measures disagree, or a course title names the skill.
* 218 not recommended, each with a coded reason.

**Status labels.** Recommendations are rule-based inferences (`is_source_evidence = false`). Status
`MODEL_SUGGESTED` means "inferred, not validated", and the UI now says exactly that (section 14).

| Skill | Action | Target courses | Support | Gap (class / level) | Notes |
|---|---|---|---|---|---|
| system design | expand existing topic | 22ECO05 | high | missing / mention | — |
| data models | expand existing topic | 22CSC11N | high | partial / introductory | — |
| SPARK | expand existing topic | 22CSE19 | high | missing / mention | — |
| make decisions | expand existing topic | 22CAO02 | high | missing / mention | population-dependent; boilerplate-inflated (section 7) |
| Agile development | expand existing topic | 22CSC21N | supported | partial / introductory | borderline support |
| lead others | add elective | — | high | missing / absent | population-dependent; absence is textual |
| MySQL | expand existing topic | 22CSC42 | high | partial / introductory | — |
| docker | expand existing topic | 22CSE25, 22ITE11 | high | partial / introductory | no ESCO label |
| node.js | expand existing topic | 22CSC42, 22CSO01N | high | partial / introductory | no ESCO label |
| financial analysis | expand existing topic | 22MEO06 | supported | partial / introductory | population-dependent; borderline support |
| NoSQL | expand existing topic | 22CSC42, 22CSE05, 22CSE28 | high | partial / introductory | — |

**Population-dependent recommendations.** *make decisions*, *lead others* and *financial analysis* follow from the
employer boards listing non-engineering roles (sales, finance, operations) alongside engineering ones.
* They are correct under the definitions.
* Each is stated against "N of the 498 eligible supplied postings… observed prevalence, not importance". The population
  statement is shown on Overview, Industry and Skill gaps.
* They are **not** CSE curriculum requirements in general. They need a curriculum committee's judgement before any
  action.
* The system did not mark them for review, and this release does not change that state in either direction. It is
  recorded here.

## 9. Peer benchmarking — PARTIAL

**Peers compared:** IIT Kanpur, NIT Warangal and NIT Tiruchirappalli, from official curriculum documents.

**Not acquired:**
* IIT Bombay and IIT Madras: their official documents list course codes and credits only, with no topics.
* IIT Delhi: only an institute-wide catalogue is available.

**Method:** each curriculum is compared on its own terms against the reference. There is no score and no ranking. Peer
topics never enter the target's analytics.

## 10. Curriculum drift

Course level, R22 → R22A:
* 15 added, 14 removed, 12 retained, 6 retained but recoded, 4 evolved.
* Lineage is shared-concept correspondence, not a statement of the institution's intent.

Concept level: evolved, merged, renamed and split concepts are **NOT ESTABLISHED** (not detected).

## 11. Semantic intelligence

* 336 AI decisions are recorded with their evidence. **0 are applied to analytics; 0 are human-validated.**
* The promotion gate (v3) was declared before any label existed and is unchanged.
* Semantic state: **AI INTERPRETATION IS ADVISORY** (SAFE_MODE).
* Deterministic rules decide every published result.

## 12. Human validation status — PENDING

* Formal state: `PENDING_INDEPENDENT_LABELS`. No reviewer responses exist; nothing in this release is human- or
  expert-validated.
* Frozen benchmark: 88 cases, sha256 `94b4e79c49bc…`, unchanged.
* Reviewer form: Google Apps Script `scripts/evaluation/create_semantic_validation_form.gs`.
  * 48 cases from the frozen subset.
  * Integrity verified: 0 missing, 0 duplicate, 0 modified, 0 invented.
  * The reviewer sees only: Reviewer ID, the case evidence, Concept A, Concept B, the relationship (A–H), confidence and
    optional reasoning.
  * The reviewer never sees: a prediction, expected answer, model confidence, benchmark result, the gate or any system
    decision.
* Files: [SEMANTIC_HUMAN_VALIDATION_FORM.md](SEMANTIC_HUMAN_VALIDATION_FORM.md),
  `data/evaluation/semantic_gold/computer-science-and-engineering/v1/form/`.

## 13. Explainability and evidence trace — VERIFIED

Every skill opens an **evidence thread**: postings (company, title, quoted text) → skill (demand support) → curriculum
courses and pages → coverage level → gap or decision.

* A link the data cannot establish says "Evidence is insufficient to establish this relationship."
* Checked live on the Mac release app (e.g. docker: 23 postings → 2 courses, 4 page spans → introductory → expand
  existing topic).
* All 11 confirmed gaps have a complete trace through the API function.

## 14. Frontend

Seventeen screens were inspected live on the Mac against the release.

**Correct:**
* System health states: Analysis **Ready**, Evidence **Available with limitations**, AI interpretation **Advisory**,
  Traceability **Complete**. SAFE_MODE and database internals sit only under technical details.
* Trends are shown as "Not established yet" with the evidence still needed.

**Defects found in the final inspection and fixed (display only; no data, definition or threshold changed):**

| Defect | Class | Fix |
|---|---|---|
| Every recommendation was badged "AI-suggested interpretation" (and so were concept, drift and mapping inferences), contradicting "AI interpretation is advisory" | A — release-blocking (honesty) | `MODEL_SUGGESTED` now reads "Inferred, not validated"; regression test |
| Data quality showed "Insufficient real data loaded yet — 0 postings, 0 courses" (it read the empty phase-1 tables) | A — release-blocking (false statement) | shows the run's validation checks (`/api/v1/curriculum/knowledge-health`) |
| Sources showed "No data sources registered yet" (the same cause) | A — release-blocking (false statement) | shows the source registry (`/api/v1/metadata/sources`); the phase-1 "Pipeline runs" view, also empty, was removed from More views |
| Skill gaps opened on the "Covered" filter (off by one) | B — cosmetic, materially confusing | opens on "Partial coverage", as the code intended |
| Occupations title showed a missing-glyph box ("→" absent from the display font) | B — cosmetic, visible | reworded "From job title to occupation" |

**Cosmetic issues left as they are:**
* The industry skill-demand bars are not sorted by demand.
* The curriculum drift page is a table, without the editorial layer.
* The representativeness sentence also appears on curriculum-only tables.
* "Preprocessing preview" (More views) belongs to the phase-1 job path and lists no jobs. It is kept because the
  ingestion review action links to it.

## 15. Testing

| Suite | Result |
|---|---|
| Backend on the Mac, real FastAPI / SQLAlchemy / Alembic stack (pytest) | **707 passed, 5 skipped**, 5 deprecation warnings (final run on the fixed build) |
| Backend function tests (container) | 582 passed, 1 skipped (FastAPI not installed there) |
| Backend TestCase suites (container) | 126 passed |
| Flutter analyze / test / web build (Mac) | **0 issues; 39/39 passed** (incl. the new status-wording test); **web build OK** |
| API validation (Mac, live) | **116/116** checks over 87 routes, incl. negative cases; migrations 0001 → 0005 PASS; database integrity PASS |
| Flutter data layer vs live API (Mac) | **49/49** screen specs, incl. the new Data quality and Source registry views |
| Static Flutter validation | 25/25 screen specs, 28/28 endpoint literals |
| Consistency audit | 15 checks, 0 inconsistent |
| Generalization audits | 0 discipline conditionals; 0 ranking logic |
| Course-title lookup regression | case-insensitive and prefix-tolerant: passing; 189 courses, no duplicate (document, code) records |
| Repository portability | no paths that collide on case-insensitive file systems |

**About the 5 Mac skips.** The validation script runs pytest with `-q`, which does not name skipped tests.
* Every skip in the suite is an environment check that reports as *skipped*, never as passed:
  * no local PostgreSQL role or database (backup/restore, migrations);
  * a source PDF absent;
  * FastAPI absent;
  * a live model endpoint reachable (replay);
  * `node` absent (form simulation);
  * no GOLD run.
* **Open warning:** the names of the exact five were not captured in this validation.
  `.venv/bin/pytest backend/tests -q -rs | grep SKIPPED` lists them.

**Upload workflow** (upload → ingestion → extraction → validation → analysis pending → current-run context, no stale
results, zero content never "succeeded"): verified by the Flutter workflow tests and the API negative cases. No upload
was made on the release instance, because an upload starts an analysis that adds a run to the release's GOLD.

## 16. Reproducibility — VERIFIED

| | Run A | Run B | Official build |
|---|---|---|---|
| Run id | c066b227857f9eaf | c066b227857f9eaf | c066b227857f9eaf |
| Content digest | b5d572db…bd029c8c | b5d572db…bd029c8c | b5d572db…bd029c8c |

**Differences:** none in content. Only `generated_at` and the run-report timings differ, and they are outside the digest.
A tie-ordering fix made the digests identical; before it, two runs with the same id had different digests
([DATA_EXPANSION_AUDIT.md §7](DATA_EXPANSION_AUDIT.md)).

## 17. Data provenance

* Every source file is SHA-256 verified against the manifest before ingestion.
* Every posting carries its source file, row, URL, posted date and the hash of its description.
* Job-board postings were taken only from employers' own boards through documented public read APIs, India only,
  dated by the source.
* Curricula come from official institution documents.
* ESCO v1.2.1 is the official download.
* Lineage: `data/gold/knowledge/lineage/c066b227857f9eaf.json`:
  * parent `84d7737ccb8e4d87`;
  * 12 sources added, 0 removed or changed;
  * 55 of 79 outputs changed.
* Excluded from redistribution:
  * peer curriculum PDFs;
  * raw job-board posting files.

  Both can be re-acquired: `scripts/mac/acquire_official_evidence.sh`, `data/metadata/official_sources.json`.

## 18. Limitations

1. **Industry trends are not established.** The current evidence is one qualifying snapshot period per population.
   Additional dated evidence is required to establish a trend.
2. **Peer coverage is partial:** 3 of 6 requested official curricula.
3. **Occupation mapping is partial:** 61 of 498 postings. No occupation is forced.
4. **Independent human semantic validation is pending:** 0 reviewer labels.
5. **AI semantic interpretation remains advisory** until the promotion gate is evaluated on independent labels.
6. **Some recommendations require human curriculum judgement:** the three population-dependent ones, the two
   borderline-support ones and the 14 withheld for review.
7. **Industry evidence represents the supplied and legitimately acquired posting population**, not the entire labour
   market.
8. **Repeated employer text is counted as demand.** It inflates *make decisions* (66 of its 89 postings), though not
   enough to change any gap.
9. **Concept-level drift** (evolved, merged, renamed, split) is not detected. Concepts are lexical clusters.
10. **Alias senses.** About 80 % of taxonomy alias matches stay in sense review and are not counted as demand.

## 19. Installation

**Requirements:** macOS or Linux; Python 3.11+; PostgreSQL 16; Flutter 3.x (web).

1. `python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt`
2. Create the database:
   ```
   createdb skillgap_<run>
   (cd backend && DATABASE_URL=postgresql+psycopg2://localhost/skillgap_<run> ../.venv/bin/alembic upgrade head)
   pg_restore --data-only --disable-triggers --no-owner -d skillgap_<run> artifacts/db/skillgap_knowledge_final_c066b227857f9eaf.dump
   ```
3. Build the web app: `cd flutter_app && flutter pub get && flutter build web --base-href /app/`
4. Start the application in production mode; the steps are in `scripts/mac/final_hardening_validation.sh` (step 5).
5. Open `http://localhost:8000/app/`.

## 20. Reproduction

1. **Evidence.**
   * The target, reference and previous-version curricula and the supplied export are in `data/raw`. They are listed
     with their hashes in `data/metadata/curriculum_sources.json`.
   * Peer PDFs and job-board files are excluded from the package. Re-acquire them with
     `bash scripts/mac/acquire_official_evidence.sh`. It needs network access; it downloads only from the publishers
     listed in `data/metadata/official_sources.json` and writes sidecars.
   * Re-acquired job boards will contain the postings open **on that day**. That is a new snapshot, so its run id and
     digest will differ from this release, by design.
2. **Run.** `python3 scripts/pipeline/run_knowledge_pipeline.py` builds a run into `data/gold/knowledge/<run>`.
   `scripts/acquisition/recompute.py --parent <run>` does the same and records lineage.
3. **Verify.**
   * Compare digests (`latest_run.json`).
   * Run the audits:
     ```
     python3 scripts/audit/full_consistency_audit.py
     python3 scripts/audit/topic_concept_mapping_audit.py
     python3 scripts/audit/generalization_audit.py
     python3 scripts/audit/release_gap_qa.py
     ```
   * Compare against the release: `scripts/audit/compare_runs.py`.
4. **Human validation.**
   * Run `createSemanticValidationForm` in Google Apps Script.
   * Import the responses with `scripts/evaluation/semantic_validation.py import-form`.
   * Then run `agreement`, `adjudicate`, `freeze` and `evaluate` (the gate is applied only there).

## 21. Release package

**Build:** `bash scripts/mac/package_release.sh` → `artifacts/skillgap-release_c066b227857f9eaf.zip`.

**Included:**
* source, backend, Flutter app, scripts, tests and documentation;
* audits and evaluation infrastructure;
* the release, baseline and original-baseline GOLD runs and the lineage records;
* the database dump;
* the human-validation form script and its integrity artifacts.

**Excluded:**
* peer PDFs and raw job-board posting files;
* BRONZE/SILVER derived text;
* other GOLD runs;
* virtual environments, build outputs and caches.

The package integrity results and the final release decision are recorded in
[FINAL_HARDENING_REPORT.md §P](FINAL_HARDENING_REPORT.md).
