# Semantic Relationship Validation — Curriculum Intelligence (Google Form)

The reviewer-facing form for the independent human validation of the semantic relationships. It presents the
**existing frozen 48-case subset** (`data/evaluation/semantic_gold/computer-science-and-engineering/v1/subset.json`)
of the **frozen 88-case benchmark** (`data/evaluation/semantic_benchmark_v1/benchmark.json`,
SHA-256 `94b4e79c49bc2c7a0c5bce0234298f9ebada568c1e767ee8651aac19ac3722b7`). No case was selected, rewritten,
regenerated, reordered or added for the form. This is only the reviewer interface: the benchmark, label definitions,
promotion gate (v3), semantic thresholds, model, production data and GOLD outputs are unchanged.

## Files

| File | What it is |
|---|---|
| `scripts/evaluation/create_semantic_validation_form.gs` | Google Apps Script that creates the complete form (generated; do not edit by hand) |
| `scripts/evaluation/semantic_validation.py form --package <dir>` | regenerates the script from the frozen subset and writes the two reports below; refuses if a check fails |
| `data/evaluation/semantic_gold/computer-science-and-engineering/v1/form/form_integrity_report.json` | case integrity and blindness validation |
| `data/evaluation/semantic_gold/computer-science-and-engineering/v1/form/response_mapping.json` | response export specification |
| `scripts/evaluation/simulate_form.js` | runs the Apps Script against a recording mock of Google Forms (node) so the exact form a reviewer would see is checked without a Google account |
| `backend/tests/test_semantic_validation_package.py` (`ReviewerForm`, `ReviewerFormImport`) | tests |

## Create the form (exact steps)

1. Sign in to the Google account that should own the form and its responses, and open
   <https://script.google.com>. Choose **New project**.
2. Delete the contents of `Code.gs`. Paste the whole of `scripts/evaluation/create_semantic_validation_form.gs`
   (about 64 KB). Rename the project, e.g. *Semantic validation form*. Press **Save** (⌘S).
3. In the function selector above the editor, choose **createSemanticValidationForm**, then press **Run**.
4. Authorise the script the first time it runs: **Review permissions** → choose the account → **Advanced** →
   **Go to *Semantic validation form* (unsafe)** → **Allow**. The warning appears because this is your own unverified
   script. The script asks only for Google Forms access; Drive access is requested only when you run
   `exportResponsesLongCsv` later.
5. Wait until the run finishes (about a minute for 194 questions). Open **Execution log**. It prints:
   ```
   Form created: Semantic Relationship Validation — Curriculum Intelligence
   Form ID:       <id>
   EDIT URL:      https://docs.google.com/forms/d/<id>/edit
   RESPONDER URL: https://docs.google.com/forms/d/e/<...>/viewform
   Short URL:     https://forms.gle/<...>
   Published:     true
   Check:         {"pages":49,"multipleChoice":96,"paragraph":48,"text":1,"other":0,"cases":48,"ok":true}
   ```
   Before it creates anything, the script checks that it holds exactly 48 cases, no duplicates, in subset order, and
   that the SHA-256 of the case texts equals `7631599200adbdfccfd1f54469420492e8f9290e661e6750a5660496bde02fcd`
   (`cases_sha256` in the integrity report). If any of these fails, it stops with an error. After creation, it checks
   the structure of the form it built.
6. Open the **EDIT URL** and preview the form (eye icon). If the form shows **Publish** at the top right, press it. The
   script already asks Google to publish the form, but some accounts do not report the publish state.
7. Send the **RESPONDER URL** to each reviewer separately, each with their own reviewer ID (e.g. `R1`, `R2`). Do
   not tell reviewers anything about the system's answers, and do not show them each other's responses. The form
   does not show a response summary to respondents.

The edit and responder URLs exist only after the script runs in your Google account; this repository cannot create
them. Record them in `form/form_integrity_report.json` → `deployed` if you want them kept with the package (optional).

## What the reviewer sees

**Title:** Semantic Relationship Validation — Curriculum Intelligence

**Description:** the exact text specified, which says there are 48 cases, asks for an independent judgment, and
states that the AI prediction and expected answers are not shown.

**Reviewer information:** only **Reviewer ID** (required short answer). The form collects no name, email (email
collection is set to *Do not collect*), college, branch, year, experience, faculty/student status or any other
personal information. Sign-in is not required, and "one response per user" is off because it would need sign-in.

**How to judge** (one page): the label definitions are the project's established label schema
(`relationship-labels-v1`, `semantic_validation.py LABEL_SCHEMA`). "A"/"B" are written as "Concept A"/"Concept B" so
they cannot be confused with the answer letters:

| Choice | Definition | Stored as |
|---|---|---|
| A — Same concept | Concept A and Concept B denote the same thing in this context | SAME_CONCEPT |
| B — Parent / broader concept | Concept A is a broader concept that includes Concept B | PARENT |
| C — Child / more specific concept | Concept A is a narrower concept, a kind or part of Concept B | CHILD |
| D — Related | clearly connected, but neither equal nor one inside the other | RELATED |
| E — Partial overlap | they share part of their meaning | PARTIAL_OVERLAP |
| F — Unrelated | different things (e.g. a shared word with a different sense) | UNRELATED |
| G — Ambiguous | the context allows more than one reading | AMBIGUOUS |
| H — Insufficient evidence | the context does not decide it | INSUFFICIENT_EVIDENCE |

The page also gives the established guidance ("judge only from the text shown; a shared word, or one phrase inside
another, is not enough for Same concept or for a parent / child relationship") and the confidence anchors: High =
certain, Moderate = fairly sure, Low = guess. The "Stored as" column is not shown in the form.

The worked examples in `HUMAN_VALIDATION_INSTRUCTIONS.md` ("AWS" → "cloud technologies", "Angular") are **not** in
the form. Those pairs are cases of the subset, so the examples would show reviewers the expected answer.

**Each case** (one page per case, in subset order):

* page title **Case *n* of 48**;
* **Concept A** and its **context / evidence**: every context line of the benchmark case, verbatim and in
  benchmark order, each labelled by its source (Source text, Job title, Course title, Unit title, Learning outcome);
* **Concept B** and its **context / evidence**: the reference concept description and hierarchy, or the curriculum
  lines for topic-to-topic cases, verbatim. Text is exactly as in the source documents, including any `**`
  emphasis copied from job postings;
* **Case *n* (Ref. *case_id*) — Relationship**: required, A–H;
* **Case *n* (Ref. *case_id*) — Confidence**: required, High / Moderate / Low;
* **Case *n* (Ref. *case_id*) — Optional reasoning**: optional paragraph.

The reference id (e.g. `bm1-001`) is a neutral case identifier. It is shown so that responses map unambiguously to
cases.

## Reviewer blindness

Only these benchmark fields reach the form: `benchmark_id`, `left_text`, `left_context`, `right_concept`,
`right_context`. Every other field is excluded and listed in the integrity report under
`blindness.excluded_benchmark_fields`:
* `label` (development label);
* `label_source`;
* `rationale`;
* `reviewer`;
* `kind` (which would reveal diagnostic/hard cases);
* `tags`;
* candidate/evidence-span ids;
* hashes and timestamps.

The form never shows a Qwen, Claude or system prediction, an expected or gold label, a model confidence or score, a
benchmark result, the promotion gate, whether a model was correct, or why a case was selected.

How this is checked:
* `form` runs the generated script in `simulate_form.js`;
* it confirms that every evidence line appears verbatim on its case page;
* it then scans all other visible text for label codes, case kinds, development tags and words such as Qwen, Claude,
  gold, gate, score, benchmark, correct, assistant, development, adjudication and rationale;
* it confirms that the only free-text question is the Reviewer ID.

## Case integrity validation

Result of `python3 scripts/evaluation/semantic_validation.py form --package data/evaluation/semantic_gold/computer-science-and-engineering/v1`:

```
case_count      = 48
duplicate_ids   = []
missing_ids     = []
modified_cases  = []
invented_ids    = []
order_matches_subset = true
leaks_found     = []
rendered_check  = PASSED (1 Reviewer ID, 49 pages, 96 multiple choice, 48 paragraph)
passed          = true
```

Case ids, in subset order: bm1-001, bm1-002, bm1-003, bm1-006, bm1-007, bm1-009, bm1-010, bm1-013, bm1-014, bm1-015,
bm1-018, bm1-019, bm1-020, bm1-021, bm1-022, bm1-023, bm1-026, bm1-027, bm1-029, bm1-031, bm1-034, bm1-035, bm1-037,
bm1-038, bm1-043, bm1-045, bm1-046, bm1-050, bm1-052, bm1-053, bm1-057, bm1-058, bm1-059, bm1-060, bm1-061, bm1-063,
bm1-066, bm1-069, bm1-070, bm1-071, bm1-072, bm1-075, bm1-076, bm1-078, bm1-080, bm1-084, bm1-086, bm1-087.

What each check means:
* `missing_ids`: subset ids absent from the frozen benchmark.
* `modified_cases`: any difference between a form case and its benchmark case, compared field by field: Concept A,
  Concept B, every context line and its source.
* The benchmark is opened only after its SHA-256 matches the package manifest.

The previous form showed only the first four context lines of Concept A and only the description of Concept B. This
form shows every line, so nothing is cut.

## Response export

`form/response_mapping.json`, one row per reviewer × case (48 rows per reviewer):

| Column | Source | Values |
|---|---|---|
| `case_id` | the reference in the question title `Case n (Ref. <case_id>) — …` | the benchmark's `benchmark_id` |
| `reviewer_id` | the **Reviewer ID** answer | as entered (pseudonymous) |
| `relationship_label` | `… — Relationship` | A→SAME_CONCEPT, B→PARENT, C→CHILD, D→RELATED, E→PARTIAL_OVERLAP, F→UNRELATED, G→AMBIGUOUS, H→INSUFFICIENT_EVIDENCE |
| `confidence` | `… — Confidence` | HIGH / MODERATE / LOW |
| `reasoning` | `… — Optional reasoning` | text or empty |
| `timestamp` | Google Forms' `Timestamp` | submission time |

The form contains no model output. Model predictions are joined later on `case_id`, by `semantic_validation.py
evaluate`, after the labels are frozen.

You can get the responses out in either of two ways:

* **In Google:** set `FORM_ID` at the bottom of the script to the logged Form ID, then run
  `exportResponsesLongCsv`. It writes `semantic_validation_responses_long.csv` with exactly these six columns to your
  Drive.
* **In the project:** Form → **Responses** → **Link to Sheets** → File → Download → CSV, then:
  ```
  python3 scripts/evaluation/semantic_validation.py import-form \
    --package data/evaluation/semantic_gold/computer-science-and-engineering/v1 \
    --csv responses.csv --long-out responses_long.csv
  ```
  This stores one immutable label file per reviewer in `labels/` and writes the six-column long CSV.

  It refuses the import if:
  * a response names a case outside the frozen subset;
  * a choice or confidence outside the form's values appears;
  * a reviewer ID refers to the assistant or a model;
  * a label file for that reviewer already exists.

Then continue with the procedure in `HUMAN_VALIDATION_INSTRUCTIONS.md`:
1. `agreement`
2. `adjudication-sheet` / `adjudicate`
3. `freeze`
4. `evaluate`

The semantic engine stays in SAFE_MODE until that procedure has passed the pre-declared gate.

## Reviewer responses as research records (2026-10-22)

`import-form` stores **independent** label sets in `labels/`; only those count for agreement, gold and the gate.
Responses whose independence is not established are kept apart, verbatim, as research records:
`semantic_validation.py import-responses` → `<package>/responses/`. Code:
* `backend/app/knowledge_engine/semantic_responses.py`: reading, records, storage, comparison, metrics;
* `backend/app/services/semantic_validation_service.py` and `backend/app/api/v1/semantic_validation_api.py`;
* screen: **Semantic decisions → Reviewer validation**;
* tests: `backend/tests/test_semantic_responses.py` and `flutter_app/test/reviewer_validation_test.dart`.

### Workbook schema and mapping

The Google Forms export: one worksheet **Form responses 1**. Every worksheet is read, and a sheet without a
**Reviewer ID** column and question columns is reported as SKIPPED.
* One row per submission.
* `Timestamp`.
* `Reviewer ID`.
* Three columns per case, titled `Case n (Ref. <case_id>) — Relationship | Confidence | Optional reasoning`. These
  are the titles the form generator writes (`QUESTION_RE`; a test keeps the two definitions identical).

The case id in the title links each answer to the frozen subset. Mapping:

| Field | Values read | Anything else |
|---|---|---|
| Relationship | the form's choices `A — Same concept` … `H — Insufficient evidence` → the eight codes of `relationship-labels-v1`; the words alone or the code also match | INVALID, kept verbatim |
| Confidence | High / Moderate / Low | INVALID |

Every record keeps:
* the raw cell text next to the code it was read as;
* the reasoning exactly as written;
* the file name and SHA-256, the sheet, the row, the cell of each answer and the submission timestamp.

The source workbook is kept unchanged in `responses/source/`.

### Statuses

| Status | Meaning |
|---|---|
| COMPLETED | a valid relationship |
| PENDING | nothing answered |
| AMBIGUOUS | a confidence or reasoning without a relationship; not read as any relationship |
| INVALID | a relationship or confidence outside the form's values |
| CONFLICTING | one reviewer submitted twice with different answers; both kept |
| NOT_IN_SOURCE | the file has no column for the question |

### How the answers were produced (`--source`)

Every import states this, and the statement is kept with each record and shown on the screen:

| Source | Meaning |
|---|---|
| `HUMAN_UNASSISTED` | a person answered from the form alone |
| `HUMAN_AI_ASSISTED` | a person answered after reading about the topics with an AI assistant |
| `NOT_STATED` | not stated |

None of the three makes a record count as an independent label (`counts_as_independent_label: false`). A set of
genuinely independent, unassisted human labels goes through `import-form`.

### Import, compare, export

```
P=data/evaluation/semantic_gold/computer-science-and-engineering/v1
python3 scripts/evaluation/semantic_validation.py import-responses --package $P --file <responses.xlsx> \
    --source HUMAN_AI_ASSISTED --reviewers R02,R03 --note "<who stated it, when>"
python3 scripts/evaluation/semantic_validation.py compare-responses --package $P --a R02 --b R03 --out r02_r03.csv
```

Importing the same responses again changes nothing (UNCHANGED). Different responses for a reviewer who already has
a file are refused (CONFLICT, HTTP 409); stored responses are never overwritten.

API (`package` defaults to the first package):

| Endpoint | Returns |
|---|---|
| `GET /api/v1/semantic-validation/packages` | packages, imported reviewers, label schema |
| `GET /api/v1/semantic-validation/questions` | the 48 questions with their evidence, and `ai_reference` |
| `GET /api/v1/semantic-validation/assessments?reviewer=R02&label=CHILD&status=PENDING&question_id=` | records, filtered |
| `GET /api/v1/semantic-validation/assessments/bm1-001/R02` | one question, one reviewer |
| `GET /api/v1/semantic-validation/missing?reviewers=R02,R03` | questions not completed |
| `GET /api/v1/semantic-validation/compare?a=R02&b=R03&outcome=DISAGREE` | per question, with metrics |
| `GET /api/v1/semantic-validation/metrics?a=R02&b=R03` | metrics with definitions |
| `GET /api/v1/semantic-validation/export.csv?reviewers=R02,R03` | verbatim records with source location |
| `POST /api/v1/semantic-validation/import` | multipart `file`, `source`, `reviewers`, `note` |

The assistant's development label of a case is returned only as `questions[].ai_reference`. It is marked
`is_human_judgment: false` and is never part of any metric.

Storage is the package's files, like the rest of the validation workflow. No database table was added; the
validation records are not in PostgreSQL either.

### Metrics, and their denominators

| Metric | Definition |
|---|---|
| questions in package | the frozen subset |
| assessments present | per reviewer: questions COMPLETED |
| completion rate | completed / questions in package |
| both completed | questions COMPLETED by both reviewers; this is the denominator for agreement |
| agreements / disagreements | both-completed questions with the same / different relationship; a missing answer is never a disagreement |
| agreement rate | agreements / both completed |
| Cohen's kappa | over the both-completed questions (`semantic_eval.cohen_kappa`) |
| label and confidence distributions | per reviewer, completed answers |

A metric that cannot be computed is null, and `unavailable` gives the reason.

### The 2026-10-22 workbook (`Semantic_Relationship_Validation_R01_to_R05.xlsx`, SHA-256 `3d9eae28…49ae04`)

**What it contains**
* One sheet with five rows, R01 to R05.
* All 48 subset cases, in subset order, and no other case.
* No formulas or merged cells.
* All 240 answers are COMPLETED, with a valid relationship and confidence. There are no blank, invalid, ambiguous
  or conflicting answers. Every optional reasoning box is filled.

**Source, as recorded**
* The project owner stated that R02 and R03 used AI to read about the topics, then answered themselves. They are
  imported as `HUMAN_AI_ASSISTED`.
* How R01, R04 and R05 answered was not stated: `NOT_STATED`.
* All five submissions carry the same timestamp, `2026-10-22 09:03:53.725`. Independent form submissions are
  stamped when each is sent, so the rows were assembled into one sheet rather than exported submission by submission.
  This is recorded with every import.

**R02 vs R03**
* 48 questions answered by both.
* 45 agreements, 3 disagreements: agreement rate 0.9375, Cohen's kappa 0.9245.

| Case | Concept A → B | R02 | R03 |
|---|---|---|---|
| bm1-043 | Information Management → knowledge management | Related (moderate) | Partial overlap (moderate) |
| bm1-045 | ml → machine learning | Ambiguous (moderate) | Same concept (moderate) |
| bm1-046 | ml → ML (computer programming) | Ambiguous (low) | Unrelated (moderate) |

* Label distribution:
  * R02: Child 12, Same concept 10, Partial overlap 7, Unrelated 7, Parent 4, Related 3, Insufficient evidence 3,
    Ambiguous 2.
  * R03: Child 12, Same concept 11, Partial overlap 8, Unrelated 8, Parent 4, Insufficient evidence 3, Related 2.
* Confidence:
  * R02: high 31, moderate 16, low 1.
  * R03: high 29, moderate 16, low 3.
* Agreement of each reviewer with the assistant's development labels, which the form did not show: 0.46 to 0.56
  (raw). There is no sign that the development labels were seen.

**Not done.** No adjudication, gold freeze or evaluation was run. The gate still has 0 independent label sets
(`labels/` is empty), and the semantic engine stays in SAFE_MODE.
