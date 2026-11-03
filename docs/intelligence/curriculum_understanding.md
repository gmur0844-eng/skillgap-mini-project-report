# Curriculum understanding (Phase 4, experimental)

*Code:* `backend/app/knowledge_engine/curriculum_understanding.py`.
*Run over the release:* `scripts/analysis/gap_reasoning_audit.py`, which writes to
`data/experiments/gap_reasoning/<run>/`.

The release, the API and the screens are unchanged. Gap v2 stays authoritative until this layer has been reviewed by
people (Phase 11).

## What it adds

The release reads a curriculum as courses, units and topics, and measures a skill's depth from topic wording. Phase
4 builds a **CurriculumProfile** for each document. It records what the release did not:

| Dimension | How it is read (general document structure, no names) |
|---|---|
| Programme level | Degree words in the programme title (B.E., B.Tech, Bachelor, M.Sc, Master, Ph.D., UG, PG). Both kinds, or neither → UNKNOWN. |
| Year of study | From the semester number (Roman or Arabic). |
| Course kind | The **head noun** of the title: lab / workshop / studio → PRACTICAL; project / internship / thesis → PROJECT; seminar → SEMINAR; MOOC / certification → SELF_DIRECTED; otherwise THEORY. A word elsewhere in the title does not count, so "Software Project Management" is THEORY. |
| Compulsory or option | Read from the scheme pages. A numbered row carrying credits or hours is COMPULSORY. A course under a short heading that says elective, honours or minor is an ELECTIVE_OPTION. Details below. |
| Practical pairing | A practical course whose title is a theory course's title plus a practical head noun ("Operating Systems" ↔ "Operating Systems Lab"). |
| Document scope | The semesters present, against the most semesters in comparable documents (the institution's other curricula and the reference, at the same level). Values: COMPLETE / PARTIAL / UNKNOWN. |

### Reading compulsory and option status from layout

The reader never uses a course code's letters. It reads the layout of the scheme pages:

- **Option heading.** A line of up to 12 words that says *elective*, *honours* or *minor*, is not a numbered row and
  names no course.
- **In-table placeholder.** If the next line after an option heading is a numbered row, the heading is a placeholder
  inside the scheme table ("Professional Elective" beside its row). It opens nothing.
- **Option block.** Any other option heading opens a block of options. The block lasts until a *Total* line, a
  section heading or the next option heading. A section heading is either:
  - a section mark (c. / IV. / 2.) on a line with no numeric column; or
  - an ordinal semester, year or session ("SEMESTER - VI", "Semester 3").
- **Continuation pages.** A numbered row on a page that follows an open option list, before any heading on that page,
  is *ambiguous*. Alone it leaves the course UNKNOWN; it is never called compulsory.
- **Prerequisite columns.** A course code printed after another course on an option line is a reference to it, not
  an option entry, when that course is also a scheme row.
- **Conflicts.** A course found both ways is CONFLICTING. A course found neither way is UNKNOWN.

## Coverage of a skill: the evidence hierarchy

Each piece of evidence is kept with its type and rank:

| Rank | Type | Meaning |
|---|---|---|
| 1 | TOPIC_DIRECT | A syllabus topic item **is** the skill. |
| 2 | TOPIC_PARTIAL | The skill is the head of a topic item ("advanced X"). |
| 3 | PRACTICAL_TITLE | A practical course is named after the skill. |
| 4 | COURSE_TITLE | A course is named after the skill. |
| 5 | OUTCOME | A course outcome names the skill. |
| 6 | TOPIC_RELATED | The skill qualifies another subject ("X injection"). |
| 7 | TOPIC_INCIDENTAL | The skill is buried in a long item. |
| 8–9 | TAXONOMY_NARROWER / BROADER | A directly narrower or broader concept is taught. This is context only, never proof. |

Course titles and outcomes are extracted with **the release extractor and the same sense rule** as topics. The
syllabus-genre concept rule is the one from Phase 3C (`skill_evidence.curriculum_profile`). A unit test checks that
the two give the same concepts.

**Level.** The depth comes from topic evidence, using the release rule and thresholds:

| Level | Rule |
|---|---|
| ADVANCED | Taught in a course and in a course it lists as a prerequisite. |
| SUBSTANTIAL | At least 3 direct or partial topics, or at least 2 units. |
| INTRODUCTORY | Fewer than that. |
| MENTION | Only related or incidental mentions. |
| ABSENT | No evidence. |

**New level: UNCERTAIN.** A title or outcome names the skill, but no topic teaches it directly. The course claims the
skill, but its depth cannot be measured, for example because lab experiments are not extracted.

Three dimensions are reported separately and never folded into the level:

- **access**: COMPULSORY (any course carrying direct evidence is compulsory), ELECTIVE_ONLY, UNKNOWN or NONE;
- **practice**:
  - PRACTISED: a practical course names the skill, or a topic sits in a practical or project course;
  - PAIRED_PRACTICAL: the theory course that teaches it has a paired practical course (inferred);
  - THEORY_ONLY or NONE otherwise;
- **cross-course pattern**: SINGLE_COURSE, SEVERAL_COURSES_ONE_YEAR, SPREAD_ACROSS_YEARS or PROGRESSION_EXPLICIT.

## Results on the release documents

The extraction regression passed:

- the run's 1,812 core-topic mentions were reproduced identically, including sense states;
- 0 of the run's mappings changed.

Course titles, outcomes and peer topics added 5,332 mentions. They are mapped with the run's own mappings wherever
the run knows the wording, so they cannot change a release mapping.

| Document | Role | Level | Scope | Kinds | Status |
|---|---|---|---|---|---|
| CBIT R22A | TARGET | UG | COMPLETE (I–VIII) | 81 theory, 25 practical, 3 project, 1 seminar, 3 self-directed | 61 compulsory, 51 option, 1 unknown |
| CBIT R22 | PREVIOUS_VERSION | UG | **PARTIAL** (I–IV of 8) | 22 / 13 / 1 | 29 compulsory, 7 unknown |
| AICTE model | REFERENCE | UG | COMPLETE | 35 / 3 / 2 | 40 unknown (no scheme layout) |
| NIT Warangal | PEER | UG | COMPLETE | 104 / 10 / 2 | 45 compulsory, 68 option, 3 unknown |
| NIT Tiruchirappalli | PEER | UG | UNKNOWN (semesters not parsed) | 102 / 5 / 2 | 39 compulsory, 44 option, 22 unknown, 4 conflicting |
| IIT Kanpur | PEER | UG | UNKNOWN | 120 theory | 120 unknown |

**Independent check of the status reader.** Three of these institutions encode status in their own course codes.
The reader never reads the codes, so agreement with each convention is an independent check
(`data/evaluation/course_status_convention_key_v1.json`). Labels come from the code convention, not from people.

| Document | Agree | Disagree | Abstained | Precision of decided |
|---|---|---|---|---|
| CBIT R22A | 112 | 0 | 1 | 1.000 |
| CBIT R22 | 29 | 0 | 5 | 1.000 |
| NIT Warangal | 68 | 0 | 0 | 1.000 |
| NIT Tiruchirappalli | 81 | 2 | 25 | 0.976 |
| **All** | **290** | **2** | **31** | **0.993** |

The two disagreements are core courses that NIT Tiruchirappalli also prints inside an elective page.

**Target coverage (R22A), 1,006 skill keys.**

| | Values |
|---|---|
| Coverage level | 763 ABSENT, 27 MENTION, **39 UNCERTAIN**, 103 INTRODUCTORY, 70 SUBSTANTIAL, 4 ADVANCED |
| Access, skills with any evidence | 92 compulsory, **90 elective only**, 1 unknown, 60 none |
| Practice | 20 practised, 64 paired practical, 107 theory only, 52 none |

**Agreement with the release coverage.** 225 of the 243 release coverage levels agree (UNCERTAIN is compared as
the release's ABSENT or MENTION).

All 18 differences have one cause. The release counted only mentions mapped to the key. Phase 4 also resolves
syllabus wordings to the key with the Phase 3C rule, for example the one-word subject name "operating systems". In
each case the coverage rises; it never falls.

## Limitations

- The head-noun rule misreads "Engineering Workshop Practice" (THEORY) and "MOOCS / Training / Internship" (PROJECT
  rather than SELF_DIRECTED). These are known failures in the synthetic suite, left as they are rather than tuned.
- Lab experiments are not extracted. Practice is therefore read from titles and pairing only. PAIRED_PRACTICAL is an
  inference.
- Status is read from layout. Two of the six documents print no scheme the reader understands (AICTE, IIT Kanpur), so
  every course there is UNKNOWN.
- The NIT Tiruchirappalli and IIT Kanpur semesters are not parsed, so their scope is UNKNOWN.
