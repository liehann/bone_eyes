// LCD eye backend: Uncanny Eyes renderer (after Bodmer's TFT_eSPI
// Animated_Eyes_2 / Phil Burgess' Adafruit Uncanny Eyes, MIT) on two GC9D01
// panels. The 128x128 artwork is upscaled to 160x160 with a nearest-neighbour
// lookup; rows are rendered on both cores into a ring of small internal-RAM
// chunk buffers and DMA'd while the next chunks render, so no full
// framebuffers are needed. `lcd prof` prints where the frame time goes.
// Per-pixel renderer code: -O2 is ~20% faster here than the default -Os.
#pragma GCC optimize("O2")
#include <esp_heap_caps.h>
#include <esp_timer.h>

#include "config.h"
#include "console.h"
#include "eye_art/eye_art.h"
#include "eye_render.h"
#include "eyes.h"
#include "fire_eye.h"
#include "fire_render.h"
#include "flame_overlay.h"
#include "gc9d01.h"
#include "m4eye/m4eye.h"
#include "settings.h"

namespace {

constexpr int N = Gc9d01Bus::kSize;
constexpr int kChunkRows = 8;
constexpr int kChunks = Gc9d01Bus::kSize / kChunkRows;
constexpr int kRing = 4;  // DMA chunk buffers

// Styles (settings::Style): the two Uncanny Eyes artworks, plus "fire"
// (procedural burning iris whose flame tips smoke and drift up over the lids;
// default eye's lid shapes). Chosen in src/settings.cpp.

// Frame-time breakdown for `lcd prof` (microseconds, summed since the last
// print). Per eye: simulation step, row rendering, time blocked on SPI.
struct Prof {
  int64_t sim, render, wait, total;
};
Prof prof[2];
// Per frame: whole draw() and core 1 waiting for the worker's simulation.
// The worker's row rendering is summed separately.
struct FrameProf {
  int64_t total, workerWait;
  uint32_t frames;
};
FrameProf frameProf;
struct WorkerProf {
  int64_t render;
};
WorkerProf workerProf;

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
      for (int i = 0; i < kRing; i++) {
        buf_[i] = (uint16_t*)heap_caps_malloc(N * kChunkRows * 2, MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
        if (!buf_[i]) return false;
      }
      eye_render::srcMap(kDefaultEye.lidSize);  // build the shared map before two cores read it
      startWorker();
      started_ = true;
    }
    ledcWrite(BL_LEDC_CHANNEL, 0);
    bus_.initPanels();
    applyOrientation();
    bus_.fill(0, 0);
    bus_.fill(1, 0);
    ledcWrite(BL_LEDC_CHANNEL, brightness_);
    uTrack_[0] = uTrack_[1] = 128;
    return true;
  }

  // --- diagnostics (`lcd ...`); callers pause the eye task first ---
  bool started() const { return started_; }
  Gc9d01Bus& bus() { return bus_; }

  void reinit() {
    bus_.initPanels();
    applyOrientation();
  }

  // Per-eye picture rotation (deg clockwise, 0/90/180/270), set by the eye
  // task from the settings (`lcd rot`, the web page).
  int rotation(int eye) const { return rot_[eye]; }
  void setRotation(int eye, int deg) override {
    rot_[eye] = deg;
    bus_.setOrientation(eye, deg, TFT_SWAP_RB);
  }
  void applyOrientation() {
    for (int e = 0; e < 2; e++) bus_.setOrientation(e, rot_[e], TFT_SWAP_RB);
  }

  void fillBoth(uint16_t c) {
    bus_.fill(0, c);
    bus_.fill(1, c);
  }

  void restoreBacklight() {
    ledcAttachPin(PIN_TFT_BL, BL_LEDC_CHANNEL);
    if (PIN_TFT_BL_R >= 0) ledcAttachPin(PIN_TFT_BL_R, BL_LEDC_CHANNEL);
    ledcWrite(BL_LEDC_CHANNEL, brightness_);
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

  // Both cores render every frame: each simulates one eye, then for each eye
  // in turn core 1 renders the even chunks of rows and a worker on core 0 the
  // odd ones, while core 1 queues them all to the SPI DMA in order. Both
  // panels share one SPI bus, so the transfers themselves are serial.
  void draw(const EyeState& l, const EyeState& r) override {
    const int64_t t0 = esp_timer_get_time();
    Frame f;
    prepare(f);
    if (worker_) {
      job_ = r;
      jobFrame_ = f;
      command(kSimRight);
      timedSimulate(0, l, f);
      const int64_t t1 = esp_timer_get_time();
      xSemaphoreTake(done_, portMAX_DELAY);
      frameProf.workerWait += esp_timer_get_time() - t1;
    } else {
      timedSimulate(0, l, f);
      timedSimulate(1, r, f);
    }
    streamEye(0, f);
    streamEye(1, f);
    frameProf.total += esp_timer_get_time() - t0;
    frameProf.frames++;
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
  int rot_[2] = {EYE_L_ROT, EYE_R_ROT};
  // Per-frame choices, made once on core 1 so both eyes agree.
  struct Frame {
    int style;
    int effect;  // 0 none, 1 flame overlay, 2 fire eye, 3 M4 eye (src/m4eye)
    bool smoke, gazeInvert;
    int fireLen;  // % of the mood's flame length
  };

  void prepare(Frame& f) {
    const settings::Settings cfg = settings::get();
    f.style = settings::effectiveStyle();
    if (f.style == settings::kM4 && !m4eye::beginFrame()) f.style = settings::kDragon;  // out of memory
    f.effect = f.style == settings::kM4 ? 3 : f.style == settings::kFire ? 2 : (cfg.flames ? 1 : 0);
    f.smoke = cfg.smoke;
    f.gazeInvert = cfg.gazeInvert;
    f.fireLen = cfg.fireLen;
    if ((f.effect == 1 || f.effect == 2) && !ensureBuffers()) {
      f.style = settings::kDragon;
      f.effect = 0;
    }
    // Fire and the flame overlay share one set of per-eye buffers; reset them
    // when switching between the two so stale heat doesn't flash up.
    for (int e = 0; e < 2; e++) {
      if (f.effect == effect_[e]) continue;
      if (f.effect == 2) fire_eye::reset(fireEye_[e], 0x9E3779B9u + e);
      if (f.effect == 1) flame_overlay::reset(flame_[e], 0x9E3779B9u + e);
      effect_[e] = f.effect;
    }
  }

  static const EyeArt& art(const Frame& f) { return f.style == settings::kDragon ? kDragonEye : kDefaultEye; }  // fire: default lids

  // Advance eye e's animation/simulation for this frame.
  void simulate(int e, const EyeState& st, const Frame& f) {
    const EyeArt& a = art(f);
    const float gx = f.gazeInvert ? -st.gazeX : st.gazeX;
    const bool flip = e == 0 ? EYE_L_LID_FLIP : EYE_R_LID_FLIP;
    const int mood = (int)st.mood;
    if (f.effect == 3) {
      m4eye::simulate(e, st, f.gazeInvert, millis());
    } else if (f.effect == 2) {
      fire_render::Params fp =
          fire_render::compute(a, gx, st.gazeY, st.lid, st.pupil, flip, uTrack_[e], mood, millis(), fireState_[e],
                              f.fireLen);
      fire_eye::step(fireEye_[e], a, fp, mood, f.smoke);
    } else {
      p_[e] = eye_render::compute(a, gx, st.gazeY, st.lid, st.pupil, flip, uTrack_[e]);
      if (f.effect == 1) flame_overlay::step(flame_[e], a, p_[e], mood, f.smoke);
    }
  }

  // Output row oy of eye e as big-endian RGB565. prev: the previous row's
  // output (or nullptr), reused when the plain eye's upscale repeats a row.
  void renderRow(int e, const Frame& f, int oy, uint16_t* row, const uint16_t* prev) {
    const EyeArt& a = art(f);
    if (f.effect == 0 && prev && eye_render::repeatsPrevious(a.lidSize, oy)) {
      memcpy(row, prev, N * 2);  // upscaling repeats every 5th row
      return;
    }
    if (f.effect == 3) {
      m4eye::renderRow(e, oy, row);  // already big-endian
      return;
    }
    if (f.effect == 2) {
      fire_eye::row(fireEye_[e], oy, row);
    } else {
      eye_render::row(a, p_[e], oy, row);
      if (f.effect == 1) flame_overlay::composite(flame_[e], oy, row);
    }
    for (int x = 0; x < N; x++) row[x] = be(row[x]);
  }

  void timedSimulate(int e, const EyeState& st, const Frame& f) {
    const int64_t t0 = esp_timer_get_time();
    simulate(e, st, f);
    prof[e].sim += esp_timer_get_time() - t0;
  }

  // Render chunk k (rows k*kChunkRows..) of eye e into its ring slot.
  uint16_t* renderChunk(int e, const Frame& f, int k) {
    uint16_t* b = buf_[k % kRing];
    for (int i = 0; i < kChunkRows; i++)
      renderRow(e, f, k * kChunkRows + i, b + i * N, i ? b + (i - 1) * N : nullptr);
    return b;
  }

  // Render and stream eye e. Core 1 renders even chunks (all of them without
  // the worker), the worker odd ones; chunk k may be rendered once chunk
  // k - kRing has left its slot, i.e. its DMA is done.
  void streamEye(int e, const Frame& f) {
    const int64_t t0 = esp_timer_get_time();
    int64_t waitUs = 0, renderUs = 0;
    rendered_ = -1;
    dmaDone_ = -1;
    if (worker_) {
      eye_ = e;
      command(kRenderOdd);
    }
    bus_.beginFrame(e, 0, 0, N - 1, N - 1);
    for (int k = 0; k < kChunks; k++) {
      uint16_t* b;
      if (!worker_ || !(k & 1)) {
        // Slot is free: at most two chunks are in flight, so k - 3 is done.
        const int64_t r = esp_timer_get_time();
        b = renderChunk(e, f, k);
        renderUs += esp_timer_get_time() - r;
      } else {
        const int64_t w = esp_timer_get_time();
        while (rendered_ < k) {
        }
        waitUs += esp_timer_get_time() - w;
        b = buf_[k % kRing];
      }
      if (bus_.inFlight() == 2) {
        const int64_t w = esp_timer_get_time();
        bus_.waitOne();
        waitUs += esp_timer_get_time() - w;
        dmaDone_ = k - 2;
      }
      bus_.queuePixels(b, N * kChunkRows);
    }
    const int64_t w = esp_timer_get_time();
    bus_.endFrame();
    waitUs += esp_timer_get_time() - w;
    Prof& pr = prof[e];
    pr.render += renderUs;
    pr.wait += waitUs;
    pr.total += esp_timer_get_time() - t0;
  }

  enum Cmd { kSimRight, kRenderOdd };
  void command(Cmd c) {
    cmd_ = c;
    xTaskNotifyGive(worker_);
  }

  static void workerTask(void* arg) {
    LcdEyes* self = (LcdEyes*)arg;
    for (;;) {
      ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
      if (self->cmd_ == kSimRight) {
        self->timedSimulate(1, self->job_, self->jobFrame_);
        xSemaphoreGive(self->done_);
        continue;
      }
      const int e = self->eye_;
      int64_t renderUs = 0;
      for (int k = 1; k < kChunks; k += 2) {
        while (self->dmaDone_ < k - kRing) {
        }
        const int64_t r = esp_timer_get_time();
        self->renderChunk(e, self->jobFrame_, k);
        renderUs += esp_timer_get_time() - r;
        __sync_synchronize();  // pixels before the flag
        self->rendered_ = k;
      }
      workerProf.render += renderUs;
    }
  }

  // Render worker on core 0 (WiFi and the web server live there too, at the
  // same or higher priority). Without it everything draws on core 1.
  void startWorker() {
    done_ = xSemaphoreCreateBinary();
    if (!done_ || xTaskCreatePinnedToCore(workerTask, "eyes0", 4096, this, 1, &worker_, 0) != pdPASS) {
      Serial.println("lcd: no core-0 render worker, drawing on one core");
      worker_ = nullptr;
    }
  }

  // Effect buffers (3 x 25.6 KB per eye) live in PSRAM, allocated on first
  // use. Fire uses one of the three (its smoke); the flame overlay all three.
  // Internal RAM would make fire ~2 fps faster; it is kept free for WiFi and
  // Bluetooth instead.
  bool ensureBuffers() {
    if (fx_[0]) return true;
    for (int e = 0; e < 2; e++) {
      uint8_t* m = (uint8_t*)heap_caps_malloc(3 * N * N, MALLOC_CAP_SPIRAM);
      if (!m) m = (uint8_t*)heap_caps_malloc(3 * N * N, MALLOC_CAP_8BIT);
      if (!m) {
        Serial.println("eyes: out of memory for fire/flames, falling back to plain eyes");
        settings::setFlames(false);
        settings::setStyleOverride(-1);
        settings::setStyle(settings::kDragon);
        return false;
      }
      fx_[e] = m;
      flame_[e] = {m, m + N * N, m + 2 * N * N, 0, 0};
      fireEye_[e] = {};
      fireEye_[e].smoke = m;
      effect_[e] = 0;
    }
    return true;
  }

  Gc9d01Bus bus_;
  bool started_ = false;
  uint16_t* buf_[kRing] = {};
  uint8_t brightness_ = BL_DEFAULT;
  int uTrack_[2] = {128, 128};
  fire_render::State fireState_[2];
  eye_render::Params p_[2] = {};
  TaskHandle_t worker_ = nullptr;
  SemaphoreHandle_t done_ = nullptr;
  volatile Cmd cmd_ = kSimRight;
  EyeState job_;  // right eye's state, for kSimRight
  Frame jobFrame_ = {};
  volatile int eye_ = 0;          // eye being streamed, for kRenderOdd
  volatile int rendered_ = -1;    // last odd chunk the worker finished
  volatile int dmaDone_ = -1;     // last chunk whose DMA has completed
  uint8_t* fx_[2] = {nullptr, nullptr};
  int effect_[2] = {0, 0};  // 0 none, 1 flame overlay, 2 fire eye
  flame_overlay::Buffers flame_[2] = {};
  fire_eye::Buffers fireEye_[2] = {};
};

// --- `lcd` bench diagnostics ---

LcdEyes* lcd = nullptr;
volatile bool toggling = false;

struct PinName {
  const char* name;
  int left, right;  // right -1 = shares the left eye's wire
};
const PinName kPins[] = {
    {"CLK", PIN_TFT_SCLK, PIN_TFT_SCLK_R}, {"DIN", PIN_TFT_MOSI, PIN_TFT_MOSI_R},
    {"CS", PIN_TFT_CS_L, PIN_TFT_CS_R},    {"DC", PIN_TFT_DC, PIN_TFT_DC_R},
    {"RST", PIN_TFT_RST, PIN_TFT_RST_R},   {"BL", PIN_TFT_BL, PIN_TFT_BL_R},
};

// Name of an LCD pin ("L CLK"), or nullptr if the GPIO isn't one.
const char* lcdPinName(int gpio, char* out, size_t n) {
  for (const PinName& p : kPins) {
    if (p.left == gpio) return snprintf(out, n, "L %s%s", p.name, p.right < 0 ? " (+R)" : ""), out;
    if (p.right == gpio) return snprintf(out, n, "R %s", p.name), out;
  }
  return nullptr;
}

void printClock() {
  Serial.printf("lcd: SPI %.2f MHz requested, %.2f MHz actual, mode 0\n", lcd->bus().clockHz() / 1e6,
                lcd->bus().actualClockHz() / 1e6);
}

void toggleTask(void* arg) {
  const int pin = (int)(intptr_t)arg;
  const bool bl = pin == PIN_TFT_BL || pin == PIN_TFT_BL_R;
  if (bl) ledcDetachPin(pin);
  pinMode(pin, OUTPUT);  // takes the pin off the SPI peripheral / LEDC
  for (int i = 0; i < 20; i++) {
    digitalWrite(pin, i & 1 ? LOW : HIGH);
    vTaskDelay(pdMS_TO_TICKS(500));
  }
  lcd->bus().restorePins();
  lcd->restoreBacklight();
  lcd->reinit();  // RST or CS may have been wiggled
  lcd->testPattern(2);
  Serial.printf("lcd: toggle GPIO%d done, pins restored, panels re-initialised, test pattern up\n", pin);
  toggling = false;
  vTaskDelete(nullptr);
}

void printRotation() {
  for (int e = 0; e < 2; e++) {
    const int r = settings::get().rot[e];
    Serial.printf("lcd: eye %c rot %d (MADCTL 0x%02X)%s\n", e ? 'R' : 'L', r, Gc9d01Bus::madctl(r, TFT_SWAP_RB),
                  r == (e ? EYE_R_ROT : EYE_L_ROT) ? "" : ", config.h default differs");
  }
}

// "L"/"R"/"both" -> eye index (2 = both), -1 if neither.
int eyeArg(const char* a) {
  if (!strcasecmp(a, "L") || !strcmp(a, "0")) return 0;
  if (!strcasecmp(a, "R") || !strcmp(a, "1")) return 1;
  if (!strcasecmp(a, "both") || !strcmp(a, "2")) return 2;
  return -1;
}

// `lcd prof`: average frame-time breakdown since the last call.
void printProf() {
  FrameProf f = frameProf;
  WorkerProf w = workerProf;
  Prof p[2] = {prof[0], prof[1]};
  frameProf = {};
  workerProf = {};
  prof[0] = prof[1] = {};
  if (!f.frames) {
    Serial.println("lcd prof: no frames yet");
    return;
  }
  const float n = f.frames * 1000.0f;  // -> ms per frame
  Serial.printf("lcd prof: %u frames, %.2f ms/frame (%.1f fps drawing)\n", f.frames, f.total / n,
                f.frames * 1e6f / f.total);
  for (int e = 0; e < 2; e++)
    Serial.printf("lcd prof: eye %d: sim %.2f ms (core %d), stream %.2f ms = core-1 render %.2f + waiting %.2f\n", e,
                  p[e].sim / n, e ? 0 : 1, p[e].total / n, p[e].render / n, p[e].wait / n);
  Serial.printf("lcd prof: core 0 renders %.2f ms/frame (odd chunks, both eyes); core 1 waits %.2f ms for its sim\n",
                w.render / n, f.workerWait / n);
}

void cmdLcd(int argc, char** argv) {
  const char* usage =
      "usage: lcd spi <MHz> | init | fill <r> <g> <b> | pins | toggle <gpio> | prof | rot [L|R|both 0|90|180|270] | "
      "madctl <L|R> <hex>  (then 'eyes anim' to resume)";
  if (argc < 2) {
    Serial.println(usage);
    if (lcd && lcd->started()) printClock();
    return;
  }
  String sub = argv[1];
  if (sub == "prof") {
    printProf();
    return;
  }
  if (sub == "pins") {
    Serial.println("lcd pins (GPIO; '=L' means the right eye shares the left eye's wire):");
    Serial.println("        L     R");
    for (const PinName& p : kPins) {
      if (p.right >= 0) Serial.printf("  %-4s  %-4d  %d\n", p.name, p.left, p.right);
      else Serial.printf("  %-4s  %-4d  =L\n", p.name, p.left);
    }
    Serial.println("  CLK/DIN L on the VSPI IO_MUX, R copied through the GPIO matrix; DC/RST R follow L; BL share one LEDC channel");
    printRotation();
    if (lcd && lcd->started()) printClock();
    return;
  }
  if (sub == "rot" && argc < 3) {
    printRotation();
    return;
  }
  if (sub == "rot") {
    // Through the settings, so the web page sees it and `config save` keeps
    // it; the eye task applies it and draws the test pattern.
    long deg;
    const int eye = eyeArg(argv[2]);
    if (eye < 0 || !console::argInt(argc, argv, 3, deg) || deg < 0 || deg > 270 || deg % 90) {
      Serial.println("usage: lcd rot <L|R|both> <0|90|180|270>  (clockwise, as seen from the front)");
      return;
    }
    settings::setRotation(eye, (int)deg);
    eyes::test(2);
    printRotation();
    Serial.println("lcd: test pattern up (bars red/green/blue/white top to bottom, yellow square top-left); "
                   "'config save' keeps the rotation");
    return;
  }
  if (!lcd || !lcd->started() || eyes::backend() != eyes::Backend::Lcd) {
    Serial.println("lcd: LCD backend not running ('eyes lcd' first)");
    return;
  }
  if (toggling) {
    Serial.println("lcd: toggle still running, wait for it to finish");
    return;
  }
  if (sub != "spi" && sub != "init" && sub != "fill" && sub != "toggle" && sub != "madctl") {
    Serial.println(usage);
    return;
  }
  if (!eyes::pause()) {
    Serial.println("lcd: eye task didn't pause, giving up");
    return;
  }

  if (sub == "spi") {
    float mhz;
    if (!console::argFloat(argc, argv, 2, mhz) || mhz < 0.1f || mhz > 80) {
      Serial.println("usage: lcd spi <MHz 0.1..80>, e.g. 1 4 10 27 40");
      return;
    }
    if (!lcd->bus().setClock((uint32_t)(mhz * 1e6f))) {
      Serial.println("lcd: re-adding the SPI device failed");
      return;
    }
    printClock();
    lcd->reinit();
    lcd->testPattern(2);
    Serial.println("lcd: panels re-initialised, test pattern up");
  } else if (sub == "init") {
    lcd->reinit();
    Serial.println("lcd: reset + init sent; white for 1 s, then red");
    lcd->fillBoth(rgb(255, 255, 255));
    delay(1000);
    lcd->fillBoth(rgb(255, 0, 0));
    Serial.println("lcd: red");
  } else if (sub == "fill") {
    long r, g, b;
    if (!console::argInt(argc, argv, 2, r) || !console::argInt(argc, argv, 3, g) ||
        !console::argInt(argc, argv, 4, b)) {
      Serial.println("usage: lcd fill <r> <g> <b>  (0..255 each)");
      return;
    }
    uint16_t c = rgb(constrain(r, 0, 255), constrain(g, 0, 255), constrain(b, 0, 255));
    lcd->fillBoth(c);
    Serial.printf("lcd: filled both with %ld %ld %ld (RGB565 0x%04X)\n", r, g, b, c);
  } else if (sub == "madctl") {
    const int eye = argc > 2 ? eyeArg(argv[2]) : -1;
    char* end = nullptr;
    const long m = argc > 3 ? strtol(argv[3], &end, 16) : -1;
    if (eye < 0 || eye > 1 || !end || *end || m < 0 || m > 0xFF) {
      Serial.println("usage: lcd madctl <L|R> <hex byte>  (raw, until the next 'lcd rot'/'lcd init')");
      return;
    }
    lcd->bus().setMadctl(eye, (uint8_t)m);
    lcd->testPattern(2);
    Serial.printf("lcd: eye %c MADCTL 0x%02lX, test pattern up\n", eye ? 'R' : 'L', m);
  } else {  // toggle
    long pin;
    char name[16];
    if (!console::argInt(argc, argv, 2, pin) || !lcdPinName(pin, name, sizeof name)) {
      Serial.println("usage: lcd toggle <gpio>, one of the LCD pins ('lcd pins')");
      return;
    }
    toggling = true;
    Serial.printf("lcd: toggling GPIO%ld (%s) at 1 Hz for 10 s\n", pin, name);
    if (xTaskCreatePinnedToCore(toggleTask, "lcdtoggle", 4096, (void*)(intptr_t)pin, 1, nullptr, 1) != pdPASS) {
      toggling = false;
      Serial.println("lcd: couldn't start the toggle task");
    }
  }
}

}  // namespace

EyeBackend* makeLcdEyes() {
  static bool registered = false;
  if (!registered) {
    console::add("lcd", "LCD bench diagnostics: lcd spi <MHz> | init | fill r g b | pins | toggle <gpio> | prof | rot | madctl",
                 cmdLcd);
    m4eye::registerCommands();
    registered = true;
  }
  static LcdEyes* instance = new LcdEyes();  // owns the SPI bus; reused across backend switches
  lcd = instance;
  return instance;
}
