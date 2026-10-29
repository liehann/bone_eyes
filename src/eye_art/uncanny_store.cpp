#include "uncanny_store.h"

#include <Arduino.h>
#include <LittleFS.h>
#include <esp_heap_caps.h>

#include "../m4eye/m4eye_fs.h"
#include "uncanny_file.h"

namespace uncanny_store {

namespace {
char loaded[24] = "", failed[24] = "";
uint8_t* buf = nullptr;
EyeArt art;
}  // namespace

const EyeArt* load(const char* name) {
  if (buf && !strcmp(loaded, name)) return &art;
  if (!strcmp(failed, name)) return nullptr;
  const uint32_t t0 = millis();
  heap_caps_free(buf);
  buf = nullptr;
  loaded[0] = 0;
  snprintf(failed, sizeof failed, "%s", name);  // until it succeeds
  if (!m4eye::store::mount()) return nullptr;
  char path[48];
  snprintf(path, sizeof path, "/uncanny/%s.eye", name);
  File f = LittleFS.open(path, "r");
  if (!f) {
    Serial.printf("uncanny: %s missing (pio run -t uploadfs), showing the default eye\n", path);
    return nullptr;
  }
  const size_t n = f.size();
  buf = (uint8_t*)heap_caps_malloc(n, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!buf) {
    Serial.printf("uncanny: no PSRAM for %s (%u bytes)\n", path, (unsigned)n);
    return nullptr;
  }
  // 4 KB at a time: a flash read into PSRAM bounces through internal RAM,
  // so big reads would take a big internal buffer.
  size_t got = 0;
  for (size_t r = 1; got < n && r; got += r) r = f.read(buf + got, n - got < 4096 ? n - got : 4096);
  f.close();
  snprintf(loaded, sizeof loaded, "%s", name);
  if (got != n || !uncanny_file::parse(buf, n, loaded, art)) {
    Serial.printf("uncanny: %s is not a valid eye file\n", path);
    heap_caps_free(buf);
    buf = nullptr;
    loaded[0] = 0;
    return nullptr;
  }
  failed[0] = 0;
  Serial.printf("uncanny: loaded %s (%u KB) in %lu ms\n", path, (unsigned)(n / 1024), millis() - t0);
  return &art;
}

void retry() { failed[0] = 0; }

}  // namespace uncanny_store
