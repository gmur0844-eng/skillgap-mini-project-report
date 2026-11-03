# Core Discipline Knowledge Layer

**Status: framework only. No real core-knowledge data has been imported.**
All tables in this layer are empty in every real environment until an
authoritative source is acquired and ingested.

## 1. Why core knowledge is separate from industry demand

Three different kinds of evidence answer three different questions:

| Evidence | Question it answers | Source |
|---|---|---|
| **Core knowledge** | What does this discipline fundamentally cover? | Academic frameworks, professional bodies, curricula |
| **Industry demand** | What are employers currently asking for? | Job postings |
| **ESCO standardization** | What is the canonical name/ID for this skill? | ESCO taxonomy |

Merging them would let a short-lived hiring trend stand in for foundational
knowledge, or hide a real industry need behind an academic label. They are
stored separately and only *compared* by later analytics -- never combined
into a composite score.

## 2. Hierarchy

```
Discipline (existing, data-driven reference table)
  -> CoreKnowledgeDomain        (unique per discipline + name)
      -> CoreTopic              (unique per domain + name)
          -> CoreSubtopic       (unique per topic + name)
CoreTopic | CoreSubtopic  -> CoreKnowledgeSkillMapping -> Skill (existing)
CurriculumTopic (existing) -> CurriculumTopicCoreTopicMapping -> CoreTopic
```

## 3. Discipline isolation

Isolation is enforced by **data relationships**: every CoreTopic reaches
its Discipline through `CoreTopic.domain_id -> CoreKnowledgeDomain.discipline_id`.
Matching only ever sees candidates pre-filtered by
`scope_core_topics_to_discipline(topics, discipline_id)`. No code compares
discipline names (verified by repo-wide audit). The API's `/topics`
endpoint *requires* `discipline_id`.

## 4. Data sources

Source kinds are stored in the existing free-text `DataSource.source_type`
column (no new provenance system): `academic_framework`,
`university_curriculum`, `professional_body`, `industry_job`, `esco`, `other`.

## 5. Provenance

Every domain/topic/subtopic/mapping has a nullable `source_id -> DataSource`.
From a topic you can answer "where did this come from?": source name, type,
URL, version, retrieval timestamp, file hash, and the `AnalysisRun` that
imported it (with RAW/BRONZE/SILVER artifacts under
`data/{raw,bronze,silver}/core_knowledge/<run_id>/`). A NULL `source_id` is
reported as **missing provenance** by the quality metrics and shown as
`source: null` by the API -- never back-filled.

## 6-9. Mappings

- **Skill mapping** (`CoreKnowledgeSkillMapping`): core topic *or* subtopic
  (exactly one -- validated by `validate_skill_mapping_target`) -> `Skill`.
- **ESCO mapping**: achieved *transitively*. `Skill` rows already carry
  `taxonomy="ESCO"` + ESCO URI and their own ESCO `DataSource`. So the chain
  Core source -> CoreTopic -> mapping (own method/source) -> Skill (ESCO source)
  keeps three distinguishable provenances: core academic source, mapping
  evidence, and ESCO source. No duplicate ESCO entity was created.
- **Curriculum mapping** (`CurriculumTopicCoreTopicMapping`): links the
  university's verbatim `CurriculumTopic` to a canonical `CoreTopic`. The
  curriculum wording is never modified; both remain queryable.
- **Industry mapping**: transitive via `ExtractedSkill -> Skill ->
  CoreKnowledgeSkillMapping -> CoreTopic`. No direct job-to-core-topic table.

## 10. Matching methodology

`match_text_to_core_topics` implements only deterministic methods:
exact label (confidence 1.0) then normalized label (lowercase + whitespace,
confidence 0.9). It returns a status:

| Status | Meaning | Persisted? |
|---|---|---|
| `MATCHED` | exactly one candidate | yes |
| `AMBIGUOUS` | 2+ candidates at the same level | **no** -- written to a SILVER review artifact |
| `NO_MATCH` | nothing matched | **no** -- written to the review artifact |

"Digital Logic Design" does **not** match "Digital Electronics". Semantic
matching is a future method; `validate_mapping_evidence` ensures any
non-curated method with NULL or < 0.85 confidence is never treated as
authoritative.

## 11. Evidence states

NULL confidence = not assessed (never treated as 0). A real `0.0` is a
genuine (poor) assessed confidence. Inactive rows (`is_active=0`) are
excluded from matching and from the API by default but keep their provenance.

## 12. Data-quality rules

`compute_core_knowledge_quality_metrics` reports totals, provenance present/
missing, active/inactive, mappings with/without assessed confidence; the
import adds total/invalid input records; the curriculum-mapping run adds
created/already-present/ambiguous/unmatched counts. `find_duplicate_names`
detects near-duplicates (same normalized name in the same parent) that the
exact-string DB constraint would miss.

## 13. Synthetic test fixtures

`data/external/demo_fixture/core_knowledge_fixture.{csv,json}` contain only
names prefixed `FIXTURE` (enforced by a test). They must be ingested with
`--test-data`, which sets `DataSource.is_test_data=1`; the API excludes such
records unless `include_test_data=true`. No GOLD analytics consume this layer yet.

## 14. Limitations

- **Not DB-tested**: the orchestration (`ingest_core_knowledge_records`,
  `map_curriculum_topics_to_core_topics`) and the API compile and use pure
  functions that are unit-tested, but have never run against a live database
  (SQLAlchemy/FastAPI are not installable in the build environment).
- Loaders implemented: CSV, JSON. PDF/JSONL/ODS/XML are not implemented.
- No `CoreKnowledgeSkillMapping` producer exists yet (only the table, validator and API).
- `is_test_data` is only threaded through core-knowledge ingestion; the older
  job/curriculum fixture ingestion paths still mark fixtures by name only.
- Coverage/alignment analytics over core topics (Phase 6 A-G) are not implemented.

## 15. First real chain: AICTE -> Core Knowledge -> CBIT Semesters I-IV mapping

**Scope: CBIT R22 CSE Semesters I-IV.** **Source coverage: Partial --
Semesters I-IV only.** This is a partial curriculum comparison because
Semesters V-VIII are not present in the currently acquired CBIT source.
No claim is made about those semesters, and none of the results below
should be read as evidence about them.

**Executed DB-free** (no SQLAlchemy runtime in this build environment,
confirmed by direct import attempt). 11 real `CoreTopic` candidates were
derived directly from AICTE's own CSE-professional-core course titles
(codes `CS-301`-`CS-603`), each with real page-level provenance, raw vs.
canonical wording preserved, and documented exclusions (audit/workshop
courses, project-capstone slots, bibliography-artifact false positives
like "ISBN-13"/"SHA-256"). This reference was kept unchanged for this
mapping pass -- it was not narrowed to manufacture matches.

The full available CBIT I-IV population was used (nothing further to
filter -- the acquired document IS Semesters I-IV in its entirety, per its
own title): 12 resolved course titles and 981 extracted topic fragments.

### A generic normalization fix, not a CSE-specific rule

The previous run found a real near-miss: CBIT's "Computer Organization And
Architecture" vs. AICTE's "Computer Organization & Architecture" -- same
subject, not matched, because `&` and `"and"` weren't treated as
equivalent. Fixed with `_normalize_conjunctions()`: a new matching tier
that converts `"X & Y"` to `"X and Y"` (and then applies the existing
case/whitespace/Unicode normalization) *before* comparing -- requiring
whitespace on both sides of `&`, so proper nouns written without spaces
("AT&T", "R&D") are never touched. This is pure text substitution, not a
lookup table of known phrases; it applies identically to any discipline's
terms (verified by a regression test using an unrelated Mechanical-style
example, "Heat Transfer & Fluid Mechanics").

### Real results, this run

| Granularity | Population | MATCHED | COMPOUND | AMBIGUOUS | NO_MATCH | Coverage |
|---|---|---|---|---|---|---|
| CBIT I-IV course titles | 12 | **1** | 0 | 0 | 11 | 8.3% |
| CBIT I-IV topic fragments | 981 | 0 | 0 | 0 | 981 | 0% |

**Methods**: EXACT 0, NORMALIZED 0, ABBREVIATION 0, SYNONYM 0, COMPOUND 0,
**CONJUNCTION_NORMALIZED 1** (the new tier).

**The one real match**: CBIT's "Computer Organization And Architecture"
(22CSC10, Semester IV) now correctly matches AICTE's "Computer Organization
& Architecture" (CS-402) via `conjunction_normalized_match`, confidence
0.88.

**Why the rest are NO_MATCH, honestly**: the remaining 11 course titles and
981 topic fragments do not textually, abbreviation-wise, or synonym-wise
correspond to any of the 11 AICTE reference topics. Some (e.g. "Data
Structures" vs. AICTE's "Data Structures and Algorithms", "Discrete
Structures" vs. "Discrete Mathematics", "Formal Language and Automata
Theory" vs. "Theory of Computation") are plausibly the same broad subject
to a human reader, but are not fabricated into matches -- the system
correctly declines to guess. This is a legitimate, expected result per
this project's explicit rule: coverage is not optimized for its own sake.
No claim is made about whether Semesters V-VIII (not in this source) would
change this picture.

**Artifacts**: `data/silver/core_knowledge/aicte_derived_cse_reference/core_topics.json`
(unchanged this run) and `cbit_mapping_results.json` (updated, with
explicit `scope`/`source_coverage`/`limitation` fields).


## 16. Complete-source mapping: CBIT R-22A Semesters I-VIII

**Scope: CBIT R22A CSE Semesters I-VIII.** **Source coverage: Complete
I-VIII curriculum.** The previous partial-source limitation (Semesters
I-IV only) is now lifted for current use. The earlier partial-scope
artifact is preserved as historical evidence at
`data/silver/core_knowledge/aicte_derived_cse_reference/historical/cbit_mapping_results_r22_semesters_i_iv_partial.json`
-- not deleted.

**Important regulation-version distinction**: the new document is CBIT's
**R-22A** regulation (effective AY 2024-25), genuinely distinct from the
earlier **R22** regulation (AY 2022-23) partial document -- not simply "the
same document with Semesters V-VIII appended." Both source files are kept
in the repo under different filenames.

**AICTE reference: unchanged (11 topics)** -- not narrowed or expanded to
manufacture matches, exactly as instructed.

**Real extraction from the complete 246-page document**: 199 course
entries (84 distinct codes), 349 modules, 4,212 topics, 600 outcomes.
Extraction confidence: 0.76. One quality-gate WARN (duplicate course
codes) -- the same expected summary-table-vs-detail-page pattern
documented in the earlier phase, not a new defect.

### Real mapping results

| Granularity | Population | MATCHED | COMPOUND | AMBIGUOUS | NO_MATCH | Coverage |
|---|---|---|---|---|---|---|
| Course titles (resolved) | 39 | 2 | 1 | 0 | 36 | 5.1% (course-level; 7.7% counting the compound as partial) |
| Topic fragments | 4,212 | 3 | 1 | 0 | 4,208 | 0.07% |

**Genuine, real, non-fabricated examples**:
- `22CSC15N "Operating Systems"` -- MATCHED, `exact_label_match`, against AICTE `CS-403 "Operating Systems"`.
- `22CSC24N "Compiler Design"` -- MATCHED, `exact_label_match`, against AICTE `CS-602 "Compiler Design"`.
- `22CSC50 "Artificial Intelligence and Machine Learning"` -- COMPOUND: correctly decomposed into `["Artificial Intelligence", "Machine Learning"]`; only "Machine Learning" matched (AICTE `CS-603`); "Artificial Intelligence" correctly stayed NO_MATCH since no such standalone topic exists in the 11-item reference. The compound result never claims the whole course is "covered."

**A genuine false positive found and disclosed, not hidden**: the
topic-fragment level's 3rd "MATCHED" result -- `course=22ECO05,
topic_text="OS"` matching "Operating Systems" via `abbreviation_match` --
is **not a real match**. Tracing it back to its real source context (the
surrounding extracted topics under the same module) shows it is a
corrupted remnant of "**OSI**" (Open Systems Interconnection, a
*networking* term) produced by comma-splitting/line-wrap during
topic-fragment extraction, not a genuine standalone reference to Operating
Systems. This is an **extraction-fragmentation artifact**, not a matching-
logic defect -- the abbreviation tier did exactly what it is designed to
do; the corrupted input is the problem. A regression test
(`test_known_limitation_short_abbreviation_can_false_positive_on_fragmented_text`)
locks in this known, disclosed limitation rather than silently patching it
by weakening the abbreviation tier (which would also lose genuine cases).
**Genuine confirmed matches, excluding this false positive: 2 exact + 1
partial-compound.**

### Distinguishing the four things this run actually measured (spec's own framing)

- **A. Extraction success**: real, strong -- 4,212 topics, 600 outcomes,
  84 distinct courses recovered from a real 246-page document, 0.76
  confidence.
- **B. Deterministic mapping success**: real, narrow -- 2 genuine exact
  matches + 1 genuine partial compound match, against an 11-item reference
  that was deliberately kept unchanged.
- **C. Actual curriculum coverage**: 5.1%-7.7% at course-level, 0.07% at
  topic-fragment level -- these numbers describe *this specific* 11-item
  AICTE reference against *this specific* CBIT extraction, nothing more.
- **D. Remaining NO_MATCH cases**: the large majority. Per the spec's
  explicit instruction, **NO_MATCH here does not mean "these subjects are
  unrelated"** -- several real CBIT titles (`"Discrete Structures"`,
  `"Data Structures Using C++"`, `"Network Security"`, `"Cyber Security"`)
  are plausibly related to AICTE reference topics to a human reader, but
  the deterministic taxonomy correctly declined to guess at that
  relationship without textual, abbreviation, synonym, or compound
  evidence.

**Database status**: unchanged -- no SQLAlchemy runtime in this build
environment, confirmed directly. Everything above is real matching-logic
execution against real extracted text, held in JSON artifacts.


## 17. Population repair: fixing the extraction-artifact denominator

**The 39-course population used in Section 16 was scientifically invalid.**
It was not a curated core/lab/elective filter -- it was an accidental
byproduct of which table row happened to extract cleanly on first sighting.
An audit (triggered by a direct question about the discrepancy) found three
real, generic parser bugs:

1. **Bare code, title on the next line was never captured.** Real CBIT
   R-22A detailed-syllabus pages put the course code alone on one line and
   the title on the next -- the parser only ever looked at the SAME line as
   the code, so these titles were silently lost. Fixed with a next-line
   lookahead (`pending_course_ref`) that also spans page boundaries, and
   gives up (leaves the title `None`) rather than guessing when the
   following line isn't title-shaped.
2. **Letter-suffixed codes were entirely invisible, not just badly
   titled.** Codes like `22CSC15N`, `22CSE06N` (a common "revised course"
   convention) didn't match the course-code regex at all -- the parser
   never even knew these 43 additional real courses existed. Fixed by
   allowing an optional trailing uppercase letter on the digit-year-prefix
   pattern.
3. **A tie-break bug in the best-occurrence resolver.** When a messy
   summary-table row and a clean detailed-syllabus title had the SAME
   alphabetic character count, the resolver's tie-break (earliest page)
   wrongly favored the noisier, usually-earlier occurrence. Fixed to prefer
   fewer digits before falling back to page number.

None of these fixes reference CBIT, AICTE, or any specific course by name
in the executable logic -- all are generic, regex/heuristic-level fixes
applicable to any curriculum document with these (common) real-world
formatting conventions. 11 new regression tests lock them in.

### Repaired population

| | Count |
|---|---|
| Total distinct course codes extracted | 127 (was 84) |
| Excluded as documented, semantic noise (not extraction artifacts) | 14 |
| **Mapping-eligible genuine courses** | **113** |
| Of which resolved automatically | 112 |
| Of which resolved via direct manual source verification | 1 (`22CSC52` -- title sits ABOVE its code line, a third table layout the fix doesn't yet handle; verified by direct inspection, not guessed) |
| Unresolved (title unknown) | **0** |

**Eligibility rule, stated explicitly**: all genuine (non-noise) course
codes are included. No core/lab/elective/project sub-filtering was
applied -- per instruction, the denominator is never shrunk without a
documented semantic reason specific to the comparison, and none was
identified as necessary here.

### Repaired real mapping results (valid denominator)

| Granularity | Population | MATCHED | COMPOUND | NO_MATCH | Coverage |
|---|---|---|---|---|---|
| Course titles (complete, valid) | **113** | **5** | 1 | 107 | **4.42%** |
| Topic fragments | 4,212 | 3 | 1 | 4,208 | 0.07% |

Two more genuine matches emerged once real courses were recovered:
`22CSC48 "THEORY OF COMPUTATION"` (normalized match against AICTE
`CS-504`) and the two previously-manually-verified matches
(`22CSC15N`/`22CSC24N`, Operating Systems / Compiler Design) now resolve
*automatically*, no manual override needed.

**This 4.42% figure is now legitimately computable and reportable** -- the
denominator (113) is complete, documented, and contains zero courses whose
title is unknown, unlike the previous 39-course figure which is preserved
only as historical/debug evidence at
`historical/cbit_mapping_results_r22a_39course_invalid_denominator.json`.

### A genuine vs. a false OS/OSI match, side by side

The previously-documented "OS" abbreviation false positive (a corrupted
"OSI" fragment from a networking course) still exists in the topic-fragment
data and is preserved, not hidden. This run additionally surfaced a
**second, genuine** "OS" abbreviation match -- this time under the actual
Operating Systems course (`22CSC15N`), verified against its real
surrounding topics ("Examples and different types of OS", "OS
architectures: Micro-kernel..."). Both are reported; the mechanism cannot
tell them apart from the fragment alone, which is exactly why topic-
fragment-level matches are documented as needing human review regardless
of outcome, while course-title-level matches remain the more trustworthy
granularity.


## 18. AICTE Core Knowledge reference expansion (this phase)

**Superseded the 11-topic reference** (preserved at
`historical/core_topics_11item_v1.json`), which used only 2 of AICTE's 214
pages and a single flat domain. Re-extracted AICTE with the current
(repaired) parser and systematically identified ALL 48 distinct real
AICTE course codes (44 resolved to real titles; 4 are bibliography-artifact
codes, not courses).

### Real, evidence-derived domain hierarchy

AICTE's own course-category prefixes (not an invented taxonomy) produced
4 real domains:

| Domain | Real prefix | Topics |
|---|---|---|
| Professional Core (Computer Science & Engineering) | CS/PCC | 11 |
| Engineering Science Foundations | ESC | 7 |
| Basic Sciences | BSC/BS | 6 (BS-102/BSC-102 merged -- see below) |
| Humanities, Social Sciences & Management | HSMC | 5 |
| **Total** | | **29** |

**Documented exclusions** (18 of 48 codes), each with an individual reason:
audit/non-credit courses (AU-101/102), capstone project slots (CS-701/801),
a lab/workshop delivery format (CS-302), the 5-course Universal Human
Values induction series (PS10-14 -- values/orientation content, not
disciplinary knowledge), 3 duplicate/prose-reference parsing artifacts
(CS403, ESC302, PCC402 -- category-label-glued-to-code or mid-sentence code
mentions, not distinct courses), and 4 bibliography artifacts (ISBN/SHA).

**A genuine source-level inconsistency found**: AICTE's own document uses
both "BS-102" and "BSC-102" for the same real course (Mathematics-I) in
different tables. Merged into one Core Topic, documented rather than
silently duplicated.

### CoreSubtopic: still not populated, now confirmed generically (not just for math-heavy courses)

Investigated module/topic-level content for CS-301, CS-401, CS-504, and
CS-602 (deliberately including non-math courses this time). All are
corrupted by AICTE's dense multi-column format -- textbook citations,
week-numbers ("(1 week)"), and line-wrap fragments mixed directly into
content, e.g. `"stepwise refinement; phases of  GCC/LL"`. This is a
structural PDF-layout problem, not specific to mathematical notation.
Promoting this to CoreSubtopic records was not attempted -- doing so
responsibly would require a more substantial, embeddings-adjacent-risk
restructuring outside this phase's scope, not a small generic fix.

### One small, generic topic-extraction improvement made (Phase 8)

`_split_topic_list` now tries semicolon-splitting FIRST when semicolons are
present, falling back to comma-splitting otherwise -- verified against real
text (`"Types of communication: verbal and non-verbal; Barriers to
communication; ..."`) where comma-only splitting fragmented coherent
phrases. 2 new regression tests. This was the smallest defensible
improvement identified; a full paragraph-structure-aware rewrite was
evaluated and NOT attempted, per instruction not to rewrite without
evidence it's required.

### Updated mapping (still not a curriculum-alignment score)

| | Population | MATCHED | COMPOUND | NO_MATCH | Coverage |
|---|---|---|---|---|---|
| Course titles (29-topic reference) | 113 | 7 | 1 | 105 | 6.19% |

Two new genuine matches emerged from the expanded reference (both derived
purely from real AICTE evidence, never added because CBIT has them):
`22EGC01N "ENGLISH"` vs. AICTE `HSMC-201 "English"`, and `22EEC01 "BASIC
ELECTRICAL ENGINEERING"` vs. AICTE `ESC-101 "Basic Electrical
Engineering"`. **This 6.19% figure is not overall curriculum alignment**:
it measures textual correspondence against a still-partial (29 of 48 real
AICTE courses) reference, using only deterministic methods, and must be
read alongside every caveat already documented in Sections 15-17.
