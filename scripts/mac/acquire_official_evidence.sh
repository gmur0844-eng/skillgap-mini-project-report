#!/usr/bin/env bash
# Evidence expansion, step 1 (run on the Mac, which can reach the official sites):
# downloads the official peer curriculum PDF(s) and a snapshot of India postings from employers' own job boards
# (public ATS APIs) into the drop folders, each file with a provenance/licence sidecar.
# Nothing is analysed and no manifest is changed here. Results: artifacts/acquisition/official_sources_report.json
#
# Run it again on later dates (e.g. weekly): each run is one more snapshot, and two or more snapshots with enough
# postings are what a genuine industry trend needs.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"; [ -x "$PY" ] || PY=python3
"$PY" scripts/acquisition/fetch_official_sources.py "$@"
echo
echo "Files:"
ls -la data/raw/curricula/incoming data/raw/jobs/incoming 2>/dev/null | grep -v "^total"
