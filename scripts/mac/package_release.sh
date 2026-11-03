#!/usr/bin/env bash
# Package the current release as a zip for sharing. Run after scripts/mac/rc_validation.sh has passed for this run
# (it writes artifacts/rc/PASSED_RUN); refuses otherwise.
# Excluded on purpose: peer-institution PDFs and every raw job file (not ours to redistribute, and the job
# spreadsheets carry personal details; both can be re-acquired with scripts/mac/acquire_official_evidence.sh), derived
# BRONZE/SILVER text, uploaded curricula and analysis-job state (runtime), the machine-local live semantic cache,
# GOLD runs other than the current release, its parent and the protected releases, extracted reference builds, older
# console logs and backups, virtual environments, build outputs and caches.
set -eu
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
NAME="$(basename "$ROOT")"
RUN="$(python3 -c "import json;print(json.load(open('$ROOT/data/gold/knowledge/latest_run.json'))['run_id'])")"
# keep: the current release, its lineage parent and every protected release (data/metadata/protected_runs.json)
PARENT="$(python3 -c "import json;print(json.load(open('$ROOT/data/gold/knowledge/lineage/$RUN.json'))['parent_run'])" 2>/dev/null || echo none)"
PROTECTED="$(python3 -c "import json;print('|'.join(json.load(open('$ROOT/data/metadata/protected_runs.json'))['protected_runs']))")"
KEEP="$RUN|$PARENT|$PROTECTED"
PASSED="$(cat "$ROOT/artifacts/rc/PASSED_RUN" 2>/dev/null || true)"
if [ "$PASSED" != "$RUN" ]; then
  echo "ERROR: run $RUN has not passed scripts/mac/rc_validation.sh (artifacts/rc/PASSED_RUN: ${PASSED:-none})"; exit 1
fi
OUT="$ROOT/artifacts/skillgap-release_$RUN.zip"
rm -f "$OUT"
EXCLUDE=()
for d in "$ROOT"/data/gold/knowledge/*/; do
  b="$(basename "$d")"
  if [[ "$b" =~ ^[0-9a-f]{16}$ ]] && ! [[ "$b" =~ ^($KEEP)$ ]]; then EXCLUDE+=("$NAME/data/gold/knowledge/$b/*"); fi
done
# experimental outputs only for the kept runs; machine-local provenance never
for d in "$ROOT"/data/experiments/*/*/; do
  b="$(basename "$d")"; l="$(basename "$(dirname "$d")")"
  if [[ "$b" =~ ^[0-9a-f]{16}$ ]] && ! [[ "$b" =~ ^($KEEP)$ ]]; then EXCLUDE+=("$NAME/data/experiments/$l/$b/*"); fi
done
EXCLUDE+=("$NAME/data/experiments/*/provenance.json" "$NAME/data/experiments/*/*/provenance.json")
for f in "$ROOT"/artifacts/db/*.dump; do
  [[ "$(basename "$f")" == "skillgap_knowledge_final_$RUN.dump" ]] || EXCLUDE+=("$NAME/artifacts/db/$(basename "$f")")
done
cd "$ROOT/.."
zip -qr "$OUT" "$NAME" -x "*/__pycache__/*" "*/.venv/*" "*/build/*" "*/.dart_tool/*" "*/node_modules/*" "*/.DS_Store" \
  "$NAME/data/bronze/*" "$NAME/data/silver/*" "$NAME/data/raw/jobs/*" "$NAME/data/raw/curricula/peers/*" \
  "$NAME/data/raw/curricula/uploads/*" "$NAME/data/raw/curricula/[0-9]*/*" "$NAME/data/gold/knowledge/analysis_jobs/*" \
  "$NAME/data/metadata/analysis_contexts/*" "$NAME/data/metadata/staged_uploads/*" \
  "$NAME/data/cache/semantic_decisions/live/*" "$NAME/data/cache/industry_extraction/*" "$NAME/data/cache/embeddings/*" \
  "$NAME/data/models/*" "$NAME/artifacts/rc/reference/*" "$NAME/artifacts/mac*" \
  "$NAME/artifacts/pre_improvement_backup_*" "$NAME/artifacts/sync_final/*" "$NAME/.mac_hashes_tmp.txt" \
  "$NAME/data/raw/curricula/incoming/*" "$NAME/data/gold/knowledge/_publish_staging/*" "$NAME/artifacts/*.tar.gz" \
  "$NAME/artifacts/*.zip" "$NAME/artifacts/pre_final_backup_*" "$NAME/artifacts/rc_reference*" "$NAME/artifacts/_to_delete/*" "$NAME/artifacts/zi*" "$NAME/.sync/*" "$NAME/flutter_app/ios/Pods/*" \
  "*/.env" "*/.env.local" "*/.env.production" "*/.pgpass" "*/.netrc" "*/.git/*" "*/._*" "*/.idea/*" "*/.vscode/*" \
  "${EXCLUDE[@]}"
echo "release zip: $OUT ($(du -h "$OUT" | cut -f1))"
if unzip -Z1 "$OUT" | grep -qiE "curricula/(peers|incoming|uploads)/|data/raw/jobs/"; then echo "ERROR: excluded material in zip"; exit 1; fi
echo "checked: no peer PDFs, no raw job files, no uploaded curricula"
shasum -a 256 "$OUT" | tee "$OUT.sha256"
python3 "$ROOT/scripts/audit/package_integrity.py" "$OUT" --release "$RUN" --out "$ROOT/artifacts/package_integrity_$RUN.json"
