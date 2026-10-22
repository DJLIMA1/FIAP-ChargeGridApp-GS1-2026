#pragma once
// Carregadores ADICIONAIS da tela (capacidade multi_charger_v1). Estação = a tela; cada ponto é
// um carregador GoodWe HCA G2 com endereço Modbus. O ponto da própria tela continua no
// controlador principal (charging_controller.cpp, com a interface do painel); os outros
// carregadores do posto ligados a esta tela vêm em "chargers" na resposta do sync dela e cada
// um tem aqui uma sessão própria, sem interface: iniciada/encerrada pelo app, comandos e
// telemetria pelo sync ENDEREÇADO (mesma chave, "charger_address" no corpo), sempre por Modbus
// (sem simulação interna), com as mesmas paradas seguras locais (45 s sem a API, duração,
// valor, perda/alarme do carregador). Limitações (docs/esp32-protocol.md): sem SoC/permanência
// /totem nos adicionais; até kMaxSlots carregadores adicionais por tela.
// C++ com String/ArduinoJson: os testes de host (tools/tests/firmware_behavior.cpp) usam este código.
#include <ArduinoJson.h>
#include "charger_link.h"
#include "kiosk_flow.h"

namespace extra {

constexpr uint8_t kMaxSlots = 3;
constexpr unsigned long kContactLossMs = 45000;   // mesmo vigia do ponto da tela
constexpr unsigned long kUnsupportedMs = 600000;  // sync endereçado recusado: tenta de novo em 10 min

struct Slot {
  bool used = false;
  uint8_t address = 0;
  charger::Link link;
  String sessionId, lastCommand, state = "idle", endReason;
  uint32_t version = 0;
  bool active = true, connected = false, syncNow = false;
  float energyWh = 0, limitW = 0, price = 0, discount = 0, maxCost = -1;
  unsigned long started = 0, lastTick = 0, lastContact = 0, lastSaved = 0, maxDurationMs = 3600000;
  unsigned long unsupportedUntil = 0;
  bool unsupported = false;
  time_t reservationDeadline = 0;
  JsonDocument acks;
  kiosk::SyncFacts kioskSync;
};

extern Slot slots[kMaxSlots];

// Cliente Modbus de cada slot (ESP32: um WiFiClient por carregador; testes: o falso).
void setClient(uint8_t index, charger::ModbusClient* client);
// "chargers" da resposta do sync da tela ([{address, charger_link}]); API antiga = vazio.
// Slot com recarga em andamento nunca é descartado nem muda de carregador.
void configure(JsonArrayConst chargers, unsigned long now);
// Corpo do sync endereçado (sem boot_id/sequence).
void fillBody(Slot& slot, JsonDocument& body);
// Resposta do sync endereçado: comandos e autorização deste carregador. true = algo mudou.
bool apply(Slot& slot, JsonDocument& response, unsigned long now);
// Relógio local da sessão do slot (energia pela potência lida no carregador e paradas seguras).
void tick(Slot& slot, unsigned long now);
// Leitura de cada carregador (~1 s) e parada segura se ele sumir durante a recarga.
void service(unsigned long now);
// Parada local (motivo do sync); com o carregador, 10060 = 1 confirmado por releitura.
charger::Error stop(Slot& slot, const char* reason);
// Reboot da tela: sessão do diário relatada como stopped/device_reboot, nunca retomada.
void restore(uint8_t address, const char* sessionId, float energyWh, uint32_t version, const char* lastCommand,
             unsigned long now);
// Sync endereçado recusado (API sem suporte ou carregador desligado da tela): pausa o slot.
void markUnsupported(Slot& slot, unsigned long now);
bool syncable(const Slot& slot, unsigned long now);
// Algum slot em recarga, reservado ou com ACK a enviar (o sync volta a 1 s).
bool busy();
void persist(Slot& slot);

}  // namespace extra
