# Local development

The project runs on one machine; nothing is deployed. These steps work from a fresh clone on macOS or Linux.

## 1. Requirements

| Tool | Needed for | Install |
|---|---|---|
| Python 3.10 or newer | backend, pipeline, tests | python.org or `brew install python` |
| Flutter (stable) | the web app | https://docs.flutter.dev/get-started/install |
| poppler (`pdftotext`, `pdfinfo`) | reading curriculum PDFs | `brew install poppler` · `apt install poppler-utils` |
| PostgreSQL 16 | optional: database-backed routes | `brew install postgresql@16` |
| Ollama | optional: the local language model | https://ollama.com |

## 2. Set up, check, run

```
bash scripts/local/setup.sh      # .venv, backend + dev dependencies, Flutter packages; reports optional tools
bash scripts/local/test.sh       # lint, backend tests, flutter analyze + test (what CI runs)
bash scripts/local/run.sh        # builds the web app, starts the API: http://localhost:8000/app/
bash scripts/local/stop.sh       # stops it
```

Without a `DATABASE_URL` (environment or `backend/.env`), `run.sh` records uploads in a local SQLite file,
`artifacts/local/skillgap_local.db` (git-ignored); analyses are always read from `data/gold`. If the API ever cannot
reach its database, uploads answer `503 DATABASE_UNAVAILABLE` rather than "could not be ingested".

Options: `setup.sh --no-flutter`, `test.sh --no-flutter --coverage` (writes `artifacts/coverage.xml`),
`run.sh --no-build` (serve the last web build), `PORT=8010 bash scripts/local/run.sh`.

## 3. What a fresh clone contains, and what it does not

`data/raw`, `data/gold` and the other evidence folders are git-ignored. Peer-institution PDFs and job postings are not
ours to redistribute, and analysis runs are large. So a fresh clone:

* starts and serves the API and the app; screens say **"No analysis yet"** (API code `NO_ANALYSIS_YET`) until an
  analysis exists;
* passes the test suite: tests that need private evidence skip with the reason
  (`backend/tests/data_requirements.py`); on a machine with the evidence they run in full;
* analyses a curriculum you upload in the app (**New analysis**). Comparisons appear only for evidence present on the
  machine: job postings (upload a CSV in the app or place files under `data/raw/jobs/`), reference and peer curricula
  (`data/raw/curricula/`, registered in `data/metadata/curriculum_sources.json` or
  `data/metadata/discipline_references.json`), and the ESCO taxonomy (`docs/ESCO_INTEGRATION.md`).

More job postings, from employers' own public job boards (Greenhouse, Lever, Ashby, SmartRecruiters; no login):
`bash scripts/local/refresh_jobs.sh` discovers boards with India postings (`data/metadata/job_board_candidates.json`),
fetches a dated snapshot of every configured board with provenance sidecars, and registers the files for the next
analysis. Run it on different dates to build a demand trend. Official peer PDFs:
`bash scripts/mac/acquire_official_evidence.sh`.

## 4. Quality checks

| Check | Local | CI (`.github/workflows/ci.yml`) |
|---|---|---|
| Lint | `ruff check backend scripts` (rules in `ruff.toml`) | yes |
| Backend tests + coverage | `cd backend && ../.venv/bin/python -m pytest --cov=app` | Python 3.10 and 3.14 |
| Flutter | `flutter analyze && flutter test` | yes, plus a web build |

Measured 2026-10-21: a clean clone passes lint and 1,000 backend tests (34 skipped for absent private evidence) with
68 % line coverage of `backend/app`; with the evidence present, 1,031 pass in one run (3 skipped: no local
PostgreSQL).

CI runs checks only. It builds nothing for release and deploys nothing.

## 5. Optional components

* **Local embedding model:** `pip install -r backend/requirements-embedding.txt`, then
  `python scripts/semantic/fetch_embedding_model.py`; see `docs/TRANSFORMER_STRATEGY.md` §9. Never the default.
* **Local language model (Ollama):** configured in `backend/app/knowledge_engine/engine_config.json`
  (`semantic_ai.providers`); `OLLAMA_HOST` overrides the address.
