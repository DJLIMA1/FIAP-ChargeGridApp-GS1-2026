#pragma once
// Lógica do carregador GoodWe HCA G2 SIMULADO (registradores, relé, watchdog, energia).
// C++ puro, sem Arduino: o firmware (src/main.cpp), o servidor de host
// (host/hca_sim_host.cpp) e os testes (tools/tests/hca_sim_test.cpp) usam este mesmo código.
//
// Regras (docs/carregador-hca-simulado.md):
// - o relé fecha só com 10060 = 2, 10029 >= mínimo e sem falha;
// - abre com 10060 = 1, 10029 abaixo do mínimo (pausa), watchdog (15 s sem nenhuma leitura
//   ou escrita do mestre), reset e boot; depois do watchdog o 10060 volta a 1, então o relé
//   só fecha de novo com um novo comando 10060 = 2; o status 5 (alarme) e a falha 19004
//   continuam visíveis nas leituras até a próxima escrita do mestre;
// - 10015 é SIMULADO: igual ao 10029 com o relé fechado (o celular consome bem menos), 0 aberto;
// - a energia (extensão 19001/19002) integra a potência simulada.
#include <stdint.h>
#include "hca_g2_map.h"
#include "modbus_tcp.h"

namespace hcasim {

class Charger : public mbtcp::RegisterBank {
 public:
  explicit Charger(const hca::Model& model = hca::kGw7k, uint8_t address = hca::kDefaultAddress);

  // Boot/reset: relé aberto, 10060 = 1, sem falha, watchdog desarmado, energia zerada.
  // 10029 e 10032 vêm da memória persistente (o HCA real grava em flash).
  void boot(uint32_t nowMs, uint16_t savedMaxTenths, uint16_t savedChargeMode);

  // Acesso do mestre (FC03/FC06/FC16). Retorna 0 ou exceção Modbus (02 endereço, 03 valor).
  // Toda chamada conta como contato do mestre (alimenta o watchdog).
  uint8_t readHolding(uint16_t address, uint16_t count, uint16_t* out) override;
  uint8_t writeHolding(uint16_t address, uint16_t count, const uint16_t* values) override;

  // Relógio: o firmware chama a cada volta do loop; leitura/escrita usam o último instante.
  void tick(uint32_t nowMs);

  // Falha local (ex.: erro de hardware): abre o relé, 10060 = 1, status alarme.
  void forceFault(uint16_t faultCode);

  bool relayClosed() const { return relay_; }
  uint16_t reg(uint16_t address) const;  // valor atual (0 = não mapeado)
  uint32_t energyWh() const { return static_cast<uint32_t>(energyMilliJoules_ / 3600000ULL); }
  uint16_t fault() const { return fault_; }
  uint8_t address() const { return address_; }
  bool setAddress(uint8_t address);  // 1..247
  bool watchdogArmed() const { return masterSeen_; }
  uint32_t msSinceMaster() const { return masterSeen_ ? now_ - lastMasterMs_ : 0; }
  const hca::Model& model() const { return model_; }
  // 10029/10032 mudaram desde a última consulta (o firmware grava na NVS).
  bool takePersistentChange();
  uint32_t relayChanges() const { return relayChanges_; }

 private:
  void contact(bool write);
  void advance(uint32_t nowMs);
  void evaluate();
  bool writable(uint16_t address) const;
  uint8_t validate(uint16_t address, uint16_t value) const;

  hca::Model model_;
  uint8_t address_;
  uint16_t maxTenths_ = 0, chargeMode_ = hca::kFastMode, startStop_ = hca::kStopValue;
  uint16_t emsDispatch_ = 0;
  uint16_t settings_[21] = {};  // 10019..10039 graváveis sem efeito no simulado (exceto 10029/10032)
  uint16_t fault_ = hca::kFaultNone;
  bool relay_ = false, masterSeen_ = false, persistentChanged_ = false;
  uint32_t now_ = 0, lastMasterMs_ = 0, lastTickMs_ = 0, relayChanges_ = 0;
  uint64_t energyMilliJoules_ = 0;  // W·ms
};

}  // namespace hcasim
