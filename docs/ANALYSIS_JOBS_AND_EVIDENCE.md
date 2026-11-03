# Adding evidence and running an analysis

*Written 2026-10-11, updated 2026-10-15. Describes the behaviour of the code in this repository; nothing here changes a
published run. The page formerly called "Add evidence" is now **New analysis** in the navigation.*

## 1. Add evidence (New analysis)

**One draft per session.** The form is kept in the app's analysis context, not in the page. Leaving Add evidence and
coming back restores:

- the kind of evidence and every field;
- the chosen file (its bytes stay in memory);
- the document suggestions and the analysis options.

The draft is cleared only by:

- **Add another file**, after an upload has succeeded;
- **Clear form**, which always asks first.

A browser reload starts an empty form: browsers do not let a page keep a chosen file, and the form says so next to the
file.

**Only what is needed comes first.** The role policy (`data/metadata/document_roles.json`) decides the required fields:

- **Curriculum:** institution, programme, discipline and curriculum version.

Each required field says why it is needed. Recommended fields (academic year, degree level, specialisation, …) sit under
**More details (optional)**.

**Values read from the document.** When a curriculum file is chosen, `POST /api/v1/ingestion/curriculum/inspect`
(`services/metadata_inference.py`) reads its first three pages. It suggests the institution, discipline, programme,
regulation (curriculum version), academic year and degree level.

- **Found:** one consistent reading. The empty field is pre-filled, with the page and the exact line shown under it,
  for the person to check.
- **Uncertain:** the document gives several readings. All of them are offered as choices; none is picked.
- **Absent:** nothing is suggested.

The rules for reading are:

- Nothing is stored by the inspect call.
- The discipline is matched against disciplines the system has already seen, and otherwise taken only from
  heading-like lines.
- Vision statements and course titles are never read as disciplines.

## 2. Is an upload ready for analysis?

The upload outcome applies the analysis's own course checks (`knowledge_engine/readiness.py`). It uses the same SILVER
build and the same document-health thresholds as the pipeline:

- at least 5 valid courses;
- at least 90% of courses with a title;
- topic noise at most 50%;
- every topic traceable to a course and a page.

A FAIL makes the upload NEEDS_REVIEW, with the failing check in words.

This closes a real disagreement. An upload with four "courses" was called ready for analysis, but they were a scheme
table's TOTAL rows. The pipeline then failed the same file. The outcome also reports `structuring_status` separately
from text extraction.

## 3. Curricula from other institutions

`pipelines/preprocessing/curriculum_structuring.py` reads courses from:

- **The built-in code shapes.**
- **Shapes the document itself demonstrates.** A shape is learned when at least three distinct codes head
  scheme-of-instruction rows: a code, a title and at least three credit/hour/mark cells. For example
  `U26BS130MA Calculus & Linear Algebra 3 - - 3 60 40 3` teaches the shape of `U26BS130MA` and `UII26ES120CS`.
  - Nothing is learned from prose.
  - The shape applies to that document only.
  - It is recorded in `learned_code_shapes`.
- **Labelled header blocks.** These are `Course Code : X` inside a line, or a line that is only `Course Code  X`, with a
  `Course Title …` field below it.
  - A labelled course takes the semester its own block states, such as "SYLLABUS FOR B.E. I-SEMESTER" or a heading
    directly above it on the same page.
  - It never takes a heading carried over from earlier pages, which in the detailed-syllabus section is not evidence
    about the course.

Table aggregate rows (`TOTAL 16 …`, `GRAND TOTAL 24`) are never courses (`reference_data/non_course_identifiers.json`).

| Document | Before | After |
|---|---|---|
| JNTU R22 B.Tech. CSE (154 pages) | 0 courses | 100 courses, semesters I–VIII, no unattributed topics |
| Vasavi R26 B.E. CSE (AIML) (64 pages) | 4 "courses" (table totals) holding all 1,319 topics | 25 courses, 23 with their stated semester |
| NITT B.Tech. CSE (peer) | 2,715 of 2,914 topic lines credited to one course | 95 courses carry their own topics |
| CBIT R22, CBIT R22A, AICTE, IITK, NITW, the earlier upload | — | identical (pinned digests in `tests/test_institution_formats.py`) |

The NITT change alters that peer's data, and therefore the peer comparison of any analysis that uses it. It is a
correction of a misattribution, recorded with its reason next to the pinned digest.

## 4. Standalone analysis and optional capabilities

A new institution's curriculum is analysed on its own. Another institution's curriculum is never used as its target or
its earlier version (`services/analysis_jobs.derived_manifest`).

`POST /api/v1/analysis/jobs` accepts `options: {"peers": bool, "industry": bool}`. Both default to true. Leaving one out:

- removes its sources from the analysis context;
- makes the pipeline report its analyses `NOT_REQUESTED`.

| Option left out | Analyses reported NOT_REQUESTED |
|---|---|
| peers | `peer_benchmark` |
| industry | `industry_gap`, `industry_demand`, `recommendations`, `skill_taxonomy` (ESCO is loaded together with the postings) |

NOT_REQUESTED is different from BLOCKED, which means the evidence was wanted but missing or unusable:

- An analysis is **ready** when its own curriculum passed and nothing it was asked to do is blocked.
- A **requested but blocked** capability still makes it NEEDS_REVIEW.
- When the **analysed curriculum itself fails** its document checks, that failure is the review reason, stated in words.

### Choosing peers explicitly (2026-10-15)

`GET /api/v1/analysis/comparison-targets?upload_id=…` (or `?discipline=…` before anything is uploaded) lists the peer
curricula, each with its discipline profile and whether it is comparable with the analysed curriculum. The New
analysis form shows this list under *Peer comparison*: comparable peers start chosen, peers of another discipline are
listed with the reason and cannot be chosen.

`options.peer_ids: [doc_id, …]` keeps only those peers in the analysis context. A peer that is unknown or of another
discipline is refused with `422 INVALID_PEER_SELECTION`, naming each one; **no other peer is used in its place**. An
empty choice means no peer comparison (reported NOT_REQUESTED, as with `peers: false`).

### Duplicate submissions

Submitting the same upload with the same options while its job is still running returns that job (with
`duplicate_submission: true`) instead of starting a second run. Different options while a job runs are refused with
`JOB_RUNNING`, as before.

### Discipline profile

Each job records the `discipline_profile` it was analysed under. What the profile changes in the analysis is described
in `docs/DISCIPLINE_SUPPORT.md`.

## 5. Live progress

The pipeline's stage observer (`knowledge_engine/observability.RunObserver`) reports each stage's start and end to a
listener. `services/analysis_progress.py` turns these events into the job's `phases`, persisted with the job record:

- **Phases**, in the order they actually run: reading the documents, skill intelligence, curriculum understanding,
  skill-gap reasoning, recommendations, peer comparison, discipline-to-industry relevance, finalising.
- **Steps**, each with its timestamps, duration and own counts (pages, courses, postings, …). A document step says
  "document k of n".
- **States:** waiting, in progress, done, needs review, failed, not run (with the gate reason) and not requested.
- **No percentages.** A final status is never published while a step is still shown running.

A listener error never affects the run.

Endpoints:

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/analysis/jobs/{id}` | The job with its phases. |
| `GET /api/v1/analysis/jobs/{id}/events` | Server-Sent Events: the complete job record on connect and after every change, until the job ends. Reconnecting simply resumes. |
| `GET /api/v1/analysis/jobs/active` | The job this server is running, used to reconnect after a page reload. |
| `POST /api/v1/analysis/jobs/{id}/retry` | Starts the same upload again with the same options and reviewer. |
| `GET /api/v1/analysis/jobs` | Recent jobs, newest first (the History page; Overview shows the latest four). |

A job left PENDING by a server that stopped mid-run is reported ANALYSIS_FAILED as interrupted, and can be retried.

The Flutter app reads the job record once a second. It shows the phases on the Overview while the analysis runs, and
after a reload it finds the running job again. The person can use the rest of the app meanwhile.

## 6. Page guides

Every page has an **About this page** line under the top bar (`flutter_app/lib/shell/page_guides.dart`). It says what
the page shows; opened, it adds why it matters, the evidence behind it and what to do next, with a link. The page's own
headline still states what was found.

## 7. Comparing two runs: curriculum, evidence or method (2026-10-16)

`GET /api/v1/analysis/run-comparison?a=<run>&b=<run>` (`services/run_comparison.py`; `b` defaults to the published
run) reads only the stored run files and separates three kinds of change:

| Kind | Compared |
|---|---|
| Curriculum | the analysed curricula (TARGET, PREVIOUS_VERSION) and the comparison curricula (PEER, REFERENCE), by content hash |
| Industry evidence | the combined hash of the job-posting and taxonomy files, and the posting files themselves |
| Method | pipeline version, curriculum parser, analysis code, configuration, semantic layer, similarity backend, discipline profile, analysis scope |

The `attribution` sentences say what a difference in results can come from. A method change is never attributed to
the curriculum: if the method differs, the reader is told to analyse both curricula with the same method and
evidence to isolate a curriculum change. Example (real): the protected release `c066b227857f9eaf` and the published
run `0534d6e1d06a617f` share their curricula and evidence and differ in the analysis code and the semantic layer, so
any difference between them comes from the method.

History offers this as **Compare with the published analysis** on every ready analysis.

## 8. Recommendations: how to check they worked

Each issued recommendation carries `verification` (`intelligence_service.verification_criteria`): what the next
analysis should measure if the change was made -- the skill taught in the named course beyond its current depth (or,
for a missing skill, taught in a named course), the gap no longer classified partial or missing, learning outcomes
that state the skill, and demand that still holds with newer postings. They are derived from the recommendation's
own gap and evidence; no number is predicted.

