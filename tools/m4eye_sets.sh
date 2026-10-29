#!/bin/sh
# Regenerate the M4 eye sets in data/eyes/ (LittleFS) and the compiled-in
# fallback header from an Adafruit M4_Eyes checkout:
#
#   git clone --depth 1 --filter=blob:none --sparse \
#       https://github.com/adafruit/Adafruit_Learning_System_Guides.git als
#   git -C als sparse-checkout set M4_Eyes
#   sh tools/m4eye_sets.sh als/M4_Eyes/eyes
#
# Then `pio run -t uploadfs` (replaces the whole LittleFS image).
# demon/ is left out on purpose: its iris is a third-party DeviantArt texture
# with no stated licence (see src/m4eye/LICENSE.md). Add it locally with
#   python3 tools/m4eye_convert.py <eyes> demon --fs data/eyes/demon
set -e
EYES=${1:?usage: m4eye_sets.sh <M4_Eyes/eyes>}
cd "$(dirname "$0")/.."
python3 tools/m4eye_convert.py "$EYES" hazel --lids symmetrical --fs data/eyes/hazel \
    --header src/m4eye/assets/hazel.h
for e in snake_green doom-red doom-spiral skull; do
  python3 tools/m4eye_convert.py "$EYES" "$e" --fs "data/eyes/$e"
done
