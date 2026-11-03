#!/usr/bin/env bash
# Grow the job-posting evidence from employers' own public job boards (run on your computer; needs internet).
#   bash scripts/local/refresh_jobs.sh             # discover new boards, fetch today's snapshot, register the files
#   bash scripts/local/refresh_jobs.sh --no-discover
# 1. checks the candidate boards (data/metadata/job_board_candidates.json) and adds those with India postings
# 2. fetches a dated snapshot of every configured board into data/raw/jobs/incoming/ (with provenance sidecars)
# 3. registers the new files, so the next analysis uses them. The published analysis is never changed.
# Run it again on later dates: each snapshot is one more period, which is what a demand trend needs.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PY=.venv/bin/python; [ -x "$PY" ] || PY=python3
if [ "${1:-}" != "--no-discover" ]; then
  echo "== discovering boards"
  "$PY" scripts/acquisition/fetch_official_sources.py --discover --add-verified
fi
echo "== fetching postings"
"$PY" scripts/acquisition/fetch_official_sources.py --jobs
echo "== registering"
"$PY" scripts/acquisition/acquire_evidence.py --register
echo
echo "Done. Start a new analysis to use the new postings; the published analysis is unchanged."
