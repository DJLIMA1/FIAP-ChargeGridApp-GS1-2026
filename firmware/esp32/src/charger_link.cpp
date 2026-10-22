#include "charger_link.h"
#include <string.h>
#include <stdio.h>

namespace charger {

bool sameConfig(const LinkConfig& a, const LinkConfig& b) {
  if (a.present != b.present) return false;
  if (!a.present) return true;
  return a.address == b.address && a.port == b.port && strcmp(a.host, b.host) == 0;
}

bool makeConfig(const char* model, const char* transport, long address, const char* host, long port, LinkConfig& out) {
  out = LinkConfig{};
  if (!model || strcmp(model, "goodwe_hca_g2") != 0) return false;
  if (!transport || strcmp(transport, "modbus_tcp") != 0) return false;
  if (address < 1 || address > hca::kMaxAddress) return false;
  if (port < 1 || port > 65535) return false;
  if (host && host[0]) {
    const size_t length = strlen(host);
    if (length >= sizeof(out.host)) return false;
    for (size_t i = 0; i < length; ++i) {
      const char c = host[i];
      const bool ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '.' || c == '-';
      if (!ok) return false;
    }
    memcpy(out.host, host, length + 1);
  } else {
    snprintf(out.host, sizeof(out.host), "cg-hca-%ld.local", address);
  }
  out.address = static_cast<uint8_t>(address);
  out.port = static_cast<uint16_t>(port);
  out.present = true;
  return true;
}

const char* errorCode(Error error) {
  switch (error) {
    case Error::None: return nullptr;
    case Error::NoLink: return "charger_not_linked";
    case Error::Offline: return "charger_offline";
    case Error::Rejected: return "charger_rejected";
    case Error::ReadbackMismatch: return "charger_readback_mismatch";
  }
  return "charger_error";
}

bool Link::configure(const LinkConfig& config) {
  if (sameConfig(config, config_)) return false;
  config_ = config;
  online_ = modeWritten_ = expectRunning_ = pendingStop_ = polled_ = false;
  power_ = status_ = failures_ = 0;
  stoppedPolls_ = 0;
  limit29_ = run60_ = -1;
  lastPollMs_ = lastOkMs_ = 0;
  lastError_ = Error::None;
  if (client_) client_->reset();
  return true;
}

bool Link::read(uint16_t address, uint16_t count, uint16_t* out, Error& error) {
  uint8_t exception = 0;
  if (client_->readHolding(config_, address, count, out, &exception)) {
    online_ = true; failures_ = 0; lastOkMs_ = client_->nowMs(now_);
    return true;
  }
  if (exception) { online_ = true; failures_ = 0; lastOkMs_ = client_->nowMs(now_); error = Error::Rejected; }
  else { online_ = false; ++failures_; error = Error::Offline; }
  return false;
}

bool Link::write(uint16_t address, uint16_t value, Error& error) {
  uint8_t exception = 0;
  if (client_->writeSingle(config_, address, value, &exception)) {
    online_ = true; failures_ = 0; lastOkMs_ = client_->nowMs(now_);
    if (address == hca::kMaxChargingPower) limit29_ = value;
    if (address == hca::kStartStop) run60_ = value;
    return true;
  }
  if (exception) { online_ = true; failures_ = 0; lastOkMs_ = client_->nowMs(now_); error = Error::Rejected; }
  else { online_ = false; ++failures_; error = Error::Offline; }
  return false;
}

// 10015..10017 (potência, reservado, status) + 10029 + 10060: confirmação por leitura.
bool Link::readLive(Error& error) {
  uint16_t live[3], limit = 0, run = 0;
  if (!read(hca::kChargingPower, 3, live, error)) return false;
  if (!read(hca::kMaxChargingPower, 1, &limit, error)) return false;
  if (!read(hca::kStartStop, 1, &run, error)) return false;
  power_ = live[0]; status_ = live[2]; limit29_ = limit; run60_ = run;
  return true;
}

// Instala o valor do 10029 (0 = pausar) e confirma pela releitura.
Error Link::apply(uint16_t value) {
  Error error = Error::None;
  if (value == 0) {
    expectRunning_ = false; stoppedPolls_ = 0;
    if (!write(hca::kStartStop, hca::kStopValue, error)) { pendingStop_ = true; return error; }
    if (!readLive(error)) { pendingStop_ = true; return error; }
    if (run60_ != hca::kStopValue || power_ != 0) { pendingStop_ = true; return Error::ReadbackMismatch; }
    pendingStop_ = false;
    return Error::None;
  }
  // 10029 grava flash no HCA: lê antes e só escreve se mudou.
  uint16_t current = 0;
  if (!read(hca::kMaxChargingPower, 1, &current, error)) return error;
  limit29_ = current;
  if (current != value && !write(hca::kMaxChargingPower, value, error)) return error;
  // 10060 não grava flash: escreve sempre (o watchdog do carregador pode tê-lo voltado a 1).
  if (!write(hca::kStartStop, hca::kStartValue, error)) return error;
  if (!readLive(error)) return error;
  // Liga confirmado: 10029/10060 batem e o carregador está em handshake ou carregando
  // (no simulado, 3 = relé fechado). Alarme ou falha ao iniciar: não confirma.
  if (limit29_ != value || run60_ != hca::kStartValue ||
      (status_ != hca::kStatusCharging && status_ != hca::kStatusHandshake))
    return Error::ReadbackMismatch;
  expectRunning_ = true; stoppedPolls_ = 0; pendingStop_ = false;
  return Error::None;
}

Error Link::startOnce(uint16_t value) {
  Error error = Error::None;
  if (!modeWritten_) {
    // Modo rápido (sem FV/bateria), escrito uma vez por link; grava flash no HCA.
    uint16_t mode = 0;
    if (!read(hca::kChargeMode, 1, &mode, error)) return error;
    if (mode != hca::kFastMode && !write(hca::kChargeMode, hca::kFastMode, error)) return error;
    modeWritten_ = true;
  }
  error = apply(value);
  if (error != Error::None && value) {
    // Não deixa o carregador ligado sem sessão confirmada.
    Error ignored = Error::None;
    expectRunning_ = false;
    if (!write(hca::kStartStop, hca::kStopValue, ignored)) pendingStop_ = true;
  }
  return error;
}

Error Link::start(long limitW, uint32_t nowMs, long* appliedW) {
  if (!active()) return lastError_ = Error::NoLink;
  now_ = nowMs;
  const uint16_t value = hca::registerForPowerW(limitW);
  // Sem resposta (link caído, mDNS lento após reboot, conexão velha): refaz e tenta de novo.
  // Recusa (exceção Modbus) ou releitura diferente não se resolvem repetindo: devolve já.
  Error error = Error::Offline;
  for (uint8_t attempt = 0; attempt < kStartAttempts && error == Error::Offline; ++attempt) {
    if (attempt || !online_) client_->prepareUrgent();
    error = startOnce(value);
  }
  if (error == Error::None && appliedW) *appliedW = hca::powerWForRegister(value);
  return lastError_ = error;
}

Error Link::setPower(long limitW, uint32_t nowMs, long* appliedW) {
  if (!active()) return lastError_ = Error::NoLink;
  now_ = nowMs;
  const uint16_t value = hca::registerForPowerW(limitW);
  const Error error = apply(value);
  if (error == Error::None && appliedW) *appliedW = hca::powerWForRegister(value);
  return lastError_ = error;
}

Error Link::stop(uint32_t nowMs) {
  if (!active()) return lastError_ = Error::NoLink;
  now_ = nowMs;
  return lastError_ = apply(0);
}

void Link::poll(uint32_t nowMs) {
  if (!active()) return;
  // Recarga ligada ou parada pendente: sempre ~1 s. Ocioso e offline: recua para 5 s.
  const uint32_t interval = (expectRunning_ || pendingStop_ || online_ || failures_ < 3) ? kPollMs : kIdleRetryMs;
  if (polled_ && nowMs - lastPollMs_ < interval) return;
  polled_ = true;
  lastPollMs_ = now_ = nowMs;
  Error error = Error::None;
  if (pendingStop_) {
    // Eco da escrita não prova que o relé abriu. Use a mesma confirmação do STOP
    // síncrono (10060 = 1 e 10015 = 0); releitura perdida mantém a pendência.
    lastError_ = apply(0);
    return;
  }
  uint16_t live[3];
  if (!read(hca::kChargingPower, 3, live, error)) return;
  power_ = live[0]; status_ = live[2];
  if (expectRunning_) {
    // Parou sozinho (reboot do carregador, watchdog): relé aberto sem a tela pedir.
    if ((status_ == hca::kStatusFree || status_ == hca::kStatusPlugged) && power_ == 0) {
      if (stoppedPolls_ < 255) ++stoppedPolls_;
    } else stoppedPolls_ = 0;
  } else if (status_ == hca::kStatusCharging || power_ > 0) {
    // Carregador ligado sem recarga na tela (tela reiniciou, outro mestre): desliga.
    lastError_ = apply(0);
  }
}

bool Link::faulted(uint32_t nowMs, bool session) const {
  if (!active() || !session) return false;
  // Inalcançável conta também com a recarga pausada (0 W): ela não poderia retomar.
  if (!online_ && nowMs - lastOkMs_ >= kLossMs) return true;
  if (!expectRunning_) return false;
  if (status_ == hca::kStatusAlarm || status_ == hca::kStatusStartFailed) return true;
  return stoppedPolls_ >= kStoppedPolls;
}

}  // namespace charger
