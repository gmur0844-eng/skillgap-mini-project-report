#!/usr/bin/env bash
# Round 2 on the Mac: the complete system PostgreSQL -> FastAPI (full app) -> Qwen/safe mode -> API -> Flutter.
# Needs round 1 (.venv, PostgreSQL 16). Never touches any database other than the ones it creates:
#   sg_migration_test (created fresh, dropped at the end), skillgap_<run_id> (created if absent), *_restore_test (temp).
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
OUT="$ROOT/artifacts/mac2"
mkdir -p "$OUT"
export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"
PY="$ROOT/.venv/bin/python"
DUMP="$ROOT/artifacts/db/skillgap_knowledge_final.dump"
RUN_ID="$(python3 -c "import json;print(json.load(open('$ROOT/data/gold/knowledge/latest_run.json'))['run_id'])")"
DB="skillgap_$RUN_ID"      # one validation database per published run; never an existing database
log() { echo "== $*" | tee -a "$OUT/round2.log"; }
url() { echo "postgresql+psycopg2://localhost/$1"; }
stop_port() { lsof -ti tcp:"$1" | xargs kill 2>/dev/null; sleep 1; }

log "0/9 test suite with the real FastAPI / SQLAlchemy / Alembic"
(cd backend && ../.venv/bin/pytest tests -q -p no:cacheprovider > "$OUT/pytest.txt" 2>&1); tail -3 "$OUT/pytest.txt" | tee -a "$OUT/round2.log"

log "1/9 migrations on an empty database: upgrade -> data -> upgrade again -> integrity"
dropdb --if-exists sg_migration_test; createdb sg_migration_test
{
  cd backend
  export DATABASE_URL="$(url sg_migration_test)"
  echo "-- upgrade 1"; ../.venv/bin/alembic upgrade head
  echo "-- current"; ../.venv/bin/alembic current
  echo "-- check models vs migrated schema"; ../.venv/bin/alembic check
  cd ..
  echo "-- load the published knowledge data (data only) into the migrated schema"
  pg_restore --data-only --disable-triggers --no-owner -d sg_migration_test "$DUMP" && echo "restore ok"
  (cd backend && echo "-- upgrade 2 (must be a no-op)" && ../.venv/bin/alembic upgrade head && ../.venv/bin/alembic current)
  unset DATABASE_URL
} > "$OUT/migration_cycle.txt" 2>&1
"$PY" scripts/db/dbtool.py verify --db sg_migration_test --report "$OUT/migration_integrity.json" > /dev/null 2>&1; \
  echo "migration integrity: $(python3 -c "import json;print(json.load(open('$OUT/migration_integrity.json'))['status'])")" | tee -a "$OUT/round2.log"
dropdb --if-exists sg_migration_test

log "2/9 production database $DB (migrations + published knowledge data)"
if ! psql -d postgres -tAc "select 1 from pg_database where datname='$DB'" | grep -q 1; then
  createdb "$DB"
  (cd backend && DATABASE_URL="$(url "$DB")" ../.venv/bin/alembic upgrade head) > "$OUT/final_db_migrate.txt" 2>&1
  pg_restore --data-only --disable-triggers --no-owner -d "$DB" "$DUMP" >> "$OUT/final_db_migrate.txt" 2>&1
fi
"$PY" scripts/db/dbtool.py verify --db "$DB" --report "$OUT/final_db_integrity.json" > /dev/null 2>&1
echo "final db integrity: $(python3 -c "import json;print(json.load(open('$OUT/final_db_integrity.json'))['status'])")" | tee -a "$OUT/round2.log"

log "3/9 backup -> fresh database -> restore -> compare"
"$PY" scripts/db/dbtool.py roundtrip --db "$DB" --workdir "$OUT/db_backups" --report "$OUT/backup_restore.json" | tail -3 | tee -a "$OUT/round2.log"

log "4/9 start the FULL application (production settings)"
stop_port 8000
(cd backend && ENVIRONMENT=production DEBUG=false DATABASE_URL="$(url "$DB")" \
  CORS_ORIGINS="http://localhost:8080" nohup ../.venv/bin/uvicorn app.main:app --port 8000 > "$OUT/uvicorn_full.log" 2>&1 &)
for i in $(seq 1 30); do curl -s -o /dev/null localhost:8000/live && break; sleep 1; done
curl -s localhost:8000/ready | tee "$OUT/ready.json"; echo
if ! curl -s -o /dev/null localhost:8000/live; then echo "FULL APP DID NOT START -- see $OUT/uvicorn_full.log" | tee -a "$OUT/round2.log"; fi

log "5/9 full API validation (all routes, negative cases, health, performance)"
"$PY" scripts/api/full_app_validation.py --base http://localhost:8000 --out "$OUT/full_api_validation.json" | tee -a "$OUT/round2.log"

log "6/9 failure modes: database down, model unavailable"
brew services stop postgresql@16 > /dev/null 2>&1; sleep 3
{
  echo "-- DB down: /ready";            curl -s -w " [%{http_code}]\n" localhost:8000/ready
  echo "-- DB down: DB route";          curl -s -w " [%{http_code}]\n" localhost:8000/api/v1/data-sources
  echo "-- DB down: knowledge route";   curl -s -o /dev/null -w "[%{http_code}]\n" localhost:8000/api/v1/intelligence/gaps
} > "$OUT/failure_db_down.txt" 2>&1
brew services start postgresql@16 > /dev/null 2>&1
for i in $(seq 1 20); do pg_isready -q && break; sleep 1; done; sleep 2
echo "-- DB back: /ready" >> "$OUT/failure_db_down.txt"; curl -s -w " [%{http_code}]\n" localhost:8000/ready >> "$OUT/failure_db_down.txt"
stop_port 8001
(cd backend && ENVIRONMENT=production DATABASE_URL="$(url "$DB")" CORS_ORIGINS="http://localhost:8080" \
  OLLAMA_URL="http://127.0.0.1:9" nohup ../.venv/bin/uvicorn app.main:app --port 8001 > "$OUT/uvicorn_nomodel.log" 2>&1 &)
for i in $(seq 1 30); do curl -s -o /dev/null localhost:8001/live && break; sleep 1; done
{ echo "-- model unavailable: /health"; curl -s localhost:8001/health; echo; echo "-- /ready"; curl -s -w " [%{http_code}]\n" localhost:8001/ready; } > "$OUT/failure_model_down.txt" 2>&1
stop_port 8001
cat "$OUT/failure_db_down.txt" | tee -a "$OUT/round2.log"

log "7/9 Flutter: analyze, tests, web build (API_URL=http://localhost:8000)"
cd flutter_app
[ -d web ] || flutter create . --platforms web --project-name skillgap_dashboard > "$OUT/flutter_create.txt" 2>&1
flutter pub get > "$OUT/flutter_pub_get.txt" 2>&1
flutter analyze > "$OUT/flutter_analyze.txt" 2>&1; echo "analyze exit $?" | tee -a "$OUT/round2.log"
flutter test > "$OUT/flutter_test.txt" 2>&1; echo "test exit $?" | tee -a "$OUT/round2.log"
flutter build web --release --dart-define=API_URL=http://localhost:8000 > "$OUT/flutter_build_web.txt" 2>&1; echo "build exit $?" | tee -a "$OUT/round2.log"

log "8/9 Flutter data layer against the live API (every screen spec)"
dart run tool/live_api_check.dart http://localhost:8000 > "$OUT/flutter_live_api_check.json" 2> "$OUT/flutter_live_api_check.err"; echo "live check exit $?" | tee -a "$OUT/round2.log"
cd "$ROOT"

log "9/9 serve the Flutter web build on http://localhost:8080 (API on :8000 keeps running)"
stop_port 8080
nohup python3 -m http.server 8080 -d flutter_app/build/web > "$OUT/web_server.log" 2>&1 &
sleep 2; curl -s -o /dev/null -w "web: [%{http_code}]\n" localhost:8080/ | tee -a "$OUT/round2.log"
log "DONE round 2 -- results in $OUT. The app is running at http://localhost:8080 (leave this running for the walkthrough)."
