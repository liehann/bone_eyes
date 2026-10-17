#include "net.h"

#include <ESPmDNS.h>
#include <WebServer.h>
#include <WiFi.h>
#include <esp_heap_caps.h>

#include "config.h"
#include "console.h"
#include "eyes.h"

namespace net {
namespace {

WebServer server(80);
bool apMode = false;

String ip() { return (apMode ? WiFi.softAPIP() : WiFi.localIP()).toString(); }

void handleRoot() {
  char body[1024];
  snprintf(body, sizeof(body),
           "<!doctype html><html><head><meta charset=utf-8>"
           "<meta name=viewport content='width=device-width,initial-scale=1'>"
           "<title>bone_eyes</title><style>body{font:16px system-ui;background:#111;color:#eee;"
           "margin:2em}h1{color:#f60}td{padding:2px 12px 2px 0}</style></head><body>"
           "<h1>&#x1F480; bone_eyes</h1><p>Hello from the skull.</p><table>"
           "<tr><td>network</td><td>%s</td></tr>"
           "<tr><td>ip</td><td>%s</td></tr>"
           "<tr><td>uptime</td><td>%lu s</td></tr>"
           "<tr><td>internal heap</td><td>%u bytes</td></tr>"
           "<tr><td>PSRAM free</td><td>%u bytes</td></tr>"
           "<tr><td>eyes</td><td>%.1f fps</td></tr>"
           "</table></body></html>",
           apMode ? "own access point" : WIFI_SSID, ip().c_str(), millis() / 1000,
           heap_caps_get_free_size(MALLOC_CAP_INTERNAL), heap_caps_get_free_size(MALLOC_CAP_SPIRAM),
           eyes::fps());
  server.send(200, "text/html", body);
}

void handleStatus() {
  char body[256];
  snprintf(body, sizeof(body),
           "{\"uptime_s\":%lu,\"heap_internal\":%u,\"heap_psram\":%u,\"eyes_fps\":%.1f,\"rssi\":%d}",
           millis() / 1000, heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
           heap_caps_get_free_size(MALLOC_CAP_SPIRAM), eyes::fps(), apMode ? 0 : WiFi.RSSI());
  server.send(200, "application/json", body);
}

void serverTask(void*) {
  for (;;) {
    server.handleClient();
    vTaskDelay(2);
  }
}

void cmdWifi(int, char**) {
  if (apMode) {
    Serial.printf("wifi: access point \"%s\", %d client(s), http://%s/\n", AP_SSID,
                  WiFi.softAPgetStationNum(), ip().c_str());
  } else {
    Serial.printf("wifi: %s \"%s\", rssi %d dBm, http://%s/ (http://%s.local/)\n",
                  WiFi.isConnected() ? "joined" : "lost", WIFI_SSID, WiFi.RSSI(), ip().c_str(),
                  NET_HOSTNAME);
  }
}

}  // namespace

void begin() {
  WiFi.setHostname(NET_HOSTNAME);
  bool joined = false;
  if (WIFI_SSID[0]) {
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.printf("wifi: joining \"%s\"...", WIFI_SSID);
    for (uint32_t t0 = millis(); millis() - t0 < WIFI_JOIN_TIMEOUT_MS && !joined; delay(100))
      joined = WiFi.status() == WL_CONNECTED;
    Serial.println(joined ? " ok" : " failed, falling back to access point");
  }
  if (!joined) {
    apMode = true;
    WiFi.mode(WIFI_AP);
    WiFi.softAP(AP_SSID, AP_PASSWORD);
  }
  if (MDNS.begin(NET_HOSTNAME)) MDNS.addService("http", "tcp", 80);
  server.on("/", handleRoot);
  server.on("/status", handleStatus);
  server.begin();
  // Core 0 with the WiFi stack; the eyes own core 1.
  xTaskCreatePinnedToCore(serverTask, "http", 4096, nullptr, 1, nullptr, 0);
  cmdWifi(0, nullptr);
}

void registerCommands() { console::add("wifi", "WiFi / web page status", cmdWifi); }

}  // namespace net
