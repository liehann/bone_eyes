# M4 eye (Adafruit M4_Eyes port)

Style `m4` draws the eyes with a port of Adafruit's M4_Eyes renderer (Monster
M4sk / Hallowing M4, Phil Burgess, MIT) on the two 160x160 GC9D01 panels.
Eye sets (textures, eyelid shapes, config) are data on LittleFS, and the
parameters can be changed at runtime from the console, the web page or
`/api/config`, and saved in NVS.

```
art m4                      # or "style":"m4" in /api/config
m4 eye snake_green          # switch eye set (resets to its config.json)
m4 irisTint #ff8080         # one parameter
m4 set {"slitPupilRadius":40,"pupilMax":0.4}
m4 reset                    # back to the eye set's own values
config save                 # keep it (style + the m4 object) across reboots
```

## Design

```
eyes.cpp (animator: gaze, lid, pupil, mood, blinks)
   |
eyes_lcd.cpp  LcdEyes::draw()             style settings::kM4 -> effect 3
   prepare()   ── m4eye::beginFrame()      core 1, between frames: apply
   |                                         pending config, (re)load eye set,
   |                                         rebuild tables / re-tint
   simulate(e) ── m4eye::simulate(e, st)   per eye (L on core 1, R on core 0)
   renderRow() ── m4eye::renderRow(e, y)   per row, both cores, 8-row chunks,
                                             DMA'd while the next chunk renders
```

- `src/m4eye/m4eye_render.h`: the engine, hardware-independent (also built
  by `tools/m4eye_preview.cpp` on the host). Same maths as `M4_Eyes.ino` /
  `tablegen.cpp`:
  - an 80x80 quarter displacement map fakes the ball's curvature;
  - a quarter polar map (`mapRadius` = eyeRadius * pi * coverage = 156 for
    hazel) gives angle and signed distance; distance >= 0 is sclera, < 0 is
    iris; the slit pupil re-solves the iris part of the distance map;
  - texture lookup is `angle * w >> 10`, `dist * h >> 7` (sclera) and
    `-dist * iPupilFactor >> 15` (iris; past the texture's height is the
    pupil);
  - eyelids are per-column open/closed extents from the 1-bit lid bitmaps,
    interpolated per frame (upper lid tracks the pupil, M4 "tracking").
- Changes from upstream: row-major (top to bottom) instead of column-major;
  output is big-endian RGB565 straight into the DMA buffer (no swap pass);
  per-column lid spans computed once per frame; pixels outside the round
  panel's visible circle are skipped (about 21% of the square).
- Integer-only per pixel; float only in the per-frame `compute()` and the
  table build.
- `m4eye.cpp`: eye sets, memory placement, pending-config handoff, the `m4`
  console command. Config writers (console, HTTP task) only touch `pending`
  under a spinlock; the eye task applies it in `beginFrame()` when no row
  renderer is running.
- `m4eye_config.{h,cpp}`: the parameter struct and its JSON (own small
  parser, no library; accepts `//` comments and M4_Eyes `config.eye` keys,
  including the nested `left`/`right` objects).
- `m4eye_fs.{h,cpp}`: LittleFS eye sets (mounts LittleFS on first use).

### Mapping onto bone_eyes' animator

- Gaze -1..1 is clamped to the unit circle and scaled by `gazeRange` times the
  travel that keeps the polar map on screen (M4's `mapDiameter - 160 * pi/2`).
- `EyeState.lid` (0 closed, 0.75 normal, 1 wide) scales both lid factors;
  above 0.75 the lids are pulled out of tracking. The animator's blinks
  therefore close the M4 lids too.
- `EyeState.pupil` 0..1 maps onto `pupilMin..pupilMax` (fraction of the iris).
- M4_Eyes lid art is drawn for the monster's right eye (tear duct to the
  viewer's right). The L eye (viewer's right) gets it mirrored; `lidMirror`
  swaps that.
- Not ported: light sensor, boop sensor, voice changer, per-frame integer
  spin (`irisiSpin`), the autonomous fractal pupil (the animator drives the
  pupil), and per-eye textures (`left`/`right` `irisTexture`). `irisSpin`
  and `irisMirror` do work per eye.

## Measurements

ESP32-WROVER (240 MHz, 2 cores), both panels on one SPI bus at 40 MHz,
firmware with WiFi joined and the web server running. `lcd prof` over 1 s
and 5 s windows (fps varies with how much of the eye the lids cover);
`m4 bench 30` renders both eyes on one core with no SPI.

Reference: style `fire` 26.0-27.8 fps, `default` (Uncanny Eyes) 36-42 fps.
Internal heap free at boot (no eye buffers yet): 150-152 KB.

| Tables | Textures | fps, both eyes | Bench, one core | Internal free |
|---|---|---|---|---|
| internal (55 KB) | PSRAM (tinted copy) | **35.7-38.0** | 22.0 ms / frame | 91-96 KB |
| PSRAM | PSRAM | 27.6-35.0 | 28.3-29.1 ms | 146-151 KB |
| internal | flash / source (untinted) | 31.3-38.5 | 22.3 ms | 91-96 KB |
| PSRAM | flash / source | 27.5-36.5 | 24.0-29.0 ms | 146-151 KB |

The default is the first row. Table placement matters most (the polar lookups
jump about); the texture location matters little. Moving the tables to PSRAM
(`m4 mem tables psram`) buys back 55 KB of internal RAM for about 15-20% of
the frame rate.

Per eye set (tables internal, textures PSRAM):

| Eye set | fps | Load from LittleFS | Table build |
|---|---|---|---|
| hazel | 36.3-37.4 | 241 ms | 63 ms |
| snake_green (slit pupil) | 37.3-41.1 | 124 ms | 238 ms |
| doom-red | 39.2-40.6 | 131 ms | 63 ms |
| doom-spiral (spinning) | 35.9-36.2 | 105 ms | 62 ms |
| skull (no lids) | 26.9-28.4 | 240 ms | 59 ms |
| hazel + tint, symmetrical lids, irisRadius 50, 20 blinks/min | 35.6-36.4 | - | 63 ms |

Memory with `m4` running: internal free 89-93 KB (largest block 45 KB) with
WiFi/HTTP up, against the 60 KB target. PSRAM: about 0.3-0.6 MB per eye set
(the loaded textures plus a tinted copy). Static RAM for the whole firmware:
102.8 KB. App flash: 1.68 MB of 2 MB, of which the built-in hazel fallback is
about 300 KB. LittleFS: five eye sets, about 1 MB of the 5.9 MB partition (no
partition change needed).

## Parameters

The `m4` object of `/api/config` (and `m4` / `config` on the console). A
partial object is a patch; unknown keys are ignored. `"eye"` switches the eye
set and first resets everything else to that set's `config.json`;
`"reset": true` does the same for the current set.

| Key | Type | What |
|---|---|---|
| `eye` | string | eye set (`m4 list`; `m4_sets.eyes` in `GET /api/config`) |
| `lids` | string | eyelid shape: `""` the eye's own, `"none"`, or a lid set name (`m4_sets.lids`) |
| `irisTint`, `scleraTint` | [r,g,b] or `"#rrggbb"` | multiply the texture (white = unchanged) |
| `irisColor`, `scleraColor` | colour | flat colour when the set has no texture |
| `pupilColor`, `backColor`, `eyelidColor` | colour | pupil, back of the eyeball, lid area |
| `pupilMin`, `pupilMax` | 0..1 | pupil size range, fraction of the iris |
| `slitPupilRadius` | px, 0..irisRadius | 0 = round pupil |
| `irisRadius` | px (160 px panel) | iris size |
| `eyeRadius`, `coverage` | px, 0.3..0.95 | ball size and how far the sclera wraps |
| `tracking`, `squint` | bool, 0..1 | upper lid follows the pupil, and how closely |
| `lidMirror` | bool | swap which eye gets the mirrored lid art |
| `blinkRate` | per minute | extra M4-style blinks on top of the animator's (`blink`, `blink_min_ms`/`blink_max_ms` settings) |
| `gazeRange` | 0..1 | eye-tracking range (default 0.75; higher shows the back of the ball at the extremes) |
| `irisSpin` (both), `irisSpinL`, `irisSpinR`, `scleraSpin` | RPM | texture spin |
| `irisMirror` (both), `irisMirrorL`, `irisMirrorR` | bool | mirror the iris texture |
| `irisAngle`, `scleraAngle` | 0..1023 | start angle |

Geometry keys (`eyeRadius`, `irisRadius`, `slitPupilRadius`, `coverage`)
rebuild the tables (60-240 ms freeze). Colour and tint keys re-tint the
texture copy. `eye` reloads from LittleFS (100-250 ms). The rest apply on the
next frame.

## Integration hooks

- **Style**: `settings::kM4` (`"m4"`) in `src/settings.{h,cpp}`; dispatched in
  `LcdEyes::prepare/simulate/renderRow` (`src/eyes_lcd.cpp`, effect 3).
- **Settings/NVS**: `settings::toJson()` nests `m4eye::getJson()` as `"m4"`
  and adds `m4eye::listJson()` as `"m4_sets"`. `settings::applyJson()` cuts the
  `"m4"` object out and hands it to `m4eye::applyJson()`. `settings::save()`
  stores `m4eye::getJson()` in NVS key `m4` (namespace `settings`);
  `settings::begin()` replays it; `settings::reset()` restores hazel's
  defaults.
- **Web page** (`src/net.cpp`): an "M4 eye" section whose inputs have ids
  `m4_<key>` and post `{"m4":{"<key>":value}}`; pickers are filled from
  `m4_sets`. The `/api/config` body buffer is 2 KB.
- **API for uploads** (`src/m4eye/m4eye.h`), for a later upload endpoint:
  - `installFile(eye, file, data, len)` writes `/eyes/<eye>/<file>`, rescans,
    and reloads if that eye is showing;
  - `loadTexture(path, ...)` reads `.565` or 24-bit `.bmp` (M4_Eyes' own
    textures work unconverted) into PSRAM;
  - `loadLidsFile(path, lids)`, `rescan()`, `reload()`.
  
  Lid bitmaps (1-bit BMP) still go through the converter.
- **Config in code**: `m4eye::config()`, `setConfig()`, `defaultsFor(eye)`.

## Eye sets on LittleFS

```
data/eyes/<name>/config.json   converted config.eye, radii in 160 px panel pixels
data/eyes/<name>/iris.565      uint16 LE width, height, then big-endian RGB565
data/eyes/<name>/sclera.565    (either may be absent: flat irisColor/scleraColor)
data/eyes/<name>/lids.bin      lid set "<name>": upperOpen, upperClosed, lowerOpen,
                               lowerClosed, 160 bytes each, y up from the bottom row
data/eyes/<name>/lids-<x>.bin  another lid set "<x>"
```

Ported: hazel (with its symmetrical lids), snake_green, doom-red,
doom-spiral, skull. Regenerate them, or add another, from an M4_Eyes checkout
with `tools/m4eye_sets.sh <M4_Eyes/eyes>` or
`python3 tools/m4eye_convert.py <M4_Eyes/eyes> <name> --fs data/eyes/<name>`,
then `pio run -t uploadfs`. **uploadfs replaces the whole LittleFS image**,
voice clips included. Without an image, `m4` falls back to the compiled-in
hazel (`src/m4eye/assets/hazel.h`, made with `--header`).

Check a set on the host before flashing:

```sh
c++ -std=c++17 -O2 -Isrc tools/m4eye_preview.cpp src/m4eye/m4eye_config.cpp -o /tmp/m4eye_preview
/tmp/m4eye_preview /tmp/m4.ppm data/eyes/snake_green '{}' '{"slitPupilRadius":0}'
```

On the board, `tools/m4eye_measure.py` (pyserial) repeats the measurements
above.

## Licences

See `src/m4eye/LICENSE.md` (copied to `data/eyes/LICENSE.md`): code and
eye sets are MIT (Adafruit / Phil Burgess). The demon eye is not included
because its iris is a DeviantArt texture with no stated licence.
