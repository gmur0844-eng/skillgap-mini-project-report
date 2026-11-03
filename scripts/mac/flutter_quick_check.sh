#!/usr/bin/env bash
# Quick Flutter check (analyze + tests) after a frontend change. Results: artifacts/mac_ux/
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$ROOT/artifacts/mac_ux"; mkdir -p "$OUT"
cd "$ROOT/flutter_app"
flutter pub get > "$OUT/pub_get.txt" 2>&1
flutter analyze > "$OUT/analyze.txt" 2>&1; echo "analyze exit $?" | tee "$OUT/summary.txt"
flutter test > "$OUT/test.txt" 2>&1; echo "test exit $?" | tee -a "$OUT/summary.txt"
tail -3 "$OUT/analyze.txt"; tail -3 "$OUT/test.txt"
