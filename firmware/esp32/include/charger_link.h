#pragma once
// Carregador externo GoodWe HCA G2 (simulado no ESP32 DevKit) ligado à tela por Modbus TCP.
// C++ puro, sem Arduino: a tradução START/STOP/SET_POWER → registradores, a confirmação por
// leitura e a detecção de perda são testadas no host (tools/tests/charger_link_test.cpp).
// O transporte de verdade (WiFiClient + mDNS) fica em src/charger_modbus_esp32.cpp.
//
// Todo conector é um carregador: a API manda connector.charger_link (endereço) e a tela lê o
// carregador sempre (~1 s online; 5 s offline). No START, online → recarga por Modbus; offline →
// simulação interna da tela (o controlador decide; ver sessionOnCharger). API antiga, sem
// charger_link: nada aqui é chamado.
#include <stddef.h>
#include <stdint.h>
#include "hca_g2_map.h"

namespace charger {

constexpr uint32_t kPollMs = 1000;        // leitura de 10015..10017 a cada ~1 s
constexpr uint32_t kIdleRetryMs = 5000;   // fora de recarga e offline: tenta a cada 5 s
constexpr uint32_t kLossMs = 5000;        // sem resposta por 5 s durante a recarga = perda
constexpr uint8_t kStoppedPolls = 3;      // parado sozinho por 3 leituras durante a recarga = falha

struct LinkConfig {
  bool present = false;
  uint8_t address = 0;           // unit id (1..247)
  uint16_t port = hca::kDefaultPort;
  char host[64] = {};            // "cg-hca-1.local" ou IP
};
bool sameConfig(const LinkConfig& a, const LinkConfig& b);
// Valida connector.charger_link (model goodwe_hca_g2, transport modbus_tcp, address 1..247,
// host opcional com [A-Za-z0-9.-], até 63; sem host: cg-hca-<address>.local). Inválido: false.
bool makeConfig(const char* model, const char* transport, long address, const char* host, long port, LinkConfig& out);

// Transporte Modbus (uma conexão, timeouts curtos). false = sem resposta válida; quando o
// carregador responde com exceção Modbus, `exception` recebe o código (senão 0).
class ModbusClient {
 public:
  virtual ~ModbusClient() = default;
  virtual bool readHolding(const LinkConfig& link, uint16_t address, uint16_t count, uint16_t* out,
                           uint8_t* exception) = 0;
  virtual bool writeSingle(const LinkConfig& link, uint16_t address, uint16_t value, uint8_t* exception) = 0;
  virtual void reset() {}  // descarta conexão e resolução (link mudou)
};

enum class Error : uint8_t { None, NoLink, Offline, Rejected, ReadbackMismatch };
// Erro curto do ACK "failed" (≤ 40 caracteres).
const char* errorCode(Error error);

class Link {
 public:
  void setClient(ModbusClient* client) { client_ = client; }
  // true = mudou (zera o estado; a próxima recarga reescreve o modo 10032).
  bool configure(const LinkConfig& config);
  bool active() const { return config_.present && client_ != nullptr; }
  bool configured() const { return config_.present; }
  const LinkConfig& config() const { return config_; }

  // Comandos síncronos e curtos. Só retornam None depois de confirmar pela releitura.
  // START: 10032 = 0 (uma vez por link), 10029 = limite (só se mudou), 10060 = 2.
  // Limite abaixo do mínimo (ou 0): começa pausado (10060 = 1).
  Error start(long limitW, uint32_t nowMs, long* appliedW);
  // SET_POWER: 10029 (só se mudou) e 10060 = 2; abaixo do mínimo pausa com 10060 = 1.
  Error setPower(long limitW, uint32_t nowMs, long* appliedW);
  // STOP: 10060 = 1, confirmado por 10060 = 1 e 10015 = 0. Sem confirmação, tenta de novo
  // a cada leitura periódica (e o watchdog de 15 s do carregador abre o relé).
  Error stop(uint32_t nowMs);

  // Leitura periódica (chamar a cada volta do loop; ela mesma espaça em ~1 s).
  void poll(uint32_t nowMs);
  // Sessão em andamento (session = state "charging", inclusive pausada) e o carregador sumiu
  // por 5 s; ou, ligado, entrou em alarme/falha ao iniciar ou parou sozinho (3 leituras).
  bool faulted(uint32_t nowMs, bool session) const;

  bool online() const { return online_; }
  bool polled() const { return polled_; }  // false = ainda sem leitura desde configure()
  bool expectRunning() const { return expectRunning_; }
  long measuredPowerW() const { return hca::powerWForRegister(power_); }  // 10015 (SIMULADO no simulador)
  uint16_t status() const { return status_; }
  int limitRegister() const { return limit29_; }  // -1 = desconhecido
  int startStopRegister() const { return run60_; }
  uint16_t failures() const { return failures_; }
  Error lastError() const { return lastError_; }
  bool pendingStop() const { return pendingStop_; }

 private:
  bool read(uint16_t address, uint16_t count, uint16_t* out, Error& error);
  bool write(uint16_t address, uint16_t value, Error& error);
  bool readLive(Error& error);
  Error apply(uint16_t value);

  ModbusClient* client_ = nullptr;
  LinkConfig config_;
  bool online_ = false, modeWritten_ = false, expectRunning_ = false, pendingStop_ = false, polled_ = false;
  uint16_t power_ = 0, status_ = 0, failures_ = 0;
  uint8_t stoppedPolls_ = 0;
  int limit29_ = -1, run60_ = -1;
  uint32_t lastPollMs_ = 0, lastOkMs_ = 0, now_ = 0;
  Error lastError_ = Error::None;
};

}  // namespace charger
