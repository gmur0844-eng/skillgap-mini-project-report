#!/usr/bin/env bash
# Runtime validation on a machine with network access (used on the project owner's Mac).
# Run from the unpacked validation bundle root. Writes everything to artifacts/.
set -u
mkdir -p artifacts
python3 -m venv .venv >/dev/null 2>&1 || true
.venv/bin/pip install -q fastapi uvicorn httpx > artifacts/pip.log 2>&1
.venv/bin/python -c "import fastapi, uvicorn, httpx; print('fastapi', fastapi.__version__, 'uvicorn', uvicorn.__version__, 'httpx', httpx.__version__)" | tee artifacts/api_versions.txt

# 1) in-process: every GET route, real ids, unknown ids
.venv/bin/python scripts/api/smoke_test_api.py --out artifacts/api_validation.json | tee artifacts/api_smoke.txt

# 2) a real server over HTTP
(cd backend && ../.venv/bin/uvicorn app.knowledge_api:app --port 8765 > ../artifacts/uvicorn.log 2>&1 &)
sleep 4
{
  echo "GET /health";                          curl -s -w "  [%{http_code} %{time_total}s]\n" localhost:8765/health
  echo "GET /api/v1/intelligence/system-health"; curl -s -o /dev/null -w "  [%{http_code} %{time_total}s]\n" localhost:8765/api/v1/intelligence/system-health
  echo "GET /api/v1/curriculum/course-drift";  curl -s -o /dev/null -w "  [%{http_code} %{time_total}s]\n" localhost:8765/api/v1/curriculum/course-drift
  echo "GET /api/v1/industry/demand";          curl -s -o /dev/null -w "  [%{http_code} %{time_total}s]\n" "localhost:8765/api/v1/industry/demand?limit=5"
  echo "GET /openapi.json";                    curl -s -o /dev/null -w "  [%{http_code} %{time_total}s]\n" localhost:8765/openapi.json
} | tee artifacts/http_check.txt
pkill -f "uvicorn app.knowledge_api" || true

# 3) Flutter static analysis, only if an SDK is installed
if command -v flutter >/dev/null 2>&1; then
  flutter --version > artifacts/flutter_version.txt 2>&1
  (cd flutter_app && flutter create . --project-name skillgap_dashboard --platforms=web,macos > ../artifacts/flutter_create.log 2>&1 \
     && flutter pub get > ../artifacts/flutter_pub_get.log 2>&1; flutter analyze > ../artifacts/flutter_analyze.txt 2>&1; echo "exit $?" >> ../artifacts/flutter_analyze.txt
     flutter test > ../artifacts/flutter_test.txt 2>&1; echo "exit $?" >> ../artifacts/flutter_test.txt
     flutter build web --release > ../artifacts/flutter_build_web.txt 2>&1; echo "exit $?" >> ../artifacts/flutter_build_web.txt)
  for f in flutter_analyze flutter_test flutter_build_web; do echo "== $f"; tail -3 artifacts/$f.txt; done
else
  echo "NO_FLUTTER_SDK" | tee artifacts/flutter_analyze.txt
fi
echo "DONE - results are in $(pwd)/artifacts"
