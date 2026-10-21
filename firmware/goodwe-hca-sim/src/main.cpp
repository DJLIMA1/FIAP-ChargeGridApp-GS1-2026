// Carregador GoodWe HCA G2 SIMULADO num ESP32 DevKit (ChargeGrid).
//
// Servidor Modbus TCP (porta 502, unit id = endereço, padrão 1) com o mapa do HCA G2,
// relé na GPIO 13 (padrão ativo em LOW) que liga a tomada do celular. Sem validação em
// hardware GoodWe: potência e energia são SIMULADAS. Guia: docs/carregador-hca-simulado.md.
//
// Toda a regra (registradores, relé, watchdog de 15 s, energia) mora em
// lib/hca_sim_core (C++ puro, testado no host). Aqui só ficam GPIO, Wi-Fi, mDNS, TCP,
// NVS e os comandos seriais.
#include <Arduino.h>
#include <ESPmDNS.h>
#include <Preferences.h>
#include <WiFi.h>
#include "hca_sim_core.h"
#include "modbus_tcp.h"

#ifndef CG_HCA_SIM_VERSION
#define CG_HCA_SIM_VERSION "1.0.0"
#endif
#ifndef CG_RELAY_PIN
#define CG_RELAY_PIN 13
#endif
#ifndef CG_RELAY_ACTIVE_LOW
#define CG_RELAY_ACTIVE_LOW 1  // módulos de relé comuns acionam com nível baixo
#endif
#ifndef CG_LED_PIN
#define CG_LED_PIN 2  // LED azul do DevKit: espelha o relé (-1 desliga)
#endif

namespace {

constexpr uint8_t kMaxClients = 3;
constexpr uint32_t kClientIdleMs = 60000;

Preferences nvs;
hcasim::Charger charger;
WiFiServer server(hca::kDefaultPort);
bool relayActiveLow = CG_RELAY_ACTIVE_LOW;
bool relayOutput = false, serverStarted = false, mdnsStarted = false, wifiWasConnected = false;
String wifiSsid, wifiPassword, mdnsName;

struct Client {
  WiFiClient socket;
  uint8_t buffer[mbtcp::kMaxAdu];
  size_t length = 0;
  uint32_t lastActivity = 0;
};
Client clients[kMaxClients];

// Saída física: o nível "desligado" vem antes de configurar o pino como saída.
void driveRelay(bool closed) {
  const uint8_t level = closed == relayActiveLow ? LOW : HIGH;
  digitalWrite(CG_RELAY_PIN, level);
  if (CG_LED_PIN >= 0) digitalWrite(CG_LED_PIN, closed ? HIGH : LOW);
}
void setupRelaySafe() {
  digitalWrite(CG_RELAY_PIN, relayActiveLow ? HIGH : LOW);
  pinMode(CG_RELAY_PIN, OUTPUT);
  if (CG_LED_PIN >= 0) pinMode(CG_LED_PIN, OUTPUT);
  driveRelay(false);
  relayOutput = false;
}

const char* statusText(uint16_t status) {
  switch (status) {
    case hca::kStatusCharging: return "carregando";
    case hca::kStatusAlarm: return "alarme";
    case hca::kStatusPlugged: return "parado";
    default: return "outro";
  }
}

void syncRelay() {
  const bool closed = charger.relayClosed();
  if (closed == relayOutput) return;
  driveRelay(closed);
  relayOutput = closed;
  Serial.printf("[relay] %s (10060=%u 10029=%u status=%u falha=%u)\n", closed ? "FECHADO" : "ABERTO",
                charger.reg(hca::kStartStop), charger.reg(hca::kMaxChargingPower), charger.reg(hca::kStatus),
                charger.fault());
}

// Registra as escritas do mestre no serial (rótulo SIMULADO) e delega à lógica pura.
class LoggedBank : public mbtcp::RegisterBank {
 public:
  uint8_t readHolding(uint16_t address, uint16_t count, uint16_t* out) override {
    return charger.readHolding(address, count, out);
  }
  uint8_t writeHolding(uint16_t address, uint16_t count, const uint16_t* values) override {
    const uint8_t error = charger.writeHolding(address, count, values);
    for (uint16_t i = 0; i < count; ++i)
      Serial.printf("[SIMULADO] unit %u reg %u <- %u%s\n", charger.address(), address + i, values[i],
                    error ? " RECUSADA" : "");
    if (error) Serial.printf("[modbus] exceção %02X\n", error);
    return error;
  }
} bank;

void startMdns() {
  if (mdnsStarted) { MDNS.end(); mdnsStarted = false; }
  mdnsName = String("cg-hca-") + charger.address();
  if (!MDNS.begin(mdnsName.c_str())) { Serial.println("[mdns] falhou"); return; }
  MDNS.addService("modbus", "tcp", hca::kDefaultPort);
  MDNS.addServiceTxt("modbus", "tcp", "address", String(charger.address()).c_str());
  MDNS.addServiceTxt("modbus", "tcp", "model", charger.model().name);
  MDNS.addServiceTxt("modbus", "tcp", "simulated", "1");
  mdnsStarted = true;
  Serial.printf("[mdns] %s.local (_modbus._tcp porta %u)\n", mdnsName.c_str(), hca::kDefaultPort);
}

void serviceWifi() {
  const bool connected = WiFi.status() == WL_CONNECTED;
  if (connected && !wifiWasConnected) {
    Serial.printf("[wifi] conectado: %s IP %s\n", WiFi.SSID().c_str(), WiFi.localIP().toString().c_str());
    if (!serverStarted) { server.begin(); server.setNoDelay(true); serverStarted = true; }
    startMdns();
  } else if (!connected && wifiWasConnected) {
    Serial.println("[wifi] desconectado (o relé abre pelo watchdog se o mestre sumir por 15 s)");
  }
  wifiWasConnected = connected;
}

void closeClient(Client& client) {
  client.socket.stop();
  client.length = 0;
}

void serviceModbus() {
  if (!serverStarted) return;
  WiFiClient incoming = server.available();
  if (incoming) {
    Client* slot = nullptr;
    for (Client& client : clients) if (!client.socket.connected()) { slot = &client; break; }
    if (slot) {
      closeClient(*slot);
      slot->socket = incoming;
      slot->socket.setNoDelay(true);
      slot->lastActivity = millis();
    } else incoming.stop();  // Sem vaga: recusa (a tela usa uma conexão só).
  }
  for (Client& client : clients) {
    if (!client.socket.connected()) { client.length = 0; continue; }
    int available = client.socket.available();
    while (available > 0 && client.length < sizeof(client.buffer)) {
      const int got = client.socket.read(client.buffer + client.length, sizeof(client.buffer) - client.length);
      if (got <= 0) break;
      client.length += got;
      available -= got;
      client.lastActivity = millis();
    }
    while (client.length) {
      const long frame = mbtcp::frameLength(client.buffer, client.length);
      if (frame < 0) { closeClient(client); break; }
      if (frame == 0) break;
      uint8_t response[mbtcp::kMaxAdu];
      charger.tick(millis());
      const size_t size = mbtcp::serve(client.buffer, frame, charger.address(), bank, response);
      if (size) client.socket.write(response, size);
      memmove(client.buffer, client.buffer + frame, client.length - frame);
      client.length -= frame;
    }
    if (client.socket.connected() && millis() - client.lastActivity > kClientIdleMs) closeClient(client);
  }
}

void persistRegisters() {
  if (!charger.takePersistentChange()) return;
  nvs.putUShort("max29", charger.reg(hca::kMaxChargingPower));
  nvs.putUShort("mode32", charger.reg(hca::kChargeMode));
}

void printStatus() {
  const bool wifi = WiFi.status() == WL_CONNECTED;
  Serial.printf("[status] firmware=goodwe-hca-sim %s modelo=%s (SIMULADO) endereco=%u mdns=%s.local\n",
                CG_HCA_SIM_VERSION, charger.model().name, charger.address(), mdnsName.length() ? mdnsName.c_str() : "-");
  Serial.printf("[status] wifi=%s ssid=%s ip=%s porta=%u clientes=%u\n", wifi ? "conectado" : "offline",
                wifiSsid.length() ? wifiSsid.c_str() : "-", wifi ? WiFi.localIP().toString().c_str() : "-",
                hca::kDefaultPort, [] { uint8_t n = 0; for (Client& c : clients) n += c.socket.connected(); return n; }());
  Serial.printf("[status] rele=%s gpio=%d ativo_em=%s falha=%u mestre=%s\n", charger.relayClosed() ? "FECHADO" : "ABERTO",
                CG_RELAY_PIN, relayActiveLow ? "LOW" : "HIGH", charger.fault(),
                charger.watchdogArmed() ? (String("ha ") + charger.msSinceMaster() / 1000 + " s").c_str() : "nunca");
  Serial.printf("[status] 10015=%u (%.1f kW SIMULADO) 10017=%u (%s) 10029=%u (%.1f kW) 10032=%u 10058=%u 10059=%u 10060=%u\n",
                charger.reg(hca::kChargingPower), charger.reg(hca::kChargingPower) / 10.0f, charger.reg(hca::kStatus),
                statusText(charger.reg(hca::kStatus)), charger.reg(hca::kMaxChargingPower),
                charger.reg(hca::kMaxChargingPower) / 10.0f, charger.reg(hca::kChargeMode), charger.reg(hca::kPowerSpec),
                charger.reg(hca::kChargerType), charger.reg(hca::kStartStop));
  Serial.printf("[status] energia_simulada_wh=%lu (19001/19002)\n", static_cast<unsigned long>(charger.energyWh()));
}

void printHelp() {
  Serial.println("[help] CG_STATUS | CG_WIFI <ssid> <senha> (ou CG_WIFI e responda) | CG_WIFI_CLEAR");
  Serial.println("[help] CG_ADDR <1-247> | CG_RELAY_LEVEL LOW|HIGH | CG_REBOOT | CG_HELP");
}

void saveWifi(const String& ssid, const String& password) {
  if (!ssid.length() || ssid.length() > 32 || password.length() > 64) {
    Serial.println("[wifi] SSID (1-32) ou senha (ate 64) invalidos");
    return;
  }
  nvs.putString("wifi_ssid", ssid);
  if (password.length()) nvs.putString("wifi_pass", password);
  else if (nvs.isKey("wifi_pass")) nvs.remove("wifi_pass");
  wifiSsid = ssid;
  wifiPassword = password;
  WiFi.disconnect();
  WiFi.begin(wifiSsid.c_str(), wifiPassword.c_str());
  Serial.printf("[wifi] salvo; conectando a %s\n", wifiSsid.c_str());
}

void handleLine(String line) {
  static uint8_t step = 0;  // 1: aguardando SSID, 2: aguardando senha
  static String pendingSsid;
  line.trim();
  if (step == 1) {
    pendingSsid = line;
    step = 2;
    Serial.println("[wifi] Senha (vazia = rede aberta):");
    return;
  }
  if (step == 2) {
    step = 0;
    saveWifi(pendingSsid, line);
    line = "";
    return;
  }
  if (!line.length()) return;
  if (line == "CG_STATUS") { printStatus(); return; }
  if (line == "CG_HELP") { printHelp(); return; }
  if (line == "CG_REBOOT") { Serial.println("[setup] reiniciando (rele aberto)"); driveRelay(false); delay(100); ESP.restart(); }
  if (line == "CG_WIFI") { step = 1; Serial.println("[wifi] SSID:"); return; }
  if (line.startsWith("CG_WIFI ")) {
    const String rest = line.substring(8);
    const int space = rest.indexOf(' ');
    saveWifi(space < 0 ? rest : rest.substring(0, space), space < 0 ? String() : rest.substring(space + 1));
    return;
  }
  if (line == "CG_WIFI_CLEAR") {
    if (nvs.isKey("wifi_ssid")) nvs.remove("wifi_ssid");
    if (nvs.isKey("wifi_pass")) nvs.remove("wifi_pass");
    wifiSsid = wifiPassword = "";
    WiFi.disconnect(true);
    Serial.println("[wifi] rede apagada");
    return;
  }
  if (line.startsWith("CG_ADDR")) {
    const long address = line.length() > 8 ? line.substring(8).toInt() : 0;
    if (address < 1 || address > hca::kMaxAddress) { Serial.println("[addr] use CG_ADDR <1-247>"); return; }
    if (charger.relayClosed()) { Serial.println("[addr] pare a recarga antes (rele fechado)"); return; }
    charger.setAddress(static_cast<uint8_t>(address));
    nvs.putUChar("addr", charger.address());
    Serial.printf("[addr] endereco (unit id) = %u\n", charger.address());
    if (WiFi.status() == WL_CONNECTED) startMdns();
    return;
  }
  if (line.startsWith("CG_RELAY_LEVEL")) {
    const String level = line.length() > 15 ? line.substring(15) : String();
    if (level != "LOW" && level != "HIGH") { Serial.println("[relay] use CG_RELAY_LEVEL LOW|HIGH"); return; }
    if (charger.relayClosed()) { Serial.println("[relay] pare a recarga antes (rele fechado)"); return; }
    relayActiveLow = level == "LOW";
    nvs.putBool("relay_low", relayActiveLow);
    driveRelay(false);
    Serial.printf("[relay] ativo em %s; saida desligada\n", relayActiveLow ? "LOW" : "HIGH");
    return;
  }
  Serial.println("[help] comando desconhecido; CG_HELP lista os comandos");
}

void serviceSerial() {
  static String input;
  while (Serial.available()) {
    const char incoming = static_cast<char>(Serial.read());
    if (incoming == '\r') continue;
    if (incoming == '\n') { handleLine(input); input = ""; continue; }
    if (input.length() < 160) input += incoming;
  }
}

}  // namespace

void setup() {
  // 1º: saída desligada (o nível vem da NVS; antes disso o pino segue em alta impedância).
  nvs.begin("cg-hca", false);
  relayActiveLow = nvs.getBool("relay_low", CG_RELAY_ACTIVE_LOW);
  setupRelaySafe();
  Serial.begin(115200);
  charger.setAddress(nvs.getUChar("addr", hca::kDefaultAddress));
  charger.boot(millis(), nvs.getUShort("max29", hca::kGw7k.maxTenths), nvs.getUShort("mode32", hca::kFastMode));
  wifiSsid = nvs.getString("wifi_ssid", "");
  wifiPassword = nvs.getString("wifi_pass", "");
  Serial.printf("\n[boot] goodwe-hca-sim %s: carregador GoodWe HCA G2 SIMULADO, endereco %u, rele GPIO%d ativo em %s (ABERTO)\n",
                CG_HCA_SIM_VERSION, charger.address(), CG_RELAY_PIN, relayActiveLow ? "LOW" : "HIGH");
  WiFi.setHostname((String("cg-hca-") + charger.address()).c_str());  // antes de mode() no core 2.x
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.setSleep(false);  // menor latência para o mestre Modbus
  if (wifiSsid.length()) WiFi.begin(wifiSsid.c_str(), wifiPassword.c_str());
  else Serial.println("[wifi] sem rede: use CG_WIFI <ssid> <senha>");
  printHelp();
}

void loop() {
  charger.tick(millis());
  serviceWifi();
  serviceModbus();
  charger.tick(millis());
  syncRelay();
  persistRegisters();
  serviceSerial();
  delay(2);
}
