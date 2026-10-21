// Cliente Modbus TCP da tela para os carregadores GoodWe (HCA G2 simulado). Um cliente por
// carregador (o do ponto da tela e os adicionais): uma conexão persistente, timeouts curtos e
// resolução mDNS com o último IP bom como reserva. O loop nunca fica preso mais que
// ~kConnectTimeoutMs + kResponseTimeoutMs por leitura (+ a resolução mDNS, no máximo a cada
// kResolveRetryMs). O LVGL roda em outra tarefa.
//
// Teste real (21/10): o link caía e só voltava reiniciando a tela. Depois de uma falha de
// conexão a tela descartava o IP e passava a depender só do mDNS (multicast), consultado a cada
// 15 s com 500 ms; com o Wi-Fi da tela em economia de energia (padrão do ESP32) o multicast se
// perde e o link ficava offline até o reboot. Agora: Wi-Fi sem economia (main.cpp), mDNS
// reiniciado quando o IP da tela muda (reconexão), consulta a cada 5 s e, sem resposta, o último
// IP bom continua sendo tentado; o START pede resolução imediata (prepareUrgent).
#include "charger_modbus_esp32.h"
#include <ESPmDNS.h>
#include <WiFi.h>
#include "modbus_tcp.h"

namespace {

constexpr int32_t kConnectTimeoutMs = 400;
constexpr uint32_t kResponseTimeoutMs = 400;
constexpr uint32_t kResolveTimeoutMs = 500;
constexpr uint32_t kUrgentResolveTimeoutMs = 1200;  // START: mDNS logo após reboot é mais lento
constexpr uint32_t kResolveRetryMs = 5000;

// Responder mDNS da tela ("cg-panel"): reinicia quando a tela troca de IP (reconexão Wi-Fi) ou
// depois de consultas seguidas sem resposta (o responder do ESP32 às vezes não volta sozinho).
bool ensureMdns(bool restart) {
  static bool ready = false;
  static IPAddress boundIp;
  if (ready && (restart || WiFi.localIP() != boundIp)) { MDNS.end(); ready = false; }
  if (!ready) {
    ready = MDNS.begin("cg-panel");
    boundIp = WiFi.localIP();
  }
  return ready;
}

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
    resolved_ = haveLastGood_ = false;
    nextResolveMs_ = 0;
    mdnsMisses_ = 0;
  }
  void prepareUrgent() override {
    // Comando (START): refaz a conexão e resolve o nome já, sem esperar o recuo.
    tcp_.stop();
    resolved_ = false;
    urgent_ = true;
  }
  uint32_t nowMs(uint32_t) const override { return millis(); }
  String fixedIp;
  String lastProblem = "-";
  IPAddress ip;
  IPAddress lastGood;
  bool resolved_ = false;
  bool haveLastGood_ = false;
  bool connected() { return tcp_.connected(); }

 private:
  bool resolve(const charger::LinkConfig& link) {
    if (resolved_) return true;
    const bool urgent = urgent_;
    urgent_ = false;
    if (fixedIp.length()) {
      resolved_ = ip.fromString(fixedIp);
      if (!resolved_) lastProblem = "ip_fixo_invalido";
      return resolved_;
    }
    if (ip.fromString(link.host)) return resolved_ = true;
    if (urgent || (long)(millis() - nextResolveMs_) >= 0) {
      nextResolveMs_ = millis() + kResolveRetryMs;
      IPAddress found;
      String name(link.host);
      if (name.endsWith(".local")) {
        if (ensureMdns(mdnsMisses_ >= 3)) {
          if (mdnsMisses_ >= 3) mdnsMisses_ = 0;
          name.remove(name.length() - 6);
          found = MDNS.queryHost(name.c_str(), urgent ? kUrgentResolveTimeoutMs : kResolveTimeoutMs);
        }
      } else if (WiFi.hostByName(link.host, found) != 1) {
        found = IPAddress(0, 0, 0, 0);
      }
      if (found != IPAddress(0, 0, 0, 0)) {
        mdnsMisses_ = 0;
        ip = found;
        return resolved_ = true;
      }
      ++mdnsMisses_;
      lastProblem = String("mdns_sem_resposta:") + link.host;
    }
    // mDNS sem resposta (ou aguardando o recuo): o último IP bom continua valendo (DHCP costuma
    // manter o mesmo IP do carregador); se ele mudou, a conexão falha e o mDNS tenta de novo.
    if (haveLastGood_) {
      ip = lastGood;
      return resolved_ = true;
    }
    return false;
  }
  bool ensure(const charger::LinkConfig& link) {
    if (WiFi.status() != WL_CONNECTED) { tcp_.stop(); lastProblem = "wifi_offline"; return false; }
    if (tcp_.connected()) return true;
    if (!resolve(link)) return false;
    if (!tcp_.connect(ip, link.port, kConnectTimeoutMs)) {
      tcp_.stop();
      resolved_ = false;  // IP pode ter mudado (DHCP): a próxima tentativa consulta o mDNS.
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
    if (tcp_.write(request, size) != size) return transportFailure("falha_envio");
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
      if (status == mbtcp::Status::Ok) {
        lastProblem = "-";
        lastGood = ip;
        haveLastGood_ = true;
        return true;
      }
      if (status == mbtcp::Status::Exception) {
        if (exception) *exception = code ? code : mbtcp::kDeviceFailure;
        lastProblem = String("excecao_modbus_") + code;
        lastGood = ip;
        haveLastGood_ = true;
        return false;
      }
      break;  // quadro inválido ou de outra transação: refaz a conexão
    }
    return transportFailure("sem_resposta");
  }

  bool transportFailure(const char* problem) {
    tcp_.stop();
    // O IP antigo pode ainda aceitar TCP sem responder Modbus. Só fechar o socket
    // mantém resolved_ para sempre e impede redescoberta após DHCP/reboot.
    // Preserve o último IP bom como reserva e o recuo das consultas mDNS.
    resolved_ = false;
    lastProblem = problem;
    return false;
  }

  WiFiClient tcp_;
  uint16_t transaction_ = 0;
  uint32_t nextResolveMs_ = 0;
  uint8_t mdnsMisses_ = 0;
  bool urgent_ = false;
};

// Slot 0: carregador do ponto da tela; 1..: carregadores adicionais (multi_charger_v1).
EspChargerClient clients[kEspChargerClients];

}  // namespace

charger::ModbusClient& espChargerClient(uint8_t slot) { return clients[slot < kEspChargerClients ? slot : 0]; }
void espChargerSetFixedIp(const String& ip) { clients[0].fixedIp = ip; clients[0].reset(); }
String espChargerFixedIp() { return clients[0].fixedIp; }
String espChargerDescribe(uint8_t slot) {
  EspChargerClient& client = clients[slot < kEspChargerClients ? slot : 0];
  return String("ip=") + (client.resolved_ ? client.ip.toString() : String("-")) +
         " ultimo_ip_bom=" + (client.haveLastGood_ ? client.lastGood.toString() : String("-")) +
         " ip_fixo=" + (client.fixedIp.length() ? client.fixedIp : String("-")) +
         " tcp=" + (client.connected() ? "conectado" : "fechado") + " ultimo_problema=" + client.lastProblem;
}
