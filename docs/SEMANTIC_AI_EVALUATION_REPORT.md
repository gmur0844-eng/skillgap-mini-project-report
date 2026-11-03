# Semantic AI Evaluation Report (improvement release)

**Status: `PENDING_INDEPENDENT_LABELS`. The model stays in `SAFE_MODE`.**

No independent human labels exist yet for the frozen 88-case benchmark, so this release reports **no model accuracy**. This document covers four things:

- the evaluation machinery that was built and tested;
- the promotion gate, declared before any independent label existed;
- exactly what an independent reviewer has to do;
- an internal development preview that is explicitly **not** an evaluation.

## 1. What is evaluated

| System | What it is |
|---|---|
| `DETERMINISTIC_BASELINE` | the rule layer alone (no model) |
| `QWEN_RAW` | `qwen2.5:7b-instruct` answers as returned (replayed from the recorded run; no new model calls) |
| `QWEN_VALIDATED` | Qwen answers after the deterministic evidence validator — the only output that could ever reach production. **This is the system the gate evaluates.** |

- **Benchmark:** `semantic_benchmark_v1`, 88 frozen cases. The benchmark sha256 is `94b4e79c49bc2c7a0c5bce0234298f9ebada568c1e767ee8651aac19ac3722b7` and is recorded in `FREEZE_MANIFEST.json`.
- **Cases preserved:** all 88 cases from the previous release are kept unchanged.
- **Case kinds:** alias sense, acronym sense, taxonomy label ambiguity, topic-mapping ambiguity, and hierarchy direction.

## 2. Independent labelling protocol (implemented, `scripts/semantic/benchmark_labelling.py`)

1. **`export`** — a reviewer-blind sheet: `independent_labels/labelling_sheet.csv` plus `LABELLING_GUIDE.md`.
   - Neither contains the model's answer, the rule verdict or the development labels.
   - Label set: SAME_CONCEPT, PARENT, CHILD, RELATED, PARTIAL_OVERLAP, UNRELATED, AMBIGUOUS, INSUFFICIENT_EVIDENCE.
2. **`ingest`** — each reviewer's file is stored with reviewer id, label, timestamp and label-set version.
   - Reviewer ids that name a model or assistant (`assistant|claude|model|qwen|gpt|llm|auto|bot`) are rejected.
   - A label set is counted only if it declares `independent: true` and `model_blind: true`.
3. **`agreement`** — agreement between reviewers:
   - Cohen's κ for 2 reviewers and Fleiss' κ for 3 or more;
   - per-case disagreement list.
4. **`adjudication-sheet` / `adjudicate`** — predefined adjudication, fixed before any label existed:
   - The adjudicator may only choose one of the reviewers' labels, or AMBIGUOUS.
   - Cases stay `UNRESOLVED` until adjudicated.
5. **`gold`** — builds `semantic_gold_v1`. Every case is recorded as UNANIMOUS, ADJUDICATED, UNRESOLVED or UNLABELLED. Only UNANIMOUS and ADJUDICATED cases are gold.
6. **`evaluate`** — computes, for each system:
   - accuracy, macro precision / recall / F1 and per-class metrics;
   - the confusion matrix;
   - definite predictions and precision on definite predictions (abstentions are counted separately, never as sense errors);
   - critical errors by category;
   - the baseline-vs-model 2×2 table, with the case ids in each cell;
   - the gate result.

   Critical-error categories: FALSE_SAME_CONCEPT, FALSE_PARENT, FALSE_CHILD, FALSE_RELATED, MISSED_SAME_CONCEPT, WRONG_HIERARCHY_DIRECTION, LEXICAL_COLLISION, ALIAS_SENSE_ERROR, ACRONYM_SENSE_ERROR, INSUFFICIENT_CONTEXT_ERROR, UNSUPPORTED_TAXONOMY_EVIDENCE.

Tests cover each step: `test_semantic_gold_evaluation.py` has 12 tests, covering κ values, adjudication rules, rejection of model-named reviewers, abstention handling, the 2×2 table, gate pass/fail, and per-class promotion.

## 3. Promotion gate v2 — declared before results

`data/evaluation/semantic_gate_v2.json` has sha256 `d16871cf…825f82`, pinned in `engine_config.json → semantic_promotion_v2`. It was declared at 2026-09-27T20:13:58Z, when 0 independent label files existed.

| Criterion | Value |
|---|---|
| independent reviewers | ≥ 1 (κ ≥ 0.60 required when ≥ 2) |
| gold cases | ≥ 80 |
| accuracy / macro F1 | ≥ 0.80 / ≥ 0.70 |
| false SAME_CONCEPT | ≤ 1 |
| wrong hierarchy direction | 0 |
| false PARENT or CHILD | ≤ 1 |
| unsupported taxonomy evidence / lexical collision | 0 / 0 |
| per promoted class | precision ≥ 0.90 with ≥ 8 predictions |

- **Classes that can be promoted:** SAME_CONCEPT, UNRELATED, PARENT, CHILD, RELATED.
- **If the gate fails:** SAFE_MODE. Decisions are recorded and shown, never applied.
- **If the gate passes:** only the classes that meet the per-class bar take effect; every other class stays blocked.
- **Changing the gate:** any change creates `semantic-gate-v3`, which must be declared before the results it will be applied to are seen.

**Disclosure.** The internal development numbers below were computed in the previous release. They were therefore known when gate v2 was declared. The gate is independent of *independent* labels, but it was not written in ignorance of the development preview. Gate v2 is stricter than those numbers (accuracy ≥ 0.80, against 0.32 for `QWEN_VALIDATED` in the preview).

## 4. Current result (`data/evaluation/semantic_benchmark_v1/results/semantic_ai_evaluation.json`)

- **Status:** `PENDING_INDEPENDENT_LABELS`
- **Independent reviewers:** 0
- **Mode:** `SAFE_MODE`
- **Reason:** no independent human labels exist for the frozen benchmark.
- **Consequence:** model accuracy is not claimed.
- **Next action:** an independent reviewer fills `labelling_sheet.csv`, then runs `benchmark_labelling.py ingest → agreement → gold → evaluate`.

In the final run, 274 semantic decisions are recorded:

- 0 have an effect on analytics;
- 42 carry `effect_blocked_reason = "promotion gate did not pass"`;
- 0 claim human validation. The database integrity check `semantic_decisions_claiming_human_validation` returns 0.

## 5. Internal development preview — NOT independent, NOT human-validated

The labels come from the development gold labelled by the assistant. They are shown only with `--internal-preview`, are labelled as such in the API and UI, and are never used by the gate.

Development label distribution (88 cases):

| Label | Cases |
|---|---|
| UNRELATED | 28 |
| RELATED | 23 |
| SAME_CONCEPT | 18 |
| CHILD | 12 |
| PARTIAL_OVERLAP | 4 |
| PARENT | 2 |
| INSUFFICIENT_EVIDENCE | 1 |

| System | Accuracy | Macro F1 | Definite predictions | Precision on definite | Critical-error rate |
|---|---|---|---|---|---|
| DETERMINISTIC_BASELINE | 0.000 | 0.000 | 0 (abstains on all 88) | — | 0.000 |
| QWEN_RAW | 0.511 | 0.241 | 87 | 0.517 | 0.364 |
| QWEN_VALIDATED | 0.318 | 0.169 | 52 | 0.539 | 0.114 |

Per-class precision for QWEN_VALIDATED:

| Class | Precision | Correct / predicted |
|---|---|---|
| SAME_CONCEPT | 0.31 | 4 / 13 |
| RELATED | 0.33 | 3 / 9 |
| UNRELATED | 0.72 | 21 / 29 |
| PARENT / CHILD | — | never predicted |

On these development labels, **no class would reach the 0.90 per-class bar**.

Critical errors:

- **QWEN_RAW:** FALSE_SAME_CONCEPT 23, ALIAS_SENSE_ERROR 18, UNSUPPORTED_TAXONOMY_EVIDENCE 11, ACRONYM_SENSE_ERROR 10, FALSE_RELATED 8, MISSED_SAME_CONCEPT 3, LEXICAL_COLLISION 2, INSUFFICIENT_CONTEXT_ERROR 1.
- **QWEN_VALIDATED:** MISSED_SAME_CONCEPT 14, FALSE_SAME_CONCEPT 9, ALIAS_SENSE_ERROR 6, FALSE_RELATED 5, ACRONYM_SENSE_ERROR 5, LEXICAL_COLLISION 2, UNSUPPORTED_TAXONOMY_EVIDENCE 1, INSUFFICIENT_CONTEXT_ERROR 1.

What the preview suggests (to be confirmed or rejected by independent labels):

- The validator cuts the critical-error rate by about two thirds, from 0.36 to 0.11. It does this mostly by abstaining.
- False SAME_CONCEPT remains the dominant severe error.

Baseline vs model (2×2 table):

- The baseline abstains on every case, so it is never "correct" on a definite label.
- QWEN_RAW is correct and the baseline wrong on 45 cases; both are wrong on 43.
- The case ids for each cell are in the results file.

## 6. A/B

The A/B comparison is the 2×2 table above plus the per-system metrics on identical cases. It becomes a real A/B result only against `semantic_gold_v1`. No production A/B traffic split exists; analytics use the deterministic arm until the gate passes.

## 7. What is not claimed

- No model accuracy.
- No human validation.
- No "independent ground truth" built from assistant labels.
- No promotion of any class.
