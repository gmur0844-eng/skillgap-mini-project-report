# Knowledge graph (engine 2.0)

> **Counts in this document describe the runs they were written for (up to run d140f830ab26adeb).** From run f173ee4fff47e2a6 on, topic cleaning changed the concept population: 1,318 concepts across all non-peer curricula, of which 1,093 contain a target-curriculum topic; the current graph has 10,331 nodes and 15,689 edges (run 84d7737ccb8e4d87). Current figures, with their scope, are in `docs/FULL_CONSISTENCY_AUDIT.md`. Annotated 2026-10-01; the text below is unchanged.

Built from GOLD records by `intelligence.knowledge_graph`; written to `intelligence/graph_nodes.jsonl`,
`graph_edges.jsonl`, `graph_consistency.json`; loaded into `knowledge.concept_relationship`; served by
`/api/v1/semantic/relationships`, `/semantic/evidence?node_id=…`, `/semantic/contradictions`.

## Nodes

CURRICULUM_VERSION (document) · COURSE · TOPIC (incl. subtopic heads) · SUBTOPIC · CONCEPT · SKILL · ESCO_SKILL ·
ESCO_SKILL_GROUP · OCCUPATION · JOB_POSTING (only postings with an established occupation) · INDUSTRY_POPULATION.
(University, programme, discipline are attributes of CURRICULUM_VERSION, not separate nodes.)

## Edges — every edge carries `method`, `methods` (all derivations), `evidence_status`, `evidence`

| Relationship | From → to | Method | Evidence status |
|---|---|---|---|
| CONTAINS | document → course, course → topic | document structure | EXTRACTED |
| PARENT_OF / CHILD_OF | subtopic head ↔ subtopic | `colon_head_list_structure` | EXTRACTED |
| PARENT_OF / CHILD_OF | ESCO broader ↔ ESCO skill | `esco_broader_relation` | REFERENCE_TAXONOMY_FACT |
| PARENT_OF / CHILD_OF / SAME_AS / RELATED_TO | target topic → reference topic | reference mapping (TF-IDF tiers) | MODEL_SUGGESTED |
| MAPS_TO | topic → concept | TF-IDF clustering | MODEL_SUGGESTED |
| MAPS_TO | skill → ESCO skill | label match | REFERENCE_MAPPED / NORMALIZED |
| MENTIONS | topic → skill | label match (sense established) | EXTRACTED |
| PREREQUISITE_OF | prerequisite course → course | explicit prerequisite statement | EXTRACTED |
| DEMANDED_BY | skill → industry population | posting prevalence (count + support state in `evidence`) | OBSERVED |
| APPEARS_IN | job posting → occupation | ESCO occupation label match | NORMALIZED |

Relationships defined by the specification but **not produced**: USED_BY, REPLACED_BY, EVOLVED_TO (no data: ESCO
export has no obsolete concepts; no multi-period industry data), SUPPORTED_BY (evidence is carried on each edge
instead), COVERS / TEACHES (coverage is a separate table, `coverage_depth.jsonl`).

## Automated consistency checks (never silently repaired)

`graph_consistency()` reports: duplicate edges, dangling edges, self-parent / self-prerequisite, SAME_AS asymmetry,
PARENT/CHILD without inverse, contradictions (SAME_AS together with PARENT/CHILD/UNRELATED on the same pair; mutual
PARENT), cycles in PARENT_OF and PREREQUISITE_OF. The same checks run as SQL after publishing
(`graph_self_parent`, `graph_duplicate_edges`). A repeated derivation of the same (source, relationship, target) is
stored once with all its methods listed.

Final-run values are in `FINAL_REPORT.md §9`. Reported asymmetries are expected by construction: reference
mappings are one-directional (target topic → reference topic), so SAME_AS and PARENT/CHILD from mappings have no
stored inverse. They are reported, not "fixed".

## Taxonomy consistency (ESCO)

Checked on every load of the full classification (`esco_full.build_store`): dangling references in all relation
files, broader cycles in both pillars, skill-skill self relations, unknown ISCO codes, duplicate rows — see
`ESCO_INTEGRATION.md`.
