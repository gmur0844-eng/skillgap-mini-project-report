# Semantic engine comparison

## What could be compared

| Engine / provider | Availability (probed at run time) | Used |
|---|---|---|
| TF-IDF (`semantic_backend.tfidf`) | available | **yes** — concept clustering, reference mappings, lexical ESCO fallback |
| sentence-transformers embedding | package not installed; `pip` → "no matching distribution"; huggingface.co → HTTP 403 (egress policy, not retried) | no |
| ONNX embedding | onnxruntime 1.25 installed, no sentence-embedding model file | no |
| API embedding | no endpoint configured | no |
| Ollama (`127.0.0.1:11434` / `OLLAMA_HOST`) | connection refused; no model name configured | no |
| OpenAI-compatible server (LM Studio, llama.cpp, vLLM; `127.0.0.1:1234` / `OPENAI_COMPATIBLE_BASE_URL`) | connection refused; no model name configured | no |
| local transformers LLM (`LOCAL_LLM_MODEL_DIR`) | `transformers` not installed | no |
| deterministic fallback | always | **yes** — records the rule verdict as `RULE_VERDICT_NO_MODEL`, `AI_PROVIDER_UNAVAILABLE` |

### The linked Mac

The session was linked to the user's Mac (macOS arm64). Names-only listings (no folder was connected, so no file
contents were read) showed: no `Ollama.app` or `LM Studio.app` in `/Applications` or `~/Applications`, no `~/.ollama`
or `~/.lmstudio`; `~/.cache/huggingface/hub` holds one dataset (`datasets--dmarsili--RSVQA-LR-2k`) and no model.
The device shell runs in an isolated Linux VM and cannot reach services on the Mac's own localhost, so even a model
served on the Mac could not be called from this pipeline run. RAM/GPU of the Mac were not measured.

**Result: no language model and no embedding model was available. No model benchmark was run; no model-vs-TF-IDF
comparison exists.** Claims such as "semantic understanding" are not made; TF-IDF similarity is lexical.

## What was compared instead (real runs, same code — engine 2.0)

| | delta-only taxonomy (run `cbd6b248…`) | full ESCO v1.2.1 (final run) |
|---|---|---|
| matching concepts / labels | 9,298 (incl. 336 skill groups) / ~17k | 13,939 skills / 101,538 terms |
| posting + topic mentions | 339 | 1,016 |
| normalized skills | 136 | 357 |
| ESCO-mapped eligible skills | 78 | 106 |
| mention sense states | ESTABLISHED 315 · BY_CONTEXT 6 · ALIAS_REVIEW 16 · ACRONYM_REVIEW 2 | ESTABLISHED 765 · BY_CONTEXT 38 · ALIAS_REVIEW 212 · ACRONYM_REVIEW 1 |
| demand rows (SUPPORTED) | 82 (4) | 115 (5) |
| gaps MISSING / PARTIAL / INSUFFICIENT | 1 / 19 / 62 | 1 / 24 / 90 |
| recommendations | 1 (SQL, EXPAND_EXISTING_TOPIC) | 1 (SQL, EXPAND_EXISTING_TOPIC, same four courses) |

The delta-only run under engine 2.0 reproduces the engine-1.1 industry numbers exactly (339 mentions, 136 skills,
78 mapped, 82 demand rows, 1 recommendation) — engine 2.0 changes nothing when only the delta is used.

Differences caused by the full taxonomy (facts from the runs):

* **Longer labels win.** "SQL Server" is an ESCO skill; postings that say only "SQL Server" no longer count as
  "SQL" (SQL 6 → 5 postings; SQL Server 3 postings).
* **"AWS"** is an ESCO hiddenLabel of *cloud technologies*; under the alias-sense rule the 6 mentions go to review
  instead of counting as demand (it was a curated technology token with 5 postings before).
* **A lexical false match was found and fixed.** In the first full-ESCO run, "Azure" matched the altLabel "Azure SQL
  Database" of *SQL Server* by TF-IDF (score above threshold) and inflated *SQL Server* to 6 postings. A generic
  containment rule now refuses a match when the surface's words are a strict subset of a longer label's words
  (recorded as `CONTAINED_IN_LONGER_LABEL`, status UNMAPPED); a TF-IDF match to an alt/hidden label also goes
  through the alias-sense rule. After the fix: azure 5 postings (UNMAPPED, SUPPORTED), SQL Server 3.
* **More aliases, more review.** 212 posting mentions are alias matches whose sense the text does not establish;
  80 skills have only such mentions (`ALIAS_SENSE_REVIEW_REQUIRED`).
* **"ML"** is AMBIGUOUS in the full taxonomy (altLabel of *machine learning* and qualifier-stripped prefLabel of
  *ML (computer programming)*).
