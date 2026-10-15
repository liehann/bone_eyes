# bone_eyes

Talking Halloween skull: two round LCD eyes, a servo jaw synced to voice clips,
mmWave presence radar, audio over Bluetooth A2DP (or an I2S DAC).

Hardware: ESP32-DevKitC-VIE (WROVER-IE, PSRAM), 2x Waveshare 0.71" 160x160
GC9D01 LCDs, HLK-LD2410C radar, MG90S jaw servo, Bluetooth speaker or PCM5102
DAC, Adafruit 4917 NeoPixel fairy lights as backup eyes. 5 V 4 A supply.

## Wiring

All pins live in [`include/config.h`](include/config.h).

| Signal | ESP32 GPIO | Notes |
|---|---|---|
| LCD DIN (both) | 23 | VSPI MOSI |
| LCD CLK (both) | 18 | VSPI SCLK |
| LCD DC (both) | **19** | moved off GPIO2 (boot strap) |
| LCD CS left eye | 5 | skull's own left eye (viewer's right) |
| LCD CS right eye | 15 | |
| LCD RST (both) | 4 | |
| LCD BL (both) | 21 | PWM, active high |
| LCD VCC / GND | 5 V rail / GND | modules have their own 3.3 V LDO |
| Radar TX → ESP32 RX | 33 | 256000 baud |
| ESP32 TX → radar RX | 32 | |
| Radar OUT | 34 | input-only pin |
| Radar VCC | 5 V rail | |
| Servo signal | 27 | servo power from the 5 V rail, not the DevKit |
| PCM5102 BCK / LRCK / DIN | 26 / 25 / 22 | I2S build only |
| NeoPixel data | 13 | backup eyes |

Pin map changes from the original plan:

- **DC moved from GPIO2 to GPIO19.** GPIO2 must be low or floating to enter the
  flasher. GPIO19 is the unused VSPI MISO.
- GPIO5 and GPIO15 are strapping pins too. They're fine as CS lines because
  they idle high, which matches their default pull-ups.
- Nothing uses GPIO12. If GPIO12 is high at boot, the WROVER selects 1.8 V
  flash and won't boot.
- Nothing uses GPIO16/17, which the WROVER's PSRAM occupies.

## Build / flash

```sh
pio run -t upload            # A2DP build (env "skull")
pio run -e skull_i2s -t upload   # PCM5102 I2S fallback
pio run -t uploadfs          # flash data/ (clips) to LittleFS
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
| `eyes bl <0-255>` | backlight |
| `eyes lcd` / `eyes pixel` | switch eye backend |
| `art default\|dragon\|fire` | LCD eye style (fire = procedural burning iris) |
| `flames on\|off` | flames and smoke rising from the eyes, over any style |

### Display bring-up checklist (milestone 2)

1. Wire one panel (CS_L only) and run `eyes test 0`. You should see red,
   green, blue and white bands top to bottom, a magenta border, a yellow
   top-left square and one dot.
   - Red and blue swapped: set `TFT_SWAP_RB`.
   - Upside down: set `EYE_L_ROT180`.
   - Garbage or nothing: lower `TFT_SPI_HZ` to 27 MHz (Waveshare's demo
     speed) and check DC/RST.
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
