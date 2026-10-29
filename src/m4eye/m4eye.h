// M4_Eyes renderer, firmware side: eye sets, memory placement, runtime
// config and the `m4` console command. The per-pixel engine is
// m4eye_render.h; parameters and their JSON are m4eye_config.h.
//
// Hook points:
//  - eyes_lcd.cpp: style settings::kM4 calls beginFrame() once per frame on
//    core 1 (no renderer running), simulate() per eye, renderRow() per row
//    from either core (output already big-endian).
//  - settings.cpp: the nested "m4" object of /api/config and `config` goes
//    through applyJson()/getJson(); save() stores getJson() in NVS key "m4",
//    begin() feeds it back with applyJson().
#pragma once
#include <stddef.h>
#include <stdint.h>

#include "eyes.h"
#include "m4eye_config.h"
#include "m4eye_render.h"

namespace m4eye {

// --- config, any task ---
Config config();          // live copy (pending changes included)
void setConfig(const Config& c);
// Patch the config with a JSON object. Changing "eye" first resets the other
// fields to that eye set's defaults, then applies the rest of the patch.
bool applyJson(const char* json, char* err = nullptr, size_t errLen = 0);
int getJson(char* out, size_t len);
Config defaultsFor(const char* eye);  // an eye set's own config.eye values

// Eye sets: those on LittleFS (/eyes/<name>/, see m4eye_fs.h) plus the
// compiled-in hazel fallback. Lid sets: lids*.bin on LittleFS plus hazel's.
int numEyeSets();
const char* eyeSetName(int i);  // valid until the next rescan()
int numLidSets();
const char* lidSetName(int i);
// JSON {"eyes":[...],"lids":[...]} for the web page's pickers.
int listJson(char* out, size_t len);

// --- files (any task; hooks for web uploads) ---
// Write /eyes/<eye>/<file> (config.json, iris.565/.bmp, sclera.565/.bmp,
// lids*.bin), rescan, and reload if it's the eye on show.
bool installFile(const char* eye, const char* file, const uint8_t* data, size_t len);
// Load a texture (.565 or 24-bit .bmp) into PSRAM, big-endian RGB565;
// caller frees with heap_caps_free(). And a 640-byte lids file.
bool loadTexture(const char* path, uint16_t** data, uint16_t* w, uint16_t* h);
bool loadLidsFile(const char* path, Lids& out);
void rescan();  // after changing files behind m4eye's back
void reload();  // re-read the current eye set at the next frame

// --- render hooks, eye task (core 1) / render worker (core 0) ---
// Applies pending config, (re)builds tables and textures. false = can't
// draw (out of memory), caller falls back to another style.
bool beginFrame();
void simulate(int eye, const EyeState& st, bool gazeInvert, uint32_t nowMs);
void renderRow(int eye, int oy, uint16_t* row);  // big-endian RGB565, 160 px

void registerCommands();

}  // namespace m4eye
