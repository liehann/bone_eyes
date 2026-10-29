// Runtime parameters of the M4 eye, and their JSON form. Self-contained (no
// JSON library); hardware-independent so host tools can use it too.
//
// Integration hook for the web page / NVS: keep a JSON string, apply it with
// m4eye::applyJson() (m4eye.h), read the live one back with m4eye::getJson().
// Keys are the field names below; unknown keys are ignored, missing keys keep
// their current value, so a partial object is a patch.
#pragma once
#include <stddef.h>
#include <stdint.h>

namespace m4eye {

struct Rgb {
  uint8_t r, g, b;
  bool operator==(const Rgb& o) const { return r == o.r && g == o.g && b == o.b; }
  bool operator!=(const Rgb& o) const { return !(*this == o); }
};

struct Config {
  char eye[32] = "hazel";  // eye set (compiled-in in Phase 1)
  char lids[32] = "";      // lid set: "" = the eye's own, "none" = no lids, or a set name (`m4 list`)

  // Geometry, in 160 px panel pixels. Changing any of these rebuilds the
  // polar tables (~0.1-0.3 s pause).
  int eyeRadius = 83;
  int irisRadius = 40;       // "iris size"
  int slitPupilRadius = 0;   // 0 = round pupil, else slit (<= irisRadius)
  float coverage = 0.6f;     // how far the sclera map wraps round the ball

  // Colour. Tints multiply the texture (255,255,255 = unchanged); changing
  // one re-tints the texture copy in RAM.
  Rgb irisTint = {255, 255, 255};
  Rgb scleraTint = {255, 255, 255};
  Rgb irisColor = {0, 0, 0};    // used when the eye set has no iris texture
  Rgb scleraColor = {0, 0, 0};  // used when it has no sclera texture
  Rgb pupilColor = {0, 0, 0};
  Rgb backColor = {140, 40, 20};  // back of the eyeball (seen at extreme gaze)
  Rgb eyelidColor = {0, 0, 0};

  // Pupil (fraction of the iris radius): the animator's pupil 0..1 maps
  // onto pupilMin..pupilMax.
  float pupilMin = 0.2f, pupilMax = 0.55f;

  // Lids / motion.
  bool tracking = true;  // upper lid follows the pupil
  float squint = 0.5f;
  bool lidMirror = false;  // swap which eye gets the mirrored lid art
  float blinkRate = 0;     // extra M4-style blinks per minute (0 = only the animator's 2-6 s blinks)
  float gazeRange = 0.75f; // eye-tracking range, 0..1 of the travel the map allows (M4 saccades: 0.75)

  // Texture motion, per eye (index 0 = L, the skull's left; 1 = R). JSON:
  // "irisSpin" sets both, "irisSpinL"/"irisSpinR" or M4's nested
  // "left": {...} / "right": {...} objects set one.
  float irisSpin[2] = {0, 0};  // RPM
  float scleraSpin = 0;        // RPM, both eyes
  bool irisMirror[2] = {false, false};
  int irisAngle = 0, scleraAngle = 0;  // 0..1023
};

// Which parts of the engine a change touches.
enum Dirty : uint32_t {
  kDirtyNone = 0,
  kDirtyLook = 1,      // per-frame values only
  kDirtyColors = 2,    // flat colours / tints: re-tint textures
  kDirtyTables = 4,    // geometry: rebuild polar tables
  kDirtyAssets = 8,    // eye set or lid set changed: reload
};
uint32_t diff(const Config& a, const Config& b);

// Parse `json` (an object, // and /* */ comments allowed, like config.eye)
// onto `c`. Returns false with a message in err on a syntax error; c is then
// unchanged. Accepts M4_Eyes config.eye keys too (irisTexture etc. ignored).
bool fromJson(const char* json, Config& c, char* err = nullptr, size_t errLen = 0);
// Write `c` as one JSON object. Returns the length (snprintf semantics).
int toJson(const Config& c, char* out, size_t len);

}  // namespace m4eye
