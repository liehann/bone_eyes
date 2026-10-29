// Uncanny Eyes sets on LittleFS (/uncanny/<name>.eye, from data/uncanny/ via
// `pio run -t uploadfs`), loaded into PSRAM one at a time. Eye task only.
#pragma once
#include "eye_art.h"

namespace uncanny_store {

// The set `name`, loading it (100-200 ms) and freeing the previous one if
// needed. nullptr if the file is missing or bad; a failed name isn't retried
// until retry() (the LCD backend calls it when the style changes).
const EyeArt* load(const char* name);
void retry();

}  // namespace uncanny_store
