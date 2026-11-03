# Final Report: Skill-Gap & Curriculum Drift Intelligence (final hardening release)

> **Historical report** (run `5e2416e1ac2aa587`), kept unchanged. The current release is `c066b227857f9eaf`, baseline `84d7737ccb8e4d87`: see [FINAL_RELEASE_REPORT.md](FINAL_RELEASE_REPORT.md).

**Final run:**
- Run id `5e2416e1ac2aa587`, pipeline `knowledge-engine-2.0.0`, code fingerprint `13a3319b8eba1829`.
- Content digest `c23b2ec2409ad23e…`. The run was repeated and was identical (65/65 files).

**Earlier reports** are kept unchanged:
- `FINAL_REPORT_v3_release.md` (run `d658c97abebca9f5`, Semantic Engine V3 in detail);
- `FINAL_REPORT_engine_2_0.md`;
- `FINAL_REPORT_engine_1_1.md`.

No historical run or experiment was deleted or overwritten. The pre-hardening state is archived read-only in `artifacts/archive/pre-final-hardening/` (with a manifest). One run was stopped part-way because the code changed; it is kept in `artifacts/aborted_runs/cd1452009c97ca79` with a README.

**Evidence tags:**
- **[FACT]** counted from sources.
- **[MODEL]** model output.
- **[INFERENCE]** produced by a stated rule.
- **[HUMAN]** human validation. None exists.

> The job-posting results describe the supplied job-posting dataset and are not necessarily representative of the entire labour market.

## 1. What this release did

It resolved every blocker that could be resolved without new external data or independent human labels. Each blocker's classification, action, files, tests and verification is in `FINAL_BLOCKER_REPORT.md`. The system then ran end to end on the Mac:

**PostgreSQL 16 (Alembic-migrated) → full FastAPI app (production settings) → Qwen 2.5 7B (connected, SAFE_MODE) → API → Flutter web app.**

The walkthrough was done in a real browser against live data.

## 2. Results of the final run

| Area | Result |
|---|---|
| Document health | 3/3 PDFs PASS; quarantine includes ATTRIBUTION_CONFLICT (47 topics, 5 outcomes) [FACT] |
| Semantic replay | 274 hits, **0 misses**, 0 live model calls in the pipeline. The 30 earlier misses were frozen as the new run `qwen-v3-replay-misses-1`, decided by Qwen (30/30, mean 6.0 s, 5/5 consistent), merged and registered with sha256 per component |
| Semantic gate | **FAILED → SAFE_MODE**: 42 effects and 21 graph edges blocked; 0 HUMAN_VALIDATED |
| Skill gaps (v2) | 10 COVERED, 13 PARTIAL, 92 INSUFFICIENT_EVIDENCE, **0 MISSING**. MISSING is only issued for supported demand; a real defect ("lead others", "ml") was fixed |
| Recommendations | 1 supported (SQL, EXPAND_EXISTING_TOPIC in 22CSC11N, 22CSE05, 22CSE32, 22CSO02), carrying full evidence; 114 suppressed with coded reasons [INFERENCE] |
| Course drift and lineage | ADDED 15, EVOLVED 4, REMOVED 14, RETAINED 12, RETAINED_RECODED 6; lineage by topic match |
| Evidence status | TEMPORAL_TREND PARTIAL, PEER_BENCHMARK SOURCE_UNAVAILABLE, OCCUPATION_MAPPING PARTIAL (22%), INDEPENDENT_SEMANTIC_LABELS REVIEW_REQUIRED |
| Knowledge graph | 10,331 nodes, 15,689 edges, **0 violations** (self-edges, invalid types, missing provenance, dangling, duplicates, contradictions, cycles) |
| Publish | one transaction; 0 integrity violations; a second publish inserts 0 rows |

## 3. Final acceptance matrix

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | 30 replay misses resolved without bypassing safety | **PASS** | 0 misses; new run recorded separately; SAFE_MODE unchanged |
| 2 | Full FastAPI app runtime-validated | **PASS** | 92/92 checks, 66 routes, 0 unhandled exceptions (`API_VALIDATION_REPORT.md`) |
| 3 | Structured API errors | **PASS** | `{error, code, message, details, request_id}`; 12 negative cases; no tracebacks |
| 4 | Health / readiness / liveness | **PASS** | `/live`, `/ready`, `/health` with components; DB down gives 503 and recovers; model down leaves the service READY |
| 5 | Dependency reproducibility | **PASS** | `requirements.lock`; fresh venv; 581 tests pass on the Mac |
| 6 | DB migrations | **PASS** | Alembic 0001 + 0002; `alembic check` no drift; upgrade is idempotent |
| 7 | Backup / restore | **PASS** | container 67,766 rows; Mac 77,210 rows over 32 tables, identical |
| 8 | Config validation | **PASS** | invalid settings or engine config refuse to start |
| 9 | Secret / security audit | **PASS** (residual risk documented) | 9/9 checks; no authentication or rate limiting (`SECURITY_AUDIT.md`) |
| 10 | CORS / input / file safety | **PASS** | explicit origins, run-id regex, 415/400/413 on uploads |
| 11 | Semantic failure / safe mode | **PASS** | 7 failure-mode tests; SAFE_MODE shown in `/health` and in Flutter |
| 12 | Evidence validation | **PASS** | validator v2.1 (NO_DIRECTIONAL_EVIDENCE); 0 metadata-only support |
| 13 | Graph integrity | **PASS** | 0 violations, including after restore |
| 14 | Recommendation safety | **PASS** | full evidence per recommendation; DB below-threshold check = 0 |
| 15 | API performance | **PASS** | median 1.21 ms, max 67.9 ms (`PERFORMANCE_REPORT.md`) |
| 16 | Flutter live integration | **PASS** | live check 23/23 screens |
| 17 | Flutter states | **PASS** | loading, error, DATA NOT AVAILABLE, empty, partial, badges; widget tests |
| 18 | Flutter manual / demo path | **PASS** | browser walkthrough, 11 screens checked against the API (`FRONTEND_VALIDATION_REPORT.md`) |
| 19 | End to end PostgreSQL → FastAPI → Flutter | **PASS** | round-2 script plus single-origin demo at `/app/` |
| 20 | Full regression | **PASS** | container 580 passed / 1 skipped; Mac 581 passed / 3 skipped; no test removed or weakened |
| 21 | Reproducibility | **PASS** | two runs identical (run id, digest, 65/65 files) |
| 22 | Final documentation | **PASS** | the 12 required reports plus the blocker, readiness and audit reports |
| 23 | Demo guide | **PASS** | `DEMO_GUIDE.md`, real values only |
| — | Generalisation (no subject-specific logic) | **PASS** | 0 forbidden conditionals |
| — | Dataset discovery (research only, nothing ingested) | **PASS** | `DATASET_DISCOVERY_REPORT.md` |
| — | Multi-period trends | **NOT AVAILABLE (C)** | needs postings from a second period; shown as PARTIAL |
| — | Peer benchmarking | **NOT AVAILABLE (C)** | needs an official peer curriculum; shown as SOURCE_UNAVAILABLE |
| — | Independent semantic accuracy | **REVIEW REQUIRED (D)** | labelling sheet exported; 0 independent labels |
| — | Model promotion | **BLOCKED FOR SAFETY (E)** | gate FAILED → SAFE_MODE; not bypassed |

Every A and B blocker **passes**. The C, D and E items are not failures of the software. They are correctly reported states that the data or a human reviewer must lift, and the product shows each one with its reason and next action.

## 4. What is honestly not claimed

- **Semantic precision is not independently measured.** The benchmark is INTERNAL_DEVELOPMENT_EVALUATION; model output is never HUMAN_VALIDATED.
- **The job-posting population is one scope:** 100 postings, IN, 2026-09-22. Trends are therefore INSUFFICIENT_EVIDENCE.
- **Cross-platform pipeline byte-identity is not claimed.** The pipeline was validated on Linux / Python 3.11 and the API/UI on macOS / Python 3.14.
- **The app has no authentication layer.** Deploy it on a trusted network or behind a proxy.

## 5. Next steps that would lift the remaining limits

1. **An independent reviewer** labels `data/evaluation/semantic_benchmark_v1/independent_labels/labelling_sheet.csv` (`benchmark_labelling.py ingest`, then `compare`).
2. **Postings from a second period** go in the drop folder with a `.source.json` licence sidecar. TEMPORAL_TREND becomes AVAILABLE.
3. **An official peer curriculum PDF** with provenance goes in the manifest. PEER_BENCHMARK becomes AVAILABLE.
4. **The O*NET release** is placed as a separate scope to raise occupation mapping above 22%.
5. **A new model or prompt** is evaluated on a new frozen benchmark (v2) with independent labels. The gate is never re-run on v1.
