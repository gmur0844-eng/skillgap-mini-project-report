# Semantic intelligence (engine 2.0)

Earlier history (engine 1.x: embedding backends, alias-sense correction, hard negatives) is in
`docs/semantic_layer_engine1.md` and is still valid. This file describes what engine 2.0 adds and what it actually ran.

## Layers (neuro-symbolic, in the order they apply)

1. **Symbolic / taxonomy** — ESCO labels (pref/alt/hidden, qualifier-stripped), prefLabel precedence, label evidence
   rule (single ordinary words, qualifier-stripped-only matches → INSUFFICIENT_EVIDENCE), qualification-context rule.
2. **Context rules** — alias sense (an alt/hidden label counts only if the same text contains another label of the
   concept), acronym sense (short curated acronyms need other technical evidence), containment rule (a surface whose
   words are a strict subset of a longer label's words is RELATED, never the same concept), coverage relation by
   label position (DIRECT / PARTIAL / RELATED / INCIDENTAL).
3. **Lexical similarity** — TF-IDF (concept clustering, reference mapping tiers, lexical ESCO fallback for curated
   tokens). Uncalibrated; never called confidence.
4. **Graph** — hierarchy, prerequisites, ESCO broader relations; consistency checks.
5. **Model adjudication** — `SemanticModelProvider` for candidate pairs the rules left open. **No model was available
   in this run**; the deterministic fallback recorded the rule verdict for every candidate.

## Semantic model provider

`backend/app/knowledge_engine/semantic_provider.py`

* Providers: `OllamaProvider`, `OpenAICompatibleProvider` (LM Studio, llama.cpp server, vLLM…), `LocalLLMProvider`
  (transformers), `EmbeddingProvider` (similarity only, never a decision), `DeterministicFallbackProvider`.
  Configured under `semantic_ai.providers` (model names empty until someone configures a model; API keys only via
  named environment variables).
* Candidate generation first (`intelligence.adjudication_candidates`): alias-sense mentions under review, ambiguous
  taxonomy labels (up to 3 candidates each), ambiguous topic mappings (2 candidates each); limit 300.
* Output contract: JSON `{relationship, reason, evidence[], alternatives[], uncertainty}` with relationship in
  SAME_CONCEPT / PARENT / CHILD / RELATED / PARTIAL_OVERLAP / UNRELATED / AMBIGUOUS / INSUFFICIENT_EVIDENCE (each
  defined in the prompt). Invalid output → retry (`max_retries`) → `REVIEW_REQUIRED` with the validation errors.
* Decision record: decision_id, run_id, provider, model, model_version, prompt_version, input_hash, context_hash,
  output_hash, source/candidate entity, relationship, reason, evidence, alternatives, uncertainty, rule verdict,
  decision_state (`MODEL_SUGGESTED` / `REVIEW_REQUIRED` / `RULE_VERDICT_NO_MODEL`), attempts, timestamp,
  `is_human_validated=false`, `score_is_confidence=false`.
* Cache: `data/cache/semantic_decisions/<provider>-<hash(model, prompt version, config)>.jsonl`, keyed by
  hash(model key, input hash, context hash). A rerun reuses decisions (tested).
* A model decision never becomes source evidence and never changes demand, coverage or gaps by itself; it is
  recorded next to the rule verdict (DB: `knowledge.semantic_decision`; integrity check
  `model_decisions_without_provider` = 0 and `semantic_decisions_claiming_human_validation` = 0).

## What ran (final run)

Probes: Ollama and OpenAI-compatible endpoints → connection refused; transformers not installed. Provider status
**AI_PROVIDER_UNAVAILABLE**. 270 candidates (212 alias sense, 36 ambiguous taxonomy label, 22 ambiguous topic
mapping) → 270 decisions, all `RULE_VERDICT_NO_MODEL`. See `SEMANTIC_ENGINE_COMPARISON.md` for the environment
inspection (container and linked Mac).

To use a model: run Ollama (or an OpenAI-compatible server) reachable from where the pipeline runs, set
`semantic_ai.providers[].model`, rerun. The same candidates are then adjudicated and cached; results are
`MODEL_SUGGESTED`, evaluated only on held-out human labels.

## Hard cases (test data, not rules)

`data/evaluation/semantic_hard_cases_v2.json` (16 pairs from the specification; expectations transcribed by the
assistant, not human labels). `scripts/evaluation/hard_case_report.py` reports behaviour with production mechanisms
only. Result on the full taxonomy: 0 pairs conflated at the ESCO-concept level except `.NET`/`Visual Basic`
(an ESCO altLabel — handled per mention by the alias-sense rule, so it does not count as demand without other
evidence); 13 of 16 left sides held back by the label evidence rule (e.g. single words "Java", "Git", "Python" —
this protects precision and costs recall); "network" inside "neural network" gets PARTIAL — a known weakness of the
head-position rule. A test fails if any engine-2.0 module contains a conditional on one of these terms.
