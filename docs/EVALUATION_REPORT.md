# Evaluation report (engine 2.0)

**No human labels exist.** Every labelled number below uses labels written by the assistant (the AI that built the
system) and is reported as such. Where no labels exist the metric is **NOT MEASURED**.

## 1. Labelled evaluations (assistant labels — not ground truth)

| Evaluation | n | Engine 1.1 (run 6472ec43, delta taxonomy) | Engine 2.0 (final run, full taxonomy) |
|---|---|---|---|
| Golden pages, topic recall (attribution-aware) | 36 expected topics on 4 pages | 1.0, 0 mis-attributed | 1.0, 0 mis-attributed (decoder unchanged) |
| Topic noise filter accuracy | 75 | 0.827 | 0.827 |
| Mapping links: precision of produced links / linked-vs-unrelated accuracy | 45 | 0.733 / 0.822 | 0.733 / 0.822 (mapping unchanged) |
| Posting mention counted as demand vs label: accuracy | 60 | 0.717 | **0.750** |
| … SKILL precision / recall | 43 SKILL labels | 0.964 / 0.628 | **0.967 / 0.674** |
| … sense accuracy of counted, ESCO-mapped mentions | | 22/25 = 0.88 | **24/27 = 0.889** |

The mention sample is not fully independent of rule development (see its caveat in `evaluation.json`). 60 items
give wide uncertainty; no significance claim is made.

## 2. Not measured

| Metric | Why |
|---|---|
| ESCO mapping precision/recall on the full taxonomy | no labelled mapping benchmark |
| Occupation mapping accuracy | no labels (22 established of 100 titles; 11 CANDIDATE kept for review) |
| Coverage relation / level accuracy | no labels |
| Subtopic hierarchy precision | no labels (see the structural-head correction in FINAL_REPORT §5) |
| Language-model adjudication quality | no model ran |
| Embedding vs TF-IDF comparison | no embedding model available |
| Calibration of any similarity score | no labels; `score_is_calibrated = false` everywhere |

## 3. Behaviour reports (no accuracy implied)

* Hard cases (`data/evaluation/results/hard_cases_v2.json`, 16 pairs): 1 conflated at the taxonomy level
  (`.NET`→*Visual Basic*, an ESCO altLabel, handled per mention by the alias-sense rule), 13 left sides held back by
  the label evidence rule, "network" inside "neural network" → PARTIAL (known weakness).
* Ten real-world cases (`data/evaluation/results/real_world_cases.md`), selected by fixed rules from the final run.
* Delta-only vs full taxonomy under the same engine: `SEMANTIC_ENGINE_COMPARISON.md`.

## 4. Automated validation (not human validation)

515 regression tests pass; static generalization audit 0 forbidden conditionals; ESCO taxonomy integrity (0
dangling references, 0 cycles); knowledge-graph checks; SQL integrity checks after publish; schema validation of
model output (tested with a fake provider: invalid JSON retried, then REVIEW_REQUIRED). Final values: FINAL_REPORT §18.
