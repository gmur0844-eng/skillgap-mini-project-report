# ESCO integration — full classification + delta (engine 2.0)

Sources (both hash-verified through `data/metadata/curriculum_sources.json`):

| source_id | file | role |
|---|---|---|
| `esco-v1.2.1-classification-en` | `data/raw/esco/ESCO_dataset_v1.2.1_classification_en_csv.zip` (sha256 `f9761b0b…deb3e`) | **the current taxonomy** |
| `esco-v1.2.1-delta` | `data/raw/esco/ESCO_dataset_v1.2.1_delta_csv.zip` (sha256 `d6fae397…c9c9`) | **change information only** |

Neither replaces the other. The full classification says what ESCO *is*; the delta says which labels *changed* in v1.2.1.

## 1. Audit of the full classification (done before any code change)

Field meanings come from `dictionary_en.csv` inside the ZIP (it names the RDF property of every column) and the
ESCO Model 2.0.0 page (https://ec.europa.eu/esco/lod/static/2.0.0/model.html). Counts are from the files.

| File | Rows | Columns (meaning) |
|---|---|---|
| `skills_en.csv` | 13,960 (13,939 URIs) | conceptType, conceptUri, skillType (`esco:skillType`: knowledge / skill/competence), reuseLevel (`esco:skillReuseLevel`), preferredLabel (`skos:prefLabel`), altLabels (`skos:altLabel`, newline-separated), hiddenLabels (`skos:hiddenLabel`), status (ISO 25964 status), modifiedDate (`dcterms:modified`), scopeNote, definition, inScheme (`skos:inScheme`), description (`dcterms:description`) |
| `occupations_en.csv` | 3,043 (3,039 URIs) | + iscoGroup (`skos:notation` of the ISCO unit group), code (`skos:notation`), regulatedProfessionNote (`esco:regulatedProfessionNote`), naceCode (`esco:hasNACECode`) |
| `skillGroups_en.csv` | 640 | SkillGroup concepts (+ code) |
| `ISCOGroups_en.csv` | 619 | ISCO-08 groups (code, label, description) |
| `broaderRelationsSkillPillar_en.csv` | 20,819 | skill→skill/group and group→group broader links (`skos:broader` as exported) |
| `broaderRelationsOccPillar_en.csv` | 3,648 | occupation→ISCO / occupation→occupation / ISCO→ISCO broader links |
| `occupationSkillRelations_en.csv` | 126,051 | occupation `esco:relatedEssentialSkill` (67,600) / `relatedOptionalSkill` (58,451) skill |
| `skillSkillRelations_en.csv` | 5,818 | originalSkill → relatedSkill, essential 189 / optional 5,629 |
| `skillsHierarchy_en.csv` | 640 | Level 0–3 URIs, labels and codes of the skill-group hierarchy (4 roots: skills, knowledge, transversal, language) |
| `conceptSchemes_en.csv` | 20 | concept schemes (with top concepts) |
| `digitalSkillsCollection_en.csv` 1,284 · `greenSkillsCollection_en.csv` 629 · `languageSkillsCollection_en.csv` 359 · `transversalSkillsCollection_en.csv` 95 · `researchSkillsCollection_en.csv` 40 · `digCompSkillsCollection_en.csv` 25 · `researchOccupationsCollection_en.csv` 122 | | collection membership (altLabels and broader lists `" \| "`-separated) |
| `greenShareOcc_en.csv` | 3,590 | green share of occupations / ISCO groups (read, not used) |
| `dictionary_en.csv` | 160 | column → RDF property dictionary |

Facts found by the audit:

* **21 skill rows and 4 occupation rows are duplicates** of another row with the same URI; they differ **only in
  `modifiedDate`**. The loader keeps the row with the latest `modifiedDate` and counts the collapse.
* All concepts have status `released`; no obsolete concepts are in the export, so ESCO "replaced by" information is
  not available from these files.
* Label volume: skills 13,939 prefLabels, 86,454 altLabels, 1,095 hiddenLabels; occupations 3,039 / 30,387 / 92.
* 5 skills have no skillType / reuseLevel (reported as `UNSPECIFIED`, not dropped).
* Integrity (checked on every load): 0 dangling references in all relation files, 0 broader cycles in the skill and
  occupation pillars, 1 skill-skill self relation, 0 occupations with an unknown ISCO code, 0 occupations without
  skills, 464 skills used by no occupation.
* Direction of `skillSkillRelations_en.csv`: the model defines `relatedEssentialSkill` as "the ESCO skill or
  competence that is essential for the subject occupation **or skill**"; the file's columns are
  `originalSkillUri, relationType, relatedSkillUri`. The engine reads it as *relatedSkill is essential/optional for
  originalSkill*. **This direction is an INFERENCE** from the column order and the model definition; the file does
  not state it.

### Delta-only vs full (factual comparison)

| | Count |
|---|---|
| concepts the delta-only reconstruction treated as skills | 9,298 |
| … that are skills in the full classification | 8,901 (prefLabel identical for all 8,901) |
| … that are **skill groups** in the full classification | **336** — the delta alone cannot tell them apart (same `/skill/` URI form); they were matching targets in engine 1.x |
| … absent from the full classification files | 61 (they have delta rows — Updated altLabel/description/prefLabel — but no row in skills / skillGroups / occupations; the files do not say why) |
| full skills not in the delta | 5,038 (engine 1.x could never match these) |
| delta active altLabels present in the full taxonomy for the same concept | 2,251 of 2,283 |
| labels the delta retires that the full taxonomy still lists for the same concept | 565 (most because the old altLabel became the prefLabel); the full taxonomy wins, each is listed in the audit as a conflict |

## 2. Representation (`backend/app/knowledge_engine/esco_full.py`)

`build_store()` returns a normalised store: `skills`, `skill_groups`, `occupations`, `isco_groups` (each with URI,
labels, descriptions, type/level/codes, `broader`/`narrower`), `occupation_skill` (typed essential/optional),
`skill_skill`, `concept_schemes`, and collection tags on each skill/occupation. URIs are preserved as identifiers;
internal ids (`skill_uid`, …) are derived from them. The store is kept in memory for the run (≈5 s to load).

`skill_vocabulary(store, delta_vocab)` produces the matching vocabulary with the same shape the extractor already
used, so extraction and mapping code did not change in kind:

* targets = the 13,939 skills (skill groups excluded); labels = prefLabel, altLabels, hiddenLabels, and a
  qualifier-stripped prefLabel (`"X (qualifier)"` → `"X"`, a weaker label kind that never establishes a sense alone);
* each altLabel carries the delta action (`Added`/`Updated`) when the delta changed it (2,251 labels);
* labels the delta retires are not matched unless the full taxonomy still lists them.

`delta_vs_full()` produces the comparison above; `occupation_index()` / `match_occupation()` map job titles to
occupations; `isco_path()` and `skill_group_path()` walk the hierarchies.

## 3. Mapping rules that changed with the full taxonomy

* **prefLabel precedence (SKOS).** When a label belongs to several concepts and exactly one has it as prefLabel,
  that concept is chosen and the others are kept as `alternative_concepts`. Example in the real data: "SQL" is the
  prefLabel of ESCO *SQL* and an altLabel of *database management systems*. Any other shared label → `AMBIGUOUS`.
* **hiddenLabel matches** are aliases: they go through the same alias-sense rule as altLabels.
* **skill_category** now comes from ESCO `skillType` (`KNOWLEDGE` / `SKILL_COMPETENCE`) when the concept has one.
* **Aliases are taxonomy facts, not text meaning** (unchanged): a posting's ".NET" is still an altLabel match of
  *Visual Basic* and still needs another label of that concept in the same posting to count.

## 4. Occupations (new)

Job title → ESCO occupation using only ESCO occupation labels (pref/alt/hidden). The title is split into segments at
punctuation and each segment is compared:

| Status | Rule | Used for analytics |
|---|---|---|
| `OCCUPATION_EXACT` | a whole segment equals a label | yes |
| `OCCUPATION_VARIANT` | a whole segment differs from a label only by a plural "s" on some words | yes |
| `OCCUPATION_CANDIDATE` | only a multi-word label inside a segment matches (uncovered words recorded) | **no** — a dropped modifier can change the occupation |
| `OCCUPATION_AMBIGUOUS` | label of several occupations, none as prefLabel | no |
| `OCCUPATION_UNMAPPED` | nothing matches | no |

Character-similarity matching was tried during development and rejected: it mapped "Account Manager" to "accounting
manager" and "Business Development Officer" to "eBusiness development officer". Only plural variants are accepted.

For established postings the posting's established skills are compared with the occupation's ESCO profile
(essential / optional / not in profile), and postings are grouped by ISCO major group. Comparisons across occupations
require `min_postings_per_group` (10) established postings in a group.

## 5. What ESCO is not used for

ESCO is not the whole knowledge system: curriculum concepts are discovered from curriculum text and exist without an
ESCO match (`TARGET_ONLY`, `NEW_DISCOVERED_UNMAPPED`); ESCO statuses are recorded per skill (`EXACT`, `NORMALIZED`,
`AMBIGUOUS`, `UNMAPPED`, `ALIAS_SENSE_REVIEW_REQUIRED`, `INSUFFICIENT_EVIDENCE`). `greenShareOcc` and NACE codes are
loaded but not analysed.
