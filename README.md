# bone_eyes

Talking Halloween skull: two round LCD eyes, a servo jaw synced to voice clips,
mmWave presence radar, audio over Bluetooth A2DP (or an I2S DAC).

Hardware: ESP32-DevKitC-VIE (WROVER-IE, PSRAM), 2x Waveshare 0.71" 160x160
GC9D01 LCDs, HLK-LD2410C radar, MG90S jaw servo, Bluetooth speaker or PCM5102
DAC, Adafruit 4917 NeoPixel fairy lights as backup eyes. 5 V 4 A supply.

## Wiring

All pins live in [`include/config.h`](include/config.h).

Each GC9D01 module comes with an 8-wire lead with separate Dupont ends, so
every LCD wire goes to its own ESP32 pin (16 wires for both eyes). "Left" and
"right" are the skull's own (the left eye is on the viewer's right).

| LCD wire | Left eye | Right eye | Notes |
|---|---|---|---|
| VCC | 3V3 | 3V3 | sets the header logic level (see below); not 5 V |
| GND | GND | GND (a different GND pin) | |
| DIN | 23 | 13 | right = copy of VSPI MOSI via the GPIO matrix |
| CLK | 18 | 14 | right = copy of VSPI SCLK via the GPIO matrix |
| CS | 5 | 15 | the only per-eye signal the firmware tells apart |
| DC | **19** | 22 | driven together |
| RST | 4 | 25 | pulsed together |
| BL | 21 | 26 | same LEDC PWM channel, active high |

Both VCC wires go to 3V3, not 5 V. On the module the header feeds the B side
of a TXB0108 level shifter whose VCCB is VCC, so VCC sets the logic level the
header expects. On 5 V the ESP32's 3.3 V outputs sit right at the TXB0108's
V_IH (0.65 × 5 V = 3.25 V) and the panel stays black with the backlight on.
The DevKitC has a single 3V3 pin, so share it through a breadboard row or a
Y-splitter. Two modules draw roughly 40–80 mA. See
[`docs/gc9d01.md`](docs/gc9d01.md).

Both eyes run off one SPI bus. Only the panel whose CS is low latches data, so
both seeing the same clock, data and DC is fine. To go back to shared wires
(one lead split to both panels), set the `*_R` pins in `config.h` to -1.

| Signal | ESP32 GPIO | Notes |
|---|---|---|
| Radar TX → ESP32 RX | 33 | 256000 baud |
| ESP32 TX → radar RX | 32 | |
| Radar OUT | 34 | input-only pin |
| Radar VCC | 5 V rail | |
| Servo signal | 27 | servo power from the 5 V rail, not the DevKit |
| NeoPixel data | 2 | backup eyes; data input is high impedance, so the GPIO2 strap is unaffected |

The PCM5102 I2S DAC is retired: audio plays from the laptop brain, and the
`skull_i2s` build isn't implemented in `src/`. Its old pins (26/25/22) are now
the right eye's BL/RST/DC, so it needs new pins if it's ever revived.

Pin map changes from the original plan:

- **DC moved from GPIO2 to GPIO19.** GPIO2 must be low or floating to enter the
  flasher. GPIO19 is the unused VSPI MISO.
- GPIO5 and GPIO15 are strapping pins too. They're fine as CS lines because
  they idle high, which matches their default pull-ups.
- **NeoPixel moved from GPIO13 to GPIO2** to free 13/14 for the right eye's
  DIN/CLK.
- Nothing uses GPIO12. If GPIO12 is high at boot, the WROVER selects 1.8 V
  flash and won't boot.
- Nothing uses GPIO16/17, which the WROVER's PSRAM occupies.

## Build / flash

```sh
pio run -t upload            # A2DP build (env "skull")
pio run -e skull_i2s -t upload   # PCM5102 I2S fallback (not implemented; needs re-pinning)
pio run -t uploadfs          # flash data/ (clips, M4 eye sets in data/eyes/) to LittleFS; replaces the whole image
pio device monitor           # console, 115200
```

The partition table assumes 8 MB flash, which is what the DevKitC-VIE ships
with. Run `esptool.py flash_id`, or check the boot banner. If the board has
4 MB, change `board_build.partitions` to `partitions_4mb.csv` and
`flash_size` to 4MB in `platformio.ini`. That build has room for about 45 s
of clips instead of about 2.3 min.

## Bench console

Type `help` in the monitor.

| Command | What it does |
|---|---|
| `info`, `heap` | chip, flash and PSRAM size; free internal and PSRAM heap |
| `eyes` | backend, mood, frame rate |
| `eyes test [0\|1\|2]` | colour bars. Left eye = 1 dot, right eye = 2 dots, yellow square = top-left |
| `eyes anim` | back to animation |
| `eyes look <x> <y>` / `eyes free` | hold a gaze (-1..1; +x = skull's right, +y = up) / release it |
| `eyes blink`, `eyes mood idle\|alert\|talking\|goodbye` | trigger a blink / set the mood |
| `eyes bl <0-255>` | backlight (a setting: `config save` keeps it) |
| `eyes lcd` / `eyes pixel` | switch eye backend |
| `art default\|dragon\|fire\|m4` | LCD eye style (a setting). `default` is the regular hazel eye; `fire` (default): burning iris whose flame tips turn to smoke, which flows around the iris and up over the lids; `m4`: the Adafruit M4_Eyes renderer with eye sets from LittleFS (see `docs/m4_eyes.md`) |
| `m4`, `m4 <key> <value>`, `m4 set <json>` | M4 eye parameters: show / change one / patch (e.g. `m4 eye snake_green`, `m4 irisTint #ff8080`). Also `m4 list`, `m4 reset` (the eye set's defaults), `m4 rescan`, `m4 mem tables int\|psram tex psram\|int\|flash`, `m4 bench [n]` |
| `flames on\|off` | flames and smoke rising from hazel/dragon eyes (a setting) |
| `config` / `config show` | print the settings as JSON |
| `config set <key> <value>`, `config keys` | change one setting live / list the keys |
| `config save` / `config reset` | keep the current settings across reboots / restore and save the `config.h` defaults |
| `!a <style>` / `!a` | brain link: override the eye style for the speaking persona (not saved) / back to the saved style |
| `lcd prof` | frame-time breakdown since the last call: simulation, row rendering on each core, SPI waits |
| `lcd rot [L\|R\|both <0\|90\|180\|270>]` | show or set each eye's picture rotation (clockwise, seen from the front), then show the test pattern. A setting: `config save` keeps it (`EYE_L_ROT` / `EYE_R_ROT` are the defaults) |

## Settings web page

The skull serves a settings page at `http://bone-eyes.local/` (or its IP; on
its own access point `http://192.168.4.1/`). It's plain HTML/JS from flash, no
CDN, so it works on the access point too. It has:

- eye style (regular/hazel, dragon, fire, M4 eye), brightness, rotation per
  eye, gaze mirror;
- M4 eye: eye set, eyelid shape, iris and sclera tint, iris size, slit pupil,
  pupil min/max, eye-tracking range, lids following the pupil, extra blinks;
- effects: flames around regular/dragon eyes, smoke, fire-eye flame length;
- behaviour: blinking on its own and the blink gap, looking around when idle,
  going cross-eyed when someone is close, pupils reacting to the mood;
- buttons for the eyes test pattern, back to animation, a blink, and the mood;
- the status table (network, IP, uptime, heap, frame rate, style, mood).

Changes apply at once. **Save** keeps them in NVS across reboots; **Reset**
restores and saves the `config.h` defaults. The brain's `!a <style>` is a
temporary override on top (shown on the page); picking a style on the page,
`!a` with no style, or a reboot goes back to the saved one.

| Endpoint | |
|---|---|
| `GET /` | the page |
| `GET /status` | uptime, heap, eye fps, RSSI, network, IP, mood, style shown |
| `GET /api/config` | settings as JSON, plus `style_override` (the brain's, or null) |
| `POST /api/config` | partial update as JSON (or form fields); `?save=1` (or `"save":1`) also saves, `?reset=1` restores the defaults first; `"mood"` sets the mood (live only). Returns the new settings; a bad value gives 400 with `"error"` |
| `POST /api/eyes?cmd=test\|anim\|blink` | test pattern / back to animation / blink |

```sh
curl http://bone-eyes.local/api/config
curl -X POST -H 'Content-Type: application/json' \
     -d '{"style":"default","flames":false,"brightness":150}' \
     'http://bone-eyes.local/api/config?save=1'
```

Keys: `style` (`default`, `dragon`, `fire` or `m4`), `flames`, `smoke`, `fire_len` (50-150 %),
`brightness` (0-255), `rot_l`, `rot_r` (0/90/180/270), `gaze_invert`, `blink`,
`blink_min_ms`, `blink_max_ms`, `wander`, `verge`, `pupil_react`, and `m4`,
a nested object of M4 eye parameters (partial; `docs/m4_eyes.md` lists them).
`GET` also returns `m4_sets`, the eye and lid sets on offer. Booleans
take `true`/`false` (or `on`/`off`, 1/0). The HTTP server runs on core 0 at
low priority, and the console logs each settings change with the client IP.

### Display bring-up checklist (milestone 2)

1. Wire one panel (CS_L only) and run `eyes test 0`. You should see red,
   green, blue and white bands top to bottom, a magenta border, a yellow
   top-left square and one dot.
   - Red and blue swapped: set `TFT_SWAP_RB`.
   - Rotated: try `lcd rot L <0|90|180|270>` until the bars run red, green,
     blue, white from top to bottom with the yellow square top-left, then
     `config save` (or set `EYE_L_ROT` / `EYE_R_ROT` in `config.h`). The skull's
     defaults are L = 270 and R = 90, because each module is mounted with its
     tip toward the nose. On the old tip-down bar, use 0 and 0.
   - Garbage or nothing: check that VCC is on 3V3 (on 5 V the panel stays
     black), then DC/RST. 40 MHz SPI works on both eyes; `lcd spi 27` (Waveshare's
     demo speed) is only worth trying with long leads.
2. Add the second panel, then run `eyes test` and check for two dots on the
   right eye.
3. Run `eyes anim`, then `eyes` to see the frame rate. Run `eyes look 1 0`:
   both irises should move toward the skull's right. If they move the other
   way, set `EYE_GAZE_X_INVERT`.

Simulate the eyes in a browser: `tools/eye_sim/build.py` builds
`tools/eye_sim/eye_sim.html`, which animates both eyes with a JS port of the
renderer and eye controller, with controls for mood, gaze and a visitor. The
build checks the port against the C++ renderer with pixel checksums.

For a static contact sheet of poses instead:

```sh
c++ -std=c++17 -O2 -Itools/host_shim -Isrc tools/eye_preview.cpp \
    src/eye_art/default_eye.cpp src/eye_art/dragon_eye.cpp -o /tmp/eye_preview
/tmp/eye_preview /tmp/eyes.ppm && open /tmp/eyes.ppm
```

## Adding voice clips

```sh
pip install numpy scipy matplotlib   # matplotlib only for --preview
tools/make_envelopes.py recordings/*.wav --preview
pio run -t uploadfs
```

- Input can be WAV in any format, or anything ffmpeg decodes.
- Output goes to `data/clips/`:
  - `<name>.wav`: 22.05 kHz 16-bit mono, trimmed and peak-normalised.
  - `<name>.env`: 30 fps jaw envelope.
- Names starting with `bye_` are goodbye clips. All other names are greetings.
- Keep names to 24 characters or fewer.
- `--preview` writes a PNG of each waveform with its envelope. Use it to tune
  `--range-db`, `--gamma`, `--attack-ms` and `--release-ms`.
- `--synth-test test_beeps` makes a bench clip with clicks once per second,
  for dialling in Bluetooth latency.

Why 22.05 kHz mono instead of 44.1 kHz stereo: A2DP wants 44.1 kHz 16-bit
stereo, which is 176 KB/s, so the 5.9 MB LittleFS partition would hold only
about 33 s. Stored at 22.05 kHz mono (44 KB/s), the same partition holds about
2.3 min. The firmware upsamples 2x and duplicates to stereo as it streams,
which costs almost nothing. 11 kHz bandwidth is plenty for a voice. The 30 fps
envelope frames are exactly 735 samples, so jaw frames line up with the audio
exactly.

## Milestones

1. [x] Builds and flashes; serial console.
2. [x] Display test pattern on one panel, then both, then animated eyes. Code
   is done; still needs bench verification.
3. [ ] Radar frames parsed; presence and distance on serial.
4. [ ] Servo sweep and jaw calibration.
5. [ ] A2DP to the speaker plus a test clip; then the I2S DAC.
6. [x] Envelope script (offline part). [ ] Synced jaw playback with an
   adjustable latency offset.
7. [ ] Behaviour state machine.
8. [ ] NeoPixel eye backend.

## Third-party code

- Eye artwork and renderer algorithm: Phil Burgess / Adafruit "Uncanny Eyes"
  (MIT), via Bodmer's TFT_eSPI `Animated_Eyes_2` example.
- GC9D01 init sequence: Waveshare 0.71" LCD demo.
- M4 eye renderer and eye sets: Phil Burgess / Adafruit "M4_Eyes" (MIT); see
  `src/m4eye/LICENSE.md` (the demon eye's third-party iris is not included).
