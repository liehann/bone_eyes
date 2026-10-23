// Eye animation: a controller that decides where the eyes look and how open
// they are, and swappable backends that draw that state (LCDs or NeoPixels).
#pragma once
#include <Arduino.h>

enum class Mood : uint8_t { Idle, Alert, Talking, Goodbye };

struct EyeState {
  float gazeX = 0;    // -1 (skull's left) .. +1 (skull's right)
  float gazeY = 0;    // -1 (down) .. +1 (up)
  float lid = 0.75f;  // 0 closed .. 1 wide open
  float pupil = 0.5f; // 0 pinpoint .. 1 dilated
  Mood mood = Mood::Idle;
};

class EyeBackend {
 public:
  virtual ~EyeBackend() = default;
  virtual const char* name() const = 0;
  virtual bool begin() = 0;
  virtual void end() {}
  // Draw one frame for both eyes. Called from the eye task only.
  virtual void draw(const EyeState& left, const EyeState& right) = 0;
  // Bench helpers. eye: 0 left, 1 right, 2 both.
  virtual void testPattern(int eye) {}
  virtual void setBrightness(uint8_t level) {}
};

namespace eyes {

enum class Backend : uint8_t { Lcd, Pixel };

// Starts the eye task on core 1 with the given backend.
void begin(Backend backend);
void setBackend(Backend backend);
Backend backend();

// Behaviour hooks. Thread-safe (called from loop()).
void setMood(Mood m);
// Look at a target. x/y in gaze units; distanceCm drives vergence (cross-eyed
// when close). Call repeatedly while tracking; it times out back to idle
// saccades after ~1 s without updates.
void lookAt(float x, float y, int distanceCm = 0);
void blink();
// Hold a fixed pose (bench). nan releases it.
void hold(float x, float y);
void release();

// Stop animating (as `eyes test` does) and wait until the eye task has let go
// of the backend, so the caller can drive the hardware directly. Stays paused
// until `eyes anim`. Returns false if the task didn't park within timeoutMs.
bool pause(uint32_t timeoutMs = 1000);

// Stats for the console.
float fps();

void registerCommands();

}  // namespace eyes
