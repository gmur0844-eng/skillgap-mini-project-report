#!/usr/bin/env bash
# Serve the complete system from ONE origin for the demo: the full API on :8000 and the Flutter web app at
# http://localhost:8000/app/ (same origin, so the browser needs no cross-origin access).
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"
RUN_ID="$(python3 -c "import json;print(json.load(open('data/gold/knowledge/latest_run.json'))['run_id'])")"
(cd flutter_app && flutter build web --release --base-href /app/ --dart-define=API_URL=http://localhost:8000 > "$ROOT/artifacts/mac2/flutter_build_demo.txt" 2>&1) \
  && echo "web build ok" || { echo "web build FAILED (see artifacts/mac2/flutter_build_demo.txt)"; exit 1; }
lsof -ti tcp:8000 | xargs kill 2>/dev/null; lsof -ti tcp:8080 | xargs kill 2>/dev/null; sleep 1
(cd backend && ENVIRONMENT=production DATABASE_URL="postgresql+psycopg2://localhost/skillgap_$RUN_ID" \
  CORS_ORIGINS="http://localhost:8000" WEB_DIR="$ROOT/flutter_app/build/web" \
  nohup ../.venv/bin/uvicorn app.main:app --port 8000 > "$ROOT/artifacts/mac2/uvicorn_demo.log" 2>&1 &)
for i in $(seq 1 30); do curl -s -o /dev/null localhost:8000/live && break; sleep 1; done
curl -s -o /dev/null -w "app: [%{http_code}] http://localhost:8000/app/\n" localhost:8000/app/
curl -s -w "  ready\n" localhost:8000/ready
