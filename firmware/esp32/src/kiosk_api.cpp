// Totem 0.8.0: executor das rotas do dispositivo. A lógica fica em kiosk_flow (puro).
#include "kiosk_api.h"
#include <HTTPClient.h>
#include <WiFi.h>
#include "runtime.h"

#ifdef CHARGEGRID_KIOSK
extern kiosk::Flow kioskFlow;
#endif

int deviceRequest(const char* method, const char* path, const char* body, String& out,
                  const char* idempotencyKey) {
  out = "";
  // Nunca durante uma recarga: o sync de 1 s (watchdog, SET_POWER, STOP) tem prioridade.
  if (state == "charging") return -10;
  if (!String(deviceApiBaseUrl()).startsWith("https://") || WiFi.status() != WL_CONNECTED) return -10;
  if (!deviceAuthorizationKey()[0]) return -10;
  HTTPClient* client = deviceHttpBegin(path);
  if (!client) return -1;
  HTTPClient& http = *client;
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Authorization", String("Device ") + deviceAuthorizationKey());
  if (idempotencyKey && idempotencyKey[0]) http.addHeader("Idempotency-Key", idempotencyKey);
  const bool hasBody = body && body[0];
  int code = strcmp(method, "GET") == 0 ? http.GET()
      : http.sendRequest(method, hasBody ? (uint8_t*)body : nullptr, hasBody ? strlen(body) : 0);
  if (code > 0) out = http.getString();
  deviceHttpEnd(code);
  tickAllSessions(); // Inclui o bloqueio de rede no vigia de todas as sessões da central.
  return code;
}

void kioskApiService() {
#ifdef CHARGEGRID_KIOSK
  kiosk::ApiRequest request;
  if (!kioskFlow.takeRequest(request)) return;
  String body;
  const int code = deviceRequest(request.method, request.path, request.body, body, request.idempotencyKey);
  kiosk::ApiResult result;
  result.kind = request.kind; result.seq = request.seq; result.status = code; result.body = body.c_str();
  kioskFlow.apiResult(result);
  Serial.printf("[kiosk] %s %s -> %d\n", request.method, request.path, code);
#endif
}
