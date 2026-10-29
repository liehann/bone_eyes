// M4 eye firmware glue. See m4eye.h for the hook points and
// docs/m4_eyes.md for the design and measurements.
#pragma GCC optimize("O2")
#include "m4eye.h"

#include <Arduino.h>
#include <esp_heap_caps.h>
#include <esp_timer.h>

#include "console.h"
#include "m4eye_assets.h"
#include "m4eye_fs.h"
#include "m4eye_render.h"

namespace m4eye {
namespace {

constexpr const char* kDefaultEye = "hazel";

// Where things live. Tables: internal RAM (default) or PSRAM. Textures: a
// tinted copy in PSRAM (default) or internal RAM (if it fits), or "flash":
// the untinted source itself (flash for the built-in eye, the PSRAM load for
// a LittleFS one). Changed with `m4 mem`, applied at the next frame.
enum Place : uint8_t { kInternal, kPsram, kFlash };
const char* const kPlaceNames[] = {"int", "psram", "flash"};

portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;
Config pending;          // written by any task under mux
bool pendingSet = false;
// What config() reports: the newest config asked for (or applied), so a
// reader never sees a stale value while the eye task is loading one.
Config latest;
bool haveLatest = false;
volatile bool reloadReq = false;
volatile Place wantTables = kInternal, wantTex = kPsram;

// Eye task state (core 1; read by the worker while rendering).
Config cur;
bool loaded = false;
Place tablesAt = kInternal, texAt = kPsram;
Place tablesAsked = kInternal, texAsked = kPsram;  // wantTables/wantTex at the last build
const EyeSet* set = nullptr;
EyeSet fsSet = {};  // the loaded LittleFS eye set, when set == &fsSet
Model model;
Lids lidsCopy;  // internal-RAM copy of the chosen lid set
uint8_t* tableMem = nullptr;  // displace + polar, one block
size_t tableCap = 0;
uint16_t* texMem[2] = {nullptr, nullptr};  // iris, sclera copies
size_t texCap[2] = {0, 0};
uint16_t flat[2];  // 1x1 iris / sclera when there's no texture
Look look[2];
Anim anim[2];
Frame frame[2];

uint16_t be565(const Rgb& c) {
  const uint16_t v = ((c.r & 0xF8) << 8) | ((c.g & 0xFC) << 3) | (c.b >> 3);
  return (v >> 8) | (v << 8);
}

const EyeSet* builtIn(const char* name) {
  for (int i = 0; i < kNumEyeSets; i++)
    if (!strcmp(kEyeSets[i].name, name)) return &kEyeSets[i];
  return nullptr;
}

bool eyeExists(const char* name) { return store::hasEye(name) || builtIn(name); }

void* allocIn(Place p, size_t n) {
  if (p == kInternal) return heap_caps_malloc(n, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
  return heap_caps_malloc(n, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
}

bool buildTablesNow() {
  Tables& t = model.t;
  t.eyeRadius = cur.eyeRadius;
  t.irisRadius = cur.irisRadius;
  t.slitPupilRadius = cur.slitPupilRadius;
  t.mapRadius = mapRadiusFor(cur.eyeRadius, cur.coverage);
  const size_t need = kDisplaceBytes + polarBytes(t.mapRadius);
  if (!tableMem || need > tableCap || tablesAsked != wantTables) {
    tablesAsked = wantTables;
    if (tableMem) heap_caps_free(tableMem);
    tableMem = nullptr;
    tableCap = 0;
    Place p = wantTables;
    tableMem = (uint8_t*)allocIn(p, need);
    if (!tableMem && p == kInternal) {
      Serial.printf("m4: no %u B internal for tables, using PSRAM\n", (unsigned)need);
      p = kPsram;
      tableMem = (uint8_t*)allocIn(p, need);
    }
    if (!tableMem) return false;
    tableCap = need;
    tablesAt = p;
  }
  t.displace = tableMem;
  t.polarAngle = tableMem + kDisplaceBytes;
  t.polarDist = (int8_t*)(t.polarAngle + (size_t)t.mapRadius * t.mapRadius);
  const int64_t t0 = esp_timer_get_time();
  buildTables(t);
  Serial.printf("m4: tables %u B in %s, mapRadius %d, built in %u ms\n", (unsigned)need, kPlaceNames[tablesAt],
                t.mapRadius, (unsigned)((esp_timer_get_time() - t0) / 1000));
  return true;
}

// Tinted copy of one texture (k 0 iris, 1 sclera).
bool textureNow(int k) {
  const uint16_t* src = k ? set->sclera : set->iris;
  const int w = k ? set->scleraW : set->irisW, h = k ? set->scleraH : set->irisH;
  const Rgb tint = k ? cur.scleraTint : cur.irisTint;
  Texture& tex = k ? model.sclera : model.iris;
  if (!src) {
    flat[k] = be565(k ? cur.scleraColor : cur.irisColor);
    tex = {&flat[k], 1, 1};
    return true;
  }
  const bool white = tint.r == 255 && tint.g == 255 && tint.b == 255;
  Place p = wantTex;
  if (p == kFlash && !white) p = kPsram;  // a tint needs a RAM copy
  if (p == kFlash) {
    if (texMem[k]) heap_caps_free(texMem[k]);
    texMem[k] = nullptr;
    texCap[k] = 0;
    tex = {src, (uint16_t)w, (uint16_t)h};
    texAt = kFlash;
    return true;
  }
  const size_t need = (size_t)w * h * 2;
  if (!texMem[k] || need > texCap[k] || texAt != p || texAsked != wantTex) {
    if (texMem[k]) heap_caps_free(texMem[k]);
    texMem[k] = (uint16_t*)allocIn(p, need);
    if (!texMem[k] && p == kInternal) {
      Serial.printf("m4: no %u B internal for a texture, using PSRAM\n", (unsigned)need);
      p = kPsram;
      texMem[k] = (uint16_t*)allocIn(p, need);
    }
    if (!texMem[k]) return false;
    texCap[k] = need;
  }
  texAt = p;
  for (int i = 0; i < w * h; i++) {
    uint16_t v = src[i];
    if (!white) {
      v = (v >> 8) | (v << 8);
      const uint32_t r = ((v >> 11) & 31) * tint.r / 255, g = ((v >> 5) & 63) * tint.g / 255,
                     b = (v & 31) * tint.b / 255;
      v = (uint16_t)((r << 11) | (g << 5) | b);
      v = (v >> 8) | (v << 8);
    }
    texMem[k][i] = v;
  }
  tex = {texMem[k], (uint16_t)w, (uint16_t)h};
  return true;
}

void lidsNow() {
  model.lids = nullptr;
  if (!strcmp(cur.lids, "none")) return;
  const char* want = cur.lids[0] ? cur.lids : set->name;
  if (store::loadLids(want, lidsCopy)) {
    model.lids = &lidsCopy;
    return;
  }
  for (int s = 0; s < kNumEyeSets; s++) {
    const EyeSet& es = kEyeSets[s];
    for (int i = 0; i < es.numLids; i++) {
      if (strcmp(es.lidNames[i], want)) continue;
      memcpy(&lidsCopy, es.lids[i], sizeof lidsCopy);
      model.lids = &lidsCopy;
      return;
    }
  }
  if (set->numLids && cur.lids[0]) {  // unknown lid set on a built-in eye: its own
    memcpy(&lidsCopy, set->lids[0], sizeof lidsCopy);
    model.lids = &lidsCopy;
  }
}

void looksNow() {
  for (int e = 0; e < 2; e++) {
    Look& l = look[e];
    l.pupilMin = cur.pupilMin;
    l.pupilMax = cur.pupilMax;
    l.squint = cur.squint;
    l.tracking = cur.tracking;
    l.gazeRange = cur.gazeRange;
    l.irisSpin = cur.irisSpin[e];
    l.scleraSpin = cur.scleraSpin;
    l.irisAngle = cur.irisAngle;
    l.scleraAngle = cur.scleraAngle;
    l.irisMirror = cur.irisMirror[e];
    l.scleraMirror = false;
    // M4_Eyes lid art is drawn for the monster's right eye (tear duct toward
    // the viewer's right); the left eye (L, viewer's right) gets it mirrored.
    l.lidFlip = (e == 0) != cur.lidMirror;
    l.blinkRate = cur.blinkRate;
  }
  model.pupilColor = be565(cur.pupilColor);
  model.backColor = be565(cur.backColor);
  model.eyelidColor = be565(cur.eyelidColor);
}

// Point `set` at eye set `name`: LittleFS first, then built-in, then the
// first built-in. Eye task only (frees the previous LittleFS set).
void selectSet(const char* name) {
  if (store::hasEye(name)) {
    EyeSet next;
    const int64_t t0 = esp_timer_get_time();
    if (store::loadEye(name, next)) {
      store::freeEye(fsSet);
      fsSet = next;
      set = &fsSet;
      Serial.printf("m4: eye \"%s\" loaded from LittleFS in %u ms\n", name,
                    (unsigned)((esp_timer_get_time() - t0) / 1000));
      return;
    }
  }
  const EyeSet* b = builtIn(name);
  set = b ? b : &kEyeSets[0];
  store::freeEye(fsSet);
}

// Apply `next` (eye task, between frames).
bool applyNow(const Config& next) {
  uint32_t d = loaded ? diff(cur, next) : ~0u;
  const bool tablesMoved = tablesAsked != wantTables, texMoved = texAsked != wantTex;
  cur = next;
  if (!set || strcmp(set->name, cur.eye) || reloadReq) {
    reloadReq = false;
    selectSet(cur.eye);
    snprintf(cur.eye, sizeof cur.eye, "%s", set->name);
    d |= kDirtyAssets;
  }
  if ((d & kDirtyTables) || tablesMoved || !model.t.displace)
    if (!buildTablesNow()) return false;
  if ((d & (kDirtyColors | kDirtyAssets)) || texMoved || !model.iris.data) {
    if (!textureNow(0) || !textureNow(1)) return false;
    texAsked = wantTex;
  }
  if ((d & kDirtyAssets) || !loaded) lidsNow();
  looksNow();
  loaded = true;
  portENTER_CRITICAL(&mux);
  if (!pendingSet) latest = cur, haveLatest = true;  // e.g. an unknown eye name fell back
  portEXIT_CRITICAL(&mux);
  return true;
}

Config fromSet(const EyeSet& s) {
  Config c;
  fromJson(s.json, c);
  snprintf(c.eye, sizeof c.eye, "%s", s.name);
  c.lids[0] = 0;
  return c;
}

// An eye set's defaults by name: its LittleFS config.json, else built-in.
Config fromName(const char* eye) {
  if (char* json = store::readConfig(eye)) {
    Config c;
    fromJson(json, c);
    free(json);
    snprintf(c.eye, sizeof c.eye, "%s", eye);
    c.lids[0] = 0;
    return c;
  }
  const EyeSet* b = builtIn(eye);
  return fromSet(b ? *b : kEyeSets[0]);
}

bool fsHasLid(const char* name) {
  for (int i = 0; i < store::numLids(); i++)
    if (!strcmp(store::lidName(i), name)) return true;
  return false;
}

// --- console ---

void printJson() {
  char* buf = (char*)malloc(1024);
  if (!buf) return;
  getJson(buf, 1024);
  Serial.println(buf);
  free(buf);
}

// Render-only timing on this core: both eyes, all rows, no SPI.
void bench(int frames) {
  if (!eyes::pause()) {
    Serial.println("m4: eye task didn't pause");
    return;
  }
  if (!beginFrame()) {
    Serial.println("m4: can't set up (memory?)");
    eyes::animate();
    return;
  }
  static uint16_t row[kSize];
  EyeState st;
  int64_t sim = 0, ren = 0;
  for (int f = 0; f < frames; f++) {
    st.gazeX = sinf(f * 0.3f) * 0.8f;
    st.gazeY = cosf(f * 0.2f) * 0.5f;
    const int64_t t0 = esp_timer_get_time();
    simulate(0, st, false, millis());
    simulate(1, st, false, millis());
    const int64_t t1 = esp_timer_get_time();
    for (int e = 0; e < 2; e++)
      for (int y = 0; y < kSize; y++) renderRow(e, y, row);
    ren += esp_timer_get_time() - t1;
    sim += t1 - t0;
  }
  Serial.printf("m4 bench: %d frames, one core: sim %.2f ms, render %.2f ms per frame (both eyes) = %.1f fps "
                "render-bound on one core; tables %s, textures %s\n",
                frames, sim / 1000.0 / frames, ren / 1000.0 / frames, 1e6 * frames / (double)(sim + ren),
                kPlaceNames[tablesAt], kPlaceNames[texAt]);
  eyes::animate();
}

void cmdM4(int argc, char** argv) {
  const char* usage =
      "usage: m4 [show | set <json> | <key> <value> | eye <name> | list | rescan | mem [tables int|psram] [tex psram|int|flash] "
      "| bench [frames] | reset]";
  if (argc < 2 || !strcmp(argv[1], "show")) return printJson();
  const char* sub = argv[1];
  if (!strcmp(sub, "list")) {
    Serial.print("m4 eye sets:");
    for (int i = 0; i < numEyeSets(); i++) Serial.printf(" %s", eyeSetName(i));
    Serial.print("\nm4 lid sets: none");
    for (int i = 0; i < numLidSets(); i++) Serial.printf(" %s", lidSetName(i));
    Serial.println();
  } else if (!strcmp(sub, "set") && argc > 2) {
    char json[256];
    size_t n = 0;
    for (int i = 2; i < argc && n < sizeof json - 2; i++)
      n += snprintf(json + n, sizeof json - n, "%s%s", i > 2 ? " " : "", argv[i]);
    char err[64];
    if (!applyJson(json, err, sizeof err)) Serial.printf("m4: %s\n", err);
    printJson();
  } else if (!strcmp(sub, "rescan")) {
    rescan();
    reload();
    Serial.printf("m4: %d eye sets, %d lid sets\n", numEyeSets(), numLidSets());
  } else if (!strcmp(sub, "reset")) {
    setConfig(defaultsFor(config().eye));
    printJson();
  } else if (!strcmp(sub, "mem")) {
    for (int i = 2; i + 1 < argc; i += 2) {
      for (int p = 0; p < 3; p++) {
        if (strcmp(argv[i + 1], kPlaceNames[p])) continue;
        if (!strcmp(argv[i], "tables") && p != kFlash) wantTables = (Place)p;
        if (!strcmp(argv[i], "tex")) wantTex = (Place)p;
      }
    }
    portENTER_CRITICAL(&mux);
    if (!pendingSet && loaded) pending = cur, pendingSet = true;
    portEXIT_CRITICAL(&mux);
    Serial.printf("m4 mem: tables %s (want %s), textures %s (want %s); internal free %u, PSRAM free %u\n",
                  kPlaceNames[tablesAt], kPlaceNames[wantTables], kPlaceNames[texAt], kPlaceNames[wantTex],
                  heap_caps_get_free_size(MALLOC_CAP_INTERNAL), heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
  } else if (!strcmp(sub, "bench")) {
    long n = 20;
    console::argInt(argc, argv, 2, n);
    bench(constrain(n, 1, 500));
  } else if (argc > 2) {
    // m4 <key> <value>: a one-key patch; bare words become strings.
    char json[96];
    const char* v = argv[2];
    char* end;
    strtod(v, &end);
    const bool bare = *end && strcmp(v, "true") && strcmp(v, "false") && v[0] != '[' && v[0] != '"';
    snprintf(json, sizeof json, bare ? "{\"%s\":\"%s\"}" : "{\"%s\":%s}", sub, v);
    char err[64];
    if (!applyJson(json, err, sizeof err)) Serial.printf("m4: %s\n", err);
    printJson();
  } else {
    Serial.println(usage);
  }
}


}  // namespace

// --- public ---

Config config() {
  bool have;
  Config c;
  portENTER_CRITICAL(&mux);
  have = haveLatest;
  if (have) c = latest;
  portEXIT_CRITICAL(&mux);
  return have ? c : fromName(kDefaultEye);
}

void setConfig(const Config& c) {
  portENTER_CRITICAL(&mux);
  pending = latest = c;
  pendingSet = haveLatest = true;
  portEXIT_CRITICAL(&mux);
}

Config defaultsFor(const char* eye) { return fromName(eye); }

bool applyJson(const char* json, char* err, size_t errLen) {
  Config c = config();
  Config next = c;
  if (!fromJson(json, next, err, errLen)) return false;
  // "reset": true goes back to the eye set's own values first.
  bool reset = false;
  if (const char* r = strstr(json, "\"reset\"")) {
    r += 7;
    while (*r == ' ' || *r == ':' || *r == '\t') r++;
    reset = !strncmp(r, "true", 4) || *r == '1';
  }
  if (strcmp(next.eye, c.eye) || reset) {
    if (!eyeExists(next.eye)) {
      if (err && errLen) snprintf(err, errLen, "no eye set \"%s\"", next.eye);
      return false;
    }
    Config base = defaultsFor(next.eye);
    fromJson(json, base);  // the rest of the patch on top of the new eye's defaults
    next = base;
  }
  setConfig(next);
  return true;
}

int getJson(char* out, size_t len) { return toJson(config(), out, len); }

// LittleFS names first, then built-ins that LittleFS doesn't shadow.
int numEyeSets() {
  store::mount();
  int n = store::numEyes();
  for (int i = 0; i < kNumEyeSets; i++) n += !store::hasEye(kEyeSets[i].name);
  return n;
}

const char* eyeSetName(int i) {
  if (i < store::numEyes()) return store::eyeName(i);
  i -= store::numEyes();
  for (int s = 0; s < kNumEyeSets; s++) {
    if (store::hasEye(kEyeSets[s].name)) continue;
    if (i-- == 0) return kEyeSets[s].name;
  }
  return "";
}

int numLidSets() {
  store::mount();
  int n = store::numLids();
  for (int s = 0; s < kNumEyeSets; s++)
    for (int i = 0; i < kEyeSets[s].numLids; i++) n += !fsHasLid(kEyeSets[s].lidNames[i]);
  return n;
}

const char* lidSetName(int i) {
  if (i < store::numLids()) return store::lidName(i);
  i -= store::numLids();
  for (int s = 0; s < kNumEyeSets; s++)
    for (int j = 0; j < kEyeSets[s].numLids; j++) {
      if (fsHasLid(kEyeSets[s].lidNames[j])) continue;
      if (i-- == 0) return kEyeSets[s].lidNames[j];
    }
  return "";
}

int listJson(char* out, size_t len) {
  size_t n = snprintf(out, len, "{\"eyes\":[");
  const int ne = numEyeSets();
  for (int i = 0; i < ne && n < len; i++) n += snprintf(out + n, len - n, "%s\"%s\"", i ? "," : "", eyeSetName(i));
  if (n < len) n += snprintf(out + n, len - n, "],\"lids\":[");
  const int nl = numLidSets();
  for (int i = 0; i < nl && n < len; i++) n += snprintf(out + n, len - n, "%s\"%s\"", i ? "," : "", lidSetName(i));
  if (n < len) n += snprintf(out + n, len - n, "]}");
  return n < len ? (int)n : (int)len - 1;
}

void rescan() { store::rescan(); }

void reload() {
  reloadReq = true;
  setConfig(config());
}

bool beginFrame() {
  Config next;
  bool have;
  portENTER_CRITICAL(&mux);
  have = pendingSet;
  if (have) next = pending;
  pendingSet = false;
  portEXIT_CRITICAL(&mux);
  if (!loaded && !have) next = fromName(kDefaultEye), have = true;
  if (have) {
    visibleSpan();  // build the shared span table before two cores read it
    if (!applyNow(next)) {
      Serial.println("m4: out of memory");
      loaded = false;
      return false;
    }
  }
  return loaded;
}

void simulate(int e, const EyeState& st, bool gazeInvert, uint32_t nowMs) {
  compute(model, look[e], gazeInvert ? -st.gazeX : st.gazeX, st.gazeY, st.lid, st.pupil, nowMs, anim[e], frame[e]);
}

void renderRow(int e, int oy, uint16_t* out) { row(model, frame[e], oy, out); }

void registerCommands() {
  console::add("m4", "M4 eye: m4 [show|set <json>|<key> <value>|list|mem ...|bench [n]|rescan|reset]", cmdM4);
}

}  // namespace m4eye
