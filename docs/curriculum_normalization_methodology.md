# Cross-University Curriculum Normalization Methodology

## Status
Framework hardened and extended this phase. **No real AICTE/CBIT/IIT data
has been ingested** — this document describes the pipeline's capability,
not an observed result.

## 1. The normalization contract

```
Institution -> Department -> Discipline -> Programme -> CurriculumVersion
    -> Course -> Module/Unit ("heading_label") -> CurriculumTopic
    -> CourseLearningOutcome (with outcome_label preserving "CO1"/"CLO1"/etc.)
    -> [matching] -> CoreTopic / CoreSubtopic (Core Knowledge Layer)
    -> CoreKnowledgeSkillMapping -> Skill -> ESCO (via Skill's own taxonomy fields)
```

**Original wording is never overwritten.** `CurriculumTopic.topic_text` and
`CourseLearningOutcome.outcome_text`/`outcome_label` always hold exactly
what the source document said. A canonical concept is reached only through
a separate mapping row (`CurriculumTopicCoreTopicMapping`,
`CoreKnowledgeSkillMapping`) that references both sides by ID — deleting
every mapping would leave the original curriculum data fully intact.

## 2. Matching states (the taxonomy)

`app/analytics/core_knowledge_mapping.py::match_text_to_core_topics()`
returns one of four overall statuses, and — when matched — one of four
implemented methods (a fifth, `semantic_match`, is a reserved but
unimplemented extension point):

| Status | Meaning |
|---|---|
| `MATCHED` | Exactly one core topic matched, via a single deterministic method. |
| `AMBIGUOUS` | 2+ candidates matched at the same method level — never resolved automatically. |
| `COMPOUND` | The whole phrase matched nothing, but decomposes into 2+ parts (on `,`, `&`, `/`, `and`) and at least one part matched independently. Partial, honest — never claims full identity with the whole phrase. |
| `NO_MATCH` | Nothing matched at any level. |

| Method | Confidence | What it means |
|---|---|---|
| `exact_label_match` | 1.0 | Byte-identical to a core topic's name. |
| `normalized_label_match` | 0.9 | Identical after Unicode NFKC + case + whitespace normalization. |
| `abbreviation_match` | 0.85 | The whole trimmed phrase is a configured abbreviation whose expansion normalized-matches. |
| `synonym_match` | 0.8 | The phrase belongs to a configured synonym group containing a core topic's name. |
| `manual_curated` | — (see below) | A human verified the mapping; always authoritative regardless of confidence. |
| `semantic_match` | — | **Reserved, not implemented.** No code path produces this yet — see §7. |

`validate_mapping_evidence(method, confidence)` gates authority: `None`
confidence on a non-curated method is **never** treated as authoritative,
and a confidence below 0.85 on an inferred method is flagged, not silently
accepted.

## 3. Abbreviations and synonyms are data, not code

`app/reference_data/term_abbreviations.json` and `term_synonyms.json` are
plain JSON files, loaded (and cached) by `load_abbreviation_map()`/
`load_synonym_groups()`. Adding a new abbreviation or synonym group means
editing a JSON file — **zero code changes, zero university-specific
branches**. The starter set is exactly the illustrative examples from this
project's own normalization-audit spec (DBMS/OS/DS/CN/AI families),
explicitly excluding broader/narrower forms.

**Critical, deliberately-tested negative case**: `"Advanced Data
Structures"` is **not** in any synonym group and is **not** an abbreviation
key, so it correctly returns `NO_MATCH` against a core topic named only
`"Data Structures"` — a modifier changes the concept, and this pipeline
never assumes otherwise.

## 4. Compound concepts

`"Data Structures and Algorithms"` is tried as a whole phrase first
(all four methods). Only if that fails does it split into `["Data
Structures", "Algorithms"]` and match each part independently. If one part
matches and the other doesn't, the orchestration
(`map_curriculum_topics_to_core_topics`) creates **one mapping row per
matched component** (never a single row implying the whole compound phrase
equals one core topic), tags each with a composite method string like
`compound_concept_match:exact_label_match` for full traceability, and
routes the unmatched component to the SILVER review artifact — never
silently dropped.

## 5. Structural parsing coverage

`app/pipelines/preprocessing/curriculum_structuring.py` is heuristic,
regex-based, and university-independent — extended this phase to also
recognize:
- `PART A` / `PART-B` as a letter-labeled structural division alongside
  numbered `UNIT`/`MODULE`/`CHAPTER` headings.
- `COURSE CONTENT:` as an alias for a topics-block label.
- Individual outcome numbering — `CO1`, `CLO1`, `CO 1`, `Course Outcome 1`,
  `Learning Outcome 1`, or a bare `1.` — each extracted into
  `CourseLearningOutcome.outcome_label`, separate from the outcome text
  itself, so neither the label nor the wording is lost.

**Known, honestly-documented gap**: OCR-artifact repair (de-hyphenation of
line-wrapped words, header/footer stripping, table extraction) is not
implemented — the parser works on whatever plain text it's given, and
garbage in still produces a low-confidence, flagged-for-review structure
out (see §6), never a fabricated clean one.

## 6. Quality gates before GOLD

`compute_curriculum_ingestion_quality_gates()` (pure, in `data_quality.py`)
checks course count, topic count, duplicate course codes, courses with zero
topics, blank topic text, malformed course codes, missing semester
information, missing learning outcomes when an outcomes section was
detected, and suspiciously low extraction volume relative to page count.
Each check is `PASS`/`WARN`/`FAIL` with a human-readable reason; the
thresholds (e.g. "fewer than 3 courses is unusual") are **documented
defaults, not calibrated against real curricula** — none exist in this
repo yet.

## 7. Semantic matching — extension point, not a feature

Per this project's own rule ("do not immediately add a large embedding
pipeline"), semantic matching is represented only as a reserved method name
(`METHOD_SEMANTIC = "semantic_match"`) that no code path currently produces.
A future implementation would slot into the same `match_text_to_core_topics`
result shape (status/method/confidence) without a redesign, and — per
`validate_mapping_evidence` — a semantic match's confidence would still be
subject to the same "never authoritative below 0.85, and a genuine
similarity score is evidence, not proof" discipline already enforced for
every other inferred method.

## 8. ESCO mapping — no forced mappings

Not every academic topic has a meaningful ESCO skill. `CoreKnowledgeSkillMapping`
connects a `CoreTopic`/`CoreSubtopic` to a `Skill`, which is separately
ESCO-tagged; if no defensible mapping exists, the honest answer is simply
**no mapping row exists** for that topic — there is no `NOT_APPLICABLE`
sentinel to fabricate, and nothing in this pipeline invents an ESCO
identifier.

## 9. Provenance

For any normalized concept, the chain is fully traceable: `CurriculumTopic`
→ `Module` → `Course` → `Programme` → `Department`/`Discipline` →
`Institution`, plus `page_number` on every extracted entity, plus the
`analysis_run_id` on every mapping row, plus `method`/`confidence` on every
mapping. Nothing is discarded to make a normalization "look" cleaner.

## 10. Versioning and isolation

Already covered by earlier phases (unaffected by this one): curriculum
version identity is `(programme_id, version_label)`, never silently
duplicated on re-ingestion; `run_curriculum_version_comparison` refuses to
compare two versions of different programmes; `scope_core_topics_to_discipline`
enforces discipline isolation by data (the FK chain), never by name
comparison — the same mechanism this phase's new matching taxonomy reuses
unchanged.

## 11. What is genuinely ready for AICTE/CBIT/IIT ingestion
- The ingestion entry point (`ingest_curriculum_document`) already accepts
  arbitrary institution/department/discipline/programme/degree/academic-year
  metadata with zero hardcoded assumptions.
- The structural parser handles UNIT/MODULE/CHAPTER/PART headings and six
  outcome-labeling conventions without per-university branches.
- The matching taxonomy handles exact/normalized/abbreviation/synonym/compound
  cases deterministically, with ambiguity and non-matches routed to a review
  artifact rather than silently resolved.
- Quality gates exist to catch a badly-parsed document before it reaches GOLD.

## 12. What is still missing
- OCR-artifact repair, table extraction, header/footer stripping.
- Any real synonym/abbreviation data beyond the five illustrative families.
- Semantic matching itself (only the extension point exists).
- Calibrated (rather than default) quality-gate thresholds.
- Any real curriculum data to validate any of the above against.

## 13. Real-document findings (AICTE + CBIT, this phase)

Both official PDFs were placed in the repo and processed through the
structural parser (DB-free — no live database is available in this build
environment; see the CLI-execution note below). This exercise found and
fixed **four real, generic bugs** that no synthetic test had caught:

1. **Course code format gap**: CBIT's real codes ("22CSC01", "22MTC01") use
   a digit-year-prefix convention the regex never anticipated (only
   letter-prefix "BSC-101"-style codes were supported). Fixed by adding a
   `\d{2}[A-Z]{2,6}\d{2,3}` alternative — a second real, widely-used Indian
   course-code convention, not a CBIT-specific branch.
2. **A real false positive**: "AY 2022-23" (an academic-year reference) was
   being extracted as a course code. Fixed by capping separator-joined
   digit runs at 3 (every genuine code observed uses exactly 3; a 4-digit
   number after a separator is a year, not a course number).
3. **Missing module-content fallback**: CBIT's real unit content has no
   explicit "Topics:" label at all — it's dense paragraph text directly
   under the heading. Before this fix, 0 topics were extracted from either
   real document regardless of page count. Fixed with `module_content_open`
   tracking + `SECTION_BOUNDARY_RE` (TEXT BOOKS/REFERENCES/etc.) to know
   where that content ends.
4. **Outcomes-label lead-in text**: CBIT's real format is "COURSE OUTCOMES:
   After completion of this course, students will be able to" — narrative
   text on the *same line* as the label. The original regex required the
   label alone on its line. Fixing this naively created a *new* bug (the
   relaxed regex started intercepting individually-numbered lines like
   "Learning Outcome 5: ..." before they reached the per-item parser); a
   negative lookahead fixed that. A *second* real false positive then
   surfaced: a sentence in AICTE happens to line-wrap onto a new line
   starting with lowercase "learning outcomes, etc." (mid-sentence prose,
   not a header) — fixed with an `isupper()` guard, since every genuine
   header observed in both documents is capitalized.

**Real extraction confidence achieved**: CBIT 0.46 → 0.85; AICTE 0.44 → 0.77
(see `extraction_confidence()`), after these four fixes — all backed by
9 new regression tests using synthetic lines that reproduce each exact
real-world pattern found.

**Honest remaining noise (not silently hidden)**: AICTE is a 214-page
multi-course national reference document with substantial narrative
discussion (committee framework, graduate-attributes philosophy) interleaved
with actual course syllabi — its outcome extraction (831 entries) is
measurably noisier than CBIT's (199 entries, clean against manual spot-check)
because that narrative occasionally resembles outcome-style prose closely
enough to pass the current heuristics. This is a real, honest limitation,
not something to be "fixed" by guessing further without more real iteration
— attempting a smarter disambiguator here starts to require semantic
understanding, explicitly out of scope this phase.

**Duplicate course codes (79 CBIT entries → 45 distinct, 122 AICTE → 48
distinct) are an EXPECTED, correct finding, not a bug**: both documents
list every course once in a semester-overview summary table and again at
its full syllabus page — exactly what `compute_curriculum_ingestion_quality_gates`'s
duplicate-detection check exists to surface, not silently deduplicate.

**Database ingestion status**: NOT RUN. This build environment has no
SQLAlchemy/PostgreSQL runtime (confirmed unavailable across every prior
phase of this project) — the structural parsing above is genuinely real and
DB-free; `ingest_curriculum_document`, GOLD counts, and core-topic mapping
against real data remain untested against an actual database.
