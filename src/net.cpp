#include "net.h"

#include <ESPmDNS.h>
#include <WebServer.h>
#include <WiFi.h>
#include <esp_heap_caps.h>

#include "config.h"
#include "console.h"
#include "eyes.h"
#include "settings.h"

namespace net {
namespace {

WebServer server(80);
bool apMode = false;

String ip() { return (apMode ? WiFi.softAPIP() : WiFi.localIP()).toString(); }

// Settings page, served straight from flash. Plain HTML/JS, no CDN (the
// skull may be on its own access point). Talks to /api/config, /api/eyes and
// /status.
const char kPage[] PROGMEM = R"HTML(<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>bone_eyes</title>
<style>
body{font:16px system-ui,sans-serif;background:#111;color:#eee;margin:0 auto;padding:1em;max-width:34em}
h1{color:#f60;margin:.2em 0}h2{font-size:1em;color:#f90;margin:1.4em 0 .4em;border-bottom:1px solid #333}
label{display:flex;justify-content:space-between;align-items:center;gap:1em;padding:.35em 0}
select,input,button{font:inherit;background:#222;color:#eee;border:1px solid #444;border-radius:6px;padding:.3em .6em}
input[type=range]{flex:1;padding:0}input[type=number]{width:6em}input[type=checkbox]{width:1.3em;height:1.3em;accent-color:#f60}
button{cursor:pointer}button.main{background:#f60;color:#111;border-color:#f60;font-weight:600}
.row{display:flex;gap:.5em;flex-wrap:wrap;margin:.6em 0}small{color:#999}#msg{color:#fc6;min-height:1.3em}
td{padding:2px 12px 2px 0}
</style></head><body>
<h1>&#x1F480; bone_eyes</h1><div id=msg></div>
<h2>Eyes</h2>
<label>Style <select id=style><option value=default>regular (hazel)</option><option value=dragon>dragon</option><option value=fire>fire</option><option value=m4>M4 eye (settings below)</option></select></label>
<div id=ovr><small></small></div>
<label>Brightness <input type=range id=brightness min=0 max=255><span id=brightness_v></span></label>
<label>Rotation left eye <select id=rot_l></select></label>
<label>Rotation right eye <select id=rot_r></select></label>
<label>Mirror gaze left/right <input type=checkbox id=gaze_invert></label>
<div class=row><button id=test>Eyes test</button><button id=anim>Animate</button><button id=blinknow>Blink</button>
<select id=mood><option>idle</option><option>alert</option><option>talking</option><option>goodbye</option></select></div>
<h2>Effects</h2>
<label>Flames around regular/dragon eyes <input type=checkbox id=flames></label>
<label>Smoke from flame tips <input type=checkbox id=smoke></label>
<label>Fire eye flame length % <input type=number id=fire_len min=50 max=150 step=5></label>
<h2>M4 eye</h2>
<label>Eye set <select id=m4_eye></select></label>
<label>Eyelid shape <select id=m4_lids></select></label>
<label>Iris tint <input type=color id=m4_irisTint></label>
<label>Sclera tint <input type=color id=m4_scleraTint></label>
<label>Iris size px <input type=range id=m4_irisRadius min=10 max=83></label>
<label>Slit pupil px (0 = round) <input type=range id=m4_slitPupilRadius min=0 max=83></label>
<label>Pupil min <input type=range id=m4_pupilMin min=0 max=1 step=.01></label>
<label>Pupil max <input type=range id=m4_pupilMax min=0 max=1 step=.01></label>
<label>Eye tracking range <input type=range id=m4_gazeRange min=0 max=1 step=.05></label>
<label>Lids follow the pupil <input type=checkbox id=m4_tracking></label>
<label>Mirror lid art <input type=checkbox id=m4_lidMirror></label>
<label>Extra blinks per minute <input type=number id=m4_blinkRate min=0 max=120 step=1></label>
<div class=row><button id=m4_reset>M4 eye set defaults</button></div>
<h2>Behaviour</h2>
<label>Blink on its own <input type=checkbox id=blink></label>
<label>Blink gap min ms <input type=number id=blink_min_ms min=500 max=20000 step=100></label>
<label>Blink gap max ms <input type=number id=blink_max_ms min=500 max=20000 step=100></label>
<label>Look around when idle <input type=checkbox id=wander></label>
<label>Cross-eyed when someone is close <input type=checkbox id=verge></label>
<label>Pupils react to mood <input type=checkbox id=pupil_react></label>
<div class=row><button class=main id=save>Save</button><button id=reset>Reset to defaults</button></div>
<small>Changes apply at once. Save keeps them across reboots.</small>
<h2>Status</h2><table id=st></table>
<script>
const $=id=>document.getElementById(id);
for(const r of['rot_l','rot_r'])for(const d of[0,90,180,270])$(r).add(new Option(d+'°',d));
const msg=t=>{$('msg').textContent=t;clearTimeout(msg.t);msg.t=setTimeout(()=>$('msg').textContent='',3000)};
const hex=a=>'#'+a.map(v=>v.toString(16).padStart(2,'0')).join('');
function opts(e,list,extra){const v=[...extra,...list].join();if(e.dataset.v==v)return;e.dataset.v=v;e.length=0;
 for(const [t,val] of extra.map(x=>[x||"eye's own",x]).concat(list.map(x=>[x,x])))e.add(new Option(t,val))}
function showM4(m,sets){if(!m)return;if(sets){opts($('m4_eye'),sets.eyes,[]);opts($('m4_lids'),sets.lids,['','none'])}
 for(const k in m){const e=$('m4_'+k);if(!e||document.activeElement===e)continue;
  if(e.type=='checkbox')e.checked=m[k];else e.value=Array.isArray(m[k])?hex(m[k]):m[k]}}
function show(c){showM4(c.m4,c.m4_sets);for(const k in c){const e=$(k);if(!e)continue;
 if(e.type=='checkbox')e.checked=c[k];else if(document.activeElement!==e)e.value=c[k]}
 $('brightness_v').textContent=c.brightness;
 $('ovr').firstChild.textContent=c.style_override?'The brain is showing "'+c.style_override+'" for the current persona; picking a style here takes over.':''}
async function post(q,b){try{const r=await fetch('/api/config'+q,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b||{})});
 const c=await r.json();if(c.error)msg('Error: '+c.error);show(c);return c}catch(e){msg('Skull unreachable')}}
document.querySelectorAll('[id^=m4_]').forEach(e=>{if(e.tagName=='BUTTON')return;
 const send=()=>post('',{m4:{[e.id.slice(3)]:e.type=='checkbox'?e.checked:e.type=='color'||e.tagName=='SELECT'?e.value:Number(e.value)}});
 if(e.type=='range'){e.oninput=()=>{clearTimeout(e.t);e.t=setTimeout(send,150)}}else e.onchange=send});
$('m4_reset').onclick=()=>post('',{m4:{reset:true}});
document.querySelectorAll('input,select').forEach(e=>{if(e.id=='mood'||e.id.startsWith('m4_'))return;
 const send=()=>post('',{[e.id]:e.type=='checkbox'?e.checked:e.id=='style'?e.value:Number(e.value)});
 if(e.type=='range')e.oninput=()=>{$('brightness_v').textContent=e.value;clearTimeout(e.t);e.t=setTimeout(send,120)};
 else e.onchange=send});
$('mood').onchange=()=>post('',{mood:$('mood').value});
$('save').onclick=async()=>{if(await post('?save=1'))msg('Saved')};
$('reset').onclick=async()=>{if(confirm('Restore the defaults and save them?')&&await post('?reset=1'))msg('Defaults restored')};
const eyes=c=>fetch('/api/eyes?cmd='+c,{method:'POST'}).then(()=>msg(c=='test'?'Test pattern up; Animate to go back':'')).catch(()=>msg('Skull unreachable'));
$('test').onclick=()=>eyes('test');$('anim').onclick=()=>eyes('anim');$('blinknow').onclick=()=>eyes('blink');
async function status(){try{const s=await(await fetch('/status')).json();
 const kb=b=>(b/1024).toFixed(1)+' KB';
 const rows=[['network',s.ap?'own access point':s.network],['ip',s.ip],['uptime',s.uptime_s+' s'],['internal heap',kb(s.heap_internal)],
  ['PSRAM free',kb(s.heap_psram)],['eyes',s.eyes_fps.toFixed(1)+' fps, '+s.style+', '+s.mood],['rssi',s.ap?'-':s.rssi+' dBm']];
 $('st').innerHTML='';for(const[k,v]of rows){const tr=$('st').insertRow();tr.insertCell().textContent=k;tr.insertCell().textContent=v}
 if(document.activeElement!==$('mood'))$('mood').value=s.mood}catch(e){}}
fetch('/api/config').then(r=>r.json()).then(show);status();setInterval(status,2000);
</script></body></html>)HTML";

void handleRoot() { server.send_P(200, "text/html", kPage, sizeof(kPage) - 1); }

void sendConfig(const char* error = nullptr) {
  static char body[2048];  // one server task, so one buffer (settings + the nested m4 object)
  size_t n = settings::toJson(body, sizeof body);
  if (error && n > 1) snprintf(body + n - 1, sizeof body - (n - 1), ",\"error\":\"%s\"}", error);
  server.send(error ? 400 : 200, "application/json", body);
}

void handleGetConfig() { sendConfig(); }

// POST /api/config: a partial JSON object (or form fields) of settings to
// apply live. ?save=1 (or "save":1) persists them, ?reset=1 restores and
// saves the defaults. "mood" sets the eye mood (live only, not saved).
void handlePostConfig() {
  static char err[48];
  const char* error = nullptr;
  bool save = server.arg("save") == "1", reset = server.arg("reset") == "1";
  Serial.printf("web: settings change from %s\n", server.client().remoteIP().toString().c_str());
  if (reset) settings::reset();
  for (int i = 0; i < server.args(); i++) {
    const String k = server.argName(i), v = server.arg(i);
    if (k == "save" || k == "reset") continue;
    if (k == "plain") {
      const char* bad;
      settings::applyJson(v.c_str(), &bad);
      if (bad) error = (snprintf(err, sizeof err, "bad value for %s", bad), err);
      if (v.indexOf("\"save\":1") >= 0 || v.indexOf("\"save\":true") >= 0) save = true;
      const int m = v.indexOf("\"mood\"");
      if (m >= 0) {
        const int q = v.indexOf('"', v.indexOf(':', m) + 1);
        Mood mood;
        if (q >= 0 && eyes::parseMood(v.substring(q + 1, v.indexOf('"', q + 1)).c_str(), mood)) eyes::setMood(mood);
        else error = "bad mood";
      }
    } else if (k == "mood") {
      Mood mood;
      if (eyes::parseMood(v.c_str(), mood)) eyes::setMood(mood);
      else error = "bad mood";
    } else if (settings::applyKey(k.c_str(), v.c_str()) < 0) {
      error = (snprintf(err, sizeof err, "bad value for %s", k.c_str()), err);
    }
  }
  if (save && !settings::save()) error = "save failed";
  sendConfig(error);
}

// POST /api/eyes?cmd=test|anim|blink
void handleEyes() {
  const String c = server.arg("cmd");
  if (c == "test") eyes::test(2);
  else if (c == "anim") eyes::animate();
  else if (c == "blink") eyes::blink();
  else return server.send(400, "application/json", "{\"error\":\"cmd: test|anim|blink\"}");
  server.send(200, "application/json", "{\"ok\":true}");
}

void handleStatus() {
  char body[384];
  snprintf(body, sizeof(body),
           "{\"uptime_s\":%lu,\"heap_internal\":%u,\"heap_psram\":%u,\"eyes_fps\":%.1f,\"rssi\":%d,"
           "\"ap\":%s,\"network\":\"%s\",\"ip\":\"%s\",\"mood\":\"%s\",\"style\":\"%s\"}",
           millis() / 1000, heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
           heap_caps_get_free_size(MALLOC_CAP_SPIRAM), eyes::fps(), apMode ? 0 : WiFi.RSSI(),
           apMode ? "true" : "false", apMode ? AP_SSID : WIFI_SSID, ip().c_str(), eyes::moodName(eyes::mood()),
           settings::kStyleNames[settings::effectiveStyle()]);
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
  server.on("/api/config", HTTP_GET, handleGetConfig);
  server.on("/api/config", HTTP_POST, handlePostConfig);
  server.on("/api/eyes", HTTP_POST, handleEyes);
  server.begin();
  // Core 0 with the WiFi stack and the LCD render worker; the eye task owns core 1.
  xTaskCreatePinnedToCore(serverTask, "http", 5120, nullptr, 1, nullptr, 0);
  cmdWifi(0, nullptr);
}

void registerCommands() { console::add("wifi", "WiFi / web page status", cmdWifi); }

}  // namespace net
