#include "runtime.h"
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
void syncDevice() {
  static unsigned long backoffMs = 5000;
  nextSync = millis() + backoffMs;
  backoffMs = min(30000UL, backoffMs * 2);
  if (!String(deviceApiBaseUrl()).startsWith("https://")) return;
  persist(); // Não regredir a energia já enviada após reboot.
  JsonDocument body;
  body["boot_id"] = bootId; body["sequence"] = ++sequence;
  body["firmware_version"] = "0.3.3";
  if (sessionId.length()) body["session_id"] = sessionId; else body["session_id"] = nullptr;
  body["physical_state"] = state; body["connected"] = reading.connected;
  if (sessionId.length()) body["soc_percent"] = reading.socPercent; else body["soc_percent"] = nullptr;
  body["energy_wh"] = reading.energyWh; body["power_w"] = reading.powerW;
  body["source"] = "simulated"; body["captured_at"] = isoTime();
  if (endReason.length()) body["end_reason"] = endReason; else body["end_reason"] = nullptr;
  body["acks"] = acknowledgements.as<JsonArray>();
  String payload; serializeJson(body, payload);
  WiFiClientSecure tls;
  tls.setCACert(deviceRootCa());
  HTTPClient http;
  http.setTimeout(3000);
  http.setConnectTimeout(3000);
  http.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS);
  if (!http.begin(tls, String(deviceApiBaseUrl()) + "/v1/devices/sync")) return;
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Authorization", String("Device ") + deviceAuthorizationKey());
  int code = http.POST(payload);
  lastSyncHttpStatus = code;
  tick(); // Inclui o tempo de bloqueio de rede no watchdog.
  if (code == 200) {
    JsonDocument response;
    if (!deserializeJson(response, http.getString()) && response["authorized"].is<JsonObject>() && response["commands"].is<JsonArray>()) {
      backoffMs = 5000;
      lastContact = millis();
      hasSynced = true;
      bool changed = apply(response);
      unsigned long seconds = response["sync_interval_seconds"] | 10UL;
      nextSync = changed ? millis() : millis() + constrain(seconds, 1UL, 30UL) * 1000UL;
    }
  }
  http.end();
}
