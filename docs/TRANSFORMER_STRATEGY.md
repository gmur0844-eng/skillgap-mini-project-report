# Transformer strategy: audit and recommendation (items 1–2 approved 2026-10-21; 3–4 pending)

Status: **recommendation only.** Nothing has been installed or downloaded, no model has been trained, and production
inference is unchanged. Every number below comes from a file in this repository; none is a prediction.

## 1. What the system does today

| Agent / component | Task | Current method | Accuracy evidence | Runtime (published run `0534d6e1d06a617f`) |
|---|---|---|---|---|
| Curriculum Understanding | PDF → courses, units, topics, outcomes | deterministic layout and structure rules (`curriculum_structuring.py`, `layout_aware_extraction.py`) | institution-format regression tests; per-document health checks; no labelled extraction set | `silver.structure` 6.4 s |
| Curriculum Understanding | topic → concept clusters | TF-IDF cosine (`semantic_backend.tfidf`) | none measured; lexical by design (`semantic_capability: "lexical overlap only -- not meaning-based"`) | `gold.concepts` 33.0 s |
| Curriculum Understanding | topic → reference (AICTE) mapping | TF-IDF + token containment | none measured | `gold.reference_mapping` 0.4 s |
| Discipline-to-Industry Relevance | which postings / skills belong to the programme | rules (`occupation_resolution.py`) + the new discipline profiles (populations listed per discipline) | none measured | in `industry.*` |
| Skill Intelligence | skill mention extraction | curated vocabulary + ESCO v1.2.1 label lookup | none measured | `industry.extract` 152.7 s (the slowest stage) |
| Skill Intelligence | mention → ESCO concept | exact/alias label match, TF-IDF lexical fallback, alias-sense and containment rules | known lexical failure fixed ("Azure" → "Azure SQL Database"), see `SEMANTIC_ENGINE_COMPARISON.md` | `industry.esco` 16.6 s |
| Semantic adjudication (shared) | SAME_CONCEPT / RELATED / PARENT / CHILD / UNRELATED between two terms | Qwen 2.5 7B via Ollama, **advisory only** under Safe Mode; replayed from a verified recording in uploads | frozen 88-case benchmark, **no independent human labels**; development preview only (below) | live: ~10 s per call; replay: no model call |
| Skill-Gap Reasoning | gap state | deterministic thresholds on demand support and coverage depth | rule tests; golden regression | `intelligence` 4.4 s |
| Curriculum Recommendation | action per established gap | deterministic rules preferring existing courses | rule tests | in `intelligence` |
| Peer comparison | concept overlap between curricula | TF-IDF | none measured | `peers.semantic_benchmark` 52.5 s |

Embedding back ends probed at run time (`run_report.json: backends_available`): `tfidf` AVAILABLE;
`sentence_transformer`, `onnx_embedding` and `api_embedding` UNAVAILABLE (package or model files absent, or no key).

### The only model evaluation that exists

`docs/SEMANTIC_AI_EVALUATION_REPORT.md`, on the frozen 88-case benchmark, against **development labels written by the
assistant** (explicitly *not* independent ground truth, never used by the promotion gate):

| System | Accuracy | Macro F1 | Critical-error rate |
|---|---|---|---|
| deterministic baseline (abstains) | 0.000 | 0.000 | 0.000 |
| Qwen raw | 0.511 | 0.241 | 0.364 |
| Qwen after validation rules | 0.318 | 0.169 | 0.114 |

No class reaches the 0.90 precision bar; 0 of 274 recorded model decisions have an effect on results. **These numbers
may not be used as evidence of model quality** until an independent reviewer labels the benchmark.

## 2. Failure modes the evidence shows

1. **Lexical blindness.** TF-IDF cannot match paraphrases with no shared words ("relational schema design" vs
   "database normalisation") and matches shared words with different senses. This affects concept clustering,
   reference mapping, peer overlap and the ESCO fallback.
2. **Sense ambiguity.** In the full-ESCO run documented in `SEMANTIC_ENGINE_COMPARISON.md`, 212 posting mentions are
   alias matches whose sense the text does not establish and 80 skills have only such mentions
   (`ALIAS_SENSE_REVIEW_REQUIRED`). "ML" and "AWS" are examples.
3. **Generative adjudication is unreliable here.** Qwen 7B over-predicts SAME_CONCEPT (23 false SAME_CONCEPT in the raw
   run) and costs ~10 s per decision on a local machine.
4. **Extraction is the time sink,** not similarity: `industry.extract` takes 52 % of the run.

## 3. Use-case decisions

| # | Use case | Recommended role | Candidate model category | Why |
|---|---|---|---|---|
| 1 | Skill extraction and normalisation | **Augment** (candidate generation only; ESCO + rules stay authoritative) | small sentence-embedding bi-encoder (≈20–120 M parameters) for mention → ESCO candidate retrieval | lexical fallback misses paraphrases; the rules that reject wrong senses must stay, so the model only proposes candidates |
| 2 | Industry skill ↔ curriculum topic matching | **Augment**, then possibly **replace** the TF-IDF similarity inside `SemanticBackend` after evaluation | the same bi-encoder; optional cross-encoder reranker for the top-k | this is exactly what an embedding model is for, and `SemanticBackend` already isolates it (one class to add) |
| 3 | Curriculum topic classification / understanding | **Experimental** | the same bi-encoder (nearest-reference-topic), no fine-tuning | structure extraction is rule-based and works; only the topic → concept step would benefit |
| 4 | Discipline → industry relevance | **Do not use a model now** | — | relevance is now decided by declared posting populations per discipline profile; it is auditable and has no labelled data to learn from |
| 5 | Skill-gap reasoning | **Do not use** | — | the gap state is a deterministic function of measured demand and coverage; a model would make it unexplainable |
| 6 | Curriculum recommendations | **Optional experimental, advisory text only** | the existing local generative model (Qwen via Ollama), wording only | may help phrase rationale; must never choose the action, and must be labelled as model-written |

## 4. Shared architecture

One **shared embedding service** behind the existing `SemanticBackend` interface, used by all agents that need
similarity (Curriculum Understanding, Skill Intelligence, peer comparison); nothing per agent.

* `fit/embed/similarity/describe` unchanged; a new `SentenceEmbeddingBackend` class registered in `_REGISTRY`.
* One model loaded once per process; embeddings cached by `sha256(model id + revision + normalised text)` on disk, so
  re-runs and uploads reuse them and the run id records the model identity (as `semantic_identity` does today).
* `describe()` records model name, revision, weights sha256 and pooling, so every similarity is traceable.
* Unavailable model → `BackendUnavailable` → TF-IDF, recorded in `backend_resolution.fallback_reason` (existing code
  path). Historical runs are never recomputed; a run with the model is a **new run id**.
* Optional reranker (cross-encoder) only for top-k candidate lists, only if the evaluation shows the bi-encoder alone
  falls short.
* Generative model stays where it is: advisory, Safe Mode, promotion gate, replayable.

Smallest practical combination: **one sentence-embedding model** (plus, conditionally, one reranker). No fine-tuning.

## 5. Baseline and evaluation plan

The current system is the baseline: the same fixed examples are scored with TF-IDF and with each candidate model.

| Task | Fixed set | Metrics | Labels |
|---|---|---|---|
| mention → ESCO concept | sample of real posting mentions (stratified: exact, alias, ambiguous, unmatched) | precision@1, recall@5, MRR; critical sense errors | two independent human reviewers, agreement (Cohen's κ) reported; disagreements adjudicated by a third |
| topic ↔ skill / reference topic | the existing reference mappings + peer topic pairs | precision@k, recall@k, nDCG@10 | same protocol |
| concept relation (existing 88 cases) | `semantic_benchmark_v1` (frozen, sha256 recorded) | accuracy, macro F1, per-class precision, critical-error rate | the existing independent-labelling protocol (`benchmark_labelling.py`) |
| cost | the published manifest, end to end | wall-clock per stage, peak memory, cache hit rate | measured |

Leakage prevention: splits frozen and hashed before any model is run; no model output is shown to labellers; the
development labels written by the assistant are excluded from every metric; no fine-tuning, so there is no training
set to leak into. Synthetic examples, if any are added for robustness checks, are labelled synthetic and reported
separately.

**Decision rule.** The embedding backend replaces TF-IDF for a task only if, on the independently labelled set, it
improves the task's primary metric with a non-overlapping bootstrap 95 % interval and does not increase critical
sense errors, at an acceptable cost on the user's Mac. Otherwise it stays experimental.

## 6. Implementation table

| Agent / component | Current | Weakness | Proposed role | Model category | Expected benefit | Resources | Evaluation | Priority | Recommendation |
|---|---|---|---|---|---|---|---|---|---|
| Skill Intelligence: ESCO normalisation | labels + TF-IDF fallback | misses paraphrases; lexical false matches | candidate retrieval (augment) | sentence-embedding bi-encoder | more correct candidates for review; rules still decide | one small model, CPU/Apple-silicon friendly; embedding cache | precision@1 / recall@5 on labelled mentions | 1 | **experiment** |
| Curriculum Understanding + peers: topic similarity | TF-IDF | lexical only | replace inside `SemanticBackend` if it wins | same bi-encoder | meaning-based clusters and peer overlap | same model (shared) | recall@k / nDCG@10 | 1 | **experiment** |
| Reranking of top-k | none | — | conditional fallback | cross-encoder | precision at the top of the list | second small model | precision@1 gain over bi-encoder | 3 | **defer** |
| Semantic adjudication | Qwen 7B advisory | low precision on development labels; slow | keep advisory | generative LLM | none until labelled evidence exists | existing | existing protocol | — | **keep as is** |
| Discipline relevance | profiles + rules | no labelled data | none | — | — | — | — | — | **do not use** |
| Gap reasoning | deterministic | — | none | — | — | — | — | — | **do not use** |
| Recommendations | deterministic | wording is template-like | rationale wording only | existing local LLM | readability | existing | human-rated quality | 4 | **defer** |

## 7. Is it worth the complexity?

Only for similarity (use cases 1–3), and only through the one shared embedding backend that the code was designed to
accept. The rest of the pipeline gains nothing measurable from a Transformer and would lose explainability. Without
independent labels no improvement can be claimed, so the first deliverable after approval is the labelled evaluation
set, not the integration.

## 8. Decisions that need your approval

1. ~~Install `sentence-transformers` (or `onnxruntime` + `tokenizers`) in the backend environment.~~ **Approved and
   done 2026-10-21** (see §9).
2. ~~Download one embedding model's weights (candidate list to be fixed before download; licence checked).~~
   **Approved and done 2026-10-21** (see §9).
3. Recruit two independent reviewers for the labelling protocol (the assistant cannot be one).
4. Whether the embedding backend may become the default for new runs if it passes the decision rule (historical
   runs, the protected release `c066b227857f9eaf` and the published run `0534d6e1d06a617f` are never recomputed).

## 9. Status after approval of items 1 and 2 (2026-10-21)

**Installed on the project owner's Mac** (macOS `.venv`, Python 3.14), from `backend/requirements-embedding.txt`:
sentence-transformers 5.7.0, transformers 5.20.2, torch 2.14.1 (CPU), huggingface_hub 2.2.0. The file is optional; the
default install (`requirements.txt`) is unchanged.

**Model.** `sentence-transformers/all-MiniLM-L6-v2`, revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, licence
Apache-2.0 (checked against an allow-list by `scripts/semantic/fetch_embedding_model.py` before download), 22 M
parameters, 384-dimensional embeddings, safetensors weights only, 14 files / 91.6 MB in
`data/models/embedding/all-MiniLM-L6-v2/` with `PROVENANCE.json` (sha256 of every file). Machine-local: `data/models/`
is git-ignored.

**Engine.** `semantic_backend._probe_sentence_transformer` loads the model only when the package is installed **and**
the model directory has a valid `PROVENANCE.json`; otherwise the run falls back to TF-IDF and records why. The model is
loaded once per process; vectors are cached in `data/cache/embeddings/` by model revision and file hashes. A run that
uses it records the repo id, revision and file hashes in `semantic_backend` and in its run id; TF-IDF run ids are
unchanged by this.

**Default unchanged.** `engine_config.json: semantic_backend` is still `"tfidf"`. The model is used only by an
explicit experiment: `python scripts/pipeline/run_knowledge_pipeline.py --semantic-backend sentence_transformer`
(a new run id; never made the published default; refuses `--publish` and `--record-baseline`). Uploaded analyses and
the API keep using TF-IDF.

**Checks.** `backend/tests/test_embedding_backend_opt_in.py` (stand-in package; no model run). On the Mac,
`scripts/semantic/check_embedding_backend.py` confirms the model loads through the engine and prints similarities for a
few hand-picked pairs; those numbers are a smoke check, not evidence of quality.

Smoke check on the Mac (2026-10-21): the engine resolved `sentence_transformer` (no fallback); model load 6.9 s,
10 texts encoded in 0.09 s. Cosine similarity, TF-IDF vs model: "relational schema design" ~ "database normalisation"
0.00 vs 0.40; "convolutional neural networks" ~ "deep learning for images" 0.00 vs 0.62; "TCP congestion control" ~
"transport layer protocols" 0.00 vs 0.49; "machine learning" ~ "machine shop safety" 0.21 vs 0.25; "binary search
trees" ~ "employee payroll accounting" 0.00 vs 0.01. Five pairs chosen by the assistant: they show the model loads and
behaves plausibly (paraphrases score above zero, the shared-word false friend is not resolved), nothing more.

**Not done (needs items 3–4).** No evaluation has been run: the labelled set of §5 needs two independent reviewers.
Until then no claim of improvement is made and the backend stays an experiment.
