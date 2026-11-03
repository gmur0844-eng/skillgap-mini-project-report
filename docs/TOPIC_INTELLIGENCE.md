# Topic intelligence

> **Counts in this document describe the runs they were written for (up to run d140f830ab26adeb).** From run f173ee4fff47e2a6 on, topic cleaning changed the concept population: 1,318 concepts across all non-peer curricula, of which 1,093 contain a target-curriculum topic; the current graph has 10,331 nodes and 15,689 edges (run 84d7737ccb8e4d87). Current figures, with their scope, are in `docs/FULL_CONSISTENCY_AUDIT.md`. Annotated 2026-10-01; the text below is unchanged.

Topics are the foundation: `PDF → structure → course → unit → topic → subtopic → concept → skill → ESCO`.
The system keeps these apart:

| Entity | What it is | Source |
|---|---|---|
| TOPIC | a clean text fragment of a unit, with provenance | SILVER |
| SUBTOPIC | an item of an explicit `Head: a, b, c` list | `topic_hierarchy.jsonl` (2.0) |
| CONCEPT | a cluster of topics within a course family (TF-IDF, lexical) | `concepts.jsonl` |
| SKILL | a normalized skill surface found in postings/topics; ESCO status per skill | `industry/skills.jsonl` |
| TECHNOLOGY | a skill whose category is `TECHNOLOGY_TOOL` (curated token list) | `skill_category` |
| ESCO SKILL | an ESCO concept (URI) — a taxonomy fact | `esco_full` store |
| COURSE | a course record; never merged with a concept | `courses.jsonl` |

`raw_text` (as in the PDF), `clean_text` (normalized) and the concept a topic joins are separate fields.

## Subtopics (2.0)

Rule: a source line `Head: item, item, …` where the head has ≤ 8 words, every item ≤ 6 words and there are ≥ 2
items. The head becomes a parent node; each item a child (`CHILD_OF`, method `colon_head_list_structure`,
evidence `EXTRACTED`), linked to the existing topic fragment that contains it when there is one. Commas alone never
create a hierarchy ("apples, oranges, pears" stays three sibling topics). Real run: see
`intelligence/intelligence_report.json → topic_hierarchy` (lines with hierarchy, subtopics, lines rejected by shape).

## Concept discovery

Unchanged from engine 1.1: course families, then TF-IDF agglomerative clustering within a family (1,337 concepts,
3,302 topics in concepts, silhouette 0.110). Concept names come from member text; generic names ("Introduction")
occur and are flagged by the review queue. No language model or embedding model was available, so there is no
"AI concept discovery" in this run — the SemanticModelProvider exists and adjudicates only candidate pairs.

## Coverage relation and depth (2.0)

For each established skill mention in a topic, the label's position inside its list item decides the relation:

| Relation | Rule | Example shape |
|---|---|---|
| DIRECT | the item is the label | "X" |
| PARTIAL | the label is the item's head | "Introduction to X", "advanced X" |
| RELATED | the label modifies another head | "X injection" |
| INCIDENTAL | the item is longer than 8 words | a sentence mentioning X |

Level per skill and document: ABSENT (no mention) · MENTION (only RELATED/INCIDENTAL) · INTRODUCTORY (DIRECT/PARTIAL,
below the substantial thresholds) · SUBSTANTIAL (≥ 3 DIRECT/PARTIAL topics or ≥ 2 units) · ADVANCED (covered in a
course AND in one of its stated prerequisite courses) · INSUFFICIENT_EVIDENCE. Course-outcome mentions are counted
as depth evidence. Thresholds were declared before the run and are heuristic (not calibrated).

Known weakness found by the hard-case report: "network" inside "neural network" gets PARTIAL (head position),
although the senses differ. Head-noun position does not detect word sense.
