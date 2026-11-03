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
| ECE, EEE, Mechanical, Civil | yes | no relevant postings supplied | no reference supplied | no peer supplied | no |

Consequences worth knowing:

- An **AI & DS** curriculum is compared with the AICTE AI & DS model curriculum, so it gets gap classification and
  recommendations too. That reference is not part of the default (CSE) analysis: it is registered in
  `data/metadata/discipline_references.json` and joins an uploaded curriculum's analysis context only when the upload
  is of its discipline and the context has no reference of it (`analysis_jobs.derived_manifest`).
- An **IT** curriculum gets industry demand, but no gap classification or recommendations: those are defined against a
  reference curriculum of the same discipline, and no IT reference has been supplied.
- An **ECE, EEE, Mechanical or Civil** curriculum is analysed as curriculum-only.
- A curriculum whose discipline is **empty or not recognised** is analysed on its own, and the reason says how to fix
  it (use a configured discipline name or add an alias).

## Registered references of other disciplines

| Reference | Parse check (2026-10-21) | Known limitations |
|---|---|---|
| `aicte-ug-cse-aids-model`, AICTE Model Curriculum for UG CSE (AI & DS), 2021, 157 pages, sha256 `2b60b806…3dcc` | 46 courses (45 with a semester), 86 units, 1,580 clean topics of 1,885 | The 11 suggested professional electives in Appendix I (computer vision, NLP, advanced ML, ...) use the placeholder code XXNNN and are not extracted as courses, so elective-level AI topics are under-represented; one title is cut at a line break (ES203); one title carries a table fragment (AU301); a second "Mathematics- I" (MT102) has no semester. |

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
