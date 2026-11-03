#!/usr/bin/env bash
# Fetch the dashboard's typefaces (Instrument Serif, IBM Plex Sans, IBM Plex Mono -- all SIL Open Font License) from
# the Google Fonts CSS2 API into flutter_app/assets/fonts/, then declare them in pubspec.yaml.
#
# pubspec.yaml is patched ONLY when every file downloaded, so a machine without network still builds: the theme
# falls back to Georgia / Helvetica Neue / Menlo (see AppFonts in lib/theme/design_system.dart).
# Idempotent: existing files are kept; the pubspec block is added once.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
APP="$ROOT/flutter_app"
DEST="$APP/assets/fonts"
mkdir -p "$DEST"

# file name | CSS2 family query
VARIANTS=(
  "InstrumentSerif-Regular.ttf|Instrument+Serif"
  "InstrumentSerif-Italic.ttf|Instrument+Serif:ital@1"
  "IBMPlexSans-Regular.ttf|IBM+Plex+Sans:wght@400"
  "IBMPlexSans-Medium.ttf|IBM+Plex+Sans:wght@500"
  "IBMPlexSans-SemiBold.ttf|IBM+Plex+Sans:wght@600"
  "IBMPlexMono-Regular.ttf|IBM+Plex+Mono:wght@400"
  "IBMPlexMono-Medium.ttf|IBM+Plex+Mono:wght@500"
)

ok=0
for v in "${VARIANTS[@]}"; do
  file="${v%%|*}"; query="${v##*|}"
  if [ -s "$DEST/$file" ]; then ok=$((ok+1)); continue; fi
  # no browser user agent -> the API answers with a single TrueType URL per face
  url=$(curl -fsS --max-time 20 -A "curl" "https://fonts.googleapis.com/css2?family=${query}" 2>/dev/null \
        | grep -Eo 'https://[^)]+\.ttf' | head -1)
  if [ -z "$url" ]; then echo "fonts: could not resolve $file"; continue; fi
  if curl -fsS --max-time 60 -o "$DEST/$file.part" "$url" && [ -s "$DEST/$file.part" ]; then
    mv "$DEST/$file.part" "$DEST/$file"; ok=$((ok+1)); echo "fonts: $file"
  else
    rm -f "$DEST/$file.part"; echo "fonts: download failed for $file"
  fi
done

if [ "$ok" -ne "${#VARIANTS[@]}" ]; then
  echo "fonts: $ok of ${#VARIANTS[@]} available; pubspec.yaml left unchanged (system fallback fonts are used)"
  exit 0
fi

if grep -q "family: InstrumentSerif" "$APP/pubspec.yaml"; then
  echo "fonts: pubspec.yaml already declares the fonts"
  exit 0
fi

cat >> "$APP/pubspec.yaml" <<'YAML'
  fonts:
    - family: InstrumentSerif
      fonts:
        - asset: assets/fonts/InstrumentSerif-Regular.ttf
        - asset: assets/fonts/InstrumentSerif-Italic.ttf
          style: italic
    - family: IBMPlexSans
      fonts:
        - asset: assets/fonts/IBMPlexSans-Regular.ttf
        - asset: assets/fonts/IBMPlexSans-Medium.ttf
          weight: 500
        - asset: assets/fonts/IBMPlexSans-SemiBold.ttf
          weight: 600
    - family: IBMPlexMono
      fonts:
        - asset: assets/fonts/IBMPlexMono-Regular.ttf
        - asset: assets/fonts/IBMPlexMono-Medium.ttf
          weight: 500
YAML
echo "fonts: declared in pubspec.yaml"
