// Cliente Modbus TCP da tela para o carregador externo (HCA G2 simulado). Uma conexão
// persistente, timeouts curtos e resolução mDNS em cache: o loop nunca fica preso mais que
// ~kConnectTimeoutMs (+ kResolveTimeoutMs na primeira resolução). O LVGL roda em outra tarefa.
#include "charger_modbus_esp32.h"
#include <ESPmDNS.h>
#include <WiFi.h>
#include "modbus_tcp.h"

namespace {

constexpr int32_t kConnectTimeoutMs = 400;
constexpr uint32_t kResponseTimeoutMs = 300;
constexpr uint32_t kResolveTimeoutMs = 1000;
constexpr uint32_t kResolveRetryMs = 10000;

class EspChargerClient : public charger::ModbusClient {
 public:
  bool readHolding(const charger::LinkConfig& link, uint16_t address, uint16_t count, uint16_t* out,
                   uint8_t* exception) override {
    uint8_t request[mbtcp::kMaxAdu];
    const size_t size = mbtcp::buildReadHolding(++transaction_, link.address, address, count, request);
    return transact(link, request, size, out, exception);
  }
  bool writeSingle(const charger::LinkConfig& link, uint16_t address, uint16_t value, uint8_t* exception) override {
    uint8_t request[mbtcp::kMaxAdu];
    const size_t size = mbtcp::buildWriteSingle(++transaction_, link.address, address, value, request);
    return transact(link, request, size, nullptr, exception);
  }
  void reset() override {
    tcp_.stop();
    resolved_ = false;
    nextResolveMs_ = 0;
  }
  String fixedIp;
  String lastProblem = "-";
  IPAddress ip;
  bool resolved_ = false;
  bool connected() { return tcp_.connected(); }

 private:
  bool resolve(const charger::LinkConfig& link) {
    if (resolved_) return true;
    if (fixedIp.length()) {
      resolved_ = ip.fromString(fixedIp);
      if (!resolved_) lastProblem = "ip_fixo_invalido";
      return resolved_;
    }
    if (ip.fromString(link.host)) return resolved_ = true;
    if ((long)(millis() - nextResolveMs_) < 0) return false;
    nextResolveMs_ = millis() + kResolveRetryMs;
    String name(link.host);
    if (name.endsWith(".local")) {
      static bool mdnsReady = false;
      if (!mdnsReady) mdnsReady = MDNS.begin("cg-panel");
      name.remove(name.length() - 6);
      ip = MDNS.queryHost(name.c_str(), kResolveTimeoutMs);
      resolved_ = ip != IPAddress(0, 0, 0, 0);
    } else {
      resolved_ = WiFi.hostByName(link.host, ip) == 1 && ip != IPAddress(0, 0, 0, 0);
    }
    if (!resolved_) lastProblem = String("mdns_sem_resposta:") + link.host;
    return resolved_;
  }
  bool ensure(const charger::LinkConfig& link) {
    if (WiFi.status() != WL_CONNECTED) { tcp_.stop(); lastProblem = "wifi_offline"; return false; }
    if (tcp_.connected()) return true;
    if (!resolve(link)) return false;
    if (!tcp_.connect(ip, link.port, kConnectTimeoutMs)) {
      tcp_.stop();
      resolved_ = false;  // IP pode ter mudado (DHCP): resolve de novo na próxima tentativa.
      nextResolveMs_ = 0;
      lastProblem = "sem_conexao_tcp";
      return false;
    }
    tcp_.setNoDelay(true);
    return true;
  }
  bool transact(const charger::LinkConfig& link, const uint8_t* request, size_t size, uint16_t* out,
                uint8_t* exception) {
    if (exception) *exception = 0;
    if (!ensure(link)) return false;
    while (tcp_.available()) tcp_.read();  // resposta atrasada de uma transação anterior
    if (tcp_.write(request, size) != size) { tcp_.stop(); lastProblem = "falha_envio"; return false; }
    uint8_t response[mbtcp::kMaxAdu];
    size_t length = 0;
    const unsigned long started = millis();
    while (millis() - started < kResponseTimeoutMs) {
      const int available = tcp_.available();
      if (available <= 0) {
        if (!tcp_.connected()) break;
        delay(1);
        continue;
      }
      const int got = tcp_.read(response + length, min((size_t)available, sizeof(response) - length));
      if (got <= 0) break;
      length += got;
      const long frame = mbtcp::frameLength(response, length);
      if (frame < 0) break;
      if (frame == 0) continue;
      uint8_t code = 0;
      const mbtcp::Status status = mbtcp::parseResponse(request, response, frame, out, &code);
      if (status == mbtcp::Status::Ok) return true;
      if (status == mbtcp::Status::Exception) {
        if (exception) *exception = code ? code : mbtcp::kDeviceFailure;
        lastProblem = String("excecao_modbus_") + code;
        return false;
      }
      break;  // quadro inválido ou de outra transação: refaz a conexão
    }
    tcp_.stop();
    lastProblem = "sem_resposta";
    return false;
  }

  WiFiClient tcp_;
  uint16_t transaction_ = 0;
  uint32_t nextResolveMs_ = 0;
};

EspChargerClient client;

}  // namespace

charger::ModbusClient& espChargerClient() { return client; }
void espChargerSetFixedIp(const String& ip) { client.fixedIp = ip; client.reset(); }
String espChargerFixedIp() { return client.fixedIp; }
String espChargerDescribe() {
  return String("ip=") + (client.resolved_ ? client.ip.toString() : String("-")) +
         " ip_fixo=" + (client.fixedIp.length() ? client.fixedIp : String("-")) +
         " tcp=" + (client.connected() ? "conectado" : "fechado") + " ultimo_problema=" + client.lastProblem;
}
