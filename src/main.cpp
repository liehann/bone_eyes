#include <Arduino.h>
#include <esp_heap_caps.h>

#include "config.h"
#include "console.h"
#include "eyes.h"
#include "jaw.h"
#include "net.h"
#include "settings.h"

namespace {

void printHeap() {
  Serial.printf("heap: internal free %u (largest block %u, min ever %u), PSRAM free %u / %u\n",
                heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
                heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL),
                heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL),
                heap_caps_get_free_size(MALLOC_CAP_SPIRAM), ESP.getPsramSize());
}

void cmdHeap(int, char**) { printHeap(); }
void cmdReboot(int, char**) { ESP.restart(); }
void cmdInfo(int, char**) {
  Serial.printf("chip %s rev %d, %d MHz, flash %u MB, PSRAM %u KB, audio %s\n", ESP.getChipModel(),
                ESP.getChipRevision(), ESP.getCpuFreqMHz(), ESP.getFlashChipSize() >> 20,
                ESP.getPsramSize() >> 10, AUDIO_OUT == AUDIO_OUT_A2DP ? "A2DP" : "I2S");
}

}  // namespace

void setup() {
  console::begin();
  delay(200);
  Serial.println("\n\n=== bone_eyes ===");
  cmdInfo(0, nullptr);
  if (ESP.getFlashChipSize() < (8u << 20)) {
    Serial.println("WARNING: flash < 8 MB; build with partitions_4mb.csv (see README)");
  }
  if (!psramFound()) Serial.println("WARNING: no PSRAM detected");

  console::add("heap", "show free heap", cmdHeap);
  console::add("info", "chip / flash / build info", cmdInfo);
  console::add("reboot", "restart the ESP32", cmdReboot);

  settings::begin();  // before the eyes start, so the first frame uses them
  settings::registerCommands();
  eyes::registerCommands();
  jaw::registerCommands();
  jaw::begin();  // goes to closed
  eyes::begin(eyes::Backend::Lcd);
  net::registerCommands();
  net::begin();
  delay(500);  // let the eye task init the panels before reporting heap

  printHeap();
  Serial.println("ready, type 'help'");
}

void loop() {
  console::poll();
  delay(1);
}
