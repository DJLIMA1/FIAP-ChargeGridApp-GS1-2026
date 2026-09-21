#include "runtime.h"
#include <HTTPClient.h>
#include <WiFiClientSecure.h>

bool probePanelFactoryIdentity(const String& payload) {
  String pendingId = pendingPanelFactoryCommand();
  String pendingKey = pendingPanelFactoryKey();
  if (!pendingId.length() || pendingKey.length() != 43) return false;
  JsonDocument body;
  if (deserializeJson(body, payload)) return false;
  body["acks"].to<JsonArray>(); // The old device's command ID belongs only to its identity.
  String cleanPayload;
  serializeJson(body, cleanPayload);
  WiFiClientSecure tls;
  tls.setCACert(deviceRootCa());
  HTTPClient http;
  http.setTimeout(3000);
  http.setConnectTimeout(3000);
  http.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS);
  if (!http.begin(tls, String(deviceApiBaseUrl()) + "/v1/devices/sync")) return false;
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Authorization", String("Device ") + pendingKey);
  int code = http.POST(cleanPayload);
  JsonDocument response;
  bool confirmed = code == 200 && !deserializeJson(response, http.getString()) &&
      response["connector"]["owned"].is<bool>() &&
      !response["connector"]["owned"].as<bool>() &&
      !response["connector"]["active"].as<bool>();
  http.end();
  if (confirmed) return finishPanelFactoryReset(pendingId);
  return false;
}

void syncDevice() {
  static unsigned long backoffMs = 5000;
  nextSync = millis() + backoffMs;
  backoffMs = min(30000UL, backoffMs * 2);
  if (!String(deviceApiBaseUrl()).startsWith("https://")) return;
  persist(); // Não regredir a energia já enviada após reboot.
  JsonDocument body;
  body["boot_id"] = bootId; body["sequence"] = ++sequence;
  body["firmware_version"] = "0.3.5";
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
  String confirmedReset;
  if (code == 200) {
    JsonDocument response;
    if (!deserializeJson(response, http.getString()) && response["authorized"].is<JsonObject>() && response["commands"].is<JsonArray>()) {
      backoffMs = 5000;
      lastContact = millis();
      hasSynced = true;
      bool changed = apply(response);
      confirmedReset = response["factory_reset_confirmed"].as<String>();
      unsigned long seconds = response["sync_interval_seconds"] | 10UL;
      nextSync = changed ? millis() : millis() + constrain(seconds, 1UL, 30UL) * 1000UL;
    }
  }
  http.end();
  if (confirmedReset.length()) finishPanelFactoryReset(confirmedReset);
  else if (code == 401 && pendingPanelFactoryCommand().length()) probePanelFactoryIdentity(payload);
}
