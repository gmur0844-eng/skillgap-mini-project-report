#!/usr/bin/env bash
# Final Flutter check on the exact release sources: analyze + widget tests, outputs kept as evidence.
set -u
cd "$(dirname "$0")/../.." || exit 1
OUT=artifacts/mac2
mkdir -p "$OUT"
cd flutter_app
sha256sum lib/main.dart test/widget_test.dart lib/screens/knowledge_screens.dart lib/screens/screen_specs.dart > "../$OUT/flutter_final_sources.sha256" 2>/dev/null || shasum -a 256 lib/main.dart test/widget_test.dart lib/screens/knowledge_screens.dart lib/screens/screen_specs.dart > "../$OUT/flutter_final_sources.sha256"
flutter analyze > "../$OUT/flutter_analyze_final.txt" 2>&1; echo "analyze exit $?" | tee -a "../$OUT/flutter_analyze_final.txt"
flutter test > "../$OUT/flutter_test_final.txt" 2>&1; echo "test exit $?" | tee -a "../$OUT/flutter_test_final.txt"
tail -2 "../$OUT/flutter_analyze_final.txt"; tail -2 "../$OUT/flutter_test_final.txt"
