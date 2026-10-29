// WiFi (home network or own access point) + the settings / status web page.
#pragma once

namespace net {

void begin();  // non-blocking after the initial join attempt
void registerCommands();

}  // namespace net
