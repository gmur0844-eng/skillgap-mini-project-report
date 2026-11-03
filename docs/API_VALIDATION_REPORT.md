# API Validation Report

## Environment

The test was run against a real server, not a simulation:
- **Host:** MacBook Air M5, macOS 26.6.2.
- **Python stack:** Python 3.14.7, fastapi 0.141.1, uvicorn 0.54.0, SQLAlchemy 2.0.54, psycopg2 2.9.13, alembic 1.20.0. The exact environment is `backend/requirements.lock`.
- **Database:** PostgreSQL 16.15 (Homebrew), database `skillgap_5e2416e1ac2aa587`. It was built by Alembic migrations, then the published knowledge data was loaded into it.
- **App:** the **full** application `app.main` (database-backed routers plus knowledge routers), started with production settings: `ENVIRONMENT=production`, `DEBUG=false`, explicit CORS, no `create_all`.
- **Tool:** `scripts/api/full_app_validation.py`, over HTTP. Routes are enumerated from the live OpenAPI schema.

## Results: 92/92 checks PASS

| Group | Result |
|---|---|
| GET routes called with real ids | 66 routes, 0 failures (status < 500, JSON, structured shape for every error) |
| Routes skipped | 9 detail routes need an id of the legacy ingestion tables (course, job, skill…). Those tables are empty in this database, so no real id exists. They were recorded as skipped, not passed. |
| Negative cases | unknown path 404 `NOT_FOUND` · run_id `../../etc` 400 `INVALID_RUN_ID` · unknown run 404 `RUN_NOT_FOUND` · `limit=-1` 422 `VALIDATION_ERROR` · `programme_id=abc` 422 · missing `skill_key` 422 · unknown concept 404 · wrong method 405 `METHOD_NOT_ALLOWED` · JSON sent to an upload route 422 · `.exe` upload 415 `UNSUPPORTED_FILE_TYPE` · empty upload 400 `EMPTY_FILE` |
| Error shape | every error is `{error, code, message, details, request_id}`; no response contains a traceback; the server log shows 0 unhandled exceptions |
| Health | `/live` 200 · `/ready` 200 READY · `/health`: DATABASE HEALTHY (migrations current, latest run published), MODEL CONNECTED (qwen2.5:7b-instruct), SEMANTIC SAFE_MODE, DATA HEALTHY, PIPELINE READY |
| **Database down** (PostgreSQL stopped) | `/ready` 503 `DATABASE_UNAVAILABLE`; database routes 503 `DATABASE_UNAVAILABLE`; knowledge routes 200 (they read GOLD files); after restart `/ready` 200 |
| **Model unavailable** (`OLLAMA_URL` pointed at a closed port) | `/health` MODEL UNAVAILABLE, SEMANTIC SAFE_MODE, `/ready` 200: the system stays fully usable |
| Performance | 65 routes × 20 requests: median of medians 1.21 ms, maximum 67.9 ms (see `PERFORMANCE_REPORT.md`) |

Evidence files are in `artifacts/mac_final/`: `full_api_validation.json`, `failure_db_down.txt`, `failure_model_down.txt`, `ready.json`, `uvicorn_full.log`.

## Defects the runtime validation found (all fixed, each guarded by a new test)

1. **The full application could not start.** Eight modules imported `DataQualityMetric` from `app.models.analysis`; the class lives in `app.models.data_source`. Earlier validation had exercised only the standalone knowledge app. Guard: `test_every_internal_from_import_resolves`, a static check of every `from app… import` in app and scripts.
2. **Every database-backed route returned 500.** `Module.topics` declared `back_populates="module"`, but `CurriculumTopic` had no `module` relationship, and SQLAlchemy mapper configuration fails for every query. Guard: `test_every_orm_back_populates_has_its_counterpart`.
3. **Replacements for deprecated or unsafe behaviour:**
   - `on_event` startup was replaced by `lifespan`.
   - The knowledge app no longer allows `*` CORS.
   - Ingestion no longer returns raw exception text.

## In-process tests (`backend/tests/test_fastapi_app.py`, `test_api_hardening.py`)

- **Structured errors:** tested on plain Starlette everywhere, and on the real FastAPI app on the Mac.
- **Other API guarantees:** request ids, JSON access log without headers or bodies, run-id validation, health components, CORS, and the full app on an Alembic-migrated SQLite database.
- **Suite totals on the Mac:** 581 passed, 3 skipped. The skipped tests need root access to the container's local PostgreSQL, which the Mac equivalents (migration cycle, backup/restore) replace.
