# Discipline support

*Written 2026-10-15. Describes the code in this repository.*

One shared engine analyses every discipline. What differs per discipline is data, in
`data/metadata/discipline_profiles.json` (version `discipline-profiles-v1`), read by
`backend/app/knowledge_engine/discipline_profiles.py`. A new discipline is a new entry; no code changes.

## What a profile holds

| Field | Used for |
|---|---|
| `aliases` | Resolving the free-text discipline of a curriculum ("B.Tech CSE (AI & ML)" → CSE). Unknown or ambiguous text resolves to *no profile*; it is never guessed. "ME" and "CE" are deliberately not aliases. |
| `industry_populations` | The job-posting populations (`population_id` in the source manifest) that count as evidence of this discipline's demand. |
| `knowledge_areas`, `occupation_examples` | Orientation for readers only. Never demand evidence; never used to assert that a skill is required. |
| `validation` | A plain statement of how far the profile has been validated with real data. |

## What the guard changes in an analysis (`pipeline.py`)

| Evidence | Rule | When it does not apply |
|---|---|---|
| Job postings | Used only when their population is listed in the analysed curriculum's profile. Excluded postings never enter the run id. | No relevant postings: `industry_gap`, `industry_demand`, `recommendations`, `skill_taxonomy` are **NOT_APPLICABLE** with the reason; the curriculum is analysed on its own. |
| Reference curricula | Compared only within the same profile. | `reference_mapping` NOT_APPLICABLE; gap classification and recommendations, which need a reference of the same discipline, NOT_APPLICABLE too. |
| Peer curricula | Compared only within the same profile; a chosen peer of another discipline is refused. | `peer_benchmark` NOT_APPLICABLE, naming the excluded peers. |

NOT_APPLICABLE does not make an analysis NEEDS_REVIEW; only BLOCKED (wanted but missing or unusable evidence) does.
The run report records `discipline_profile`, and, when anything was left out, `industry_exclusion` and
`not_comparable_documents`.

The published CSE manifest is unaffected: its target, reference and three peers are all CSE and all 15 job-posting
sources belong to populations listed for CSE (`tests/test_discipline_profiles.py::ReleaseManifestUnchanged`). The run
id of a new run of that manifest still changes, because the code fingerprint changed; published runs are never
recomputed.

## Current support status (from the evidence present, `GET /api/v1/metadata/discipline-profiles`)

| Discipline | Curriculum analysis | Industry demand and gaps | Reference mapping | Peer comparison | Validated with real data |
|---|---|---|---|---|---|
| CSE | yes | yes (15 sources) | yes (AICTE model curriculum) | yes (3 peers) | **yes**: the published release |
| AI & DS | yes | yes (same postings) | yes (AICTE AI & DS model curriculum 2021, registered 2026-10-21; electives not extracted, see below) | no peer supplied | no |
| IT | yes | yes (same postings) | no IT reference supplied | no peer supplied | no |
| ECE, EEE, Mechanical, Civil | yes | no relevant postings supplied | yes (AICTE model curricula, registered 2026-10-22; see below) | no peer supplied | no |

Consequences worth knowing:

- An **AI & DS** curriculum is compared with the AICTE AI & DS model curriculum, so it gets gap classification and
  recommendations too. That reference is not part of the default (CSE) analysis: it is registered in
  `data/metadata/discipline_references.json` and joins an uploaded curriculum's analysis context only when the upload
  is of its discipline and the context has no reference of it (`analysis_jobs.derived_manifest`).
- An **IT** curriculum gets industry demand, but no gap classification or recommendations: those are defined against a
  reference curriculum of the same discipline, and no IT reference has been supplied.
- An **ECE, EEE, Mechanical or Civil** curriculum is compared with its AICTE model curriculum (reference mapping), the
  same way as AI & DS. It still gets no industry demand, gaps or recommendations: no job postings of those
  populations have been supplied.
- A curriculum whose discipline is **empty or not recognised** is analysed on its own, and the reason says how to fix
  it (use a configured discipline name or add an alias).

## Registered references of other disciplines

| Reference | Parse check (2026-10-22) | Known limitations |
|---|---|---|
| `aicte-ug-cse-aids-model`, AICTE Model Curriculum for UG CSE (AI & DS), 2021, 157 pages, sha256 `2b60b806…3dcc` | 47 courses (45 with a semester), 86 units, 1,974 clean topics of 2,320 (on 2026-10-21, before the parser read "Course Contents:": 46 courses, 1,580 clean topics) | The 11 suggested professional electives in Appendix I (computer vision, NLP, advanced ML, ...) use the placeholder code XXNNN and are not extracted as courses, so elective-level AI topics are under-represented; one title is cut at a line break (ES203); one title carries a table fragment (AU301); a second "Mathematics- I" (MT102) has no semester. |
| `aicte-ug-ece-model`, AICTE Revised Model Curriculum, UG ECE, 2023, 160 pages, sha256 `99a142b6…7049` | 95 courses (88 with a semester), 47 with topics; 105 units; 3,340 clean topics of 4,398 | Labs, audit courses, open-elective slots and internships have no syllabus text. Slot ES-05 offers two alternative courses, merged under one code. The syllabus section numbers some courses differently from the scheme (scheme EC-10 Microcontrollers is EC-08 in the syllabus, which also uses EC-08 for Analog Circuits). First-year codes appear in two spellings (BS-02 / BS02). |
| `aicte-ug-mech-model`, AICTE Revised Model Curriculum, UG Mechanical, 2023, 162 pages, sha256 `f8e1960d…d641` | 56 courses (all with a semester), 34 with topics; 172 units; 2,196 clean topics of 2,773 | Labs, projects, audit courses and elective slots have no syllabus text. The "Objectives" / "Contents" side labels are not in the text layer, so content is read from its "Heading: list" paragraphs (rule below); a syllabus written as plain prose is not read. |
| `aicte-ug-civil-model`, AICTE Model Curriculum, UG Civil, 2024 edition (PDF created 2023-11-26), 189 pages, sha256 `21fd1b4a…9f61` | 54 courses (53 with a semester), 36 with topics; 199 units; 3,609 clean topics of 4,768 | Elective slots (PCE, MOPCE) and audit courses have no syllabus text. Syllabi written as one prose paragraph (PCC-15, PCC-16, PCC-17) are not read. Two scheme codes have no readable title (BS-01, ES-05) and are set aside. |
| `aicte-ug-eee-model`, pages 191–268 of the AICTE Model Curriculum for UG Engineering & Technology, January 2018, Volume I (Electrical Engineering), 78 pages, sha256 `bf547730…ecf8` | 38 courses (none with a semester), 29 with topics; 181 units; 2,490 clean topics of 3,900 | A derived file: the Electrical Engineering section cut unchanged from the 433-page volume (`qpdf … --pages . 191-268`; the command and the volume's hash are in the registry). The 2018 edition; the section has no semester headings. |

All five files live under `data/raw/curricula/aicte/` (git-ignored); the registry records each one's hash, and the
pipeline refuses a file whose hash differs.

### Parser rules added for these layouts (2026-10-22)

Each rule is generic (no institution or document name) and has a regression test in
`backend/tests/test_parser_structural_rules.py`. Run against the saved pages of every registered curriculum, the CBIT
R22 and R22A targets and the IITK, NITW and NITT peers give byte-identical structured output.

| Rule | Real line it reads |
|---|---|
| The plural label "Course Contents:" opens a syllabus's content, like "Course Content:" | every AICTE model curriculum |
| A course code may be joined to its category tag by a hyphen | `PCC-ME 202  Fluid Mechanics & Hydraulic  3L:1T:0P  4 credits` |
| A code's separator may be a hyphen followed by a space | `PCC- 05 Surveying and Geomatics` |
| A code followed by a year in brackets is a cited standard, not a course | `5. IS269 (2015) Ordinary Portland Cement …` |
| Under a header with a lettered `3L:1T:0P` cell, a bare "Course Contents" or "Contents:" line is a content label | AICTE Civil and Mechanical |
| Under such a header, with no unit heading and no content yet, a "Heading: a; b; c" paragraph opens the content; the numbered reference list after it closes it | AICTE Mechanical |

The first rule also changes two AICTE references of the CSE family, because they label some syllabi the same way:
the CSE reference gains 30 clean Engineering Graphics topics (course ESC-102; 2,242 → 2,272 clean topics) plus two
fragments the noise filter sets aside (one of ESC-102, and "1." under AU-101); its courses, units and outcomes are
unchanged; the AI & DS reference gains 394 clean topics and one course (AU102). The published run
`a6af6bfb7330bdff` was made before this change and is not recomputed; a new run of the default manifest will include
the Engineering Graphics topics.

The CSE-derived core topics (`core_reference`) are matched only against course titles of a curriculum of the same
discipline.

**Plumbing check (2026-10-21), not a validation.** To exercise the path end to end before a real AI & DS curriculum is
available, the CBIT CSE R22A syllabus was submitted labelled as AI & DS in an isolated copy of the project (results
discarded; they describe no AI & DS curriculum). The run completed: reference mapping used `aicte-ug-cse-aids-model`
only (the CSE reference was set aside as not comparable), no CSE core topics were matched, and gap classification and
recommendations were ALLOWED. It found and fixed a crash that affected every IT or AI & DS analysis with job postings:
skill mentions of the set-aside CSE reference were extracted but had no topic in the run, so coverage raised a
KeyError. Extraction now skips set-aside curricula.

Passing unit tests do not validate a discipline. A discipline becomes validated only when a real curriculum of it has
been analysed with relevant evidence and the results have been checked.
