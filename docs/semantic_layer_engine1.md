# Semantic layer — upgrade status, alias-sense correction, hard negatives

> **Counts in this document describe the runs they were written for (up to run d140f830ab26adeb).** From run f173ee4fff47e2a6 on, topic cleaning changed the concept population: 1,318 concepts across all non-peer curricula, of which 1,093 contain a target-curriculum topic; the current graph has 10,331 nodes and 15,689 edges (run 84d7737ccb8e4d87). Current figures, with their scope, are in `docs/FULL_CONSISTENCY_AUDIT.md`. Annotated 2026-10-01; the text below is unchanged.

Final run **`6472ec43cba27593`** (pipeline `knowledge-engine-1.1.0`, code fingerprint `889d95730b7af071`, config
`1.2.0`, content digest `488fd701…8d46`). Previous run `81c8820d2bdaa681` is kept unchanged under `data/gold/knowledge/`.

## 1. Environment (inspected before any change)

| Item | Found |
|---|---|
| Python | 3.11.15 |
| PyTorch, CUDA, GPU | not installed / none (`nvidia-smi` absent), 2 CPUs, 7.8 GB RAM, ~30 GB disk free |
| transformers, sentence-transformers, tokenizers, huggingface_hub | not installed |
| onnxruntime | 1.25.0 installed, but no sentence-embedding model: the only `.onnx` files are a file-type classifier and runtime test models |
| HuggingFace cache | none |
| Network | PyPI: "no matching distribution" for sentence-transformers; `huggingface.co` → HTTP 403 from the organisation egress proxy (policy denial, not retried or routed around) |

**Result: no transformer or embedding model can run here.** The embedding backend is implemented behind the existing
abstraction but reports `UNAVAILABLE` with the reason; nothing is labelled "semantic embedding" that is not one.

## 2. What was built

* **Backends** (`semantic_backend.py`): `tfidf` (unchanged, deterministic fallback, used), `sentence_transformer`
  (loads a local model directory when the package and files exist), `onnx_embedding` (probe), `api_embedding` (probe).
  `available_backends()` and every run report record which were available and why not.
* **EmbeddingBackend** — any encoder behind `fit / embed / similarity / describe`; provenance = model id, model version,
  configuration and its hash; `semantic_capability` says "embedding-based semantic similarity (uncalibrated; not confidence)".
* **EmbeddingCache** — vectors keyed by SHA-256 of the text inside a file keyed by model id + configuration hash;
  unchanged texts are never re-embedded; a new configuration gets a new cache (tested with a deterministic test double).
* **Contextual input** — `contextual_input(text, context)` builds "discipline | document | course | unit | text |
  neighbours: …" from whatever metadata a record carries; no subject assumptions (tested).
* **Separate signals on every linked topic mapping** (440): `lexical_similarity` (TF-IDF cosine of the topic texts),
  `context_similarity` (TF-IDF cosine of course title + unit + sibling topics), `semantic_similarity = null` with
  `semantic_similarity_status = EMBEDDING_BACKEND_UNAVAILABLE`, `taxonomy_similarity = null`, `composite_score = null`,
  plus provenance (backend, parameters, `similarity_method`, `score_is_calibrated = false`, SHA-256 of both texts).
  The context signal is recorded only; it does **not** change the relationship decision (median 0.144; 180 of 440
  linked mappings share almost no unit context, < 0.1 — these fed the review set).
* **Concept discovery, clustering comparison, before/after metrics for an embedding model: not run** — there is no
  embedding model to compare. TF-IDF concept discovery is unchanged (1,337 concepts, silhouette 0.110).

## 3. Alias-sense correction (generic)

The supplied delta really lists ".NET" as an English altLabel of ESCO "Visual Basic"
(`…/skill/13bdd41a-2a18-441f-96db-41252c519413`). The pipeline had treated that taxonomy fact as proof that every
".NET" in a posting means Visual Basic. The rule now separates the two facts:

| Match | Taxonomy fact | Meaning in the text |
|---|---|---|
| prefLabel, exact or case/whitespace-normalized | established | established (identity preserved) |
| altLabel that is a spelling variant of the prefLabel (same words, character ratio ≥ 0.9) | established | established |
| any other altLabel (prefLabel differs) | `TAXONOMY_ALIAS_MATCH` | established only if the same posting also contains **another label of that concept**; else `ALIAS_SENSE_REVIEW_REQUIRED` |
| short upper-case curated acronym (AWS, GCP) | curated token | established only if another curated technical token or a technical-looking label (digit, symbol, camel case) occurs in the posting; else `ACRONYM_SENSE_REVIEW_REQUIRED` |

Decided per mention (the same alias can be established in one posting and not in another). Unestablished mentions keep
their raw text, span, context and ESCO candidate, go to the review queue, and do not enter demand, coverage, gaps or
recommendations. A skill with no established mention gets `esco_status = ALIAS_SENSE_REVIEW_REQUIRED`, `esco_uri = NULL`,
`taxonomy_candidate_uri` = the ESCO concept (the ESCO row is not deleted). No surface, label or subject is named in code;
the static audit still reports 0 conditionals.

### Before (run 81c8820d) → after (run 6472ec43)

| Measure | Before | After |
|---|---|---|
| mention sense states | — | ESTABLISHED 315 · ESTABLISHED_BY_CONTEXT 6 · ALIAS_SENSE_REVIEW_REQUIRED 16 · ACRONYM_SENSE_REVIEW_REQUIRED 2 |
| mentions counted as demand | 163 in 64 postings | 145 in 59 postings |
| analytics-eligible skills | 93 | 86 |
| ESCO-mapped eligible skills | 84 | 78 |
| skill statuses | EXACT 58 · NORMALIZED 26 | EXACT 58 · NORMALIZED 20 · **ALIAS_SENSE_REVIEW_REQUIRED 6** (others unchanged: AMBIGUOUS 1, UNMAPPED 8, INSUFFICIENT_EVIDENCE 43) |
| demand rows | 89 (SUPPORTED 7, OBSERVED 13, INSUFFICIENT 69) | 82 (SUPPORTED 4, OBSERVED 14, INSUFFICIENT 64) |
| removed from demand | — | Visual Basic (5, via ".NET"), use spreadsheets software (7, via "MS Excel"), solve technical problems (1), search engines (1), statistics (1, via "data collection"), SAP Data Services (1), gcp (1, Good Clinical Practice context) |
| changed | — | aws 5 → 4 postings (SUPPORTED → OBSERVED; the EY service-line mention is now under review) |
| gaps | 89: MISSING 1 · PARTIAL 20 · INSUFFICIENT 68 | 82: MISSING 1 · PARTIAL 19 · INSUFFICIENT 62 (statistics PARTIAL and six INSUFFICIENT gaps removed; no classification changed) |
| recommendations | 1 (SQL, EXPAND_EXISTING_TOPIC) | **1, identical** — SQL: ESCO EXACT, 6/100 postings, 6/95 companies, 4/113 target courses, PARTIAL |
| suppressions | 88 | 81 |
| industry review items | 14 | 28 (ALIAS_SENSE_CHECK 6, ACRONYM_SENSE_CHECK 2, HIGH_FREQUENCY_CONTEXT_DEPENDENT_LABEL 11 — this kind never fired before because of a bug, fixed —, DISCIPLINE_RELEVANCE_UNESTABLISHED 3, HIGH_DEMAND_UNMAPPED 3, AMBIGUOUS_ESCO 2, BORDERLINE_RECOMMENDATION 1) |
| assistant-labelled mention sample (60) | precision 0.968, recall 0.698, sense 24/28 | precision 0.964, recall 0.628, sense 22/25 |

The recall drop is the price of the rule: "MS Excel" (twice in the sample) is a real skill whose ESCO meaning
("use spreadsheets software") is plausible but not established by the text alone — it now waits for review.

## 4. Hard negatives (`data/evaluation/semantic_hard_negatives.json`, tested in `test_semantic_sense.py`)

| Case | Mechanism | Status |
|---|---|---|
| Angular vs "Angular momentum" | label evidence rule | HANDLED |
| .NET vs Visual Basic; positive control "Visual Basic 6 and .NET" | alias-sense validation | HANDLED |
| GCP (Good Clinical Practice) vs cloud; positive control "AWS, GCP and Docker" | acronym-sense validation | HANDLED |
| "version control systems" vs ESCO "control systems" | none | **KNOWN_FAILURE** (pinned) |
| database management vs management | token containment → CHILD, never SAME_CONCEPT | HANDLED |
| test vs testing | no morphology identity → RELATED | HANDLED_CONSERVATIVELY |
| "Stack" across course families | family scoping of candidates | HANDLED |
| "Mass Communication students" | label evidence rule | HANDLED |
| "communication skills", "accounting work in Tally" | label evidence rule | KNOWN_LIMITATION (real skills held back) |

## 5. Human benchmark and evaluation status

No human label exists. The frozen review set `data/human_validation/v1/` (54 items, see
`docs/human_validation_review_set_v1.md`) is the benchmark; its hash split is DEVELOPMENT 17 / VALIDATION 17 / FINAL_TEST 20 —
too small for significance tests, stated in the manifest. `semantic_similarity` stays "not confidence" until labelled
examples allow calibration. Existing assistant-labelled samples are kept and still reported as assistant labels.

## 6. Cost

Cached run 186 s total; `industry.extract` 132 s (label matching over 7,667 topics + 100 postings; peak heap 53 MB),
`gold.concepts` 37 s (peak heap 182 MB), RSS peak 296 MB, CPU only. The new context signal adds < 1 s to mapping.
Embedding cache size: 0 (no embedding model ran).

## 7. Limitations

TF-IDF remains the only similarity; the context signal is lexical too; the "version control systems" head-noun error
remains; alias- and acronym-sense rules trade recall for precision; nothing is human-validated.
