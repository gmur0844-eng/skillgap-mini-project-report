# Semantic validation plan

The machine-readable version of this plan is `data/evaluation/semantic_validation_plan.json`.

## What is validated

The relationships the semantic layer decides are SAME_CONCEPT, PARENT, CHILD, RELATED, PARTIAL_OVERLAP, UNRELATED, AMBIGUOUS and INSUFFICIENT_EVIDENCE.

The **88-case frozen benchmark** (`semantic_benchmark_v1`, sha256 `94b4e79c…`) is unchanged and remains the full internal benchmark.

## 48-case human subset

Human validation uses **48 cases selected from the 88**; no new case is invented. The selection (`scripts/evaluation/semantic_validation.py`, `select_subset`) is:

1. **Proportional by case kind**, using largest-remainder allocation:

   | Case kind | Cases |
   |---|---|
   | ALIAS_SENSE | 25 |
   | AMBIGUOUS_TAXONOMY_LABEL | 10 |
   | DIAGNOSTIC | 7 |
   | AMBIGUOUS_TOPIC_MAPPING | 6 |

2. **Proportional by label within each kind.** Every class present in the benchmark is kept. Class counts are not forced to be equal, because the benchmark itself is unbalanced:

   | Class | Cases |
   |---|---|
   | UNRELATED | 14 |
   | SAME_CONCEPT | 11 |
   | RELATED | 11 |
   | CHILD | 7 |
   | PARTIAL_OVERLAP | 2 |
   | PARENT | 2 |
   | INSUFFICIENT_EVIDENCE | 1 |

3. **Failure modes kept.** Every failure-mode tag stays represented: lexical collision 14, acronym 10, paraphrase 10, hierarchy 9, abbreviation 5, alias 3.
4. **Deterministic order.** The order within each cell is SHA-256(seed + case id). The selection is reproducible and does not use any model output.

The development labels used for the class stratification are the assistant's. They are never shown to reviewers.

## Reviewers, agreement, gold

- **Reviewers:** 2 independent domain reviewers, each blind to model predictions, the assistant adjudication, the deterministic prediction, model confidence, the current system decision and the expected answer.
- **Agreement:** Cohen's kappa for two reviewers, Fleiss' kappa for three or more. Raw agreement, per-class specific agreement and the disagreement matrix are also recorded.
- **Adjudication:** predefined. A named human adjudicator chooses one of the reviewers' labels, or *Ambiguous*.
- **Gold:** `semantic_gold_v1` contains the UNANIMOUS and ADJUDICATED cases only, and is immutable once frozen.

## Gate v3 (declared before any label)

`data/evaluation/semantic_gate_v3.json` has sha256 `399b4cfa…` and is pinned in `engine_config.json → semantic_validation`. It keeps every criterion of gate v2 except two changes:

- **min_gold_cases 80 → 44.** Gate v2's 80 cases could never be met by a 48-case subset; 44 allows up to 4 unresolved cases.
- **min_independent_reviewers 1 → 2.** This makes the gate stricter.

**Disclosure:** the development-label preview on all 88 cases was known when gate v3 was declared, and the criteria were not relaxed because of it.

## Branch-agnostic layout

`data/evaluation/semantic_gold/<discipline>/<version>/` holds:

- `MANIFEST.json`, `subset.json`, `blind_export.csv` and `form_cases.json`;
- the `labels/` folder, `agreement.json`, `adjudication.json`, `semantic_gold_v1.json` and `metrics.json`;
- `assistant_adjudication.json`.

A new discipline is added with

```
semantic_validation.py build --discipline "<name>" --benchmark <that discipline's frozen benchmark>
```

and needs no code change. Computer Science and Engineering is only the first package; the tests build a "Landscape Architecture" package from the same code.

## Status now

- Package `computer-science-and-engineering/v1`: built.
- Labels: **0 independent label sets so far**, so the status is PENDING_INDEPENDENT_LABELS.
- Reviewer responses (2026-10-22): R01–R05, all 48 cases each, imported as research records
  (`responses/`; R02 and R03 human AI-assisted, the rest source not stated). They are compared and shown,
  but never count as independent labels (`docs/SEMANTIC_HUMAN_VALIDATION_FORM.md`, last section).
- Qwen stays in SAFE_MODE.
- No accuracy is claimed.
