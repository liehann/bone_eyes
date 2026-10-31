#include "jaw.h"

#include "config.h"
#include "console.h"
#include "settings.h"

#include <driver/gpio.h>
#include <esp_timer.h>
#include <soc/gpio_reg.h>
#include <soc/gpio_sig_map.h>
#include <soc/io_mux_reg.h>

namespace jaw {
namespace {

constexpr uint8_t kChannel = 0;  // backlight is channel 7 (timer 3); this one uses timer 0
constexpr int kFreq = 50;
constexpr int kBits = 14;
// Slew limit: the ~18 deg of safe travel takes at least ~80 ms.
constexpr float kMaxDegPerSec = 225.0f;
constexpr uint32_t kTickMs = 5;

portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;
float target = JAW_CLOSED_DEG;  // where we want to be
volatile float pos = JAW_CLOSED_DEG;  // slewed position actually written

float clampDeg(float d) { return d < 0 ? 0 : d > 180 ? 180 : d; }

void write(float deg) {
  const float us = SERVO_MIN_US + (SERVO_MAX_US - SERVO_MIN_US) * clampDeg(deg) / 180.0f;
  ledcWrite(kChannel, (uint32_t)(us * (1 << kBits) / (1000000.0f / kFreq)));
}

void task(void*) {
  uint32_t last = millis();
  for (;;) {
    vTaskDelay(pdMS_TO_TICKS(kTickMs));
    const uint32_t now = millis();
    const float step = kMaxDegPerSec * (now - last) / 1000.0f;
    last = now;
    portENTER_CRITICAL(&mux);
    const float t = target;
    portEXIT_CRITICAL(&mux);
    float p = pos;
    if (p < t) p = min(p + step, t);
    else if (p > t) p = max(p - step, t);
    pos = p;
    write(p);
  }
}

void setTarget(float d) {
  portENTER_CRITICAL(&mux);
  target = clampDeg(d);
  portEXIT_CRITICAL(&mux);
}

// Reads the pad back: enables the input buffer (FUN_IE) without touching the output matrix,
// then samples GPIO_IN for ~130 ms and measures high time and period from the edges.
void diag() {
  const int pin = PIN_SERVO;
  const uint32_t sel = REG_READ(GPIO_FUNC0_OUT_SEL_CFG_REG + 4 * pin);
  Serial.printf("jaw diag: GPIO%d matrix out sel=%u (LEDC ch0 high-speed sig = %d), oen_sel=%u\n", pin,
                (unsigned)(sel & 0xFF), LEDC_HS_SIG_OUT0_IDX, (unsigned)((sel >> 10) & 1));
  Serial.printf("jaw diag: LEDC ch%u duty=%lu (of %d) freq=%lu Hz, our pos=%.1f deg\n", kChannel,
                (unsigned long)ledcRead(kChannel), 1 << kBits, (unsigned long)ledcReadFreq(kChannel), (float)pos);
  REG_SET_BIT(GPIO_PIN_MUX_REG[pin], FUN_IE);
  int64_t rise[16], fall[16];
  int nr = 0, nf = 0, highs = 0, samples = 0;
  const int64_t t0 = esp_timer_get_time();
  int prev = gpio_get_level((gpio_num_t)pin);
  while (esp_timer_get_time() - t0 < 130000) {
    const int v = gpio_get_level((gpio_num_t)pin);
    const int64_t now = esp_timer_get_time();
    samples++;
    highs += v;
    if (v && !prev && nr < 16) rise[nr++] = now;
    if (!v && prev && nf < 16) fall[nf++] = now;
    prev = v;
  }
  Serial.printf("jaw diag: %d samples, %d high (%.1f%%), %d rising, %d falling edges\n", samples, highs,
                100.0f * highs / samples, nr, nf);
  if (nr >= 2) Serial.printf("jaw diag: period %.2f ms\n", (rise[nr - 1] - rise[0]) / 1000.0f / (nr - 1));
  if (nr >= 1) {
    for (int i = 0; i < nf; i++)
      if (fall[i] > rise[0]) {
        Serial.printf("jaw diag: high time %.3f ms\n", (fall[i] - rise[0]) / 1000.0f);
        break;
      }
  }
  if (nr == 0) Serial.printf("jaw diag: NO PULSES on the pad (level stuck %s)\n", prev ? "high" : "low");
}

void printSettings() {
  const settings::Settings s = settings::get();
  Serial.printf("jaw: closed %ld deg, open %ld deg (travel %ld deg), now %.1f deg; 'jaw save' keeps them\n",
                (long)s.jawClosed, (long)s.jawOpen, (long)(s.jawOpen - s.jawClosed), (float)pos);
}

void cmdJaw(int argc, char** argv) {
  if (argc < 2) return printSettings();
  long v;
  if (!strcmp(argv[1], "save")) {
    Serial.println(settings::save() ? "jaw: saved (with the other settings)" : "jaw: save failed");
  } else if (!strcmp(argv[1], "diag")) {
    diag();
  } else if (!strcmp(argv[1], "test")) {
    test();
  } else if (!strcmp(argv[1], "closed") || !strcmp(argv[1], "open")) {
    if (!console::argInt(argc, argv, 2, v) || v < 0 || v > 180) {
      Serial.println("usage: jaw closed|open <0-180>");
      return;
    }
    settings::applyKey(argv[1][0] == 'c' ? "jaw_closed" : "jaw_open", argv[2]);
    setTarget(v);  // move there so you can see it
    printSettings();
  } else if (console::argInt(argc, argv, 1, v)) {
    if (v < 0 || v > 180) {
      Serial.println("jaw: angle 0-180");
      return;
    }
    setTarget(v);
    Serial.printf("jaw: raw angle %ld (not limited to closed/open; configured closed %ld, open %ld)\n", v,
                  (long)settings::get().jawClosed, (long)settings::get().jawOpen);
  } else {
    Serial.println("usage: jaw | jaw <deg> | jaw closed <deg> | jaw open <deg> | jaw save | jaw test | jaw diag");
  }
}

// Brain link: !j <0-1000>. Silent (30 fps).
void cmdBrainJaw(int argc, char** argv) {
  long v;
  if (console::argInt(argc, argv, 1, v)) setOpening((int)v);
}

}  // namespace

void begin() {
  ledcSetup(kChannel, kFreq, kBits);
  ledcAttachPin(PIN_SERVO, kChannel);
  const float c = settings::get().jawClosed;
  pos = target = c;  // boot at closed (no slew from an unknown start)
  write(c);
  xTaskCreatePinnedToCore(task, "jaw", 2048, nullptr, 2, nullptr, 0);
}

void setOpening(int pm) {
  pm = pm < 0 ? 0 : pm > 1000 ? 1000 : pm;
  const settings::Settings s = settings::get();
  setTarget(s.jawClosed + (s.jawOpen - s.jawClosed) * (pm / 1000.0f));
}

void setRawAngle(float deg) { setTarget(deg); }

float angle() { return pos; }

void test() {
  const settings::Settings s = settings::get();
  Serial.printf("jaw: test %ld -> %ld -> %ld, 3 times\n", (long)s.jawClosed, (long)s.jawOpen, (long)s.jawClosed);
  for (int i = 0; i < 3; i++) {
    setOpening(1000);
    delay(500);
    setOpening(0);
    delay(500);
  }
}

void registerCommands() {
  console::add("jaw", "jaw servo: jaw | <deg> | closed <deg> | open <deg> | save | test", cmdJaw);
  console::add("!j", "brain link: !j <0-1000> jaw opening", cmdBrainJaw);
}

}  // namespace jaw
