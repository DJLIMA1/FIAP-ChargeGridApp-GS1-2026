#pragma once
// Cliente Modbus FALSO para os testes de host da tela: em vez de TCP, cada pedido vira um
// ADU Modbus TCP de verdade (mbtcp::build*), é atendido pela lógica real do carregador
// simulado (hcasim::Charger via mbtcp::serve) e a resposta passa por mbtcp::parseResponse.
// Falhas injetáveis: carregador fora do ar, escrita perdida (eco ok sem aplicar), resposta
// com exceção. Registra cada operação para conferir a tradução dos comandos.
#include <string>
#include <vector>
#include "charger_link.h"
#include "hca_sim_core.h"
#include "modbus_tcp.h"

struct FakeChargerClient : charger::ModbusClient {
  hcasim::Charger device;
  const unsigned long* clock = nullptr;
  bool offline = false;
  int dropWrites = 0;   // próximas N escritas respondem ok, mas não são aplicadas
  int failNext = 0;     // próximas N transações sem resposta (carregador "piscando"/conexão velha)
  int failReads = 0;    // próximas N leituras do endereço escolhido sem resposta
  int failReadAt = -1;  // -1 = qualquer leitura; permite interromper o readback depois da escrita
  int urgent = 0;       // pedidos de resolução imediata (prepareUrgent) do START
  std::vector<std::string> log;
  int resets = 0;
  uint16_t transaction = 0;

  explicit FakeChargerClient(const unsigned long* now, uint8_t address = 1) : device(hca::kGw7k, address), clock(now) {
    device.boot(*clock, hca::kGw7k.maxTenths, 1);  // modo FV salvo: a tela deve escrever 10032 = 0
  }
  size_t exchange(const uint8_t* request, size_t size, uint8_t* response) {
    device.tick(static_cast<uint32_t>(*clock));
    return mbtcp::serve(request, size, device.address(), device, response);
  }
  bool readHolding(const charger::LinkConfig& link, uint16_t address, uint16_t count, uint16_t* out,
                   uint8_t* exception) override {
    if (exception) *exception = 0;
    log.push_back("R " + std::to_string(address) + "x" + std::to_string(count));
    if (offline) return false;
    if (failNext > 0) { --failNext; return false; }
    if (failReads > 0 && (failReadAt < 0 || failReadAt == address)) { --failReads; return false; }
    uint8_t request[mbtcp::kMaxAdu], response[mbtcp::kMaxAdu];
    const size_t size = mbtcp::buildReadHolding(++transaction, link.address, address, count, request);
    const size_t length = exchange(request, size, response);
    uint8_t code = 0;
    const mbtcp::Status status = mbtcp::parseResponse(request, response, length, out, &code);
    if (status == mbtcp::Status::Exception && exception) *exception = code;
    return status == mbtcp::Status::Ok;
  }
  bool writeSingle(const charger::LinkConfig& link, uint16_t address, uint16_t value, uint8_t* exception) override {
    if (exception) *exception = 0;
    if (offline || failNext > 0) {
      if (!offline) --failNext;
      log.push_back("W " + std::to_string(address) + "=" + std::to_string(value) + " offline");
      return false;
    }
    if (dropWrites > 0) {
      --dropWrites;
      log.push_back("W " + std::to_string(address) + "=" + std::to_string(value) + " lost");
      return true;
    }
    log.push_back("W " + std::to_string(address) + "=" + std::to_string(value));
    uint8_t request[mbtcp::kMaxAdu], response[mbtcp::kMaxAdu];
    const size_t size = mbtcp::buildWriteSingle(++transaction, link.address, address, value, request);
    const size_t length = exchange(request, size, response);
    uint8_t code = 0;
    const mbtcp::Status status = mbtcp::parseResponse(request, response, length, nullptr, &code);
    if (status == mbtcp::Status::Exception && exception) *exception = code;
    return status == mbtcp::Status::Ok;
  }
  void reset() override { ++resets; }
  void prepareUrgent() override { ++urgent; }
  int count(const std::string& entry) const {
    int found = 0;
    for (const auto& item : log) found += item == entry;
    return found;
  }
  // Só as escritas, na ordem (ex.: "W 10032=0|W 10029=20|W 10060=2").
  std::string writes() const {
    std::string joined;
    for (const auto& item : log)
      if (item[0] == 'W') joined += (joined.empty() ? "" : "|") + item;
    return joined;
  }
};
