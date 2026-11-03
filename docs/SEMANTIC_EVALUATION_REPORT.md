# Semantic Evaluation Report — Engine V3 (qwen-270-v3)

> **Development estimates only.** The benchmark is a DEVELOPMENT GOLD SET labelled by the assistant, not by
> independent human reviewers. No number here is a validated accuracy.

## 1. What was evaluated

| System | What it is | Cases |
|---|---|---|
| BASELINE | Deterministic rules alone. Every candidate is AMBIGUOUS, because candidates exist only where the rules could not decide. | 75 pool cases |
| V2_RAW | The qwen-270-v1 run (adjudicate-v2): the model's relationship, not validated. | 75 pool cases |
| V3_RAW | The qwen-270-v3 run (adjudicate-v3): the model's relationship before validation. | 88 (75 pool + 13 diagnostics) |
| V3_VALIDATED | What downstream code may read. Details below. | 88 |

How V3_VALIDATED is derived:
- A MODEL_SUPPORTED decision keeps the model's relationship.
- A validator downgrade becomes INSUFFICIENT_EVIDENCE.
- MODEL_SUGGESTED keeps AMBIGUOUS or INSUFFICIENT_EVIDENCE.
- REVIEW_REQUIRED becomes AMBIGUOUS.

Run details:
- Model and runtime: qwen2.5:7b-instruct (Q4_K_M, digest 845dbda0…) on Ollama 0.34.4, on a MacBook Air M5 with 16 GB. Temperature 0, sequential.
- Volume: 283/283 decisions, 3001 s total. Mean latency 10.6 s, p95 15.1 s. Tokens: 221,152 prompt and 32,097 output.
- Candidates are frozen at sha `a889097d…`. The benchmark is frozen at sha `94b4e79c…` and was verified by the evaluator before scoring.

## 2. Benchmark and labelling protocol

The set has 88 cases:
- **By kind:** ALIAS_SENSE 45, AMBIGUOUS_TAXONOMY_LABEL 18, AMBIGUOUS_TOPIC_MAPPING 12, DIAGNOSTIC 13.
- **By label:** UNRELATED 28, RELATED 23, SAME_CONCEPT 18, CHILD 12, PARTIAL_OVERLAP 4, PARENT 2, INSUFFICIENT_EVIDENCE 1.

Cases were selected in this order: every hard-case surface first (at most 2 per surface), then candidate-id-hash order within each kind until the quotas were reached, then all 13 diagnostics.

Protocol, applied case by case:
1. Answer the V3 question: *Does the LEFT expression mean, represent, teach or require the RIGHT concept in this context?*
2. Read only the source items (posting sentence, job title, course, unit, outcomes) and the concept items (ESCO description and hierarchy).
3. Ignore the candidate-generation metadata (for example "X is an ESCO altLabel of Y").
4. Apply the definitions used by the prompt:
   - **SAME_CONCEPT:** LEFT expresses the concept itself.
   - **PARENT / CHILD:** broader / narrower. Containment of a string is never hierarchy.
   - **RELATED:** associated, but neither contains the other.
   - **PARTIAL_OVERLAP:** shared content.
   - **UNRELATED:** a different sense.
   - **INSUFFICIENT_EVIDENCE:** the context does not decide.
5. Record one label, one evidence span and a one-line rationale.

Known biases:
- The labeller had seen the V2 outputs for the 75 pool cases.
- There is one labeller, with no agreement measurement.
- This protocol description was written after the freeze. It describes what was applied; it is not a pre-registration.

The set was frozen before any V3 output existed. It is not edited; a correction creates `semantic_benchmark_v2`.

## 3. Results on the benchmark

Committed = a definite relationship (SAME_CONCEPT, PARENT, CHILD, RELATED, PARTIAL_OVERLAP or UNRELATED).

| System | n | Agreement with dev gold | Committed | Coverage | Precision when committed |
|---|---|---|---|---|---|
| BASELINE | 75 | 0.000 | 0 | 0.00 | — |
| V2_RAW | 75 | 0.347 | 69 | 0.92 | 0.377 |
| V3_RAW | 88 | 0.511 | 87 | 0.99 | 0.517 |
| V3_VALIDATED | 88 | 0.318 | 52 | 0.59 | 0.538 |

Per class (precision / recall), all cases:

| Class | V2_RAW | V3_RAW | V3_VALIDATED |
|---|---|---|---|
| SAME_CONCEPT | 0.33 / 1.00 | 0.39 / 0.83 | 0.31 / 0.22 |
| RELATED | 0.36 / 0.21 | 0.44 / 0.35 | 0.33 / 0.13 |
| UNRELATED | 0.86 / 0.24 | 0.73 / 0.79 | 0.72 / 0.75 |
| CHILD | — / 0.00 | — / 0.00 | — / 0.00 |
| PARENT | 0.17 / 0.50 | — / 0.00 | — / 0.00 |

Special measures:

| Measure | V2_RAW | V3_RAW | V3_VALIDATED |
|---|---|---|---|
| Lexical-collision rejection (UNRELATED on collision cases) | 0.24 (n=25) | 0.79 (n=28) | 0.75 (n=28) |
| Collisions called SAME_CONCEPT | 13 | 2 | 2 |
| Alias SAME_CONCEPT precision | 0.29 (34 predictions) | 0.44 (18 predictions) | 0.00 (1 prediction) |
| Alias UNRELATED precision | 1.00 (4 predictions) | 0.86 (14 predictions) | 0.85 (13 predictions) |
| Hierarchy direction (PARENT/CHILD predicted on hierarchy gold) | 2 (1 correct, 1 reversed) | 0 | 0 |

Diagnostics:
- **V3_RAW correct: 6/13.** These were:
  - Angular momentum ≠ Angular, and Angular = Angular.
  - Neural network ≠ computer network.
  - JavaScript ≠ Java.
  - The C/C++ buffer-overflow case (RELATED).
  - DBMS = database management systems.
- **Missed:**
  - neural network models → artificial neural networks: called UNRELATED.
  - SQL Injection → SQL: called UNRELATED instead of RELATED.
  - Git/GitHub, Python for Data Science, CNN: called SAME_CONCEPT instead of CHILD.

## 4. Population behaviour (all 283 decisions)

Validated states:
- MODEL_SUPPORTED 133
- INSUFFICIENT_EVIDENCE 135 (validator downgrades)
- REVIEW_REQUIRED 11
- MODEL_SUGGESTED 4

Grounding:
- Schema-valid 100%.
- Evidence traceable to an input item: 96.1%.
- Source-side evidence: 83.2%.
- Metadata cited: 7.2%.
- Metadata-only support: 0.

Validator findings:

| Finding | Count |
|---|---|
| NO_CONCEPT_EVIDENCE | 121 |
| NO_SOURCE_EVIDENCE | 47 |
| ALIAS_SAME_CONCEPT_WITHOUT_SOURCE_TEXT | 31 |
| METADATA_CITED | 20 |
| QUOTE_NOT_IN_ITEM | 11 |
| NON_DEFINITE | 4 |
| SOURCE_TYPE_MISLABELLED | 1 |

Consistency: 20/20 re-asked candidates gave the same relationship, and 17/20 gave byte-identical output.

V2 → V3 transitions on the pool (ALIAS_SENSE):
- Of V2's 169 SAME_CONCEPT decisions, V3_VALIDATED gives:
  - SAME_CONCEPT 12
  - RELATED 21
  - UNRELATED 15
  - INSUFFICIENT_EVIDENCE 113
  - AMBIGUOUS 8
- The systemic V2 failure is therefore gone: the taxonomy statement is no longer accepted as evidence.

## 5. Findings

1. **V3 fixed the V2 systemic failure.** The metadata-as-evidence pattern is eliminated: 0 metadata-only supported decisions. Lexical-collision rejection rises from 0.24 to 0.75–0.79.
2. **The model does not use the hierarchy classes.** It gave 0 CHILD predictions against 12 gold CHILD cases. Narrower concepts are called SAME_CONCEPT. This is a model limitation at 7B / Q4, not a prompt defect we tuned around.
3. **The validator trades coverage for honesty.** Precision when committed is roughly unchanged (0.52 → 0.54), but 41% of cases become abstentions. Most downgrades are NO_CONCEPT_EVIDENCE: the model states a meaning relation without quoting the concept description.
4. **Precision when committed is about 0.54.** That is far below what an authoritative taxonomy mapping needs.

## 6. Safety gate (pre-declared in `engine_config.json` before V3 outputs existed)

| Check | Value | Threshold | Pass |
|---|---|---|---|
| Supported SAME_CONCEPT alias predictions | 1 | ≥ 8 | ✗ |
| Precision of SAME_CONCEPT alias | 0.00 | ≥ 0.85 | ✗ |
| Lexical collisions supported as SAME_CONCEPT | 2 | 0 | ✗ |
| Precision of UNRELATED alias | 0.846 | ≥ 0.85 | ✗ |
| Schema-valid rate | 1.00 | ≥ 0.98 | ✓ |
| Metadata-only supported | 0 | 0 | ✓ |

**GATE: FAILED.** What this means in practice:
- No V3 decision changes a mention's sense state, a skill's ESCO status, demand counts or a graph edge.
- Every V3 decision is still stored with its model, prompt, hashes, evidence, validated state and findings. It can be seen via `/api/v1/semantic/decisions`, with `effect = null` and `effect_blocked_reason = "promotion gate did not pass"`.
- Nothing is labelled HUMAN_VALIDATED.

What would change this:
- Independent human labels (see `docs/HUMAN_VALIDATION.md`).
- A stronger model.
- A V4 prompt, evaluated on a NEW frozen benchmark (v2). The gate is never re-run on v1 after tuning.

## 7. Artifacts

- `data/semantic_runs/qwen-270-v3/`:
  - `candidates.json`
  - `freeze_manifest.json`
  - `out/`: decisions, consistency, memory, run_meta and cache
  - `analysis/evaluation_v3.json`
  - `analysis/benchmark_predictions.jsonl`
  - `analysis/promotion_gate.json`
- `data/evaluation/semantic_benchmark_v1/` (frozen)
- `scripts/semantic/evaluate_v3.py`

## 8. Follow-up run: qwen-v3-replay-misses-1 (the 30 replay misses)

The SILVER attribution fix changed the context of 30 `AMBIGUOUS_TOPIC_MAPPING` candidates, so no recorded decision matched them.

**How they were decided:**
- The pipeline exported them exactly as the model would see them (`intelligence/semantic_pending_candidates.jsonl`).
- They were frozen as a **new** run (`data/semantic_runs/qwen-v3-replay-misses-1`, candidates sha `12d10de0…`, hashes re-verified).
- The same model, prompt and schema decided them on the Mac: 30/30 decisions, 173.6 s, mean 6.0 s, p95 6.9 s; re-ask consistency 5/5 identical.

**Validated states:**

| State | Relationship | Decisions |
|---|---|---|
| MODEL_SUPPORTED | UNRELATED | 21 |
| MODEL_SUPPORTED | RELATED | 3 |
| MODEL_SUPPORTED | SAME_CONCEPT | 2 |
| REVIEW_REQUIRED | UNRELATED / RELATED | 4 |

**How the decisions are replayed:**
- The replay cache is the union of both runs' recorded caches. It is registered as `qwen-270-v3+replay-misses-1`, and each component's sha is listed in `engine_config.json` `semantic_replay`.
- Replay misses in the final run: **0**.

**Effect on downstream results:** none. The qwen-270-v3 promotion gate (FAILED) governs these decisions too, so they have no effect. Neither the earlier runs nor the frozen benchmark were modified.

**Validator v2.1.** The only change to the validator after V3 is that PARENT/CHILD now also needs a cited *directional* item (ESCO hierarchy/relation, course/unit title or learning outcome). A justification sentence alone no longer counts, because containment is never hierarchy. The model made no PARENT/CHILD predictions on the benchmark, so the gate result is unchanged.

**Independent labelling infrastructure.** `scripts/semantic/benchmark_labelling.py`:
- `export` produces a model-blind, gold-blind sheet plus a guide.
- `ingest` requires a named human reviewer (the assistant or a model is refused), validates every label, and stores immutable `labels_<reviewer>_<version>.json`.
- `compare` reports per-class precision/recall against the independent labels, plus Cohen's κ against the development gold.

Independent labels so far: **0**. The benchmark therefore remains an **INTERNAL_DEVELOPMENT_EVALUATION**.
