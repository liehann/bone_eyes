// Uncanny Eyes artwork tables (Phil Burgess / Adafruit, MIT licence; taken
// from Bodmer's TFT_eSPI Animated_Eyes_2 example). Lid maps are 128x128 and
// get upscaled to the 160x160 panels at render time. `default` and `dragon`
// are compiled in (flash); the other sets are files on LittleFS
// (data/uncanny/, see uncanny_file.h) loaded into PSRAM when picked.
#pragma once
#include <stdint.h>

struct EyeArt {
  const char* name;
  const uint16_t* sclera;
  int scleraW, scleraH;
  const uint16_t* iris;
  int irisMapW, irisMapH;
  const uint8_t* upper;
  const uint8_t* lower;
  int lidSize;  // square
  const uint16_t* polar;
  int irisW, irisH;
  int irisMin, irisMax;  // iris scale range (larger = smaller pupil)
  bool noTracking;       // upper lid doesn't follow the pupil (owl, nauga, doe)
};

extern const EyeArt kDefaultEye;
extern const EyeArt kDragonEye;
