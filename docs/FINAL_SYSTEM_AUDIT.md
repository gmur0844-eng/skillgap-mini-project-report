# Final System Audit (run 5e2416e1ac2aa587)

> **Historical report** (run `5e2416e1ac2aa587`), kept unchanged. The current release is `c066b227857f9eaf`, baseline `84d7737ccb8e4d87`: see [FINAL_RELEASE_REPORT.md](FINAL_RELEASE_REPORT.md).

| Layer | Checked | Result | Evidence / residual |
|---|---|---|---|
| **Data** | source hashes, manifest, provenance, populations kept separate | PASS | all sources SHA-verified; no Kaggle; postings are one scope (IN, 2026-09-22) with the representativeness warning on every industry response |
| **Parsing** | document health, quarantine, attribution | PASS | 3/3 PDFs PASS; 1,187 quarantined records with reasons, including the new ATTRIBUTION_CONFLICT (47 topics + 5 outcomes carried over from an unreadable header) |
| **NLP** | Unicode tokenisation, alias/acronym sense | PASS | curly-apostrophe tails removed (tests); 203 mentions held for sense review, not counted as demand |
| **Semantics** | V3 evidence separation, validator authority, gate | PASS (SAFE_MODE) | metadata never counts as evidence; validator v2.1 requires directional evidence; the gate FAILED, so 0 effects; 0 human-validated; replay 274/274 |
| **ESCO** | full v1.2.1, 13,939 skills, delta as change information only | PASS | ESCO audit screen / API |
| **Database** | migrations, constraints, integrity, backup/restore, run isolation | PASS | `alembic check` no drift; 0 integrity violations (with new graph/recommendation checks); round trip identical on two machines; run-scoped tables |
| **Graph** | self-edges, invalid types, provenance, dangling, duplicates, contradictions, cycles | PASS | all 0 on 15,689 edges; model edges admitted only with a passed gate (21 blocked) |
| **API** | full app, errors, health, failure modes, performance | PASS | 92/92; DB-down gives 503 and recovers; model-down leaves the service READY; median 1.2 ms |
| **Flutter** | analyze, tests, web build, live data layer, walkthrough | PASS | 23/23 live screen checks; responsive layout; see `FRONTEND_VALIDATION_REPORT.md` |
| **Configuration** | externalised, validated at startup | PASS | `.env.example`; production refuses DEBUG, SQLite and `*` CORS |
| **Logging** | structured, no secrets | PASS | one JSON line per request; headers and bodies are never logged |
| **Security** | 9 static checks + runtime | PASS | no auth / rate limit (documented residual risk) |
| **Reproducibility** | two full runs, cache behaviour, idempotent publish | PASS | same run id and digest, 65/65 files; second publish inserts 0 rows |
| **Generalisation** | forbidden subject-specific conditionals | PASS | 0 (8 literal hits are seed-script discipline descriptions, i.e. data) |
| **Tests** | full suite | PASS | Mac 581 passed / 3 skipped; container 580 / 1 skipped; no test removed or weakened |

## Nondeterminism reported honestly

- **Model output** is deterministic at temperature 0 in 17/20 and 5/5 re-asks. That is why decisions are recorded once and replayed, never regenerated in the pipeline.
- **Timing and memory files** are excluded from the content digest.
- **Two validated environments:** the pipeline runs on Linux / Python 3.11 and the API/UI on macOS / Python 3.14. The pipeline was not re-run on the Mac, so cross-platform pipeline byte-identity is **not claimed**.
