// Runs the actual firmware controller and LVGL screen on a host framebuffer.
#include <cassert>
#include <cmath>
#include <cstdio>
#include "runtime.h"
#include "lvgl.h"
#include "panel_claim.h"

struct ClaimStorage {
  bool owned = false, failWrites = false, failRemove = false;
  std::string token, deviceKey = "legacy-key";
  bool getBool(const char* name, bool) { assert(std::string(name) == "owned"); return owned; }
  size_t putBool(const char* name, bool value) {
    assert(std::string(name) == "owned");
    if (failWrites) return 0;
    owned = value; return 1;
  }
  bool isKey(const char* name) {
    assert(std::string(name) == "claim_token" || std::string(name) == "device_key");
    return std::string(name) == "claim_token" ? !token.empty() : !deviceKey.empty();
  }
  bool remove(const char* name) {
    assert(std::string(name) == "claim_token" || std::string(name) == "device_key");
    if (failRemove) return false;
    if (std::string(name) == "claim_token") token.clear();
    else deviceKey.clear();
    return true;
  }
  size_t putString(const char* name, const char* value) {
    assert(std::string(name) == "claim_token");
    if (failWrites) return 0;
    token = value; return token.size();
  }
} claimStorage;

unsigned long testMillis = 1000;
Preferences store;
SimulatedSensors sensors;
Reading reading{20, 0, 0, false};
String bootId, sessionId, lastCommand, state = "idle", endReason;
String connectorPublicCode = "CG-01";
String stationPresenceCode = "#F12345";
unsigned long presenceCodeReceivedAt = 1000, presenceCodeTtlMs = 300000;
String panelClaimToken;
bool panelOwned = false, connectorOwnershipKnown = false, connectorActive = true;
uint32_t version = 0, sequence = 0;
unsigned long lastContact = 1000, lastTick = 1000, started = 1000, nextSync = 0, lastSaved = 0;
unsigned long maxDurationMs = 3600000;
float maxCost = -1, price = 1, discount = 0;
float chargePowerW = kBenchPowerW;
float socStartPercent = -1, batteryKwh = 0, phoneSocPercent = -1;
String socSource;
time_t reservationDeadline = 0;
JsonDocument acknowledgements;
bool hasSynced = true, sessionPricingKnown = false;
bool panelIntegrationEnabled = true, panelIdentityConfigured = true, panelNetworkConfigured = true;
int lastSyncHttpStatus = 200;
bool savePanelConnection(const char*, const char*, const char*) { return false; }
bool clearPanelConnection() { return false; }
bool preparePanelFactoryReset(const String& commandId, String& keyHash, String& claimHash) {
  if (state != "idle" || sessionId.length() || reading.connected || !panelOwned || !hasSynced) return false;
  assert(commandId.length());
  keyHash = String(std::string(64, 'a').c_str());
  claimHash = String(std::string(64, 'b').c_str());
  return true;
}
bool finishPanelFactoryReset(const String&) { return false; }
bool probePanelFactoryIdentity(const String&) { return false; }
void confirmPanelOwnership() {
  panelOwned = true; panelClaimToken = "";
  rememberPanelOwnership(claimStorage);
}
extern "C" bool lvgl_port_lock(int) { return true; }
extern "C" bool lvgl_port_unlock() { return true; }
bool chargegridPanelHardwareSetup() { return true; }

#include "../../firmware/esp32/src/sensors.cpp"
#include "../../firmware/esp32/src/charging_controller.cpp"
#include "../../firmware/esp32/src/panel_ui.cpp"

static lv_color_t framebuffer[800 * 480], drawbuf[800 * 48];
static unsigned flushCount = 0;
static void flush(lv_disp_drv_t* drv, const lv_area_t* area, lv_color_t* colors) {
  ++flushCount;
  for (int y = area->y1; y <= area->y2; ++y)
    for (int x = area->x1; x <= area->x2; ++x) framebuffer[y * 800 + x] = *colors++;
  lv_disp_flush_ready(drv);
}
static void screenshot(const char* directory, const char* name) {
  panelTick(); refresh(); lv_obj_update_layout(lv_scr_act()); lv_refr_now(nullptr);
  char path[1024]; snprintf(path, sizeof(path), "%s/%s.ppm", directory, name);
  FILE* out = fopen(path, "wb"); assert(out);
  fprintf(out, "P6\n800 480\n255\n");
  for (auto pixel : framebuffer) {
    lv_color32_t rgb; rgb.full = lv_color_to32(pixel);
    fputc(rgb.ch.red, out); fputc(rgb.ch.green, out); fputc(rgb.ch.blue, out);
  }
  fclose(out);
}
static JsonDocument startResponse(bool authorized = true) {
  JsonDocument doc;
  doc["server_time"] = "2026-09-21T12:00:00Z";
  doc["control_version"] = 1;
  doc["connector"]["public_code"] = "CG-01";
  doc["authorized"]["reservation"] = nullptr;
  if (authorized) {
    doc["authorized"]["session"]["id"] = "test-session";
    doc["authorized"]["session"]["max_duration_minutes"] = 60;
    doc["authorized"]["session"]["price_per_kwh"] = 2;
  } else doc["authorized"]["session"] = nullptr;
  auto cmd = doc["commands"].to<JsonArray>().add<JsonObject>();
  cmd["id"] = "start-1"; cmd["type"] = "START"; cmd["version"] = 1;
  cmd["session_id"] = "test-session"; cmd["expires_at"] = "2026-09-21T13:00:00Z";
  return doc;
}
struct NetworkStorage {
  bool present = true, fail = false;
  std::string value = "old-password";
  bool isKey(const char* key) { assert(std::string(key) == "wifi_pass"); return present; }
  bool remove(const char* key) {
    assert(std::string(key) == "wifi_pass");
    if (fail) return false;
    present = false; value.clear(); return true;
  }
  size_t putString(const char* key, const char* password) {
    assert(std::string(key) == "wifi_pass");
    if (fail) return 0;
    present = true; value = password; return value.size();
  }
};

int main(int argc, char** argv) {
  constexpr const char* claimToken = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefg";
  assert(validPanelClaimToken(claimToken));
  assert(!validPanelClaimToken(nullptr));
  assert(!validPanelClaimToken("short"));
  assert(!validPanelClaimToken("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef="));
  assert(!validPanelClaimToken("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef/"));
  assert(!savePanelClaim(claimStorage, claimToken, false, false, false));
  assert(!savePanelClaim(claimStorage, claimToken, true, true, false));
  assert(!savePanelClaim(claimStorage, claimToken, true, false, true));
  assert(savePanelClaim(claimStorage, claimToken, true, false, false));
  claimStorage.failRemove = true;
  assert(!rememberPanelOwnership(claimStorage) && claimStorage.owned);
  assert(!savePanelClaim(claimStorage, claimToken, true, false, false));
  claimStorage.failRemove = false;
  assert(rememberPanelOwnership(claimStorage) && claimStorage.token.empty());
  assert(!preparePanelForFactoryReprovision(claimStorage, false, false));
  assert(!preparePanelForFactoryReprovision(claimStorage, true, true));
  assert(claimStorage.owned && !claimStorage.deviceKey.empty());
  claimStorage.failRemove = true;
  assert(!preparePanelForFactoryReprovision(claimStorage, true, false));
  assert(claimStorage.owned);
  claimStorage.failRemove = false;
  assert(preparePanelForFactoryReprovision(claimStorage, true, false));
  assert(!claimStorage.owned && claimStorage.deviceKey.empty() && claimStorage.token.empty());
  claimStorage = ClaimStorage{};
  assert(validPanelNetwork("open-network", ""));
  assert(!validPanelNetwork("", ""));
  assert(!validPanelNetwork("open-network", nullptr));
  NetworkStorage network;
  assert(savePanelPassword(network, "") && !network.present && network.value.empty());
  assert(savePanelPassword(network, ""));
  assert(savePanelPassword(network, "new-password") && network.value == "new-password");
  network.fail = true;
  assert(!savePanelPassword(network, "") && network.present);
  assert(!savePanelPassword(network, "another-password"));
  assert(argc == 2);
  setenv("TZ", "UTC0", 1); tzset();
  acknowledgements.to<JsonArray>();
  auto unauthorized = startResponse(false);
  apply(unauthorized); assert(state == "idle" && sessionId.empty());
  assert(acknowledgements[0]["status"] == "failed");
  version = 0;
  auto response = startResponse();
  assert(apply(response)); assert(state == "charging" && reading.connected);
  testMillis += 10000; tick(); assert(std::abs(reading.energyWh - 20) < 0.01);
  auto before = reading.energyWh;
  apply(response); assert(reading.energyWh == before); // Repeated START never resets energy.
  requestLocalSafeStop(); assert(state == "stopped" && !reading.connected && reading.powerW == 0);
  apply(response); assert(state == "stopped"); // Reboot/retry cannot resume a stopped session.
  assert(acknowledgements[0]["status"] == "failed");
  sessionId = ""; lastCommand = ""; version = 0; state = "idle";
  apply(response); lastContact = testMillis;
  testMillis += 50000; tick();
  assert(state == "stopped" && endReason == "communication_lost");
  assert(std::abs(reading.energyWh - 90) < 0.01); // Only the first 45 seconds count.
  sessionId = ""; lastCommand = ""; version = 0; state = "idle";
  response["authorized"]["session"]["max_cost"] = 0.01;
  apply(response); lastContact = testMillis;
  testMillis += 10000; tick();
  assert(state == "stopped" && endReason == "cost_limit");
  assert(reading.energyWh <= 5.001); // Money limit is enforced during a blocked network call.
  assert(!sensors.read(false, 0).connected);
  // Station/driver power limit: max_power_kw caps the simulated power (text Decimal accepted).
  sessionId = ""; lastCommand = ""; version = 0; state = "idle";
  auto limited = startResponse();
  limited["commands"][0]["parameters"]["max_power_kw"] = "3.6";
  apply(limited); lastContact = testMillis;
  assert(state == "charging" && std::abs(chargePowerW - 3600) < 0.01);
  testMillis += 10000; tick();
  assert(std::abs(reading.powerW - 3600) < 0.01 && std::abs(reading.energyWh - 10) < 0.01);
  sessionId = ""; lastCommand = ""; version = 0; state = "idle";
  limited["commands"][0]["parameters"]["max_power_kw"] = 60; // Above the bench rating: rating wins.
  apply(limited); assert(std::abs(chargePowerW - 7200) < 0.01);

  // Car SoC: legacy START (no fields) keeps the old bench behaviour and no battery stop.
  sessionId = ""; lastCommand = ""; version = 0; state = "idle";
  response["authorized"]["session"].remove("max_cost");
  apply(response); lastContact = testMillis;
  assert(state == "charging" && !sessionSocKnown() && socSource.empty());
  testMillis += 10000; tick();
  assert(state == "charging" && std::abs(reading.socPercent - (20 + 20.0f / 600)) < 0.001);
  // Simulated source: SoC rises with delivered energy (start + kWh / battery * 100).
  sessionId = ""; lastCommand = ""; version = 0; state = "idle";
  auto socStart = startResponse();
  socStart["commands"][0]["parameters"]["soc_percent"] = 50;
  socStart["commands"][0]["parameters"]["battery_kwh"] = "60.00"; // Decimal serialised as text.
  socStart["commands"][0]["parameters"]["soc_source"] = "simulated";
  apply(socStart); lastContact = testMillis;
  assert(state == "charging" && sessionSocKnown() && std::abs(reading.socPercent - 50) < 0.001);
  testMillis += 10000; tick();
  assert(std::abs(reading.socPercent - (50 + 20.0f / 600)) < 0.001);
  auto socSync = socStart; socSync["commands"].to<JsonArray>();
  socSync["authorized"]["session"]["soc_percent"] = 12; // API echo never overrides the simulation.
  apply(socSync); assert(std::abs(reading.socPercent - (50 + 20.0f / 600)) < 0.001);
  // At 100 % the bench stops locally (energy capped exactly at the free capacity).
  sessionId = ""; lastCommand = ""; version = 0; state = "idle";
  socStart["commands"][0]["parameters"]["soc_percent"] = 99.9;
  socStart["commands"][0]["parameters"]["battery_kwh"] = 10;
  apply(socStart); lastContact = testMillis;
  testMillis += 10000; tick();
  assert(state == "stopped" && endReason == "battery_full" && reading.socPercent == 100);
  assert(std::abs(reading.energyWh - 10) < 0.05 && reading.powerW == 0 && !reading.connected);
  // Phone source: the device shows the level pushed by the app and never recalculates it.
  sessionId = ""; lastCommand = ""; version = 0; state = "idle";
  socStart["commands"][0]["parameters"]["soc_percent"] = 40;
  socStart["commands"][0]["parameters"]["soc_source"] = "phone";
  apply(socStart); lastContact = testMillis;
  assert(state == "charging" && sessionSocKnown() && reading.socPercent == 40);
  testMillis += 10000; tick();
  assert(state == "charging" && reading.socPercent == 40);
  socSync = socStart; socSync["commands"].to<JsonArray>();
  socSync["authorized"]["session"]["soc_source"] = "phone";
  socSync["authorized"]["session"]["soc_percent"] = "63.50";
  apply(socSync); lastContact = testMillis;
  assert(reading.socPercent == 63.5f);
  testMillis += 10000; tick(); assert(state == "charging" && reading.socPercent == 63.5f);
  auto fullStop = socSync;
  auto stopCommand = fullStop["commands"].to<JsonArray>().add<JsonObject>();
  stopCommand["id"] = "stop-full"; stopCommand["type"] = "STOP"; stopCommand["version"] = 2;
  stopCommand["session_id"] = "test-session"; stopCommand["expires_at"] = "2026-09-21T13:00:00Z";
  stopCommand["parameters"]["reason"] = "battery_full";
  fullStop["control_version"] = 2;
  assert(apply(fullStop) && state == "stopped" && endReason == "battery_full");
  assert(acknowledgements[0]["status"] == "applied");
  sessionId = ""; lastCommand = ""; version = 0; state = "idle"; endReason = "";
  socSource = ""; socStartPercent = -1; batteryKwh = 0; phoneSocPercent = -1;

  // A reboot starts idle. Replaying the old RESERVE must not falsely ACK it;
  // only a fresh server version can restore the reservation and its deadline.
  sessionId = ""; lastCommand = ""; version = 0; state = "idle";
  JsonDocument reservation;
  reservation["server_time"] = "2026-09-21T12:00:00Z";
  reservation["control_version"] = 1;
  reservation["authorized"]["session"] = nullptr;
  reservation["authorized"]["reservation"]["id"] = "reservation-1";
  reservation["authorized"]["reservation"]["expires_at"] = "2030-01-01T12:00:00Z";
  auto reserve = reservation["commands"].to<JsonArray>().add<JsonObject>();
  reserve["id"] = "reserve-1"; reserve["version"] = 1; reserve["type"] = "RESERVE";
  reserve["reservation_id"] = "reservation-1"; reserve["expires_at"] = "2030-01-01T12:00:00Z";
  assert(apply(reservation) && state == "reserved");
  const auto deadline = reservationDeadline;
  apply(reservation); assert(acknowledgements[0]["status"] == "applied");
  state = "idle"; // Simulated reboot, persistent version/command unchanged.
  apply(reservation);
  assert(state == "idle" && acknowledgements[0]["status"] == "failed");
  reservation["control_version"] = 2; reserve["id"] = "reserve-restored"; reserve["version"] = 2;
  assert(apply(reservation) && state == "reserved" && reservationDeadline == deadline);

  // ---- 0.7.0: live power (SET_POWER), power_limit_w START, overstay, sync extensions ----
  auto resetSession = [] {
    sessionId = ""; lastCommand = ""; version = 0; state = "idle"; endReason = "";
    socSource = ""; socStartPercent = -1; batteryKwh = 0; phoneSocPercent = -1;
    reading = {20, 0, 0, false}; overstayEnabled = false; chargePowerW = kBenchPowerW;
    maxCost = -1; lastContact = testMillis;
  };
  assert(chargerLimitW(0) == 0 && chargerLimitW(-5) == 0);
  assert(chargerLimitW(6000) == 6000 && chargerLimitW(6049) == 6000 && chargerLimitW(9000) == 7200);
  assert(chargerLimitW(1399) == 0 && chargerLimitW(1400) == 1400); // Below the floor pauses, never exceeds.
  assert(panelLatin1("Loja 24/30 kW \u00B7 3 carros", 40) == "Loja 24/30 kW \u00B7 3 carros");
  assert(panelLatin1("  Pico \u2014 2 carros \U0001F697", 40) == "Pico 2 carros"); // Glyphs the fonts lack.
  assert(panelLatin1(std::string(50, 'a').c_str(), 40) == std::string(40, 'a'));
  assert(panelLatin1(nullptr, 40).empty());
  resetSession();
  JsonDocument syncBody; fillSyncBody(syncBody, true);
  assert(syncBody["firmware_version"] == "0.7.0" && syncBody["connected"] == false);
  assert(syncBody["capabilities"].size() == 1 && syncBody["capabilities"][0] == "set_power_v1");
  assert(syncBody["applied_power_w"] == 0); // Idle: nothing installed.
  assert(syncBody["charger"]["model"] == "esp32_bench" && syncBody["charger"]["transport"] == "simulated");
  assert(syncBody["charger"]["min_power_w"] == 1400 && syncBody["charger"]["max_power_w"] == 7200);
  assert(syncBody["charger"]["step_w"] == 100);
  JsonDocument legacySync; fillSyncBody(legacySync, false); // Older API (extra="forbid").
  assert(legacySync["firmware_version"] == "0.7.0" && legacySync["capabilities"].isNull());
  assert(legacySync["applied_power_w"].isNull() && legacySync["charger"].isNull());
  assert(!legacySync["acks"].isNull() && !legacySync["energy_wh"].isNull());
  // START: power_limit_w wins over the legacy max_power_kw; integer W, rounded down to the step.
  auto powered = startResponse();
  powered["commands"][0]["parameters"]["max_power_kw"] = "3.6";
  powered["commands"][0]["parameters"]["power_limit_w"] = 5000;
  apply(powered); lastContact = testMillis;
  assert(state == "charging" && chargePowerW == 5000 && reading.powerW == 5000);
  assert(acknowledgements[0]["status"] == "applied");
  testMillis += 3600; tick(); assert(std::abs(reading.energyWh - 5) < 0.01);
  syncBody.clear(); fillSyncBody(syncBody, true); assert(syncBody["applied_power_w"] == 5000);
  // START paused (power_limit_w = 0): charging, no energy, no division by zero on the limits.
  resetSession();
  auto paused = startResponse();
  paused["authorized"]["session"]["max_cost"] = 5;
  paused["commands"][0]["parameters"]["power_limit_w"] = 0;
  paused["commands"][0]["parameters"]["soc_percent"] = 50;
  paused["commands"][0]["parameters"]["battery_kwh"] = 40;
  paused["commands"][0]["parameters"]["soc_source"] = "simulated";
  apply(paused); lastContact = testMillis;
  assert(state == "charging" && chargePowerW == 0 && reading.powerW == 0 && reading.connected);
  testMillis += 20000; lastContact = testMillis; tick();
  assert(state == "charging" && reading.energyWh == 0 && reading.powerW == 0 && endReason.empty());
  syncBody.clear(); fillSyncBody(syncBody, true);
  assert(syncBody["applied_power_w"] == 0 && syncBody["physical_state"] == "charging");
  // SET_POWER: raise from pause, reduce, replay, 0 W pause, wrong session, invalid, after STOP.
  auto setPower = [](const char* id, int commandVersion, JsonVariantConst limit, const char* session = "test-session") {
    JsonDocument doc = startResponse();
    doc["control_version"] = commandVersion;
    auto cmd = doc["commands"].to<JsonArray>().add<JsonObject>();
    cmd["id"] = id; cmd["type"] = "SET_POWER"; cmd["version"] = commandVersion;
    cmd["session_id"] = session; cmd["expires_at"] = "2026-09-21T13:00:00Z";
    cmd["reservation_id"] = nullptr;
    if (!limit.isNull()) cmd["parameters"]["power_limit_w"] = limit;
    cmd["parameters"]["previous_power_w"] = 0; cmd["parameters"]["decision_id"] = 123;
    cmd["parameters"]["reason_short"] = "Loja 24/30 kW";
    return doc;
  };
  JsonDocument limits; limits.add(7200); limits.add(3600); limits.add(0); limits.add(6049); limits.add(-1);
  auto raise = setPower("power-1", 2, limits[0]);
  assert(apply(raise) && chargePowerW == 7200 && version == 2 && lastCommand == "power-1");
  assert(acknowledgements[0]["status"] == "applied" && acknowledgements[0]["applied_power_w"] == 7200);
  assert(acknowledgements[0]["error"].isNull());
  testMillis += 10000; lastContact = testMillis; // 10 s at 7.2 kW before the reduction arrives.
  auto reduce = setPower("power-2", 3, limits[1]);
  assert(apply(reduce) && chargePowerW == 3600 && reading.powerW == 3600);
  assert(std::abs(reading.energyWh - 20) < 0.01); // Old power integrated up to the switch.
  assert(acknowledgements[0]["applied_power_w"] == 3600);
  testMillis += 10000; lastContact = testMillis; tick();
  assert(std::abs(reading.energyWh - 30) < 0.01); // New power from the switch on.
  assert(!apply(reduce) && acknowledgements[0]["status"] == "applied"); // Redelivery: same value again.
  assert(acknowledgements[0]["applied_power_w"] == 3600 && version == 3);
  auto pause = setPower("power-3", 4, limits[2]);
  assert(apply(pause) && state == "charging" && chargePowerW == 0 && reading.powerW == 0);
  assert(acknowledgements[0]["status"] == "applied" && acknowledgements[0]["applied_power_w"] == 0);
  const float pausedEnergy = reading.energyWh;
  const unsigned long pausedStarted = started;
  testMillis += 30000; lastContact = testMillis; tick();
  assert(state == "charging" && reading.energyWh == pausedEnergy && started == pausedStarted);
  auto rounded = setPower("power-4", 5, limits[3]);
  assert(apply(rounded) && chargePowerW == 6000 && acknowledgements[0]["applied_power_w"] == 6000);
  auto mismatch = setPower("power-5", 6, limits[1], "other-session");
  assert(!apply(mismatch) && acknowledgements[0]["status"] == "failed");
  assert(acknowledgements[0]["error"] == "no_active_session" && chargePowerW == 6000 && lastCommand == "power-4");
  auto invalid = setPower("power-6", 7, limits[4]);
  assert(!apply(invalid) && acknowledgements[0]["error"] == "invalid_power_limit" && chargePowerW == 6000);
  auto missing = setPower("power-7", 8, JsonVariantConst());
  assert(!apply(missing) && acknowledgements[0]["error"] == "invalid_power_limit");
  requestLocalSafeStop(); assert(state == "stopped" && !reading.connected); // No overstay: disconnects.
  auto late = setPower("power-8", 9, limits[1]);
  assert(!apply(late) && acknowledgements[0]["error"] == "no_active_session" && reading.powerW == 0);
  // Authorized session power fields are shown only (sanitised reason, applied value).
  resetSession();
  auto shown = startResponse(); apply(shown); lastContact = testMillis;
  shown["commands"].to<JsonArray>();
  shown["authorized"]["session"]["applied_power_kw"] = 6.0;
  shown["authorized"]["session"]["target_power_kw"] = 7.2;
  shown["authorized"]["session"]["power_state"] = "raising";
  shown["authorized"]["session"]["power_reason_short"] = "Loja 24/30 kW \u00B7 3 carros \u2014 pico";
  apply(shown);
  assert(sessionAppliedPowerKw == 6.0f && powerReasonShort == "Loja 24/30 kW \u00B7 3 carros pico");
  shown["authorized"]["session"].remove("applied_power_kw"); shown["authorized"]["session"].remove("power_reason_short");
  apply(shown); assert(sessionAppliedPowerKw < 0 && powerReasonShort.empty()); // Older API: nothing shown.

  // Overstay: without parameters.overstay the old disconnect-on-stop behaviour is kept.
  resetSession();
  apply(response); lastContact = testMillis; assert(!overstayEnabled);
  requestLocalSafeStop(); assert(state == "stopped" && !reading.connected);
  assert(!requestLocalDisconnect()); // Nothing connected: no extra sync.
  resetSession();
  auto withOverstay = startResponse();
  auto terms = withOverstay["commands"][0]["parameters"]["overstay"].to<JsonObject>();
  terms["grace_minutes"] = 5; terms["interval_minutes"] = 10; terms["amount"] = "1.50"; terms["max_amount"] = "15.00";
  apply(withOverstay); lastContact = testMillis;
  assert(state == "charging" && overstayEnabled && reading.connected);
  assert(!requestLocalDisconnect() && reading.connected); // Never during charging.
  requestLocalSafeStop();
  assert(state == "stopped" && reading.connected && reading.powerW == 0 && endReason == "requested");
  syncBody.clear(); fillSyncBody(syncBody, true);
  assert(syncBody["connected"] == true && syncBody["physical_state"] == "stopped" && syncBody["applied_power_w"] == 0);
  JsonDocument closed; // The API ends the session; the car is still plugged in.
  closed["server_time"] = "2026-09-21T12:00:00Z"; closed["control_version"] = 1;
  closed["connector"]["public_code"] = "CG-01";
  closed["authorized"]["session"] = nullptr; closed["authorized"]["reservation"] = nullptr;
  closed["commands"].to<JsonArray>();
  closed["overstay"]["session_id"] = "test-session"; closed["overstay"]["status"] = "grace";
  closed["overstay"]["grace_remaining_seconds"] = 300; closed["overstay"]["fee_due"] = "0.00";
  closed["overstay"]["max_fee"] = "15.00"; closed["overstay"]["amount"] = "1.50";
  closed["overstay"]["interval_minutes"] = 10;
  apply(closed);
  assert(state == "idle" && sessionId.empty() && reading.connected && overstayStatus == "grace");
  assert(overstayGraceSeconds == 300 && overstayMaxFee == 15.0f && overstayAmount == 1.5f && overstayIntervalMinutes == 10);
  JsonDocument busyReset; // FACTORY_RESET is refused while a car is connected.
  busyReset["server_time"] = "2026-09-21T12:00:00Z"; busyReset["control_version"] = 2;
  busyReset["authorized"]["session"] = nullptr; busyReset["authorized"]["reservation"] = nullptr;
  auto busyCommand = busyReset["commands"].to<JsonArray>().add<JsonObject>();
  busyCommand["id"] = "reset-busy"; busyCommand["type"] = "FACTORY_RESET"; busyCommand["version"] = 2;
  busyCommand["expires_at"] = "2030-01-01T12:00:00Z";
  panelOwned = true;
  apply(busyReset);
  assert(acknowledgements[0]["status"] == "failed" && acknowledgements[0]["error"] == "factory_reset_requires_idle");
  panelOwned = false;
  nextSync = testMillis + 5000;
  assert(requestLocalDisconnect() && !reading.connected && !overstayEnabled && nextSync == testMillis);
  closed["overstay"] = nullptr; apply(closed); assert(overstayStatus.empty());
  // RELEASE clears the connection; a reboot always starts disconnected.
  resetSession();
  apply(withOverstay); lastContact = testMillis; requestLocalSafeStop();
  JsonDocument release;
  release["server_time"] = "2026-09-21T12:00:00Z"; release["control_version"] = 2;
  release["authorized"]["session"]["id"] = "test-session"; release["authorized"]["reservation"] = nullptr;
  auto releaseCommand = release["commands"].to<JsonArray>().add<JsonObject>();
  releaseCommand["id"] = "release-1"; releaseCommand["type"] = "RELEASE"; releaseCommand["version"] = 2;
  releaseCommand["session_id"] = "test-session"; releaseCommand["expires_at"] = "2030-01-01T12:00:00Z";
  assert(apply(release) && state == "idle" && !reading.connected && !overstayEnabled);
  resetSession();
  apply(withOverstay); lastContact = testMillis; requestLocalSafeStop(); assert(reading.connected);
  applyBootSafety(); // Simulated reboot with the session journal still present.
  assert(!reading.connected && !overstayEnabled && state == "stopped" && endReason == "communication_lost");
  assert(chargePowerW == kBenchPowerW && reading.powerW == 0);
  // Payment kiosk fields: https URL only; unknown/absent fields mean no QR (older API).
  JsonDocument kiosk;
  kiosk["connector"]["public_code"] = "CG-01";
  kiosk["connector"]["kiosk_url"] = "https://api.example.test/pay/k/CG-01?c=12345";
  kiosk["connector"]["payment"]["status"] = "awaiting_payment";
  kiosk["connector"]["payment"]["amount"] = "20.00";
  kiosk["connector"]["payment"]["environment"] = "test";
  kiosk["authorized"]["session"] = nullptr; kiosk["authorized"]["reservation"] = nullptr;
  kiosk["commands"].to<JsonArray>();
  apply(kiosk);
  assert(kioskUrl == "https://api.example.test/pay/k/CG-01?c=12345");
  assert(paymentStatus == "awaiting_payment" && paymentAmount == 20.0f && paymentTest);
  kiosk["connector"]["kiosk_url"] = "javascript:alert(1)"; kiosk["connector"]["payment"]["status"] = "refunded";
  apply(kiosk); assert(kioskUrl.empty() && paymentStatus.empty());
  kiosk["connector"].remove("kiosk_url"); kiosk["connector"].remove("payment");
  apply(kiosk); assert(kioskUrl.empty() && paymentStatus.empty() && paymentAmount < 0);
  resetSession(); sessionId = ""; state = "idle";

  lv_init();
  static lv_disp_draw_buf_t db; lv_disp_draw_buf_init(&db, drawbuf, nullptr, 800 * 48);
  static lv_disp_drv_t dd; lv_disp_drv_init(&dd);
  dd.hor_res = 800; dd.ver_res = 480; dd.flush_cb = flush; dd.draw_buf = &db;
  lv_disp_drv_register(&dd); panelSetup();
  sessionId = ""; state = "idle"; lastContact = testMillis;
  panelOwned = true; connectorOwnershipKnown = true; connectorActive = true;
  connectorPublicCode = "CG-01";
  stationPresenceCode = "#F12345";
  presenceCodeReceivedAt = testMillis;
  presenceCodeTtlMs = 300000;
  screenshot(argv[1], "panel-idle");
  assert(std::string(lv_label_get_text(statusLabel)) == "Pronto para você");
  assert(std::string(lv_label_get_text(codeLabel)) == "#F12345");
  assert(std::string(lv_label_get_text(codeTimerLabel)) == "Troca em 05:00");
  assert(lv_bar_get_value(codeProgressBar) == 100);
  assert(!lv_obj_has_flag(stepsCard, LV_OBJ_FLAG_HIDDEN));
  assert(lv_obj_has_flag(sessionCard, LV_OBJ_FLAG_HIDDEN));
  flushCount = 0;
  panelTick(); refresh(); lv_refr_now(nullptr);
  assert(flushCount == 0); // An unchanged snapshot must not redraw the RGB panel.
  connectorPublicCode = "CG-4C754B2F6E";
  presenceCodeTtlMs = 0; // The code expired just before the next sync.
  panelTick(); refresh();
  assert(std::string(lv_label_get_text(codeLabel)) == "--");
  assert(std::string(lv_label_get_text(codeTimerLabel)) == "Novo código em instantes");
  assert(lv_bar_get_value(codeProgressBar) == 0);
  connectorPublicCode = "CG-01";
  stationPresenceCode = "null"; // Older API omitted the field.
  panelTick(); refresh();
  assert(std::string(lv_label_get_text(codeLabel)) == "CG-01");
  assert(std::string(lv_label_get_text(codeTimerLabel)) == "Código #F em breve");
  stationPresenceCode = "#F12345";
  presenceCodeTtlMs = 300000;
  state = "reserved"; reservationDeadline = time(nullptr) + 30;
  screenshot(argv[1], "panel-reserved");
  assert(flushCount > 0); // A real state transition still reaches the display.
  assert(std::string(lv_label_get_text(timeLabel)) == "1 min");
  assert(!lv_obj_has_flag(reservationCard, LV_OBJ_FLAG_HIDDEN));
  state = "charging"; sessionId = "test-session"; reading = {42, 3210, 7200, true};
  screenshot(argv[1], "panel-charging");
  assert(!lv_obj_has_flag(sessionCard, LV_OBJ_FLAG_HIDDEN));
  assert(!lv_obj_has_flag(stopButton, LV_OBJ_FLAG_HIDDEN));
  assert(lv_obj_has_flag(batteryCard, LV_OBJ_FLAG_HIDDEN)); // No SoC from the API: legacy layout.
  socSource = "simulated"; socStartPercent = 35; batteryKwh = 50;
  reading.socPercent = currentSessionSoc(reading.energyWh);
  screenshot(argv[1], "panel-charging-soc");
  assert(!lv_obj_has_flag(batteryCard, LV_OBJ_FLAG_HIDDEN));
  assert(std::string(lv_label_get_text(socLabel)) == "41%");
  assert(std::string(lv_label_get_text(socDetailLabel)) == "Início 35%");
  assert(lv_bar_get_value(socBar) == 41);
  assert(!lv_obj_has_flag(stopButton, LV_OBJ_FLAG_HIDDEN));
  socSource = "phone"; phoneSocPercent = 99.6f; reading.socPercent = 99.6f;
  panelTick(); refresh();
  assert(std::string(lv_label_get_text(socLabel)) == "99%"); // Never shows 100% before full.
  state = "stopped"; endReason = "battery_full"; reading.socPercent = 100;
  screenshot(argv[1], "panel-battery-full");
  assert(std::string(lv_label_get_text(statusLabel)) == "Bateria cheia");
  assert(std::string(lv_label_get_text(socLabel)) == "100%");
  assert(lv_obj_has_flag(stopButton, LV_OBJ_FLAG_HIDDEN));
  // The API ends the session in the same sync: the end state is held for 10 s.
  state = "idle"; sessionId = ""; endReason = ""; reading = {20, 0, 0, false};
  socSource = ""; socStartPercent = -1; batteryKwh = 0; phoneSocPercent = -1;
  testMillis += 5000; lastContact = testMillis; panelTick(); refresh();
  assert(std::string(lv_label_get_text(statusLabel)) == "Bateria cheia");
  testMillis += 6000; lastContact = testMillis; panelTick(); refresh();
  assert(std::string(lv_label_get_text(statusLabel)) == "Pronto para você");
  sessionId = "test-session";
  state = "charging"; endReason = ""; reading = {42, 3210, 7200, true};
  socSource = ""; socStartPercent = -1; batteryKwh = 0; phoneSocPercent = -1;
  lv_event_send(stopButton, LV_EVENT_CLICKED, nullptr); panelTick();
  assert(state == "stopped" && reading.powerW == 0 && endReason == "requested");
  screenshot(argv[1], "panel-stopped");
  auto text = [](lv_obj_t* target) { return std::string(lv_label_get_text(target)); };
  auto hidden = [](lv_obj_t* target) { return lv_obj_has_flag(target, LV_OBJ_FLAG_HIDDEN); };
  // 0.7.0 live power: the applied value confirmed by the API and the short reason; 0 W is a pause.
  state = "charging"; endReason = ""; reading = {42, 3210, 6000, true}; chargePowerW = 6000;
  sessionAppliedPowerKw = 6.0f; powerReasonShort = "Loja 24/30 kW \u00B7 3 carros";
  screenshot(argv[1], "panel-charging-power");
  assert(text(statusLabel) == "Recarga em andamento");
  assert(text(instructionLabel) == "Potência 6,0 kW \u00B7 Loja 24/30 kW \u00B7 3 carros");
  chargePowerW = 0; sessionAppliedPowerKw = 0; reading.powerW = 0;
  screenshot(argv[1], "panel-charging-paused");
  assert(text(statusLabel) == "Recarga pausada" && !hidden(stopButton));
  assert(text(instructionLabel) == "Pausada para dividir a potência: Loja 24/30 kW \u00B7 3 carros");
  sessionAppliedPowerKw = -1; powerReasonShort = ""; chargePowerW = kBenchPowerW; reading.powerW = 7200;
  panelTick(); refresh();
  assert(text(instructionLabel) == "Acompanhe pelo app. Para parar, toque em Encerrar."); // Older API.
  // 0.7.0 overstay: stopped but still plugged in; local countdown, then the fee from the API.
  overstayEnabled = true; requestLocalSafeStop(); assert(state == "stopped" && reading.connected);
  overstayStatus = "grace"; overstayGraceSeconds = 300; overstayReceivedAt = testMillis;
  overstayAmount = 1.5f; overstayIntervalMinutes = 10; overstayMaxFee = 15; overstayFeeDue = 0;
  screenshot(argv[1], "panel-overstay-grace");
  assert(text(statusLabel) == "Recarga concluída" && text(connectionLabel) == "Carro conectado");
  assert(text(messageTitle) == "Recarga concluída \u00B7 desconecte em 05:00");
  assert(text(messageDetail) == "Após a tolerância: R$ 1,50 a cada 10 min, até R$ 15,00.");
  assert(!hidden(disconnectButton) && hidden(stopButton) && !hidden(messageCard));
  testMillis += 61000; lastContact = testMillis; panelTick(); refresh();
  assert(text(messageTitle) == "Recarga concluída \u00B7 desconecte em 03:59");
  state = "idle"; sessionId = ""; endReason = ""; // The API ended the session; the car stays.
  overstayStatus = "billing"; overstayFeeDue = 1.5f;
  screenshot(argv[1], "panel-overstay-fee");
  assert(text(messageTitle) == "Taxa de permanência: R$ 1,50");
  assert(hidden(codeCard) && !hidden(disconnectButton) && text(statusLabel) == "Recarga concluída");
  overstayStatus = "capped"; overstayFeeDue = 15; panelTick(); refresh();
  assert(text(messageTitle) == "Taxa de permanência: R$ 15,00 (valor máximo)");
  overstayStatus = "no_fee"; panelTick(); refresh();
  assert(text(messageTitle) == "Recarga concluída \u00B7 desconecte o carro");
  assert(text(messageDetail) == "Sem taxa de permanência neste ponto.");
  nextSync = testMillis + 5000;
  lv_event_send(disconnectButton, LV_EVENT_CLICKED, nullptr); panelTick();
  assert(!reading.connected && !overstayEnabled && nextSync == testMillis);
  overstayStatus = ""; panelTick(); refresh();
  assert(text(statusLabel) == "Pronto para você" && hidden(disconnectButton));
  // 0.7.0 payment kiosk QR on the Ready screen (Stripe test mode).
  kioskUrl = "https://chargegrid-api-preview-djlima1s-projects.vercel.app/pay/k/CG-01?c=12345";
  paymentStatus = ""; paymentAmount = -1; paymentTest = false;
  screenshot(argv[1], "panel-kiosk-qr");
  assert(!hidden(kioskCard) && !hidden(kioskQrBox) && hidden(stepsCard) && !hidden(codeCard));
  assert(std::string(lastKioskQr) == kioskUrl && text(kioskTitle) == "Sem o app? Pague aqui \u00B7 TESTE");
  assert(text(kioskDetail) == "Escaneie com a câmera do celular e escolha o valor.");
  assert(text(instructionLabel).find("pague pelo QR") != std::string::npos);
  assert(lv_obj_get_width(rowLineTop) == 531 && lv_obj_get_y(codeCard) == 118);
  paymentStatus = "awaiting_payment"; paymentAmount = 20; paymentTest = true;
  screenshot(argv[1], "panel-kiosk-awaiting");
  assert(text(kioskDetail) == "Aguardando pagamento (teste) \u00B7 R$ 20,00");
  paymentStatus = "paid"; panelTick(); refresh();
  assert(text(kioskDetail) == "Pagamento confirmado (teste) \u00B7 iniciando");
  kioskUrl = ""; panelTick(); refresh(); // QR gone (e.g. START on its way): status stays visible.
  assert(hidden(kioskCard) && hidden(kioskQrBox) && !hidden(stepsCard));
  assert(text(instructionLabel) == "Pagamento confirmado (teste) \u00B7 iniciando");
  lv_obj_update_layout(lv_scr_act());
  assert(lv_obj_get_width(rowLineTop) == 711 && lv_obj_get_y(codeCard) == 130);
  paymentStatus = ""; paymentAmount = -1; paymentTest = false; panelTick(); refresh();
  assert(text(instructionLabel) == "Abra o app ChargeGrid e use o código ao lado para iniciar a recarga.");
  state = "stopped"; sessionId = "test-session"; endReason = "requested";
  state = "idle"; sessionId = ""; lastSyncHttpStatus = 401;
  screenshot(argv[1], "panel-key-error");
  assert(std::string(lv_label_get_text(statusLabel)) == "Ponto indisponível");
  assert(std::string(lv_label_get_text(instructionLabel)).find("chave") == std::string::npos);
  panelIntegrationEnabled = false;
  screenshot(argv[1], "panel-setup");
  lv_obj_clear_flag(configScreen, LV_OBJ_FLAG_HIDDEN);
  lv_keyboard_set_textarea(configKeyboard, ssidInput);
  lv_btnmatrix_set_selected_btn(configKeyboard, 1);
  lv_event_send(configKeyboard, LV_EVENT_VALUE_CHANGED, nullptr);
  assert(std::string(lv_textarea_get_text(ssidInput)) == "q");
  lv_btnmatrix_set_selected_btn(configKeyboard, 11);
  lv_event_send(configKeyboard, LV_EVENT_VALUE_CHANGED, nullptr);
  assert(std::string(lv_textarea_get_text(ssidInput)).empty());
  screenshot(argv[1], "panel-maintenance");
  lv_textarea_set_text(ssidInput, "open-network");
  lv_textarea_set_text(passwordInput, "");
  saveConfig(nullptr);
  assert(configSaveRequested && std::string(requestedSsid) == "open-network");
  assert(requestedPassword[0] == '\0');
  configSaveRequested = false;
  lv_textarea_set_text(ssidInput, "");
  saveConfig(nullptr);
  assert(!configSaveRequested);
  closeConfig(nullptr);

  panelIntegrationEnabled = false; panelNetworkConfigured = false; WiFi.connection = 0;
  panelClaimToken = claimToken; panelOwned = false; connectorOwnershipKnown = false;
  state = "idle"; sessionId = ""; hasSynced = false;
  assert(savePanelClaim(claimStorage, claimToken, true, false, false));
  screenshot(argv[1], "panel-factory-qr-offline");
  assert(!lv_obj_has_flag(claimCard, LV_OBJ_FLAG_HIDDEN));
  assert(std::string(lastClaimQr) == std::string("chargegrid://claim?token=") + claimToken);
  lv_event_send(claimNetworkButton, LV_EVENT_CLICKED, nullptr);
  assert(!lv_obj_has_flag(configScreen, LV_OBJ_FLAG_HIDDEN));
  closeConfig(nullptr);

  JsonDocument ownership;
  ownership["connector"]["public_code"] = "CG-FACTORY-01";
  ownership["authorized"]["session"] = nullptr;
  ownership["authorized"]["reservation"] = nullptr;
  ownership["commands"].to<JsonArray>();
  apply(ownership); // Old API: missing owned must not destroy a claim secret.
  assert(panelClaimToken == claimToken && !panelOwned && !connectorOwnershipKnown);
  ownership["connector"]["owned"] = "true";
  apply(ownership); assert(panelClaimToken == claimToken && !panelOwned);
  ownership["connector"]["owned"] = false;
  ownership["connector"]["active"] = false;
  panelIntegrationEnabled = true; panelNetworkConfigured = true; WiFi.connection = WL_CONNECTED;
  hasSynced = true; lastSyncHttpStatus = 200; lastContact = testMillis;
  apply(ownership);
  screenshot(argv[1], "panel-factory-qr-online");
  assert(panelClaimToken == claimToken && !panelOwned && connectorOwnershipKnown);

  version = 0; lastCommand = "";
  auto blockedStart = startResponse();
  blockedStart["connector"]["owned"] = false; blockedStart["connector"]["active"] = false;
  apply(blockedStart);
  assert(state == "idle" && acknowledgements[0]["error"] == "point_unowned");

  ownership["connector"]["owned"] = true;
  apply(ownership);
  assert(panelOwned && panelClaimToken.empty() && claimStorage.owned && claimStorage.token.empty());
  assert(!savePanelClaim(claimStorage, claimToken, true, false, false));
  screenshot(argv[1], "panel-factory-claimed-inactive");
  assert(lv_obj_has_flag(claimCard, LV_OBJ_FLAG_HIDDEN) && lastClaimQr[0] == '\0');
  assert(std::string(lv_label_get_text(statusLabel)) == "Em breve");
  ownership["connector"]["active"] = true;
  apply(ownership);
  screenshot(argv[1], "panel-factory-claimed-active");
  assert(std::string(lv_label_get_text(statusLabel)) == "Pronto para você");
  panelClaimToken = claimToken; // Even a stale RAM copy cannot expose a legacy owner's QR.
  ownership["connector"].remove("owned");
  apply(ownership); screenshot(argv[1], "panel-legacy-owner-no-qr");
  assert(panelOwned && lv_obj_has_flag(claimCard, LV_OBJ_FLAG_HIDDEN));
  JsonDocument factoryReset;
  factoryReset["server_time"] = "2026-09-21T12:00:00Z";
  factoryReset["control_version"] = version + 1;
  factoryReset["connector"]["owned"] = true;
  factoryReset["connector"]["active"] = false;
  factoryReset["authorized"]["reservation"] = nullptr;
  factoryReset["authorized"]["session"] = nullptr;
  auto resetCommand = factoryReset["commands"].to<JsonArray>().add<JsonObject>();
  resetCommand["id"] = "reset-1"; resetCommand["type"] = "FACTORY_RESET";
  resetCommand["version"] = version + 1;
  resetCommand["expires_at"] = "2030-01-01T12:00:00Z";
  state = "idle"; sessionId = ""; reading.connected = false; hasSynced = true;
  assert(apply(factoryReset));
  assert(acknowledgements[0]["status"] == "applied");
  assert(acknowledgements[0]["new_device_key_hash"].as<String>().length() == 64);
  assert(acknowledgements[0]["new_claim_token_hash"].as<String>().length() == 64);
  apply(factoryReset);
  assert(acknowledgements[0]["status"] == "applied");
  state = "reserved";
  resetCommand["id"] = "reset-2"; resetCommand["version"] = version + 1;
  factoryReset["control_version"] = version + 1;
  apply(factoryReset);
  assert(acknowledgements[0]["status"] == "failed");
  assert(acknowledgements[0]["new_device_key_hash"].isNull());
  puts("PASS: open Wi-Fi validation, password removal/persistence and configuration UI");
  puts("PASS: actual controller authorization, replay, watchdog, cost limit, local touch stop, car SoC (simulated rise, phone passthrough, battery_full local stop and API stop), reserved reboot/recovery, countdown, status text and keyboard");
  puts("PASS: 0.7.0 SET_POWER (raise, reduce, replay, 0 W pause, rounding, wrong session, invalid, after stop), START power_limit_w (incl. 0 W), sync capabilities/charger/applied_power_w and legacy body");
  puts("PASS: 0.7.0 overstay (keep connected, disconnect + immediate sync, RELEASE, reboot, factory reset refusal, texts), payment kiosk QR and status, live power texts");
  puts("PASS: factory claim token validation/storage, QR lifecycle, reset command safety and 20 LVGL frames");
}
