#include "settings.h"

#include <Preferences.h>
#include <stddef.h>

#include "config.h"
#include "console.h"
#include "eye_art/eye_tint.h"
#include "m4eye/m4eye.h"

namespace settings {

const char* const kStyleNames[kNumStyles] = {"default", "dragon", "fire",       "m4",       "cat", "goat",
                                             "owl",     "newt",   "terminator", "nosclera", "doe", "nauga"};

namespace {

// kColor: 0xRRGGBB, "#rrggbb" in JSON. kPalette: a fire palette name.
enum Kind : uint8_t { kBool, kInt, kStyleKind, kRot, kColor, kPalette };

// One row per setting: JSON / NVS / console key, kind, range, member.
struct Field {
  const char* key;
  Kind kind;
  int32_t lo, hi;
  size_t off;
};
#define FIELD(key, kind, lo, hi, member) {key, kind, lo, hi, offsetof(Settings, member)}
const Field kFields[] = {
    FIELD("style", kStyleKind, 0, kNumStyles - 1, style),
    FIELD("flames", kBool, 0, 1, flames),
    FIELD("smoke", kBool, 0, 1, smoke),
    FIELD("fire_len", kInt, 50, 150, fireLen),
    FIELD("brightness", kInt, 0, 255, brightness),
    FIELD("rot_l", kRot, 0, 270, rot[0]),
    FIELD("rot_r", kRot, 0, 270, rot[1]),
    FIELD("gaze_invert", kBool, 0, 1, gazeInvert),
    FIELD("blink", kBool, 0, 1, autoBlink),
    FIELD("blink_min_ms", kInt, 500, 20000, blinkMinMs),
    FIELD("blink_max_ms", kInt, 500, 20000, blinkMaxMs),
    FIELD("wander", kBool, 0, 1, wander),
    FIELD("verge", kBool, 0, 1, verge),
    FIELD("pupil_react", kBool, 0, 1, pupilReact),
    FIELD("iris_hue", kInt, -180, 180, irisHue),
    FIELD("iris_sat", kInt, 0, 200, irisSat),
    FIELD("iris_tint", kColor, 0, 0xFFFFFF, irisTint),
    FIELD("sclera_hue", kInt, -180, 180, scleraHue),
    FIELD("sclera_sat", kInt, 0, 200, scleraSat),
    FIELD("sclera_tint", kColor, 0, 0xFFFFFF, scleraTint),
    FIELD("fire_palette", kPalette, 0, eye_tint::kNumPalettes - 1, firePalette),
};
#undef FIELD

Settings cur;
int override_ = -1;
portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;
Preferences prefs;
constexpr const char* kNs = "settings";

int32_t& member(Settings& s, const Field& f) { return *(int32_t*)((uint8_t*)&s + f.off); }
int32_t member(const Settings& s, const Field& f) { return *(const int32_t*)((const uint8_t*)&s + f.off); }

int32_t clampField(const Field& f, int32_t v) {
  if (f.kind == kRot) v = ((v % 360 + 360) % 360) / 90 * 90;
  return v < f.lo ? f.lo : v > f.hi ? f.hi : v;
}

int styleIndex(const char* s) {
  for (int i = 0; i < kNumStyles; i++)
    if (strcasecmp(s, kStyleNames[i]) == 0) return i;
  if (strcasecmp(s, "hazel") == 0 || strcasecmp(s, "regular") == 0) return kDefault;
  return -1;
}

void setField(const Field& f, int32_t v) {
  v = clampField(f, v);
  portENTER_CRITICAL(&mux);
  member(cur, f) = v;
  if (f.kind == kStyleKind) override_ = -1;
  if (cur.blinkMaxMs < cur.blinkMinMs) {  // keep the range ordered
    if (f.off == offsetof(Settings, blinkMinMs)) cur.blinkMaxMs = cur.blinkMinMs;
    else cur.blinkMinMs = cur.blinkMaxMs;
  }
  portEXIT_CRITICAL(&mux);
}

const Field* find(const char* key) {
  for (const Field& f : kFields)
    if (strcmp(f.key, key) == 0) return &f;
  return nullptr;
}

// Parse a console / JSON value for field f: numbers, true/false/on/off,
// style names.
bool parseValue(const Field& f, const char* s, size_t n, int32_t& out) {
  char buf[16];
  if (n >= sizeof buf) return false;
  memcpy(buf, s, n);
  buf[n] = 0;
  if (f.kind == kStyleKind) {
    int i = styleIndex(buf);
    if (i >= 0) return out = i, true;
  }
  if (f.kind == kPalette)
    for (int i = 0; i < eye_tint::kNumPalettes; i++)
      if (!strcasecmp(buf, eye_tint::kPaletteNames[i])) return out = i, true;
  if (f.kind == kColor) {  // #rrggbb, rrggbb or 0xrrggbb
    const char* h = buf[0] == '#' ? buf + 1 : (buf[0] == '0' && (buf[1] == 'x' || buf[1] == 'X')) ? buf + 2 : buf;
    char* end;
    const long v = strtol(h, &end, 16);
    if (end - h != 6 || *end) return false;
    out = (int32_t)v;
    return true;
  }
  if (!strcasecmp(buf, "true") || !strcasecmp(buf, "on")) return out = 1, true;
  if (!strcasecmp(buf, "false") || !strcasecmp(buf, "off")) return out = 0, true;
  char* end;
  long v = strtol(buf, &end, 10);
  if (end == buf || *end) return false;
  out = (int32_t)v;
  return true;
}

void print() {
  char* buf = (char*)malloc(2048);
  if (!buf) return;
  toJson(buf, 2048);
  Serial.println(buf);
  free(buf);
}

// --- console ---

void cmdConfig(int argc, char** argv) {
  const char* usage = "usage: config [show | save | reset | set <key> <value> | keys]";
  if (argc < 2 || !strcmp(argv[1], "show")) {
    print();
  } else if (!strcmp(argv[1], "save")) {
    Serial.println(save() ? "config: saved" : "config: save failed");
  } else if (!strcmp(argv[1], "reset")) {
    reset();
    Serial.println("config: defaults restored and saved");
    print();
  } else if (!strcmp(argv[1], "keys")) {
    for (const Field& f : kFields)
      Serial.printf("  %-13s %s\n", f.key,
                    f.kind == kBool        ? "on|off"
                    : f.kind == kStyleKind ? "default|dragon|fire|m4|cat|goat|owl|newt|terminator|nosclera|doe|nauga"
                    : f.kind == kRot       ? "0|90|180|270"
                    : f.kind == kColor     ? "#rrggbb (multiply; #ffffff = none)"
                    : f.kind == kPalette   ? "orange|red|blue|green|purple|white"
                                           : "number");
    Serial.println("  m4            {json}  (M4 eye parameters; 'm4 show' / 'm4 <key> <value>')");
  } else if (!strcmp(argv[1], "set") && argc > 3) {
    const Field* f = find(argv[2]);
    int32_t v;
    if (!f || !parseValue(*f, argv[3], strlen(argv[3]), v)) {
      Serial.println("config: unknown key or bad value ('config keys' lists them)");
      return;
    }
    setField(*f, v);
    print();
  } else {
    Serial.println(usage);
  }
}

void cmdArt(int argc, char** argv) {
  if (argc > 1) {
    const int i = styleIndex(argv[1]);
    if (i >= 0) return setStyle(i);
  }
  const Settings s = get();
  Serial.printf("art: %s%s%s (options: default dragon fire m4 cat goat owl newt terminator nosclera doe nauga; "
                "'config save' keeps it)\n",
                kStyleNames[s.style],
                override_ >= 0 ? ", brain override " : "", override_ >= 0 ? kStyleNames[override_] : "");
}

void cmdFlames(int argc, char** argv) {
  if (argc > 1) setFlames(!strcmp(argv[1], "on"));
  Serial.printf("flames: %s\n", get().flames ? "on" : "off");
}

// Brain link: `!a <style>` overrides the style until `!a` alone (or reboot).
void cmdBrainArt(int argc, char** argv) {
  if (argc < 2) return setStyleOverride(-1);
  const int i = styleIndex(argv[1]);
  if (i >= 0) setStyleOverride(i);
}

}  // namespace

int applyKey(const char* key, const char* value) {
  const Field* f = find(key);
  int32_t v;
  if (!f) return 0;
  if (!parseValue(*f, value, strlen(value), v)) return -1;
  setField(*f, v);
  return 1;
}

Settings defaults() {
  Settings d;
  d.style = styleIndex(EYE_ART_DEFAULT);
  if (d.style < 0) d.style = kFire;
  d.flames = EYE_FLAMES_DEFAULT;
  d.smoke = EYE_SMOKE_DEFAULT;
  d.fireLen = 100;
  d.brightness = BL_DEFAULT;
  d.rot[0] = EYE_L_ROT;
  d.rot[1] = EYE_R_ROT;
  d.gazeInvert = EYE_GAZE_X_INVERT;
  d.autoBlink = true;
  d.blinkMinMs = EYE_BLINK_MIN_MS;
  d.blinkMaxMs = EYE_BLINK_MAX_MS;
  d.wander = true;
  d.verge = true;
  d.pupilReact = true;
  d.irisHue = d.scleraHue = 0;
  d.irisSat = d.scleraSat = 100;
  d.irisTint = d.scleraTint = 0xFFFFFF;
  d.firePalette = eye_tint::kOrange;
  return d;
}

void begin() {
  Settings s = defaults();
  if (prefs.begin(kNs, true)) {  // read-only; fails (harmlessly) until the first save
    for (const Field& f : kFields) member(s, f) = clampField(f, prefs.getInt(f.key, member(s, f)));
    if (prefs.isKey("m4")) m4eye::applyJson(prefs.getString("m4", "").c_str());
    prefs.end();
  }
  portENTER_CRITICAL(&mux);
  cur = s;
  portEXIT_CRITICAL(&mux);
}

Settings get() {
  portENTER_CRITICAL(&mux);
  Settings s = cur;
  portEXIT_CRITICAL(&mux);
  return s;
}

int effectiveStyle() {
  portENTER_CRITICAL(&mux);
  int s = override_ >= 0 ? override_ : cur.style;
  portEXIT_CRITICAL(&mux);
  return s;
}

int styleOverride() { return override_; }

void setStyleOverride(int style) {
  portENTER_CRITICAL(&mux);
  override_ = style >= 0 && style < kNumStyles ? style : -1;
  portEXIT_CRITICAL(&mux);
}

void setStyle(int style) { setField(*find("style"), style); }
void setFlames(bool on) { setField(*find("flames"), on); }
void setBrightness(int level) { setField(*find("brightness"), level); }
void setRotation(int eye, int deg) {
  if (eye != 1) setField(*find("rot_l"), deg);
  if (eye != 0) setField(*find("rot_r"), deg);
}

bool save() {
  const Settings s = get();
  if (!prefs.begin(kNs, false)) return false;
  bool ok = true;
  for (const Field& f : kFields)
    if (prefs.getInt(f.key, INT32_MIN) != member(s, f)) ok &= prefs.putInt(f.key, member(s, f)) == 4;
  constexpr int kM4Max = 1024;
  char* m4 = (char*)malloc(kM4Max);
  const int n = m4 ? m4eye::getJson(m4, kM4Max) : -1;
  if (n > 0 && n < kM4Max && (!prefs.isKey("m4") || prefs.getString("m4", "") != m4))
    ok &= prefs.putString("m4", m4) == (size_t)n;
  free(m4);
  prefs.end();
  return ok;
}

void reset() {
  if (prefs.begin(kNs, false)) {
    prefs.clear();
    prefs.end();
  }
  portENTER_CRITICAL(&mux);
  cur = defaults();
  override_ = -1;
  portEXIT_CRITICAL(&mux);
  m4eye::setConfig(m4eye::defaultsFor("hazel"));
}

size_t toJson(char* out, size_t n) {
  const Settings s = get();
  const int ov = override_;
  size_t len = snprintf(out, n, "{");
  for (const Field& f : kFields) {
    if (len >= n) break;
    const int32_t v = member(s, f);
    if (f.kind == kStyleKind) len += snprintf(out + len, n - len, "\"%s\":\"%s\",", f.key, kStyleNames[v]);
    else if (f.kind == kBool) len += snprintf(out + len, n - len, "\"%s\":%s,", f.key, v ? "true" : "false");
    else if (f.kind == kColor) len += snprintf(out + len, n - len, "\"%s\":\"#%06x\",", f.key, (unsigned)v);
    else if (f.kind == kPalette)
      len += snprintf(out + len, n - len, "\"%s\":\"%s\",", f.key, eye_tint::kPaletteNames[v]);
    else len += snprintf(out + len, n - len, "\"%s\":%d,", f.key, v);
  }
  if (len < n) {
    len += snprintf(out + len, n - len, "\"m4\":");
    if (len < n) len += m4eye::getJson(out + len, n - len);
    // Read-only: the eye/lid sets the m4 pickers offer.
    if (len < n) len += snprintf(out + len, n - len, ",\"m4_sets\":");
    if (len < n) len += m4eye::listJson(out + len, n - len);
    if (len < n) len += snprintf(out + len, n - len, ",");
  }
  if (len < n) {
    if (ov >= 0) len += snprintf(out + len, n - len, "\"style_override\":\"%s\"}", kStyleNames[ov]);
    else len += snprintf(out + len, n - len, "\"style_override\":null}");
  }
  return len < n ? len : n - 1;
}

// The value of a nested "m4": {...} object, as [begin, end) of json.
bool m4Object(const char* json, const char** b, const char** e) {
  for (const char* p = strstr(json, "\"m4\""); p; p = strstr(p + 1, "\"m4\"")) {
    const char* v = p + 4;
    while (*v == ' ' || *v == '\t' || *v == '\n' || *v == '\r') v++;
    if (*v++ != ':') continue;
    while (*v == ' ' || *v == '\t' || *v == '\n' || *v == '\r') v++;
    if (*v != '{') return false;
    int depth = 0;
    bool str = false;
    for (const char* q = v; *q; q++) {
      if (str) {
        if (*q == '\\' && q[1]) q++;
        else if (*q == '"') str = false;
      } else if (*q == '"') {
        str = true;
      } else if (*q == '{') {
        depth++;
      } else if (*q == '}' && --depth == 0) {
        *b = v;
        *e = q + 1;
        return true;
      }
    }
    return false;
  }
  return false;
}

int applyJson(const char* json, const char** err) {
  int applied = 0;
  if (err) *err = nullptr;
  // The nested M4 object first, and blank it out of the flat-key scan below
  // (its "irisRadius" etc. aren't top-level keys, but "blink"-like names
  // could collide).
  const char *mb, *me;
  String flat = json;
  if (m4Object(json, &mb, &me)) {
    String obj = flat.substring(mb - json, me - json);
    if (m4eye::applyJson(obj.c_str())) applied++;
    else if (err) *err = "m4";
    for (size_t i = mb - json; i < (size_t)(me - json); i++) flat[i] = ' ';
    json = flat.c_str();
  }
  for (const Field& f : kFields) {
    // Find "key" followed by ':' (so "rot_l" in a value can't match).
    const size_t kl = strlen(f.key);
    for (const char* p = strstr(json, f.key); p; p = strstr(p + 1, f.key)) {
      if (p == json || p[-1] != '"' || p[kl] != '"') continue;
      const char* v = p + kl + 1;
      while (*v == ' ' || *v == '\t' || *v == '\n' || *v == '\r') v++;
      if (*v++ != ':') continue;
      while (*v == ' ' || *v == '\t' || *v == '\n' || *v == '\r') v++;
      if (*v == '"') v++;
      size_t vl = strcspn(v, "\",} \t\r\n");
      int32_t x;
      if (parseValue(f, v, vl, x)) {
        setField(f, x);
        applied++;
      } else if (err && !*err) {
        *err = f.key;
      }
      break;
    }
  }
  return applied;
}

void registerCommands() {
  console::add("config", "settings: config [show|save|reset|set <key> <value>|keys]", cmdConfig);
  console::add("art", "eye style: art [default|dragon|fire|m4|cat|goat|owl|newt|terminator|nosclera|doe|nauga]",
               cmdArt);
  console::add("flames", "flames + smoke around hazel/dragon eyes: flames [on|off]", cmdFlames);
  console::add("!a", "brain link: !a <style> overrides the eye style, !a alone restores it", cmdBrainArt);
}

}  // namespace settings
