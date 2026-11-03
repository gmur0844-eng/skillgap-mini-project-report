#!/usr/bin/env bash
# Commit and package a release that has passed scripts/mac/rc_validation.sh. Two steps, so the staged changes can be
# reviewed before anything is committed:
#
#   bash scripts/mac/finalize_release.sh stage     # git init if needed, stage the intended files, show what is staged
#   bash scripts/mac/finalize_release.sh commit    # commit the staged files, then package the release zip
#
# Refuses unless artifacts/rc/PASSED_RUN names the current run. Never resets, amends, force-pushes or deletes:
# an existing repository and its history are used as they are, and only the paths below are staged.
# What is staged is governed by .gitignore: code, tests, scripts, documentation, configuration, metadata, curated
# evaluation data and the hash-pinned semantic recordings -- never raw job files, peer PDFs, generated runs, dumps,
# logs, secrets or caches.
set -eu
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
STEP="${1:-}"
RUN="$(python3 -c "import json;print(json.load(open('data/gold/knowledge/latest_run.json'))['run_id'])")"
PASSED="$(cat artifacts/rc/PASSED_RUN 2>/dev/null || true)"
if [ "$PASSED" != "$RUN" ]; then
  echo "ERROR: run $RUN has not passed scripts/mac/rc_validation.sh (artifacts/rc/PASSED_RUN: ${PASSED:-none})"; exit 1
fi
PATHS=(README.md .gitignore .env.example backend flutter_app scripts docs data/metadata data/evaluation data/external
       data/cache)

case "$STEP" in
  stage)
    if [ ! -d .git ]; then git init -q -b main && echo "initialised a new git repository (branch main)"; fi
    existing=(); for p in "${PATHS[@]}"; do [ -e "$p" ] && existing+=("$p"); done
    git add -- "${existing[@]}"
    echo "staged for run $RUN:"; git diff --cached --stat | tail -15
    # the same checks the release zip gets: nothing personal, prohibited or secret may be staged
    bad="$(git diff --cached --name-only | grep -iE '^data/(raw|bronze|silver|gold|experiments)/|(^|/)\.env$|\.dump$|\.zip$|/\.venv/|__pycache__' || true)"
    if [ -n "$bad" ]; then echo "ERROR: prohibited files staged:"; echo "$bad" | head; exit 1; fi
    git diff --cached --name-only > artifacts/rc/staged_files.txt
    echo "$(wc -l < artifacts/rc/staged_files.txt | tr -d ' ') files staged (list: artifacts/rc/staged_files.txt)."
    echo "Review them, then run: bash scripts/mac/finalize_release.sh commit"
    ;;
  commit)
    [ -d .git ] || { echo "ERROR: run the stage step first"; exit 1; }
    git diff --cached --quiet && { echo "ERROR: nothing staged; run the stage step first"; exit 1; }
    git commit -q -m "Finalize skill-gap intelligence release (run $RUN)" \
      -m "Release candidate $RUN passed scripts/mac/rc_validation.sh: backend tests, REPLAY_VERIFIED_RUN pipeline and publish, agents, protected release c066b227857f9eaf unchanged, cross-machine reproducibility gate, database integrity, release gap QA, Flutter analyze/test/build, API and live checks. See docs/FINAL_RELEASE_REPORT.md." \
      -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" \
      -m "Claude-Session: https://claude.ai/code/session_01XTrb1YGF6RUbhJ7pqxk2ag"
    HASH="$(git rev-parse HEAD)"
    echo "commit $HASH"; echo "$HASH" > artifacts/rc/COMMIT
    git status --short | head -5; echo "(working tree status above; empty means clean apart from ignored files)"
    bash scripts/mac/package_release.sh
    ;;
  *)
    echo "usage: bash scripts/mac/finalize_release.sh stage|commit"; exit 2 ;;
esac
