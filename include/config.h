// All pins and tunables in one place.
#pragma once
#include <stdint.h>

// ---------------------------------------------------------------------------
// Pins (ESP32-DevKitC-VIE / ESP32-WROVER-IE)
//
// Avoided: GPIO6-11 (flash), GPIO16/17 (WROVER PSRAM), GPIO12 (MTDI strap:
// high at boot selects 1.8 V flash and the WROVER won't boot), GPIO0 (boot).
// GPIO5 and GPIO15 are straps too, but as CS lines they idle high, which
// matches their default pull-ups, so they're safe.
// DC moved from the proposed GPIO2 to GPIO19: GPIO2 must be low/floating to
// enter the flasher, and a DC line is the one display signal a module might
// pull high. GPIO19 is the unused VSPI MISO, so it costs nothing.
// ---------------------------------------------------------------------------

// Displays: one VSPI bus, but every wire on its own pin, because each module
// comes with an 8-wire Dupont lead. "L"/"R" are the skull's own left/right.
// Left eye: the bus pins (CLK/DIN on the VSPI IO_MUX pins).
constexpr int PIN_TFT_SCLK = 18;
constexpr int PIN_TFT_MOSI = 23;
constexpr int PIN_TFT_CS_L = 5;
constexpr int PIN_TFT_DC = 19;
constexpr int PIN_TFT_RST = 4;
constexpr int PIN_TFT_BL = 21;  // LEDC PWM
// Right eye: CLK/DIN are copies of the bus signals through the GPIO matrix,
// DC/RST are driven in step with the left pins, BL shares the LEDC channel.
// Only the panel whose CS is low latches data, so both seeing the same
// signals is fine. Set any of these to -1 to drop it and share the left
// eye's wire instead (the old shared-bus wiring: all -1).
// GPIO13/14/15 are the JTAG pins, unused here. GPIO15 is a strap (it idles
// high, matching its pull-up); GPIO14 may toggle briefly at boot, which the
// panel ignores while CS is high.
constexpr int PIN_TFT_SCLK_R = 14;
constexpr int PIN_TFT_MOSI_R = 13;
constexpr int PIN_TFT_CS_R = 15;
constexpr int PIN_TFT_DC_R = 22;
constexpr int PIN_TFT_RST_R = 25;
constexpr int PIN_TFT_BL_R = 26;

// HLK-LD2410C radar (UART2).
constexpr int PIN_RADAR_RX = 33;   // ESP32 RX  <- radar TX
constexpr int PIN_RADAR_TX = 32;   // ESP32 TX  -> radar RX
constexpr int PIN_RADAR_OUT = 34;  // input-only pin, fine for OUT

// Jaw servo.
constexpr int PIN_SERVO = 27;

// PCM5102 I2S DAC: retired. Audio plays from the laptop brain, and the
// skull_i2s build isn't implemented in src. Its old pins (26/25/22) now belong
// to the right eye, so reviving it means picking new pins first.

// Backup NeoPixel eyes (Adafruit 4917 fixed-address fairy lights). GPIO2 is a
// strap (must be low/floating to enter the flasher), but a NeoPixel data
// input is high impedance, so it doesn't disturb that.
constexpr int PIN_NEOPIXEL = 2;

// ---------------------------------------------------------------------------
// Displays
// ---------------------------------------------------------------------------
constexpr int EYE_SIZE = 160;                  // 160x160 GC9D01
constexpr uint32_t TFT_SPI_HZ = 40000000;      // both eyes verified at 40 MHz; drop to 27 MHz only if long leads glitch
constexpr uint8_t BL_LEDC_CHANNEL = 7;         // high channel, servo lib takes the low ones
constexpr uint8_t BL_DEFAULT = 200;            // 0..255
// Per-mounting fixes, checked on the bench with `eyes test` / `eyes look`:
constexpr bool TFT_SWAP_RB = false;        // red and blue swapped in `eyes test`
// Picture rotation per eye, degrees clockwise as seen from the front, relative
// to the panel's native orientation (tip/FPC at the bottom): 0, 90, 180, 270.
// In the printed skull each module is turned 90 deg so its tip points at the
// nose (hardware/eye_mount.scad module_rot): the left eye (viewer's right) is
// turned 90 deg clockwise, the right eye 90 deg anticlockwise, so the picture
// is turned back the other way. Old stand-alone bar (tip down): 0 and 0.
// Adjust on the bench with `lcd rot <L|R> <deg>` and `eyes test`.
constexpr int EYE_L_ROT = 270;
constexpr int EYE_R_ROT = 90;
constexpr bool EYE_GAZE_X_INVERT = false;  // `eyes look 1 0` should look toward the skull's right
// "L"/"R" are the skull's own left/right (L = viewer's right). The lid art
// has a tear duct on one side; these put both at the nose (checked with
// tools/eye_preview.cpp).
constexpr bool EYE_L_LID_FLIP = false;
constexpr bool EYE_R_LID_FLIP = true;
constexpr const char* EYE_ART_DEFAULT = "fire";   // "default" (hazel), "dragon" or "fire" (burning, smoking iris)
constexpr bool EYE_FLAMES_DEFAULT = false;         // flames + smoke around hazel/dragon eyes

// ---------------------------------------------------------------------------
// Jaw (calibrate after mounting; `jaw closed <deg>` / `jaw open <deg>` then
// `jaw save` stores them in NVS, these are the defaults)
// ---------------------------------------------------------------------------
constexpr int JAW_CLOSED_DEG = 90;
constexpr int JAW_OPEN_DEG = 60;
constexpr int SERVO_MIN_US = 500;
constexpr int SERVO_MAX_US = 2400;

// ---------------------------------------------------------------------------
// Audio
// ---------------------------------------------------------------------------
#define AUDIO_OUT_A2DP 1
#define AUDIO_OUT_I2S 2
#ifndef AUDIO_OUT
#define AUDIO_OUT AUDIO_OUT_A2DP  // platformio.ini env "skull_i2s" overrides
#endif
constexpr const char* BT_SPEAKER_NAME = "CHANGE_ME";  // exact name your speaker advertises
constexpr int AUDIO_LATENCY_MS_DEFAULT = 200;       // jaw delay vs audio; tune with `lat <ms>`
constexpr uint32_t CLIP_RATE = 22050;               // stored rate; played at 44100 (2x upsample)

// ---------------------------------------------------------------------------
// Radar / behaviour
// ---------------------------------------------------------------------------
constexpr uint32_t RADAR_BAUD = 256000;
constexpr int APPROACH_CM = 150;          // trigger a clip when someone is closer than this
constexpr uint32_t CLIP_COOLDOWN_MS = 15000;

// ---------------------------------------------------------------------------
// Console
// ---------------------------------------------------------------------------
constexpr uint32_t CONSOLE_BAUD = 115200;

// ---------------------------------------------------------------------------
// Network. With WIFI_SSID set in include/secrets.h (gitignored; copy
// secrets.example.h) the skull joins that network as http://bone-eyes.local.
// Otherwise, or if joining fails, it opens its own access point and serves
// http://192.168.4.1.
// ---------------------------------------------------------------------------
#if __has_include("secrets.h")
#include "secrets.h"
#endif
#ifndef WIFI_SSID
#define WIFI_SSID ""
#endif
#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD ""
#endif
#ifndef AP_PASSWORD
#define AP_PASSWORD "bonejaw1031"  // WPA2 needs >= 8 chars; override in secrets.h
#endif
constexpr const char* NET_HOSTNAME = "bone-eyes";
constexpr const char* AP_SSID = "bone-eyes";
constexpr uint32_t WIFI_JOIN_TIMEOUT_MS = 10000;
