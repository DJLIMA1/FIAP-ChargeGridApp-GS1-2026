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
        !configStore.getBool("owned", true) && !configStore.isKey("wifi_ssid")) {
      configStore.putBool("reset_done", false);
      delay(120); ESP.restart();
    }
    return false;
  }
  bool saved = configStore.putString("device_key", newKey) == 43;
  saved = configStore.putString("claim_token", newClaim) == 43 && saved;
  saved = configStore.putBool("owned", false) > 0 && saved;
  saved = (!configStore.isKey("wifi_ssid") || configStore.remove("wifi_ssid")) && saved;
  saved = (!configStore.isKey("wifi_pass") || configStore.remove("wifi_pass")) && saved;
  if (!saved || !store.clear()) return false;
  // The durable completion flag remains until all old credentials and journal
  // entries are gone, so an interrupted reset is safe to retry after reboot.
  saved = (!configStore.isKey("reset_cmd") || configStore.remove("reset_cmd"));
  saved = (!configStore.isKey("reset_key") || configStore.remove("reset_key")) && saved;
  saved = (!configStore.isKey("reset_claim") || configStore.remove("reset_claim")) && saved;
  if (!saved || !configStore.putBool("reset_done", false)) return false;
  WiFi.disconnect(true, true);
  Serial.println("[setup] Factory reset complete; new private claim QR ready");
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
      Serial.printf("[status] state=%s wifi=%s identity=%s synced=%s http=%d session=%s energy_wh=%.3f power_w=%.0f source=simulated firmware=0.3.5\n",
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
  finalizeStoredFactoryReset();
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
#ifdef CHARGEGRID_PANEL_ENABLED
  static unsigned long nextResetRetry = 0;
  if (configStore.getBool("reset_done", false) && millis() >= nextResetRetry) {
    nextResetRetry = millis() + 5000;
    finalizeStoredFactoryReset();
  }
#endif
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
