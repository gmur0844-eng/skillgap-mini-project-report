# Security Audit

The automated audit is `scripts/security/security_audit.py` (static checks; exits 1 on any failure). Its result is in `artifacts/security_audit.json`. **All 9 checks PASS.** The runtime behaviour was also verified against the live server on the Mac (see `API_VALIDATION_REPORT.md`).

| Area | Finding before | Fix / state now | Evidence |
|---|---|---|---|
| **Secrets in source** | none found | regex scan (AWS keys, private keys, `api_key=`/`token=` literals, bearer tokens, `sk-…`, GitHub tokens, URLs with passwords) → 0 findings | `secrets: PASS` |
| **.env handling** | `.env.example` only; no `.env` committed | every secret-named key in `.env.example` is empty (`JOOBLE_API_KEY=`); credentials only from the environment | `env_files: PASS` |
| **Debug mode** | no setting | `DEBUG=false` by default; production refuses `DEBUG=true` at startup | `debug: PASS`, `test_settings_validation_rejects_unsafe_production_config` |
| **Configuration** | not validated | pydantic settings validated at startup (environment, DB scheme, CORS, URLs, threshold ranges); engine config validated (ranges, relations, no literal provider keys, replay registrations complete). Invalid config fails with every problem listed. | `test_api_hardening` |
| **CORS** | knowledge app allowed `*` | explicit origins from `CORS_ORIGINS`; any `localhost` port only outside production; GET only on the knowledge app; no credentials | `cors: PASS`, `test_cors_allows_local_dev_origins_and_exposes_request_id` |
| **Error leakage** | ingestion returned `f"Ingestion failed: {exc}"`; unhandled errors = default 500 | every error is `{error, code, message, details, request_id}`; unhandled exceptions become `INTERNAL_ERROR` with no text or traceback, logged by type only; DB outages become `DATABASE_UNAVAILABLE` (503) | `error_leakage: PASS`, `test_every_error_has_the_structured_shape_and_no_stack_trace` |
| **Path traversal** | `run_id` joined to a directory path unchecked | `run_id` must match `^[0-9a-f]{16}$` before any file access (`INVALID_RUN_ID` 400) | `path_input: PASS`, `test_run_id_is_validated_before_any_file_access` |
| **File uploads** | client file name used for the temp path; size checked after full write; temp files never removed | client name reduced to `[A-Za-z0-9._-]`, never a path; streamed with a size limit (`FILE_TOO_LARGE` 413); empty file rejected (`EMPTY_FILE`); extension allow-list (`UNSUPPORTED_FILE_TYPE` 415); temp directory removed after ingestion | `uploads: PASS`, full-app tests |
| **SQL injection** | ORM in API routes; publisher SQL built from internal table names only | no f-string SQL in API/service code; the DB tool passes no user input into SQL | `sql: PASS` |
| **Shell execution** | none | no `shell=True`, `os.system`, `eval`, `exec` in application code; subprocess calls use argument lists | `shell: PASS` |
| **Logging** | unstructured | one JSON line per request (request id, method, path, status, duration, `run_id`); headers, bodies and other query parameters are never logged | `test_access_log_is_json_without_headers_or_bodies` |
| **Container** | root user | Dockerfile runs as a non-root user, applies migrations before serving, installs the lock file when present | `docker/backend.Dockerfile` |
| **Default DB password** | `skillgap:skillgap` hard-coded in compose | `${POSTGRES_PASSWORD:-skillgap}`: a local-development default only; production supplies `DATABASE_URL` | `docker/docker-compose.yml` |

## Residual risks (accepted, documented)

- **No authentication.** The API has no authentication layer; it is designed as a read-only analytics API on a trusted network. Ingestion endpoints should not be exposed publicly without an authenticating reverse proxy.
- **No rate limiting.** There is no rate limiting in the app.
- **All-rights-reserved sources.** The IIT curriculum PDFs are all-rights-reserved: analyse them, don't redistribute them.
