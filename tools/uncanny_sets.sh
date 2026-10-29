#!/bin/sh
# Regenerate data/uncanny/*.eye from a TFT_eSPI checkout's Animated_Eyes_2
# artwork (Adafruit Uncanny Eyes, MIT). Then `pio run -t uploadfs`.
#
#   tools/uncanny_sets.sh <TFT_eSPI>/examples/Generic/Animated_Eyes_2/data
#
# Upstream turns lid tracking off for owl, nauga and doe (TFT_eSPI config.h:
# "DISABLE TRACKING").
set -e
src=${1:?usage: $0 <TFT_eSPI>/examples/Generic/Animated_Eyes_2/data}
here=$(dirname "$0")
out="$here/../data/uncanny"
mkdir -p "$out"
# newt and noSclera keep Adafruit's IRIS_MIN/MAX in TFT_eSPI, which are on
# the other renderer's scale (iris edge threshold t = 128 * (1023 - v) / 1024;
# here v' = 128 * IRIS_MAP_HEIGHT / t). Converted: newt 180..750 -> 78..241,
# noSclera 120..550 -> 91..174.
for set in cat goat terminator; do
  python3 "$here/uncanny_convert.py" "$src/${set}Eye.h" "$out/$set.eye"
done
python3 "$here/uncanny_convert.py" "$src/newtEye.h" "$out/newt.eye" --iris 78,241
python3 "$here/uncanny_convert.py" "$src/noScleraEye.h" "$out/nosclera.eye" --iris 91,174
for set in owl nauga doe; do
  python3 "$here/uncanny_convert.py" "$src/${set}Eye.h" "$out/$set.eye" --no-tracking
done
