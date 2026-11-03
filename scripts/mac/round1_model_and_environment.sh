#!/usr/bin/env bash
# Round 1 on the model host (Mac): decide the 30 replay-miss candidates with the real model, and prepare the
# runtime environment (Python venv with the declared dependencies, PostgreSQL 16) for the full-system validation.
# Safe to re-run: earlier model outputs are archived by the runner, never overwritten.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
OUT="$ROOT/artifacts/mac"
mkdir -p "$OUT"
log() { echo "== $*" | tee -a "$OUT/round1.log"; }

log "1/4 semantic model"
{ ollama --version; curl -s -m 5 http://127.0.0.1:11434/api/tags | python3 -c "import sys,json;print([m['name'] for m in json.load(sys.stdin)['models']])"; } 2>&1 | tee "$OUT/ollama.txt"

log "2/4 decide the 30 replay-miss candidates (new run qwen-v3-replay-misses-1)"
python3 scripts/semantic/run_frozen_adjudication.py --frozen data/semantic_runs/qwen-v3-replay-misses-1 \
  --consistency-sample 5 2>&1 | tail -25 | tee "$OUT/qwen_misses.log"

log "3/4 python environment"
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip > /dev/null 2>&1
if ! .venv/bin/pip install -q -r backend/requirements.txt > "$OUT/pip_install.log" 2>&1; then
  echo "requirements.txt failed on this Python; see pip_install.log" | tee -a "$OUT/round1.log"
fi
if ! .venv/bin/python -c "import psycopg2" 2>/dev/null; then
  .venv/bin/pip install -q "psycopg[binary]>=3.2" >> "$OUT/pip_install.log" 2>&1 && echo "PSYCOPG=3" > "$OUT/driver.txt"
else
  echo "PSYCOPG=2" > "$OUT/driver.txt"
fi
.venv/bin/python --version > "$OUT/python_version.txt" 2>&1
.venv/bin/pip freeze > "$OUT/requirements.lock.txt"
.venv/bin/python -c "import fastapi, sqlalchemy, alembic, pandas, sklearn, pdfplumber, pydantic; print('imports ok')" 2>&1 | tee -a "$OUT/round1.log"

log "4/4 PostgreSQL 16"
export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"
if ! command -v pg_ctl >/dev/null 2>&1; then
  brew install postgresql@16 > "$OUT/brew_postgres.log" 2>&1
fi
brew services start postgresql@16 >> "$OUT/brew_postgres.log" 2>&1
for i in $(seq 1 20); do pg_isready -q && break; sleep 1; done
{ pg_isready; psql --version; } 2>&1 | tee "$OUT/postgres.txt"

log "DONE round 1 -- results in $OUT and data/semantic_runs/qwen-v3-replay-misses-1/out"
