# Performance Report

All figures below were measured. Nothing is tuned blindly and no index was added (see "Bottlenecks").

## Pipeline (run 5e2416e1ac2aa587, Linux container, 2 CPUs, Python 3.11)

| Measure | Value |
|---|---|
| Total wall time, incl. PostgreSQL publish | ~101–106 s per run (two consecutive runs) |
| Sum of stage time | 116.4 s (CPU stage time; stages overlap little) |
| Peak RSS | ~1.06 GB |

Slowest stages:

| Stage | Time | RSS | Note |
|---|---|---|---|
| industry.extract | 48.7 s | 842 MB | skill extraction over 101,538 vocabulary terms plus sense validation |
| gold.concepts | 35.4 s | 896 MB | KMeans k = 4..24 plus agglomerative clustering |
| industry.esco | 15.4 s | 698 MB | full ESCO v1.2.1 reconstruction |
| industry.gold | 3.4 s | | |
| gold.write | 3.4 s | | |
| intelligence | 2.7 s | | |
| publish.postgres | 2.0 s | | |

## API (full application `app.main`, macOS M5, PostgreSQL 16, production settings)

Each of 65 GET routes was called 20 times through HTTP (client side) against the live server. Source: `artifacts/mac_final/full_api_validation.json`.

| Statistic | Value |
|---|---|
| Mean of route means | 3.08 ms |
| Median of route medians | 1.21 ms |
| Median p95 | 1.37 ms |
| Maximum single request | 67.9 ms |

Slowest routes, with the server-side time from the `X-Response-Time-ms` header:

| Route | Mean | Median | p95 | Max | Server median |
|---|---|---|---|---|---|
| /api/v1/semantic/relationships | 34.0 | 28.5 | 64.0 | 65.0 | 28.0 |
| /api/v1/semantic/evidence | 33.4 | 26.4 | 61.9 | 67.9 | 25.8 |
| /api/v1/curriculum/concept-mappings | 12.8 | 11.0 | 14.0 | 46.0 | 10.4 |
| /api/v1/curriculum/topics | 12.1 | 10.2 | 12.4 | 46.3 | 9.6 |

Health and database-backed routes:

| Route | Median | Note |
|---|---|---|
| /ready | 1.9 ms | includes a PostgreSQL round trip |
| /health | 2.0 ms | model probe cached for 30 s |
| /api/v1/jobs | 1.3 ms | database-backed |
| /api/v1/analytics/skill-gaps | 1.0 ms | database-backed |

The first request after start is slower (97 ms for system-health), because the GOLD run is loaded into the process cache (`knowledge_service.load_run`, LRU 4 runs).

## Database

- The integrity query runs in well under a second on 77,210 rows over 32 tables. Publishing the whole run takes 2.0 s in one transaction.
- Backup of `skillgap_5e2416e1ac2aa587`: 2.1 MB custom-format dump. Restore and compare: PASS.
- The database-backed routes are empty-population list queries on indexed primary/foreign keys. No N+1 pattern was observed, because the routes return flat lists without per-row lazy loads.

## Semantic model (Qwen 2.5 7B Instruct Q4_K_M, Ollama 0.34.4, M5 16 GB)

| Run | Calls | Mean | Median | p95 | Max | Tokens (prompt / output) |
|---|---|---|---|---|---|---|
| qwen-270-v3 | 283 | 10.6 s | 10.5 s | 15.1 s | 18.4 s | 221,152 / 32,097 |
| qwen-v3-replay-misses-1 | 29 (+1 cached) | 6.0 s | 6.0 s | 6.9 s | 7.6 s | 23,788 / 3,120 |

- **Model memory:** 4.64 GB, fully resident in unified memory (`size_vram` = size).
- **Swap in use** while the runs were active: 5.9 GB and 1.9 GB respectively. That is general system memory pressure on 16 GB and includes other apps; it is reported, not attributed to the model alone.
- **In the pipeline:** replayed decisions are cache hits, costing 0 model calls and roughly milliseconds.

## Flutter

- **Release web build:** main.dart.js is 2.6 MB. Icon tree-shaking cut the Material Icons font from 1.6 MB to 9.8 KB. Build time is about 12 s.
- **Initial page load** (localhost): index.html, then flutter_bootstrap.js and main.dart.js. Loading is dominated by main.dart.js parsing. The browser timing was not instrumented, so no load-time number is claimed.

## Bottlenecks and decisions

- **`/semantic/relationships` and `/semantic/evidence`** filter 15,689 graph edges in Python on every request (about 25–28 ms). This is acceptable at this scale. An edge index by node would lower it, but nothing needs it yet, so it was not added.
- **Pipeline wall time** is dominated by extraction and concept clustering. That is expected for a batch job, which runs about 2 minutes.
- **No database indexes were added:** every database-backed route measured ≤ 1.4 ms at the median.
