#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <time.h>
#include "runtime.h"
#include "panel_ui.h"
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
String panelClaimToken;
bool panelOwned = false, connectorOwnershipKnown = false, connectorActive = true;
uint32_t version = 0, sequence = 0;
unsigned long lastContact, lastTick, started, nextSync = 0, lastSaved = 0;
unsigned long maxDurationMs = 3600000;
float maxCost = -1, price = 0, discount = 0;
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
#endif

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
void handleSerialMaintenance() {
  static uint8_t step = 0;
  static String pendingSsid;
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
      Serial.printf("[status] state=%s wifi=%s identity=%s synced=%s http=%d session=%s energy_wh=%.3f power_w=%.0f source=simulated firmware=0.3.1\n",
        state.c_str(), WiFi.status() == WL_CONNECTED ? "connected" : "offline",
        panelIdentityConfigured ? "configured" : "missing", hasSynced ? "yes" : "no",
        lastSyncHttpStatus, sessionId.length() ? "present" : "none", reading.energyWh, reading.powerW);
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
  WiFi.begin(panelWifiSsid.c_str(), panelWifiPassword.c_str());
  connectStarted = millis(); step = 3;
  Serial.printf("[setup] Network saved; connecting to SSID: %s\n", pendingSsid.c_str());
}
#endif

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
#endif
  version = store.getUInt("version", 0); lastCommand = store.getString("command", "");
  sessionId = store.getString("session", ""); reading.energyWh = store.getFloat("energy", 0);
  reading.socPercent = min(100.0f, 20.0f + reading.energyWh / 600.0f);
  if (sessionId.length()) { state = "stopped"; endReason = "communication_lost"; }
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
  if (panelNetworkConfigured) WiFi.begin(panelWifiSsid.c_str(), panelWifiPassword.c_str());
#else
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
#endif
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  panelSetup();
}
void loop() {
  tick();
  panelTick();
#ifdef CHARGEGRID_PANEL_ENABLED
  handleSerialMaintenance();
#endif
  // Hora confiável é necessária para certificados e expiração.
  if (
#ifdef CHARGEGRID_PANEL_ENABLED
      panelIntegrationEnabled &&
#endif
      WiFi.status() == WL_CONNECTED && time(nullptr) > 1700000000 && (long)(millis() - nextSync) >= 0) syncDevice();
  delay(20);
}
