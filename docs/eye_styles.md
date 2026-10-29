# Eye styles and colour controls

The LCD eye styles (`art <style>`, `"style"` in `/api/config`, the web
page's Style picker):

| Style | Renderer | Artwork lives in |
|---|---|---|
| `default` (hazel), `dragon` | Uncanny Eyes (`src/eye_render.h`) | app flash (`src/eye_art/*Eye.h`) |
| `cat`, `goat`, `owl`, `newt`, `terminator`, `nosclera`, `doe`, `nauga` | Uncanny Eyes | LittleFS `data/uncanny/<style>.eye`, loaded into PSRAM when picked |
| `fire` | procedural (`src/fire_eye.h`), default eye's lids | tables in internal RAM |
| `m4` | Adafruit M4_Eyes port (`docs/m4_eyes.md`) | LittleFS `data/eyes/` |

The style numbers are stored in NVS, so new styles are appended (`cat` = 4 ...
`nauga` = 11) and the old ones keep their numbers.

## Uncanny Eyes sets on LittleFS

All eight sets would need about 1.2 MB of app flash, and the app partition
was at 1.68 of 2 MB, so only `default` and `dragon` stay compiled in. The
others are files in `data/uncanny/`, flashed with `pio run -t uploadfs` (1.2
MB of the 5.9 MB LittleFS partition, beside the M4 eye sets). Picking one
reads it into PSRAM (84-138 ms, 107-212 KB) and frees the previous one; the
renderer then reads the same tables from PSRAM instead of flash. If a file is
missing the default eye is shown and the console says so.

Converted with `tools/uncanny_sets.sh <TFT_eSPI>/examples/Generic/Animated_Eyes_2/data`
(each set: `tools/uncanny_convert.py <header> <out.eye> [--no-tracking]
[--iris MIN,MAX] [--symmetrical]`). The headers are the ones `default` and
`dragon` came from: Bodmer's TFT_eSPI copy of Adafruit's Uncanny Eyes
`graphics/`, flattened, with iris ranges for this renderer. Sizes and scaling
are handled as for `default`/`dragon`: 128x128 lid maps upscaled to the 160 px
panels, the sclera window moved by the gaze. The converter writes the same
tables unchanged into one little-endian file (layout in
`src/eye_art/uncanny_file.h`).

Per-set notes:

- `owl`, `nauga`, `doe`: lid tracking off, as upstream ("DISABLE TRACKING"):
  the lids stay fully open between blinks.
- `newt`, `nosclera`: TFT_eSPI kept Adafruit's `IRIS_MIN/MAX`, which are on the
  other renderer's scale and leave almost no iris here. Rescaled
  (newt 180..750 -> 78..241, noSclera 120..550 -> 91..174).
- `goat`: the sclera is no bigger than the screen, so (as upstream) the eye
  doesn't move with the gaze; only the lids and pupil animate.
- `terminator`: its lid maps never cover the eye, so it doesn't blink (as
  upstream).
- `cat`, `owl`, `nauga`: the coloured iris is part of the sclera artwork; the
  iris map is only the pupil.

Preview on the host before flashing:

```sh
c++ -std=c++17 -O2 -Itools/host_shim -Isrc tools/eye_preview.cpp \
    src/eye_art/default_eye.cpp src/eye_art/dragon_eye.cpp -o /tmp/eye_preview
/tmp/eye_preview /tmp/eyes.ppm data/uncanny/*.eye [--tint 120,100,ffffff,0,100,ffc0c0]
```

Licence and attribution: `src/eye_art/LICENSE.md` (copied to
`data/uncanny/LICENSE.md`). MIT, Phil Burgess for Adafruit Industries.

## Colour controls

Settings (NVS, `/api/config`, `config set <key> <value>`, the web page's
"Colour" section and "Flame colour"):

| Key | Range | Applies to |
|---|---|---|
| `iris_hue`, `sclera_hue` | -180..180 degrees | Uncanny Eyes styles (default, dragon, cat ...) |
| `iris_sat`, `sclera_sat` | 0..200 % (100 = unchanged) | same |
| `iris_tint`, `sclera_tint` | `"#rrggbb"`, multiply (`#ffffff` = none) | same |
| `fire_palette` | `orange`, `red`, `blue`, `green`, `purple`, `white` | the fire eye and the flames around default/dragon |

M4 has its own tints (`m4 irisTint`, `m4 scleraTint`).

How it stays free at render time:

- Hue, saturation and tint fold into one 3x3 fixed-point colour matrix
  (CSS `hue-rotate()`/`saturate()` maths, then the multiply). When a colour
  setting or the artwork changes, the eye task runs every texel of the iris
  and sclera textures through it once, into tinted copies in PSRAM (13-58 ms,
  between two frames). This is the per-pixel RGB565 map applied ahead of time:
  the renderer reads the tinted copy exactly as it read the original, so it
  does no extra work per pixel. With neutral settings it reads the originals
  (flash for default/dragon), so nothing changes.
- The fire palette is the 256-entry heat -> RGB565 table. Other palettes are
  channel swaps/scales of the orange one, built into a 512-byte table in
  internal RAM when the setting changes; the renderers read whichever table is
  active, one pointer per row.

## Measurements

ESP32-WROVER, both panels on one 40 MHz SPI bus, WiFi joined and the web
server up; `lcd prof` over 5 s windows (fps depends on how much the lids
cover).

| Style | Before | After |
|---|---|---|
| default | 43.3-43.4 | 44.1-44.3 |
| default, iris hue 120 + sclera tint (PSRAM copies) | - | 44.6-44.7 |
| dragon | 38.0-39.3 | 38.4 (tinted 38.3-38.7) |
| fire | 26.8-27.0 | 26.6-27.1 (blue palette 26.6-27.1) |
| m4 (hazel) | 36.3-37.0 | 36.8-37.4 |
| default + flames overlay | - | 16.5-16.7 (blue palette 16.7-16.8) |
| cat, goat, owl, newt, terminator, nauga | - | 41.1-42.8 |
| doe | - | 40.3-40.4 |
| nosclera | - | 37.2-37.3 |

Internal heap free with WiFi up: 146-148 KB without m4 (before 147 KB), 90.6
KB with the m4 tables allocated (before 91.4 KB). Loading an Uncanny set or
a tinted copy uses PSRAM only (107-212 KB per set, plus up to 133 KB of tinted
copies); internal free is unchanged. The file is read 4 KB at a time so the
flash-to-PSRAM bounce buffer stays small.

App flash: 1,691,141 of 2,097,152 bytes (80.6 %; before 1,683,585). Static RAM
104.0 KB, about 1 KB more than before (the 512-byte fire palette and a
512-byte bigger `/api/config` reply buffer).
