// Standalone mode: no laptop. Clips from LittleFS (/clips/NNN.clp, made by
// tools/make_standalone_clips.py) play over Bluetooth A2DP to the speaker in
// config.h, with the jaw driven from each clip's envelope.
//
// Only in the env:skull_standalone image (STANDALONE_BUILD): linking the BT
// stack costs ~50 KB of internal heap, so the laptop image (env:skull) leaves
// it out and everything here is a no-op there. Tunables (lat, gap, gain) are
// kept in NVS namespace "standalone".
// Console: mode/bt (status), lat <ms>, gap <s>, gain <%>, play [n], auto on|off.
#pragma once

namespace standalone {

void loadMode();       // read the mode from NVS; call first in setup()
bool active();         // standalone mode this boot
void registerCommands();
// Standalone: start Classic BT (BLE memory released), A2DP and the player.
void begin();

}  // namespace standalone
