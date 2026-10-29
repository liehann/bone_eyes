#include "m4eye_fs.h"

#include <Arduino.h>
#include <LittleFS.h>
#include <esp_heap_caps.h>

#include "m4eye.h"
#include "m4eye_config.h"

namespace m4eye {

namespace {

constexpr int kMaxEyes = 24, kMaxLids = 32;
struct LidEntry {
  char name[32];
  uint8_t eye;  // index into eyes_
  bool own;     // lids.bin (else lids-<name>.bin)
};
char eyes_[kMaxEyes][32];
int nEyes = 0;
LidEntry lids_[kMaxLids];
int nLids = 0;
bool mounted = false, tried = false;
SemaphoreHandle_t lock = xSemaphoreCreateRecursiveMutex();

struct Lock {
  Lock() { xSemaphoreTakeRecursive(lock, portMAX_DELAY); }
  ~Lock() { xSemaphoreGiveRecursive(lock); }
};

uint16_t rd16(const uint8_t* p) { return p[0] | p[1] << 8; }
uint32_t rd32(const uint8_t* p) { return p[0] | p[1] << 8 | p[2] << 16 | (uint32_t)p[3] << 24; }

void* psram(size_t n) {
  void* p = heap_caps_malloc(n, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  return p ? p : malloc(n);
}

// A .565 file, or an uncompressed 24-bit BMP (what M4_Eyes ships).
bool readTexture(File& f, uint16_t** data, uint16_t* w, uint16_t* h) {
  uint8_t hdr[54];
  const size_t got = f.read(hdr, sizeof hdr);
  if (got >= 2 && hdr[0] == 'B' && hdr[1] == 'M') {
    if (got < 54) return false;
    const uint32_t off = rd32(hdr + 10);
    const int32_t bw = (int32_t)rd32(hdr + 18), bh = (int32_t)rd32(hdr + 22);
    const uint16_t bpp = rd16(hdr + 28);
    const uint32_t comp = rd32(hdr + 30);
    if (bpp != 24 || comp != 0 || bw <= 0 || bw > 2048 || bh == 0 || abs(bh) > 2048) return false;
    const int H = abs(bh);
    const size_t stride = ((size_t)bw * 3 + 3) & ~3u;
    uint16_t* px = (uint16_t*)psram((size_t)bw * H * 2);
    uint8_t* line = (uint8_t*)malloc(stride);
    if (!px || !line) return free(line), heap_caps_free(px), false;
    bool ok = true;
    for (int r = 0; r < H && ok; r++) {
      ok = f.seek(off + (size_t)r * stride) && f.read(line, stride) == stride;
      const int y = bh > 0 ? H - 1 - r : r;  // positive height = bottom-up
      for (int x = 0; x < bw; x++) {
        const uint8_t b = line[x * 3], g = line[x * 3 + 1], rr = line[x * 3 + 2];
        const uint16_t v = ((rr & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3);
        px[y * bw + x] = (v >> 8) | (v << 8);
      }
    }
    free(line);
    if (!ok) return heap_caps_free(px), false;
    *data = px;
    *w = bw;
    *h = H;
    return true;
  }
  if (got < 4) return false;
  const uint16_t tw = rd16(hdr), th = rd16(hdr + 2);
  const size_t n = (size_t)tw * th * 2;
  if (!tw || !th || tw > 2048 || th > 2048 || f.size() != n + 4) return false;
  uint16_t* px = (uint16_t*)psram(n);
  if (!px) return false;
  if (!f.seek(4) || f.read((uint8_t*)px, n) != n) return heap_caps_free(px), false;
  *data = px;
  *w = tw;
  *h = th;
  return true;
}

void addLid(const char* name, int eye, bool own) {
  if (nLids >= kMaxLids) return;
  for (int i = 0; i < nLids; i++)
    if (!strcmp(lids_[i].name, name)) return;
  snprintf(lids_[nLids].name, sizeof lids_[0].name, "%s", name);
  lids_[nLids].eye = eye;
  lids_[nLids].own = own;
  nLids++;
}

}  // namespace

// --- public helpers (m4eye.h) ---

bool loadTexture(const char* path, uint16_t** data, uint16_t* w, uint16_t* h) {
  Lock l;
  if (!store::mount()) return false;
  File f = LittleFS.open(path, "r");
  if (!f) return false;
  const bool ok = readTexture(f, data, w, h);
  f.close();
  return ok;
}

bool loadLidsFile(const char* path, Lids& out) {
  Lock l;
  if (!store::mount()) return false;
  File f = LittleFS.open(path, "r");
  if (!f) return false;
  const bool ok = f.size() == sizeof(Lids) && f.read((uint8_t*)&out, sizeof out) == sizeof out;
  f.close();
  return ok;
}

bool installFile(const char* eye, const char* file, const uint8_t* data, size_t len) {
  if (!eye || !*eye || strchr(eye, '/') || !file || !*file || strchr(file, '/')) return false;
  bool ok;
  {
    Lock l;
    if (!store::mount()) return false;
    char path[96];
    snprintf(path, sizeof path, "/eyes/%s", eye);
    if (!LittleFS.exists("/eyes")) LittleFS.mkdir("/eyes");
    if (!LittleFS.exists(path)) LittleFS.mkdir(path);
    snprintf(path, sizeof path, "/eyes/%s/%s", eye, file);
    File f = LittleFS.open(path, "w");
    if (!f) return false;
    ok = f.write(data, len) == len;
    f.close();
    store::rescan();
  }
  if (ok && !strcmp(config().eye, eye)) reload();
  return ok;
}

namespace store {

bool mount() {
  Lock l;
  if (tried) return mounted;
  tried = true;
  mounted = LittleFS.begin(false);
  if (!mounted) Serial.println("m4: no LittleFS image (pio run -t uploadfs); built-in eyes only");
  rescan();
  return mounted;
}

void rescan() {
  Lock l;
  nEyes = nLids = 0;
  if (!mounted) return;
  File root = LittleFS.open("/eyes");
  if (!root || !root.isDirectory()) return;
  for (File d = root.openNextFile(); d && nEyes < kMaxEyes; d = root.openNextFile()) {
    if (!d.isDirectory()) continue;
    const char* name = strrchr(d.name(), '/') ? strrchr(d.name(), '/') + 1 : d.name();
    char path[96];
    snprintf(path, sizeof path, "/eyes/%s/config.json", name);
    if (!LittleFS.exists(path)) continue;
    snprintf(eyes_[nEyes++], sizeof eyes_[0], "%s", name);
    // Lid sets in this folder.
    snprintf(path, sizeof path, "/eyes/%s", name);
    File dir = LittleFS.open(path);
    for (File f = dir.openNextFile(); f; f = dir.openNextFile()) {
      const char* fn = strrchr(f.name(), '/') ? strrchr(f.name(), '/') + 1 : f.name();
      char lid[32];
      if (!strcmp(fn, "lids.bin")) {
        addLid(name, nEyes - 1, true);
      } else if (!strncmp(fn, "lids-", 5) && strlen(fn) > 9 && !strcmp(fn + strlen(fn) - 4, ".bin")) {
        snprintf(lid, sizeof lid, "%.*s", (int)(strlen(fn) - 9), fn + 5);
        addLid(lid, nEyes - 1, false);
      }
    }
  }
}

int numEyes() { return nEyes; }
const char* eyeName(int i) { return i >= 0 && i < nEyes ? eyes_[i] : ""; }
bool hasEye(const char* name) {
  Lock l;
  mount();
  for (int i = 0; i < nEyes; i++)
    if (!strcmp(eyes_[i], name)) return true;
  return false;
}
int numLids() { return nLids; }
const char* lidName(int i) { return i >= 0 && i < nLids ? lids_[i].name : ""; }

char* readConfig(const char* eye) {
  Lock l;
  if (!mount()) return nullptr;
  char path[96];
  snprintf(path, sizeof path, "/eyes/%s/config.json", eye);
  File f = LittleFS.open(path, "r");
  if (!f) return nullptr;
  const size_t n = f.size();
  char* s = n < 8192 ? (char*)malloc(n + 1) : nullptr;
  if (s) {
    s[f.read((uint8_t*)s, n)] = 0;
  }
  f.close();
  return s;
}

// "irisTexture": "iris.565" -> value, from the config text.
static bool jsonString(const char* json, const char* key, char* out, size_t n) {
  char k[40];
  snprintf(k, sizeof k, "\"%s\"", key);
  const char* p = strstr(json, k);
  if (!p) return false;
  p = strchr(p + strlen(k), ':');
  if (!p) return false;
  p = strchr(p, '"');
  if (!p) return false;
  const char* e = strchr(p + 1, '"');
  if (!e || (size_t)(e - p - 1) >= n) return false;
  memcpy(out, p + 1, e - p - 1);
  out[e - p - 1] = 0;
  return true;
}

bool loadEye(const char* eye, EyeSet& out) {
  Lock l;
  out = {};
  char* json = readConfig(eye);
  if (!json) return false;
  char* name = strdup(eye);
  out.name = name;
  out.json = json;
  const char* keys[2] = {"irisTexture", "scleraTexture"};
  for (int k = 0; k < 2; k++) {
    char fn[48], path[96];
    if (!jsonString(json, keys[k], fn, sizeof fn)) continue;
    snprintf(path, sizeof path, "/eyes/%s/%s", eye, strrchr(fn, '/') ? strrchr(fn, '/') + 1 : fn);
    uint16_t* d = nullptr;
    uint16_t w = 0, h = 0;
    if (!loadTexture(path, &d, &w, &h)) {
      Serial.printf("m4: can't load %s\n", path);
      continue;
    }
    if (k == 0) out.iris = d, out.irisW = w, out.irisH = h;
    else out.sclera = d, out.scleraW = w, out.scleraH = h;
  }
  return true;
}

void freeEye(EyeSet& s) {
  free((void*)s.name);
  free((void*)s.json);
  heap_caps_free((void*)s.iris);
  heap_caps_free((void*)s.sclera);
  s = {};
}

bool loadLids(const char* lidSet, Lids& out) {
  Lock l;
  if (!mount()) return false;
  for (int i = 0; i < nLids; i++)
    if (!strcmp(lids_[i].name, lidSet)) {
      char path[112];
      if (lids_[i].own) snprintf(path, sizeof path, "/eyes/%s/lids.bin", eyes_[lids_[i].eye]);
      else snprintf(path, sizeof path, "/eyes/%s/lids-%s.bin", eyes_[lids_[i].eye], lids_[i].name);
      return loadLidsFile(path, out);
    }
  return false;
}

}  // namespace store
}  // namespace m4eye
