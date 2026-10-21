#include "hca_sim_core.h"

namespace hcasim {
namespace {
constexpr uint16_t kSettingsFirst = 10019, kSettingsLast = 10039;
bool inRange(uint16_t address, uint16_t count, uint16_t first, uint16_t last) {
  return address >= first && static_cast<uint32_t>(address) + count - 1 <= last;
}
}  // namespace

Charger::Charger(const hca::Model& model, uint8_t address) : model_(model), address_(address) {
  if (address_ < 1 || address_ > hca::kMaxAddress) address_ = hca::kDefaultAddress;
  boot(0, model_.maxTenths, hca::kFastMode);
}

void Charger::boot(uint32_t nowMs, uint16_t savedMaxTenths, uint16_t savedChargeMode) {
  now_ = lastTickMs_ = lastMasterMs_ = nowMs;
  maxTenths_ = savedMaxTenths <= model_.maxTenths ? savedMaxTenths : model_.maxTenths;
  chargeMode_ = savedChargeMode <= 2 ? savedChargeMode : hca::kFastMode;
  startStop_ = hca::kStopValue;  // Boot seguro: nunca retoma sozinho.
  emsDispatch_ = 0;
  for (uint16_t& item : settings_) item = 0;
  fault_ = hca::kFaultNone;
  masterSeen_ = false;
  persistentChanged_ = false;
  energyMilliJoules_ = 0;
  relay_ = false;
  relayChanges_ = 0;
  evaluate();
}

bool Charger::setAddress(uint8_t address) {
  if (address < 1 || address > hca::kMaxAddress) return false;
  address_ = address;
  return true;
}

void Charger::advance(uint32_t nowMs) {
  const uint32_t elapsed = nowMs - lastTickMs_;
  if (relay_) energyMilliJoules_ += static_cast<uint64_t>(hca::powerWForRegister(maxTenths_)) * elapsed;
  lastTickMs_ = now_ = nowMs;
}

void Charger::tick(uint32_t nowMs) {
  // Watchdog: só depois do primeiro contato do mestre desde o boot (antes disso o relé
  // já está aberto). Dispara uma vez; a falha fica até a próxima escrita do mestre. A
  // energia só soma até o instante do disparo, mesmo com um intervalo longo entre ticks.
  if (masterSeen_ && fault_ == hca::kFaultNone && nowMs - lastMasterMs_ >= hca::kWatchdogMs) {
    advance(lastMasterMs_ + hca::kWatchdogMs);
    fault_ = hca::kFaultCommunication;
    startStop_ = hca::kStopValue;
    evaluate();
  }
  advance(nowMs);
}

void Charger::forceFault(uint16_t faultCode) {
  fault_ = faultCode ? faultCode : hca::kFaultCommunication;
  startStop_ = hca::kStopValue;
  evaluate();
}

void Charger::contact(bool write) {
  masterSeen_ = true;
  lastMasterMs_ = now_;
  if (write && fault_ == hca::kFaultCommunication) fault_ = hca::kFaultNone;
}

void Charger::evaluate() {
  const bool closed = fault_ == hca::kFaultNone && startStop_ == hca::kStartValue && maxTenths_ >= model_.minTenths;
  if (closed != relay_) ++relayChanges_;
  relay_ = closed;
}

uint16_t Charger::reg(uint16_t address) const {
  switch (address) {
    case hca::kEmsDispatch: return emsDispatch_;
    case hca::kChargingPower: return relay_ ? maxTenths_ : 0;  // SIMULADO
    case hca::kStatus:
      return fault_ != hca::kFaultNone ? hca::kStatusAlarm : relay_ ? hca::kStatusCharging : hca::kStatusPlugged;
    case hca::kMaxChargingPower: return maxTenths_;
    case hca::kChargeMode: return chargeMode_;
    case hca::kPowerSpec: return model_.powerSpec;
    case hca::kChargerType: return model_.chargerType;
    case hca::kStartStop: return startStop_;
    case hca::kExtVersion: return 1;
    case hca::kExtEnergyHigh: return static_cast<uint16_t>(energyWh() >> 16);
    case hca::kExtEnergyLow: return static_cast<uint16_t>(energyWh() & 0xFFFF);
    case hca::kExtRelay: return relay_ ? 1 : 0;
    case hca::kExtFault: return fault_;
    case hca::kExtAddress: return address_;
    case hca::kExtSimulated: return 1;
    default:
      if (address >= kSettingsFirst && address <= kSettingsLast) return settings_[address - kSettingsFirst];
      return 0;
  }
}

uint8_t Charger::readHolding(uint16_t address, uint16_t count, uint16_t* out) {
  if (count < 1 || count > mbtcp::kMaxReadCount) return mbtcp::kIllegalValue;
  if (!inRange(address, count, hca::kOfficialFirst, hca::kOfficialLast) &&
      !inRange(address, count, hca::kExtFirst, hca::kExtLast))
    return mbtcp::kIllegalAddress;
  contact(false);
  for (uint16_t i = 0; i < count; ++i) out[i] = reg(static_cast<uint16_t>(address + i));
  return 0;
}

bool Charger::writable(uint16_t address) const {
  // Iguais a tools/edge/modbus_sim.py: 10000, 10019..10039 e 10060.
  return address == hca::kEmsDispatch || address == hca::kStartStop ||
         (address >= kSettingsFirst && address <= kSettingsLast);
}

uint8_t Charger::validate(uint16_t address, uint16_t value) const {
  if (!writable(address)) return mbtcp::kIllegalAddress;
  // 10029: acima do máximo do modelo é recusado (Illegal Data Value). Abaixo do mínimo é
  // aceito e PAUSA (extensão do simulado; a tela nunca escreve abaixo de 14, ela pausa
  // pelo 10060 = 1, como o adaptador do chargegrid_core).
  if (address == hca::kMaxChargingPower && value > model_.maxTenths) return mbtcp::kIllegalValue;
  if (address == hca::kStartStop && value != hca::kStopValue && value != hca::kStartValue) return mbtcp::kIllegalValue;
  if (address == hca::kChargeMode && value > 2) return mbtcp::kIllegalValue;
  if (address == hca::kEmsDispatch && value > 1) return mbtcp::kIllegalValue;
  return 0;
}

uint8_t Charger::writeHolding(uint16_t address, uint16_t count, const uint16_t* values) {
  if (count < 1 || count > mbtcp::kMaxWriteCount) return mbtcp::kIllegalValue;
  if (static_cast<uint32_t>(address) + count - 1 > 0xFFFF) return mbtcp::kIllegalAddress;
  // Tudo ou nada: valida todos antes de aplicar.
  for (uint16_t i = 0; i < count; ++i) {
    const uint8_t error = validate(static_cast<uint16_t>(address + i), values[i]);
    if (error) return error;
  }
  contact(true);
  for (uint16_t i = 0; i < count; ++i) {
    const uint16_t target = static_cast<uint16_t>(address + i), value = values[i];
    if (target == hca::kStartStop) startStop_ = value;
    else if (target == hca::kEmsDispatch) emsDispatch_ = value;
    else if (target == hca::kMaxChargingPower) {
      if (maxTenths_ != value) persistentChanged_ = true;
      maxTenths_ = value;
    } else if (target == hca::kChargeMode) {
      if (chargeMode_ != value) persistentChanged_ = true;
      chargeMode_ = value;
    } else settings_[target - kSettingsFirst] = value;
  }
  evaluate();
  return 0;
}

bool Charger::takePersistentChange() {
  const bool changed = persistentChanged_;
  persistentChanged_ = false;
  return changed;
}

}  // namespace hcasim
