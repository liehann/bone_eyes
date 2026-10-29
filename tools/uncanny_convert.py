#!/usr/bin/env python3
"""Convert an Uncanny Eyes artwork header into a LittleFS eye file.

The input is one of the `*Eye.h` tables that Bodmer's TFT_eSPI
`examples/Generic/Animated_Eyes_2/data/` ships: Phil Burgess' Adafruit
Uncanny Eyes artwork (adafruit/Uncanny_Eyes, `uncannyEyes/graphics/`),
re-laid out as flat arrays with iris ranges for that renderer. The firmware's
compiled-in `default` and `dragon` styles are those same headers, included
unchanged (src/eye_art/); this writes the identical tables to a file instead,
so the other sets cost no app flash.

  tools/uncanny_convert.py <TFT_eSPI>/examples/Generic/Animated_Eyes_2/data/catEye.h \\
      data/uncanny/cat.eye [--no-tracking] [--symmetrical]

File layout (all little-endian, read straight into PSRAM by
src/eye_art/uncanny_file.h):

  char  magic[4] = "UEYE"
  u16   version = 1, flags (bit 0: no lid tracking)
  u16   scleraW, scleraH, irisMapW, irisMapH, lidSize, irisW, irisH,
        irisMin, irisMax, reserved
  u16   sclera[scleraH * scleraW]     RGB565
  u16   iris[irisMapH * irisMapW]     RGB565
  u8    upper[lidSize * lidSize], lower[lidSize * lidSize]
  u16   polar[irisH * irisW]          angle << 7 | distance
"""
import argparse
import re
import struct
import sys


def preprocess(text, symmetrical):
    """Drop // comment lines and pick one branch of #ifdef SYMMETRICAL_EYELID."""
    out, stack = [], []  # stack of "keep this branch" flags
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#ifdef SYMMETRICAL_EYELID"):
            stack.append(symmetrical)
            continue
        if s.startswith("#else") and stack:
            stack[-1] = not stack[-1]
            continue
        if s.startswith("#endif") and stack:
            stack.pop()
            continue
        if not all(stack) or s.startswith("//"):
            continue
        out.append(line)
    return "\n".join(out)


def defines(text):
    d = {}
    for m in re.finditer(r"^\s*#define\s+(\w+)\s+(\d+)", text, re.M):
        d[m.group(1)] = int(m.group(2))
    return d


def array(text, name, count):
    m = re.search(r"const\s+uint(?:8|16)_t\s+" + name + r"\s*\[[^\]]*\]\s*PROGMEM\s*=\s*\{(.*?)\};", text, re.S)
    if not m:
        sys.exit(f"array {name} not found")
    vals = [int(v, 0) for v in re.findall(r"0[xX][0-9a-fA-F]+|\d+", m.group(1))]
    if len(vals) != count:
        sys.exit(f"array {name}: {len(vals)} values, expected {count}")
    return vals


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("header")
    ap.add_argument("out")
    ap.add_argument("--no-tracking", action="store_true", help="upper lid doesn't follow the pupil (owl, nauga, doe)")
    ap.add_argument("--symmetrical", action="store_true", help="use the SYMMETRICAL_EYELID lids where the set has them")
    ap.add_argument("--iris", metavar="MIN,MAX", help="override IRIS_MIN,IRIS_MAX (this renderer's scale)")
    a = ap.parse_args()

    text = preprocess(open(a.header).read(), a.symmetrical)
    d = defines(text)
    sw, sh = d["SCLERA_WIDTH"], d["SCLERA_HEIGHT"]
    mw, mh = d["IRIS_MAP_WIDTH"], d["IRIS_MAP_HEIGHT"]
    S = d["SCREEN_WIDTH"]
    iw, ih = d["IRIS_WIDTH"], d["IRIS_HEIGHT"]
    imin, imax = d.get("IRIS_MIN", 90), d.get("IRIS_MAX", 130)  # TFT_eSPI config.h defaults
    if a.iris:
        imin, imax = (int(v) for v in a.iris.split(","))
    if d["SCREEN_HEIGHT"] != S or S != 128:
        sys.exit("lid maps must be 128x128")
    if sw < S or sh < S:
        sys.exit("sclera smaller than the lid map")

    sclera = array(text, "sclera", sw * sh)
    iris = array(text, "iris", mw * mh)
    upper = array(text, "upper", S * S)
    lower = array(text, "lower", S * S)
    polar = array(text, "polar", iw * ih)

    with open(a.out, "wb") as f:
        f.write(b"UEYE")
        f.write(struct.pack("<2H", 1, 1 if a.no_tracking else 0))
        f.write(struct.pack("<10H", sw, sh, mw, mh, S, iw, ih, imin, imax, 0))
        f.write(struct.pack(f"<{len(sclera)}H", *sclera))
        f.write(struct.pack(f"<{len(iris)}H", *iris))
        f.write(bytes(upper))
        f.write(bytes(lower))
        f.write(struct.pack(f"<{len(polar)}H", *polar))
    print(f"{a.out}: sclera {sw}x{sh}, iris map {mw}x{mh}, polar {iw}x{ih}, iris {imin}..{imax}"
          f"{', no tracking' if a.no_tracking else ''}")


if __name__ == "__main__":
    main()
