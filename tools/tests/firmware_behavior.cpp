// Runs the actual firmware controller and LVGL screen on a host framebuffer.
#include <cassert>
#include <cmath>
#include <cstdio>
#include "runtime.h"
#include "lvgl.h"

unsigned long testMillis = 1000;
Preferences store;
SimulatedSensors sensors;
Reading reading{20, 0, 0, false};
String bootId, sessionId, lastCommand, state = "idle", endReason;
String connectorPublicCode = "CG-01";
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
extern "C" bool lvgl_port_lock(int) { return true; }
extern "C" bool lvgl_port_unlock() { return true; }
bool chargegridPanelHardwareSetup() { return true; }

#include "../../firmware/esp32/src/sensors.cpp"
#include "../../firmware/esp32/src/charging_controller.cpp"
#include "../../firmware/esp32/src/panel_ui.cpp"

static lv_color_t framebuffer[800 * 480], drawbuf[800 * 48];
static void flush(lv_disp_drv_t* drv, const lv_area_t* area, lv_color_t* colors) {
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
int main(int argc, char** argv) {
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

  lv_init();
  static lv_disp_draw_buf_t db; lv_disp_draw_buf_init(&db, drawbuf, nullptr, 800 * 48);
  static lv_disp_drv_t dd; lv_disp_drv_init(&dd);
  dd.hor_res = 800; dd.ver_res = 480; dd.flush_cb = flush; dd.draw_buf = &db;
  lv_disp_drv_register(&dd); panelSetup();
  sessionId = ""; state = "idle"; lastContact = testMillis;
  screenshot(argv[1], "panel-idle");
  state = "reserved"; reservationDeadline = time(nullptr) + 30;
  screenshot(argv[1], "panel-reserved");
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
  puts("PASS: actual controller authorization, replay, watchdog, cost limit, local touch stop, reserved countdown, status text, keyboard and 7 LVGL frames");
}
