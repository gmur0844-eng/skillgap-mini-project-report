# Performance audit and live-mode cache fix (Phase 10)

*Written 2026-10-09. The protected release `c066b227857f9eaf` is unchanged (directory hash `305eb75b…455c`).*

## 1. Defect fixed: LIVE-mode semantic cache

**Observed.** On the owner's Mac on 2026-10-03, Ollama was reachable, so the pipeline ran in LIVE mode. The
adjudicator appended its decisions to `data/cache/semantic_decisions/ollama-8b81c19ed450357b.jsonl`. That file is the
hash-pinned recording the release replays (config `semantic_replay`, sha256 `1aa87473…`), and it is read-only. After
4.5 minutes of model calls the run died with `PermissionError`. The workaround was `OLLAMA_URL=http://127.0.0.1:9`, which also changed the replay cache key and silently switched the run to the deterministic fallback (fixed 2026-10-09). For a release build, use `SEMANTIC_MODE=replay`.

**Why.** A live provider and the recorded provider have the same description, so the same model key and the same
cache file. Four problems follow:

| Risk | Consequence |
|---|---|
| The recording is read-only | The run crashes. |
| The recording is writable | Live output silently mixes into a verified recording. Its sha256 stops matching, every later run rejects the replay, and results change with no visible cause. |
| A model tag is re-pulled with new weights | The live description is unchanged, so old decisions are served as if current. |
| A LIVE run and a REPLAY run use the same inputs | They have the same run id. The pipeline deletes and regenerates the GOLD directory of a run id, so one mode's results replace the other's. |

**Fix.** Generic: nothing names a file or a model.

- `semantic_provider.OllamaProvider`: the probe records the model's digest from `/api/tags`. The digest is part of
  the provider description, and therefore of the cache key. An unreachable endpoint records no digest, so the
  description that replay relies on is unchanged.
- `semantic_provider.Adjudicator(pinned_files=…)`: a hash-pinned recording is never appended to, whatever the mode. A
  failed cache write is recorded in `stats.cache_write_failed` and the run continues; the decision is simply not
  cached.
- `intelligence_stage.semantic_setup`: LIVE decisions live in their own namespace,
  `data/cache/semantic_decisions/live/`. LIVE mode never reads or writes the recordings.
- `intelligence_stage.semantic_identity` is added to the run id, in `pipeline.run`:
  - it is the mode, the adjudicator's model key (provider, model, digest, prompt, schema, settings) and the replayed
    recording's sha256;
  - LIVE, REPLAY and fallback runs of the same inputs are therefore different runs;
  - the identity is also written to `run_report.json`.
- `pipeline.protected_runs()` reads `data/metadata/protected_runs.json`, which lists `c066b227857f9eaf`. The pipeline
  refuses to delete or regenerate a protected run in place (`ProtectedRunError`).

Safe Mode is unchanged. A LIVE run has no promotion gate, so its decisions are recorded and never applied.

**Tests.** `backend/tests/test_live_cache_isolation.py` has 7 tests:

- a pinned recording is never appended to;
- an unwritable cache does not fail the run (previously `PermissionError`);
- the digest changes the cache key;
- the probe records the digest, and an unreachable endpoint keeps the recorded key;
- LIVE uses its own namespace and leaves the recording byte-identical;
- the semantic identity differs by mode;
- the protected release is checked before any deletion.

**Regression against the release.** The full pipeline was re-run with the current code into a scratch GOLD root,
without changing `latest_run.json`. It ran in REPLAY_VERIFIED_RUN mode and produced run `10ee1d77afa50b0c`.
`scripts/audit/compare_runs.py` against `c066`:

- 75 files unchanged and 1 added (`recommendation_reasoning.jsonl`, from Phase 7);
- 4 changed, each explained by validated earlier work:
  - `health.json`: the Phase 2 `programme_comparison` gate, NOT_APPLICABLE;
  - `intelligence_report.json` and `recommendations.csv`: the Phase 7 reasoning block;
  - `peer_benchmark.json`: identical after removing run-derived uids and ordering.

No result changed because of Phase 10.

## 2. Measurements

| Stage | c066 (container, 2 Oct) | Current code (container, 9 Oct) | Mac, M5 (R26 run, 3 Oct) |
|---|---|---|---|
| industry.extract (posting and curriculum mentions, mapping, sense checks) | 151.7 s | 133.0 s | 30.9 s |
| peers.semantic_benchmark | 55.6 s | 48.3 s | 15.8 s |
| gold.concepts (agglomerative clustering) | 35.6 s | 33.1 s | 3.7 s |
| industry.gold | 17.2 s | 14.2 s | 4.1 s |
| industry.esco (ESCO zip parse) | 16.8 s | 13.6 s | 5.2 s |
| everything else | ~41 s | ~24 s | ~6 s |
| **Total** | **318 s** | **266 s** | **~66 s** |

The BRONZE page cache is hit for every document in all three runs, so no PDF is re-parsed. About 55% of every run is
the industry extraction plus the ESCO load. Both re-derive evidence that has not changed between runs.

## 3. Caches not added, and why

| Candidate | Saving on the Mac | Decision |
|---|---|---|
| Industry evidence: the extraction result, keyed by job-file hashes, core-topic content hash, taxonomy hashes, code fingerprint, config hash and semantic identity | ~31 s per run | **Added 2026-10-16 after the identity proof (§7).** Originally deferred: it is not release-blocking: a full Mac run takes about a minute. It touches the authoritative pipeline and needs a cold-vs-warm byte-identity proof (two full runs) before it can be trusted. |
| ESCO index, keyed by the taxonomy zip hashes and the loader's code hash | ~5 s per run | Deferred, for the same reason. |
| Semantic decisions | — | Exists. Now isolated by mode and model digest (§1). |
| BRONZE page text | — | Exists. An audit may rebuild it only from the run's own source and parser (Phase 4–6 fix). |

Neither deferred cache affects correctness. They are optimisations for after the release.

## 4. Cross-machine reproducibility (2026-10-10)

**Observation.** The Mac build and the container build of the same run (`a47ba76bfd6e24d9`) differed in 7 of 80 GOLD
files. A same-machine repeat in the container was identical, so these were platform effects:

| Cause | Fixed or bounded |
|---|---|
| Equal TF-IDF weights (family names) ordered by `argsort` | Fixed: ties broken by term |
| Equal similarities (peer top-k candidates) ordered by `argsort` | Fixed: stable sort |
| CSV written in clustering order (`concepts.csv`) | Fixed: written in key order |
| Edge-order cut (review queue related concepts) | Fixed: documented order |
| Floating-point near-ties in peer comparison: thousands of cosine similarities against a threshold, on OpenBLAS (x86) vs Apple Accelerate (arm64) | Bounded |

None of the fixes changes a threshold or an algorithm.

**Environments.**

| | Container | Mac |
|---|---|---|
| Python | 3.11 | 3.14 |
| NumPy | 2.4.4 | 2.5.3 |
| SciPy | 1.17.1 | 1.18.1 |
| scikit-learn | 1.8.0 | 1.9.1 |
| BLAS | OpenBLAS 0.3.31 | Apple Accelerate |

Each run now records its environment in `run_report.json` (`numeric_environment`).

**Pinning was considered and not adopted.**
- PyPI publishes cp314 macOS arm64 wheels for all three container versions, so a pin is installable.
- It would not give bit-identical peer outputs: the macOS 14 wheels link Accelerate, and OpenBLAS uses different kernels on
  arm64 and x86.
- The Mac keeps its validated `backend/requirements.lock`.

**Gate.** `scripts/audit/reproducibility_gate.py` with `scripts/audit/reproducibility_policy.json`.
- *Allowed:* descriptive labels, and AMBIGUOUS/RELATED peer relations and their summaries, within stated bounds.
- *Must be identical:* everything else, including every supported or SAME_CONCEPT peer relation.
- Every allowed difference is reported in `artifacts/rc/reproducibility_gate.json`.
- `rc_validation.sh` fails the release on a gate failure.

Measured on the previous Mac build, before the order fixes:
- the gate failed exactly on the three order defects listed above;
- the peer and label differences were within bounds (AMBIGUOUS ≤ 2.5% per peer, percentages ≤ 0.18 points).

## 5. Upload analysis R26: 14 minutes, and the fix (2026-10-10)

**Baseline** (historical, unchanged).

| | |
|---|---|
| Job | `job-569cfd48c93f` |
| Run | `cb63f123f77a2a5c` (parent `0534d6e1d06a617f`) |
| Machine | Mac, M5 |
| Total stage time | 851.95 s |
| `industry.extract` | 802.22 s |
| Next largest stages | `peers.semantic_benchmark` 18.18 s, `gold.concepts` 13.98 s |

**Root cause.** The time went to live model calls, not to extraction.

* **Call chain.** `pipeline.run`, stage `industry.extract` → `industry_stage.extract_and_map(sense_resolver=…)` →
  `intelligence_stage.industry_sense_resolver.resolve` → `decide_v3` → `semantic_provider.Adjudicator.decide` →
  `OllamaProvider.complete`. This is one sequential HTTP call per adjudication candidate.
* **Why the run was LIVE.** The app's upload analyses (`services/analysis_jobs._default_runner`) did not set a semantic
  mode. Because Ollama was running, the job went LIVE (`semantic_identity LIVE|e6ebab6aa0ff425a|-`).
* **The 316 candidates, from the run's own live decision cache** (`data/cache/semantic_decisions/live/ollama-e6ebab6aa0ff425a.jsonl`):

  | Outcome | Count | Time |
  |---|---|---|
  | Answered on the first attempt | 78 | **767.6 s** in total (mean 9.84 s, max 14.9 s; `qwen2.5:7b-instruct`) |
  | Failed three times with `Connection refused` (Ollama stopped mid-run) | 238 | 1.3 s in total |

  That is 792 calls: 78 successes plus 714 failed attempts.
* **None of these decisions could change a result.** A LIVE run has no promotion gate, so every decision is recorded
  with `effect = null` (Safe Mode). 96% of the stage produced advisory records only.
* **A cache defect.** The 238 transport failures were written to the live decision cache. A later live run would have
  served "the model produced no output" from the cache instead of asking again.
* **Without model calls**, the same R26 inputs take about 33 s of `industry.extract` on the Mac
  (802.22 − 767.6 − 1.3). This figure is derived from the run's own records, not measured.

**Changes.** No threshold, rule, algorithm or analytical definition is changed.

1. **Upload analyses run in replay mode** (`analysis_jobs.job_semantic_mode`, passed as
   `pipeline.run(semantic_mode=…)` to `semantic_setup(mode=…)`).
   * This is the mode release builds use. The verified recording is used; no live model is called.
   * `ANALYSIS_SEMANTIC_MODE=live` restores live advisory decisions for jobs.
   * The argument is used instead of mutating the environment, because jobs run in a server thread.
2. **Transport failures are never cached** (`semantic_provider._transient_failure`).
   * A `MODEL_FAILURE` with no model output is not written to a decision cache.
   * Such records already in a writable cache are ignored on load, so the candidate is asked again.
   * A hash-pinned recording is still served exactly as recorded.
   * Schema-invalid model output, which is a real model response, is cached as before.
3. **The sense-check label search compiles each label once** (`industry._label_pattern`, LRU cache).
   * A label whose words do not all occur in the text is skipped before any regex is built. This is a necessary
     condition for a match, so answers are identical.
   * R26 makes 25,074 searches over 2,439 distinct labels, which exceeded `re`'s 512-pattern cache.
4. **Secondary stages.**
   * `concepts.discover_concepts` groups cluster members in one pass instead of rescanning all labels per cluster.
   * `semantic_backend.top_terms` sorts only the candidates at or above the n-th weight. The result equals the full
     (−weight, term) sort.

**Measurements in the container** (2 vCPU, x86, OpenBLAS; about 4× slower than the Mac; same R26 inputs; replay mode;
BRONZE warm):

| Run | Code | Stage total | `industry.extract` |
|---|---|---|---|
| A | original | 426.0 s | 227.1 s |
| B | label search only | 336.4 s | 142.5 s |
| D | all changes | 304.4 s | 131.9 s |

* Run-to-run noise on this machine is large: the profiled run of the original code measured 121.6 s.
* Label search in isolation, on the 25,074 recorded calls (3 runs each): 7.10 s → 1.42 s median, 5.0×. All answers are
  identical.
* Model calls in replay mode: 0. All 316 candidates are replay misses: the recording has no decision for R26's
  contexts, and they are listed in `semantic_pending_candidates.jsonl`.

**Output equivalence.**

| Comparison | Result |
|---|---|
| Original code against final code, same inputs (A vs D) | 81 of 82 GOLD files identical; `peers/peer_benchmark.json` has the same content in a run-id-dependent order |
| Release manifest rebuilt with the final code against the validated release `0534d6e1d06a617f` | 79 of 80 identical; the same single order-only difference |
| The original Mac LIVE run against the container replay run | 78 of 82 identical. The differences are the semantic-decision records and their report section (78 advisory suggestions vs 316 pending candidates; 0 effects either way), and the known NITT peer concept count (platform, 354 vs 355). |

Skill mentions (10,032), normalized skills (660), ESCO-mapped skills (221), sense states, demand, gaps,
recommendations, coverage, the graph and provenance are identical.

**Expected effect on the Mac.** `industry.extract` goes from 802 s to about 33 s (derived; −96%, about 24×), and the
whole analysis from about 852 s to about 83 s (851.95 − 768.9; about 10×). A new upload analysis on the Mac gives the measured figure.

**Not changed.**
* KMeans family selection (112 fits with `n_init = 10`) dominates `gold.concepts` and the peer stage. It is the
  validated clustering, so it is unchanged.
* The industry evidence is recomputed for every upload even when the postings are unchanged. Caching it is deferred
  (§3): it needs a cold-vs-warm identity proof.

## 6. Analysis jobs: page-geometry cache and optional capabilities (2026-10-11)

**Where the time went.** This morning's upload analysis of a new institution (`job-672a201f1480`, Mac host) spent
231 s of its 277 s re-reading the five PDFs. The BRONZE text cache is keyed by the parser's code fingerprint, so every
parser change re-reads every document. In that read, pdfplumber's `find_tables` is about 90% of the time: 7.6 of
8.3 s on a 67-page syllabus, measured in the container. It depends only on the PDF and pdfplumber, not on this
project's parser.

**Changes.**
- **Page-geometry cache** (`layout_aware_extraction.document_geometry`).
  - It records each page's raw tables (bbox and cells) and words (text and box).
  - Key: the file's SHA-256, the pdfplumber version and `GEOMETRY_SCHEMA`.
  - The parser's own processing still runs on every change; only the PDF reading is reused.
  - Any other file, pdfplumber version or schema misses the cache.
  - It lives under `data/bronze/curricula/<sha16>/`, which is ignored by git and excluded from release packages.
- **Optional capabilities.** `options: {"peers": false, "industry": false}` leaves those sources out of an upload's
  analysis (§4 of `docs/ANALYSIS_JOBS_AND_EVIDENCE.md`).

**Correctness proof.** For all seven curricula of the release inputs, text extracted cold (reading the PDF and storing
its geometry) and warm (from the cache) is byte-identical to the stored BRONZE pages of the release
(`pages.6d93cd03ca5098d9.json`).

**Measurements.** All on the same machine: the Linux VM on the owner's Mac, 4 cores. The inputs are the Vasavi R26
upload plus the release's reference, peers, job postings and ESCO; replay mode.

| | Before (code on the Mac this morning) | After |
|---|---|---|
| Text extraction after a parser change, 5 PDFs | 46.1 s (7.2 + 5.5 + 4.5 + 12.9 + 16.0) | 1.9 s (geometry cache hit) |
| Full analysis, first run after a parser change | did not finish within the 175 s limit of one call | 49.6 s, ANALYSIS_READY |
| Full analysis, text cache warm | 34.7 s, NEEDS_REVIEW (the curriculum failed its checks, so most stages were skipped) | — |
| Without peer comparison | not available | 37.9 s, ANALYSIS_READY |
| Curriculum only (no peers, no industry) | not available | 3.6 s, ANALYSIS_READY |

Notes on the after runs:
- The full run's 49.6 s is now dominated by `industry.extract` (20.4 s) and `peers.semantic_benchmark` (10.5 s).
  Before, these stages did not run at all, because the curriculum was never readable.
- Building the geometry cache once costs 4.6–15.9 s per document on this machine.

**Still deferred (at the time).** The industry-evidence cache (§3, ~20 s here) was not added then. It has since been
added after a three-run identity proof (§7).

## 7. Industry-extraction cache (2026-10-16)

The rule-based part of `industry.extract` (skill mentions in postings and topics, their ESCO mapping, and the
rule-based sense checks) is now cached in `data/cache/industry_extraction/<key>.json.gz`
(`industry_stage.ExtractionCache`). The model-based sense resolver is never cached and runs on every run after the
cached part. The cache entry is written before the resolver runs, so it never holds a model decision.

**Key.** A SHA-256 over: the cache format version; the postings and curriculum topics exactly as this run read them;
the analysis code fingerprint; the configuration hash; the similarity backend actually used; the taxonomy file hashes;
the ESCO mode; and the Python, numpy, scipy and scikit-learn versions. Any other input misses.

**Safety.** A corrupt, foreign-version or mismatched entry is a miss. An unwritable cache directory costs time only
(status `MISS_NOT_STORED`); the run never fails because of the cache. Writes are atomic (temporary file, then rename).
The cache status is recorded only in observability (`stages[].cache`: `OFF`, `MISS`, `HIT`, `MISS_NOT_STORED`),
never in analytical outputs. `INDUSTRY_EXTRACTION_CACHE=off` disables it.

**Identity proof.** The full corpus analysis was run three times in the container with the same inputs: cache off,
cold (empty cache) and warm (filled by the cold run).

| | Off | Cold | Warm |
|---|---|---|---|
| run_id | 2cfadc4303cab91e | 2cfadc4303cab91e | 2cfadc4303cab91e |
| Content digest | 8daf7062…89e3f | same | same |
| `industry.extract` | 105.7 s | 96.5 s (MISS) | 4.8 s (HIT) |
| Whole run | 1366 s * | 249 s | 147 s |

\* The off run shared the machine with other work; its total is not a fair baseline. Compare stage times instead.

Of the 84 output files, 81 are byte-identical across all three runs. The other three (`observability.json`,
`run_report.json`, `run_report.md`) differ only in `generated_at`, per-stage `started_at`, `duration_s`, `rss_mb`,
`peak_python_heap_mb`, `total_duration_s` and the `cache` status of stages. These differences were checked
field by field. Off vs cold differs also in the page-geometry cache status, because the off run built that cache.

Tests: `backend/tests/test_industry_extraction_cache.py` (round trip, every key input changes the key,
corrupt or foreign entries miss, switched off, unwritable directory).

Not yet measured on the Mac. The ESCO-index cache (§3) remains deferred.

## 8. PDF pages read on several cores (2026-10-21)

pdfplumber reads one page at a time on one core. Both places that read every page now spread the pages over worker
processes in contiguous ranges and join the results in page order (`backend/app/pipelines/preprocessing/
parallel_pages.py`): the page geometry of an analysis (`layout_aware_extraction.document_geometry`, cached afterwards)
and the page text of "Upload and extract" (`pipelines/ingestion/curriculum.py`). `PDF_WORKERS` sets the number of
processes (default: CPU cores, at most 8; `PDF_WORKERS=1` is the old sequential path); documents shorter than 16 pages
stay sequential; a pool that cannot start falls back to sequential reading.

Measured in the container (2 cores), cold, sequential vs 2 workers, output compared field by field:

| PDF | Pages | Geometry | Page text | Output |
|---|---|---|---|---|
| AICTE AI & DS model curriculum | 157 | 13.2 s -> 8.0 s | 13.3 s -> 6.3 s | identical |
| CBIT B.E. CSE R22A | 246 | 45.5 s -> 28.3 s | 44.3 s -> 23.9 s | identical |

Measured on the project owner's Mac (2026-10-21), CBIT R22A page geometry, cold: **12.2 s with 1 worker, 2.9 s with
8 workers** (4.2x). Tests: `backend/tests/test_parallel_pages.py`.

## 9. Every agent: profiled and sped up, results unchanged (2026-10-22)

Measured on a copy of the project owner's data (6 curricula, 1,533 job postings, two snapshots) in the Linux
environment of the owner's Mac (4 cores, Python 3.10), cold (`INDUSTRY_EXTRACTION_CACHE=off`, `SEMANTIC_MODE=replay`),
profiled with `cProfile`. Each change was then checked by re-running and comparing every output file with
`scripts/evaluation/compare_run_outputs.py`: **81 of 81 files identical** (once run-derived ids are masked and the
order of rows sorted by them is ignored). The experimental layers' outputs (`scripts/pipeline/run_agents.py`) are
byte-identical.

| Agent / stage | Before | After | What was slow, and the change |
|---|---|---|---|
| Skill Intelligence: reading skills (`industry.extract`) | 36 s | 9 s | Each candidate term searched the whole text. It is now tried only where its first word occurs, with the word boundaries checked in Python (`skill_extraction._matches`, `_bounded`). Candidate terms are indexed by their first two words. |
| Curriculum Understanding: concepts (`gold.concepts`) | 13 s | 3.6 s | The same texts were stemmed again by every TF-IDF fit and transform; tokens and stems are cached (`concept_semantic_matching`). The reference topics outside a course family were rebuilt for each of 4,426 topics; now once per family (`mapping.map_topics`). |
| Peer benchmark (`peers.semantic_benchmark`) | 16 s | 8.6 s | Same stemming cache. |
| Job-posting validation | 1.9 s (profiled) | ~0 | Letters are counted only up to the 20 needed (`validation._alnum_count`). |
| Skill-text normalisation | 2.2 s (profiled) | ~0 | Cached (a pure function of the text). |
| **Whole analysis** | **71 s** | **41 s** | |
| Experimental layers (`run_agents.py`) | 23 s | 19 s | ESCO was loaded twice per script; now once per process, every caller getting an independent copy (`industry_stage.load_esco`). Employer-name spans are cached per posting (`skill_evidence`). |

**One behaviour fixed, not only sped up.** The indexed matcher chose candidate terms from the text's ASCII words, so a
text writing a term with one of four characters that match ASCII letters case-insensitively (KELVIN SIGN, long s, dotless
i, dotted capital I) missed it ("ıt" for "it"), unlike the original matcher. Candidates are now chosen with those read as
their letters, and such texts are searched in full. `test_performance_equivalence.py` compares the matcher with the
original on 3,000 generated texts built from awkward pieces (prefixes, apostrophes, repeated overlapping terms,
underscores, accented and Greek letters, those four characters, runs of whitespace). On the real data the results were
unchanged.

**Left as they are.** Posting segments (`segment_postings`, about 5 s): k-means for k = 2..8 with 10 starts each; faster
alternatives change the clusters. A disk cache of ESCO: loading takes 1.3 s outside the profiler, and a 47 MB cache file
for that was not worth it. The website's API: all 93 GET routes answer from the stored run files in 4 to 110 ms on first
call (`/api/v1/agents` is the slowest), so nothing needed changing there.
