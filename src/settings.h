// User settings (eye style, effects, backlight, rotation, behaviour toggles),
// kept in NVS so they survive a reboot. Changes apply live; save() persists
// them. The eye task reads get() once per frame. The web page, the `config`
// console command and the older per-setting commands (`art`, `flames`,
// `eyes bl`, `lcd rot`) all go through here.
#pragma once
#include <Arduino.h>

namespace settings {

// Values are stored in NVS: append, never renumber.
enum Style : int32_t {
  kDefault = 0, kDragon = 1, kFire = 2, kM4 = 3,
  // Uncanny Eyes sets on LittleFS (data/uncanny/<name>.eye), kCat..kNauga.
  kCat = 4, kGoat, kOwl, kNewt, kTerminator, kNoSclera, kDoe, kNauga,
};
constexpr int kNumStyles = 12;
// "default", "dragon", "fire", "m4", "cat", "goat", "owl", "newt",
// "terminator", "nosclera", "doe", "nauga"
extern const char* const kStyleNames[kNumStyles];
// Style drawn by the Uncanny Eyes renderer from a LittleFS file (named after
// the style).
inline bool isUncannyFile(int style) { return style >= kCat && style <= kNauga; }
// The M4 eye's own parameters (src/m4eye/m4eye_config.h) ride along as a
// nested "m4" object in toJson()/applyJson(), saved as one NVS string.

struct Settings {
  int32_t style;       // Style
  int32_t flames;      // flames + smoke around the default/dragon eyes
  int32_t smoke;       // smoke from flame tips (fire eye and flame overlay)
  int32_t fireLen;     // fire eye flame length, % of the per-mood length
  int32_t brightness;  // backlight 0..255
  int32_t rot[2];      // picture rotation per eye (L, R), 0/90/180/270
  int32_t gazeInvert;  // mirror gaze left/right
  int32_t autoBlink;   // blink on its own
  int32_t blinkMinMs, blinkMaxMs;  // gap between blinks
  int32_t wander;      // idle saccades; off = look straight ahead
  int32_t verge;       // go cross-eyed when someone is close
  int32_t pupilReact;  // pupils dilate/constrict with the mood
  // Colour of the Uncanny Eyes styles (default, dragon, cat ...): hue
  // rotation (deg), saturation (%) and a multiply tint (0xRRGGBB) for the
  // iris and the sclera textures. Baked into texture copies when they change.
  int32_t irisHue, irisSat, irisTint;
  int32_t scleraHue, scleraSat, scleraTint;
  int32_t jawClosed, jawOpen;  // servo angles (deg) for closed / fully open
  int32_t firePalette;  // eye_tint::Palette, for the fire eye and the flame overlay
};

void begin();  // load from NVS (defaults where unset); call before eyes::begin
void registerCommands();

Settings get();       // live copy, thread-safe
Settings defaults();
// Style to draw: the temporary override (`!a <style>` from the brain) if any,
// else the configured style.
int effectiveStyle();
int styleOverride();        // -1 = none
void setStyleOverride(int style);  // -1 clears

// Apply a partial update. Each setter clamps and applies live. Setting the
// style also clears the override (the user asked for this style).
void setStyle(int style);
void setFlames(bool on);
void setBrightness(int level);
void setRotation(int eye, int deg);  // eye 0 L, 1 R, 2 both

bool save();
void reset();  // defaults live, and the saved copy erased

// JSON for /api/config (and `config`). Returns length written.
size_t toJson(char* out, size_t n);
// Apply a flat JSON object's known keys (unknown ones ignored). Returns the
// number of keys applied; *err gets the first bad key, if any.
int applyJson(const char* json, const char** err);
// One key=value (form fields, `config set`): 1 applied, 0 unknown key, -1 bad value.
int applyKey(const char* key, const char* value);

}  // namespace settings
