#include "jaw.h"

#include "config.h"
#include "console.h"
#include "settings.h"

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
    Serial.println("usage: jaw | jaw <deg> | jaw closed <deg> | jaw open <deg> | jaw save | jaw test");
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
