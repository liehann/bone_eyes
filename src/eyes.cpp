#include "eyes.h"

#include <math.h>

#include "config.h"
#include "console.h"
#include "settings.h"

EyeBackend* makeLcdEyes();    // eyes_lcd.cpp
EyeBackend* makePixelEyes();  // eyes_pixel.cpp

namespace eyes {
namespace {

// Requests from loop() to the eye task, guarded by `mux`.
struct Shared {
  Mood mood = Mood::Idle;
  float targetX = 0, targetY = 0;
  int targetCm = 0;
  uint32_t targetMs = 0;  // last lookAt(); 0 = none
  bool blinkReq = false;
  bool hold = false;
  float holdX = 0, holdY = 0;
  int testReq = -1;          // test pattern request, eye index
  bool animate = true;       // false while showing a test pattern
  Backend pendingBackend = Backend::Lcd;
  bool backendReq = false;
};
Shared shared;
// True while the eye task is idling with no requests pending: it won't touch
// the backend until it next reads `shared`. Written under `mux`.
bool parked = false;
portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;

EyeBackend* active = nullptr;
Backend activeKind = Backend::Lcd;
volatile float measuredFps = 0;

constexpr uint32_t kTrackTimeoutMs = 1000;
constexpr uint32_t kBlinkMs = 160;

float frand(float lo, float hi) { return lo + (hi - lo) * (esp_random() / 4294967295.0f); }

// Critically-damped-ish approach: fraction of the gap closed per frame for a
// given time constant.
float approach(float cur, float target, float dt, float tau) {
  return cur + (target - cur) * (1 - expf(-dt / tau));
}

EyeBackend* create(Backend b) { return b == Backend::Lcd ? makeLcdEyes() : makePixelEyes(); }

void eyeTask(void*) {
  // Animation state lives entirely in this task.
  float gx = 0, gy = 0;          // current gaze
  float sx = 0, sy = 0;          // saccade target
  float lid = 0.75f, pupil = 0.5f;
  float verge = 0;               // inward rotation per eye when close
  uint32_t nextSaccade = 0, nextBlink = millis() + 2000, blinkStart = 0;
  uint32_t last = millis(), fpsT0 = last;
  int frames = 0;
  // Backlight / rotation last sent to the backend; -1 = resend.
  int appliedBl = -1, appliedRot[2] = {-1, -1};
  int lastTest = 2;  // redrawn when the rotation changes during a test

  for (;;) {
    uint32_t now = millis();
    float dt = (now - last) / 1000.0f;
    last = now;

    const settings::Settings cfg = settings::get();
    const bool cfgDirty =
        cfg.brightness != appliedBl || cfg.rot[0] != appliedRot[0] || cfg.rot[1] != appliedRot[1];
    Shared s;
    portENTER_CRITICAL(&mux);
    s = shared;
    parked = !s.animate && s.testReq < 0 && !cfgDirty && !s.backendReq;
    shared.blinkReq = false;
    shared.testReq = -1;
    shared.backendReq = false;
    portEXIT_CRITICAL(&mux);

    if (s.backendReq && (!active || s.pendingBackend != activeKind)) {
      if (active) active->end();  // backends are singletons, never deleted
      activeKind = s.pendingBackend;
      active = create(activeKind);
      if (!active->begin()) Serial.printf("eyes: backend %s failed to start\n", active->name());
      appliedBl = appliedRot[0] = appliedRot[1] = -1;
    }
    if (!active) {
      vTaskDelay(100);
      continue;
    }
    if (cfg.brightness != appliedBl) active->setBrightness(appliedBl = cfg.brightness);
    bool rotChanged = false;
    for (int e = 0; e < 2; e++) {
      if (cfg.rot[e] == appliedRot[e]) continue;
      active->setRotation(e, appliedRot[e] = cfg.rot[e]);
      rotChanged = true;
    }
    if (s.testReq >= 0) active->testPattern(lastTest = s.testReq);
    else if (rotChanged && !s.animate) active->testPattern(lastTest);
    if (!s.animate) {
      vTaskDelay(50);
      continue;
    }

    // --- gaze ---
    bool tracking = s.targetMs && now - s.targetMs < kTrackTimeoutMs;
    float tx, ty, tau;
    if (s.hold) {
      tx = s.holdX, ty = s.holdY, tau = 0.05f;
    } else if (tracking) {
      tx = s.targetX, ty = s.targetY, tau = 0.08f;
    } else {
      if ((int32_t)(now - nextSaccade) >= 0) {
        // Mostly small hops near centre, occasionally a big look around.
        float r = frand(0, 1) < 0.2f ? 0.9f : 0.45f;
        sx = frand(-r, r);
        sy = frand(-r, r) * 0.6f;
        nextSaccade = now + (uint32_t)frand(400, s.mood == Mood::Idle ? 3000 : 1200);
      }
      if (!cfg.wander) sx = sy = 0;  // look straight ahead
      tx = sx, ty = sy, tau = 0.03f;  // saccades are fast
    }
    gx = approach(gx, tx, dt, tau);
    gy = approach(gy, ty, dt, tau);
    float wantVerge = (cfg.verge && tracking && s.targetCm > 0) ? constrain(30.0f / s.targetCm, 0.0f, 0.25f) : 0;
    verge = approach(verge, wantVerge, dt, 0.2f);

    // --- lids / pupil by mood ---
    float wantLid = 0.75f, wantPupil = 0.5f;
    switch (s.mood) {
      case Mood::Idle: wantLid = 0.72f; wantPupil = 0.45f; break;
      case Mood::Alert: wantLid = 1.0f; wantPupil = 0.85f; break;
      case Mood::Talking: wantLid = 0.9f; wantPupil = 0.7f; break;
      case Mood::Goodbye: wantLid = 0.45f; wantPupil = 0.3f; break;
    }
    if (!cfg.pupilReact) wantPupil = 0.5f;
    lid = approach(lid, wantLid, dt, 0.15f);
    pupil = approach(pupil, wantPupil, dt, 0.3f);

    // --- blink ---
    if (s.blinkReq || (cfg.autoBlink && (int32_t)(now - nextBlink) >= 0)) {
      blinkStart = now;
      nextBlink = now + (uint32_t)frand(cfg.blinkMinMs, cfg.blinkMaxMs);
    }
    float blinkLid = lid;
    if (blinkStart && now - blinkStart < kBlinkMs) {
      float p = (now - blinkStart) / (float)kBlinkMs;  // 0..1, closed at 0.5
      blinkLid = lid * fabsf(1 - 2 * p);
    }

    EyeState l, r;
    l.gazeY = r.gazeY = gy;
    l.gazeX = constrain(gx + verge, -1.0f, 1.0f);  // left eye turns right (inward) when close
    r.gazeX = constrain(gx - verge, -1.0f, 1.0f);
    l.lid = r.lid = blinkLid;
    l.pupil = r.pupil = pupil;
    l.mood = r.mood = s.mood;
    active->draw(l, r);

    frames++;
    if (now - fpsT0 >= 1000) {
      measuredFps = frames * 1000.0f / (now - fpsT0);
      frames = 0;
      fpsT0 = now;
    }
    vTaskDelay(1);  // let the idle task feed the watchdog
  }
}

template <typename F>
void withShared(F f) {
  portENTER_CRITICAL(&mux);
  f(shared);
  portEXIT_CRITICAL(&mux);
}

// --- console ---

void cmdEyes(int argc, char** argv) {
  if (argc < 2) {
    Shared s;
    withShared([&](Shared& sh) { s = sh; });
    Serial.printf("eyes: backend %s, mood %s, %s, %.1f fps%s\n", active ? active->name() : "none",
                  moodName(s.mood), s.animate ? "animating" : "test pattern", measuredFps,
                  s.hold ? " (held)" : "");
    return;
  }
  String sub = argv[1];
  if (sub == "test") {
    long eye = 2;
    console::argInt(argc, argv, 2, eye);
    test((int)eye);
  } else if (sub == "anim") {
    animate();
  } else if (sub == "blink") {
    blink();
  } else if (sub == "look") {
    float x, y;
    if (console::argFloat(argc, argv, 2, x) && console::argFloat(argc, argv, 3, y)) hold(x, y);
    else Serial.println("usage: eyes look <x -1..1> <y -1..1>");
  } else if (sub == "free") {
    release();
  } else if (sub == "mood") {
    Mood m;
    if (argc > 2 && parseMood(argv[2], m)) return setMood(m);
    Serial.println("usage: eyes mood idle|alert|talking|goodbye");
  } else if (sub == "bl") {
    long v;
    if (console::argInt(argc, argv, 2, v)) settings::setBrightness((int)v);
    else Serial.printf("eyes: backlight %d ('config save' keeps it)\n", (int)settings::get().brightness);
  } else if (sub == "lcd" || sub == "pixel") {
    setBackend(sub == "lcd" ? Backend::Lcd : Backend::Pixel);
  } else {
    Serial.println("usage: eyes [test [0|1|2] | anim | blink | look x y | free | mood m | bl 0-255 | lcd | pixel]");
  }
}

}  // namespace

const char* moodName(Mood m) {
  switch (m) {
    case Mood::Idle: return "idle";
    case Mood::Alert: return "alert";
    case Mood::Talking: return "talking";
    case Mood::Goodbye: return "goodbye";
  }
  return "?";
}

bool parseMood(const char* name, Mood& out) {
  for (int i = 0; i < 4; i++)
    if (strcmp(name, moodName((Mood)i)) == 0) return out = (Mood)i, true;
  return false;
}

Mood mood() {
  Mood m;
  withShared([&](Shared& sh) { m = sh.mood; });
  return m;
}

void test(int eye) {
  withShared([&](Shared& sh) { sh.animate = false; sh.testReq = eye < 0 || eye > 2 ? 2 : eye; });
}

void animate() {
  withShared([](Shared& sh) { sh.animate = true; });
}

void begin(Backend b) {
  withShared([&](Shared& sh) { sh.pendingBackend = b; sh.backendReq = true; });
  // Core 1 (Arduino loop core); Bluetooth lives on core 0. The LCD backend
  // adds a render worker on core 0 (eyes_lcd.cpp).
  xTaskCreatePinnedToCore(eyeTask, "eyes", 6144, nullptr, 1, nullptr, 1);
}

void setBackend(Backend b) {
  withShared([&](Shared& sh) { sh.pendingBackend = b; sh.backendReq = true; sh.animate = true; });
}

Backend backend() { return activeKind; }

void setMood(Mood m) {
  withShared([&](Shared& sh) { sh.mood = m; });
}

void lookAt(float x, float y, int distanceCm) {
  uint32_t now = millis();
  withShared([&](Shared& sh) {
    sh.targetX = constrain(x, -1.0f, 1.0f);
    sh.targetY = constrain(y, -1.0f, 1.0f);
    sh.targetCm = distanceCm;
    sh.targetMs = now ? now : 1;
  });
}

void blink() {
  withShared([](Shared& sh) { sh.blinkReq = true; });
}

void hold(float x, float y) {
  withShared([&](Shared& sh) { sh.hold = true; sh.holdX = x; sh.holdY = y; sh.animate = true; });
}

void release() {
  withShared([](Shared& sh) { sh.hold = false; });
}

bool pause(uint32_t timeoutMs) {
  // Clear `parked` with the request so a stale value from an earlier pause
  // can't be read before the task has seen animate == false.
  withShared([](Shared& sh) { sh.animate = false; parked = false; });
  uint32_t t0 = millis();
  for (;;) {
    bool p;
    portENTER_CRITICAL(&mux);
    p = parked;
    portEXIT_CRITICAL(&mux);
    if (p) return true;
    if (millis() - t0 > timeoutMs) return false;
    delay(5);
  }
}

float fps() { return measuredFps; }

void registerCommands() {
  console::add("eyes", "eye state / test / anim / look / mood / bl / lcd|pixel", cmdEyes);
}

}  // namespace eyes
