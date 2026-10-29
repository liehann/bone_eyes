#!/usr/bin/env python3
"""Convert an Adafruit M4_Eyes eye folder (config.eye + BMPs, made for 240x240
panels) into bone_eyes M4 eye assets for the 160x160 GC9D01 panels.

  python3 tools/m4eye_convert.py <M4_Eyes/eyes> <name> --header src/m4eye/assets/<name>.h

Radii are scaled 160/240. Eyelid bitmaps become four 160-byte column tables
(upperOpen, upperClosed, lowerOpen, lowerClosed; y counted from the bottom,
as M4_Eyes' loadEyelid() builds them). Textures keep their resolution and
are stored big-endian RGB565 (the panel's byte order).

--lids <bmp prefix> adds a further lid set from the same folder, e.g.
"--lids symmetrical" for hazel/upper-symmetrical.bmp + lower-symmetrical.bmp.

Upstream: github.com/adafruit/Adafruit_Learning_System_Guides, M4_Eyes/
(MIT, Phillip Burgess / Adafruit). See src/m4eye/LICENSE.md.
"""
import argparse
import json
import os
import re
import sys

from PIL import Image

SRC_SIZE = 240
OUT = 160
SCALE = OUT / SRC_SIZE


def strip_comments(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    out = []
    for line in text.splitlines():
        # Drop // comments that are outside strings.
        in_str = False
        for i, ch in enumerate(line):
            if ch == '"' and (i == 0 or line[i - 1] != "\\"):
                in_str = not in_str
            if not in_str and line[i:i + 2] == "//":
                line = line[:i]
                break
        out.append(line)
    text = "\n".join(out)
    return re.sub(r",(\s*[}\]])", r"\1", text)  # trailing commas


def rgb565_be(r, g, b):
    v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    return ((v & 0xFF) << 8) | (v >> 8)


def texture(path):
    im = Image.open(path).convert("RGB")
    w, h = im.size
    px = im.load()
    return w, h, [rgb565_be(*px[x, y]) for y in range(h) for x in range(w)]


def lid_tables(path, init):
    """M4_Eyes loadEyelid(): per screen column, the vertical extent of the
    white band, y measured upward from the bottom. Columns without any band
    keep `init` (159 for the upper lid = never covers, 0 for the lower)."""
    im = Image.open(path).convert("L")
    if im.size != (SRC_SIZE, SRC_SIZE):
        sys.exit(f"{path}: expected {SRC_SIZE}x{SRC_SIZE}, got {im.size}")
    im = im.resize((OUT, OUT), Image.BOX)
    px = im.load()
    lo = [init] * OUT  # "min" array
    hi = [init] * OUT  # "max" array
    for x in range(OUT):
        ys = [y for y in range(OUT) if px[x, y] >= 128]
        if ys:
            hi[x] = OUT - 1 - min(ys)
            lo[x] = OUT - 1 - max(ys)
    return lo, hi


def lid_set(folder, upper, lower):
    # upper: loadEyelid(upper, upperClosed, upperOpen, 159)
    uc, uo = lid_tables(os.path.join(folder, upper), OUT - 1)
    # lower: loadEyelid(lower, lowerOpen, lowerClosed, 0)
    lo, lc = lid_tables(os.path.join(folder, lower), 0)
    return {"upperOpen": uo, "upperClosed": uc, "lowerOpen": lo, "lowerClosed": lc}


def colour(v, default):
    if v is None:
        return default
    if isinstance(v, list):
        return [max(0, min(255, int(c * 255.999) if isinstance(c, float) else int(c))) for c in v[:3]]
    if isinstance(v, str):
        n = int(v, 0)
        return [(n >> 11 & 31) * 255 // 31, (n >> 5 & 63) * 255 // 63, (n & 31) * 255 // 31]
    return default


def convert(eyes_dir, name, extra_lids):
    folder = os.path.join(eyes_dir, name)
    with open(os.path.join(folder, "config.eye")) as f:
        cfg = json.loads(strip_comments(f.read()))

    def scaled(key, default):
        v = cfg.get(key)
        return round(abs(v) * SCALE) if v else default

    def path(key):
        v = cfg.get(key)
        return os.path.join(eyes_dir, v) if isinstance(v, str) else None

    eyelid_index = int(cfg.get("eyelidIndex", "0x00"), 0) & 0xFF if isinstance(cfg.get("eyelidIndex"), str) \
        else int(cfg.get("eyelidIndex", 0)) & 0xFF
    lid_rgb = colour(hex((eyelid_index * 0x0101)), [0, 0, 0])
    out = {
        "name": name,
        "eyeRadius": scaled("eyeRadius", OUT // 2 + 5),
        "irisRadius": scaled("irisRadius", OUT // 4),
        "slitPupilRadius": scaled("slitPupilRadius", 0),
        "coverage": cfg.get("coverage", 0.6),
        "pupilColor": colour(cfg.get("pupilColor"), [0, 0, 0]),
        "backColor": colour(cfg.get("backColor"), [0, 0, 0]),
        "irisColor": colour(cfg.get("irisColor"), [0, 0, 0]),
        "scleraColor": colour(cfg.get("scleraColor"), [0, 0, 0]),
        "eyelidColor": lid_rgb,
        "pupilMin": cfg.get("pupilMin", 1 - (0.45 + 0.35)),
        "pupilMax": cfg.get("pupilMax", 1 - 0.45),
        "tracking": cfg.get("tracking", True),
        "squint": cfg.get("squint", 0.5),
        "irisSpin": cfg.get("irisSpin", 0.0),
        "scleraSpin": cfg.get("scleraSpin", 0.0),
        "irisMirror": bool(cfg.get("irisMirror", False)),
        "irisAngle": cfg.get("irisAngle", 0),
        "scleraAngle": cfg.get("scleraAngle", 0),
    }
    for side in ("left", "right"):
        if isinstance(cfg.get(side), dict) and cfg[side]:
            out[side] = cfg[side]
    tex = {}
    for key, tkey in (("iris", "irisTexture"), ("sclera", "scleraTexture")):
        p = path(tkey)
        if p:
            tex[key] = texture(p)
    lids = {}
    up, low = path("upperEyelid"), path("lowerEyelid")
    if up and low:
        lids[name] = lid_set(os.path.dirname(up), os.path.basename(up), os.path.basename(low))
    for suffix in extra_lids:
        lids[f"{name}-{suffix}"] = lid_set(folder, f"upper-{suffix}.bmp", f"lower-{suffix}.bmp")
    return out, tex, lids


def c_ident(s):
    return re.sub(r"\W", "_", s)


def write_header(path, cfg, tex, lids):
    ident = c_ident(cfg["name"])
    lines = [
        f"// Generated by tools/m4eye_convert.py from Adafruit M4_Eyes eyes/{cfg['name']}",
        "// (MIT, Phillip Burgess / Adafruit Industries; see src/m4eye/LICENSE.md).",
        "// Textures: big-endian RGB565. Lids: 160-entry column tables, y from the bottom.",
        "#pragma once",
        "#include <stdint.h>",
        "",
        f"namespace m4eye_asset_{ident} {{",
        "",
        "// Converted config.eye (radii scaled to the 160 px panel).",
        f"static const char kConfig[] = R\"json({json.dumps(cfg)})json\";",
        "",
    ]
    for key, (w, h, data) in tex.items():
        lines.append(f"constexpr int k{key.capitalize()}W = {w}, k{key.capitalize()}H = {h};")
        lines.append(f"static const uint16_t k{key.capitalize()}[{w * h}] = {{")
        for i in range(0, len(data), 16):
            lines.append("  " + ",".join(f"0x{v:04X}" for v in data[i:i + 16]) + ",")
        lines.append("};")
        lines.append("")
    lines.append(f"constexpr int kLidSets = {len(lids)};")
    lines.append("static const char* const kLidNames[kLidSets] = {" +
                 ", ".join(f'"{n}"' for n in lids) + "};")
    lines.append("// Per set: upperOpen, upperClosed, lowerOpen, lowerClosed.")
    lines.append("static const uint8_t kLids[kLidSets][4][160] = {")
    for n, t in lids.items():
        lines.append(f"  {{  // {n}")
        for k in ("upperOpen", "upperClosed", "lowerOpen", "lowerClosed"):
            lines.append("    {" + ",".join(str(v) for v in t[k]) + "},")
        lines.append("  },")
    lines.append("};")
    lines.append("")
    lines.append("}  // namespace")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def write_fs(outdir, cfg, tex, lids):
    """Phase 2 layout (data/eyes/<name>/): config.json, iris.565, sclera.565,
    lids.bin. A .565 file is a 4-byte header (uint16 LE width, height) then
    big-endian RGB565 pixels."""
    os.makedirs(outdir, exist_ok=True)
    c = dict(cfg)
    for key, (w, h, data) in tex.items():
        fn = f"{key}.565"
        with open(os.path.join(outdir, fn), "wb") as f:
            f.write(w.to_bytes(2, "little") + h.to_bytes(2, "little"))
            f.write(b"".join(v.to_bytes(2, "little") for v in data))  # v is already byte-swapped
        c[f"{key}Texture"] = fn
    for n, t in lids.items():
        fn = f"lids-{n}.bin" if n != cfg["name"] else "lids.bin"
        with open(os.path.join(outdir, fn), "wb") as f:
            for k in ("upperOpen", "upperClosed", "lowerOpen", "lowerClosed"):
                f.write(bytes(t[k]))
    with open(os.path.join(outdir, "config.json"), "w") as f:
        json.dump(c, f, indent=1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("eyes_dir", help="path to M4_Eyes/eyes")
    ap.add_argument("name", help="eye folder name, e.g. hazel")
    ap.add_argument("--header", help="write a C header (Phase 1, compiled in)")
    ap.add_argument("--fs", help="write a LittleFS folder, e.g. data/eyes/hazel")
    ap.add_argument("--lids", action="append", default=[], help="extra lid set suffix, e.g. symmetrical")
    a = ap.parse_args()
    cfg, tex, lids = convert(a.eyes_dir, a.name, a.lids)
    if a.header:
        write_header(a.header, cfg, tex, lids)
    if a.fs:
        write_fs(a.fs, cfg, tex, lids)
    print(json.dumps(cfg))
    for k, (w, h, _) in tex.items():
        print(f"{k}: {w}x{h} ({w * h * 2} bytes)")
    print("lids:", ", ".join(lids))


if __name__ == "__main__":
    main()
