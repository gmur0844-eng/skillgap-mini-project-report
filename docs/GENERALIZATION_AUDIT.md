# Generalization audit

Can the system analyse a curriculum of any discipline, from any institution, without code changes? This audit checks
the code statically and the data model structurally.

| | |
|---|---|
| Tool | `scripts/audit/generalization_audit.py` (regression test: `test_consistency_fixes.GeneralizationAudit`) |
| Result | `data/evaluation/branch_generalization_audit.json` |

## Static scan

151 production files (backend, pipeline, scripts, Flutter `lib/`) were scanned for discipline, programme or
institution names and for ranking logic.

| Classification | Hits | Allowed? |
|---|---|---|
| COMMENT_OR_DOCSTRING | 47 | yes — examples in documentation |
| SOURCE_SPECIFIC_CONFIG | 10 | yes — column layouts of supplied posting files and posting-id patterns of named job boards; data formats, not disciplines |
| PRODUCTION_CONDITIONAL (`if discipline == …`) | 0 | no |
| HARDCODED_LIST (a finite list of disciplines/branches) | 0 | no |
| RANKING_LOGIC (a university score or ranking) | 0 | no |

## Structural checks

| Check | Result |
|---|---|
| Document roles and their required metadata come from data (`data/metadata/document_roles.json`) | yes |
| Discipline is free text; the upload form suggests disciplines already seen and accepts any other | yes |
| Generic words and course comparability (mapping gate) are computed from each run's documents | yes |
| Semantic gold sets are stored per discipline (`data/evaluation/semantic_gold/<discipline>/v1`) | yes — one package so far: computer-science-and-engineering |
| Institution and programme optional where the role allows it (a reference curriculum may belong to no institution; a general reference document needs only a title) | yes |

## Known limitations (stated, not hidden)

* Discipline identity is an exact string: two spellings of one discipline are analysed as two disciplines. The upload
  form offers the disciplines already analysed to reduce this.
* The industry taxonomy loader reads ESCO. Another taxonomy needs a loader; the taxonomy source is recorded per
  mapping, and a concept can exist without any taxonomy mapping, so ESCO is not assumed to cover every discipline.
* The reference-vocabulary scope (`core_reference.applies_to_discipline`) is data; a discipline without one simply has
  no reference vocabulary.
* Only one discipline has real evidence in this repository, so generality is shown by construction and by the
  static audit, not yet by a second discipline's run.
