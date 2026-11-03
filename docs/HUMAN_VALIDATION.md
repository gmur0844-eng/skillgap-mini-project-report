# Human validation (optional)

**Status: 0 human labels exist. Nothing in this project is human-validated.**

The system runs without human labels. Human review is an optional layer that, when supplied, measures the model
and may promote specific relationships; it never adds source evidence.

## States used in outputs

| State | Meaning |
|---|---|
| ACCEPTED | a deterministic rule established it (e.g. prefLabel exact, established alias) |
| MODEL_SUGGESTED | a lexical or language model proposed it (uncalibrated) |
| REVIEW_AVAILABLE | a review item exists; review is optional |
| REVIEW_REQUIRED | the rules could not decide; the item stays out of demand/coverage/gaps until decided |
| INSUFFICIENT_EVIDENCE | no conclusion possible from the data |
| HUMAN_VALIDATED | only after ingesting real labels — none |

## Frozen review set v1 (unchanged)

`data/human_validation/v1/` — 54 items frozen against engine-1.1 run `6472ec43cba27593` (see `human_validation_review_set_v1.md`
for how to fill it). Engine 2.0 changed the code, so by the v1 rule the frozen items now describe the **v1 model
outputs stored in the items**. The ingest script still refuses labels when the engine changed, unless run with
`--frozen-outputs-only`: then labels are evaluated against the stored v1 outputs and the evaluation states the
engine change and its scope. Nothing is claimed about engine 2.0 from v1 labels.

## Engine-2.0 review queue

Available without a file: `/api/v1/semantic/review` (270 adjudication candidates in the final run, all
`RULE_VERDICT_NO_MODEL`, `human_labels: 0`) and `industry/industry_review_queue.jsonl` (alias sense, acronym sense,
ambiguous ESCO, discipline relevance, high-frequency context-dependent labels, borderline recommendation). A v2
frozen review set was **not** created in this pass; creating one follows the v1 procedure
(`scripts/review/build_review_set.py`).

## Automated validation is not human validation

Graph consistency, taxonomy integrity, hard-case behaviour, schema validation of model output, SQL integrity checks
and the regression tests are AUTOMATED VALIDATION. They are reported as such (FINAL_REPORT §18) and never called
human validation.
