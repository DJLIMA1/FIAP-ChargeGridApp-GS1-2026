#include "runtime.h"
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include "kiosk_api.h"
#include "extra_chargers.h"

// Conexão TLS mantida entre syncs (keep-alive): sem novo handshake a cada envio,
// o sync de 1 s em recarga custa ~100-300 ms em vez de 1-2 s. Compartilhada com as rotas
// do totem (deviceRequest), que rodam no mesmo laço e nunca durante uma recarga.
namespace {
WiFiClientSecure deviceTls;
HTTPClient deviceHttpClient;
bool deviceClientReady = false;
constexpr unsigned long kHandshakeTimeoutSeconds = 3;

// O prazo periódico começa ao terminar o lote inteiro, nunca antes dos filhos.
// Pedidos de transição/STOP feitos durante uma operação bloqueante continuam imediatos.
struct SyncBatch {
  uint32_t intervalMs;
  bool immediate = false;
  bool contacted = false;
  uint32_t revision = syncRequests.revision();
  ~SyncBatch() {
    nextSync = syncschedule::afterBatch(millis(), intervalMs,
        immediate || (contacted && revision != syncRequests.revision()));
    if (contacted || immediate) syncRequests.contacted();
    else syncRequests.retryAfter(nextSync);
  }
};
}  // namespace

HTTPClient* deviceHttpBegin(const char* path) {
  if (!deviceClientReady) {
    deviceTls.setCACert(deviceRootCa());
    deviceTls.setHandshakeTimeout(kHandshakeTimeoutSeconds);
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
  tls.setHandshakeTimeout(kHandshakeTimeoutSeconds);
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

// Sync ENDEREÇADO de cada carregador adicional desta tela (mesma chave e conexão TLS do sync da
// tela, "charger_address" no corpo). 409/422 (API sem suporte ou carregador desligado da tela):
// o slot pausa 10 min. Falha de rede: o vigia de 45 s de cada sessão continua valendo.
static bool syncExtraChargers() {
  bool delivered = true;
  for (extra::Slot& slot : extra::slots) {
    if (!extra::syncable(slot, millis())) continue;
    JsonDocument body;
    body["boot_id"] = bootId; body["sequence"] = ++sequence;
    extra::fillBody(slot, body);
    String payload; serializeJson(body, payload);
    HTTPClient* client = deviceHttpBegin("/v1/devices/sync");
    if (!client) return false;
    client->addHeader("Content-Type", "application/json");
    client->addHeader("Authorization", String("Device ") + deviceAuthorizationKey());
    const int code = client->POST(payload);
    const String reply = code > 0 ? client->getString() : String();
    tickAllSessions(); // Antes de atualizar lastContact; inclui cabeçalho e corpo HTTP.
    if (code == 200) {
      JsonDocument response;
      if (!deserializeJson(response, reply) && response["authorized"].is<JsonObject>() &&
          response["commands"].is<JsonArray>()) {
        slot.unsupported = false;
        slot.syncNow = extra::apply(slot, response, millis());
      } else delivered = false;
    } else if (code == 409 || code == 422) {
      extra::markUnsupported(slot, millis());
      Serial.printf("[sync] carregador %u: sync enderecado recusado (%d)\n", slot.address, code);
    } else delivered = false;
    deviceHttpEnd(code);
    serviceChargerLinks(); // Um filho lento não suspende a leitura/STOP dos demais.
    if (code <= 0) return false;  // rede caiu: tenta no próximo ciclo periódico, sem perder ACK/estado
  }
  return delivered;
}

void syncDevice() {
  static unsigned long backoffMs = 5000;
  SyncBatch batch{static_cast<uint32_t>(backoffMs)};
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
  const String reply = code > 0 ? http.getString() : String();
  lastSyncHttpStatus = code;
  // Só um 422 que aponta os campos 0.7.0 rebaixa o corpo; os 422 de regra da API
  // (invalid_time, energy_regression, session_required) mantêm SET_POWER declarado.
  if (code == 422 && !legacyBody && syncRejectedExtensions(reply.c_str())) {
    legacyBody = true; legacySince = millis();
    backoffMs = 5000; batch.immediate = true; // Reenvia já com o corpo anterior.
    Serial.println("[sync] API anterior: campos 0.7.0 recusados; usando corpo 0.6");
  }
  tickAllSessions(); // Inclui o tempo de bloqueio de rede no vigia de todas as sessões.
  String confirmedReset;
  if (code == 200) {
    JsonDocument response;
    if (!deserializeJson(response, reply) && response["authorized"].is<JsonObject>() && response["commands"].is<JsonArray>()) {
      backoffMs = 5000;
      batch.contacted = true;
      lastContact = millis();
      hasSynced = true;
      bool changed = apply(response);
      confirmedReset = response["factory_reset_confirmed"].as<String>();
      unsigned long seconds = response["sync_interval_seconds"] | 10UL;
      batch.immediate = changed;
      batch.intervalMs = constrain(seconds, 1UL, 30UL) * 1000UL;
    }
  }
  deviceHttpEnd(code);
  serviceChargerLinks();
  if (code == 200 && hasSynced && !confirmedReset.length()) {
    const bool extrasDelivered = syncExtraChargers();
    // Carregador adicional em recarga/reserva ou com ACK a enviar: ciclo de 1 s (ou já).
    bool now = false;
    for (const extra::Slot& slot : extra::slots)
      now = now || (extrasDelivered && extra::syncable(slot, millis()) && slot.syncNow);
    if (now) batch.immediate = true;
    else if (extra::busy()) batch.intervalMs = min(batch.intervalMs, uint32_t{1000});
  }
  if (confirmedReset.length()) finishPanelFactoryReset(confirmedReset);
  else if (code == 401 && pendingPanelFactoryCommand().length()) probePanelFactoryIdentity(payload);
}
