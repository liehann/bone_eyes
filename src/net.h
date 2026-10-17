// WiFi (home network or own access point) + a small status web page.
#pragma once

namespace net {

void begin();  // non-blocking after the initial join attempt
void registerCommands();

}  // namespace net
