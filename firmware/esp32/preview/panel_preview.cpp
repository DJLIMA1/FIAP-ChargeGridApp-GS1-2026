// Host renderer for the totem UI: compiles the real src/panel_ui.cpp against
// LVGL on the desktop and writes one PPM per screen. Never touches hardware.
// Build/run: python3 firmware/esp32/preview/render.py (see README.md).
#include <cstdio>
#include <cstdlib>
#include <string>
#include "runtime.h"
#include "lvgl.h"

unsigned long testMillis = 1000;
Preferences store;
SimulatedSensors sensors;
Reading reading{20, 0, 0, false};
String bootId, sessionId, lastCommand, state = "idle", endReason;
String connectorPublicCode = "CG-01";
String stationPresenceCode = "#F47580";
unsigned long presenceCodeReceivedAt = 1000, presenceCodeTtlMs = 300000;
String panelClaimToken;
bool panelOwned = true, connectorOwnershipKnown = true, connectorActive = true;
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
void requestLocalSafeStop() {}
extern "C" bool lvgl_port_lock(int) { return true; }
extern "C" bool lvgl_port_unlock() { return true; }
bool chargegridPanelHardwareSetup() { return true; }

#include "../src/panel_ui.cpp"

static lv_color_t framebuffer[800 * 480], drawbuf[800 * 48];
static void flush(lv_disp_drv_t* drv, const lv_area_t* area, lv_color_t* colors) {
  for (int y = area->y1; y <= area->y2; ++y)
    for (int x = area->x1; x <= area->x2; ++x) framebuffer[y * 800 + x] = *colors++;
  lv_disp_flush_ready(drv);
}
static void shot(const char* dir, const char* name) {
  panelTick(); refresh(); lv_obj_update_layout(lv_scr_act()); lv_refr_now(nullptr);
  lv_mem_monitor_t mon; lv_mem_monitor(&mon);
  printf("%-22s lv_mem used=%u max=%u of %u bytes\n", name, (unsigned)(mon.total_size - mon.free_size),
         (unsigned)mon.max_used, (unsigned)mon.total_size);
  char path[1024]; snprintf(path, sizeof(path), "%s/%s.ppm", dir, name);
  FILE* out = fopen(path, "wb");
  fprintf(out, "P6\n800 480\n255\n");
  for (auto pixel : framebuffer) {
    lv_color32_t rgb; rgb.full = lv_color_to32(pixel);
    fputc(rgb.ch.red, out); fputc(rgb.ch.green, out); fputc(rgb.ch.blue, out);
  }
  fclose(out);
}
static void online() {
  WiFi.connection = WL_CONNECTED; hasSynced = true; lastSyncHttpStatus = 200;
  lastContact = testMillis; panelOwned = true; connectorActive = true;
  state = "idle"; sessionId = "";
}

int main(int argc, char** argv) {
  const char* dir = argc > 1 ? argv[1] : ".";
  lv_init();
  static lv_disp_draw_buf_t db; lv_disp_draw_buf_init(&db, drawbuf, nullptr, 800 * 48);
  static lv_disp_drv_t dd; lv_disp_drv_init(&dd);
  dd.hor_res = 800; dd.ver_res = 480; dd.flush_cb = flush; dd.draw_buf = &db;
  lv_disp_drv_register(&dd);
  online(); panelSetup();
  // 1. Ponto sem dono: QR de vinculação.
  panelOwned = false; connectorOwnershipKnown = false;
  panelClaimToken = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefg";
  shot(dir, "totem-1-setup");
  // 2. Pronto para uso com código #F.
  panelClaimToken = ""; online();
  shot(dir, "totem-2-ready");
  // 3. Indisponível (sem Wi-Fi).
  WiFi.connection = 0;
  shot(dir, "totem-3-unavailable");
  // 4. Manutenção (conector desativado pelo responsável).
  online(); connectorActive = false;
  shot(dir, "totem-4-maintenance");
  // Extras: reserva, recarga, encerrada, configuração Wi-Fi.
  online(); state = "reserved"; reservationDeadline = time(nullptr) + 8 * 60;
  shot(dir, "totem-5-reserved");
  state = "charging"; sessionId = "s"; reading = {42, 3210, 7200, true}; sessionPricingKnown = true; price = 2;
  shot(dir, "totem-6-charging");
  state = "stopped";
  shot(dir, "totem-7-stopped");
  online();
  lv_obj_clear_flag(configScreen, LV_OBJ_FLAG_HIDDEN);
  lv_keyboard_set_textarea(configKeyboard, ssidInput);
  lv_textarea_set_text(ssidInput, "MinhaRede");
  shot(dir, "totem-8-config");
  return 0;
}
