#!/usr/bin/env bash
# Improvement release (final run c8ecd067bb733f58) on the Mac: the complete system PostgreSQL -> FastAPI (full app) ->
# API -> Flutter. Needs the earlier rounds (.venv, PostgreSQL 16, Flutter). Never touches an existing database:
#   sg_improve_migration_test (created fresh, dropped at the end), skillgap_<run_id> (created if absent).
# Results: artifacts/mac_improve/. Leaves the app running at http://localhost:8000/app/ for the walkthrough.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
OUT="$ROOT/artifacts/mac_improve"
mkdir -p "$OUT"
export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"
PY="$ROOT/.venv/bin/python"
BUNDLE="$ROOT/artifacts/improvement_run_bundle.tar.gz"
log() { echo "== $*" | tee -a "$OUT/validation.log"; }
url() { echo "postgresql+psycopg2://localhost/$1"; }
stop_port() { lsof -ti tcp:"$1" | xargs kill 2>/dev/null; sleep 1; }
: > "$OUT/validation.log"

log "0/8 unpack the new run (files it replaces are copied to artifacts/pre_improvement_backup_5e2416e1ac2aa587 first)"
B="$ROOT/artifacts/pre_improvement_backup_5e2416e1ac2aa587"
for f in data/gold/knowledge/latest_run.json data/gold/knowledge/concept_registry.json data/metadata/curriculum_sources.json; do
  [ -f "$f" ] && [ ! -f "$B/$f" ] && mkdir -p "$B/$(dirname "$f")" && cp -p "$f" "$B/$f"
done
tar -xzf "$BUNDLE" -C "$ROOT" && echo "bundle ok" | tee -a "$OUT/validation.log"
RUN_ID="$(python3 -c "import json;print(json.load(open('$ROOT/data/gold/knowledge/latest_run.json'))['run_id'])")"
DB="skillgap_$RUN_ID"
DUMP="$ROOT/artifacts/db/skillgap_knowledge_improve_$RUN_ID.dump"
echo "run $RUN_ID" | tee -a "$OUT/validation.log"

log "1/8 backend test suite with the real FastAPI / SQLAlchemy / Alembic"
(cd backend && ../.venv/bin/pytest tests -q -p no:cacheprovider > "$OUT/pytest.txt" 2>&1); tail -3 "$OUT/pytest.txt" | tee -a "$OUT/validation.log"

log "2/8 migrations 0001 -> 0003 on an empty database: upgrade -> data -> upgrade again -> integrity"
dropdb --if-exists sg_improve_migration_test; createdb sg_improve_migration_test
{
  cd backend
  export DATABASE_URL="$(url sg_improve_migration_test)"
  echo "-- upgrade 1"; ../.venv/bin/alembic upgrade head
  echo "-- current"; ../.venv/bin/alembic current
  cd ..
  echo "-- load the published knowledge data (data only) into the migrated schema"
  pg_restore --data-only --disable-triggers --no-owner -d sg_improve_migration_test "$DUMP" && echo "restore ok"
  (cd backend && echo "-- upgrade 2 (must be a no-op)" && ../.venv/bin/alembic upgrade head && ../.venv/bin/alembic current)
  unset DATABASE_URL
} > "$OUT/migration_cycle.txt" 2>&1
"$PY" scripts/db/dbtool.py verify --db sg_improve_migration_test --report "$OUT/migration_integrity.json" > /dev/null 2>&1
echo "migration integrity: $(python3 -c "import json;print(json.load(open('$OUT/migration_integrity.json'))['status'])")" | tee -a "$OUT/validation.log"
dropdb --if-exists sg_improve_migration_test

log "3/8 production database $DB"
if ! psql -d postgres -tAc "select 1 from pg_database where datname='$DB'" | grep -q 1; then
  createdb "$DB"
  (cd backend && DATABASE_URL="$(url "$DB")" ../.venv/bin/alembic upgrade head) > "$OUT/db_migrate.txt" 2>&1
  pg_restore --data-only --disable-triggers --no-owner -d "$DB" "$DUMP" >> "$OUT/db_migrate.txt" 2>&1
fi
"$PY" scripts/db/dbtool.py verify --db "$DB" --report "$OUT/db_integrity.json" > /dev/null 2>&1
echo "db integrity: $(python3 -c "import json;print(json.load(open('$OUT/db_integrity.json'))['status'])")" | tee -a "$OUT/validation.log"

log "4/8 Flutter: pub get, analyze, tests, web build served under /app/"
(
  cd flutter_app
  flutter pub get > "$OUT/flutter_pub_get.txt" 2>&1
  flutter analyze > "$OUT/flutter_analyze.txt" 2>&1; echo "analyze exit $?" | tee -a "$OUT/validation.log"
  flutter test > "$OUT/flutter_test.txt" 2>&1; echo "test exit $?" | tee -a "$OUT/validation.log"
  flutter build web --release --base-href /app/ --dart-define=API_URL=http://localhost:8000 > "$OUT/flutter_build_web.txt" 2>&1
  echo "build exit $?" | tee -a "$OUT/validation.log"
)

log "5/8 start the FULL application (production settings, web app at /app/)"
stop_port 8000
(cd backend && ENVIRONMENT=production DEBUG=false DATABASE_URL="$(url "$DB")" CORS_ORIGINS="http://localhost:8000" \
  WEB_DIR="$ROOT/flutter_app/build/web" nohup ../.venv/bin/uvicorn app.main:app --port 8000 > "$OUT/uvicorn.log" 2>&1 &)
for i in $(seq 1 40); do curl -s -o /dev/null localhost:8000/live && break; sleep 1; done
curl -s localhost:8000/ready | tee "$OUT/ready.json"; echo
curl -s -o /dev/null -w "web app: [%{http_code}] http://localhost:8000/app/\n" localhost:8000/app/ | tee -a "$OUT/validation.log"

log "6/8 full API validation (every GET route incl. the new ones, negative cases, health, performance)"
"$PY" scripts/api/full_app_validation.py --base http://localhost:8000 --out "$OUT/full_api_validation.json" | tail -5 | tee -a "$OUT/validation.log"

log "7/8 Flutter data layer against the live API (every screen spec + every redesigned screen endpoint)"
(cd flutter_app && dart run tool/live_api_check.dart http://localhost:8000 > "$OUT/flutter_live_api_check.json" 2> "$OUT/flutter_live_api_check.err")
echo "live check exit $?" | tee -a "$OUT/validation.log"

log "8/8 new endpoints over HTTP"
for p in /api/v1/overview "/api/v1/search?q=network" /api/v1/peers/status /api/v1/industry/temporal-trends \
         /api/v1/occupations/resolution /api/v1/evaluation/semantic /api/v1/lineage/recompute; do
  curl -s -o /dev/null -w "GET $p [%{http_code} %{time_total}s]\n" "localhost:8000$p"
done | tee "$OUT/http_new_endpoints.txt" | tee -a "$OUT/validation.log"
log "DONE -- results in $OUT. The app keeps running at http://localhost:8000/app/ for the walkthrough."
