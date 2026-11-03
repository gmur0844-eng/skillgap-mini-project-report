# Final hardening report — consistency audit, upload workflow, editorial frontend

> **Current release: `c066b227857f9eaf`** (2026-10-02), the evidence-expansion run built on top of the release
> described below: 498 postings from official employer job boards plus the original export, a third peer curriculum,
> 11 evidence-supported gaps and 11 issued recommendations. See section O. Sections A–N describe the hardening of
> the previous release `84d7737ccb8e4d87`, which remains in GOLD unchanged as the parent run.

Previous release run **`84d7737ccb8e4d87`** (code fingerprint `ac5f7b024802aed3`, content digest `ac31a3c5…`), parent
`c8ecd067bb733f58`, baseline `5e2416e1ac2aa587`. Rule followed throughout: audit first, fix only what the audit
classified as a bug or a false label, record every change as a new run with lineage, and never present an internal or
assistant label as independent ground truth.

## A. Outcome in one paragraph

The audit found two real bugs and one false label behind the Overview numbers, all fixed: SQL was recommended
although the depth measure says it is covered (now withheld for review); the database silently dropped most graph
edges of every run after the first (primary key fixed, verified with three runs in one database); and the headline gap
figure described a population it did not count (now counts evidence-supported gaps, which is 0). A course-context
gate stops single shared words from creating "same concept" links between unrelated courses. The upload workflow now
carries a new curriculum to its own analysis and never shows an older run's results meanwhile. The frontend was
rebuilt as an editorial briefing. Human validation of the semantic layer is fully prepared but **has not happened**:
no human labels exist yet. The Flutter part is complete in code and covered by new widget tests, which must still pass
on the Mac (section M).

## B. Baseline and history preserved

* Baseline GOLD `5e2416e1ac2aa587` is byte-identical to its archive (`artifacts/archive/baseline-5e2416e1ac2aa587`,
  checked by extracting the archived tarball and comparing every file).
* No file of runs `5e2416e1`, `405319df`, `c8ecd067` was modified after the pre-audit snapshot
  (`artifacts/archive/pre_audit_c8ecd067bb733f58/`, code + config + docs).
* The first audit results are kept unchanged (`*_before_c8ecd067bb733f58.json`); the old run's database load (115
  edges) is left as published.
* Every change produced a new run: trial `d2cbddb5e664c731` (outside the project GOLD), final `84d7737ccb8e4d87`,
  lineage `data/gold/knowledge/lineage/84d7737ccb8e4d87.json` (10 of 79 outputs changed).

## C. Cross-layer consistency audit

[FULL_CONSISTENCY_AUDIT.md](FULL_CONSISTENCY_AUDIT.md) · `data/evaluation/full_consistency_audit.json`.
15 checks across GOLD → database → API → UI → documentation. Before: 3 inconsistent (2 TRUE_BUG, 1
DISPLAY_LABEL_PROBLEM). After: 0 inconsistent; 5 scope differences labelled, 1 expected difference, 1 stale
documentation annotated.

| Overview | Before | After | Why |
|---|---|---|---|
| Target-curriculum courses / topics / concepts | 113 / 4,426 / 1,093 | same | scopes now stated (189 / 8,935 / 1,318 are other populations) |
| Industry postings / eligible skills | 100 / 120 | same | 357 normalized, 115 with demand, 106 ESCO-mapped |
| Gaps (headline) | 13 | **0 evidence-supported** | 13 are PARTIAL with thin demand; none has supported demand |
| Recommendations | 1 | **0 issued, 1 withheld for review** | SQL: breadth says partial, depth says covered |
| Suppressed | 114 | 114 + 1 withheld | every one with a coded reason |

## D. Topic → concept mapping

[TOPIC_CONCEPT_MAPPING_AUDIT.md](TOPIC_CONCEPT_MAPPING_AUDIT.md) · `data/evaluation/topic_concept_mapping_audit.json`.
The three mapping problems (topic → concept, curriculum → reference, industry skill → taxonomy) are audited
separately and every graph edge carries its `mapping_kind`. Course-context gate: 263 of 522 curriculum → reference
links moved to REVIEW_REQUIRED; identity links REFERENCE_MAPPED 51 → 33. On the 33 identity pairs the assistant read,
all 7 wrong/doubtful ones are now held for review, at the cost of 11 correct ones also held. The old n = 45 figure
(0.578) is the deterministic pair rule against assistant labels, recomputed identically every run — it is not system
accuracy and is no longer reported as such. Concept membership and taxonomy alias roll-ups were flagged (267 concepts,
27 aliases) and deliberately **not** changed without a reviewer.

## E. Peers, industry, temporal, occupations, gaps, depth, drift, recommendations

Peers: 2 of 6 requested official curricula available (status PEER_DATA_PARTIAL); 4,067 relations, 859 supported, 0
model-supported; peer topics never enter target concepts. Industry: 100 postings from one week in India — trends are
not computable (one period), stated as such. Occupations: 22 of 100 postings established; no title-contradicted posting
is established. Gaps v2 and coverage depth: consistent across layers. Drift: course-level EVOLVED exists (4);
concept-level EVOLVED/MERGED/RENAMED/SPLIT is not detected — a stated limitation. Recommendations: reconciled with gap
v2 (section C).

## F. Database

`knowledge.concept_relationship` primary key `(run_id, edge_id)` and a `mapping_kind` column with a CHECK constraint
(`knowledge_schema_consistency.sql`, idempotent; Alembic `0004_consistency_schema`). `document.document_role`
(Alembic `0005_document_role`). Integrity checks are schema-aware so an older database still verifies. Verified:
fresh database `skillgap_knowledge_final` PASS (15,689 edges = GOLD); multi-run database `skillgap_knowledge_improve`
PASS with 15,689 edges for each of two later runs. Dump: `artifacts/db/skillgap_knowledge_final_84d7737ccb8e4d87.dump`.

## G. Semantic AI and human validation

* The 88-case frozen benchmark is unchanged (sha `94b4e79c49bc…`).
* Assistant labels for all 88 cases are stored as `ASSISTANT_ADJUDICATION` (`semantic_gold/<discipline>/v1/assistant_adjudication.json`); they are never stored as, or counted as, human validation.
* 48-case stratified human subset (by kind, then label, every class present, failure modes covered, seeded order), blind export without model output, Google Form generator (`scripts/evaluation/create_semantic_validation_form.gs`), [HUMAN_VALIDATION_FORM.md](HUMAN_VALIDATION_FORM.md), [HUMAN_VALIDATION_INSTRUCTIONS.md](HUMAN_VALIDATION_INSTRUCTIONS.md).
* Agreement (Cohen's kappa for 2 reviewers, Fleiss' for more, per-class agreement, disagreement matrix), adjudication sheet, freeze as `semantic_gold_v1`, evaluation — all implemented and tested on synthetic inputs.
* Gate v3 declared **before any label exists** (`semantic_gate_v3.json`, pinned in the config): ≥ 44 gold cases, ≥ 2 independent reviewers.
* Status: **no human labels yet; the AI layer stays advisory (SAFE MODE).** [SEMANTIC_VALIDATION_PLAN.md](SEMANTIC_VALIDATION_PLAN.md).

## H. Generalization

[GENERALIZATION_AUDIT.md](GENERALIZATION_AUDIT.md) · `data/evaluation/branch_generalization_audit.json`. 151 files:
0 discipline conditionals, 0 hard-coded discipline lists, 0 ranking logic; 10 source-format configs (allowed).
Document roles and metadata policy are data; discipline is free text; gold sets live under
`semantic_gold/<discipline>/v1`; ESCO is not assumed to cover every discipline. Only one discipline has real evidence
here, so generality is shown by construction, not yet by a second discipline's run.

## I. Upload → dashboard

Upload → staged by hash → analysis job on a derived manifest → Overview in the pending state → the new run, with every
request scoped to it. Not-run, failed, needs-review and status-unavailable states never fall back to older results.
Details and tests: [FRONTEND_INTELLIGENCE_AUDIT.md §1](FRONTEND_INTELLIGENCE_AUDIT.md).

## J. Ingestion

One canonical outcome per upload (`pipelines/ingestion/outcome.py`): SUCCESSFUL_AND_USABLE / NEEDS_REVIEW /
EXECUTION_SUCCEEDED_BUT_NO_USABLE_CONTENT / EXECUTION_FAILED / REGISTERED_AS_REFERENCE, with execution, extraction,
quality and review status separate. Zero courses, zero topics or confidence 0 is never "succeeded"; it cannot start an
analysis. Role-based metadata policy from data; institution optional for reference curricula. 13-point audit:
[FRONTEND_INTELLIGENCE_AUDIT.md §2](FRONTEND_INTELLIGENCE_AUDIT.md).

## K. Frontend

Editorial redesign (warm near-black, one brass accent, serif display type, no gradients/shadows/pills), Overview as a
briefing with numbered findings and scoped counts last, human status wording with codes in tooltips, four navigation
groups, grouped search, mapping kinds on graph edges, withheld recommendations shown apart.
[FRONTEND_INTELLIGENCE_AUDIT.md §3–4](FRONTEND_INTELLIGENCE_AUDIT.md).

## L. Tests

| Suite | Result (container) |
|---|---|
| Backend function tests | 582 passed, 0 failed, 1 skipped (FastAPI not installed in the container) |
| Backend TestCase suites (incl. 13 consistency, 17 ingestion outcome, 7 validation package) | 97 passed |
| Static Flutter validation (every endpoint literal is a real route) | 23/23 screens, 26/26 endpoints |
| Flutter widget tests | not runnable in the container (no Flutter SDK; the network blocks it) — see M |

New Flutter tests (`test/workflow_test.dart`, updated `test/premium_ui_test.dart`): upload → pending Overview without
any request for old results; ready → every request scoped to the new run; analysis endpoint unavailable → not-run +
Run analysis + retry; job status unavailable → stays pending; failure → retry and explicit way back; ingestion result
for usable / zero courses / zero topics / confidence 0 / flagged / failed; ids not shown as the result; run-context
scoping rules; WCAG contrast of every text and status colour on every background; overview briefing; withheld
recommendations.

## M. Mac validation

`scripts/mac/final_hardening_validation.sh` — pytest with the real FastAPI stack; migrations 0001 → 0005 on an empty
database with the data restored and re-upgraded; fresh production database from the dump; typefaces; Flutter pub get /
analyze / test / web build; the full application in production mode; full API validation; the Flutter data layer
against the live API (now including the upload metadata and analysis-job endpoints).

Status: **pending — results are filled in from `artifacts/mac_final/` after the run.** The previous Mac run (release
`c8ecd067`) had pytest 642 passed, API validation 109/109, build OK, but `flutter test` failed 9 tests (a list tile
inside a coloured box, two overflowing status badges, labels the tests no longer found); those causes were fixed in
code here and must be confirmed by this run.

## N. Limitations and next steps

* Human validation: two reviewers must label the 48 cases; until then no AI decision changes a result. The reviewer
  form is ready: [SEMANTIC_HUMAN_VALIDATION_FORM.md](SEMANTIC_HUMAN_VALIDATION_FORM.md).
* 263 curriculum → reference mappings, 267 concept clusters and 27 taxonomy alias roll-ups await a reviewer.
* Trends need postings from at least two comparable periods; peers need the four missing official curricula.
* Concept-level drift does not detect evolved/merged/renamed/split concepts.
* Discipline identity is an exact string; the taxonomy loader reads ESCO only.
* The source registry is available through the API but not yet shown on a screen.

## O. Evidence expansion release `c066b227857f9eaf`

**Sources:** [DATA_EXPANSION_AUDIT.md](DATA_EXPANSION_AUDIT.md) covers the sources, method, the defects found and fixed,
and the before/after comparison. In brief:
* 11 employer job boards, read through the publishers' documented public APIs (Greenhouse, Lever), gave 416 India
  postings with source dates. 398 remain eligible after duplicates are removed.
* The NIT Tiruchirappalli curriculum, an official PDF, was added as a third peer.
* Nothing was scraped or fabricated. No date was invented: a job-board snapshot is one period, dated by the
  snapshot day.

| | |
|---|---|
| Run | `c066b227857f9eaf`, parent `84d7737ccb8e4d87`, code fingerprint `d2ca61a7b68aa478` |
| Content digest | `b5d572db06f48d323b9e91e81e0ab6976c2b5ea19e2cff84d549c334bd029c8c` |
| Reproducibility | the same id and digest in three independent builds (two probe GOLD roots and the official build) |
| Lineage | `data/gold/knowledge/lineage/c066b227857f9eaf.json`: 12 sources added, 0 removed or changed; 55 of 79 outputs changed |
| Manifest | `data/metadata/curriculum_sources.json` (the release manifest is archived in `artifacts/archive/manifests/`) |
| Database | fresh `skillgap_knowledge_final2`: 16,568 edges equal to GOLD, all 34 integrity checks 0; dump `artifacts/db/skillgap_knowledge_final_c066b227857f9eaf.dump` |
| Consistency audit | 15 checks, **0 inconsistent** (`data/evaluation/full_consistency_audit.json`); the release-run result is kept as `…_84d7737ccb8e4d87.json` |
| Mapping audit | curriculum mappings unchanged (4,426 topic mappings, 1,318 concepts); skill → taxonomy mappings 702 → 1,030, with about 80 % of alias matches still held for sense review (`topic_concept_mapping_audit.json`) |
| Generalization | 152 files, 0 disallowed discipline logic, 0 ranking logic |

| Evidence | 84d7737c | c066b227 |
|---|---|---|
| Eligible postings / companies | 100 / 95 | 498 / 106 |
| Skills with supported demand | 5 | 68 |
| Evidence-supported gaps | 0 | 11 (+ 2 held for review: a course title names the skill) |
| Recommendations issued / withheld for review | 0 / 1 | 11 / 14 |
| Peer curricula | 2 | 3 |
| Postings with an established occupation | 22 | 61 |
| Trends | not established | not established (one snapshot per population) |

**Audit correction.** The consistency audit counted gaps without the review rule that the product applies. It reported
13 gaps against the headline's 11, the difference being data analytics and operating systems, which the course-title
rule holds for review. The audit now uses the same definition as `intelligence_stage.is_confirmed_gap` and lists the
review items separately. Rerun on both releases: 0 inconsistent.

**Portability fix.** `docs/` had three pairs of files whose names differ only by case (`ARCHITECTURE.md` /
`architecture.md` and two more). On macOS one file of each pair silently replaced the other. The engine-1.x documents
are now `architecture_data_flow.md`, `human_validation_review_set_v1.md` and `semantic_layer_engine1.md`, with every
link updated. A test (`test_repository_portability.py`) prevents the problem from coming back.

**What still holds back a stronger claim:**
* **Trends.** The acquisition must be repeated on later dates; two snapshots of at least 30 postings each are needed.
* **Recommendations from the mixed-function population.** Three recommendations follow from the boards listing
  non-engineering roles: *make decisions*, *lead others* and *financial analysis*. They are correct under the
  definitions but deserve a reviewer's judgement.
* **Human validation.** Pending, as in section N. The AI layer stays advisory.

**Mac validation of this release:** see section P.

## P. Final release validation — `c066b227857f9eaf` (2026-10-02)

| | |
|---|---|
| CURRENT RELEASE | `c066b227857f9eaf`, digest `b5d572db06f48d323b9e91e81e0ab6976c2b5ea19e2cff84d549c334bd029c8c` |
| BASELINE | `84d7737ccb8e4d87`, unchanged |

### Mac validation (`scripts/mac/final_hardening_validation.sh`, results in `artifacts/mac_final/`)

Three runs were made:

1. **Run 1** passed every section. The live inspection after it found the UI defects below.
2. **Run 2** also passed, but it validated the pre-fix frontend: the corrected bundle had not reached the Mac (the
   staged copy was stale). It is **not counted**.
3. **Run 3**, on the corrected bundle (sha256 `060daa83…`, verified on the Mac before the run), is the record:

| Section | Result | Status |
|---|---|---|
| Backend tests (pytest, real FastAPI / SQLAlchemy / Alembic) | 707 passed, 5 skipped, 5 deprecation warnings | VERIFIED |
| Migrations 0001 → 0005 (empty DB → data → upgrade again) | integrity PASS | VERIFIED |
| Production database `skillgap_c066b227857f9eaf` from the dump | integrity PASS | VERIFIED |
| Flutter analyze / test / web build | 0 issues / 39 passed / build OK | VERIFIED |
| Application start (production settings) | READY; web app 200 at `/app/` | VERIFIED |
| API validation | 116/116 checks, 87 routes, negative cases (404 on unknown job and upload) | VERIFIED |
| Flutter data layer vs live API | 49/49 screen specs; live check exit 0 | VERIFIED |
| New endpoints over HTTP | all 200 / expected 404 | VERIFIED |
| Fonts | declared and bundled | VERIFIED |
| Fixes present in the built app | the old wordings are absent from `main.dart.js`; the new ones present | VERIFIED |

**Warnings, not hidden:**
* The 5 skipped tests are not named in the `-q` log. Every skip condition in the suite is environmental. To list them:
  `.venv/bin/pytest backend/tests -q -rs`.
* The 5 warnings are library deprecations (Starlette TestClient, Alembic `path_separator`) and one scikit-learn
  convergence notice in a test fixture.
* The readiness payload reports the component `data: DEGRADED`. It means evidence coverage is limited (peers,
  occupations, trends). System health shows it as "Evidence: available with limitations", not as a failure.

### Defects found during final validation and how they were classified

| # | Defect | Class | Action |
|---|---|---|---|
| 1 | Recommendations (and concept, drift and mapping inferences) labelled "AI-suggested interpretation"; they are rule-based and the AI layer is advisory | A — release-blocking | label "Inferred, not validated" (`design_system.dart`); Flutter regression test |
| 2 | Data quality: "Insufficient real data loaded yet — 0 postings, 0 courses" (phase-1 tables, empty in this architecture) | A — release-blocking | screen reads the run's validation checks (`/api/v1/curriculum/knowledge-health`) |
| 3 | Sources: "No data sources registered yet" (same cause) | A — release-blocking | screen reads the source registry (`/api/v1/metadata/sources`); the empty phase-1 "Pipeline runs" view removed from More views |
| 4 | Skill gaps opened on "Covered" (off-by-one default tab) | B — cosmetic, materially confusing | opens on "Partial coverage", as the code comment intended |
| 5 | Occupations title rendered a missing-glyph box | B — cosmetic, visible | reworded |
| 6 | Consistency audit counted 13 gaps against 11 (the audit lacked the review rule) | D — audit/documentation | audit aligned with `is_confirmed_gap`; 0 inconsistent on both releases (section O) |
| 7 | README described an early phase as current ("498/498 tests", "FastAPI never started") | D — documentation | current-release section added; history kept and marked historical |
| 8 | Older "final" reports name earlier runs | D — documentation | one-line historical banner each; contents unchanged |
| 9 | `package_release.sh` would have packaged a local `.env` | A — release-blocking (packaging) | `.env`, `.git` and editor and OS metadata excluded; `package_integrity.py` runs after packaging |
| — | Industry demand bars not sorted; drift page is a table; the scope sentence also appears on curriculum tables; "Preprocessing preview" lists no jobs (phase-1 path, kept because the ingestion review action links to it) | B — cosmetic, not material | left as they are, documented |

**No data, analytical definition, threshold, gate, benchmark or GOLD output was changed.** The backend change during this
stage is limited to audit and packaging scripts. The only Flutter changes are display wording, two data sources
(phase-1 endpoints replaced by existing run-scoped endpoints) and one default tab.

### Analytical QA (`scripts/audit/release_gap_qa.py` → `data/evaluation/release_gap_qa_c066b227857f9eaf.json`)

| Release figure | GOLD | Database | Status |
|---|---|---|---|
| Job postings | 498 | 498 | VERIFIED |
| Judgeable skills (SUPPORTED + HIGH_SUPPORT) | 68 | 68 | VERIFIED |
| Evidence-supported gaps | 11 (+ 2 held for review) | 24 partial or missing rows; support and review are joined in GOLD | VERIFIED |
| Recommendations issued / withheld / not recommended | 11 / 14 / 218 | 11 supported, 232 suppressed | VERIFIED |
| Peer curricula | 3 available, 3 missing | — | PARTIAL |
| Occupation-resolved postings | 61 (resolver v2) | 61 (`occupation_resolution`); 58 in the v1 table | PARTIAL |
| Trends | 1 qualifying period per population | — | NOT ESTABLISHED |
| Semantic validation | `PENDING_INDEPENDENT_LABELS`, 0 labels | 0 decisions applied | PENDING |

**Gaps and recommendations.**
* All 11 gaps satisfy the declared rules, and every link of their evidence chain re-derives from the run's files.
  None was held.
* All 11 recommendations map to a confirmed gap and have an evidence trace.
* Evidence-quality finding: *make decisions* draws 66 of its 89 postings from one sentence of employer boilerplate. It
  stays HIGH_SUPPORT without them (23 postings, 5 companies), so it is documented, not reclassified
  ([FINAL_RELEASE_REPORT.md §7](FINAL_RELEASE_REPORT.md)).
* *make decisions*, *lead others* and *financial analysis* are scoped to the acquired employer population and need
  curriculum judgement. The system did not mark them for review, and that state was not changed.

### Other checks

| Check | Result | Status |
|---|---|---|
| Reproducibility | 3 builds: run id and content digest identical; only `generated_at` and timings differ | VERIFIED |
| Course-title lookup | case-insensitive and prefix-tolerant regression test passing; 189 courses, no duplicate (document, code) record; 22CSE52 and 22CSC52 share a title as two distinct courses in the source | VERIFIED |
| Generalization | 0 discipline conditionals (static audit: 29 literals, all in seed data, comments or configuration); 0 ranking logic | VERIFIED |
| Human-validation form | 48 cases; 0 missing / duplicate / modified / invented; reviewer-blind; script and integrity report in the package | VERIFIED |
| Upload workflow | Flutter workflow tests (pending state, no stale results, zero content never "succeeded", failure and retry) and API negative cases; no live upload on the release instance, because it would add a run to the release GOLD | VERIFIED (by tests) |
| Evidence thread | live on the release app: docker → 23 postings → 22CSE25 / 22ITE11 pages → introductory → expand existing topic | VERIFIED |
| System health | Analysis Ready · Evidence Available with limitations · AI interpretation Advisory · Traceability Complete | VERIFIED |

### Package

The package is built with `scripts/mac/package_release.sh`, which runs `scripts/audit/package_integrity.py`. The result
is `artifacts/package_integrity_c066b227857f9eaf.json`. The zip's SHA-256 is recorded there and in the release summary.
It cannot be written inside the zip it describes.
