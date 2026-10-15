#include <Arduino.h>

#include "eye_art.h"

namespace {
#include "dragonEye.h"
#ifndef IRIS_MIN
#define IRIS_MIN 90
#define IRIS_MAX 130
#endif
}  // namespace

const EyeArt kDragonEye = {"dragon", sclera, SCLERA_WIDTH, SCLERA_HEIGHT, iris, IRIS_MAP_WIDTH, IRIS_MAP_HEIGHT,
                         upper, lower, SCREEN_WIDTH, polar, IRIS_WIDTH, IRIS_HEIGHT, IRIS_MIN, IRIS_MAX};
