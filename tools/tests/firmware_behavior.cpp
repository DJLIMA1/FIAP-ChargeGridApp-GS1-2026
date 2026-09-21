// Runs the actual firmware controller and LVGL screen on a host framebuffer.
#include <cassert>
#include <cmath>
#include <cstdio>
#include "runtime.h"
#include "lvgl.h"
#include "panel_claim.h"

struct ClaimStorage {
  bool owned = false, failWrites = false, failRemove = false;
  std::string token;
  bool getBool(const char* name, bool) { assert(std::string(name) == "owned"); return owned; }
  size_t putBool(const char* name, bool value) {
    assert(std::string(name) == "owned");
    if (failWrites) return 0;
    owned = value; return 1;
  }
  bool isKey(const char* name) { assert(std::string(name) == "claim_token"); return !token.empty(); }
  bool remove(const char* name) {
    assert(std::string(name) == "claim_token");
    if (failRemove) return false;
    token.clear(); return true;
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
String panelClaimToken;
bool panelOwned = false, connectorOwnershipKnown = false, connectorActive = true;
uint32_t version = 0, sequence = 0;
unsigned long lastContact = 1000, lastTick = 1000, started = 1000, nextSync = 0, lastSaved = 0;
unsigned long maxDurationMs = 3600000;
float maxCost = -1, price = 1, discount = 0;
time_t reservationDeadline = 0;
JsonDocument acknowledgements;
bool hasSynced = true, sessionPricingKnown = false;
bool panelIntegrationEnabled = true, panelIdentityConfigured = true, panelNetworkConfigured = true;
int lastSyncHttpStatus = 200;
bool savePanelConnection(const char*, const char*, const char*) { return false; }
bool clearPanelConnection() { return false; }
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

  lv_init();
  static lv_disp_draw_buf_t db; lv_disp_draw_buf_init(&db, drawbuf, nullptr, 800 * 48);
  static lv_disp_drv_t dd; lv_disp_drv_init(&dd);
  dd.hor_res = 800; dd.ver_res = 480; dd.flush_cb = flush; dd.draw_buf = &db;
  lv_disp_drv_register(&dd); panelSetup();
  sessionId = ""; state = "idle"; lastContact = testMillis;
  screenshot(argv[1], "panel-idle");
  flushCount = 0;
  panelTick(); refresh(); lv_refr_now(nullptr);
  assert(flushCount == 0); // An unchanged snapshot must not redraw the RGB panel.
  state = "reserved"; reservationDeadline = time(nullptr) + 30;
  screenshot(argv[1], "panel-reserved");
  assert(flushCount > 0); // A real state transition still reaches the display.
  assert(std::string(lv_label_get_text(timeLabel)) == "1 min");
  state = "charging"; sessionId = "test-session"; reading = {42, 3210, 7200, true};
  screenshot(argv[1], "panel-charging");
  assert(!lv_obj_has_flag(stopButton, LV_OBJ_FLAG_HIDDEN));
  lv_event_send(stopButton, LV_EVENT_CLICKED, nullptr); panelTick();
  assert(state == "stopped" && reading.powerW == 0 && endReason == "requested");
  screenshot(argv[1], "panel-stopped");
  state = "idle"; sessionId = ""; lastSyncHttpStatus = 401;
  screenshot(argv[1], "panel-key-error");
  assert(std::string(lv_label_get_text(statusLabel)) == "Revise a chave do ponto");
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
  lv_textarea_set_text(keyInput, "");
  saveConfig(nullptr);
  assert(configSaveRequested && std::string(requestedSsid) == "open-network");
  assert(requestedPassword[0] == '\0' && requestedKey[0] == '\0');
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
  assert(std::string(lv_label_get_text(statusLabel)) == "Ponto ainda inativo");
  ownership["connector"]["active"] = true;
  apply(ownership);
  screenshot(argv[1], "panel-factory-claimed-active");
  assert(std::string(lv_label_get_text(statusLabel)) == "Disponível");
  panelClaimToken = claimToken; // Even a stale RAM copy cannot expose a legacy owner's QR.
  ownership["connector"].remove("owned");
  apply(ownership); screenshot(argv[1], "panel-legacy-owner-no-qr");
  assert(panelOwned && lv_obj_has_flag(claimCard, LV_OBJ_FLAG_HIDDEN));
  puts("PASS: open Wi-Fi validation, password removal/persistence and configuration UI");
  puts("PASS: actual controller authorization, replay, watchdog, cost limit, local touch stop, reserved reboot/recovery, countdown, status text and keyboard");
  puts("PASS: factory claim token validation/storage, QR offline/online, owned deletion, legacy suppression, activation and 12 LVGL frames");
}
