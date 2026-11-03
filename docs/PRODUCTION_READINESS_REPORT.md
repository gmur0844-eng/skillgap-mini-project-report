# Production Readiness Report

> **Historical report** (run `5e2416e1ac2aa587`), kept unchanged. The current release is `c066b227857f9eaf`, baseline `84d7737ccb8e4d87`: see [FINAL_RELEASE_REPORT.md](FINAL_RELEASE_REPORT.md).

**Run:** `5e2416e1ac2aa587`. **Verdict: ready for a supervised production or demo deployment on a trusted network.** The analytics layer is complete; the data limits listed below apply and are shown in the product itself.

| Area | Status | Evidence |
|---|---|---|
| Pipeline | READY | health PASS (3 documents), 7/7 analytics gates ALLOWED, reproducible (two runs identical) |
| Database | READY | Alembic migrations (0001, 0002); `alembic check` shows no model/schema drift; integrity 0 violations; backup/restore PASS on two machines |
| API | READY | full app 92/92 live checks; structured errors; `/live` `/ready` `/health`; DB-down gives 503 and recovers; production settings validated at startup |
| Semantic model | CONNECTED, **SAFE_MODE** | Qwen 2.5 7B reachable; the promotion gate failed, so model output has no effect; the reason is shown in `/health` and in the Flutter System Health screen |
| Frontend | READY | 23 knowledge screens; analyze, tests and web build pass; 23/23 screens checked against the live API; single-origin serving under `/app/` |
| Security | PASS (9/9) with residual risks | `SECURITY_AUDIT.md`: no authentication and no rate limiting; put a reverse proxy in front of ingestion routes |
| Configuration | externalised and validated | `.env.example`; invalid configuration refuses to start |
| Observability | JSON request log with request id and timing; component health | `core/errors.py`, `core/health.py` |
| Performance | adequate | API median 1.2 ms; pipeline about 2 min; Qwen 6–11 s per decision (offline, recorded) |

## Deployment

```
cp .env.example .env                       # set ENVIRONMENT=production, DATABASE_URL, CORS_ORIGINS
cd backend && pip install -r requirements.lock && alembic upgrade head
python3 ../scripts/pipeline/run_knowledge_pipeline.py --publish --dsn "$PG_DSN"   # or restore a published dump
flutter build web --base-href /app/ --dart-define=API_URL=https://<host>     # in flutter_app/
WEB_DIR=../flutter_app/build/web uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Known limits (data or human dependent; shown as such in the product)

| Limit | Status | What lifts it |
|---|---|---|
| Industry trends | PARTIAL (1 of 2 periods) | postings from another period |
| Peer benchmarking | SOURCE_UNAVAILABLE | an official peer curriculum PDF |
| Occupation mapping | PARTIAL (22%) | O*NET, as a separate scope |
| Semantic accuracy | INTERNAL_DEVELOPMENT_EVALUATION, REVIEW_REQUIRED | independent labels |
