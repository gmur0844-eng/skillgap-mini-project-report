#!/usr/bin/env bash
# One-time local setup from a fresh clone (macOS or Linux). Safe to run again.
#   bash scripts/local/setup.sh            # backend + Flutter (if flutter is installed)
#   bash scripts/local/setup.sh --no-flutter
# Creates .venv, installs backend and development dependencies, fetches Flutter packages, and reports which optional
# system tools are present. It downloads no data and no model.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
WITH_FLUTTER=1; [ "${1:-}" = "--no-flutter" ] && WITH_FLUTTER=0

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null || { echo "python3 is required (3.10 or newer)"; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || { echo "Python 3.10 or newer is required"; exit 1; }

if [ ! -x .venv/bin/python ]; then
  echo "creating .venv"
  "$PY" -m venv .venv
fi
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r backend/requirements.txt -r backend/requirements-dev.txt
echo "backend dependencies: installed ($(.venv/bin/python -V))"

if [ "$WITH_FLUTTER" = 1 ]; then
  if command -v flutter >/dev/null; then
    (cd flutter_app && flutter pub get >/dev/null) && echo "flutter packages: fetched ($(flutter --version 2>/dev/null | head -1))"
  else
    echo "flutter: not installed (the web app cannot be built; the API still runs). See https://docs.flutter.dev/get-started/install"
  fi
fi

echo
echo "optional tools:"
for t in pdftotext pdfinfo psql; do
  if command -v "$t" >/dev/null; then echo "  $t: found"; else echo "  $t: missing"; fi
done
command -v pdftotext >/dev/null || echo "  -> curriculum PDFs need poppler (macOS: brew install poppler; Debian/Ubuntu: apt install poppler-utils)"
command -v psql >/dev/null || echo "  -> PostgreSQL is optional: without it the API serves analyses from the files in data/gold"
.venv/bin/python - <<'PY'
import importlib.util
print("  embedding model package:", "installed" if importlib.util.find_spec("sentence_transformers") else
      "not installed (optional: pip install -r backend/requirements-embedding.txt)")
PY
echo
echo "next: bash scripts/local/test.sh   (checks)   |   bash scripts/local/run.sh   (start the app)"
