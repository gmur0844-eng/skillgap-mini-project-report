#!/usr/bin/env bash
# Release-candidate build and validation on the Mac, on the CURRENT working tree (nothing is unpacked over it).
# The Mac is the canonical release-build platform; the container build of the same run id is the reference.
#   1 backend tests   2 knowledge pipeline (REPLAY mode, publish to a fresh build DB)   3 the agents' experimental
#   layers   4 protected release, release comparison against c066 (informational) and the cross-machine
#   reproducibility gate   5 DB dump, migration cycle, integrity   6 Flutter analyze / test / web build
#   7 full app + API validation + Flutter live check
# Every check that can fail the release is recorded; the last line is the verdict (RC VERDICT: PASS or FAIL).
# Never touches the protected release c066b227857f9eaf (the pipeline refuses to regenerate it) or an existing
# database: skillgap_rc_build_<date> and sg_rc_migration_test are created fresh; skillgap_<run_id> only if absent.
# Results: artifacts/rc/. Leaves the app running at http://localhost:8000/app/.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
OUT="$ROOT/artifacts/rc"; mkdir -p "$OUT"
export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"
# SEMANTIC_MODE=replay is set ONLY on the pipeline and agent commands (deterministic release: replay the verified
# recording even when Ollama is running). It is never exported: the backend tests decide their own semantic mode.
unset SEMANTIC_MODE
PY="$ROOT/.venv/bin/python"
FAILS=""
log() { echo "== $*" | tee -a "$OUT/validation.log"; }
check() { if [ "$2" = ok ]; then echo "  [ok]   $1" | tee -a "$OUT/validation.log"; else FAILS="$FAILS${FAILS:+; }$1"; echo "  [FAIL] $1" | tee -a "$OUT/validation.log"; fi; }
url() { echo "postgresql+psycopg2://localhost/$1"; }
stop_port() { lsof -ti tcp:"$1" | xargs kill 2>/dev/null; sleep 1; }
: > "$OUT/validation.log"
PROTECTED_BEFORE="$(cd data/gold/knowledge/c066b227857f9eaf && find . -type f | sort | xargs shasum -a 256 | shasum -a 256 | cut -c1-64)"

log "0/7 static checks of the Flutter sources (screen specs, routes, const maps)"
"$PY" scripts/frontend/static_validate_flutter.py > "$OUT/static_flutter.txt" 2>&1; R=$?; tail -3 "$OUT/static_flutter.txt" | tee -a "$OUT/validation.log"
check "static Flutter checks" "$([ $R -eq 0 ] && echo ok)"

log "1/7 backend tests"
(cd backend && env -u SEMANTIC_MODE ../.venv/bin/pytest tests -q -p no:cacheprovider -rs > "$OUT/pytest.txt" 2>&1); R=$?
grep -E "^SKIPPED" "$OUT/pytest.txt" | tee -a "$OUT/validation.log"; tail -1 "$OUT/pytest.txt" | tee -a "$OUT/validation.log"
check "backend tests: no failures or errors" "$([ $R -eq 0 ] && ! tail -1 "$OUT/pytest.txt" | grep -qE "[0-9]+ (failed|error)" && echo ok)"

log "2/7 knowledge pipeline (REPLAY mode) + publish"
BUILD_DB="skillgap_rc_build_$(date +%Y%m%d%H%M)"
createdb "$BUILD_DB"
SEMANTIC_MODE=replay "$PY" scripts/pipeline/run_knowledge_pipeline.py --publish --dsn "postgresql://localhost/$BUILD_DB" > "$OUT/pipeline.txt" 2>&1
R=$?; echo "pipeline exit $R" | tee -a "$OUT/validation.log"; grep -E "^publish:" "$OUT/pipeline.txt" | cut -c1-80 | tee -a "$OUT/validation.log"
check "pipeline exit 0" "$([ $R -eq 0 ] && echo ok)"
check "database publish PASS" "$(grep -qE "^publish: PASS" "$OUT/pipeline.txt" && echo ok)"
RUN_ID="$(python3 -c "import json;print(json.load(open('data/gold/knowledge/latest_run.json'))['run_id'])")"
MODE="$(python3 -c "import json;print(json.load(open('data/gold/knowledge/$RUN_ID/run_report.json'))['intelligence']['semantic_adjudication']['mode'])")"
REF="$ROOT/artifacts/rc_reference_$RUN_ID.tar.gz"   # the container build of the same run id (same code and inputs)
echo "run $RUN_ID; semantic mode $MODE" | tee -a "$OUT/validation.log"
"$PY" -c "import json;e=json.load(open('data/gold/knowledge/$RUN_ID/run_report.json')).get('numeric_environment') or {};print('numeric environment:', {k: e.get(k) for k in ('python','platform','numpy','scipy','sklearn')}, [b.get('internal_api') for b in e.get('blas') or [] if isinstance(b, dict)])" | tee -a "$OUT/validation.log"
check "semantic mode REPLAY_VERIFIED_RUN" "$([ "$MODE" = "REPLAY_VERIFIED_RUN" ] && echo ok)"
"$PY" scripts/acquisition/recompute.py --parent c066b227857f9eaf --new-run "$RUN_ID" > "$OUT/lineage.txt" 2>&1; R=$?; echo "lineage exit $R" | tee -a "$OUT/validation.log"
check "lineage recorded" "$([ $R -eq 0 ] && echo ok)"

log "3/7 agents: experimental layers (relevance -> skill evidence -> curriculum understanding + gap reasoning)"
SEMANTIC_MODE=replay "$PY" scripts/pipeline/run_agents.py --run "$RUN_ID" > "$OUT/agents.txt" 2>&1; R=$?; tail -4 "$OUT/agents.txt" | tee -a "$OUT/validation.log"
check "agents' experimental layers COMPLETE" "$([ $R -eq 0 ] && grep -q "^COMPLETE" "$OUT/agents.txt" && echo ok)"

log "4/7 protected release and reproducibility"
PROTECTED_AFTER="$(cd data/gold/knowledge/c066b227857f9eaf && find . -type f | sort | xargs shasum -a 256 | shasum -a 256 | cut -c1-64)"
echo "protected c066 unchanged: $([ "$PROTECTED_BEFORE" = "$PROTECTED_AFTER" ] && echo yes || echo NO) ($PROTECTED_AFTER)" | tee -a "$OUT/validation.log"
check "protected release c066 unchanged" "$([ "$PROTECTED_BEFORE" = "$PROTECTED_AFTER" ] && echo ok)"
echo "content digest: $(python3 -c "import json;print(json.load(open('data/gold/knowledge/latest_run.json'))['content_digest'])")" | tee -a "$OUT/validation.log"
# (a) RELEASE comparison: this release against the protected release c066 -- different code, so differences are
#     expected and reviewed by hand against the documented changes. Informational, not a gate.
log "4a release comparison against c066 (different code; informational, reviewed by hand)"
"$PY" scripts/audit/compare_runs.py --base data/gold/knowledge/c066b227857f9eaf --new "data/gold/knowledge/$RUN_ID" \
  --out "$OUT/compare_c066.json" > "$OUT/compare_c066.txt" 2>&1
"$PY" -c "import json;d=json.load(open('$OUT/compare_c066.json'));print('files', d['files_summary']);print('changed', d['files']['changed']);print('added', d['files']['added'])" | tee -a "$OUT/validation.log"
# (b) REPRODUCIBILITY gate: this Mac build against the container build of the SAME run id (same code and inputs).
#     Only the documented platform-sensitive fields may differ (scripts/audit/reproducibility_policy.json).
log "4b reproducibility gate: Mac build against the container reference build of the same run id"
if [ -f "$REF" ]; then
  rm -rf "$OUT/reference" && mkdir -p "$OUT/reference" && tar -xzf "$REF" -C "$OUT/reference"
  "$PY" scripts/audit/reproducibility_gate.py --reference "$OUT/reference/$RUN_ID" --candidate "data/gold/knowledge/$RUN_ID" \
    --out "$OUT/reproducibility_gate.json" > "$OUT/reproducibility_gate.txt" 2>&1; R=$?
  head -60 "$OUT/reproducibility_gate.txt" | tee -a "$OUT/validation.log"
  check "reproducibility gate PASS" "$([ $R -eq 0 ] && echo ok)"
else
  echo "no reference build for run $RUN_ID ($REF): the code or inputs differ from the container build" | tee -a "$OUT/validation.log"
  check "reproducibility gate (reference build for this run id present)" ""
fi

log "5/7 database: dump, migration cycle on an empty database, production database, integrity"
DUMP="$ROOT/artifacts/db/skillgap_knowledge_final_$RUN_ID.dump"; mkdir -p "$ROOT/artifacts/db"
pg_dump -Fc -d "$BUILD_DB" -f "$DUMP" && echo "dump ok" | tee -a "$OUT/validation.log"
check "database dump" "$([ -s "$DUMP" ] && echo ok)"
dropdb --if-exists sg_rc_migration_test; createdb sg_rc_migration_test
{
  cd backend; export DATABASE_URL="$(url sg_rc_migration_test)"
  ../.venv/bin/alembic upgrade head && ../.venv/bin/alembic current; cd ..
  pg_restore --data-only --disable-triggers --no-owner -d sg_rc_migration_test "$DUMP" && echo "restore ok"
  (cd backend && ../.venv/bin/alembic upgrade head && ../.venv/bin/alembic current); unset DATABASE_URL
} > "$OUT/migration_cycle.txt" 2>&1
"$PY" scripts/db/dbtool.py verify --db sg_rc_migration_test --report "$OUT/migration_integrity.json" > /dev/null 2>&1
MI="$(python3 -c "import json;print(json.load(open('$OUT/migration_integrity.json'))['status'])" 2>/dev/null)"
echo "migration integrity: $MI" | tee -a "$OUT/validation.log"; check "migration cycle integrity PASS" "$([ "$MI" = PASS ] && echo ok)"
dropdb --if-exists sg_rc_migration_test
DB="skillgap_$RUN_ID"
if ! psql -d postgres -tAc "select 1 from pg_database where datname='$DB'" | grep -q 1; then
  createdb "$DB"
  (cd backend && DATABASE_URL="$(url "$DB")" ../.venv/bin/alembic upgrade head) > "$OUT/db_migrate.txt" 2>&1
  pg_restore --data-only --disable-triggers --no-owner -d "$DB" "$DUMP" >> "$OUT/db_migrate.txt" 2>&1
fi
"$PY" scripts/db/dbtool.py verify --db "$DB" --report "$OUT/db_integrity.json" > /dev/null 2>&1
DI="$(python3 -c "import json;print(json.load(open('$OUT/db_integrity.json'))['status'])" 2>/dev/null)"
echo "db integrity: $DI" | tee -a "$OUT/validation.log"; check "database integrity PASS" "$([ "$DI" = PASS ] && echo ok)"
"$PY" scripts/audit/release_gap_qa.py --run "$RUN_ID" --db "$DB" > "$OUT/release_gap_qa.txt" 2>&1
HELD="$(python3 -c "import json;print(len(json.load(open('data/evaluation/release_gap_qa_$RUN_ID.json'))['gaps_held']))" 2>/dev/null)"
echo "release gap QA: held=$HELD" | tee -a "$OUT/validation.log"; check "release gap QA held=0" "$([ "$HELD" = 0 ] && echo ok)"

log "6/7 Flutter: analyze, tests, web build"
(
  cd flutter_app
  flutter pub get > "$OUT/flutter_pub_get.txt" 2>&1
  flutter analyze > "$OUT/flutter_analyze.txt" 2>&1; echo "analyze exit $?" | tee -a "$OUT/validation.log"
  flutter test > "$OUT/flutter_test.txt" 2>&1; echo "test exit $?" | tee -a "$OUT/validation.log"; tail -1 "$OUT/flutter_test.txt" | tee -a "$OUT/validation.log"
  flutter build web --release --base-href /app/ --dart-define=API_URL=http://localhost:8000 > "$OUT/flutter_build_web.txt" 2>&1
  echo "build exit $?" | tee -a "$OUT/validation.log"
)
check "flutter analyze exit 0" "$(grep -q "^analyze exit 0$" "$OUT/validation.log" && echo ok)"
check "flutter tests pass" "$(grep -q "^test exit 0$" "$OUT/validation.log" && echo ok)"
check "flutter web build exit 0" "$(grep -q "^build exit 0$" "$OUT/validation.log" && echo ok)"

log "7/7 full application: API validation and the Flutter data layer against the live API"
stop_port 8000
(cd backend && ENVIRONMENT=production DEBUG=false DATABASE_URL="$(url "$DB")" CORS_ORIGINS="http://localhost:8000" \
  WEB_DIR="$ROOT/flutter_app/build/web" nohup ../.venv/bin/uvicorn app.main:app --port 8000 > "$OUT/uvicorn.log" 2>&1 &)
for i in $(seq 1 40); do curl -s -o /dev/null localhost:8000/live && break; sleep 1; done
curl -s localhost:8000/ready > "$OUT/ready.json"; echo "ready: $(head -c 200 "$OUT/ready.json")" | tee -a "$OUT/validation.log"
check "readiness READY with data HEALTHY" "$(python3 -c "import json,sys;r=json.load(open('$OUT/ready.json'));sys.exit(0 if r.get('status')=='READY' and r['components'].get('data')=='HEALTHY' else 1)" 2>/dev/null && echo ok)"
"$PY" scripts/api/full_app_validation.py --base http://localhost:8000 --out "$OUT/full_api_validation.json" > "$OUT/full_api_validation.txt" 2>&1; R=$?
tail -5 "$OUT/full_api_validation.txt" | tee -a "$OUT/validation.log"; check "full API validation" "$([ $R -eq 0 ] && echo ok)"
(cd flutter_app && dart run tool/live_api_check.dart http://localhost:8000 > "$OUT/flutter_live_api_check.json" 2> "$OUT/flutter_live_api_check.err")
R=$?; echo "live check exit $R" | tee -a "$OUT/validation.log"; check "Flutter data layer against the live API" "$([ $R -eq 0 ] && echo ok)"
for p in /api/v1/agents /api/v1/agents/gap-review /api/v1/intelligence/recommendations /api/v1/overview; do
  curl -s -o /dev/null -w "GET $p [%{http_code} %{time_total}s]\n" "localhost:8000$p"
done | tee -a "$OUT/validation.log"
check "agents endpoints 200" "$(grep -q "GET /api/v1/agents \[200" "$OUT/validation.log" && grep -q "GET /api/v1/agents/gap-review \[200" "$OUT/validation.log" && echo ok)"
log "DONE -- results in $OUT; the app runs at http://localhost:8000/app/"
grep -E "^  \[(ok|FAIL)\]" "$OUT/validation.log"
if [ -z "$FAILS" ]; then
  echo "RC VERDICT: PASS (run $RUN_ID)" | tee -a "$OUT/validation.log"; echo "$RUN_ID" > "$OUT/PASSED_RUN"
else
  rm -f "$OUT/PASSED_RUN"; echo "RC VERDICT: FAIL (run $RUN_ID): $FAILS" | tee -a "$OUT/validation.log"; exit 1
fi
