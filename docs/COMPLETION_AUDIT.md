# Completion audit (Phase 0 of the Master Project Completion Directive)

*Written 2026-10-08. Sources:*

- *the repository (the Linux working copy, kept in sync with the owner's Mac);*
- *the Mac state read on 2026-10-08;*
- *release `c066b227857f9eaf`.*

*Nothing destructive was done while writing it.*

**Status labels**

- **COMPLETE**: implemented and validated.
- **PARTIAL**: implemented but limited.
- **EXPERIMENTAL**: implemented, not authoritative.
- **PENDING**: waiting on an external input.
- **PLANNED / MISSING**: not in the code.

**Protected baseline:** release **`c066b227857f9eaf`** (2026-10-02, digest `b5d572db…bd029c8c`):

- 498 eligible postings;
- 68 judgeable skills;
- 11 confirmed gaps (+2 held);
- 11 recommendations issued, 14 withheld.

It has not been modified.

---

## 1. Current architecture

```
Evidence files ──► knowledge_engine.pipeline.run()  (deterministic; RAW → BRONZE → SILVER → GOLD)
                      │                                └─ Qwen via Ollama: advisory, Safe Mode
                      ├─► data/gold/knowledge/<run_id>/  (authoritative results, content-addressed)
                      └─► optional publish to PostgreSQL schema `knowledge`
FastAPI (16 routers, 103 routes) ──reads──► GOLD files of the selected run (latest_run.json or ?run_id=)
Flutter web app (/app/) ──HTTP──► FastAPI
```

The architecture is documented in full in `docs/PROJECT_HANDOVER.md` §C. The API does not recompute anything; an
upload starts a background pipeline run (`backend/app/services/analysis_jobs.py`).

## 2. Existing intelligence components (directive §4)

| Directive layer | Existing implementation | Status |
|---|---|---|
| Curriculum Understanding Engine | `silver.py`, `pipelines/preprocessing/curriculum_structuring.py`, `concepts.py`, `prerequisites.py`, `intelligence.coverage_depth` | PARTIAL: course → unit → topic → concept, outcomes and prerequisites are present. There is no explicit `CurriculumProfile` object, no use of a lab / description / title evidence hierarchy, and no UNCERTAIN depth level. |
| Discipline-to-Industry Relevance Engine | Rules only (details below) | MISSING as a layer |
| Skill Intelligence Engine | `skill_extraction.py`, `skill_normalization.py`, `industry.map_skills`, `industry.sense_check`, support states | PARTIAL: mention → normalised → ESCO skill → supported. "Discipline-relevant skill" exists only as the gap-stage rule. |
| Skill-Gap Reasoning Engine | `analytics/gap_classification.py` (v1), `intelligence_stage.gap_v2`, review overrides | PARTIAL: depth, support, ESCO ambiguity and review flags are used. Not used: peers, related courses, cross-course coherence, or concept-level semantic coverage (e.g. container orchestration ↔ Kubernetes). |
| Curriculum Recommendation Engine | `analytics/recommendation_engine.py`, `industry.recommend` (suppression), `intelligence_stage.reconcile_recommendations` | PARTIAL: least-disruptive change preferred (10 of 11 are "expand existing topic"). There is no existing-course-first inspection, no "strengthen existing course" or "review before structural change" actions, and the elective rule fires on demand alone. |

The rules that stand in for the Discipline-to-Industry Relevance Engine today:

- the `DISCIPLINE_RELEVANCE_UNESTABLISHED` gap override (`industry.py` around line 560);
- occupation resolution (`occupation_resolution.py`, 61 of 498 postings);
- sense review of ambiguous aliases.

There is no per-posting relevance classification: all 498 postings count in every denominator.

## 3. Existing semantic AI

COMPLETE as infrastructure, EXPERIMENTAL as intelligence.

- **Engine.** Qwen 2.5 7B Instruct (Q4_K_M) via Ollama, temperature 0, `semantic_v3.py`.
- **Prompt and schema.** Prompt `adjudicate-v3`, schema `decision-schema-v2`, evidence validator, retries.
- **Cache.** Keyed on model, prompt and settings plus input and context hashes.
- **Replay.** Replay of hash-pinned recorded runs.
- **Promotion gate.** Declared in advance, and **failed**.
- **Independent-label gate v3.** Defined; 0 human labels.
- **Release c066:** 336 candidates, 36 replayed, 300 replay misses, **0 applied**.

**Open defect.** In LIVE mode, i.e. when Ollama is reachable, the adjudicator appends to the hash-pinned, read-only
replay cache, and the run fails with `PermissionError`. Observed on the Mac on 2026-10-03, after 4.5 minutes of live
calls. The workaround is to start the server with `OLLAMA_URL=http://127.0.0.1:9`.

## 4. Existing Safe Mode

COMPLETE. Decisions are recorded and shown, never applied, unless a gate passes. Even a passed gate only affects
alias-sense establishment. Safe Mode is reported in `/health` and the UI ("AI interpretation is advisory").

## 5. Existing industry pipeline

COMPLETE:

- 15 job files ingested;
- personal columns dropped;
- duplicates removed (URL plus 5-gram Jaccard 0.75);
- skills extracted, normalised and mapped to ESCO v1.2.1 (exact / normalised / TF-IDF ≥ 0.5 with a 0.03 lead /
  ambiguous);
- support states set (high support ≥ 10 postings and ≥ 5 companies; supported ≥ 5 and ≥ 3; observed ≥ 3).

**Gaps against the directive:**

- No job-relevance layer: §6–8 of the directive are MISSING.
- No boilerplate detection: §7 is MISSING. "make decisions" draws 66 of its 89 postings from repeated employer text.
- The raw postings are preserved in RAW/SILVER/GOLD.

## 6. Existing curriculum pipeline

COMPLETE for extraction:

- pdftotext with layout, plus pdfplumber tables, cached per document hash and parser fingerprint;
- structuring with quarantine;
- health gates;
- concepts by agglomerative clustering (seeded);
- reference mapping to AICTE;
- prerequisites;
- coverage depth (heuristic, uncalibrated).

**Missing:** academic-level classification (UG year vs PG), core/elective status as an input, and lab evidence as a
distinct coverage level.

## 7. Existing gap reasoning

A **confirmed gap** requires all three:

- v2 class PARTIAL or MISSING;
- demand SUPPORTED or HIGH_SUPPORT;
- no `REVIEW_REQUIRED`.

INSUFFICIENT_EVIDENCE is first-class: 202 of 243 skills, including "help customers", "financial statements" and
"reproductive health" through the discipline-relevance override.

The internal states differ from the directive's list:

| Directive state | Current state |
|---|---|
| NO_GAP | COVERED |
| LIMITED_COVERAGE / DEPTH_GAP | PARTIAL |
| STRUCTURAL_GAP | MISSING |
| INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE |
| REVIEW_REQUIRED | evidence_status REVIEW_REQUIRED |
| OUTDATED_COVERAGE | OUTDATED, which can never fire (see D5 in `docs/PROJECT_HANDOVER.md` §O) |

## 8. Existing recommendation logic

**Rules** (`recommendation_engine.py`):

| Gap class | Action |
|---|---|
| PARTIAL | EXPAND_EXISTING_TOPIC; ADD_MODULE if there is no course evidence |
| MISSING | ADD_MODULE if grouped; ADD_NEW_SUBJECT if demand ≥ 15%; otherwise ADD_ELECTIVE |

Suppression reasons: GAP_INSUFFICIENT_EVIDENCE, COVERAGE_SUFFICIENT, INDUSTRY_SUPPORT_BELOW_THRESHOLD,
ESCO_MAPPING_AMBIGUOUS. Reconciliation withholds a recommendation on classification or course-title conflict.

**Directive §13–15 conflicts:**

- The MISSING branch does go straight to an elective or a new subject, without inspecting existing courses.
- The R26 trial produced exactly the outcome the directive warns about, e.g. "Operating systems → elective" for a
  first-year syllabus.
- The labels are imperatives ("Add elective"), where the directive asks for "Consider a new elective".

## 9. Existing peer and benchmarking

- **Peer comparison: PARTIAL.** 3 of 6 peers. Four separate measures, no ranking, a status banner.
- **NIRF benchmark selection: MISSING.** Inputs are also missing:
  - The owner supplied the NIRF 2025 **Overall** ranking PDF. The directive asks for the **Engineering** ranking.
  - Only the IIT Delhi CSE department page publishes per-course descriptions. IIT Madras CSE lists codes and credits
    only.
- **Depth & relevance profile: MISSING.**
- **Branch matching (CSE↔CSE, AI&DS↔AI&DS) and academic-level matching: MISSING.**

## 10. Existing frontend state

The redesign ("editorial research instrument") is built and running on the Mac.

**Check of 2026-10-03:**

- `flutter analyze`: 2 lint infos.
  - `prefer_interpolation_to_compose_strings` in `industry_screen.dart`.
  - `prefer_const_constructors` in `recommendations_screen.dart`.
  - The Mac has `analysis_options.yaml` with `flutter_lints`; the Linux copy did not until today.
- Tests: **39 passed, 4 failed.**
  - Two taps landed on the top bar after `ensureVisible`.
  - Two found duplicate headings because the page cross-fade (420 ms) outlasted the tests' 400 ms pump.

These are fixed in Phase 1 (§20); re-validation on the Mac is pending.

**Plain-language layer: MISSING.** Users still see "analytics gates blocked: concept_drift: … TARGET +
PREVIOUS_VERSION …".

## 11. Existing validation

The release was validated on macOS on 2026-10-02:

- 707 Python tests passed, 5 skipped;
- migrations and DB integrity PASS;
- release frontend: analyze 0, 39/39 tests, build OK;
- 116/116 API checks;
- 49/49 live checks;
- reproducibility: 3 identical builds;
- package integrity passed.

**However, the release zip contains raw job-export spreadsheets with personal columns.** The team-share zip of
2026-10-06 excludes them. Human semantic validation: PENDING, 0 labels.

## 12. Existing caching

| Cache | Key | Status |
|---|---|---|
| PDF page text (BRONZE) | document sha256 + parser fingerprint | COMPLETE |
| Semantic decisions | model key (model, prompt, schema, settings) + input hash + context hash | COMPLETE |
| Run results | content-addressed run id (code, config, inputs) | COMPLETE: an identical run is regenerated, not reused |
| Industry evidence (postings → skills → ESCO → demand) | — | **MISSING**: recomputed on every run |
| ESCO index | — | **MISSING**: the zip is re-parsed on every run |
| Relevance cache (directive §28) | — | MISSING (no relevance layer yet) |

## 13. Existing performance (measured on the owner's Mac, Apple M5)

| Run | Total | Breakdown |
|---|---|---|
| R26 run `0567481bd43ddb4d` (2026-10-03), all PDFs cached | **~66 s** | industry.extract 30.9 s · peers 15.8 s · ESCO load 5.2 s · industry.gold 4.1 s · concepts 3.7 s |
| R26 run `cefa55f44975540d` (2026-10-06) | **~158 s** | bronze.extract 84 s (R22A extracted for the first time on the Mac) · industry.extract 32.1 s · peers 16.0 s · ESCO 7.6 s · concepts 6.2 s |
| A LIVE-mode attempt (Qwen reachable) | **4.5 min** before failing | the defect in §3 |

About half of each run (industry extract plus ESCO load, about 37–40 s) re-derives evidence that has not changed.
`docs/performance/PERFORMANCE_AUDIT.md` is not yet written; it is Phase 10.

## 14. Existing R26 behaviour

The upload is CBIT R26, CSE (AI & ML), semesters I–II. Its metadata was entered as institution "CBIT" and programme
"BE.".

- **Upload pairing (added 2026-10-03).** The upload recognises CBIT as Chaitanya Bharathi Institute of Technology, so
  R22A becomes the earlier curriculum and R22 leaves the context. The job notes that the programmes differ.
- **The pipeline still blocks it.** It requires an exact institution and programme match (`pipeline.py` line 288,
  `same_programme`), so `concept_drift` was BLOCKED and the job is "needs review".
- **This is correct in substance.** R26 (CSE AI & ML) and R22A (CSE) are different programmes, and the directive
  (§18) says not to present this as same-programme drift.
- **What's missing** is a separate **cross-programme comparison** for same institution, different programme.
- **Default view.** The R26 trial had become the default run shown in the app. It was restored to the release on
  2026-10-08 (Phase 1). Both R26 runs are kept.

## 15. Existing tests

| Suite | Contents |
|---|---|
| Python | 62 test files (`backend/tests/`), including 19 upload/analysis-job tests (with the pairing tests added 2026-10-03) |
| Flutter | `widget_test.dart` (4), `workflow_test.dart` (14 incl. 4 unit tests), `premium_ui_test.dart` (23 incl. 3 unit tests) |
| Tools | `tool/live_api_check.dart`; static checker `scripts/frontend/static_validate_flutter.py`; audits in `scripts/audit/` |

None of the directive's §29 relevance, boilerplate, cross-course, recommendation-hierarchy or NIRF tests exist yet.

## 16. Already complete from the directive

- **§1** baseline capabilities.
- **§2** separation of authoritative and experimental results (Safe Mode, deterministic GOLD, release protected).
- **§3** branch-agnostic design. Only CSE has been run; a static audit exists.
- **§10** semantic AI infrastructure, cache, Safe Mode and the "Qwen unavailable → core continues" behaviour (replay or
  deterministic fallback).
- **§17** evidence graph with provenance on every edge (10,868 nodes, 16,568 edges). There are no relevance edges yet.
- **§21** editorial redesign and navigation groups. Under re-validation.
- **§26** frozen benchmark and blind reviewer form. The labels are pending.
- **§32** the team zip excludes personal data.

## 17. Partial

- **§5** curriculum understanding: no `CurriculumProfile`, no evidence-hierarchy weighting, no UNCERTAIN level, no
  level classification.
- **§9** skill intelligence: no explicit "discipline-relevant" or "analytically eligible" stages.
- **§11–12** gap reasoning: no cross-course coherence, no peer evidence, limited semantic coverage.
- **§13–16** recommendations: least-disruptive in practice, but there is no existing-course inspection, the elective
  and new-subject rules are too direct, and the wording is imperative.
- **§18** R26: institution aliasing exists in the upload step only.
- **§19** peers: 3 of 6.
- **§23–25** UI: the skill-gaps and recommendations screens are editorial lists, but use "of 498 postings" everywhere.

## 18. Missing

- **§6–8** discipline-to-industry relevance engine (job and skill relevance separated), boilerplate detection, and the
  498-posting old-vs-new audit.
- **§18** a cross-programme comparison mode.
- **§19–20** NIRF benchmark selection, branch and level matching, and the depth & relevance profile.
- **§22** the plain-language terminology layer.
- **§27** the performance audit document and safe optimisations.
- **§34** documentation: `docs/intelligence/*` (5 files), `docs/industry_relevance_methodology.md`,
  `docs/industry_relevance_evaluation.md`, `docs/performance/PERFORMANCE_AUDIT.md`.
- **Fix needed:** the LIVE-mode semantic cache write (§3).

## 19. Conflicts and duplicates

1. **Two trend vocabularies.**
   - `gap_v2` reads trends from `intelligence.industry_trends`, which expects `skill_series`. The industry stage never
     produces it, so EMERGING and OUTDATED are unreachable.
   - `industry_intel.py` computes trends that `gap_v2` never sees.
   - The directive's OUTDATED_COVERAGE must be wired to one source, not a third.
2. **Two gap classifiers (v1 and v2).** v2 is authoritative and v1 feeds it. The directive's new states should extend
   v2, not add a v3 in parallel.
3. **Two semantic protocols.** Legacy v2 in `semantic_provider.py`, active v3 in `semantic_v3.py`. Reuse v3 for any
   new relevance adjudication.
4. **Upload-time institution matching vs pipeline `same_programme`.** Two different identity rules. Phase 2 must use
   one shared rule.
5. **Recommendation funnel count.** The run report's 26 is counted before reconciliation; 11 are issued (D4).
6. **Directive §21 navigation includes no "Add evidence".** The app has it under Evidence, and the upload workflow
   depends on it. Keep it.
7. **Directive §6 "do not invent numeric thresholds without evaluation".** Any relevance rule must be evidence-state
   based (RELEVANT / LIKELY / UNCERTAIN / NOT) with stated reasons, and evaluated against labelled postings before
   promotion. No labels exist yet, so the layer must stay EXPERIMENTAL (§20, Phase 3).

## 20. Recommended implementation order

| Phase | Work | Depends on | Promotes to authoritative? |
|---|---|---|---|
| **1** (done 2026-10-08, awaiting Mac re-run) | 4 Flutter tests (stale tap positioning; page transition shortened from 420 to 260 ms, inside the 200–300 ms band), 2 lints, release restored as default | — | n/a |
| **2** | Shared institution/programme identity rule. Same programme → drift; same institution, different programme → **cross-programme comparison** (new, labelled as such); different institution → peer. R26 vs R22A becomes a cross-programme comparison. | — | yes (deterministic, tested) |
| **8a** | Plain-language label layer and error explanations (frontend only) | — | yes |
| **7** | Recommendation reasoning: existing-course-first inspection, "consider…" wording, high bar for an elective or standalone course, "review before structural change" | Phase 4 helpers | yes, after tests and a diff against c066 is reviewed |
| **3** | Experimental job/skill relevance layer and boilerplate detection; 498-posting old-vs-new report; trace of the three phrases | — | **no**: experimental until evaluated on labelled postings |
| **4–6** | `CurriculumProfile`, evidence hierarchy, cross-course coverage, skill-intelligence stages, gap states | 3 | experimental, then promoted after evaluation |
| **10** | Performance audit, then safe caches (industry evidence keyed by job-file hashes + taxonomy hash + code fingerprint; ESCO index cache); fix the LIVE-mode cache write | — | yes (outputs must stay byte-identical) |
| **9** | NIRF benchmark plus depth profile | **owner inputs:** the NIRF Engineering page and department syllabus PDFs | experimental |
| **11** | Human validation (Google Form, 2 reviewers) | owner and reviewers | — |
| **12** | Full Mac validation; new release; package without personal data | all of the above | — |

Phases 2 and 7 are moved ahead of 3–6 because they fix visible, user-reported problems: R26 drift, and the "Add
elective / New subject" wording. Neither needs the experimental relevance model.

Each phase runs its tests, checks for regressions against the protected release, and records what changed in this
file.

---

## Progress log

- **2026-10-08 — Phase 0** written.
- **2026-10-08 — Phase 1** changes applied on the Mac. Backups are in `.sync/pre_phase1_1008/`.
  - **Analyzer.** Two lints fixed in `industry_screen.dart` and `recommendations_screen.dart`.
  - **Page transition.** Shortened to `AppMotion.normal` (260 ms) in `app_shell.dart`, inside the brief's 200–300 ms
    band for transitions.
  - **Tests.** Two tests now scroll the link to the middle of the page before tapping, via a `_reveal` helper in
    `premium_ui_test.dart`. The expectations are unchanged.
  - **Default run.** `latest_run.json` and `concept_registry.json` restored to release `c066b227857f9eaf`. The R26 runs
    `0567481bd43ddb4d` and `cefa55f44975540d` are kept.
  - **Mac re-run, first pass.** analyze 0 issues; tests 42/43. The remaining failure was a real layout bug: an
    opened trail stage overflowed by 22 px, because its height was measured at full width but laid out at the reading
    width.
  - **Fix.** Trail stages now get a fixed reading width (`Trail._contentWidth`), so measurement and layout agree.
  - **Mac re-run, final (2026-10-08).** `flutter analyze`: no issues. `flutter test`: **43/43 passed**.
    `flutter build web`: OK.
  - **Still pending.** The API and live checks (`scripts/api/full_app_validation.py`, `tool/live_api_check.dart`)
    need the server running on the Mac.
- **2026-10-08 — Phase 2** (same-programme versions vs cross-programme comparison). Backups are in
  `.sync/pre_phase2_1008/`.
  - **One identity rule.** `backend/app/knowledge_engine/identity.py` is used by uploads (`analysis_jobs.py`) and the
    pipeline. It replaces the pipeline's exact-string check.
    - It recognises acronyms ("CBIT" = Chaitanya Bharathi Institute of Technology) and strips degree words from
      programme titles.
    - It returns SAME_PROGRAMME, SAME_INSTITUTION_OTHER_PROGRAMME, DIFFERENT_INSTITUTION or UNKNOWN, with the reasons.
    - A specialisation stated on only one document is **not** assumed to be the same programme.
  - **Pipeline.**
    - The curriculum-changes gate is ALLOWED only for SAME_PROGRAMME. Otherwise it is **NOT_APPLICABLE** with a
      plain reason. It is no longer BLOCKED, so an upload without an earlier version is not marked "needs review".
    - A new `programme_comparison` gate and stage run the same deterministic drift functions for
      SAME_INSTITUTION_OTHER_PROGRAMME. They write `programme_comparison/{course,concept}_differences.jsonl` and a
      `programme_comparison` report block. Nothing goes into `concept_drift.jsonl` / `course_drift.jsonl` and nothing
      is published as drift.
    - Earlier-version analytics (coverage then vs now, curriculum-industry lag) receive the earlier document only for
      SAME_PROGRAMME.
  - **API.** New `GET /api/v1/curriculum/programme-comparison?level=course|concept`. This is additive; existing
    contracts are unchanged.
  - **UI.** When there is no earlier version of the programme, the Curriculum changes screen shows "How {programme}
    compares with {other programme}" and states that the differences are between programmes, not changes over time.
    Without any comparison it explains what to add.
  - **Regression check** (Linux, isolated copy). The release inputs were re-run with the new code (run
    `b26dee4710c8b06c`). After ignoring run-id-derived identifiers and ordering, these are **identical** to release
    c066:
    - recommendations;
    - gaps v1 and v2;
    - demand;
    - suppressions;
    - evidence traces;
    - concept and course drift;
    - peer coverage levels.
  - **New gate list.** `programme_comparison` is NOT_APPLICABLE for the release configuration.
  - **Cross-programme check** (Linux). R22 relabelled as a CBIT "AIML" programme against R22A:
    - concept_drift NOT_APPLICABLE;
    - programme_comparison ALLOWED on semesters I–IV;
    - drift files empty.
  - **Tests.**
    - New `backend/tests/test_curriculum_identity.py` (12 tests), plus updated upload tests. 33/33 pass on Linux and on
      the Mac.
    - 2 new Flutter tests (programme comparison screen; no earlier version).
    - Full backend suite on Linux: 713 passed, 0 failed, 7 skipped (FastAPI/pytest-only modules).
  - **Observed, unrelated to Phase 2.** In the Linux copy the semantic layer used its deterministic fallback, not the
    recorded replay. It has no effect on results (Safe Mode, 0 decisions applied). To be checked in Phase 10.
  - **Upload jobs and the default run.** Upload jobs no longer replace the default run: `pipeline.run(set_latest=False)`
    from `analysis_jobs`. An uploaded curriculum's analysis is opened through its own run id, so a trial such as R26
    can't silently become the default view again (directive §30). Tested.
  - **Pending on the Mac:**
    - the full pytest suite;
    - Flutter analyze/test/build;
    - a server restart;
    - re-running the R26 analysis.

    Expected R26 result: curriculum changes "not applicable"; a programme comparison of CSE (AIML) R26 against
    B.E. CSE R22A on semester(s) I–II; the job not marked "needs review" for this reason.
- **2026-10-08 — Phase 2 validated on the Mac.**
  - pytest **724 passed, 5 skipped** (the 5 expected environment skips).
  - `flutter analyze` no issues; `flutter test` **45/45**; web build OK. A first pass had found 2 lints and a renamed
    course missing from the comparison screen; both are fixed.
  - R26 re-analysed (run `dee614c750e37ea5`, ANALYSIS_READY):
    - curriculum changes NOT_APPLICABLE;
    - programme comparison ALLOWED on semesters I–II;
    - lineage recorded against parent `c066b227857f9eaf`;
    - the default run is still the release.
- **2026-10-08 — Phase 7** (recommendation reasoning, existing-course-first). EXPERIMENTAL; the rule engine's output is
  unchanged and kept.
  - **New module** `backend/app/knowledge_engine/recommendation_reasoning.py`, called from `intelligence_stage.run`.
    For every issued recommendation it reads:
    - the target curriculum's coverage evidence (courses that teach it, or mention it in passing);
    - the same institution's other curriculum (earlier version or other programme), whose coverage is computed for
      this purpose;
    - the semesters each document covers.
  - **Actions**, in order of preference:
    1. EXPAND_EXISTING_TOPIC
    2. STRENGTHEN_EXISTING_COURSE
    3. REVIEW_BEFORE_CHANGE: the document is incomplete, the institution teaches the skill elsewhere, or demand is only
       SUPPORTED
    4. CONSIDER_ELECTIVE: no coverage anywhere and HIGH_SUPPORT

    CONSIDER_STANDALONE_COURSE is never inferred and is always listed as an alternative considered, with the reason.
  - **Output.** Each row records the why, the evidence (course codes, titles, topic text, pages), the alternatives
    considered and the limitations. Written to `intelligence/recommendation_reasoning.jsonl`.
  - **API.** A `reasoning` field is added to `/api/v1/intelligence/recommendations` items and to `/api/v1/overview`
    issued actions (additive).
  - **UI.**
    - Recommendations and Overview show the reasoned action in "consider" wording, with the existing courses.
    - The rule engine's action is shown as "Rule engine: Consider a new elective (from coverage percentages alone)".
    - The evidence chain gains a "Recommended intervention" step (why, not chosen, limitations, "the institution
      decides any curriculum change").
    - Rule actions are always worded as considerations (`StatusStyle.human`): "Consider a new elective", "Consider a
      new standalone course".
  - **Effect on R26** (dry run on the Mac's run `dee614c750e37ea5`). All 24 rule-engine actions (22 "add elective",
    3 "add new subject"; e.g. operating systems, SQL, machine learning) become **REVIEW_BEFORE_CHANGE**. Each names the
    course that teaches the skill in B.E. CSE R22A (e.g. 22CSC15N Operating Systems, 22CSC11N Database Management
    Systems, 22ITE11 DevOps Tools) and states that the analysed document covers semesters 1–2 only.
  - **Effect on the release** (re-run on the release inputs, run `957c7135c7157f40`). 7 expand an existing topic,
    3 strengthen an existing course, 1 consider a new elective ("lead others"; population-dependent, see Phase 3).
    Recommendations, gaps v1 and v2, demand, suppressions, traces, drift and coverage depth are all **identical** to
    c066, ignoring run-id-derived identifiers.
  - **Tests.**
    - `backend/tests/test_recommendation_reasoning.py`: 11 tests covering the directive §29 recommendation cases
      (existing course prevents an unjustified new subject or elective; partial coverage → expand; missing with no
      suitable course → possible elective; standalone needs a higher bar and is never inferred; insufficient evidence
      → review; title-only cannot justify; branch- and institution-agnostic; complete evidence chain).
    - 1 new Flutter test.

  - **Mac validation (verified 2026-10-08).**
    - pytest: 735 passed, 5 skipped. flutter analyze: no issues. flutter test: 46/46 passed. Web build: OK.
    - R26 run `609656ccd407bc96` is ANALYSIS_READY, with concept_drift NOT_APPLICABLE and programme_comparison ALLOWED.
      Its `recommendation_reasoning.jsonl` has 24 rows, all REVIEW_BEFORE_CHANGE, each naming the R22A courses that
      teach the skill (e.g. machine learning → 22CSC59, 22CSC50, 22CSE07N, 22CSE26).
    - The default run is still `c066b227857f9eaf` (digest b5d572db…bd029c8c).
- **2026-10-08 — Phase 8a** (plain-language layer; frontend only, no backend or API change). Validated on the Mac.
  - **`lib/theme/plain_language.dart`** (new) is the one place backend vocabulary becomes words:
    - document roles, requirement keys ("analytics gates"), status enums, field names and check names;
    - `Plain.analysisOutcome` turns a job reason into what happened, why and what to do, keeping the original text
      for technical details;
    - `Plain.error` explains failed requests;
    - `Plain.prose` rewrites only known codes inside backend prose. Quoted job postings and syllabus lines are never
      reworded.
  - **Screens.**
    - The "needs review" screen now reads "We couldn't compare this curriculum with an earlier version yet", with the
      reason, the next steps, and the raw reason under Technical details.
    - Error states give what, why and next step, with HTTP details folded away.
    - Tables use readable column names.
    - The Data quality "Analyses" section names each analysis and gives the reason.
    - Data lineage layers are worded as Original source / Processed source / Prepared evidence / Analysis results.
    - Run IDs appear only in technical details (or in the top bar's tooltip).
    - "Target", "drift", "taxonomy", "gate" and "pipeline" are removed from normal views. The navigation now says
      "Curriculum changes".
  - **Tests.**
    - `test/plain_language_test.dart`: every backend requirement reason, the screenshot case, translations, and
      branch- and institution-agnostic wording. It also includes a static audit of every prose literal in `lib/`.
    - A rendered audit renders every navigation destination at two widths from fixtures full of backend codes and
      asserts that no code reaches a normal view.
    - A workflow test covers the needs-review explanation.
    - Existing tests were updated only where the wording changed.
  - **Not changed.** Legacy screens that are not routed (`data_sources_screen`, the old `data_quality_screen`, the
    pipeline-runs view, which is not in the navigation) keep their text. Document IDs (e.g. a curriculum's file
    slug) are still shown on Data quality, because the health report carries no friendlier name.
  - **Mac validation (verified 2026-10-08).**
    - flutter analyze: no issues. flutter test: 59 passed, 0 failed. Web release build: OK.
    - The first run failed three tests whose expectations still used the old wording or an exact-text match on a
      rich-text badge. The expectations were corrected and made stricter; no app code changed.
- **2026-10-08 — Phase 3** (discipline-to-industry relevance and employer boilerplate). EXPERIMENTAL: not wired
  into the pipeline. The release, its API and its screens are unchanged.
  - **Code.**
    - `backend/app/knowledge_engine/relevance.py`: text segments (job-specific, shared role text, employer
      boilerplate); programme profile and its ESCO neighbourhood; job relevance from three signals (skills,
      occupation, title); skill relevance, kept separate from job relevance.
    - No blacklist. The code names no discipline or institution. The one provisional number has a sensitivity
      report.
  - **Audit.** `scripts/analysis/relevance_audit.py` writes `data/experiments/relevance/<run>/`.
  - **Documentation.** `docs/industry_relevance_methodology.md` and `docs/industry_relevance_evaluation.md`.
  - **Result on the 498 release postings.**
    - 79 relevant, 163 likely relevant, 207 uncertain, 49 not relevant. 449 eligible under the proposed policy
      (only contradicted postings leave); 242 under the strict one.
    - Employer boilerplate accounts for most of the inflation: social media management 151 → 33 postings, make
      decisions 89 → 20, machine learning 72 → 31 (still high support), reproductive health 12 → 0.
    - All 11 issued recommendations keep their skills and stay at least "supported".
    - Financial statements stays in demand under the proposed policy (the postings are uncertain because an open
      elective puts finance skills near the profile) and is never a discipline gap.
  - **Tests.** `backend/tests/test_relevance.py`, 12 tests, pass in the container.
  - **Open.** Not promoted until evaluated against human labels (Phase 11). Wiring it into the pipeline (as a
    parallel, non-authoritative output) is a later decision.
- **2026-10-08 — Phase 3 validated on the Mac.** 747 backend tests passed, 5 skipped. The relevance-audit summary
  hash matches exactly (`6a3c11d9…5202`).
- **2026-10-08 — Phase 3B** (skill extraction kept separate from skill qualification). EXPERIMENTAL; the release,
  API and screens are unchanged.
  - **Code.**
    - `backend/app/knowledge_engine/skill_qualification.py`: every extracted mention gets a type, a decision,
      a categorical confidence and a reason, with full provenance.
    - Decisions: `EXCLUDED_BOILERPLATE`, `AMBIGUOUS`, `EXCLUDED_INSUFFICIENT_CONTEXT`,
      `EXCLUDED_GENERIC_CAPABILITY`, `TRANSVERSAL`, `QUALIFIED_TECHNICAL`, `QUALIFIED_PROFESSIONAL`,
      `QUALIFIED_DOMAIN`, and `DISCIPLINE_ADJACENT` at skill level.
    - No word list. Evidence: provenance, ESCO type, reuse level and parents, requirement framing, framing bound
      to the word, taxonomy siblings, surface form, and the programme profile.
  - **Audit.** `scripts/analysis/skill_qualification_audit.py` writes
    `data/experiments/skill_qualification/<run>/`.
  - **Benchmark.** `data/evaluation/skill_qualification_benchmark_v1/`: 239 frozen real mentions (131 hard cases,
    108 random). It has assistant labels only; the human-label template is empty.
  - **Metrics against assistant labels.** v0 (held-out): P 0.869, R 0.744, F1 0.802. v0.1 (after reading the demand
    output, not held-out): P 0.925, R 0.592, F1 0.722.
  - **Result.**
    - make decisions 89 → 1 posting; lead others and make decisions are no longer gap candidates, and 2 of the 11
      issued recommendations lose their basis.
    - social media management 151 → 0; reproductive health 12 → 0; help customers 11 → 0 (ambiguous).
    - financial statements is kept as domain knowledge and is not a gap candidate.
    - Python (99 postings), Java (65) and communication (139) enter demand through sentence context.
  - **Tests.** `backend/tests/test_skill_qualification.py`, 13 tests. Results are reproducible across hash seeds.
  - **Documentation.** `docs/skill_qualification_methodology.md`; the relevance methodology and evaluation
    documents are updated.
- **2026-10-08 — Phase 3B validated on the Mac.** 760 backend tests passed, 5 skipped. The skill-qualification
  summary hash matches (`6dba04e2…f85b0`).
- **2026-10-08 — Phase 3C** (skill evidence v0.2, generalization). EXPERIMENTAL; the release, API and screens are
  unchanged.
  - **Code.** `backend/app/knowledge_engine/skill_evidence.py` keeps extraction, context, qualification,
    normalization, relevance and demand as separate stages.
  - **General mechanisms.**
    - occurrence-level extraction;
    - a bounded context window: clause, sentence, list, section, posting, metadata;
    - sentence roles and evidence strength;
    - qualification separate from normalization: unconfirmed concepts are counted under their own wording and never
      make a gap;
    - contextual normalization;
    - syntactic guards;
    - employer-as-subject detection;
    - "what the skill is" separate from programme relevance;
    - curriculum-side profile qualification;
    - a recorded (unused) hook for a semantic model.
  - **Evaluation.**
    - Validation (150) and final holdout (200) samples were frozen and labelled by an independent model annotator
      before v0.2 was written. Not human.
    - A synthetic generalization suite (59 cases plus 17 programme-relevance cases, 6 disciplines) was frozen before
      v0.2.
    - The holdout was run once on frozen code. Holdout P 0.795, R 0.908, F1 0.848 (v0.1 F1 0.559). Validation F1
      0.815 (v0.1 0.475). Development F1 0.835 (v0.1 0.722). Abstention 5–11%.
    - Error taxonomy E1–E12 applied automatically. The dominant remaining class is E5 (wrong sense).
  - **Tests.** `backend/tests/test_skill_evidence.py`: 30 tests covering unseen phrases and writing styles,
    normalization, adversarial cases, properties, a static audit, and an end-to-end synthetic suite through the real
    extractor and taxonomy.
  - **Documentation.** `docs/skill_evidence_generalization.md`.
- **2026-10-08 — Phase 3C validated on the Mac.** 790 backend tests passed, 5 skipped. The final-holdout audit
  reproduced every figure above. The scorecard hash matches (`6ea0f53b…0823`). Phase 3C is the deterministic
  baseline for Phases 4–6; the semantic-model hook stays recorded and unused.
- **2026-10-08 — Phases 4–6** (curriculum understanding, skill intelligence stages, gap reasoning). EXPERIMENTAL;
  the release, the API, the screens and gap v2 are unchanged. Built on the validated Phase 3C baseline, whose
  scorecard hash the audit checks before running.
  - **Code.**
    - `backend/app/knowledge_engine/curriculum_understanding.py`: CurriculumProfile; programme level; course kind
      from the title's head noun; compulsory / option status read from the scheme layout; practical pairing;
      document scope; coverage with an evidence hierarchy; the UNCERTAIN level; access, practice and cross-course
      dimensions; taxonomy-relation context.
    - `skill_intelligence.py`: six stages with stop reasons over the v0.2 fields.
    - `gap_reasoning.py`: NO_GAP, LIMITED_COVERAGE, DEPTH_GAP, STRUCTURAL_GAP, INSUFFICIENT_EVIDENCE, REVIEW_REQUIRED
      and OUTDATED_COVERAGE, with a partial-document guard, non-deciding corroboration and an advisory-only semantic
      slot.
    - Scripts: `scripts/analysis/gap_reasoning_audit.py`, `scripts/analysis/gap_review_sample.py`.
  - **Release check.** 1,812 / 1,812 core-topic mentions reproduced; 0 mappings changed. Course titles, outcomes and
    peer topics added 5,332 mentions, pinned to the run's mappings.
  - **Status reader vs the institutions' own code conventions** (independent of the reader): 290 agree, 2 disagree,
    31 abstained, precision 0.993.
  - **Release results.**
    - 58 skills are analytically eligible: 15 NO_GAP, 10 LIMITED_COVERAGE (taught only in electives), 5 DEPTH_GAP,
      21 STRUCTURAL_GAP, 6 REVIEW_REQUIRED, 1 INSUFFICIENT_EVIDENCE.
    - Of the 11 issued recommendations, 7 keep a gap state, 2 need review and 2 lose their basis (make decisions,
      lead others: transversal).
    - OUTDATED_COVERAGE is wired to `industry_v2/skill_trends.jsonl`. It cannot fire with one posting period.
  - **Synthetic suite** (`data/evaluation/gap_reasoning_suite_v1`): 4 invented disciplines, AUTHOR_LABELLED, written
    after the code. Gap 23/23 and course kind 13/15 (2 known failures kept). The first run is recorded in its
    MANIFEST: one general fix and one suite authoring error.
  - **Tests and determinism.** `backend/tests/test_gap_reasoning.py`: 32 tests. Outputs are byte-identical across
    hash seeds.
  - **Blind review set** for Phase 11: `data/evaluation/gap_state_review_v1` (58 items). No human labels yet.
  - **Documentation.** `docs/intelligence/` (README, curriculum_understanding, skill_intelligence, gap_reasoning).
  - **Not done.** No UI or API exposure yet, and nothing is promoted: both wait for human review.
- **2026-10-09 — Phases 4–6 reproducibility fix** (no reasoning logic changed; the release is unchanged).
  - **Mac failure.** pytest passed (822 passed, 5 skipped), but `gap_reasoning_audit.py` stopped with
    `FileNotFoundError: data/bronze/curricula/bc14c2f0e5170367/pages.6d93cd03ca5098d9.json`.
  - **Cause 1: an unshipped cache.**
    - `bc14c2f0e5170367` is `cbit-be-cse-r22`, the PREVIOUS_VERSION document (R22, semesters I–IV,
      `data/raw/curricula/cbit/cbit_be_cse_r22_syllabus.pdf`).
    - BRONZE page text is a cache that `pipeline.bronze_pages` writes for (source sha256, parser fingerprint), and
      `package_integrity.py` excludes BRONZE and SILVER from every package.
    - The Mac's own pipeline runs (2026-10-03 and 2026-10-06, the R26 trials) never processed R22, so the Mac had no R22
      cache. The audit read the cache directly, an implicit dependency on an artifact the release contract does not
      ship.
    - The parser fingerprint is the same on the Mac and here (`6d93cd03ca5098d9`). The page text of the five
      documents both machines hold is identical apart from the cache timestamp (and the doc_id label the R26 runs
      wrote).
  - **Cause 2: SILVER is not pinned to a run** (found while checking the fix against the Mac's tree). The Mac's R22A
    SILVER topics carry role PREVIOUS_VERSION, stamped by the R26 trial, while c066 used TARGET. Every other SILVER
    file is byte-identical on both machines.
  - **Fix** (`scripts/analysis/gap_reasoning_audit.py`):
    - an explicit `INPUT_CONTRACT`, a single `need()` accessor and preflight checks;
    - a missing BRONZE cache is rebuilt only from the run's own source and parser, with every other case an explicit
      `InputContractError`;
    - full-content checks of the rebuilt SILVER (except the run-assigned role), the release GOLD courses and the run's
      mentions;
    - per-document page-text content hashes in the scorecard, and machine-local provenance in `provenance.json`.
  - **Proof.**
    - Rebuilding R22 here from the PDF reproduced the cached pages, methods and image pages exactly.
    - A simulated Mac tree (no R22 cache, the Mac's R22A SILVER) produced the same scorecard as the full tree.
    - All analysis outputs (profiles, coverage, stages, gaps, synthetic results) are unchanged from 2026-10-08.
    - The scorecard hash changed only because it now carries the input content hashes:
      `1eb337eee409f64b23f711b9b5795b16668842c4a13ec3885edf7f2cb5a90044`.
    - The Phase 3C scorecard (`6ea0f53b…`) and the release (`305eb75b…`) are unchanged.
  - **Regression tests.** `backend/tests/test_audit_input_contract.py`, 12 tests:
    - every path literal is declared;
    - no direct read bypasses the contract;
    - unshipped classes agree with the packaging rules;
    - no analysis script reads BRONZE without a contract;
    - the run-assigned SILVER fields match the pipeline;
    - guarded rebuild cases: wrong parser, changed source, missing source, matching parser;
    - the page-text hash ignores timestamps.
  - **Not changed.** `scripts/evaluation/build_golden_fixtures.py` also reads BRONZE directly. It is an evaluation
    fixture builder, not an analysis audit, and is left for review.
- **2026-10-09 — Phase 4–6 validated on the Mac.** 834 passed, 5 skipped. The R22 BRONZE cache was rebuilt from the
  PDF and verified. Scorecard hash `1eb337ee…0044`.
- **2026-10-09 — Phase 10** (performance audit and LIVE-mode cache fix). Details in
  `docs/performance/PERFORMANCE_AUDIT.md`.
  - **Defect.** LIVE mode appended to the hash-pinned replay recording, which crashed the run with `PermissionError`
    (or, if the file were writable, would have corrupted the recording). Three related risks were also open: stale
    decisions from a re-pulled model, and a LIVE run and a REPLAY run sharing a run id and overwriting each other's
    GOLD.
  - **Fix.**
    - The model digest is part of the cache key.
    - Pinned recordings are never written; LIVE has its own cache namespace.
    - Cache-write failures are recorded, not fatal.
    - The semantic identity is in the run id and in `run_report.json`.
    - `data/metadata/protected_runs.json` and `ProtectedRunError` stop any in-place regeneration of `c066`.
  - **Tests.** `backend/tests/test_live_cache_isolation.py`: 7 tests. The full backend suite in the container: 839
    passed, 0 failed, 4 skipped. This used a stand-in runner, because the container cannot install pytest.
  - **Regression.** A full pipeline re-run (REPLAY mode, scratch GOLD root) differs from `c066` only by the earlier
    validated Phase 2 and 7 additions and by run-derived ids.
  - **Performance.** About 55% of a run is industry extraction plus the ESCO load. Both caches are deferred: not
    release-blocking, and each needs a byte-identity proof.
- **2026-10-09 — Agents integration and release candidate** (EXPERIMENTAL layers stay labelled; authoritative results
  unchanged).
  - **Agents in code, API and app.**
    - `backend/app/services/agents_service.py`: the five-agent registry, with responsibility, authoritative and
      experimental code, inputs and outputs, and per-run status. NOT_PRODUCED and PARTIAL are reported, never
      hidden.
    - `GET /api/v1/agents` and `GET /api/v1/agents/gap-review`, in both the full app and the knowledge API.
    - Flutter: "Analysis agents" (System) and "Gap review (experimental)" (Evidence), spec-driven, with
      plain-language terms for the new states.
    - `scripts/pipeline/run_agents.py`: runs the experimental layers in agent order, stops on failure and records a
      manifest.
  - **Release candidate run `10ee1d77afa50b0c`**, built in the container: REPLAY mode, published to PostgreSQL
    (PASS), content digest `0be9f08d…f11e`.
    - Against `c066`: 75 files unchanged, 1 added (Phase 7 `recommendation_reasoning.jsonl`) and 4 changed. Each
      change is explained by the Phase 2 and 7 additions or by run-derived ids.
    - Its experimental layers are identical to `c066`'s, apart from the run id and the ordering of the
      recommendation list.
    - The recommendation agent's Phase 7 reasoning now exists in the default run (it was missing from `c066`, which
      predates Phase 7).
  - **Tests.**
    - Backend: `test_agents_service.py` (3) and one FastAPI agents test (skipped here: FastAPI is not installed in
      the container).
    - Flutter: `agents_screens_test.dart` (3; runs on the Mac).
    - `scripts/frontend/static_validate_flutter.py`: 27 / 27 screens.
  - **Mac validation script.** `scripts/mac/rc_validation.sh` runs on the current tree and unpacks nothing. The older
    `final_hardening_validation.sh` unpacks the 2 October bundle over the tree and must not be used now.
- **2026-10-09 — RC blockers from the first Mac RC run** (`artifacts/rc/`).
  - **Backend test.** `test_replay_key_stability`:
    - *Symptom.* `DETERMINISTIC_FALLBACK != REPLAY_VERIFIED_RUN`, "cache key of this configuration differs".
    - *Cause.* The RC script disabled live mode with `OLLAMA_URL=http://127.0.0.1:9`. The endpoint address is part
      of the provider description, and so of the replay cache key. The recording was rejected and the Mac run
      (`e54902a88b8f9980`) silently used the deterministic fallback, so it is a different run from the container's.
    - *Fix.* `RecordedProvider` now describes itself as the recording was made: the configured endpoint, and no
      digest. A transport override can no longer change a recording's key.
    - *New setting.* `SEMANTIC_MODE=replay` forces replay even when Ollama is running, and replaces the URL hack.
    - *Tests.* Replay stays selected under three endpoint overrides; `SEMANTIC_MODE=replay` never goes live.
  - **Flutter analyze, tests and web build** (one cause): a duplicate key `coverage_level` in the
    `Plain.fields` const map, which I added in the agents integration. Removed.
    `scripts/frontend/static_validate_flutter.py` now fails on duplicate const-map keys, so the container catches
    this class of error before the Mac does.
  - **Readiness `data=DEGRADED`.**
    - *Cause.* `health.data_component` counted NOT_APPLICABLE gates (the Phase 2 programme comparison) and WARN
      documents (the three peers, which pass the health gate with warnings) as degradation. The data reported
      DEGRADED even for c066.
    - *Fix.* Only BLOCKED analyses and FAILed documents degrade the data. Warnings and not-applicable analyses are
      listed separately. `backend/tests/test_data_health_states.py` adds 2 tests.
  - **Release QA tooling.** `release_gap_qa.py` reached PostgreSQL only through `su postgres`, which fails silently on
    the Mac. It now tries libpq first.
  - **Packaging.** `package_release.sh` kept two stale runs. It now keeps the current release, its lineage parent and
    the protected runs; experiment outputs only for those runs; no `provenance.json`; and only the release's
    database dump.
  - **RC rebuilt** in the container with the fixed code: `a47ba76bfd6e24d9`, REPLAY_VERIFIED_RUN, digest
    `ebda2c8c…b454`, publish PASS.
    - Lineage against `c066`: 75 files unchanged, 1 added, 4 changed (the Phase 2 and 7 additions).
    - Release gap QA: 0 held.
    - Agents: COMPLETE, with experimental outputs identical to `c066` apart from the run id and the order of the
      recommendation list.
    - The container build is shipped to the Mac as `artifacts/rc_reference_a47ba76bfd6e24d9.tar.gz`, for a
      cross-platform comparison in `rc_validation.sh`.
  - **Tests in the container.** Backend 849 passed, 0 failed, 1 skipped; static Flutter check 27/27. The protected
    release is unchanged (`305eb75b…`).
- **2026-10-09/10 — second Mac RC (`a47ba76bfd6e24d9`) and its fixes.**
  - **Mac results.**
    - Backend: 849 passed, 1 failed, 4 skipped.
    - REPLAY_VERIFIED_RUN; same run id as the container reference.
    - Database, gap QA (0 held), Flutter (analyze, tests, build), readiness HEALTHY and 119/119 API checks all passed.
    - 7 GOLD files differed from the container reference.
  - **Backend failure.**
    - *Cause.* `rc_validation.sh` exported `SEMANTIC_MODE=replay` to the whole run, pytest included. Under replay,
      `semantic_setup` indexed `r["gate_file"]` of a test's minimal replay entry and raised `KeyError`.
    - *Fix.*
      - Replay entries are checked for `cache_file`, `cache_sha256`, `gate_file` and `gate_sha256`. A missing field is
        a `replay_rejected` entry ("hash, provider or protocol mismatch", plus `missing_fields`).
      - The tests set the mode themselves.
      - `rc_validation.sh` sets `SEMANTIC_MODE=replay` only on the pipeline and agent commands, and runs pytest with
        it unset.
    - *Regression test.* `test_malformed_replay_entry_is_rejected_not_raised`. It fails on the old code with `KeyError`.
  - **Order defects** (a same-machine repeat was identical, so these are order effects, not hash-seed nondeterminism).

    | Defect | Fix |
    |---|---|
    | 3 family names were exact TF-IDF ties ordered by `argsort` | `top_terms` sorts by (−weight, term) |
    | `exports/concepts.csv` was written in clustering order | sorted by `concept_uid` |
    | The review queue's related concepts were cut to 6 in edge order | sorted by (relation, name, uid) first |
    | Peer top-k candidates used an unstable `argsort` over equal similarities (repeated topic texts) | stable sort (found while auditing every `argsort` in the engine) |
    | `recommendations.csv` listed suppressions by a run-derived uid | listed by skill key |

    Thresholds and algorithms are unchanged.
  - **Cross-machine control.**
    - `run_report.json` records the numeric environment.
    - `scripts/audit/reproducibility_gate.py` and `reproducibility_policy.json` are an explicit gate with a narrow,
      documented allow-list (descriptive labels; bounded AMBIGUOUS/RELATED peer relations and their summaries). Every
      allowed difference is reported, and anything else fails. Tests: `test_reproducibility_gate.py`.
    - `rc_validation.sh` keeps the release comparison against `c066` (informational, different code) separate from the
      gate, and ends with `RC VERDICT`.
    - Pinning: the container's NumPy 2.4.4, SciPy 1.17.1 and scikit-learn 1.8.0 have cp314 macOS arm64 wheels. Pinning
      would still not remove the BLAS difference (macOS 14 wheels use Accelerate), so the Mac keeps its lock.
  - **Packaging and source control.**
    - `package_release.sh` refuses unless `artifacts/rc/PASSED_RUN` names the run. It now also excludes:
      - every raw job file (the spreadsheets carry personal details);
      - uploaded curricula and analysis-job state;
      - the live semantic cache;
      - extracted reference builds;
      - old console logs and backups.

      It writes the zip's sha256. `package_integrity.py` prohibits the same material and expects the gate report.
    - Neither the Mac folder nor the container copy is a git repository. `scripts/mac/finalize_release.sh` handles this
      in two steps:
      - `stage` initialises a repository if needed and stages only code, tests, scripts, docs, configuration, metadata,
        curated evaluation data and the pinned recordings (per `.gitignore`), refusing prohibited files;
      - `commit` commits and packages.
  - **New candidate `0534d6e1d06a617f`** (container reference build).
    - Code fingerprint `3e93f815…`; content digest `1f4b2604…b7b8`; REPLAY_VERIFIED_RUN; publish PASS.
    - Database integrity PASS; gap QA 0 held; agents COMPLETE.
    - Backend 867 passed, 0 failed, 1 skipped, with or without `SEMANTIC_MODE=replay` exported.
    - Against `c066`: all 21 authoritative metrics are identical. 11 files changed, each explained in
      `docs/FINAL_RELEASE_REPORT.md`. The protected release is unchanged (`305eb75b…455c`).
  - **Phase 9 (NIRF): INCOMPLETE.** The NIRF ranking page and department syllabus PDFs are not present in the
    repository or the Mac folder. Nothing is produced or claimed.
  - **Phase 11 (human validation): INCOMPLETE.** The 58-item blind set is ready, and its manifest says "none yet (human
    labels pending)". There are no reviewers, labels or agreement figures.
  - **Next.** Run `rc_validation.sh` on the Mac. If it ends with `RC VERDICT: PASS`, run `finalize_release.sh stage`,
    review the staged changes, then run `finalize_release.sh commit`.
