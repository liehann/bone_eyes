#include "standalone.h"

#include <Arduino.h>

#ifndef STANDALONE_BUILD
// Laptop image (env:skull): no BT stack linked, nothing to do.
namespace standalone {
void loadMode() {}
bool active() { return false; }
void registerCommands() {}
void begin() {}
}  // namespace standalone
#else

#include <BluetoothA2DPSource.h>
#include <LittleFS.h>
#include <Preferences.h>
#include <esp_bt.h>
#include <esp_heap_caps.h>
#include <esp_random.h>
#include <esp_timer.h>

#include "config.h"
#include "console.h"
#include "jaw.h"

namespace standalone {
namespace {

constexpr const char* kNs = "standalone";
constexpr uint32_t kOutRate = 44100;
constexpr int kMaxClips = 200;
constexpr int kRecent = 15;  // don't repeat any of the last N (capped at half the clips)

bool standalone_ = false;
int32_t latMs = AUDIO_LATENCY_MS_DEFAULT;
int32_t gapS = 30;
int32_t gainPct = 100;
volatile bool autoOn = true;

BluetoothA2DPSource a2dp;
int numClips = 0;

// The clip being played. pcm/env live in PSRAM. The A2DP callback reads pcm
// under mux; the player task swaps them.
portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;
int16_t* pcm = nullptr;
uint32_t pcmN = 0, pcmRate = 16000;
uint16_t* env = nullptr;
uint32_t envN = 0, envHz = 50;
volatile bool playing = false;
volatile uint64_t phase = 0;  // source position, 32.32 fixed point
volatile int curClip = -1;
volatile int playReq = -2;    // -2 none, -1 random, else clip index
volatile uint32_t cbCalls = 0;

// IMA ADPCM (matches tools/make_standalone_clips.py).
const int16_t kSteps[89] = {
    7,     8,     9,     10,    11,    12,    13,    14,    16,    17,    19,    21,    23,    25,    28,
    31,    34,    37,    41,    45,    50,    55,    60,    66,    73,    80,    88,    97,    107,   118,
    130,   143,   157,   173,   190,   209,   230,   253,   279,   307,   337,   371,   408,   449,   494,
    544,   598,   658,   724,   796,   876,   963,   1060,  1166,  1282,  1411,  1552,  1707,  1878,  2066,
    2272,  2499,  2749,  3024,  3327,  3660,  4026,  4428,  4871,  5358,  5894,  6484,  7132,  7845,  8630,
    9493,  10442, 11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767};
const int8_t kIdx[8] = {-1, -1, -1, -1, 2, 4, 6, 8};

void adpcmDecode(const uint8_t* in, uint32_t n, int16_t* out) {
  int pred = 0, idx = 0;
  for (uint32_t i = 0; i < n; i++) {
    const int c = (in[i >> 1] >> ((i & 1) * 4)) & 15;
    const int st = kSteps[idx];
    int diff = st >> 3;
    if (c & 4) diff += st;
    if (c & 2) diff += st >> 1;
    if (c & 1) diff += st >> 2;
    pred = (c & 8) ? pred - diff : pred + diff;
    pred = pred < -32768 ? -32768 : pred > 32767 ? 32767 : pred;
    idx += kIdx[c & 7];
    idx = idx < 0 ? 0 : idx > 88 ? 88 : idx;
    out[i] = (int16_t)pred;
  }
}

// A2DP data callback (BT task): 16 kHz mono -> 44.1 kHz stereo, linear interpolation.
int32_t audioCb(Frame* f, int32_t len) {
  cbCalls++;
  portENTER_CRITICAL(&mux);
  const bool on = playing;
  const int16_t* p = pcm;
  const uint32_t n = pcmN;
  uint64_t ph = phase;
  const uint64_t step = ((uint64_t)pcmRate << 32) / kOutRate;
  portEXIT_CRITICAL(&mux);
  const int32_t g = gainPct;
  int32_t i = 0;
  if (on && p) {
    for (; i < len; i++) {
      const uint32_t k = (uint32_t)(ph >> 32);
      if (k + 1 >= n) break;
      const uint32_t fr = (uint32_t)(ph >> 16) & 0xFFFF;
      int32_t s = p[k] + (((int32_t)(p[k + 1] - p[k]) * (int32_t)fr) >> 16);
      s = s * g / 100;
      s = s < -32768 ? -32768 : s > 32767 ? 32767 : s;
      f[i].channel1 = f[i].channel2 = (int16_t)s;
      ph += step;
    }
  }
  for (; i < len; i++) f[i].channel1 = f[i].channel2 = 0;
  portENTER_CRITICAL(&mux);
  if (playing && pcm == p) phase = ph;
  portEXIT_CRITICAL(&mux);
  return len;
}

bool nameMatches(const char* ssid, esp_bd_addr_t, int rssi) {
  static char last[64];
  if (strncmp(last, ssid, sizeof last - 1)) {  // log each new name once in a row
    strncpy(last, ssid, sizeof last - 1);
    Serial.printf("bt: found \"%s\" (rssi %d)\n", ssid, rssi);
  }
  return strncasecmp(ssid, BT_SPEAKER_NAME, strlen(BT_SPEAKER_NAME)) == 0;
}

void connState(esp_a2d_connection_state_t s, void*) {
  static const char* const names[] = {"disconnected", "connecting", "connected", "disconnecting"};
  Serial.printf("bt: %s, internal heap free %u (largest %u)\n", s < 4 ? names[s] : "?",
                heap_caps_get_free_size(MALLOC_CAP_INTERNAL), heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL));
}

void stopClip() {
  portENTER_CRITICAL(&mux);
  playing = false;
  int16_t* p = pcm;
  uint16_t* e = env;
  pcm = nullptr;
  env = nullptr;
  pcmN = envN = 0;
  portEXIT_CRITICAL(&mux);
  vTaskDelay(pdMS_TO_TICKS(30));  // let a callback that copied the pointer finish
  heap_caps_free(p);
  heap_caps_free(e);
  curClip = -1;
}

bool loadClip(int i) {
  char path[24];
  snprintf(path, sizeof path, "/clips/%03d.clp", i);
  File f = LittleFS.open(path, "r");
  if (!f) return Serial.printf("standalone: can't open %s\n", path), false;
  uint8_t h[16];
  if (f.read(h, 16) != 16 || memcmp(h, "BCLP", 4) || h[5] != 1) return Serial.printf("standalone: bad %s\n", path), false;
  const uint32_t rate = h[6] | h[7] << 8;
  const uint32_t n = h[8] | h[9] << 8 | h[10] << 16 | (uint32_t)h[11] << 24;
  const uint32_t hz = h[12] | h[13] << 8, ne = h[14] | h[15] << 8;
  const size_t adBytes = (n + 1) / 2;
  uint16_t* e = (uint16_t*)heap_caps_malloc(ne * 2 + 2, MALLOC_CAP_SPIRAM);
  uint8_t* ad = (uint8_t*)heap_caps_malloc(adBytes, MALLOC_CAP_SPIRAM);
  int16_t* p = (int16_t*)heap_caps_malloc(n * 2 + 4, MALLOC_CAP_SPIRAM);
  bool ok = e && ad && p && f.read((uint8_t*)e, ne * 2) == ne * 2 && f.read(ad, adBytes) == adBytes;
  if (ok) adpcmDecode(ad, n, p);
  heap_caps_free(ad);
  if (!ok) {
    heap_caps_free(e);
    heap_caps_free(p);
    return Serial.printf("standalone: load %s failed\n", path), false;
  }
  portENTER_CRITICAL(&mux);
  pcm = p;
  pcmN = n;
  pcmRate = rate;
  env = e;
  envN = ne;
  envHz = hz ? hz : 50;
  phase = 0;
  playing = true;
  portEXIT_CRITICAL(&mux);
  curClip = i;
  return true;
}

int recent[kRecent];
int nRecent = 0;

int pickClip() {
  const int keep = min(kRecent, numClips / 2);
  for (int tries = 0; tries < 50; tries++) {
    const int c = esp_random() % numClips;
    bool dup = false;
    for (int k = 0; k < nRecent && k < keep; k++) dup |= recent[k] == c;
    if (!dup) return c;
  }
  return esp_random() % numClips;
}

void remember(int c) {
  memmove(recent + 1, recent, sizeof(int) * (kRecent - 1));
  recent[0] = c;
  if (nRecent < kRecent) nRecent++;
}

uint32_t nextGapMs() { return (uint32_t)gapS * 1000 * (80 + esp_random() % 41) / 100; }

// 50 Hz: start clips, drive the jaw from the playing clip's envelope.
void playerTask(void*) {
  uint32_t nextAt = millis() + 10000;
  int64_t t0 = 0;          // clip start (us), for the no-BT clock
  int64_t lastTick = 0;
  int64_t audioEndUs = 0;  // when the source ran out (for the jaw tail)
  int lastLevel = -1;
  for (;;) {
    vTaskDelay(pdMS_TO_TICKS(10));
    const int64_t now = esp_timer_get_time();
    int req = playReq;
    if (req == -2 && autoOn && numClips && curClip < 0 && (int32_t)(millis() - nextAt) >= 0) req = -1;
    if (req != -2 && numClips) {
      playReq = -2;
      if (curClip >= 0) stopClip();
      const int c = req >= 0 && req < numClips ? req : pickClip();
      const int64_t l0 = esp_timer_get_time();
      if (loadClip(c)) {
        remember(c);
        t0 = lastTick = esp_timer_get_time();
        audioEndUs = 0;
        Serial.printf("standalone: clip %03d, %.1f s, loaded in %u ms, %s\n", c, pcmN / (float)pcmRate,
                      (unsigned)((t0 - l0) / 1000), a2dp.is_connected() ? "to the speaker" : "no speaker (jaw only)");
      }
      nextAt = millis() + nextGapMs();
      continue;  // fresh `now` for the first tick
    }
    if (curClip < 0) continue;
    // Source position: the A2DP callback advances it while connected; with
    // no speaker, a wall clock does (so the jaw still runs).
    const bool bt = a2dp.is_connected() && cbCalls;
    uint32_t k;
    portENTER_CRITICAL(&mux);
    if (!bt && playing) phase += ((uint64_t)(now - lastTick) * pcmRate << 32) / 1000000;
    k = (uint32_t)(phase >> 32);
    if (playing && k + 1 >= pcmN) playing = false;
    const bool on = playing;
    portEXIT_CRITICAL(&mux);
    lastTick = now;
    if (!on && !audioEndUs) audioEndUs = now;
    // Jaw: the envelope at (source time - latency).
    int64_t tMs = on ? (int64_t)k * 1000 / pcmRate : (int64_t)pcmN * 1000 / pcmRate + (now - audioEndUs) / 1000;
    tMs -= latMs;
    const int64_t fi = tMs < 0 ? -1 : tMs * envHz / 1000;
    int level = 0;
    if (fi >= 0 && fi < (int64_t)envN) level = env[fi];
    if (level != lastLevel) jaw::setOpening(level), lastLevel = level;
    if (!on && fi >= (int64_t)envN) {
      Serial.printf("standalone: clip %03d done in %u ms (audio %u ms + latency %d ms)\n", (int)curClip,
                    (unsigned)((now - t0) / 1000), (unsigned)(pcmN * 1000ull / pcmRate), (int)latMs);
      jaw::setOpening(0);
      lastLevel = 0;
      stopClip();
      nextAt = millis() + nextGapMs();
    }
  }
}

void saveInt(const char* key, int32_t v) {
  Preferences p;
  p.begin(kNs, false);
  p.putInt(key, v);
  p.end();
}

void printStatus() {
  Serial.printf("mode %s; clips %d; lat %d ms; gap %d s +-20%%; gain %d%%; auto %s\n",
                standalone_ ? "standalone" : "laptop", numClips, (int)latMs, (int)gapS, (int)gainPct,
                autoOn ? "on" : "off");
  if (standalone_)
    Serial.printf("bt: speaker \"%s\" %s, playing %d; internal heap free %u (largest %u, min %u)\n", BT_SPEAKER_NAME,
                  a2dp.is_connected() ? "connected" : "not connected", (int)curClip,
                  heap_caps_get_free_size(MALLOC_CAP_INTERNAL), heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL),
                  heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL));
}

void cmdMode(int, char**) {
  printStatus();
  Serial.println("mode: set by the image; back to laptop: pio run -e skull -t upload");
}

void cmdInt(int argc, char** argv, const char* key, int32_t& v, long lo, long hi) {
  long x;
  if (argc >= 2) {
    if (!console::argInt(argc, argv, 1, x) || x < lo || x > hi)
      return (void)Serial.printf("usage: %s <%ld-%ld>\n", argv[0], lo, hi);
    v = x;
    saveInt(key, v);
  }
  Serial.printf("%s %d (saved)\n", argv[0], (int)v);
}

void cmdLat(int argc, char** argv) { cmdInt(argc, argv, "lat", latMs, -500, 2000); }
void cmdGap(int argc, char** argv) { cmdInt(argc, argv, "gap", gapS, 5, 3600); }
void cmdGain(int argc, char** argv) { cmdInt(argc, argv, "gain", gainPct, 0, 400); }

void cmdPlay(int argc, char** argv) {
  if (!standalone_) return (void)Serial.println("play: standalone mode only (mode standalone)");
  long v = -1;
  if (argc >= 2 && (!console::argInt(argc, argv, 1, v) || v < 0 || v >= numClips))
    return (void)Serial.printf("usage: play [0-%d]\n", numClips - 1);
  playReq = (int)v;
}

void cmdAuto(int argc, char** argv) {
  if (argc >= 2) autoOn = !strcmp(argv[1], "on");
  Serial.printf("auto %s\n", autoOn ? "on" : "off");
}

void cmdBt(int, char**) { printStatus(); }

int countClips() {
  if (!LittleFS.begin(false)) return 0;
  int n = 0;
  char path[24];
  while (n < kMaxClips) {
    snprintf(path, sizeof path, "/clips/%03d.clp", n);
    if (!LittleFS.exists(path)) break;
    n++;
  }
  return n;
}

}  // namespace

void loadMode() {
  Preferences p;
  p.begin(kNs, true);
  standalone_ = true;
  latMs = p.getInt("lat", AUDIO_LATENCY_MS_DEFAULT);
  gapS = p.getInt("gap", 30);
  gainPct = p.getInt("gain", 100);
  p.end();
}

bool active() { return standalone_; }

void registerCommands() {
  console::add("mode", "show standalone status", cmdMode);
  console::add("lat", "standalone: jaw delay vs audio, ms", cmdLat);
  console::add("gap", "standalone: seconds between clips (+-20%)", cmdGap);
  console::add("gain", "standalone: audio gain %", cmdGain);
  console::add("play", "standalone: play [n] now", cmdPlay);
  console::add("auto", "standalone: auto on|off", cmdAuto);
  console::add("bt", "standalone: Bluetooth / player status", cmdBt);
}

void begin() {
  numClips = countClips();
  Serial.printf("standalone: %d clips; internal heap before BT %u\n", numClips,
                heap_caps_get_free_size(MALLOC_CAP_INTERNAL));
  // Classic BT only: release BLE memory, then init the controller ourselves
  // (btStart() in the library would ask for dual mode).
  esp_bt_controller_mem_release(ESP_BT_MODE_BLE);
  esp_bt_controller_config_t cfg = BT_CONTROLLER_INIT_CONFIG_DEFAULT();
  cfg.mode = ESP_BT_MODE_CLASSIC_BT;
  esp_err_t err = esp_bt_controller_init(&cfg);
  if (err == ESP_OK) err = esp_bt_controller_enable(ESP_BT_MODE_CLASSIC_BT);
  if (err != ESP_OK) Serial.printf("standalone: BT controller failed: %d\n", err);
  a2dp.set_local_name("bone-eyes");
  a2dp.set_auto_reconnect(true);
  a2dp.set_ssid_callback(nameMatches);
  a2dp.set_on_connection_state_changed(connState);
  a2dp.set_data_callback_in_frames(audioCb);
  a2dp.start(BT_SPEAKER_NAME);
  Serial.printf("standalone: BT up, looking for \"%s\"; internal heap free %u (largest %u)\n", BT_SPEAKER_NAME,
                heap_caps_get_free_size(MALLOC_CAP_INTERNAL), heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL));
  xTaskCreatePinnedToCore(playerTask, "player", 4096, nullptr, 3, nullptr, 0);
}

}  // namespace standalone

#endif  // STANDALONE_BUILD
