// Jaw servo (MG90S on PIN_SERVO). Closed/open angles live in settings (NVS);
// every command is clamped between them and slew-limited so the jaw can't slam.
// Console: jaw, jaw <deg>, jaw closed|open <deg>, jaw save, jaw test; brain link: !j <0-1000>.
#pragma once
#include <Arduino.h>

namespace jaw {

void begin();  // attach PWM, go to closed
void registerCommands();

// 0 = closed, 1000 = fully open; clamped, slew-limited.
void setOpening(int per_mille);
// Raw servo angle for calibration: NOT limited to closed/open (0..180 only).
void setRawAngle(float deg);
// Sweep closed -> open -> closed 3 times (blocks ~3 s in the caller).
void test();
float angle();  // current slewed angle

}  // namespace jaw
