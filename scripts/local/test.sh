#!/usr/bin/env bash
# Every check CI runs, locally:  bash scripts/local/test.sh [--no-flutter] [--coverage]
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PY=.venv/bin/python; [ -x "$PY" ] || { echo "run scripts/local/setup.sh first"; exit 1; }
WITH_FLUTTER=1; COV=()
for a in "$@"; do
  case "$a" in
    --no-flutter) WITH_FLUTTER=0 ;;
    --coverage) COV=(--cov=app --cov-report=term:skip-covered --cov-report=xml:../artifacts/coverage.xml) ;;
  esac
done
fail=0
step() { echo; echo "== $1"; shift; "$@" || { echo "FAILED: $*"; fail=1; }; }
if ! "$PY" -c "import ruff, pytest_cov" 2>/dev/null; then
  echo "development tools are missing from .venv: run  bash scripts/local/setup.sh  (installs ruff, pytest-cov)"; exit 1
fi
step "lint (ruff)" "$PY" -m ruff check backend scripts
mkdir -p artifacts
step "backend tests" bash -c "cd backend && ../$PY -m pytest ${COV[*]:-}"
if [ "$WITH_FLUTTER" = 1 ] && command -v flutter >/dev/null; then
  step "flutter analyze" bash -c "cd flutter_app && flutter analyze"
  step "flutter test" bash -c "cd flutter_app && flutter test"
fi
echo
[ "$fail" = 0 ] && echo "ALL CHECKS PASSED" || echo "SOME CHECKS FAILED"
exit "$fail"
