#!/usr/bin/env bash
# Improvement release: Flutter pub get + analyze + widget tests + web build, outputs kept as evidence in
# artifacts/mac_improve/. Run from anywhere:  bash scripts/mac/improvement_flutter_check.sh
set -u
cd "$(dirname "$0")/../.." || exit 1
OUT="$PWD/artifacts/mac_improve"
mkdir -p "$OUT"
cd flutter_app || exit 1
flutter --version > "$OUT/flutter_version.txt" 2>&1
flutter pub get > "$OUT/flutter_pub_get.txt" 2>&1; echo "pub get exit $?" | tee -a "$OUT/flutter_pub_get.txt"
flutter analyze > "$OUT/flutter_analyze.txt" 2>&1; echo "analyze exit $?" | tee -a "$OUT/flutter_analyze.txt"
flutter test > "$OUT/flutter_test.txt" 2>&1; echo "test exit $?" | tee -a "$OUT/flutter_test.txt"
flutter build web --release --base-href /app/ > "$OUT/flutter_build_web.txt" 2>&1; echo "build exit $?" | tee -a "$OUT/flutter_build_web.txt"
find lib test tool -name '*.dart' -print0 | sort -z | xargs -0 shasum -a 256 > "$OUT/flutter_sources.sha256"
echo "--- summary"; tail -3 "$OUT/flutter_analyze.txt"; tail -3 "$OUT/flutter_test.txt"; tail -2 "$OUT/flutter_build_web.txt"
