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

// Displays: VSPI, shared bus, one CS per eye.
constexpr int PIN_TFT_MOSI = 23;
constexpr int PIN_TFT_SCLK = 18;
constexpr int PIN_TFT_DC = 19;
constexpr int PIN_TFT_CS_L = 5;
constexpr int PIN_TFT_CS_R = 15;
constexpr int PIN_TFT_RST = 4;  // shared by both modules
constexpr int PIN_TFT_BL = 21;  // shared, LEDC PWM

// HLK-LD2410C radar (UART2).
constexpr int PIN_RADAR_RX = 33;   // ESP32 RX  <- radar TX
constexpr int PIN_RADAR_TX = 32;   // ESP32 TX  -> radar RX
constexpr int PIN_RADAR_OUT = 34;  // input-only pin, fine for OUT

// Jaw servo.
constexpr int PIN_SERVO = 27;

// PCM5102 I2S DAC (fallback audio output).
constexpr int PIN_I2S_BCK = 26;
constexpr int PIN_I2S_LRCK = 25;
constexpr int PIN_I2S_DOUT = 22;

// Backup NeoPixel eyes (Adafruit 4917 fixed-address fairy lights).
constexpr int PIN_NEOPIXEL = 13;

// ---------------------------------------------------------------------------
// Displays
// ---------------------------------------------------------------------------
constexpr int EYE_SIZE = 160;                  // 160x160 GC9D01
constexpr uint32_t TFT_SPI_HZ = 40000000;      // drop to 27 MHz if long Dupont leads glitch
constexpr uint8_t BL_LEDC_CHANNEL = 7;         // high channel, servo lib takes the low ones
constexpr uint8_t BL_DEFAULT = 200;            // 0..255
// Per-mounting fixes, checked on the bench with `eyes test` / `eyes look`:
constexpr bool TFT_SWAP_RB = false;        // red and blue swapped in `eyes test`
constexpr bool EYE_L_ROT180 = false;       // panel mounted upside down
constexpr bool EYE_R_ROT180 = false;
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
