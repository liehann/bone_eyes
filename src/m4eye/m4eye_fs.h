// M4 eye sets on LittleFS (Phase 2), internal to m4eye. Layout, written by
// tools/m4eye_convert.py --fs data/eyes/<name> and flashed with
// `pio run -t uploadfs`:
//
//   /eyes/<name>/config.json   converted config.eye (160 px radii); names
//                              its textures in irisTexture/scleraTexture
//   /eyes/<name>/iris.565      texture: uint16 LE width, height, then
//   /eyes/<name>/sclera.565    big-endian RGB565 pixels (or a 24-bit .bmp)
//   /eyes/<name>/lids.bin      lid set "<name>": 4 x 160 bytes
//   /eyes/<name>/lids-<x>.bin  further lid set "<x>"
#pragma once
#include <stddef.h>
#include <stdint.h>

#include "m4eye_assets.h"
#include "m4eye_render.h"

namespace m4eye {
namespace store {

bool mount();  // idempotent; false if there's no LittleFS partition/image
void rescan();
int numEyes();
const char* eyeName(int i);  // valid until the next rescan()
bool hasEye(const char* name);
int numLids();
const char* lidName(int i);

// The eye's config.json, malloc'd (caller frees), or nullptr.
char* readConfig(const char* eye);
// Load an eye set: config, textures (PSRAM) and its own lid sets. The
// EyeSet's buffers are owned by it; release with freeEye().
bool loadEye(const char* eye, EyeSet& out);
void freeEye(EyeSet& s);
bool loadLids(const char* lidSet, Lids& out);

}  // namespace store
}  // namespace m4eye
