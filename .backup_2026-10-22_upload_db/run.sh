#!/usr/bin/env bash
# Start the application locally: API + web app on one port.
#   bash scripts/local/run.sh            # http://localhost:8000/app/
#   PORT=8010 bash scripts/local/run.sh
#   bash scripts/local/run.sh --no-build # serve the last web build
# Uses PostgreSQL only when DATABASE_URL is set (environment or backend/.env); otherwise the API serves analyses from
# the files in data/gold. Logs: artifacts/local/api.log.  Stop with: bash scripts/local/stop.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PORT="${PORT:-8000}"
PY=.venv/bin/python; [ -x "$PY" ] || { echo "run scripts/local/setup.sh first"; exit 1; }
mkdir -p artifacts/local

if [ "${1:-}" != "--no-build" ]; then
  if command -v flutter >/dev/null; then
    echo "building the web app..."
    (cd flutter_app && flutter build web --release --base-href /app/ --dart-define=API_URL="http://localhost:$PORT" \
      > "$ROOT/artifacts/local/flutter_build.log" 2>&1) || { echo "web build failed: artifacts/local/flutter_build.log"; exit 1; }
  else
    echo "flutter not installed: serving the API only"
  fi
fi

if lsof -ti "tcp:$PORT" >/dev/null 2>&1; then
  echo "port $PORT is in use; stop the running server first: bash scripts/local/stop.sh"; exit 1
fi
WEB=()
[ -f flutter_app/build/web/index.html ] && WEB=(WEB_DIR="$ROOT/flutter_app/build/web")
(cd backend && env ${WEB[@]+"${WEB[@]}"} CORS_ORIGINS="http://localhost:$PORT" \
  nohup "../$PY" -m uvicorn app.main:app --port "$PORT" < /dev/null > "$ROOT/artifacts/local/api.log" 2>&1 &)
for _ in $(seq 1 40); do curl -s -o /dev/null "localhost:$PORT/live" && break; sleep 0.5; done
if ! curl -s -o /dev/null "localhost:$PORT/live"; then echo "the API did not start: artifacts/local/api.log"; exit 1; fi
echo "API:  http://localhost:$PORT/docs"
[ ${#WEB[@]} -gt 0 ] && echo "App:  http://localhost:$PORT/app/"
echo "status: $(curl -s "localhost:$PORT/ready")"
if [ ! -f data/gold/knowledge/latest_run.json ]; then
  echo
  echo "No analysis yet. Open the app and use 'New analysis' to upload a curriculum, or see docs/LOCAL_DEVELOPMENT.md."
fi
