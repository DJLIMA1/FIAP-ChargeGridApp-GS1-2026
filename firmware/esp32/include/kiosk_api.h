#pragma once
// Rotas do dispositivo para o totem (/v1/devices/kiosk/*), reaproveitando a conexão TLS
// keep-alive do sync. Executa no laço principal (mesma tarefa do sync), nunca durante
// charging, timeout curto (3 s) e Idempotency-Key quando o fluxo manda.
#include <Arduino.h>

class HTTPClient;
// Conexão compartilhada com o sync (api_client.cpp). begin() no caminho; end() com o código
// HTTP (<= 0 derruba a conexão para o próximo envio refazer o handshake).
HTTPClient* deviceHttpBegin(const char* path);
void deviceHttpEnd(int code);

// Retorna o status HTTP (out = corpo) ou <= 0 sem resposta: -10 recusado localmente
// (recarga em andamento, sem rede/chave/API https).
int deviceRequest(const char* method, const char* path, const char* body, String& out,
                  const char* idempotencyKey = nullptr, uint8_t chargerAddress = 0);
