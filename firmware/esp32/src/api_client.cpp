#include "runtime.h"
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include "kiosk_api.h"

// Conexão TLS mantida entre syncs (keep-alive): sem novo handshake a cada envio,
// o sync de 1 s em recarga custa ~100-300 ms em vez de 1-2 s. Compartilhada com as rotas
// do totem (deviceRequest), que rodam no mesmo laço e nunca durante uma recarga.
namespace {
WiFiClientSecure deviceTls;
HTTPClient deviceHttpClient;
bool deviceClientReady = false;
}  // namespace

HTTPClient* deviceHttpBegin(const char* path) {
  if (!deviceClientReady) {
    deviceTls.setCACert(deviceRootCa());
    deviceHttpClient.setReuse(true);
    deviceHttpClient.setTimeout(3000);
    deviceHttpClient.setConnectTimeout(3000);
    deviceHttpClient.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS);
    deviceClientReady = true;
  }
  if (!deviceHttpClient.begin(deviceTls, String(deviceApiBaseUrl()) + path)) { deviceTls.stop(); return nullptr; }
  return &deviceHttpClient;
}
void deviceHttpEnd(int code) {
  deviceHttpClient.end();
  if (code <= 0) deviceTls.stop(); // conexão quebrada: o próximo envio refaz o handshake
}

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
  // API anterior à 0.7.0 recusa campos desconhecidos (422): o ponto volta ao corpo 0.6
  // e continua funcionando como carga fixa; tenta de novo os campos novos a cada 10 min
  // apenas ocioso, para nunca perder um sync com sessão por causa da sondagem.
  static bool legacyBody = false;
  static unsigned long legacySince = 0;
  if (legacyBody && millis() - legacySince >= 600000UL && state == "idle" && !sessionId.length()) legacyBody = false;
  JsonDocument body;
  body["boot_id"] = bootId; body["sequence"] = ++sequence;
  fillSyncBody(body, !legacyBody);
  String payload; serializeJson(body, payload);
  HTTPClient* client = deviceHttpBegin("/v1/devices/sync");
  if (!client) return;
  HTTPClient& http = *client;
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Authorization", String("Device ") + deviceAuthorizationKey());
  int code = http.POST(payload);
  lastSyncHttpStatus = code;
  // Só um 422 que aponta os campos 0.7.0 rebaixa o corpo; os 422 de regra da API
  // (invalid_time, energy_regression, session_required) mantêm SET_POWER declarado.
  if (code == 422 && !legacyBody && syncRejectedExtensions(http.getString().c_str())) {
    legacyBody = true; legacySince = millis();
    backoffMs = 5000; nextSync = millis(); // Reenvia já com o corpo anterior.
    Serial.println("[sync] API anterior: campos 0.7.0 recusados; usando corpo 0.6");
  }
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
  deviceHttpEnd(code);
  if (confirmedReset.length()) finishPanelFactoryReset(confirmedReset);
  else if (code == 401 && pendingPanelFactoryCommand().length()) probePanelFactoryIdentity(payload);
}
