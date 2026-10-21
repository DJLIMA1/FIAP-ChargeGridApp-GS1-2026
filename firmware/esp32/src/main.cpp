#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <mbedtls/base64.h>
#include <mbedtls/sha256.h>
#include <time.h>
#include "runtime.h"
#include "panel_ui.h"
#include "charger_modbus_esp32.h"
#include "extra_chargers.h"
#include <esp_system.h>
#ifdef CHARGEGRID_PANEL_ENABLED
#include "panel_service_config.h"
#include "panel_hardware.h"
#include "panel_network.h"
#include "panel_claim.h"
#else
#if __has_include("chargegrid_config.h")
#include "chargegrid_config.h"
#else
#include "config.example.h"
#endif
#endif

// Bancada exclusivamente simulada: não configura GPIO nem relé.
Preferences store;
#ifdef CHARGEGRID_PANEL_ENABLED
Preferences configStore;
#endif
SimulatedSensors sensors;
Reading reading{20, 0, 0, false};
String bootId, sessionId, lastCommand, state = "idle", endReason;
String connectorPublicCode = "--";
String stationPresenceCode;
unsigned long presenceCodeReceivedAt = 0, presenceCodeTtlMs = 0;
String panelClaimToken;
bool panelOwned = false, connectorOwnershipKnown = false, connectorActive = true;
uint32_t version = 0, sequence = 0;
unsigned long lastContact, lastTick, started, nextSync = 0, lastSaved = 0;
unsigned long maxDurationMs = 3600000;
float maxCost = -1, price = 0, discount = 0;
float chargePowerW = kBenchPowerW;
float socStartPercent = -1, batteryKwh = 0, phoneSocPercent = -1;
String socSource;
time_t reservationDeadline = 0;
JsonDocument acknowledgements;
bool hasSynced = false;
bool sessionPricingKnown = false;
bool panelIntegrationEnabled = false;
bool panelIdentityConfigured = false;
bool panelNetworkConfigured = false;
int lastSyncHttpStatus = 0;
#ifdef CHARGEGRID_PANEL_ENABLED
String panelWifiSsid, panelWifiPassword, panelDeviceKey;

String factorySecret() {
  uint8_t randomBytes[32];
  esp_fill_random(randomBytes, sizeof(randomBytes));
  unsigned char encoded[48]{};
  size_t length = 0;
  if (mbedtls_base64_encode(encoded, sizeof(encoded), &length, randomBytes, sizeof(randomBytes))) return "";
  String result(reinterpret_cast<char*>(encoded));
  result.replace('+', '-'); result.replace('/', '_');
  if (result.endsWith("=")) result.remove(result.length() - 1);
  return result;
}

String factoryHash(const String& secret) {
  unsigned char digest[32];
  if (mbedtls_sha256(reinterpret_cast<const unsigned char*>(secret.c_str()), secret.length(), digest, 0)) return "";
  char hex[65];
  for (size_t i = 0; i < sizeof(digest); ++i) snprintf(hex + i * 2, 3, "%02x", digest[i]);
  hex[64] = '\0';
  return String(hex);
}

bool finalizeStoredFactoryReset() {
  if (!configStore.getBool("reset_done", false)) return false;
  String newKey = configStore.getString("reset_key", "");
  String newClaim = configStore.getString("reset_claim", "");
  if (newKey.length() != 43 || !validPanelClaimToken(newClaim.c_str())) {
    // A fully written new identity may survive a power loss during cleanup.
    if (configStore.getString("device_key", "").length() == 43 &&
        validPanelClaimToken(configStore.getString("claim_token", "").c_str()) &&
        !configStore.getBool("owned", true)) {
      configStore.putBool("reset_done", false);
      delay(120); ESP.restart();
    }
    return false;
  }
  bool saved = configStore.putString("device_key", newKey) == 43;
  saved = configStore.putString("claim_token", newClaim) == 43 && saved;
  saved = configStore.putBool("owned", false) > 0 && saved;
  // The screen can be handed to a new vendor without requiring physical
  // access just to reconnect it. Factory reset revokes ownership and all
  // ChargeGrid state, while deliberately preserving its configured network.
  if (!saved || !store.clear()) return false;
  // The durable completion flag remains until all old credentials and journal
  // entries are gone, so an interrupted reset is safe to retry after reboot.
  saved = (!configStore.isKey("reset_cmd") || configStore.remove("reset_cmd"));
  saved = (!configStore.isKey("reset_key") || configStore.remove("reset_key")) && saved;
  saved = (!configStore.isKey("reset_claim") || configStore.remove("reset_claim")) && saved;
  if (!saved || !configStore.putBool("reset_done", false)) return false;
  Serial.println("[setup] Factory reset complete; Wi-Fi preserved; new private claim QR ready");
  delay(120); ESP.restart();
  return true;
}
#endif

bool preparePanelFactoryReset(const String& commandId, String& keyHash, String& claimHash) {
#ifdef CHARGEGRID_PANEL_ENABLED
  if (state != "idle" || sessionId.length() || reading.connected || reading.powerW > 0 ||
      WiFi.status() != WL_CONNECTED || !panelOwned || !hasSynced) return false;
  String key = configStore.getString("reset_key", "");
  String claim = configStore.getString("reset_claim", "");
  if (configStore.getString("reset_cmd", "") != commandId || key.length() != 43 ||
      !validPanelClaimToken(claim.c_str())) {
    key = factorySecret(); claim = factorySecret();
    if (key.length() != 43 || !validPanelClaimToken(claim.c_str())) return false;
    if (configStore.putString("reset_key", key) != 43 ||
        configStore.putString("reset_claim", claim) != 43 ||
        configStore.putString("reset_cmd", commandId) != commandId.length()) return false;
  }
  keyHash = factoryHash(key); claimHash = factoryHash(claim);
  return keyHash.length() == 64 && claimHash.length() == 64;
#else
  return false;
#endif
}

String pendingPanelFactoryCommand() {
#ifdef CHARGEGRID_PANEL_ENABLED
  return configStore.getString("reset_cmd", "");
#else
  return "";
#endif
}

String pendingPanelFactoryKey() {
#ifdef CHARGEGRID_PANEL_ENABLED
  return configStore.getString("reset_key", "");
#else
  return "";
#endif
}

bool finishPanelFactoryReset(const String& commandId) {
#ifdef CHARGEGRID_PANEL_ENABLED
  if (!commandId.length() || configStore.getString("reset_cmd", "") != commandId ||
      !configStore.putBool("reset_done", true)) return false;
  return finalizeStoredFactoryReset();
#else
  return false;
#endif
}

const char* deviceApiBaseUrl() {
#ifdef CHARGEGRID_PANEL_ENABLED
  return CHARGEGRID_DEFAULT_API_BASE_URL;
#else
  return API_BASE_URL;
#endif
}
const char* deviceAuthorizationKey() {
#ifdef CHARGEGRID_PANEL_ENABLED
  return panelDeviceKey.c_str();
#else
  return DEVICE_KEY;
#endif
}
const char* deviceRootCa() {
#ifdef CHARGEGRID_PANEL_ENABLED
  return CHARGEGRID_ROOT_CA;
#else
  return ROOT_CA;
#endif
}

void confirmPanelOwnership() {
  panelOwned = true;
  panelClaimToken = "";
#ifdef CHARGEGRID_PANEL_ENABLED
  // Retry persistence/removal on every explicitly owned response if NVS fails.
  if (!rememberPanelOwnership(configStore)) Serial.println("[setup] Ownership persistence pending; retrying after sync");
#endif
}

bool savePanelConnection(const char* ssid, const char* password, const char* deviceKey) {
#ifdef CHARGEGRID_PANEL_ENABLED
  if (!validPanelNetwork(ssid, password) || !deviceKey) return false;
  if (state == "charging" || state == "reserved") return false;
  const bool changesIdentity = deviceKey[0] && panelDeviceKey != deviceKey;
  if (changesIdentity && (state == "charging" || state == "reserved" || sessionId.length())) return false;
  bool saved = configStore.putString("wifi_ssid", ssid) > 0;
  saved = savePanelPassword(configStore, password) && saved;
  if (deviceKey[0]) saved = configStore.putString("device_key", deviceKey) > 0 && saved;
  if (!saved) return false;
  if (changesIdentity) { version = 0; lastCommand = ""; persist(); }
  delay(120);
  ESP.restart();
#endif
  return false;
}

#ifdef CHARGEGRID_PANEL_ENABLED
// Carregador GoodWe do conector (teste manual): CG_CHARGER lê agora e mostra o estado; CG_CHARGER_IP
// <ip> fixa o IP (fallback ao mDNS cg-hca-<endereço>.local) e CG_CHARGER_IP clear volta ao host.
void handleChargerCommand(const String& line) {
  if (line.startsWith("CG_CHARGER_IP")) {
    String ip = line.length() > 14 ? line.substring(14) : String();
    ip.trim();
    IPAddress parsed;
    if (ip == "clear") ip = "";
    else if (!parsed.fromString(ip)) { Serial.println("[charger] use CG_CHARGER_IP <a.b.c.d> | CG_CHARGER_IP clear"); return; }
    if (ip.length()) configStore.putString("chg_ip", ip);
    else if (configStore.isKey("chg_ip")) configStore.remove("chg_ip");
    espChargerSetFixedIp(ip);
    Serial.printf("[charger] ip_fixo=%s\n", ip.length() ? ip.c_str() : "-");
    return;
  }
  if (!chargerLink.configured()) {
    Serial.printf("[charger] API sem connector.charger_link (sem endereco): rele/simulacao interna; %s\n",
                  espChargerDescribe().c_str());
    return;
  }
  uint16_t live[3]{}, limit = 0, run = 0, mode = 0, spec = 0, type = 0;
  uint8_t exception = 0;
  const charger::LinkConfig& link = chargerLink.config();
  charger::ModbusClient& client = espChargerClient();
  const bool ok = client.readHolding(link, hca::kChargingPower, 3, live, &exception) &&
      client.readHolding(link, hca::kMaxChargingPower, 1, &limit, &exception) &&
      client.readHolding(link, hca::kChargeMode, 1, &mode, &exception) &&
      client.readHolding(link, hca::kPowerSpec, 1, &spec, &exception) &&
      client.readHolding(link, hca::kChargerType, 1, &type, &exception) &&
      client.readHolding(link, hca::kStartStop, 1, &run, &exception);
  // Próximo START: por Modbus com o carregador respondendo; offline, recusado (charger_offline).
  const char* path = state == "charging" ? (sessionOnCharger ? "modbus" : "simulacao_da_tela")
                                         : (chargerLink.online() ? "modbus" : "recusada_carregador_offline");
  Serial.printf("[charger] goodwe_hca_g2 host=%s porta=%u endereco=%u link=%s recarga=%s falhas=%u ultimo_erro=%s espera_ligado=%s parada_pendente=%s %s\n",
                link.host, link.port, link.address, chargerLink.online() ? "online" : "offline",
                path, chargerLink.failures(),
                charger::errorCode(chargerLink.lastError()) ? charger::errorCode(chargerLink.lastError()) : "-",
                chargerLink.expectRunning() ? "sim" : "nao", chargerLink.pendingStop() ? "sim" : "nao",
                espChargerDescribe().c_str());
  if (ok) Serial.printf("[charger] leitura agora: 10015=%u (%.1f kW) 10017=%u 10029=%u (%.1f kW) 10032=%u 10058=%u 10059=%u 10060=%u\n",
                        live[0], live[0] / 10.0f, live[2], limit, limit / 10.0f, mode, spec, type, run);
  else Serial.printf("[charger] leitura agora falhou%s\n", exception ? " (excecao Modbus)" : "");
  // Carregadores adicionais desta tela (multi_charger_v1).
  for (uint8_t i = 0; i < extra::kMaxSlots; ++i) {
    const extra::Slot& slot = extra::slots[i];
    if (!slot.used) continue;
    Serial.printf("[charger] adicional endereco=%u host=%s link=%s estado=%s sessao=%s energia_wh=%.1f %s%s\n",
                  slot.address, slot.link.config().host, slot.link.online() ? "online" : "offline",
                  slot.state.c_str(), slot.sessionId.length() ? "sim" : "nao", slot.energyWh,
                  espChargerDescribe(i + 1).c_str(), slot.unsupported ? " (sync recusado pela API)" : "");
  }
}

void handleSerialMaintenance() {
  static uint8_t step = 0;
  static String pendingSsid;
  static String migrationCode;
  static String input;
  static unsigned long inputStarted = 0;
  static unsigned long connectStarted = 0;
  if (inputStarted && millis() - inputStarted >= 15000) {
    input = ""; inputStarted = 0; step = 0;
    Serial.println("[setup] Input timed out");
  }
  if (step == 3) {
    if (WiFi.status() == WL_CONNECTED) {
      Serial.printf("[setup] Wi-Fi connected: %s, IP %s\n", WiFi.SSID().c_str(), WiFi.localIP().toString().c_str());
      step = 0;
    } else if (millis() - connectStarted > 20000) {
      Serial.printf("[setup] Wi-Fi connection failed for SSID: %s\n", pendingSsid.c_str());
      step = 0;
    }
    return;
  }
  if (!Serial.available()) return;
  const char incoming = (char)Serial.read();
  if (incoming != '\n') {
    if (incoming != '\r' && input.length() < 193) input += incoming;
    if (!inputStarted) inputStarted = millis();
    if (input.length() < 193 && millis() - inputStarted < 15000) return;
    input = ""; inputStarted = 0; step = 0;
    Serial.println("[setup] Input too long or timed out");
    return;
  }
  String line = input;
  input = ""; inputStarted = 0;
  if (step == 6) {
    step = 0;
    if (line != String("MIGRATE ") + migrationCode || state != "idle" || sessionId.length() ||
        reading.powerW > 0 || WiFi.status() != WL_CONNECTED || !hasSynced || lastSyncHttpStatus != 200) {
      Serial.println("[setup] Migration cancelled: confirmation or idle sync missing"); return;
    }
    if (!preparePanelForFactoryReprovision(configStore, true, false)) {
      Serial.println("[setup] Migration NVS write failed; retry while idle"); return;
    }
    version = 0; lastCommand = ""; persist();
    panelDeviceKey = ""; panelClaimToken = ""; panelOwned = false;
    panelIdentityConfigured = panelIntegrationEnabled = false;
    hasSynced = false; lastSyncHttpStatus = 0;
    Serial.println("[setup] Old identity retired; Wi-Fi preserved. Provision new key and claim token over USB.");
    delay(120); ESP.restart();
    return;
  }
  if (step == 5) {
    step = 0;
    if (!savePanelClaim(configStore, line.c_str(), state == "idle", sessionId.length() > 0, panelOwned)) {
      line = "";
      Serial.println("[setup] Claim token rejected: invalid, owned or session pending"); return;
    }
    panelClaimToken = line; line = "";
    Serial.println("[setup] Claim token saved; pairing screen ready");
    return;
  }
  if (step == 4) {
    step = 0;
    if (state == "charging" || state == "reserved" || sessionId.length()) {
      Serial.println("[setup] Identity change blocked during pending session"); return;
    }
    if (line.length() < 16 || line.length() > 192 || line.indexOf(' ') >= 0) {
      Serial.println("[setup] Invalid device key"); return;
    }
    if (!configStore.putString("device_key", line)) { Serial.println("[setup] NVS write failed"); return; }
    if (panelDeviceKey != line) { version = 0; lastCommand = ""; persist(); }
    panelDeviceKey = line; line = "";
    panelIdentityConfigured = true;
    panelIntegrationEnabled = panelNetworkConfigured;
    hasSynced = false; lastSyncHttpStatus = 0; nextSync = millis();
    Serial.println("[setup] Device key saved; synchronization scheduled");
    return;
  }
  if (step == 0) {
    if (line == "CG_MIGRATE") {
      if (state != "idle" || sessionId.length() || reading.powerW > 0 ||
          !panelOwned || !hasSynced || lastSyncHttpStatus != 200 ||
          WiFi.status() != WL_CONNECTED || connectorPublicCode == "--") {
        Serial.println("[setup] Migration requires an owned, online, idle point without a session"); return;
      }
      migrationCode = connectorPublicCode;
      step = 6;
      Serial.printf("[setup] Type MIGRATE %s to retire old identity (Wi-Fi preserved):\n", migrationCode.c_str());
      return;
    }
    if (line == "CG_CLAIM") {
      if (state != "idle" || sessionId.length() || panelOwned || configStore.getBool("owned", false)) {
        Serial.println("[setup] Claim provisioning requires an unowned idle point"); return;
      }
      step = 5; Serial.println("[setup] Claim token (input hidden):"); return;
    }
    if (line == "CG_SCREEN") {
      if (state != "idle" || sessionId.length()) {
        Serial.println("[screen] Capture requires an idle point without a session"); return;
      }
      if (!chargegridPanelCapture()) Serial.println("[screen] Framebuffer unavailable");
      return;
    }
    if (line == "CG_KEY") {
      if (state == "charging" || state == "reserved" || sessionId.length()) {
        Serial.println("[setup] Identity change blocked during pending session"); return;
      }
      step = 4; Serial.println("[setup] Device key (input hidden):"); return;
    }
    if (line == "CG_STATUS") {
      Serial.printf("[status] state=%s wifi=%s identity=%s synced=%s http=%d session=%s energy_wh=%.3f power_w=%.0f connected=%s source=simulated kiosk=%s kiosk_order=%s firmware=%s\n",
        state.c_str(), WiFi.status() == WL_CONNECTED ? "connected" : "offline",
        panelIdentityConfigured ? "configured" : "missing", hasSynced ? "yes" : "no",
        lastSyncHttpStatus, sessionId.length() ? "present" : "none", reading.energyWh, reading.powerW,
        reading.connected ? "yes" : "no",
        kioskSync.kiosk.enabled ? (kioskSync.kiosk.method == kiosk::Method::Simulated ? "simulated" : "stripe") : "off",
        store.isKey("kord") ? "present" : "none", CHARGEGRID_FIRMWARE_VERSION);
      // Motivo do último reset (1 power-on, 3 software, 4 panic, 5-7 watchdogs, 9 brownout...).
      Serial.printf("[status] reset_reason=%d\n", (int)esp_reset_reason());
      return;
    }
    if (line == "CG_CHARGER" || line.startsWith("CG_CHARGER_IP")) {
      handleChargerCommand(line);
      return;
    }
    if (line == "CG_STOP") {
      requestLocalSafeStop();
      Serial.printf("[stop] state=%s power_w=%.0f\n", state.c_str(), reading.powerW);
      return;
    }
    if (line == "CG_WIFI") {
      if (state == "charging" || state == "reserved") {
        Serial.println("[setup] Network maintenance blocked during an active charging flow");
        return;
      }
      step = 1; Serial.println("[setup] SSID:");
    }
    return;
  }
  if (step == 1) {
    if (!line.length() || line.length() > 32) { step = 0; Serial.println("[setup] Invalid SSID"); return; }
    pendingSsid = line; step = 2; Serial.println("[setup] Password (input hidden):"); return;
  }
  if (line.length() > 64) { step = 0; line = ""; Serial.println("[setup] Invalid password"); return; }
  if (state == "charging" || state == "reserved") {
    step = 0; line = "";
    Serial.println("[setup] Network maintenance blocked during an active charging flow");
    return;
  }
  const bool saved = configStore.putString("wifi_ssid", pendingSsid) > 0 &&
      savePanelPassword(configStore, line.c_str());
  if (!saved) { step = 0; line = ""; Serial.println("[setup] NVS write failed"); return; }
  panelWifiSsid = pendingSsid; panelWifiPassword = line; line = "";
  panelNetworkConfigured = true;
  panelIntegrationEnabled = panelNetworkConfigured && panelIdentityConfigured;
  WiFi.setSleep(false);  // sem economia de energia: Modbus/mDNS com o carregador sem atrasos
  WiFi.begin(panelWifiSsid.c_str(), panelWifiPassword.c_str());
  connectStarted = millis(); step = 3;
  Serial.printf("[setup] Network saved; connecting to SSID: %s\n", pendingSsid.c_str());
}
#endif

// Totem 0.8.0: pedido aberto guardado na NVS para retomar pelo sync após reboot.
void kioskPersistOrder(const char* orderId) {
  if (orderId && orderId[0]) store.putString("kord", orderId);
  else if (store.isKey("kord")) store.remove("kord");
}

bool clearPanelConnection() {
#ifdef CHARGEGRID_PANEL_ENABLED
  if (state == "charging" || state == "reserved") return false;
  bool cleared = (!configStore.isKey("wifi_ssid") || configStore.remove("wifi_ssid"));
  cleared = (!configStore.isKey("wifi_pass") || configStore.remove("wifi_pass")) && cleared;
  if (!cleared) return false;
  WiFi.disconnect(true, true);
  delay(120);
  ESP.restart();
#endif
  return false;
}

void setup() {
  Serial.begin(115200);
  setenv("TZ", "UTC0", 1); tzset();
  store.begin("chargegrid", false);
#ifdef CHARGEGRID_PANEL_ENABLED
  configStore.begin("cg-config", false);
  finalizeStoredFactoryReset();
#endif
  version = store.getUInt("version", 0); lastCommand = store.getString("command", "");
  sessionId = store.getString("session", ""); reading.energyWh = store.getFloat("energy", 0);
  if (sessionId.length()) {
    // A sessão interrompida reporta o SoC final coerente com a energia salva.
    socStartPercent = store.getFloat("soc0", -1); batteryKwh = store.getFloat("batt", 0);
    socSource = store.getString("socsrc", "");
    if (socSource == "phone") phoneSocPercent = socStartPercent;
  }
  reading.socPercent = currentSessionSoc(reading.energyWh);
  applyBootSafety();
  // Carregadores adicionais (multi_charger_v1): sessões do diário relatadas como device_reboot.
  {
    String addresses = store.getString("xaddrs", "");
    int from = 0;
    while (from < (int)addresses.length()) {
      int comma = addresses.indexOf(',', from);
      if (comma < 0) comma = addresses.length();
      const long address = addresses.substring(from, comma).toInt();
      from = comma + 1;
      if (address < 1 || address > 247) continue;
      char name[8];
      snprintf(name, sizeof(name), "x%ldc", address); const String command = store.getString(name, "");
      snprintf(name, sizeof(name), "x%lds", address); const String session = store.getString(name, "");
      snprintf(name, sizeof(name), "x%lde", address); const float energy = store.getFloat(name, 0);
      snprintf(name, sizeof(name), "x%ldv", address); const uint32_t saved = store.getUInt(name, 0);
      extra::restore((uint8_t)address, session.c_str(), energy, saved, command.c_str(), millis());
    }
  }
  Serial.printf("[boot] firmware %s reset_reason=%d\n", CHARGEGRID_FIRMWARE_VERSION, (int)esp_reset_reason());
  bootId = String(esp_random(), HEX) + String(esp_random(), HEX) + String(esp_random(), HEX);
  acknowledgements.to<JsonArray>();
  lastContact = lastTick = millis();
  WiFi.setAutoReconnect(true);
#ifdef CHARGEGRID_PANEL_ENABLED
  panelWifiSsid = configStore.getString("wifi_ssid", "");
  panelWifiPassword = configStore.getString("wifi_pass", "");
  panelDeviceKey = configStore.getString("device_key", "");
  panelOwned = configStore.getBool("owned", false);
  panelClaimToken = configStore.getString("claim_token", "");
  if (panelOwned) confirmPanelOwnership();
  else if (!validPanelClaimToken(panelClaimToken.c_str())) panelClaimToken = "";
  panelIdentityConfigured = panelDeviceKey.length();
  panelNetworkConfigured = panelWifiSsid.length() > 0;
  panelIntegrationEnabled = panelIdentityConfigured && panelNetworkConfigured;
  // Sem economia de energia no Wi-Fi: com o modem dormindo, respostas Modbus passavam do
  // tempo limite e o multicast do mDNS se perdia (link do carregador "preso" offline).
  WiFi.setSleep(false);
  if (panelNetworkConfigured) WiFi.begin(panelWifiSsid.c_str(), panelWifiPassword.c_str());
#else
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
#endif
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  chargerLink.setClient(&espChargerClient(0));
  for (uint8_t i = 0; i < extra::kMaxSlots; ++i) extra::setClient(i, &espChargerClient(i + 1));
#ifdef CHARGEGRID_PANEL_ENABLED
  espChargerSetFixedIp(configStore.getString("chg_ip", ""));
#endif
  panelSetup();
#ifdef CHARGEGRID_KIOSK
  kioskResume(store.getString("kord", "").c_str(), esp_random());
#endif
}
void loop() {
#ifdef CHARGEGRID_PANEL_ENABLED
  static unsigned long nextResetRetry = 0;
  if (configStore.getBool("reset_done", false) && millis() >= nextResetRetry) {
    nextResetRetry = millis() + 5000;
    finalizeStoredFactoryReset();
  }
#endif
  tick();
  // O sync com a API tem prioridade: com ele vencido, a leitura Modbus (até ~0,8 s por
  // carregador offline) espera a próxima volta — o vigia de 45 s nunca depende do Modbus.
  const bool syncDue =
#ifdef CHARGEGRID_PANEL_ENABLED
      panelIntegrationEnabled &&
#endif
      WiFi.status() == WL_CONNECTED && time(nullptr) > 1700000000 && (long)(millis() - nextSync) >= 0;
  if (!syncDue) {
    chargerLinkService(); // Carregador do ponto da tela (link online/offline vai no sync); API antiga: retorna na hora.
    extra::service(millis()); // Carregadores adicionais desta tela (multi_charger_v1).
  }
  panelTick();
#ifdef CHARGEGRID_PANEL_ENABLED
  handleSerialMaintenance();
#endif
  // Hora confiável é necessária para certificados e expiração.
  if (syncDue) syncDevice();
#ifdef CHARGEGRID_KIOSK
  // Um pedido do totem por vez, na mesma tarefa e conexão TLS do sync (nunca em recarga).
  if (panelIntegrationEnabled && WiFi.status() == WL_CONNECTED && time(nullptr) > 1700000000) kioskApiService();
#endif
  delay(20);
}
