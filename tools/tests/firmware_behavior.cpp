// Runs the actual firmware controller and LVGL screen on a host framebuffer.
#include <cassert>
#include <cmath>
#include <cstdio>
#include <vector>
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
std::string persistedOrder = "<none>";
void kioskPersistOrder(const char* orderId) { persistedOrder = orderId ? orderId : ""; }
extern "C" bool lvgl_port_lock(int) { return true; }
extern "C" bool lvgl_port_unlock() { return true; }
bool chargegridPanelHardwareSetup() { return true; }

#include "../../firmware/esp32/src/sensors.cpp"
#include "../../firmware/esp32/src/charging_controller.cpp"
#include "../../firmware/esp32/src/charger_link.cpp"
#include "../../firmware/esp32/src/extra_chargers.cpp"
#include "fake_charger_client.h"
#include "../../firmware/esp32/src/kiosk_flow.cpp"
#include "../../firmware/esp32/src/panel_ui.cpp"
#include "../../firmware/esp32/src/ui/widgets.cpp"
#include "../../firmware/esp32/src/ui/router.cpp"
#include "../../firmware/esp32/src/ui/view_choose.cpp"
#include "../../firmware/esp32/src/ui/view_login.cpp"
#include "../../firmware/esp32/src/ui/view_amount.cpp"
#include "../../firmware/esp32/src/ui/view_review.cpp"
#include "../../firmware/esp32/src/ui/view_pay.cpp"
#include "../../firmware/esp32/src/ui/view_starting.cpp"
#include "../../firmware/esp32/src/ui/view_live.cpp"
#include "../../firmware/esp32/src/ui/view_confirm_stop.cpp"
#include "../../firmware/esp32/src/ui/view_receipt.cpp"
#include "../../firmware/esp32/src/ui/view_notice.cpp"

static lv_color_t framebuffer[800 * 480], drawbuf[800 * 48], panelIdleFrame[800 * 480];
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

// ---- 0.8.0: totem de autoatendimento (kiosk_flow + router + views reais, LVGL real) ----
static const char* kKioskOrderId = "7d0c9a52-3f1e-4b5a-9a51-2c0d5e8f1a10";
static const char* kKioskSessionId = "58967906-cabe-48d3-ae70-af6859edc100";
static const char* kKioskOrderQr = "https://chargegrid-api-preview-djlima1s-projects.vercel.app/pay/o/7d0c9a52-3f1e-4b5a-9a51-2c0d5e8f1a10?t=QUJDREVGR0hJSktMTU5PUFFSU1RVVldY";
static const char* kKioskReceiptUrl = "https://chargegrid-api-preview-djlima1s-projects.vercel.app/pay/r/7d0c9a52-3f1e-4b5a-9a51-2c0d5e8f1a10?t=QUJDREVGR0hJSktMTU5PUFFSU1RVVldY";

static std::string kioskSyncJson(const char* kioskBlock, const char* order = "null", const char* session = "null") {
  char out[3072];
  snprintf(out, sizeof(out), R"({"server_time":"2026-10-20T12:00:00+00:00","control_version":0,"overstay":null,
    "connector":{"public_code":"CG-01","active":true,"presence_code":"#F12345",
    "presence_expires_at":"2026-10-20T12:05:00+00:00"%s%s},
    "authorized":{"reservation":null,"session":%s},"commands":[],"kiosk_order":%s})",
           kioskBlock[0] ? ",\"kiosk\":" : "", kioskBlock, session, order);
  return out;
}

static void testKioskSyncBlocks() {
  // Leitura aditiva em apply(): ausente, nulo e inválido = totem desligado.
  const char* off[] = {"", "null", R"({"enabled":"yes","method":"simulated"})", R"({"enabled":true,"method":null,"label":null,"reason":"payments_unavailable"})",
                       R"({"enabled":true,"method":"card_terminal"})", "[]"};
  for (const char* block : off) {
    JsonDocument doc; assert(!deserializeJson(doc, kioskSyncJson(block)));
    apply(doc);
    assert(!kioskSync.kiosk.enabled && !kioskSync.order.present && kioskSync.sessionOrigin[0] == '\0');
  }
  JsonDocument doc;
  const std::string order = std::string(R"({"id":")") + kKioskOrderId + R"(","status":"charging","session_id":")" + kKioskSessionId +
      R"J(","payment":{"status":"in_use","label":"Pago (simulado) · em uso","method":"simulated","amount":"50.00","qr_url":null},"receipt":null,"error":null})J";
  const std::string session = std::string(R"({"id":")") + kKioskSessionId + R"(","status":"charging","origin":"kiosk_totem","price_per_kwh":"2.0000"})";
  assert(!deserializeJson(doc, kioskSyncJson(R"({"enabled":true,"method":"simulated","label":"SIMULADO","reason":null})", order.c_str(), session.c_str())));
  apply(doc);
  assert(kioskSync.kiosk.enabled && kioskSync.kiosk.method == kiosk::Method::Simulated && std::string(kioskSync.kiosk.label) == "SIMULADO");
  assert(kioskSync.order.present && std::string(kioskSync.order.status) == "charging" && std::string(kioskSync.sessionOrigin) == "kiosk_totem");
  assert(state == "idle" && sessionId.empty()); // Bloco do totem nunca liga nada: só START liga.
  // Mesma resposta sem os blocos (API antiga): limpa.
  doc.clear(); assert(!deserializeJson(doc, kioskSyncJson(""))); apply(doc);
  assert(!kioskSync.kiosk.present && !kioskSync.order.present);
  puts("PASS: 0.8.0 sync reading of connector.kiosk / kiosk_order / session.origin (absent, null, invalid, valid) in apply()");
}

static lv_obj_t* findButton(lv_obj_t* parent, const char* text) {
  if (!parent) return nullptr;
  for (uint32_t i = 0; i < lv_obj_get_child_cnt(parent); ++i) {
    lv_obj_t* child = lv_obj_get_child(parent, i);
    if (lv_obj_has_flag(child, LV_OBJ_FLAG_HIDDEN)) continue;   // subárvore oculta (ex.: tela de Wi-Fi)
    if (lv_obj_check_type(child, &lv_btn_class) && lv_obj_get_child_cnt(child) &&
        lv_obj_check_type(lv_obj_get_child(child, 0), &lv_label_class) &&
        std::string(lv_label_get_text(lv_obj_get_child(child, 0))) == text && !lv_obj_has_flag(child, LV_OBJ_FLAG_HIDDEN))
      return child;
    if (lv_obj_t* found = findButton(child, text)) return found;
  }
  return nullptr;
}
static bool hasLabel(lv_obj_t* parent, const std::string& text) {
  if (!parent) return false;
  for (uint32_t i = 0; i < lv_obj_get_child_cnt(parent); ++i) {
    lv_obj_t* child = lv_obj_get_child(parent, i);
    if (lv_obj_check_type(child, &lv_label_class) && !lv_obj_has_flag(child, LV_OBJ_FLAG_HIDDEN) &&
        std::string(lv_label_get_text(child)).find(text) != std::string::npos) return true;
    if (hasLabel(child, text)) return true;
  }
  return false;
}
// Cobertura de glifos: todo label visível da tela do totem só usa glifos da fonte dele.
static uint32_t nextCodepoint(const char*& c) {
  const unsigned char* u = reinterpret_cast<const unsigned char*>(c);
  uint32_t cp = *u; int extra = 0;
  if (cp >= 0xF0) { cp &= 0x07; extra = 3; } else if (cp >= 0xE0) { cp &= 0x0F; extra = 2; } else if (cp >= 0xC0) { cp &= 0x1F; extra = 1; }
  ++u;
  for (int i = 0; i < extra; ++i) cp = (cp << 6) | (*u++ & 0x3F);
  c = reinterpret_cast<const char*>(u);
  return cp;
}
static bool fontCovers(const lv_font_t* font, const char* text, uint32_t* missing = nullptr) {
  for (const char* c = text; *c;) {
    const uint32_t cp = nextCodepoint(c);
    if (cp == '\n') continue;
    lv_font_glyph_dsc_t dsc;
    if (!lv_font_get_glyph_dsc(font, &dsc, cp, 0)) { if (missing) *missing = cp; return false; }
  }
  return true;
}
static unsigned glyphChecks = 0;
static void assertGlyphs(lv_obj_t* parent, const char* screen) {
  if (!parent) return;
  for (uint32_t i = 0; i < lv_obj_get_child_cnt(parent); ++i) {
    lv_obj_t* child = lv_obj_get_child(parent, i);
    if (lv_obj_check_type(child, &lv_label_class) && !lv_obj_has_flag(child, LV_OBJ_FLAG_HIDDEN)) {
      uint32_t missing = 0;
      const char* value = lv_label_get_text(child);
      if (!fontCovers(lv_obj_get_style_text_font(child, 0), value, &missing)) {
        fprintf(stderr, "Missing glyph U+%04X in \"%s\" on %s\n", missing, value, screen);
        assert(false);
      }
      ++glyphChecks;
    }
    assertGlyphs(child, screen);
  }
}
struct KioskMem { std::string name; unsigned used; };
static std::vector<KioskMem> kioskMem;
static void kioskShot(const char* directory, const char* name) {
  screenshot(directory, name);
  if (std::strncmp(name, "kiosk-", 6) == 0 && ui::routerRoot()) assertGlyphs(ui::routerRoot(), name);
  lv_mem_monitor_t mon; lv_mem_monitor(&mon);
  kioskMem.push_back({name, static_cast<unsigned>(mon.total_size - mon.free_size)});
}
static kiosk::ApiRequest kioskApi(int status, const std::string& body, kiosk::RequestKind expected) {
  kiosk::ApiRequest request;
  assert(kioskFlow.takeRequest(request) && request.kind == expected);
  kiosk::ApiResult result; result.kind = request.kind; result.seq = request.seq; result.status = status; result.body = body.c_str();
  kioskFlow.apiResult(result);
  panelTick();   // efeitos do fluxo (NVS "kord", parada local) saem no laço, como na placa
  return request;
}
static void kioskTap(const char* text) {
  refresh();
  lv_obj_t* button = findButton(lv_scr_act(), text);
  if (!button) { fprintf(stderr, "Button not found: %s\n", text); assert(false); }
  lv_event_send(button, LV_EVENT_CLICKED, nullptr);
  panelTick(); refresh();
}
static void kioskApply(const std::string& json) {
  JsonDocument doc; assert(!deserializeJson(doc, json)); apply(doc);
  lastContact = testMillis; hasSynced = true; lastSyncHttpStatus = 200;
}

static void runKioskScreens(const char* out) {
  const char* simulatedBlock = R"({"enabled":true,"method":"simulated","label":"SIMULADO","reason":null})";
  const char* stripeBlock = R"({"enabled":true,"method":"stripe","label":"TESTE","reason":null})";
  const std::string offer = R"({"ui_version":2,"enabled":true,"available":true,"reason":null,"open_order_id":null,"method":"simulated","label":"SIMULADO",
    "power_kw":"7.200","speed_prices":{"max":"2.3000","reduced":"1.8400"},"price":{"price_per_kwh":"2.3000","base_price_per_kwh":"2.0000","demand_multiplier":"1.15","reason_label":"Alta demanda"},
    "limits":{"max_total":"200.00","overstay_reserve":"30.00"},
    "modes":{"value":{"shortcuts":["10.00","20.00","40.00","60.00"],"min":"5.00","max":"170.00"},
             "time":{"shortcuts":[15,30,60],"min":5,"max":60},"energy":{"shortcuts":["5.0","10.0","20.0"],"min":"1.0","max":"73.9","decimals":1}},
    "overstay":{"enabled":true,"version":"ov-3","summary":"Após 10 min: R$ 1,00 por minuto, até R$ 30,00"},"start_timeout_seconds":60})";
  const std::string quote = R"({"quote_hash":"0123456789abcdef0123456789abcdef","mode":"value","amount":"20.00","total":"50.00",
    "energy_cap":"20.00","overstay_reserve":"30.00","price_per_kwh":"2.3000","base_price_per_kwh":"2.0000","demand_multiplier":"1.15",
    "demand":{"multiplier":"1.15","reason_label":"Alta demanda"},"estimated_energy_kwh":"8.696","max_duration_minutes":73,
    "overstay":{"enabled":true,"version":"ov-3","summary":"Após 10 min: R$ 1,00 por minuto, até R$ 30,00"},"method":"simulated","label":"SIMULADO"})";
  auto orderJson = [](const char* status, const char* method, const char* payment) {
    return std::string(R"({"id":")") + kKioskOrderId + R"(","status":")" + status + R"(","method":")" + method +
        R"(","expires_in_seconds":300,"qr_url":")" + kKioskOrderQr + R"(","quote":{"total":"50.00"},"payment":)" + payment +
        R"(,"session_id":null,"receipt":null,"receipt_url":")" + kKioskReceiptUrl + R"(","error":null})";
  };
  auto syncOrder = [](const char* status, const char* receipt) {
    return std::string(R"({"id":")") + kKioskOrderId + R"(","status":")" + status + R"(","session_id":")" + kKioskSessionId +
        R"J(","payment":{"status":"in_use","label":"Pago (simulado)","method":"simulated","amount":"50.00","qr_url":null},"receipt":)J" + receipt + "}";
  };
  // As respostas dizem owned=true; os testes de vínculo depois precisam do estado anterior.
  const ClaimStorage savedClaim = claimStorage;
  const bool savedOwned = panelOwned, savedOwnershipKnown = connectorOwnershipKnown;
  const String savedClaimToken = panelClaimToken;
  lv_mem_monitor_t mon; lv_mem_monitor(&mon);
  kioskMem.push_back({"panel-ready (0.7.0 screens)", static_cast<unsigned>(mon.total_size - mon.free_size)});

  // T0: totem ligado no posto -> botão "Iniciar recarga" na tela Pronto.
  kioskApply(kioskSyncJson(simulatedBlock));
  stationPresenceCode = "#F12345"; presenceCodeReceivedAt = testMillis; presenceCodeTtlMs = 300000;
  kioskShot(out, "kiosk-ready");
  assert(kioskFlow.state() == kiosk::State::Idle && kioskFlow.canStart());
  assert(kioskStartButton && !lv_obj_has_flag(kioskStartButton, LV_OBJ_FLAG_HIDDEN));
  assert(std::string(lv_label_get_text(codeCaptionLabel)) == "TEM O APP? CÓDIGO");
  assert(std::string(lv_label_get_text(codeLabel)) == "#F12345" && !lv_obj_has_flag(codeCard, LV_OBJ_FLAG_HIDDEN));
  assertGlyphs(darkRoot, "kiosk-ready");
  lv_event_send(kioskStartButton, LV_EVENT_CLICKED, nullptr); panelTick();
  assert(kioskFlow.state() == kiosk::State::Welcome);
  kioskShot(out, "kiosk-welcome");
  kioskTap("Continuar sem login");
  kioskApi(200, offer, kiosk::RequestKind::Offer);
  kioskShot(out, "kiosk-connector");
  kioskTap("Próximo passo");
  kioskShot(out, "kiosk-choose");
  assert(darkRoot == nullptr && alertRoot == nullptr);   // telas atuais liberadas
  assert(ui::routerScreen() == kiosk::Screen::Choose && hasLabel(ui::routerRoot(), "Defina sua recarga"));
  kioskTap("Por valor");
  kioskShot(out, "kiosk-amount");
  assert(findButton(ui::routerRoot(), "R$ 20,00") && findButton(ui::routerRoot(), "R$ 60,00"));
  kioskTap("Outro valor");
  kioskTap("2"); kioskTap("5");
  kioskShot(out, "kiosk-keypad");
  assert(hasLabel(ui::routerRoot(), "25 R$"));
  lv_obj_t* comma = findButton(ui::routerRoot(), ",");
  assert(comma && lv_obj_has_state(comma, LV_STATE_DISABLED));   // vírgula só em kWh
  kioskTap(LV_SYMBOL_BACKSPACE); assert(hasLabel(ui::routerRoot(), "2 R$"));
  kioskTap("Voltar");
  kioskTap("R$ 20,00");
  kioskShot(out, "kiosk-power");
  kioskTap("Máxima - 7,2 kW - R$ 2,30/kWh");
  kioskApi(200, quote, kiosk::RequestKind::Quote);
  kioskShot(out, "kiosk-payment-method");
  kioskTap("Cartão de crédito / débito");
  kioskShot(out, "kiosk-review");
  assert(hasLabel(ui::routerRoot(), "R$ 2,00 x 1,15 Alta demanda") && hasLabel(ui::routerRoot(), "R$ 50,00"));
  kioskTap("Aceitar e pagar");
  kioskApi(201, orderJson("held", "simulated", "null"), kiosk::RequestKind::CreateOrder);
  assert(persistedOrder == kKioskOrderId);
  kioskShot(out, "kiosk-pay-simulated");
  assert(findButton(ui::routerRoot(), "Já efetuei o pagamento"));
  testMillis += 50000; lastContact = testMillis;
  kioskShot(out, "kiosk-still-there");
  assert(hasLabel(ui::routerRoot(), "Ainda está aí?"));
  kioskTap("Continuar");
  assert(!hasLabel(ui::routerRoot(), "Ainda está aí?"));
  kioskTap("Já efetuei o pagamento");
  kioskApi(200, orderJson("paid", "simulated", R"({"status":"paid","method":"simulated"})"), kiosk::RequestKind::Pay);
  kioskShot(out, "kiosk-starting");
  assert(ui::routerScreen() == kiosk::Screen::Starting);
  // START normal do servidor (o totem nunca liga sozinho).
  JsonDocument start = startResponse();
  start["control_version"] = 1;
  start["authorized"]["session"]["id"] = kKioskSessionId; start["authorized"]["session"]["origin"] = "kiosk_totem";
  start["authorized"]["session"]["max_cost"] = 20.0; start["authorized"]["session"]["price_per_kwh"] = 2.3;
  start["commands"][0]["session_id"] = kKioskSessionId;
  start["connector"]["kiosk"]["enabled"] = true; start["connector"]["kiosk"]["method"] = "simulated"; start["connector"]["kiosk"]["label"] = "SIMULADO";
  start["connector"]["owned"] = true; start["connector"]["active"] = true;
  sessionId = ""; lastCommand = ""; version = 0;
  apply(start); lastContact = testMillis;
  assert(state == "charging" && sessionId == kKioskSessionId);
  testMillis += 600000; lastContact = testMillis; tick();
  sessionAppliedPowerKw = 7.2f; powerReasonShort = "Máx. do carregador";
  kioskShot(out, "kiosk-live");
  assert(ui::routerScreen() == kiosk::Screen::Live && hasLabel(ui::routerRoot(), "kWh") && hasLabel(ui::routerRoot(), "7,2 kW"));
  lv_obj_t* liveRoot = ui::routerRoot();
  kioskTap("Encerrar");
  kioskShot(out, "kiosk-confirm-stop");
  assert(ui::routerRoot() == liveRoot && hasLabel(ui::routerRoot(), "7,2 kW"));
  assert(state == "charging" && ui::routerScreen() == kiosk::Screen::ConfirmStop);
  kioskTap("Sim, encerrar");
  assert(state == "stopped" && endReason == "requested");     // requestLocalSafeStop()
  kioskApply(kioskSyncJson(simulatedBlock, syncOrder("finished", (std::string(R"({"number":"1A2B3C4D","energy_kwh":"1.200","total":"2.76","returned":"47.24","return_kind":"simulated","final":true,"end_reason":"requested","url":")") + kKioskReceiptUrl + "\"}").c_str()).c_str()));
  kioskShot(out, "kiosk-receipt");
  assert(ui::routerScreen() == kiosk::Screen::Receipt && hasLabel(ui::routerRoot(), "1A2B3C4D") && hasLabel(ui::routerRoot(), "Simulado, sem cobrança"));
  reading.connected = true;
  testMillis += 30000; lastContact = testMillis;
  kioskShot(out, "kiosk-receipt-expired-connected");
  assert(kioskFlow.state() == kiosk::State::Receipt && !kioskFlow.view().qr[0]);
  assert(hasLabel(ui::routerRoot(), "1,20 kWh") && hasLabel(ui::routerRoot(), "R$ 2,76"));
  lv_obj_t* disconnect = findButton(ui::routerRoot(), "Desconectar");
  assert(disconnect && lv_obj_is_visible(disconnect));
  lv_obj_t* disconnectLabel = lv_obj_get_child(disconnect, 0);
  assert(lv_obj_get_height(disconnectLabel) <= lv_obj_get_style_text_font(disconnectLabel, 0)->line_height);
  assert(lv_obj_get_width(disconnectLabel) <= lv_obj_get_width(disconnect));
  kioskTap("Concluir");
  assert(persistedOrder.empty() && kioskFlow.state() == kiosk::State::Idle);
  reading.connected = false;
  // De volta às telas atuais (reconstruídas).
  kioskApply(kioskSyncJson(simulatedBlock));
  kioskShot(out, "kiosk-back-to-ready");
  assert(darkRoot && alertRoot && ui::routerScreen() == kiosk::Screen::None && kioskFlow.canStart());

  // Optional account access through the actual LVGL keyboard queue.
  lv_event_send(kioskStartButton, LV_EVENT_CLICKED, nullptr); panelTick(); refresh();
  kioskTap("Entrar na minha conta");
  kioskShot(out, "kiosk-login-email");
  for (const char* c = "marina@example.com"; *c; ++c) { ui::pushKey(*c); panelTick(); }
  kioskTap("Continuar");
  for (const char* c = "Private2!"; *c; ++c) { ui::pushKey(*c); panelTick(); }
  kioskShot(out, "kiosk-login-password");
  assert(!hasLabel(ui::routerRoot(), "Private2!") && hasLabel(ui::routerRoot(), "*********"));
  kioskTap("Entrar");
  kioskApi(200, R"({"access_token":"test-user-jwt"})", kiosk::RequestKind::Login);
  JsonDocument accountOffer; deserializeJson(accountOffer, offer);
  accountOffer["account"]["name"] = "Marina";
  accountOffer["account"]["vehicle"]["name"] = "BYD Dolphin";
  accountOffer["account"]["wallet"]["balance"] = "214.80";
  accountOffer["balance_available"] = true;
  accountOffer["connector_type"] = "Tipo 2"; accountOffer["public_code"] = "CG-01";
  std::string accountBody; serializeJson(accountOffer, accountBody);
  kioskApi(200, accountBody, kiosk::RequestKind::Offer);
  kioskTap("Próximo passo"); kioskShot(out, "kiosk-choose-account");
  kioskTap("Por autonomia"); kioskShot(out, "kiosk-autonomy");
  kioskTap("60 km"); kioskTap("Reduzida - 3,6 kW - R$ 1,84/kWh");
  kioskApi(200, quote, kiosk::RequestKind::Quote);
  kioskShot(out, "kiosk-payment-balance");
  kioskTap("Saldo do app - R$ 214,80");
  kioskShot(out, "kiosk-review-balance");
  ui::pushAction(kiosk::Action::Cancel); panelTick(); refresh();
  assert(!kioskFlow.authToken()[0] && kioskFlow.state() == kiosk::State::Idle);

  // The central's screen can select and stop a child charger while the primary stays untouched.
  FakeChargerClient childClient(&testMillis, 2);
  extra::Slot& child = extra::slots[0];
  child.used = true; child.address = 2; child.state = "idle"; child.lastContact = testMillis;
  child.link.setClient(&childClient);
  charger::LinkConfig childConfig;
  assert(charger::makeConfig("goodwe_hca_g2", "modbus_tcp", 2, nullptr, 502, childConfig));
  child.link.configure(childConfig); child.link.poll(testMillis);
  assert(child.link.online());
  JsonDocument childSync; deserializeJson(childSync, kioskSyncJson(simulatedBlock));
  kiosk::readSync(childSync.as<JsonObjectConst>(), child.kioskSync);
  // Primary session belongs to somebody else; a free child keeps self-service available.
  state = "charging"; sessionId = "primary-session-untouched";
  panelTick(); refresh(); assert(kioskFlow.canStart());
  lv_event_send(kioskStartButton, LV_EVENT_CLICKED, nullptr); panelTick(); refresh();
  kioskTap("Continuar sem login");
  JsonDocument choices; deserializeJson(choices, offer);
  JsonArray connectors = choices["connectors"].to<JsonArray>();
  JsonObject first = connectors.add<JsonObject>(); first["address"] = 0;
  first["label"] = "Tipo 2 / CG-01 (em uso)"; first["available"] = false;
  JsonObject second = connectors.add<JsonObject>(); second["address"] = 2;
  second["label"] = "Tipo 2 / CG-02"; second["available"] = true;
  std::string childOffer; serializeJson(choices, childOffer);
  kioskApi(200, childOffer, kiosk::RequestKind::Offer);
  kioskShot(out, "kiosk-connectors"); kioskTap("Tipo 2 / CG-02");
  kioskApi(200, childOffer, kiosk::RequestKind::Offer);
  assert(kioskFlow.chargerAddress() == 2);
  kioskTap("Por valor"); kioskTap("R$ 20,00"); kioskTap("Máxima - 7,2 kW - R$ 2,30/kWh");
  kioskApi(200, quote, kiosk::RequestKind::Quote); kioskTap("Cartão de crédito / débito");
  kioskTap("Aceitar e pagar");
  kioskApi(201, orderJson("held", "simulated", "null"), kiosk::RequestKind::CreateOrder);
  kioskTap("Já efetuei o pagamento");
  kioskApi(200, orderJson("paid", "simulated", R"({"status":"paid","method":"simulated"})"), kiosk::RequestKind::Pay);
  assert(child.link.start(3600, testMillis, nullptr) == charger::Error::None);
  child.state = "charging"; child.sessionId = kKioskSessionId; child.limitW = 3600;
  child.price = 2; child.maxCost = 20; child.energyWh = 1000; child.started = testMillis;
  deserializeJson(childSync, kioskSyncJson(simulatedBlock, syncOrder("charging", "null").c_str()));
  kiosk::readSync(childSync.as<JsonObjectConst>(), child.kioskSync);
  kioskShot(out, "kiosk-live-extra");
  assert(ui::routerScreen() == kiosk::Screen::Live && hasLabel(ui::routerRoot(), "3,6 kW"));
  kioskTap("Encerrar"); kioskTap("Sim, encerrar");
  assert(child.state == "stopped" && !childClient.device.relayClosed());
  assert(state == "charging" && sessionId == "primary-session-untouched");
  kioskShot(out, "kiosk-receipt-extra");
  kioskTap("Concluir");
  child.link.setClient(nullptr); child = extra::Slot();
  state = "idle"; sessionId = ""; kioskApply(kioskSyncJson(simulatedBlock)); panelTick(); refresh();

  // Stripe: QR do pedido na tela.
  kioskApply(kioskSyncJson(stripeBlock));
  panelTick(); refresh();
  lv_event_send(kioskStartButton, LV_EVENT_CLICKED, nullptr); panelTick();
  kioskTap("Continuar sem login");
  std::string stripeOffer = offer; stripeOffer.replace(stripeOffer.find("\"simulated\",\"label\":\"SIMULADO\""), 30, "\"stripe\",\"label\":\"TESTE\"");
  kioskApi(200, stripeOffer, kiosk::RequestKind::Offer); panelTick(); refresh();
  kioskTap("Próximo passo");
  kioskTap("Por tempo"); kioskTap("30 min");
  kioskTap("Máxima - 7,2 kW - R$ 2,30/kWh");
  std::string stripeQuote = quote; stripeQuote.replace(stripeQuote.find("\"simulated\",\"label\":\"SIMULADO\""), 30, "\"stripe\",\"label\":\"TESTE\"");
  kioskApi(200, stripeQuote, kiosk::RequestKind::Quote); panelTick(); refresh();
  kioskTap("Cartão de crédito / débito");
  kioskTap("Aceitar e pagar");
  kioskApi(201, orderJson("held", "stripe", "null"), kiosk::RequestKind::CreateOrder);
  kioskApi(200, orderJson("awaiting_payment", "stripe", (std::string(R"({"status":"awaiting_payment","method":"stripe","qr_url":")") + kKioskOrderQr + "\"}").c_str()),
           kiosk::RequestKind::Pay);
  kioskShot(out, "kiosk-pay-stripe");
  assert(ui::routerScreen() == kiosk::Screen::Pay && !hasLabel(ui::routerRoot(), "TESTE"));
  kioskTap("Cancelar");
  kioskApi(200, orderJson("canceled", "stripe", "null"), kiosk::RequestKind::Cancel);
  kioskShot(out, "kiosk-notice-canceled");
  assert(ui::routerScreen() == kiosk::Screen::Notice && hasLabel(ui::routerRoot(), "Pedido cancelado"));
  kioskTap("Concluir");

  // TE: o app inicia durante T1.
  kioskApply(kioskSyncJson(simulatedBlock));
  panelTick(); refresh();
  lv_event_send(kioskStartButton, LV_EVENT_CLICKED, nullptr); panelTick();
  kioskTap("Continuar sem login");
  kioskApi(200, offer, kiosk::RequestKind::Offer);
  const std::string appSession = std::string(R"({"id":")") + kKioskSessionId + R"(","status":"starting","origin":"app"})";
  kioskApply(kioskSyncJson(simulatedBlock, "null", appSession.c_str()));
  kioskShot(out, "kiosk-notice-app-started");
  assert(hasLabel(ui::routerRoot(), "Este ponto acabou de ser iniciado pelo app"));
  kioskTap("Concluir");
  // Recarga iniciada pelo app: Encerrar das telas atuais pede confirmação (totem ligado).
  state = "charging"; sessionId = kKioskSessionId; reading = {42, 3210, 7200, true}; started = testMillis;
  panelTick(); refresh();
  assert(darkRoot && !lv_obj_has_flag(stopButton, LV_OBJ_FLAG_HIDDEN));
  lv_event_send(stopButton, LV_EVENT_CLICKED, nullptr); panelTick();
  assert(state == "charging");
  kioskShot(out, "kiosk-confirm-app-stop");
  assert(hasLabel(ui::routerRoot(), "Encerrar a recarga do app?") && hasLabel(ui::routerRoot(), "Esta recarga foi iniciada pelo app"));
  kioskTap("Sim, encerrar");
  assert(state == "stopped");
  state = "idle"; sessionId = ""; endReason = ""; reading = {20, 0, 0, false};
  // Retomada após reboot: "Verificando pagamento".
  kioskFlow.resume(kKioskOrderId, testMillis);
  kioskShot(out, "kiosk-verifying");
  assert(ui::routerScreen() == kiosk::Screen::Verifying);
  kioskApi(404, R"({"error":{"code":"not_found","message":"x"}})", kiosk::RequestKind::GetOrder);
  panelTick(); refresh();

  // Totem desligado de novo (API sem os blocos): telas atuais idênticas às da 0.7.0.
  kioskApply(kioskSyncJson(""));
  stationPresenceCode = "#F12345"; presenceCodeReceivedAt = testMillis; presenceCodeTtlMs = 300000;
  screenshot(out, "panel-idle-after-kiosk");
  assert(kioskFlow.state() == kiosk::State::Off && lv_obj_has_flag(kioskStartButton, LV_OBJ_FLAG_HIDDEN));
  assert(memcmp(panelIdleFrame, framebuffer, sizeof(framebuffer)) == 0);   // pixel a pixel

  // Textos fixos: títulos só com glifos das Bold, corpo nas Medium.
  for (const auto& entry : kiosk::str::kAll) {
    const lv_font_t* fonts[] = {&chargegrid_brand_30, &chargegrid_brand_34, &chargegrid_title_48};
    const lv_font_t* bodies[] = {&chargegrid_body_14, &chargegrid_body_17, &chargegrid_body_19, &chargegrid_body_22};
    if (entry.role == kiosk::str::TITLE) for (auto font : fonts) assert(fontCovers(font, entry.text) && ui::boldCovers(entry.text));
    for (auto font : bodies) assert(fontCovers(font, entry.text));
    ++glyphChecks;
  }
  assert(fontCovers(ui::tokens::symbol(), LV_SYMBOL_BACKSPACE));
  for (const char** map : {ui::view_login::lower, ui::view_login::upper, ui::view_login::symbols})
    for (const char** key = map; **key; ++key) assert(fontCovers(ui::tokens::bodyLarge(), *key));
  assert(!ui::boldCovers("Pico \xE2\x80\x94 2") && !ui::boldCovers("Verificando\xE2\x80\xA6") && !ui::boldCovers("a \xC2\xB7 b"));

  // Memória do pool LVGL (64 KB, host 64 bits: superestima a placa de 32 bits).
  char path[1024]; snprintf(path, sizeof(path), "%s/kiosk-memory.txt", out);
  FILE* report = fopen(path, "wb"); assert(report);
  unsigned kioskPeak = 0;
  for (const auto& item : kioskMem) {
    fprintf(report, "%-34s %6u bytes %5.1f%%\n", item.name.c_str(), item.used, item.used * 100.0 / LV_MEM_SIZE);
    if (item.name.rfind("kiosk-", 0) == 0 && item.name != "kiosk-ready" && item.name != "kiosk-back-to-ready")
      kioskPeak = std::max(kioskPeak, item.used);
  }
  lv_mem_monitor(&mon);
  fprintf(report, "lv_mem max_used (requested bytes, whole run) %6u\n", (unsigned)mon.max_used);
  fclose(report);
  printf("Kiosk screens LVGL pool peak: %u of %u bytes (%.1f%%); 0.7.0 Ready screen: %u bytes\n", kioskPeak, (unsigned)LV_MEM_SIZE,
         kioskPeak * 100.0 / LV_MEM_SIZE, kioskMem.front().used);
  assert(kioskPeak < LV_MEM_SIZE * 8 / 10);   // < 80 % por tela do totem
  claimStorage = savedClaim; panelOwned = savedOwned; connectorOwnershipKnown = savedOwnershipKnown;
  panelClaimToken = savedClaimToken;
  printf("PASS: 0.8.0 totem screens (T0-T8/TE, simulated + Stripe), real router/views, %u label glyph checks, panel restored pixel-identical\n", glyphChecks);
}


// Carregador GoodWe HCA G2 do conector (connector.charger_link) pelo controlador real. Online
// no START: START/SET_POWER/STOP viram escritas Modbus e o ACK só sai depois da releitura;
// perda do carregador para a sessão com segurança. Offline no START: simulação interna da tela
// até o fim da sessão (link "offline"); o carregador que aparece depois vale na próxima recarga.
// API sem charger_link: tudo continua igual (cliente nunca chamado).
static JsonDocument linkedResponse(const char* type, const char* id, uint32_t commandVersion, const char* session,
                                   bool linked = true) {
  JsonDocument doc;
  doc["server_time"] = "2026-09-21T12:00:00Z";
  doc["control_version"] = commandVersion;
  doc["connector"]["public_code"] = "CG-01";
  doc["connector"]["owned"] = true;
  doc["connector"]["active"] = true;
  if (linked) {
    doc["connector"]["charger_link"]["model"] = "goodwe_hca_g2";
    doc["connector"]["charger_link"]["transport"] = "modbus_tcp";
    doc["connector"]["charger_link"]["address"] = 1;
    doc["connector"]["charger_link"]["host"] = "cg-hca-1.local";
  } else doc["connector"]["charger_link"] = nullptr;
  doc["authorized"]["reservation"] = nullptr;
  if (session) {
    doc["authorized"]["session"]["id"] = session;
    doc["authorized"]["session"]["max_duration_minutes"] = 60;
    doc["authorized"]["session"]["price_per_kwh"] = 2;
  } else doc["authorized"]["session"] = nullptr;
  JsonArray commands = doc["commands"].to<JsonArray>();
  if (type) {
    JsonObject command = commands.add<JsonObject>();
    command["id"] = id; command["type"] = type; command["version"] = commandVersion;
    if (session) command["session_id"] = session;
    command["expires_at"] = "2026-09-21T13:00:00Z";
  }
  return doc;
}
static void runChargerLinkScenarios();
static void runLinkTransitionScenarios() {
  FakeChargerClient client(&testMillis);
  chargerLink.setClient(&client);
  auto screen = linkedResponse(nullptr, nullptr, 0, nullptr);
  state = "idle"; sessionId = ""; apply(screen);
  nextSync = testMillis + 5000;
  chargerLinkService();
  assert(chargerLink.online() && nextSync == testMillis && !client.device.relayClosed());
  auto revision = syncRequests.revision();
  nextSync = testMillis + 5000; chargerLinkService();
  assert(syncRequests.revision() == revision && nextSync == testMillis + 5000);
  client.offline = true; testMillis += 1000; chargerLinkService();
  assert(!chargerLink.online() && nextSync == testMillis);
  revision = syncRequests.revision();
  chargerLinkService(); assert(syncRequests.revision() == revision);
  client.offline = false; testMillis += 1000; chargerLinkService();
  assert(chargerLink.online() && nextSync == testMillis && !client.device.relayClosed());
  chargerLink.configure(charger::LinkConfig{}); chargerLink.setClient(nullptr);
  puts("PASS: transições offline/online pedem sync imediato uma vez, sem reboot ou START automático");
}
// Carregadores ADICIONAIS da tela (multi_charger_v1): a resposta do sync da tela lista
// "chargers"; cada um tem sessão própria (sync endereçado), sempre por Modbus, com START estrito.
static JsonDocument extraResponse(uint8_t address, const char* type, const char* id, uint32_t commandVersion,
                                  const char* session) {
  JsonDocument doc = linkedResponse(type, id, commandVersion, session);
  doc["connector"]["public_code"] = "CG-02";
  doc["connector"]["charger_link"]["address"] = address;
  doc["connector"]["charger_link"]["host"] = address == 2 ? "cg-hca-2.local" : "cg-hca-3.local";
  return doc;
}
static void runExtraChargerScenarios() {
  FakeChargerClient two(&testMillis, 2), three(&testMillis, 3);
  extra::setClient(0, &two);
  extra::setClient(1, &three);
  sessionId = ""; lastCommand = ""; version = 0; state = "idle"; endReason = "";
  panelOwned = true; connectorOwnershipKnown = true; connectorActive = true; lastContact = testMillis;
  // A tela recebe a lista de carregadores adicionais no sync dela.
  auto screen = linkedResponse(nullptr, nullptr, 1, nullptr, false);
  JsonArray listed = screen["chargers"].to<JsonArray>();
  for (uint8_t address : {2, 3}) {
    JsonObject item = listed.add<JsonObject>();
    item["address"] = address; item["public_code"] = address == 2 ? "CG-02" : "CG-03";
    item["charger_link"]["model"] = "goodwe_hca_g2"; item["charger_link"]["transport"] = "modbus_tcp";
    item["charger_link"]["address"] = address;
  }
  apply(screen);
  extra::Slot& slot = extra::slots[0];
  assert(slot.used && slot.address == 2 && extra::slots[1].used && extra::slots[1].address == 3);
  assert(std::string(slot.link.config().host) == "cg-hca-2.local" && slot.state == "idle");
  // Corpo endereçado: charger_address, capacidades e o link (ainda sem leitura = offline).
  JsonDocument body; extra::fillBody(slot, body);
  assert(body["charger_address"] == 2 && body["charger"]["address"] == 2 && body["charger"]["link"] == "offline");
  assert(body["capabilities"][1] == "multi_charger_v1" && body["physical_state"] == "idle" && body["session_id"].isNull());
  nextSync = testMillis + 5000;
  testMillis += 1000; extra::service(testMillis);
  assert(nextSync == testMillis && extra::slots[0].syncNow && extra::slots[1].syncNow);
  body.clear(); extra::fillBody(slot, body);
  assert(body["charger"]["link"] == "online" && body["charger"]["model"] == "goodwe_hca_g2");
  // START no carregador 2: ACK só após releitura; o ponto da tela continua livre.
  auto start = extraResponse(2, "START", "x-start-1", 1, "x-session-1");
  start["commands"][0]["parameters"]["power_limit_w"] = 3650;
  assert(extra::apply(slot, start, testMillis));
  assert(slot.acks[0]["status"] == "applied" && slot.state == "charging" && slot.sessionId == "x-session-1");
  assert(two.writes() == "W 10032=0|W 10029=36|W 10060=2" && two.device.relayClosed() && slot.limitW == 3600);
  assert(state == "idle" && sessionId == "" && !three.device.relayClosed());
  for (int i = 0; i < 60; ++i) { testMillis += 1000; slot.lastContact = testMillis; extra::service(testMillis); }
  assert(std::abs(slot.energyWh - 60) < 0.1 && slot.state == "charging");
  body.clear(); extra::fillBody(slot, body);
  assert(body["physical_state"] == "charging" && body["power_w"] == 3600 && body["applied_power_w"] == 3600);
  assert(body["session_id"] == "x-session-1" && body["connected"] == true);
  // SET_POWER 2 kW por releitura; reentrega confirma o valor instalado.
  auto power = extraResponse(2, "SET_POWER", "x-power-1", 2, "x-session-1");
  power["commands"][0]["parameters"]["power_limit_w"] = 2000;
  extra::apply(slot, power, testMillis);
  assert(slot.acks[0]["status"] == "applied" && slot.acks[0]["applied_power_w"] == 2000);
  extra::apply(slot, power, testMillis);
  assert(slot.acks[0]["status"] == "applied" && slot.acks[0]["applied_power_w"] == 2000);
  // Carregador 3 offline: START recusado (charger_offline), sem sessão.
  extra::Slot& other = extra::slots[1];
  three.offline = true;
  auto refused = extraResponse(3, "START", "x-start-3", 1, "x-session-3");
  extra::apply(other, refused, testMillis);
  assert(other.acks[0]["status"] == "failed" && other.acks[0]["error"] == "charger_offline");
  assert(other.state == "idle" && !other.sessionId.length() && three.count("R 10032x1") == charger::kStartAttempts);
  // A lista da tela sem o carregador 2 não o descarta no meio da recarga.
  auto shrink = linkedResponse(nullptr, nullptr, 1, nullptr, false);
  shrink["chargers"].to<JsonArray>();
  apply(shrink);
  assert(slot.used && slot.state == "charging" && !other.used);
  // Carregador 2 some: em 5 s parada segura (device_fault) e sync imediato.
  two.offline = true;
  for (int i = 0; i < 5; ++i) { testMillis += 1000; slot.lastContact = testMillis; extra::service(testMillis); }
  assert(slot.state == "stopped" && slot.endReason == "device_fault" && nextSync == testMillis);
  body.clear(); extra::fillBody(slot, body);
  assert(body["physical_state"] == "stopped" && body["end_reason"] == "device_fault" && body["power_w"] == 0);
  // A API encerra mesmo sem confirmação física: a sessão some, mas o endpoint do STOP fica.
  auto ended = extraResponse(2, nullptr, nullptr, 2, nullptr);
  extra::apply(slot, ended, testMillis);
  assert(slot.state == "idle" && !slot.sessionId.length());
  assert(slot.link.pendingStop() && two.device.relayClosed());
  const charger::LinkConfig pendingEndpoint = slot.link.config();
  const int resetsBefore = two.resets;
  auto prematureStart = extraResponse(2, "START", "x-start-before-stop", 3, "x-session-before-stop");
  two.log.clear();
  extra::apply(slot, prematureStart, testMillis);
  assert(slot.acks[0]["status"] == "failed" &&
         slot.acks[0]["error"] == "previous_session_requires_reconciliation");
  assert(!slot.sessionId.length() && slot.link.pendingStop() && two.log.empty());
  // Nem a lista da tela nem o sync endereçado podem trocar o endpoint pendente.
  JsonDocument changedEndpoint = screen;
  changedEndpoint["chargers"][0]["charger_link"]["host"] = "replacement.local";
  changedEndpoint["chargers"][0]["charger_link"]["port"] = 1502;
  apply(changedEndpoint);
  assert(charger::sameConfig(slot.link.config(), pendingEndpoint) && two.resets == resetsBefore);
  ended["connector"]["charger_link"]["host"] = "replacement.local";
  ended["connector"]["charger_link"]["port"] = 1502;
  extra::apply(slot, ended, testMillis);
  assert(charger::sameConfig(slot.link.config(), pendingEndpoint) && two.resets == resetsBefore);
  // Remover da lista não perde o slot; outro endereço só ocupa um slot diferente.
  apply(shrink);
  assert(slot.used && slot.address == 2 && slot.link.pendingStop());
  apply(screen);
  assert(extra::slots[1].used && extra::slots[1].address == 3 && slot.address == 2);
  testMillis += 1000; extra::service(testMillis);
  assert(slot.used && slot.link.pendingStop() && charger::sameConfig(slot.link.config(), pendingEndpoint));
  // Reconexão: escreve STOP no carregador antigo, mas readback interrompido ainda o retém.
  two.offline = false; two.failReadAt = hca::kStartStop; two.failReads = 1;
  testMillis += 1000; extra::service(testMillis);
  assert(!two.device.relayClosed() && slot.link.pendingStop());
  apply(shrink);
  assert(slot.used && slot.address == 2 && slot.link.pendingStop());
  // Releitura completa confirma 10060 = 1 / potência 0; agora o slot pode ser liberado/reusado.
  testMillis += 1000; extra::service(testMillis);
  assert(!slot.link.pendingStop() && !two.device.relayClosed());
  // As duas origens voltam a aceitar configuração depois de confirmar STOP.
  extra::apply(slot, ended, testMillis);
  assert(std::string(slot.link.config().host) == "replacement.local" && slot.link.config().port == 1502);
  apply(screen);
  assert(charger::sameConfig(slot.link.config(), pendingEndpoint));
  apply(shrink);
  assert(!slot.used);
  // Vigia de 45 s sem a API no carregador adicional.
  apply(screen);
  extra::Slot& again = extra::slots[0];
  two.offline = false; two.log.clear();
  testMillis += 1000; extra::service(testMillis);
  start = extraResponse(2, "START", "x-start-2", 5, "x-session-2");
  extra::apply(again, start, testMillis);
  assert(again.state == "charging");
  for (int i = 0; i < 46; ++i) { testMillis += 1000; extra::service(testMillis); }
  assert(again.state == "stopped" && again.endReason == "communication_lost" && !two.device.relayClosed());
  // Reboot da tela: diário do carregador adicional relatado como device_reboot, nunca retomado.
  extra::slots[0] = extra::Slot(); extra::slots[1] = extra::Slot();
  extra::setClient(0, &two); extra::setClient(1, &three);
  extra::restore(2, "x-session-2", 12.5f, 5, "x-start-2", testMillis);
  assert(extra::slots[0].used && extra::slots[0].state == "stopped" && extra::slots[0].endReason == "device_reboot");
  assert(extra::slots[0].energyWh == 12.5f && extra::slots[0].lastCommand == "x-start-2");
  // API antiga (sem "chargers"): nenhum adicional novo.
  extra::slots[0] = extra::Slot();
  apply(shrink);
  for (const extra::Slot& item : extra::slots) assert(!item.used);
  extra::setClient(0, nullptr); extra::setClient(1, nullptr);
  puts("PASS: carregadores adicionais da tela (lista do sync, corpo endereçado, START estrito por Modbus, energia "
       "pelo 10015, SET_POWER, charger_offline, perda → device_fault, STOP pendente retém endpoint/slot e bloqueia "
       "START até releitura confirmar, reconexão e reuso, vigia de 45 s, reboot → device_reboot)");
}

static void runBlockingSlotClockScenarios() {
  struct SlowClient : FakeChargerClient {
    explicit SlowClient() : FakeChargerClient(&testMillis, 2) { offline = true; }
    bool readHolding(const charger::LinkConfig& config, uint16_t address, uint16_t count,
                     uint16_t* out, uint8_t* exception) override {
      testMillis += 1500;
      return FakeChargerClient::readHolding(config, address, count, out, exception);
    }
  } slow;
  FakeChargerClient active(&testMillis, 3);
  extra::setClient(0, &slow); extra::setClient(1, &active);
  for (int i = 0; i < 2; ++i) {
    auto& slot = extra::slots[i]; slot.used = true; slot.address = i + 2;
    charger::LinkConfig config;
    assert(charger::makeConfig("goodwe_hca_g2", "modbus_tcp", slot.address, nullptr, 502, config));
    slot.link.configure(config);
  }
  auto& charging = extra::slots[1];
  assert(charging.link.start(2000, testMillis, nullptr) == charger::Error::None);
  charging.state = "charging"; charging.sessionId = "clock-session";
  charging.started = charging.lastTick = testMillis;
  charging.lastContact = testMillis - 44000;
  extra::service(testMillis);
  assert(charging.state == "stopped" && charging.endReason == "communication_lost");
  assert(!active.device.relayClosed()); // O slot anterior bloqueou: vigia usa a hora nova.
  for (auto& slot : extra::slots) slot = extra::Slot();
  extra::setClient(0, nullptr); extra::setClient(1, nullptr);
  puts("PASS: bloqueio de outro slot não atrasa o vigia de 45 s nem a parada física");
}

static void runChargerLinkScenarios() {
  FakeChargerClient client(&testMillis);
  chargerLink.setClient(&client);
  auto reset = [] {
    sessionId = ""; lastCommand = ""; version = 0; state = "idle"; endReason = "";
    socSource = ""; socStartPercent = -1; batteryKwh = 0; phoneSocPercent = -1;
    reading = {20, 0, 0, false}; overstayEnabled = false; chargePowerW = kBenchPowerW;
    maxCost = -1; lastContact = testMillis; panelOwned = true; connectorOwnershipKnown = true; connectorActive = true;
  };
  auto service = [](int seconds) {
    for (int i = 0; i < seconds; ++i) { testMillis += 1000; lastContact = testMillis; tick(); chargerLinkService(); }
  };
  reset();
  // Sem charger_link: START igual a antes (bancada interna); o cliente Modbus nunca é chamado.
  auto plain = linkedResponse("START", "plain-start", 1, "plain-session", false);
  plain["commands"][0]["parameters"]["power_limit_w"] = 3650;
  apply(plain);
  assert(!chargerLink.configured() && state == "charging" && chargePowerW == 3600 && client.log.empty());
  JsonDocument body; fillSyncBody(body, true);
  assert(body["charger"]["model"] == "esp32_bench" && body["charger"]["address"].isNull());
  testMillis += 3600; tick();
  assert(std::abs(reading.energyWh - 3.6) < 0.01 && client.log.empty());
  // Mudança de link durante a recarga não vale até ela terminar.
  auto midSession = linkedResponse(nullptr, nullptr, 1, "plain-session");
  apply(midSession);
  assert(!chargerLink.configured() && state == "charging");
  reset();

  // Link: sync com connector.charger_link → START 3,65 kW. Link recém-configurado no mesmo
  // sync: a tela lê o carregador uma vez antes de decidir (online → Modbus).
  auto start = linkedResponse("START", "hca-start-1", 1, "hca-session-1");
  start["commands"][0]["parameters"]["power_limit_w"] = 3650;
  apply(start);
  assert(chargerLink.active() && std::string(chargerLink.config().host) == "cg-hca-1.local");
  assert(acknowledgements[0]["status"] == "applied" && state == "charging" && sessionId == "hca-session-1");
  assert(sessionOnCharger && chargerLink.online());
  assert(client.writes() == "W 10032=0|W 10029=36|W 10060=2" && client.device.relayClosed());
  assert(chargePowerW == 3600 && reading.powerW == 3600);
  body.clear(); fillSyncBody(body, true);
  assert(body["charger"]["model"] == "goodwe_hca_g2" && body["charger"]["transport"] == "modbus_tcp");
  assert(body["charger"]["address"] == 1 && body["charger"]["link"] == "online");
  assert(body["charger"]["min_power_w"] == 1400 && body["charger"]["max_power_w"] == 7000 && body["charger"]["step_w"] == 100);
  assert(body["charger"]["variant"] == "GW7K-HCA-20" && body["applied_power_w"] == 3600 && body["source"] == "simulated");
  // Leitura ~1 s: potência/energia vêm do 10015; o carregador também integra (SIMULADO).
  service(60);
  assert(std::abs(reading.energyWh - 60) < 0.05 && reading.powerW == 3600 && state == "charging");
  assert(client.device.energyWh() == 60 && client.device.relayClosed());
  // SET_POWER 2,0 kW / pausa / teto 7,0 kW, cada um com ACK depois da releitura.
  auto power = linkedResponse("SET_POWER", "hca-power-1", 2, "hca-session-1");
  power["commands"][0]["parameters"]["power_limit_w"] = 2049;
  client.log.clear();
  apply(power);
  assert(acknowledgements[0]["status"] == "applied" && acknowledgements[0]["applied_power_w"] == 2000);
  assert(client.writes() == "W 10029=20|W 10060=2" && chargePowerW == 2000 && reading.powerW == 2000);
  power = linkedResponse("SET_POWER", "hca-power-2", 3, "hca-session-1");
  power["commands"][0]["parameters"]["power_limit_w"] = 900;
  client.log.clear();
  apply(power);
  assert(acknowledgements[0]["status"] == "applied" && acknowledgements[0]["applied_power_w"] == 0);
  assert(client.writes() == "W 10060=1" && !client.device.relayClosed() && state == "charging");
  const float pausedEnergy = reading.energyWh;
  service(10);
  assert(reading.energyWh == pausedEnergy && reading.powerW == 0 && state == "charging");
  power = linkedResponse("SET_POWER", "hca-power-3", 4, "hca-session-1");
  power["commands"][0]["parameters"]["power_limit_w"] = 7200;
  apply(power);
  assert(acknowledgements[0]["applied_power_w"] == 7000 && client.device.relayClosed() && reading.powerW == 7000);
  // Escrita perdida no SET_POWER: ACK failed e o limite anterior continua.
  power = linkedResponse("SET_POWER", "hca-power-4", 5, "hca-session-1");
  power["commands"][0]["parameters"]["power_limit_w"] = 3000;
  client.dropWrites = 1;
  apply(power);
  assert(acknowledgements[0]["status"] == "failed" && acknowledgements[0]["error"] == "charger_readback_mismatch");
  assert(chargePowerW == 7000 && lastCommand == "hca-power-3");
  // Carregador some durante a recarga: em 5 s a tela para (device_fault) e sincroniza já.
  client.offline = true;
  service(4);
  assert(state == "charging");
  body.clear(); fillSyncBody(body, true);
  assert(body["charger"]["link"] == "offline");
  service(1);
  assert(state == "stopped" && endReason == "device_fault" && reading.powerW == 0 && nextSync == testMillis);
  assert(chargerLink.pendingStop());
  // O carregador volta (o watchdog dele já abriu o relé): a parada pendente é enviada.
  client.offline = false;
  client.log.clear();
  service(1);
  assert(client.writes() == "W 10060=1" && !client.device.relayClosed() && chargerLink.online());
  // STOP da API para a sessão já parada localmente: mantém o motivo; carregador já parado.
  auto stopAfterFault = linkedResponse("STOP", "hca-stop-0", 6, "hca-session-1");
  apply(stopAfterFault);
  assert(acknowledgements[0]["status"] == "applied" && endReason == "device_fault");
  reset();

  // Carregador some entre a última leitura (online) e o START: a tela tenta de novo (2ª tentativa
  // com resolução imediata) e, sem resposta, recusa: ACK failed charger_offline, sem sessão local,
  // sem relé interno/simulação (bug do teste real: a tela dava OK sem o carregador).
  client.offline = true;
  assert(chargerLink.online());
  client.log.clear(); client.urgent = 0;
  start = linkedResponse("START", "hca-start-2", 7, "hca-session-2");
  start["commands"][0]["parameters"]["power_limit_w"] = 7200;
  apply(start);
  assert(acknowledgements[0]["status"] == "failed" && acknowledgements[0]["error"] == "charger_offline");
  assert(state == "idle" && sessionId == "" && !sessionOnCharger && reading.powerW == 0);
  // Online na última leitura: a 1ª tentativa usa a conexão atual; a 2ª refaz conexão/resolução.
  assert(client.count("R 10029x1") == charger::kStartAttempts && client.urgent == charger::kStartAttempts - 1);
  assert(lastCommand != "hca-start-2" && !client.device.relayClosed());
  body.clear(); fillSyncBody(body, true);
  assert(body["physical_state"] == "idle" && body["session_id"].isNull() && body["charger"]["link"] == "offline");
  assert(body["charger"]["address"] == 1 && body["power_w"] == 0);
  // A API encerra a sessão (STOP charger_offline): confirmado sem depender do carregador.
  client.log.clear();
  auto stopFailedStart = linkedResponse("STOP", "hca-stop-1", 8, "hca-session-2");
  stopFailedStart["authorized"]["session"] = nullptr;
  stopFailedStart["commands"][0]["parameters"]["reason"] = "charger_offline";
  apply(stopFailedStart);
  assert(acknowledgements[0]["status"] == "applied" && client.writes().empty());
  reset();

  // Já offline há várias leituras (recuo de 5 s): o START ainda tenta agora e recusa.
  service(6);
  assert(!chargerLink.online());
  client.log.clear();
  start = linkedResponse("START", "hca-start-2b", 9, "hca-session-2b");
  start["commands"][0]["parameters"]["power_limit_w"] = 3650;
  apply(start);
  assert(acknowledgements[0]["status"] == "failed" && acknowledgements[0]["error"] == "charger_offline");
  assert(state == "idle" && !sessionOnCharger && client.count("R 10029x1") == charger::kStartAttempts);
  reset();
  // O carregador volta: a leitura periódica o encontra e o sync já o declara online.
  client.offline = false;
  service(5);
  assert(chargerLink.online() && !chargerLink.pendingStop());
  body.clear(); fillSyncBody(body, true);
  assert(body["charger"]["model"] == "goodwe_hca_g2" && body["charger"]["link"] == "online");
  // Primeira tentativa sem resposta (conexão velha/mDNS após reboot), segunda confirma: START ok.
  client.failNext = 1; client.urgent = 0; client.log.clear();
  start = linkedResponse("START", "hca-start-2c", 12, "hca-session-2c");
  start["commands"][0]["parameters"]["power_limit_w"] = 5000;
  apply(start);
  assert(acknowledgements[0]["status"] == "applied" && sessionOnCharger && client.device.relayClosed());
  // 1ª tentativa: leitura perdida → desliga por segurança (10060 = 1); 2ª: liga e confirma.
  assert(client.urgent == 1 && client.writes() == "W 10060=1|W 10029=50|W 10060=2" && chargePowerW == 5000);
  auto stop = linkedResponse("STOP", "hca-stop-1c", 13, "hca-session-2c");
  apply(stop);
  assert(acknowledgements[0]["status"] == "applied" && !client.device.relayClosed());
  reset();
  // Exceção Modbus (endereço errado → 0x0B) não é repetida: recusa na hora com charger_rejected.
  {
    FakeChargerClient wrong(&testMillis, 2);  // carregador responde como unit 2; a tela fala com 1
    chargerLink.setClient(&wrong);
    auto relinked = linkedResponse(nullptr, nullptr, 13, nullptr, false);
    apply(relinked);  // sem link: zera o estado do Link
    start = linkedResponse("START", "hca-start-2d", 14, "hca-session-2d");
    apply(start);
    assert(acknowledgements[0]["status"] == "failed" && acknowledgements[0]["error"] == "charger_rejected");
    assert(wrong.urgent == 1 && wrong.count("R 10032x1") == 1 && state == "idle");
    chargerLink.setClient(&client);
    apply(relinked);
    reset();
  }

  // STOP normal: ACK applied só com 10060 = 1 e 10015 = 0 relidos.
  start = linkedResponse("START", "hca-start-3", 15, "hca-session-3");
  apply(start);
  assert(acknowledgements[0]["status"] == "applied" && client.device.relayClosed());
  service(5);
  client.log.clear();
  stop = linkedResponse("STOP", "hca-stop-2", 16, "hca-session-3");
  apply(stop);
  assert(acknowledgements[0]["status"] == "applied" && state == "stopped" && endReason == "requested");
  assert(client.writes() == "W 10060=1" && !client.device.relayClosed());
  reset();
  // STOP perdido: a sessão termina (stopped) mas sem ACK applied; a parada sai na leitura.
  start = linkedResponse("START", "hca-start-4", 17, "hca-session-4");
  apply(start);
  client.dropWrites = 1;
  stop = linkedResponse("STOP", "hca-stop-3", 18, "hca-session-4");
  apply(stop);
  assert(acknowledgements[0]["status"] == "failed" && acknowledgements[0]["error"] == "charger_readback_mismatch");
  assert(state == "stopped" && client.device.relayClosed());
  service(1);
  assert(!client.device.relayClosed() && !chargerLink.pendingStop());
  reset();
  // Parada local (toque/CG_STOP) também desliga o carregador.
  start = linkedResponse("START", "hca-start-5", 19, "hca-session-5");
  apply(start);
  assert(client.device.relayClosed());
  requestLocalSafeStop();
  assert(state == "stopped" && !client.device.relayClosed());
  reset();
  // Carregador reiniciou no meio da recarga (boot seguro): falha em 3 leituras.
  start = linkedResponse("START", "hca-start-6", 20, "hca-session-6");
  apply(start);
  client.device.boot(testMillis, 70, 0);
  service(3);
  assert(state == "stopped" && endReason == "device_fault");
  reset();

  // API antiga (sem charger_link): volta exatamente ao corpo da bancada.
  auto unlinked = linkedResponse(nullptr, nullptr, 21, nullptr, false);
  apply(unlinked);
  assert(!chargerLink.configured());
  body.clear(); fillSyncBody(body, true);
  assert(body["charger"]["model"] == "esp32_bench" && body["charger"]["transport"] == "simulated");
  assert(body["charger"]["max_power_w"] == 7200 && body["charger"]["link"].isNull() && body["charger"]["address"].isNull());
  chargerLink.setClient(nullptr);
  reset();
  puts("PASS: carregador GoodWe HCA G2 do conector pelo controlador real (START/SET_POWER/STOP com ACK após releitura, "
       "perda → device_fault, STOP pendente, reboot do carregador; offline no START → 2 tentativas e ACK failed "
       "charger_offline sem simulação da tela; 1ª tentativa perdida e 2ª ok → START aplicado; exceção Modbus sem "
       "repetir; carregador que volta → online no sync; sem charger_link = bancada de sempre)");
}

static void runSharedSessionScreens(const char* out) {
  sessionOnCharger = false; overstayEnabled = false; endReason = "";
  sessionId = "app-shared-session"; state = "charging";
  panelOwned = connectorOwnershipKnown = connectorActive = true;
  panelIntegrationEnabled = panelNetworkConfigured = hasSynced = true;
  WiFi.connection = WL_CONNECTED; lastSyncHttpStatus = 200; lastContact = testMillis;
  for (auto& slot : extra::slots) slot = extra::Slot();
  FakeChargerClient client(&testMillis);
  charger::LinkConfig config;
  assert(charger::makeConfig("goodwe_hca_g2", "modbus_tcp", 1, nullptr, 502, config));
  chargerLink.setClient(&client); chargerLink.configure(config); chargerLink.poll(testMillis);
  reading = {41, 2500, 7200, true}; chargePowerW = 7200;
  price = 2.3; discount = 0; maxCost = 20; sessionPricingKnown = true;
  sessionAppliedPowerKw = 7.2; started = testMillis - 1200000UL; maxDurationMs = 1800000;
  socSource = "phone"; phoneSocPercent = 41;
  kioskSync = kiosk::SyncFacts{}; // O app usa a mesma tela mesmo com totem desligado.
  kioskSync.sessionPresent = true; snprintf(kioskSync.sessionOrigin, sizeof(kioskSync.sessionOrigin), "app");
  kioskFlow = kiosk::Flow{}; kioskFlow.followAppSessions();
  kioskShot(out, "kiosk-shared-app-live");
  assert(kioskFlow.state() == kiosk::State::Live && ui::routerScreen() == kiosk::Screen::Live);
  assert(!hasLabel(ui::routerRoot(), "SIMULADO") && hasLabel(ui::routerRoot(), "2,50 kWh"));
  kiosk::KioskView appView = kioskFlow.view();
  kioskFlow = kiosk::Flow{};
  kioskFlow.resume(kKioskOrderId, testMillis);
  snprintf(kioskSync.sessionOrigin, sizeof(kioskSync.sessionOrigin), "kiosk_totem");
  kioskShot(out, "kiosk-shared-totem-live");
  assert(ui::routerScreen() == kiosk::Screen::Live);
  for (int i = 0; i < 4; ++i) {
    assert(std::string(appView.metrics[i].name) == kioskFlow.view().metrics[i].name);
    assert(std::string(appView.metrics[i].value) == kioskFlow.view().metrics[i].value);
  }
  kioskFlow = kiosk::Flow{}; kioskFlow.followAppSessions();
  snprintf(kioskSync.sessionOrigin, sizeof(kioskSync.sessionOrigin), "app");
  panelTick(); refresh();
  ui::pushAction(kiosk::Action::Stop); panelTick(); refresh();
  assert(ui::routerScreen() == kiosk::Screen::ConfirmStop && hasLabel(ui::routerRoot(), "2,50 kWh"));
  ui::pushAction(kiosk::Action::ConfirmYes); panelTick(); panelTick(); refresh();
  assert(state == "stopped" && kioskFlow.state() == kiosk::State::Receipt);
  kioskShot(out, "kiosk-shared-app-receipt");
  assert(hasLabel(ui::routerRoot(), "2,50 kWh") && hasLabel(ui::routerRoot(), "R$ 5,75"));
  assert(hasLabel(ui::routerRoot(), "20 min"));
  sessionId = ""; state = "idle"; reading.connected = false; reading.energyWh = 0; sessionPricingKnown = false;
  kioskSync.sessionPresent = false;
  kioskShot(out, "kiosk-shared-app-receipt-reconciled");
  assert(hasLabel(ui::routerRoot(), "2,50 kWh") && hasLabel(ui::routerRoot(), "R$ 5,75"));
  ui::pushAction(kiosk::Action::Done); panelTick(); refresh();
  client.offline = true; testMillis += 5000; chargerLink.poll(testMillis); lastContact = testMillis;
  kioskShot(out, "kiosk-charger-offline");
  assert(!kioskFlow.canStart() && hasLabel(alertRoot, "Carregador indisponível"));
  assert(std::string(snapshot.connection) == "Central online");
  client.offline = false; testMillis += 5000; chargerLink.poll(testMillis); lastContact = testMillis;
  lastSyncHttpStatus = 503; // Um erro HTTP isolado não derruba 45 s de contato válido.
  panelTick(); refresh(); assert(snapshot.mode == PanelMode::Ready && snapshot.online);
  lastSyncHttpStatus = 200;
  chargerLink.configure(charger::LinkConfig{}); chargerLink.setClient(nullptr);
  puts("PASS: actual LVGL shared app/totem charging and receipt, hidden method badge, final values retained, charger offline vs central online and transient HTTP recovery");
}

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
  assert(syncBody["firmware_version"] == CHARGEGRID_FIRMWARE_VERSION && syncBody["connected"] == false);
  assert(syncBody["capabilities"].size() == 2 && syncBody["capabilities"][0] == "set_power_v1");
  assert(syncBody["capabilities"][1] == "multi_charger_v1");
  assert(syncBody["applied_power_w"] == 0); // Idle: nothing installed.
  assert(syncBody["charger"]["model"] == "esp32_bench" && syncBody["charger"]["transport"] == "simulated");
  assert(syncBody["charger"]["min_power_w"] == 1400 && syncBody["charger"]["max_power_w"] == 7200);
  assert(syncBody["charger"]["step_w"] == 100);
  JsonDocument legacySync; fillSyncBody(legacySync, false); // Older API (extra="forbid").
  assert(legacySync["firmware_version"] == CHARGEGRID_FIRMWARE_VERSION && legacySync["capabilities"].isNull());
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
  assert(!reading.connected && !overstayEnabled && state == "stopped" && endReason == "device_reboot");
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
  testKioskSyncBlocks();
  resetSession(); sessionId = ""; state = "idle";

  // ---- Real API responses (captured from apps/api POST /v1/devices/sync, live power + overstay) ----
  // Timestamps loaded from PostgreSQL carry the session time zone (-03:00 here), with fractions.
  const ClaimStorage savedClaim = claimStorage; // Real responses say owned=true; the claim tests below need the old state.
  const bool savedOwned = panelOwned, savedOwnershipKnown = connectorOwnershipKnown;
  const String savedClaimToken = panelClaimToken;
  assert(parseTime("2026-10-20T04:09:50.703479-03:00") == parseTime("2026-10-20T07:09:50Z"));
  assert(parseTime("2026-10-20T07:09:50+00:00") == parseTime("2026-10-20T07:09:50"));
  assert(parseTime("2026-10-20T04:09:50-0300") == parseTime("2026-10-20T07:09:50.999Z"));
  assert(parseTime("2026-10-20T09:39:50+02:30") == parseTime("2026-10-20T07:09:50Z"));
  assert(parseTime("2026-10-20T07:09:50+7") == 0 && parseTime("garbage") == 0 && parseTime(nullptr) == 0);
  const char* realStart = R"({"server_time":"2026-10-20T07:09:20.765272+00:00","sync_interval_seconds":1,"control_version":1,
    "overstay":null,"connector":{"id":"c","public_code":"CG-A","max_duration_minutes":60,"owned":true,"active":true,
    "presence_code":"#F00975","presence_expires_at":"2026-10-20T07:10:00+00:00","kiosk_url":null,"payment":null},
    "authorized":{"reservation":null,"session":{"id":"58967906-cabe-48d3-ae70-af6859edc100","status":"starting",
    "max_duration_minutes":30,"max_cost":null,"price_per_kwh":"2.0000","discount_percent":0,"soc_percent":null,
    "battery_kwh":null,"soc_source":null,"start_soc_percent":null,"max_power_kw":7.2,"applied_power_kw":null,
    "target_power_kw":7.2,"power_state":"raising","power_reason_short":"Máx. do carregador"}},
    "commands":[{"id":"ade38acd-7f27-4baa-b9eb-2f241a5e1ace","type":"START","version":1,
    "expires_at":"2026-10-20T04:09:50.703479-03:00","reservation_id":null,"session_id":"58967906-cabe-48d3-ae70-af6859edc100",
    "parameters":{"max_cost":null,"overstay":{"amount":"1.00","max_amount":"30.00","grace_minutes":10,"interval_minutes":1},
    "session_id":"58967906-cabe-48d3-ae70-af6859edc100","soc_source":null,"battery_kwh":null,"soc_percent":null,
    "max_power_kw":7.2,"power_limit_w":7200,"price_per_kwh":"2.0000","discount_percent":0,"power_decision_id":1,
    "max_duration_minutes":30}}]})";
  JsonDocument real; assert(!deserializeJson(real, realStart));
  assert(apply(real)); // Before the offset fix the START looked 3 h expired and was silently ignored.
  assert(state == "charging" && sessionId == "58967906-cabe-48d3-ae70-af6859edc100" && reading.connected);
  assert(acknowledgements.size() == 1 && acknowledgements[0]["status"] == "applied");
  assert(overstayEnabled && chargePowerW == 7200 && std::abs(price - 2.0f) < 0.001f && maxCost < 0);
  assert(maxDurationMs == 30UL * 60000UL && sessionAppliedPowerKw < 0 && powerReasonShort.empty()); // Shown from the next sync.
  // Bodies saved next to the frames so they can be checked against the API SyncInput schema.
  auto saveBody = [&](JsonDocument& body, const char* name) {
    body["boot_id"] = "host-boot"; body["sequence"] = 1;
    char path[1024]; snprintf(path, sizeof(path), "%s/sync-body-%s.json", argv[1], name);
    FILE* out = fopen(path, "wb"); assert(out);
    std::string text; serializeJson(body, text); fputs(text.c_str(), out); fclose(out);
  };
  JsonDocument realBody; fillSyncBody(realBody, true);
  assert(realBody["applied_power_w"] == 7200 && realBody["connected"] == true && realBody["physical_state"] == "charging");
  saveBody(realBody, "charging");
  const char* realSetPower = R"({"server_time":"2026-10-20T07:09:21.388969+00:00","sync_interval_seconds":1,"control_version":2,
    "overstay":null,"connector":{"public_code":"CG-A","owned":true,"active":true,"kiosk_url":null,"payment":null},
    "authorized":{"reservation":null,"session":{"id":"58967906-cabe-48d3-ae70-af6859edc100","status":"charging",
    "max_duration_minutes":30,"max_cost":null,"price_per_kwh":"2.0000","discount_percent":0,"max_power_kw":7.2,
    "applied_power_kw":7.2,"target_power_kw":6.0,"power_state":"reducing","power_reason_short":"Loja 12/30 kW · 3 carros"}},
    "commands":[{"id":"a92caeb0-5d34-4bfd-9b6d-191561a7a9aa","type":"SET_POWER","version":2,
    "expires_at":"2026-10-20T04:09:36.384609-03:00","reservation_id":null,"session_id":"58967906-cabe-48d3-ae70-af6859edc100",
    "parameters":{"reason":"site","attempt":1,"direction":"reduce","decision_id":6,"reason_short":"Loja 12/30 kW · 3 carros",
    "power_limit_w":6000,"previous_power_w":7200}}]})";
  real.clear(); assert(!deserializeJson(real, realSetPower));
  assert(apply(real) && chargePowerW == 6000 && version == 2);
  assert(acknowledgements[0]["status"] == "applied" && acknowledgements[0]["applied_power_w"] == 6000);
  realBody.clear(); fillSyncBody(realBody, true); saveBody(realBody, "set-power-ack");
  assert(realBody["acks"][0]["applied_power_w"] == 6000 && realBody["applied_power_w"] == 6000);
  assert(std::abs(sessionAppliedPowerKw - 7.2f) < 0.001f && powerReasonShort == "Loja 12/30 kW · 3 carros"); // ACK not yet seen by the API.
  const char* realStop = R"({"server_time":"2026-10-20T07:09:21.731986+00:00","sync_interval_seconds":1,"control_version":3,
    "overstay":null,"connector":{"public_code":"CG-A","owned":true,"active":true,"kiosk_url":null,"payment":null},
    "authorized":{"reservation":null,"session":{"id":"58967906-cabe-48d3-ae70-af6859edc100","status":"stopping",
    "price_per_kwh":"2.0000","discount_percent":0}},
    "commands":[{"id":"81e6f2b2-a02d-4502-9319-9d1b78335d0e","type":"STOP","version":3,
    "expires_at":"2026-10-20T04:09:51.635131-03:00","reservation_id":null,"session_id":"58967906-cabe-48d3-ae70-af6859edc100",
    "parameters":{}}]})";
  real.clear(); assert(!deserializeJson(real, realStop));
  assert(apply(real) && state == "stopped" && reading.connected && endReason == "requested");
  realBody.clear(); fillSyncBody(realBody, true); // Session closes "completed" with connected=true: overstay opens.
  assert(realBody["connected"] == true && realBody["session_id"] == "58967906-cabe-48d3-ae70-af6859edc100");
  assert(realBody["end_reason"] == "requested" && realBody["applied_power_w"] == 0); saveBody(realBody, "stopped-connected");
  const char* realOverstay = R"({"server_time":"2026-10-20T07:09:21.808023+00:00","sync_interval_seconds":5,"control_version":3,
    "overstay":{"session_id":"58967906-cabe-48d3-ae70-af6859edc100","status":"grace","grace_remaining_seconds":600,
    "fee_due":"0.00","max_fee":"30.00","amount":"1.00","interval_minutes":1},
    "connector":{"public_code":"CG-A","owned":true,"active":true,"kiosk_url":null,"payment":null},
    "authorized":{"reservation":null,"session":null},"commands":[]})";
  real.clear(); assert(!deserializeJson(real, realOverstay));
  apply(real);
  assert(state == "idle" && sessionId.empty() && reading.connected && overstayStatus == "grace");
  assert(overstayGraceSeconds == 600 && overstayFeeDue == 0 && overstayMaxFee == 30 && overstayAmount == 1 &&
         overstayIntervalMinutes == 1);
  realBody.clear(); fillSyncBody(realBody, true); // Idle with the cable: the API keeps counting the overstay.
  assert(realBody["connected"] == true && realBody["session_id"].isNull() && realBody["energy_wh"] == 0);
  saveBody(realBody, "overstay-idle");
  assert(requestLocalDisconnect() && !reading.connected); // The next sync closes it ("disconnected").
  realBody.clear(); fillSyncBody(realBody, true); saveBody(realBody, "unplugged");
  JsonDocument legacyReal; fillSyncBody(legacyReal, false); saveBody(legacyReal, "legacy");
  // Payment kiosk fields exactly as the API sends them (Stripe test mode).
  const char* realKiosk = R"({"server_time":"2026-10-20T07:09:22+00:00","control_version":3,"overstay":null,
    "connector":{"public_code":"CG-01","owned":true,"active":true,"kiosk_url":"https://api.chargegrid.test/pay/k/CG-01?c=62600",
    "payment":{"status":"awaiting_payment","status_label":"Aguardando pagamento","amount":"20.00","environment":"test"}},
    "authorized":{"reservation":null,"session":null},"commands":[]})";
  real.clear(); assert(!deserializeJson(real, realKiosk)); apply(real);
  assert(kioskUrl == "https://api.chargegrid.test/pay/k/CG-01?c=62600" && paymentStatus == "awaiting_payment");
  assert(paymentAmount == 20.0f && paymentTest && overstayStatus.empty());
  // 422 from the real API: only an extra_forbidden on the 0.7.0 fields means "older API".
  assert(syncRejectedExtensions(R"({"error":{"code":"validation_error","message":"Dados inválidos","fields":[{"field":"capabilities","message":"Extra inputs are not permitted"}]}})"));
  assert(syncRejectedExtensions(R"({"error":{"code":"validation_error","fields":[{"field":"charger.step_w","message":"x"}]}})"));
  assert(syncRejectedExtensions(R"({"detail":[{"loc":["body","applied_power_w"],"msg":"Extra inputs are not permitted"}]})"));
  assert(!syncRejectedExtensions(R"({"error":{"code":"validation_error","fields":[{"field":"unknown_extension","message":"Extra inputs are not permitted"}]}})"));
  assert(!syncRejectedExtensions(R"({"error":{"code":"validation_error","fields":[{"field":"chargers","message":"x"}]}})"));
  assert(!syncRejectedExtensions(R"({"error":{"code":"invalid_time","message":"Horário inválido"}})"));
  assert(!syncRejectedExtensions(R"({"error":{"code":"energy_regression","message":"Energia acumulada diminuiu"}})"));
  assert(!syncRejectedExtensions(R"({"error":{"code":"session_required","message":"Medição de recarga exige session_id"}})"));
  assert(!syncRejectedExtensions("") && !syncRejectedExtensions(nullptr) && !syncRejectedExtensions("<html>"));
  resetSession(); sessionId = ""; state = "idle"; kioskUrl = ""; paymentStatus = ""; paymentAmount = -1; paymentTest = false;
  claimStorage = savedClaim; panelOwned = savedOwned; connectorOwnershipKnown = savedOwnershipKnown;
  panelClaimToken = savedClaimToken;

  lv_init();
  static lv_disp_draw_buf_t db; lv_disp_draw_buf_init(&db, drawbuf, nullptr, 800 * 48);
  static lv_disp_drv_t dd; lv_disp_drv_init(&dd);
  dd.hor_res = 800; dd.ver_res = 480; dd.flush_cb = flush; dd.draw_buf = &db;
  lv_disp_drv_register(&dd); panelSetup();
  // Referência do renderer antigo somente para regressão. No firmware de produção,
  // panelSetup habilita o acompanhamento compartilhado incondicionalmente.
  kioskFlow.followAppSessions(false);
  sessionId = ""; state = "idle"; lastContact = testMillis;
  panelOwned = true; connectorOwnershipKnown = true; connectorActive = true;
  connectorPublicCode = "CG-01";
  stationPresenceCode = "#F12345";
  presenceCodeReceivedAt = testMillis;
  presenceCodeTtlMs = 300000;
  screenshot(argv[1], "panel-idle");
  memcpy(panelIdleFrame, framebuffer, sizeof(framebuffer));
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
  assert(lv_obj_is_visible(timeLabel) && lv_obj_is_visible(codeTimerLabel) && lv_obj_is_visible(codeProgressBar));
  assert(hasLabel(reservationCard, "Inicie em"));
  assert(std::string(lv_label_get_text(codeLabel)) == "#F12345");
  assert(std::string(lv_label_get_text(codeCaptionLabel)) == "CÓDIGO DO PONTO");
  assert(std::string(lv_label_get_text(codeTimerLabel)).find("Troca em") == 0);
  presenceCodeTtlMs = 0; panelTick(); refresh();
  assert(std::string(lv_label_get_text(codeLabel)) == "--");
  stationPresenceCode = "#F54321"; presenceCodeTtlMs = 300000; presenceCodeReceivedAt = testMillis;
  panelTick(); refresh();
  assert(std::string(lv_label_get_text(codeLabel)) == "#F54321");
  assert(std::string(lv_label_get_text(codeTimerLabel)) == "Troca em 05:00");
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
  runKioskScreens(argv[1]);
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
  runLinkTransitionScenarios();
  runChargerLinkScenarios();
  runExtraChargerScenarios();
  runBlockingSlotClockScenarios();
  runSharedSessionScreens(argv[1]);
  puts("PASS: open Wi-Fi validation, password removal/persistence and configuration UI");
  puts("PASS: actual controller authorization, replay, watchdog, cost limit, local touch stop, car SoC (simulated rise, phone passthrough, battery_full local stop and API stop), reserved reboot/recovery, countdown, status text and keyboard");
  puts("PASS: 0.7.0 SET_POWER (raise, reduce, replay, 0 W pause, rounding, wrong session, invalid, after stop), START power_limit_w (incl. 0 W), sync capabilities/charger/applied_power_w and legacy body");
  puts("PASS: 0.7.0 overstay (keep connected, disconnect + immediate sync, RELEASE, reboot, factory reset refusal, texts), payment kiosk QR and status, live power texts");
  puts("PASS: real API sync responses (ISO offsets -03:00, Decimal text, START overstay + power_limit_w, SET_POWER ack, STOP keeps the cable, overstay block, kiosk) and 422 classification");
  puts("PASS: factory claim token validation/storage, QR lifecycle, reset command safety and 20 panel LVGL frames");
}
