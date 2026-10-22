// Totem 0.8.0: executor das rotas do dispositivo. A lógica fica em kiosk_flow (puro).
#include "kiosk_api.h"
#include <HTTPClient.h>
#include <WiFi.h>
#include "runtime.h"
#include "extra_chargers.h"

#ifdef CHARGEGRID_KIOSK
extern kiosk::Flow kioskFlow;
#endif

int deviceRequest(const char* method, const char* path, const char* body, String& out,
                  const char* idempotencyKey, uint8_t chargerAddress) {
  out = "";
  // Nunca durante uma recarga: o sync de 1 s (watchdog, SET_POWER, STOP) tem prioridade.
  bool otherReady = false;
  for (const auto& slot : extra::slots)
    if (slot.used && slot.active && slot.state == "idle" && slot.link.online()) otherReady = true;
  const bool selectingOther = otherReady && (strcmp(path, "/v1/devices/kiosk/offer") == 0 || strcmp(path, "/v1/auth/login") == 0);
  if (state == "charging" && !selectingOther
#ifdef CHARGEGRID_KIOSK
      && !chargerAddress
#endif
      ) return -10;
  if (!String(deviceApiBaseUrl()).startsWith("https://") || WiFi.status() != WL_CONNECTED) return -10;
  if (!deviceAuthorizationKey()[0]) return -10;
  HTTPClient* client = deviceHttpBegin(path);
  if (!client) return -1;
  HTTPClient& http = *client;
  // Login may include the identity provider's cold start; there is no live session here.
  if (strcmp(path, "/v1/auth/login") == 0) http.setTimeout(8000);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Authorization", String("Device ") + deviceAuthorizationKey());
#ifdef CHARGEGRID_KIOSK
  if (kioskFlow.authToken()[0] && strncmp(path, "/v1/devices/kiosk/", 18) == 0)
    http.addHeader("X-Kiosk-Authorization", String("Bearer ") + kioskFlow.authToken());
  if (chargerAddress && strncmp(path, "/v1/devices/kiosk/", 18) == 0)
    http.addHeader("X-Kiosk-Charger-Address", String(chargerAddress));
#endif
  if (idempotencyKey && idempotencyKey[0]) http.addHeader("Idempotency-Key", idempotencyKey);
  const bool hasBody = body && body[0];
  int code = strcmp(method, "GET") == 0 ? http.GET()
      : http.sendRequest(method, hasBody ? (uint8_t*)body : nullptr, hasBody ? strlen(body) : 0);
  if (code > 0) out = http.getString();
  http.setTimeout(3000);
  deviceHttpEnd(code);
  tickAllSessions(); // Inclui o bloqueio de rede no vigia de todas as sessões da central.
  return code;
}

void kioskApiService() {
#ifdef CHARGEGRID_KIOSK
  kiosk::ApiRequest request;
  if (!kioskFlow.takeRequest(request)) return;
  String body;
  const int code = deviceRequest(request.method, request.path, request.body, body, request.idempotencyKey, request.chargerAddress);
  kiosk::ApiResult result;
  result.kind = request.kind; result.seq = request.seq; result.status = code; result.body = body.c_str();
  kioskFlow.apiResult(result);
  Serial.printf("[kiosk] %s %s -> %d\n", request.method, request.path, code);
#endif
}
