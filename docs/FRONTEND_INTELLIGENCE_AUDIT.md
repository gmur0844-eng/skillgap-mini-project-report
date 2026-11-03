# Frontend intelligence audit

What the dashboard told a reader before this release, what was wrong with it, and what it does now. Status column:
**test** = covered by a Flutter widget test; **Mac** = to be confirmed in the Mac validation run (analyze, test,
build, live API); nothing here is claimed as seen in a browser until that run has passed.

## 1. Upload → dashboard

| Requirement | Now | Status |
|---|---|---|
| Visible progress while a file is processed | the six-step workflow (Add evidence → Validate → Extract → Review → Publish → Analyse) marks the current step; an upload shows a progress bar and "Uploading and processing — the server extracts and validates the document…" | test |
| Success notification with counts | "Curriculum uploaded successfully — 12 courses · 300 topics · 60 learning outcomes. Opening curriculum intelligence…" | test |
| Automatic navigation to Overview | yes, after a usable curriculum | test |
| New-run context, never stale GOLD | `AnalysisContext` (shell): while the analysis is pending / not run / failed / needs review, Overview shows that state and **no request for older results is sent** (asserted on the request log); when ready, every analytics request carries `run_id` of the new run | test |
| Pending state | "Curriculum ingested successfully · Analysis is being prepared" | test |
| Analysis cannot run | "Curriculum uploaded successfully · Curriculum extraction is complete. Analysis has not yet been run." + **Run analysis** | test |
| Analysis endpoint unavailable | stays pending, says "analysis status unavailable …; retrying", keeps checking | test |
| Failure | "Analysis failed", the reason, **Retry analysis**, technical details collapsed, and an explicit "Show the latest published run instead" | test |
| Every page shows run, target curriculum, source document, time, evidence status | top-bar context line: "Run 84d7737c · CBIT R22A · source … · time · n of m evidence requirements incomplete", or the upload state | test |

Backend: `POST /api/v1/analysis/jobs` (start), `GET /api/v1/analysis/jobs[/{id}]`, `GET /api/v1/uploads/{id}`. An
upload is staged by content hash; the analysis runs on a *derived* source manifest (the project manifest is never
edited) and is recorded in run lineage with trigger `UPLOAD_ANALYSIS_JOB`. States: ANALYSIS_PENDING / ANALYSIS_READY /
ANALYSIS_FAILED / NEEDS_REVIEW (quality gates blocked), REVIEW_REQUIRED before start when the extraction needs a
reviewer's name.

## 2. Ingestion page (13-point audit)

| # | Finding before | Now | Status |
|---|---|---|---|
| 1 | title shown twice (shell bar and page) | the shell shows only breadcrumb + context; each page has one title | test (nav) |
| 2 | white text on pale panels | warm dark palette; every text/status colour ≥ 4.5:1 on every background | test (contrast) |
| 3 | one "Succeeded" field for execution, extraction, quality, review | four separate rows: Processing · Extraction · Document quality · Review, plus Overall and Next action | test |
| 4 | raw result (ids, paths) as the result | decision first (headline, counts, confidence, status, next action); ids only under "View raw ingestion details" | test (id not visible) |
| 5 | no first-class empty states | EXTRACTION_FAILED / NO_USABLE_CONTENT / NEEDS_REVIEW come from the backend's single interpretation (`pipelines/ingestion/outcome.py`) | test (backend + UI) |
| 6 | "Succeeded" with zero courses/topics | courses = 0, topics = 0 or confidence = 0 → **"Processing completed, but no usable curriculum content was extracted — review required"**, actions Review extraction / View preprocessing / Return to dashboard; never "Open curriculum intelligence" | test (3 cases) |
| 7 | flagged extraction looked successful | NEEDS_REVIEW: "Extracted, but it needs review before analysis" + "Accept after review" (reviewer's name recorded with the analysis) | test |
| 8 | institution/programme always required | per role, from data: TARGET / PREVIOUS_VERSION need institution, programme, discipline, version; PEER also the source URL; REFERENCE needs discipline and version (may belong to no institution); GENERAL_REFERENCE needs a title and is not analysed | backend test |
| 9 | generic metadata missing | institution, programme, discipline, specialization, degree level, academic year, curriculum version, document role, source URL, licence, title, publisher | — |
| 10 | discipline from a finite list | free text with suggestions from disciplines already analysed | backend test |
| 11 | source selector implied permission to collect from job platforms | "Choose the column layout of your CSV file. The application reads only the file you upload; it does not connect to, log in to or collect from any job platform." The source registry API (`/api/v1/metadata/sources`) reports type, scope, access method, licence and configuration status, with the note that being listed is not permission; it is not yet shown on a screen | — |
| 12 | no workflow | Add evidence → Validate → Extract → Review → Publish → Analyse | test |
| 13 | zero-content extraction could flow downstream | an upload that is not SUCCESSFUL_AND_USABLE cannot start an analysis (backend refuses NOT_ANALYSABLE / REVIEW_REQUIRED) and the UI offers no analysis action | backend + UI test |

Ingestion acceptance test — three states, never collapsed:

| State | Headline |
|---|---|
| SUCCESSFUL_AND_USABLE | Successfully extracted — ready for analysis |
| EXECUTION_SUCCEEDED_BUT_NO_USABLE_CONTENT | Processing completed, but no usable curriculum content was extracted — review required |
| EXECUTION_FAILED | Processing failed — review error details |

An upload that fails before processing (validation, size, type) shows "Upload failed", the reason in words, Retry,
and collapsed technical details.

## 3. Visual redesign

| Before | Now |
|---|---|
| blue/purple gradients, a wall of KPI cards, pill badges, uppercase labels | warm near-black (#0F0E0C) and off-white (#EDE8DF), one brass accent (#CDB077); no gradients, no shadows; outlined status tags written in words; sentence case |
| Overview = numbers first | Overview = **briefing**: the key finding as a headline, "What this briefing rests on" (40) beside "From industry evidence to the curriculum" (60), numbered findings (01, 02 …) each linking to its evidence, skills to watch, "Can I trust this?" beside the evidence requirements, and the raw counts last under "Analysis coverage", each with its scope |
| codes in the UI (SAFE_MODE, SAME_CONCEPT, INSUFFICIENT_DATA …) | words (AI interpretation is advisory, Equivalent concept, Not enough time periods); the code stays in the tooltip |
| icon-heavy sidebar | four typographic groups — Intelligence, Explore, Evidence, System — primary entries first, tables and technical screens after; icons only when collapsed |
| flat search list | search as a command surface: results grouped by Courses, Topics, Concepts, Industry skills, Skill taxonomy, Occupations, Companies, Job postings |
| graph edges without meaning | each edge names its mapping kind (topic → concept, curriculum → reference curriculum, industry skill → skill taxonomy, …) |
| recommendations as boxed cards | numbered editorial entries with the evidence chain on demand; candidates **withheld for review** listed separately |

Typography: Instrument Serif (display), IBM Plex Sans (text), IBM Plex Mono (code), all SIL OFL, fetched by
`scripts/mac/fetch_fonts.sh`; if they cannot be fetched the theme falls back to Georgia / Helvetica Neue / Menlo and
the build still works. Motion: 140 / 220 / 320 ms. Layout: 1,180 px measure, 40/60 splits that stack under 860 px.

## 4. Acceptance questions

| Question | Answer |
|---|---|
| Does the first screen say what is true, not just how much data there is? | yes — the key finding is the headline; counts come last |
| Is every number scoped? | yes — each coverage row names its population and has its source in a tooltip |
| Can a reader tell a gap from thin evidence? | yes — "Evidence-supported gap" vs "Demand too thin to state a gap" per skill |
| Is the AI's role honest? | yes — "AI interpretation is advisory"; no model decision changes results; nothing is called human-validated |
| After an upload, can old results be mistaken for new ones? | no — tested on the request log |
| Can a zero-content extraction look successful? | no — tested for zero courses, zero topics, confidence 0 |
| Are internal ids the primary result anywhere? | no — tested on the ingestion result |
| Does every finding lead to its evidence? | yes — each finding links to its screen |
| Is it legible? | contrast ≥ 4.5:1 tested for every text and status colour on every background |
| Does it look like a generic AI dashboard template? | the design avoids the template markers listed above; whether it *reads* as distinctive is a judgement for the reviewer after the Mac run |

## 5. Product abstraction (second pass)

The question every screen answers first, then why, then the evidence, then how it was calculated, and only last the
implementation. Codes, run ids, model names and database terms appear only inside "Technical details" panels.

### System health → "Is the current analysis ready to use?"

Before: six equal component cards (API, database, model, semantic, data, pipeline) in which advisory AI and incomplete
evidence looked like failures. Now (`GET /api/v1/readiness`, every state derived from the run's GOLD):

| Layer | Content |
|---|---|
| Answer | "Curriculum intelligence is ready" + one sentence |
| Four states | Analysis *Ready* (health gates allowed, target curriculum present) · Evidence *Available with limitations* (core curriculum / industry / taxonomy evidence present, at least one other dimension limited) · AI interpretation *Advisory* (semantic gate not passed) · Traceability *Complete* (8 checks: hashed sources, postings to file + row, demand to postings, every withheld/suppressed item with a reason, graph edges with provenance, no dangling edges, run digest) |
| Evidence coverage | Curriculum · Industry · Skill taxonomy · Peer curricula · Industry trends · Occupation mapping; every limited row opens to *what is missing / why it matters / what would resolve it* |
| What to know | three sentences generated from the same states |
| AI interpretation | advisory explanation, why, what it affects, what remains authoritative |
| Freshness | last successful analysis, curriculum analysed, dates of industry evidence |
| Technical details (collapsed) | run id, pipeline version, code fingerprint, config hash, content digest, semantic mode and gate checks, decisions, effects blocked, evidence requirements, analytics gates, graph checks, live service components |

Nothing was removed; it was moved to the right layer. The states are never inflated: trends stay *Not established*,
peers and occupations *Partial* until the evidence exists.

### Overview

Key finding in plain words ("No evidence-supported skill gaps identified" + the reason) → a line of figures
(confirmed · partial · covered, not KPI cards) → the flow Industry → Skills → Curriculum → Gaps → Actions, each stage
opening to its evidence → where attention is needed (each skill opens its **evidence thread**) → limitations →
recommended actions as decisions (a withheld candidate reads "Review · SQL", never "Recommendation") → curriculum
evolution and peer perspective → trust → scoped raw counts.

**Evidence thread** (signature interaction): postings → skill → curriculum courses → coverage → action, drawn link by
link from `GET /api/v1/intelligence/evidence-trace`; a link the data cannot establish says "Evidence is insufficient to
establish this relationship."

### Other screens

Skill gaps as a numbered editorial list (industry signal · curriculum · interpretation, evidence thread on demand);
recommendations as decisions (issued · withheld for review · not recommended, with human reasons); Industry opens with
"N job postings currently inform this analysis" and a one-sentence trend state; peer comparison states that institutions
are compared, never ranked; navigation trimmed to Intelligence / Explore / Evidence / System with technical tables
folded under "More views"; search as a keyboard-driven command surface (↑ ↓ Enter Esc) grouped by kind; methods in words
("Textual similarity" for TF-IDF cosine); sections reveal in sequence (60 ms apart) and every motion is switched off with
the system's reduced-motion setting.
