# Topic → concept mapping audit

This audit asks whether the mappings are *semantically* right, not only whether the numbers agree. It reads the
texts, the courses they come from and the evidence each mapping rests on.

| | |
|---|---|
| Tool | `scripts/audit/topic_concept_mapping_audit.py --run <run_id>` |
| Results | `data/evaluation/topic_concept_mapping_audit.json` (final run `84d7737ccb8e4d87`) · `topic_concept_mapping_audit_before_c8ecd067bb733f58.json` (before the fix, kept unchanged) |
| Labels in this audit | `ASSISTANT_ADJUDICATION` = the assistant read both texts and both courses. **This is not human validation** and is never stored as such. `DETERMINISTIC_RULE` = a stated rule. `REQUIRES_HUMAN_REVIEW` = nobody has decided. |

## Three different problems, kept apart

| | Problem | What a mistake looks like |
|---|---|---|
| A | **topic → concept** (clustering membership) | "Index" (database indexing) and "index" (data-science text) in one concept |
| B | **curriculum topic → reference-curriculum topic** | "techniques" in *Network Security* mapped SAME_CONCEPT to "techniques" in *Compiler Design* |
| C | **industry skill → taxonomy (ESCO) concept** | "powershell" resolved to "computer programming" through a taxonomy alias |

Each graph edge now says which of these it is (`mapping_kind`), so the three are never counted or explained together.

## A — topic → concept membership

1,318 concepts hold 3,231 of 7,625 clean topics. 267 concepts are flagged: 38 have a generic name (a word that appears
in the topics of at least 10 % of courses — computed from the data, not a word list) and 255 have members from courses
whose whole-course topic text is not comparable (TF-IDF cosine below 0.12, the threshold already calibrated for peer
comparison). Flagged concepts are proposed as `REVIEW_REQUIRED (concept may merge different senses)`; membership is
**not** changed in this release, because re-clustering would change every downstream number without an independent
check that the new clusters are better.

Known patterns probed:

| Pattern | Topics | Concepts | Not in any concept | Observation |
|---|---|---|---|---|
| stack | 16 | 3 | 9 | data-structure stacks (Compiler Design, Data Structures) kept apart from OS/concurrency "Stacks Elimination"; protocol "stack" stays unclustered |
| data types | 32 | 8 | 17 | SQL data types, JavaScript data types and C data types form separate concepts — correct |
| network vs neural network | 45 | 8 | 31 | neural networks stay with ML / deep-learning courses; **"Network Design" joins a Machine Learning topic with Nature-Inspired Algorithms** — flagged for review |
| angular | 5 | 0 | 5 | only angular *velocity/momentum* (Physics, Engineering Graphics); no Angular-framework topic exists in the curricula |
| communication | 30 | 7 | 14 | verbal/technical communication separated from communication systems (physics) — correct |
| plan | 28 | 3 | 24 | project planning, interview planning and path planning kept apart |
| network security vs computer networks | 1 | 0 | 1 | no concept merges them |

## B — curriculum topic → reference topic

522 target topics are linked to a reference topic. 404 carry at least one risk flag:

| Flag | Count | Meaning |
|---|---|---|
| CONTAINMENT_OF_SINGLE_WORD | 247 | the link rests on one shared word inside a longer phrase |
| LOW_COURSE_CONTEXT | 228 | the two courses are not comparable (course-context cosine < 0.12) |
| CONJUNCTION_DIRECTION_RISK | 100 | "A and B" phrases where PARENT/CHILD direction is uncertain |
| FRAGMENT_SOURCE | 39 | the source is a lower-case fragment |
| SIMILARITY_WITHOUT_COURSE_CONTEXT | 37 | RELATED/PARTIAL_OVERLAP by text similarity only |
| GENERIC_OR_SINGLE_WORD_IDENTITY | 33 | SAME_CONCEPT by identical single/generic word |

Examples read by the assistant (ASSISTANT_ADJUDICATION): "Concepts" (*Engineering Economics*) → *Advanced Programming*
UNRELATED; "techniques" (*Network Security*) → *Compiler Design* UNRELATED; "Properties" (*Web Programming*) →
*Engineering Graphics* UNRELATED (CSS properties vs geometric properties); "Initialization" (*Problem Solving in C*)
→ *Machine Learning* UNRELATED (variable vs weight initialization); "Paths" (*Software Testing*) → *Discrete
Mathematics* RELATED, not the same concept.

**Fix — course-context gate** (`mapping.context_gate`, recorded per mapping in `signals.context_gate`):

* an exact text identity stays `REFERENCE_MAPPED` only if the text has at least two content words, or the courses are
  comparable and the word is not generic;
* every other linked relationship needs comparable courses;
* otherwise the mapping becomes `REVIEW_REQUIRED`. The relationship is kept as a candidate; nothing is deleted.

| Linked mappings | before (c8ecd067) | after (84d7737c) |
|---|---|---|
| SAME_CONCEPT · REFERENCE_MAPPED | 51 | 33 |
| SAME_CONCEPT · REVIEW_REQUIRED | 0 | 18 |
| PARENT / CHILD / RELATED / PARTIAL_OVERLAP · MODEL_SUGGESTED | 471 | 226 |
| … · REVIEW_REQUIRED | 0 | 245 |

On the 33 identity pairs the assistant read: before the gate, 7 wrong or doubtful pairs (4 UNRELATED, 2 AMBIGUOUS,
1 RELATED) were `REFERENCE_MAPPED`; after it, all 7 are `REVIEW_REQUIRED`, and the 15 that stay `REFERENCE_MAPPED` are
all read as the same concept. The cost: 11 pairs the assistant reads as genuinely the same (e.g. OS *segmentation*,
*swapping*, C *pointers*) also went to review because the word is single and the courses differ. The gate trades recall
for precision; a human reviewer can accept them. These are assistant readings, not human labels.

## The old n = 45 evaluation (0.578)

`data/evaluation/semantic_benchmark.json` holds 45 pairs labelled **by the assistant** in an earlier round. The
reported 0.578 is the relationship-level agreement of the deterministic pair rule with those labels (0.822 for
linked vs unrelated). It is recomputed every run and is identical in all runs, because it re-applies the rule to the
45 fixed pairs — it does not measure what the current pipeline links. Of the 30 historical pipeline links in the set,
21 are still produced, and 7 of those agree with the label. **It is not an accuracy of the system against
independent ground truth**, and it is now reported only with that wording. The independent measure is the 48-case
human subset of the frozen 88-case semantic benchmark ([SEMANTIC_VALIDATION_PLAN.md](SEMANTIC_VALIDATION_PLAN.md)).

## C — industry skill → taxonomy (ESCO)

59 eligible skills are resolved through a taxonomy alias. 32 are wording variants of the label (e.g. "attention to
detail" → "attend to detail") — `DETERMINISTIC_RULE`. 27 resolve to a *differently named, broader* concept, for
example "powershell", "angularjs", "web design", "ct" → *computer programming*; "jquery", "vue.js" → *JavaScript
Framework*; "vms" → *operating systems*; "linkedin" → *social media management*. These are flagged
`ALIAS_TO_DIFFERENTLY_NAMED_CONCEPT` / `REQUIRES_HUMAN_REVIEW` and **not changed**: they are ESCO's own alias
relations, the mentions are marked `TAXONOMY_ALIAS_MATCH`, and 202 alias mentions whose sense is unverified
(`ALIAS_SENSE_REVIEW_REQUIRED`) are already excluded from demand. Changing them would substitute our judgement for
the taxonomy's without a reviewer.

## What remains open

* A: 267 flagged concepts need a reviewer; re-clustering is deliberately not done without one.
* B: 263 `REVIEW_REQUIRED` mappings (33 assistant-read, the rest unread).
* C: 27 alias roll-ups to broader concepts.
* Discipline-generic: generic words and course comparability are computed from each run's own documents; no word or
  course list is hard-coded.
