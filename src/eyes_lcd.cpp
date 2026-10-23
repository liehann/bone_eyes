// LCD eye backend: Uncanny Eyes renderer (after Bodmer's TFT_eSPI
// Animated_Eyes_2 / Phil Burgess' Adafruit Uncanny Eyes, MIT) on two GC9D01
// panels. The 128x128 artwork is upscaled to 160x160 with a nearest-neighbour
// lookup; rows are rendered into small internal-RAM buffers and DMA'd while the
// next chunk renders, so no full framebuffers are needed.
#include <esp_heap_caps.h>

#include "config.h"
#include "console.h"
#include "eye_art/eye_art.h"
#include "eye_render.h"
#include "eyes.h"
#include "fire_eye.h"
#include "fire_render.h"
#include "flame_overlay.h"
#include "gc9d01.h"

namespace {

constexpr int N = Gc9d01Bus::kSize;
constexpr int kChunkRows = 8;

// Styles: the two Uncanny Eyes artworks, plus "fire" (procedural burning
// iris whose flame tips smoke and drift up over the lids; default eye's lid
// shapes).
const char* const kStyles[] = {"default", "dragon", "fire"};
constexpr int kFireStyle = 2;
volatile int currentStyle = 1;
volatile bool flamesOn = EYE_FLAMES_DEFAULT;  // flames + smoke around hazel/dragon eyes

uint16_t be(uint16_t c) { return (c >> 8) | (c << 8); }
uint16_t rgb(uint8_t r, uint8_t g, uint8_t b) { return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3); }

class LcdEyes : public EyeBackend {
 public:
  const char* name() const override { return "lcd"; }

  bool begin() override {
    if (!started_) {
      if (!bus_.begin(PIN_TFT_MOSI, PIN_TFT_SCLK, PIN_TFT_DC, PIN_TFT_RST, TFT_SPI_HZ)) {
        Serial.println("lcd: SPI init failed");
        return false;
      }
      bus_.mirror(PIN_TFT_MOSI_R, PIN_TFT_SCLK_R, PIN_TFT_DC_R, PIN_TFT_RST_R);
      bus_.addPanel(PIN_TFT_CS_L);
      bus_.addPanel(PIN_TFT_CS_R);
      ledcSetup(BL_LEDC_CHANNEL, 5000, 8);
      ledcAttachPin(PIN_TFT_BL, BL_LEDC_CHANNEL);
      if (PIN_TFT_BL_R >= 0) ledcAttachPin(PIN_TFT_BL_R, BL_LEDC_CHANNEL);
      for (int i = 0; i < 2; i++) {
        buf_[i] = (uint16_t*)heap_caps_malloc(N * kChunkRows * 2, MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
        if (!buf_[i]) return false;
      }
      started_ = true;
    }
    ledcWrite(BL_LEDC_CHANNEL, 0);
    bus_.initPanels();
    bus_.setOrientation(0, EYE_L_ROT180, TFT_SWAP_RB);
    bus_.setOrientation(1, EYE_R_ROT180, TFT_SWAP_RB);
    bus_.fill(0, 0);
    bus_.fill(1, 0);
    ledcWrite(BL_LEDC_CHANNEL, brightness_);
    uTrack_[0] = uTrack_[1] = 128;
    return true;
  }

  void end() override {
    // Keep the SPI bus (can't cleanly re-add it); just blank.
    bus_.fill(0, 0);
    bus_.fill(1, 0);
    ledcWrite(BL_LEDC_CHANNEL, 0);
  }

  void setBrightness(uint8_t level) override {
    brightness_ = level;
    ledcWrite(BL_LEDC_CHANNEL, level);
  }

  void draw(const EyeState& l, const EyeState& r) override {
    drawEye(0, l);
    drawEye(1, r);
  }

  // Colour bars + orientation markers. Left eye shows one white dot, right
  // shows two; a yellow square marks the top-left corner.
  void testPattern(int eye) override {
    for (int e = 0; e < 2; e++) {
      if (eye != 2 && eye != e) continue;
      const uint16_t bars[] = {rgb(255, 0, 0), rgb(0, 255, 0), rgb(0, 0, 255), rgb(255, 255, 255)};
      bus_.beginFrame(e, 0, 0, N - 1, N - 1);
      for (int y0 = 0; y0 < N; y0 += kChunkRows) {
        if (bus_.inFlight() == 2) bus_.waitOne();
        uint16_t* b = buf_[(y0 / kChunkRows) & 1];
        for (int y = y0; y < y0 + kChunkRows; y++) {
          for (int x = 0; x < N; x++) {
            uint16_t c = bars[y * 4 / N];
            if (x < 20 && y < 20) c = rgb(255, 255, 0);
            if (x == 0 || y == 0 || x == N - 1 || y == N - 1) c = rgb(255, 0, 255);
            for (int d = 0; d <= e; d++) {
              int cx = N / 2 + (e ? (d ? 15 : -15) : 0), dx = x - cx, dy = y - N / 2;
              if (dx * dx + dy * dy < 64) c = rgb(255, 255, 255) ^ (y * 4 / N == 3 ? 0xFFFF : 0);
            }
            b[(y - y0) * N + x] = be(c);
          }
        }
        bus_.queuePixels(b, N * kChunkRows);
      }
      bus_.endFrame();
    }
  }

 private:
  void drawEye(int e, const EyeState& st) {
    const int style = currentStyle;
    const bool fire = style == kFireStyle;
    const EyeArt& a = style == 1 ? kDragonEye : kDefaultEye;  // fire uses the default lids
    const float gx = EYE_GAZE_X_INVERT ? -st.gazeX : st.gazeX;
    const bool flip = e == 0 ? EYE_L_LID_FLIP : EYE_R_LID_FLIP;
    const int mood = (int)st.mood;

    // Fire and the flame overlay share one set of per-eye buffers; reset them
    // when switching between the two so stale heat doesn't flash up.
    const int effect = fire ? 2 : (flamesOn ? 1 : 0);
    if (effect && !ensureBuffers()) return;
    if (effect != effect_[e]) {
      if (effect == 2) fire_eye::reset(fireEye_[e], 0x9E3779B9u + e);
      if (effect == 1) flame_overlay::reset(flame_[e], 0x9E3779B9u + e);
      effect_[e] = effect;
    }
    const bool flames = effect == 1;

    eye_render::Params p;
    if (fire) {
      fire_render::Params fp =
          fire_render::compute(a, gx, st.gazeY, st.lid, st.pupil, flip, uTrack_[e], mood, millis(), fireState_[e]);
      fire_eye::step(fireEye_[e], a, fp, mood);
    } else {
      p = eye_render::compute(a, gx, st.gazeY, st.lid, st.pupil, flip, uTrack_[e]);
      if (flames) flame_overlay::step(flame_[e], a, p, mood);
    }

    bus_.beginFrame(e, 0, 0, N - 1, N - 1);
    int chunk = 0;
    uint16_t* b = nullptr;
    uint16_t* prev = nullptr;
    for (int oy = 0; oy < N; oy++) {
      if (oy % kChunkRows == 0) {
        if (bus_.inFlight() == 2) bus_.waitOne();
        b = buf_[chunk++ & 1];
      }
      uint16_t* row = b + (oy % kChunkRows) * N;
      if (!fire && !flames && prev && eye_render::repeatsPrevious(a.lidSize, oy)) {
        memcpy(row, prev, N * 2);  // upscaling repeats every 5th row
      } else {
        if (fire) {
          fire_eye::row(fireEye_[e], oy, row);
        } else {
          eye_render::row(a, p, oy, row);
          if (flames) flame_overlay::composite(flame_[e], oy, row);
        }
        for (int x = 0; x < N; x++) row[x] = be(row[x]);
      }
      prev = row;
      if (oy % kChunkRows == kChunkRows - 1) bus_.queuePixels(b, N * kChunkRows);
    }
    bus_.endFrame();
  }

  // Effect buffers (3 x 25.6 KB per eye) live in PSRAM, allocated on first use.
  bool ensureBuffers() {
    if (fx_[0]) return true;
    for (int e = 0; e < 2; e++) {
      uint8_t* m = (uint8_t*)heap_caps_malloc(3 * N * N, MALLOC_CAP_SPIRAM);
      if (!m) m = (uint8_t*)heap_caps_malloc(3 * N * N, MALLOC_CAP_8BIT);
      if (!m) {
        Serial.println("eyes: out of memory for fire/flames, falling back to plain eyes");
        flamesOn = false;
        currentStyle = 1;
        return false;
      }
      fx_[e] = m;
      flame_[e] = {m, m + N * N, m + 2 * N * N, 0, 0};
      fireEye_[e] = {m, m + N * N, m + 2 * N * N, 0, 0, 0, 0, 0};
      effect_[e] = 0;
    }
    return true;
  }

  Gc9d01Bus bus_;
  bool started_ = false;
  uint16_t* buf_[2] = {nullptr, nullptr};
  uint8_t brightness_ = BL_DEFAULT;
  int uTrack_[2] = {128, 128};
  fire_render::State fireState_[2];
  uint8_t* fx_[2] = {nullptr, nullptr};
  int effect_[2] = {0, 0};  // 0 none, 1 flame overlay, 2 fire eye
  flame_overlay::Buffers flame_[2] = {};
  fire_eye::Buffers fireEye_[2] = {};
};

void cmdArt(int argc, char** argv) {
  for (int i = 0; i < 3; i++) {
    if (argc > 1 && strcmp(argv[1], kStyles[i]) == 0) {
      currentStyle = i;
      return;
    }
  }
  Serial.printf("art: %s (options: default dragon fire)\n", kStyles[currentStyle]);
}

void cmdFlames(int argc, char** argv) {
  if (argc > 1) flamesOn = strcmp(argv[1], "on") == 0;
  Serial.printf("flames: %s\n", flamesOn ? "on" : "off");
}

}  // namespace

EyeBackend* makeLcdEyes() {
  static bool registered = false;
  if (!registered) {
    for (int i = 0; i < 3; i++)
      if (strcmp(kStyles[i], EYE_ART_DEFAULT) == 0) currentStyle = i;
    console::add("art", "LCD eye style: art [default|dragon|fire]", cmdArt);
    console::add("flames", "flames + smoke around hazel/dragon eyes: flames [on|off]", cmdFlames);
    registered = true;
  }
  static LcdEyes* instance = new LcdEyes();  // owns the SPI bus; reused across backend switches
  return instance;
}
