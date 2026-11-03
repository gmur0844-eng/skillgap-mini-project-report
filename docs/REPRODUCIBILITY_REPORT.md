# Reproducibility Report

## Final run (after final blocker resolution): `5e2416e1ac2aa587`

| | run 1 | run 2 |
|---|---|---|
| run_id | 5e2416e1ac2aa587 | 5e2416e1ac2aa587 |
| content digest | c23b2ec2409ad23e... | c23b2ec2409ad23e... |
| analytical files compared | 65 | 65 (0 differ) |
| database publish | PASS | PASS (idempotent, 0 rows inserted) |
| semantic mode | REPLAY_VERIFIED_RUN (qwen-270-v3+replay-misses-1) | same |
| semantic cache hits / replay misses / model calls | 274 / 0 / 0 | 274 / 0 / 0 |

Evidence: `artifacts/reproducibility/final2/{run1,run2,compare}.json` (compare exit 0).
Inputs hashed into the run id: pipeline version, parser fingerprint, code fingerprint `13a3319b8eba1829`, config hash
`0190ef3a5859...`, semantic backend, every source SHA-256.
Environments: pipeline -- Linux container, Python 3.11.15 (`artifacts/environment/container_pipeline_env.txt`);
API/Flutter/DB runtime -- macOS, Python 3.14.7, exact lock `backend/requirements.lock`.

A run that was deliberately stopped mid-way while code changed (`cd1452009c97ca79`) was never published and is kept,
incomplete, under `artifacts/aborted_runs/` for audit.

---

## Previous final run d658c97abebca9f5 (kept for history)

The run id is `d658c97abebca9f5`, with engine `knowledge-engine-2.0.0`. It is a hash of these inputs:

| Input | Value |
|---|---|
| pipeline version | `knowledge-engine-2.0.0` |
| parser fingerprint | `a7f6801a5ad88f49` |
| code fingerprint | `61177c817ea483bb` |
| config hash | `4db072b9…` |
| semantic backend | TF-IDF |
| source document SHA-256s | (see the run manifest) |

The content digest is `130548a2181d3e328d60d70fbc55d054f470493ae2810ef26da8320a4695f23b`. It is a SHA-256 over every analytical file, sorted by path. The digest excludes the timing and memory reports (`run_report.*`, `observability.json`, `publish_report.json`).

## Two consecutive full runs (RAW → BRONZE → SILVER → HEALTH GATE → GOLD → PUBLISH)

| | Run 1 | Run 2 |
|---|---|---|
| run_id | d658c97abebca9f5 | d658c97abebca9f5 |
| content digest | 130548a2… | 130548a2… |
| analytical files compared | 63 | 63 (0 differ) |
| database publish | PASS (all rows inserted) | PASS (0 rows inserted, idempotent) |
| integrity violations | 0 | 0 |
| semantic mode | REPLAY_VERIFIED_RUN | REPLAY_VERIFIED_RUN |
| semantic cache hits / replay misses / model calls | 244 / 30 / 0 | 244 / 30 / 0 |

These results come from `scripts/evaluation/reproducibility_check.py`, which snapshots both runs and compares them. The evidence is in `artifacts/reproducibility/run1.json`, `run2.json` and `compare.json`, and the compare step exited with code 0.

## Semantic replay

The linked Mac ran the model. The pipeline host replays those recorded decisions and makes no model calls:

- The replay is registered under the top-level key `semantic_replay.runs` in `engine_config.json`. `semantic_ai` is unchanged, so the cache key (`model_key 8b81c19ed450357b`) is identical to the Mac run's.
- The replay is used only if all of these hold:
  - the cache file's SHA-256 matches;
  - the promotion-gate file's SHA-256 matches;
  - the prompt version matches;
  - this configuration computes the same cache file name.
- A candidate whose input and context hash exactly matches a recorded decision gets that decision (244 of 274).
- The other 30 are **REPLAY_MISS**:
  - All 30 are `AMBIGUOUS_TOPIC_MAPPING` candidates.
  - Their context changed after the candidates were frozen, because the silver attribution fix removed 47 misattributed topics and 5 outcomes.
  - A miss is recorded as `MODEL_FAILURE` with the reason `REPLAY_MISS … the model was not called`.
  - A miss has no timestamp or latency, so it is deterministic, and it has no effect.
  - A miss is not counted as a model call.

## Things that are deliberately not reproducible bit-for-bit

- **`run_report.json` / `observability.json`:** these hold stage timings and memory, and are excluded from the digest.
- **The Mac model run itself:** the model's `consistency` result was 20/20 same relationship, and 17/20 byte-identical outputs at temperature 0 on Ollama/Metal. That is why decisions are recorded once and replayed, never regenerated inside the pipeline.

## Preserved history

| Item | Location |
|---|---|
| Pre-V3 backup (read-only) | `artifacts/archive/pre-v3/`, including a PostgreSQL dump, GOLD 438ec2c0, the qwen-270-v1 run, and code/config/docs |
| Earlier GOLD runs | `data/gold/knowledge/<run_id>/` (never deleted) |
| Semantic runs | `data/semantic_runs/qwen-270-v1/` (V2), `data/semantic_runs/qwen-270-v3/` (V3) |
| Development benchmark (frozen) | `data/evaluation/semantic_benchmark_v1/` |
