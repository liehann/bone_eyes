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
#include "gc9d01.h"

namespace {

constexpr int N = Gc9d01Bus::kSize;
constexpr int kChunkRows = 8;

const EyeArt* const kArts[] = {&kDefaultEye, &kDragonEye};
const EyeArt* volatile currentArt = &kDragonEye;

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
      bus_.addPanel(PIN_TFT_CS_L);
      bus_.addPanel(PIN_TFT_CS_R);
      ledcSetup(BL_LEDC_CHANNEL, 5000, 8);
      ledcAttachPin(PIN_TFT_BL, BL_LEDC_CHANNEL);
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
    const EyeArt& a = *currentArt;
    eye_render::Params p =
        eye_render::compute(a, EYE_GAZE_X_INVERT ? -st.gazeX : st.gazeX, st.gazeY, st.lid, st.pupil,
                            e == 0 ? EYE_L_LID_FLIP : EYE_R_LID_FLIP, uTrack_[e]);

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
      if (prev && eye_render::repeatsPrevious(a.lidSize, oy)) {
        memcpy(row, prev, N * 2);  // upscaling repeats every 5th row
      } else {
        eye_render::row(a, p, oy, row);
        for (int x = 0; x < N; x++) row[x] = be(row[x]);
      }
      prev = row;
      if (oy % kChunkRows == kChunkRows - 1) bus_.queuePixels(b, N * kChunkRows);
    }
    bus_.endFrame();
  }

  Gc9d01Bus bus_;
  bool started_ = false;
  uint16_t* buf_[2] = {nullptr, nullptr};
  uint8_t brightness_ = BL_DEFAULT;
  int uTrack_[2] = {128, 128};
};

void cmdArt(int argc, char** argv) {
  for (const EyeArt* a : kArts) {
    if (argc > 1 && strcmp(argv[1], a->name) == 0) {
      currentArt = a;
      return;
    }
  }
  Serial.printf("art: %s (options:", currentArt->name);
  for (const EyeArt* a : kArts) Serial.printf(" %s", a->name);
  Serial.println(")");
}

}  // namespace

EyeBackend* makeLcdEyes() {
  static bool registered = false;
  if (!registered) {
    for (const EyeArt* a : kArts)
      if (strcmp(a->name, EYE_ART_DEFAULT) == 0) currentArt = a;
    console::add("art", "LCD eye artwork: art [default|dragon]", cmdArt);
    registered = true;
  }
  static LcdEyes* instance = new LcdEyes();  // owns the SPI bus; reused across backend switches
  return instance;
}
