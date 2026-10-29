#include "m4eye_config.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

namespace m4eye {
namespace {

// --- a small JSON reader: enough for flat objects of numbers, bools,
// strings and short number arrays, with nested objects one level deep. ---

struct Value {
  enum Type { Num, Bool, Str, Arr, Obj, Null } type = Null;
  double num = 0;
  bool b = false;
  char str[32] = "";
  double arr[4] = {};
  int arrN = 0;
};

struct Parser {
  const char* p;
  const char* err;
  explicit Parser(const char* s) : p(s), err(nullptr) {}

  void ws() {
    for (;;) {
      while (*p && isspace((unsigned char)*p)) p++;
      if (p[0] == '/' && p[1] == '/') {
        while (*p && *p != '\n') p++;
      } else if (p[0] == '/' && p[1] == '*') {
        const char* e = strstr(p + 2, "*/");
        p = e ? e + 2 : p + strlen(p);
      } else {
        return;
      }
    }
  }
  bool fail(const char* m) {
    if (!err) err = m;
    return false;
  }
  bool string(char* out, size_t n) {
    if (*p != '"') return fail("expected string");
    p++;
    size_t i = 0;
    while (*p && *p != '"') {
      char c = *p++;
      if (c == '\\' && *p) c = *p++;
      if (i + 1 < n) out[i++] = c;
    }
    if (*p != '"') return fail("unterminated string");
    p++;
    out[i] = 0;
    return true;
  }
  bool number(double& out) {
    char* e;
    out = strtod(p, &e);
    if (e == p) return fail("bad value");
    p = e;
    return true;
  }
  // Parses a value; an object is handed to onObj(key) for its members.
  template <typename F>
  bool value(Value& v, F&& onObj) {
    ws();
    if (*p == '"') {
      v.type = Value::Str;
      return string(v.str, sizeof v.str);
    }
    if (!strncmp(p, "true", 4)) return v.type = Value::Bool, v.b = true, p += 4, true;
    if (!strncmp(p, "false", 5)) return v.type = Value::Bool, v.b = false, p += 5, true;
    if (!strncmp(p, "null", 4)) return v.type = Value::Null, p += 4, true;
    if (*p == '[') {
      v.type = Value::Arr;
      p++;
      ws();
      while (*p && *p != ']') {
        double d;
        if (!number(d)) return false;
        if (v.arrN < 4) v.arr[v.arrN++] = d;
        ws();
        if (*p == ',') p++, ws();
      }
      if (*p != ']') return fail("unterminated array");
      p++;
      return true;
    }
    if (*p == '{') {
      v.type = Value::Obj;
      return onObj();
    }
    v.type = Value::Num;
    return number(v.num);
  }
  // Object members -> f(key, value). Nested objects recurse with f too,
  // with the key prefixed "outer.".
  template <typename F>
  bool object(const char* prefix, F& f) {
    ws();
    if (*p != '{') return fail("expected {");
    p++;
    for (;;) {
      ws();
      if (*p == '}') {
        p++;
        return true;
      }
      char key[48], full[64];
      if (!string(key, sizeof key)) return false;
      snprintf(full, sizeof full, "%s%s", prefix, key);
      ws();
      if (*p != ':') return fail("expected :");
      p++;
      Value v;
      char sub[64];
      snprintf(sub, sizeof sub, "%s.", full);
      if (!value(v, [&] { return object(sub, f); })) return false;
      if (v.type != Value::Obj) f(full, v);
      ws();
      if (*p == ',') {
        p++;
      } else if (*p != '}') {
        return fail("expected , or }");
      }
    }
  }
};

float clampF(double v, float lo, float hi) { return v < lo ? lo : v > hi ? hi : (float)v; }
int clampI(double v, int lo, int hi) { return v < lo ? lo : v > hi ? hi : (int)(v + (v < 0 ? -0.5 : 0.5)); }

bool asRgb(const Value& v, Rgb& out) {
  if (v.type == Value::Arr && v.arrN >= 3) {
    uint8_t c[3];
    for (int i = 0; i < 3; i++) {
      double d = v.arr[i];
      // M4_Eyes: floats are 0..1, ints 0..255. JSON can't tell 1 from 1.0,
      // so any component < 1 that isn't 0 makes it a float triple.
      c[i] = (uint8_t)clampI(d, 0, 255);
    }
    bool frac = false;
    for (int i = 0; i < 3; i++) frac |= v.arr[i] > 0 && v.arr[i] < 1;
    if (frac)
      for (int i = 0; i < 3; i++) c[i] = (uint8_t)clampI(v.arr[i] * 255.999, 0, 255);
    out = {c[0], c[1], c[2]};
    return true;
  }
  if (v.type == Value::Str) {  // "#rrggbb" or "0xRRGGBB"
    const char* s = v.str[0] == '#' ? v.str + 1 : (strncasecmp(v.str, "0x", 2) ? v.str : v.str + 2);
    if (strlen(s) != 6) return false;
    unsigned long n = strtoul(s, nullptr, 16);
    out = {(uint8_t)(n >> 16), (uint8_t)(n >> 8), (uint8_t)n};
    return true;
  }
  return false;
}

bool asNum(const Value& v, double& d) {
  if (v.type == Value::Num) return d = v.num, true;
  if (v.type == Value::Bool) return d = v.b, true;
  return false;
}

// One key onto the config. "left." / "right." prefixes select an eye.
void apply(Config& c, const char* key, const Value& v) {
  int eye = -1;
  if (!strncmp(key, "left.", 5)) eye = 0, key += 5;
  else if (!strncmp(key, "right.", 6)) eye = 1, key += 6;
  double d = 0;
  const bool num = asNum(v, d);
  auto both = [&](float* a, float val) {
    if (eye < 0) a[0] = a[1] = val;
    else a[eye] = val;
  };
  if (!strcmp(key, "eye") && v.type == Value::Str) snprintf(c.eye, sizeof c.eye, "%s", v.str);
  else if (!strcmp(key, "lids") && v.type == Value::Str) snprintf(c.lids, sizeof c.lids, "%s", v.str);
  else if (!strcmp(key, "eyeRadius") && num) c.eyeRadius = clampI(d, 40, 120);
  else if (!strcmp(key, "irisRadius") && num) c.irisRadius = clampI(d, 4, 120);
  else if (!strcmp(key, "slitPupilRadius") && num) c.slitPupilRadius = clampI(d, 0, 120);
  else if (!strcmp(key, "coverage") && num) c.coverage = clampF(d, 0.3f, 0.95f);
  else if (!strcmp(key, "irisTint")) asRgb(v, c.irisTint);
  else if (!strcmp(key, "scleraTint")) asRgb(v, c.scleraTint);
  else if (!strcmp(key, "irisColor")) asRgb(v, c.irisColor);
  else if (!strcmp(key, "scleraColor")) asRgb(v, c.scleraColor);
  else if (!strcmp(key, "pupilColor")) asRgb(v, c.pupilColor);
  else if (!strcmp(key, "backColor")) asRgb(v, c.backColor);
  else if (!strcmp(key, "eyelidColor")) asRgb(v, c.eyelidColor);
  else if (!strcmp(key, "pupilMin") && num) c.pupilMin = clampF(d, 0, 1);
  else if (!strcmp(key, "pupilMax") && num) c.pupilMax = clampF(d, 0, 1);
  else if (!strcmp(key, "tracking") && num) c.tracking = d != 0;
  else if (!strcmp(key, "squint") && num) c.squint = clampF(d, 0, 1);
  else if (!strcmp(key, "lidMirror") && num) c.lidMirror = d != 0;
  else if (!strcmp(key, "blinkRate") && num) c.blinkRate = clampF(d, 0, 120);
  else if (!strcmp(key, "gazeRange") && num) c.gazeRange = clampF(d, 0, 1);
  else if (!strcmp(key, "irisSpin") && num) both(c.irisSpin, clampF(d, -300, 300));
  else if (!strcmp(key, "irisSpinL") && num) c.irisSpin[0] = clampF(d, -300, 300);
  else if (!strcmp(key, "irisSpinR") && num) c.irisSpin[1] = clampF(d, -300, 300);
  else if (!strcmp(key, "scleraSpin") && num) c.scleraSpin = clampF(d, -300, 300);
  else if (!strcmp(key, "irisMirror") && num) {
    if (eye < 0) c.irisMirror[0] = c.irisMirror[1] = d != 0;
    else c.irisMirror[eye] = d != 0;
  } else if (!strcmp(key, "irisMirrorL") && num) c.irisMirror[0] = d != 0;
  else if (!strcmp(key, "irisMirrorR") && num) c.irisMirror[1] = d != 0;
  else if (!strcmp(key, "irisAngle") && num) c.irisAngle = clampI(d, -100000, 100000) & 1023;
  else if (!strcmp(key, "scleraAngle") && num) c.scleraAngle = clampI(d, -100000, 100000) & 1023;
}

}  // namespace

uint32_t diff(const Config& a, const Config& b) {
  uint32_t d = kDirtyNone;
  if (strcmp(a.eye, b.eye) || strcmp(a.lids, b.lids)) d |= kDirtyAssets;
  if (a.eyeRadius != b.eyeRadius || a.irisRadius != b.irisRadius || a.slitPupilRadius != b.slitPupilRadius ||
      a.coverage != b.coverage)
    d |= kDirtyTables;
  if (a.irisTint != b.irisTint || a.scleraTint != b.scleraTint || a.irisColor != b.irisColor ||
      a.scleraColor != b.scleraColor || a.pupilColor != b.pupilColor || a.backColor != b.backColor ||
      a.eyelidColor != b.eyelidColor)
    d |= kDirtyColors;
  return d | kDirtyLook;  // per-frame values are cheap: always re-read
}

bool fromJson(const char* json, Config& c, char* err, size_t errLen) {
  Config tmp = c;
  Parser ps(json);
  auto f = [&](const char* key, const Value& v) { apply(tmp, key, v); };
  if (!ps.object("", f)) {
    if (err && errLen) snprintf(err, errLen, "%s at offset %d", ps.err ? ps.err : "error", (int)(ps.p - json));
    return false;
  }
  if (tmp.slitPupilRadius > tmp.irisRadius) tmp.slitPupilRadius = tmp.irisRadius;
  c = tmp;
  return true;
}

int toJson(const Config& c, char* out, size_t len) {
  auto rgb = [](const Rgb& v, char* b) {
    snprintf(b, 20, "[%u,%u,%u]", v.r, v.g, v.b);
    return b;
  };
  char a[7][20];
  return snprintf(out, len,
                  "{\"eye\":\"%s\",\"lids\":\"%s\",\"eyeRadius\":%d,\"irisRadius\":%d,\"slitPupilRadius\":%d,"
                  "\"coverage\":%.3g,\"irisTint\":%s,\"scleraTint\":%s,\"irisColor\":%s,\"scleraColor\":%s,"
                  "\"pupilColor\":%s,\"backColor\":%s,\"eyelidColor\":%s,\"pupilMin\":%.3g,\"pupilMax\":%.3g,"
                  "\"tracking\":%s,\"squint\":%.3g,\"lidMirror\":%s,\"blinkRate\":%.3g,\"gazeRange\":%.3g,"
                  "\"irisSpinL\":%.4g,\"irisSpinR\":%.4g,\"scleraSpin\":%.4g,\"irisMirrorL\":%s,"
                  "\"irisMirrorR\":%s,\"irisAngle\":%d,\"scleraAngle\":%d}",
                  c.eye, c.lids, c.eyeRadius, c.irisRadius, c.slitPupilRadius, c.coverage, rgb(c.irisTint, a[0]),
                  rgb(c.scleraTint, a[1]), rgb(c.irisColor, a[2]), rgb(c.scleraColor, a[3]), rgb(c.pupilColor, a[4]),
                  rgb(c.backColor, a[5]), rgb(c.eyelidColor, a[6]), c.pupilMin, c.pupilMax,
                  c.tracking ? "true" : "false", c.squint, c.lidMirror ? "true" : "false", c.blinkRate, c.gazeRange,
                  c.irisSpin[0], c.irisSpin[1], c.scleraSpin, c.irisMirror[0] ? "true" : "false",
                  c.irisMirror[1] ? "true" : "false", c.irisAngle, c.scleraAngle);
}

}  // namespace m4eye
