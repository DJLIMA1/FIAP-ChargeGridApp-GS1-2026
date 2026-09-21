#include "panel_ui.h"

#ifndef CHARGEGRID_PANEL_ENABLED

void panelSetup() {}
void panelTick() {}

#else

#include <Arduino.h>
#include <WiFi.h>
#include <lvgl.h>
#include <time.h>
#include "runtime.h"
#include "lvgl_v8_port.h"
#include "panel_hardware.h"
#include "chargegrid_logo.h"
#include "panel_fonts.h"
#include "panel_network.h"
#include "panel_claim.h"


// O port da placa deve chamar lv_disp_drv_register/lv_indev_drv_register antes
// de panelSetup(). A escolha do port depende do modelo Waveshare 7 ou 7B.
namespace {
const lv_color_t COLOR_BG = LV_COLOR_MAKE(0x13, 0x13, 0x13);
const lv_color_t COLOR_CARD = LV_COLOR_MAKE(0x1F, 0x1F, 0x1F);
const lv_color_t COLOR_CONTROL = LV_COLOR_MAKE(0x34, 0x34, 0x34);
const lv_color_t COLOR_RED = LV_COLOR_MAKE(0xD7, 0x2B, 0x32);
const lv_color_t COLOR_TEXT = LV_COLOR_MAKE(0xF5, 0xF5, 0xF5);
const lv_color_t COLOR_MUTED = LV_COLOR_MAKE(0xAA, 0xAC, 0xAF);
const lv_color_t COLOR_GREEN = LV_COLOR_MAKE(0x54, 0xC6, 0x91);
const lv_color_t COLOR_AMBER = LV_COLOR_MAKE(0xF3, 0xBC, 0x60);

lv_obj_t *statusLabel, *codeLabel, *connectionLabel, *socLabel;
lv_obj_t *energyLabel, *powerLabel, *costLabel, *timeLabel;
lv_obj_t *instructionLabel, *sourceLabel, *stopButton, *footerLabel, *progressBar;
lv_obj_t *configScreen, *configKeyboard, *ssidInput, *passwordInput, *keyInput, *configStatus;
lv_obj_t *claimCard, *claimQr, *claimNetworkButton;
char lastClaimQr[80]{};
unsigned long logoPressedAt = 0, clearArmedAt = 0;
volatile bool configSaveRequested = false, configClearRequested = false;
char requestedSsid[33]{}, requestedPassword[65]{}, requestedKey[193]{};
unsigned long lastRefresh = 0;
bool ready = false;
volatile bool localStopRequested = false;
portMUX_TYPE snapshotMux = portMUX_INITIALIZER_UNLOCKED;
struct PanelSnapshot {
  char status[64], code[64], connection[48], soc[16], energy[24];
  char power[24], cost[24], remaining[32], instruction[128];
  char claimUrl[80];
  bool showClaim;
  bool showStop;
  bool online;
  bool reserved;
  int progress;
} snapshot{};

lv_obj_t* label(lv_obj_t* parent, const char* text, const lv_font_t* font,
                lv_color_t color) {
  lv_obj_t* value = lv_label_create(parent);
  lv_label_set_text(value, text);
  lv_obj_set_style_text_font(value, font, 0);
  lv_obj_set_style_text_color(value, color, 0);
  return value;
}

lv_obj_t* card(lv_obj_t* parent, int x, int y, int width, int height) {
  lv_obj_t* value = lv_obj_create(parent);
  lv_obj_set_pos(value, x, y);
  lv_obj_set_size(value, width, height);
  lv_obj_set_style_bg_color(value, COLOR_CARD, 0);
  lv_obj_set_style_border_width(value, 0, 0);
  lv_obj_set_style_radius(value, 12, 0);
  lv_obj_set_style_pad_all(value, 16, 0);
  lv_obj_clear_flag(value, LV_OBJ_FLAG_SCROLLABLE);
  return value;
}

void stopClicked(lv_event_t*) { localStopRequested = true; }

void inputFocused(lv_event_t* event) {
  lv_keyboard_set_textarea(configKeyboard, static_cast<lv_obj_t*>(lv_event_get_target(event)));
}
void closeConfig(lv_event_t*) {
  lv_textarea_set_text(passwordInput, "");
  lv_textarea_set_text(keyInput, "");
  clearArmedAt = 0;
  lv_obj_add_flag(configScreen, LV_OBJ_FLAG_HIDDEN);
}
void openConfig(lv_event_t*) {
  lv_textarea_set_text(passwordInput, "");
  lv_textarea_set_text(keyInput, "");
  lv_label_set_text(configStatus, "Senha vazia: rede aberta. Chave vazia: manter a atual.");
  lv_obj_clear_flag(configScreen, LV_OBJ_FLAG_HIDDEN);
}
void saveConfig(lv_event_t*) {
  const char* ssid = lv_textarea_get_text(ssidInput);
  const char* password = lv_textarea_get_text(passwordInput);
  const char* key = lv_textarea_get_text(keyInput);
  if (!validPanelNetwork(ssid, password)) {
    lv_label_set_text(configStatus, "Informe o SSID. Para rede aberta, deixe a senha vazia.");
    return;
  }
  taskENTER_CRITICAL(&snapshotMux);
  snprintf(requestedSsid, sizeof(requestedSsid), "%s", ssid);
  snprintf(requestedPassword, sizeof(requestedPassword), "%s", password);
  snprintf(requestedKey, sizeof(requestedKey), "%s", key);
  configSaveRequested = true;
  taskEXIT_CRITICAL(&snapshotMux);
  lv_label_set_text(configStatus, "Salvando e reiniciando para conectar...");
}
void clearConfig(lv_event_t*) {
  if (!clearArmedAt || millis() - clearArmedAt > 5000) {
    clearArmedAt = millis();
    lv_label_set_text(configStatus, "Toque em Limpar novamente para confirmar.");
    return;
  }
  configClearRequested = true;
  lv_label_set_text(configStatus, "Limpando a rede e reiniciando...");
}
void logoEvent(lv_event_t* event) {
  if (lv_event_get_code(event) == LV_EVENT_PRESSED) logoPressedAt = millis();
  if (lv_event_get_code(event) == LV_EVENT_RELEASED && millis() - logoPressedAt >= 5000) {
    openConfig(nullptr);
  }
}

const char* statusTitle() {
  if (state == "charging") return "Recarga em andamento";
  if (panelIntegrationEnabled && WiFi.status() != WL_CONNECTED) return "Wi-Fi desconectado";
  if (panelIntegrationEnabled && WiFi.status() == WL_CONNECTED && (lastSyncHttpStatus == 401 || lastSyncHttpStatus == 403)) return "Revise a chave do ponto";
  if (!hasSynced) return "Conectando ao servidor";
  if (millis() - lastContact >= 45000 && state == "idle") return "Ponto offline";
  if (state == "reserved") return "Reservado para você";
  if (state == "stopped") return "Recarga encerrada";
  if (state == "fault") return "Falha no equipamento";
  if (connectorOwnershipKnown && !panelOwned) return "Vincule este ponto";
  if (!connectorActive) return "Ponto ainda inativo";
  return "Disponível";
}

const char* instruction() {
  if (WiFi.status() != WL_CONNECTED) return "Wi-Fi desconectado. Segure o logo por 5 segundos para configurar.";
  if (lastSyncHttpStatus == 401 || lastSyncHttpStatus == 403) return "Revise a chave individual na configuração de manutenção.";
  if (!hasSynced) return "Wi-Fi conectado. Aguardando autenticação da API.";
  if (WiFi.status() != WL_CONNECTED || !hasSynced || millis() - lastContact >= 45000) return "Offline: reconectando ao servidor. Acompanhe pelo app.";
  if (state == "reserved") return "Tudo pronto. Inicie a recarga simulada pelo app antes do fim da reserva.";
  if (state == "charging") return "Acompanhe a recarga pelo app. Você pode encerrar aqui a qualquer momento.";
  if (state == "stopped") return "Sessão encerrada. Consulte o resumo no app.";
  if (state == "fault") return "Não use o ponto. Procure outro posto no app.";
  if (connectorOwnershipKnown && !panelOwned) return "Vincule o ponto à sua conta de vendedor pelo QR de instalação.";
  if (!connectorActive) return "No app, revise os dados do seu posto e ative este ponto para receber recargas.";
  return "Use o app ChargeGrid para autenticar, reservar e iniciar.";
}

void refresh() {
  PanelSnapshot current;
  taskENTER_CRITICAL(&snapshotMux);
  current = snapshot;
  taskEXIT_CRITICAL(&snapshotMux);
  // LVGL invalidates objects even when a setter receives the same value. On
  // this RGB panel, rewriting the whole UI every 500 ms causes needless flushes.
  auto setTextIfChanged = [](lv_obj_t* target, const char* value) {
    if (std::strcmp(lv_label_get_text(target), value) != 0) lv_label_set_text(target, value);
  };
  auto setHiddenIfChanged = [](lv_obj_t* target, bool hidden) {
    if (lv_obj_has_flag(target, LV_OBJ_FLAG_HIDDEN) == hidden) return;
    if (hidden) lv_obj_add_flag(target, LV_OBJ_FLAG_HIDDEN);
    else lv_obj_clear_flag(target, LV_OBJ_FLAG_HIDDEN);
  };
  static bool painted = false, lastOnline = false, lastStop = false, lastReserved = false;
  setTextIfChanged(statusLabel, current.status);
  setTextIfChanged(codeLabel, current.code);
  setTextIfChanged(connectionLabel, current.connection);
  if (!painted || current.online != lastOnline)
    lv_obj_set_style_text_color(connectionLabel, current.online ? COLOR_GREEN : COLOR_AMBER, 0);
  if (!painted || current.showStop != lastStop || current.reserved != lastReserved)
    lv_obj_set_style_text_color(statusLabel, current.showStop ? COLOR_GREEN : (current.reserved ? COLOR_AMBER : COLOR_TEXT), 0);
  setTextIfChanged(socLabel, current.soc);
  setTextIfChanged(energyLabel, current.energy);
  setTextIfChanged(powerLabel, current.power);
  setTextIfChanged(costLabel, current.cost);
  setTextIfChanged(timeLabel, current.remaining);
  setTextIfChanged(instructionLabel, current.instruction);
  setHiddenIfChanged(stopButton, !current.showStop);
  if (current.progress >= 0 && lv_bar_get_value(progressBar) != current.progress)
    lv_bar_set_value(progressBar, current.progress, LV_ANIM_OFF);
  setHiddenIfChanged(progressBar, current.progress < 0);
  if (current.showClaim) {
    if (std::strcmp(lastClaimQr, current.claimUrl) != 0) {
      if (lv_qrcode_update(claimQr, current.claimUrl, std::strlen(current.claimUrl)) == LV_RES_OK)
        snprintf(lastClaimQr, sizeof(lastClaimQr), "%s", current.claimUrl);
    }
    setHiddenIfChanged(claimCard, false);
  } else {
    setHiddenIfChanged(claimCard, true);
    if (lastClaimQr[0]) {
      // Remove the displayed secret, not just the overlay, after ownership.
      lv_color_t whiteIndex{}; whiteIndex.full = 1;
      lv_canvas_fill_bg(claimQr, whiteIndex, LV_OPA_COVER);
      memset(lastClaimQr, 0, sizeof(lastClaimQr));
    }
  }
  lastOnline = current.online; lastStop = current.showStop;
  lastReserved = current.reserved; painted = true;
}

void uiTask(void*) {
  while (true) {
    if (millis() - lastRefresh >= 500 && lvgl_port_lock(50)) {
      lastRefresh = millis(); refresh(); lvgl_port_unlock();
    }
    vTaskDelay(pdMS_TO_TICKS(50));
  }
}
void showConfigError(const char* message) {
  if (lvgl_port_lock(50)) {
    lv_label_set_text(configStatus, message);
    lvgl_port_unlock();
  }
}
}  // namespace

void panelSetup() {
  if (!chargegridPanelHardwareSetup()) {
    Serial.println("[panel] profile LCD/touch ausente; controlador segue sem UI");
    return;
  }
  lvgl_port_lock(-1);
  lv_obj_t* screen = lv_scr_act();
  lv_obj_set_style_bg_color(screen, COLOR_BG, 0);
  lv_obj_clear_flag(screen, LV_OBJ_FLAG_SCROLLABLE);

  lv_obj_t* brand = label(screen, "ChargeGrid", &chargegrid_montserrat_24, COLOR_TEXT);
  lv_obj_set_pos(brand, 76, 20);
  lv_obj_t* mark = lv_img_create(screen);
  lv_img_set_src(mark, &chargegrid_logo_64x64);
  lv_img_set_pivot(mark, 0, 0);
  lv_img_set_zoom(mark, 160);
  lv_obj_set_pos(mark, 24, 12);
  lv_obj_add_flag(mark, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_add_event_cb(mark, logoEvent, LV_EVENT_ALL, nullptr);

  connectionLabel = label(screen, "● Offline", &chargegrid_montserrat_16, COLOR_MUTED);
  lv_obj_align(connectionLabel, LV_ALIGN_TOP_RIGHT, -24, 24);

  lv_obj_t* mainCard = card(screen, 24, 72, 752, 152);
  statusLabel = label(mainCard, "Disponível", &chargegrid_montserrat_28, COLOR_TEXT);
  codeLabel = label(mainCard, "Posto --", &chargegrid_montserrat_18, COLOR_RED);
  lv_obj_set_pos(codeLabel, 0, 42);
  instructionLabel = label(mainCard, "Use o app ChargeGrid para autenticar, reservar e iniciar.", &chargegrid_montserrat_16, COLOR_MUTED);
  lv_obj_set_pos(instructionLabel, 0, 76);
  lv_label_set_long_mode(instructionLabel, LV_LABEL_LONG_WRAP);
  lv_obj_set_width(instructionLabel, 700);
  progressBar = lv_bar_create(screen);
  lv_obj_set_pos(progressBar, 40, 206); lv_obj_set_size(progressBar, 720, 4);
  lv_bar_set_range(progressBar, 0, 100);
  lv_obj_set_style_bg_color(progressBar, LV_COLOR_MAKE(0x34, 0x34, 0x34), LV_PART_MAIN);
  lv_obj_set_style_bg_color(progressBar, COLOR_RED, LV_PART_INDICATOR);
  lv_obj_add_flag(progressBar, LV_OBJ_FLAG_HIDDEN);

  lv_obj_t* metrics = card(screen, 24, 240, 752, 128);
  const char* names[] = {"Bateria", "Energia", "Potência", "Custo estimado", "Tempo restante"};
  lv_obj_t** values[] = {&socLabel, &energyLabel, &powerLabel, &costLabel, &timeLabel};
  for (int i = 0; i < 5; ++i) {
    const int x = i * 145;
    lv_obj_t* name = label(metrics, names[i], &chargegrid_montserrat_14, COLOR_MUTED);
    lv_obj_set_pos(name, x, 8);
    *values[i] = label(metrics, "--", &chargegrid_montserrat_24, COLOR_TEXT);
    lv_obj_set_pos(*values[i], x, 38);
    lv_obj_set_width(*values[i], 136);
    lv_label_set_long_mode(*values[i], LV_LABEL_LONG_WRAP);
  }
  lv_obj_set_style_text_font(energyLabel, &chargegrid_montserrat_20, 0);
  lv_obj_set_style_text_font(powerLabel, &chargegrid_montserrat_20, 0);
  lv_obj_set_style_text_font(costLabel, &chargegrid_montserrat_20, 0);
  sourceLabel = label(metrics, "Bancada • dados simulados", &chargegrid_montserrat_14, COLOR_MUTED);
  lv_obj_set_pos(sourceLabel, 0, 84);

  stopButton = lv_btn_create(screen);
  lv_obj_set_pos(stopButton, 24, 394); lv_obj_set_size(stopButton, 220, 52);
  lv_obj_set_style_bg_color(stopButton, COLOR_RED, 0);
  lv_obj_set_style_radius(stopButton, 8, 0);
  lv_obj_set_style_shadow_width(stopButton, 0, 0);
  lv_obj_add_event_cb(stopButton, stopClicked, LV_EVENT_CLICKED, nullptr);
  lv_obj_t* stopText = label(stopButton, "Encerrar recarga", &chargegrid_montserrat_18, lv_color_white());
  lv_obj_center(stopText);
  lv_obj_add_flag(stopButton, LV_OBJ_FLAG_HIDDEN);
  footerLabel = label(screen, "Reserve · Inicie · Acompanhe no app", &chargegrid_montserrat_14, COLOR_MUTED);
  lv_obj_align(footerLabel, LV_ALIGN_BOTTOM_RIGHT, -24, -43);

  // Factory onboarding overlays operational metrics but leaves the brand and
  // connection status visible. Only a separate claim token can produce this QR.
  claimCard = card(screen, 24, 72, 752, 384);
  lv_obj_t* claimEyebrow = label(claimCard, "SEU PONTO CHARGEGRID", &chargegrid_montserrat_14, COLOR_RED);
  lv_obj_set_pos(claimEyebrow, 8, 8);
  lv_obj_t* claimTitle = label(claimCard, "Vincule seu ponto", &chargegrid_montserrat_28, COLOR_TEXT);
  lv_obj_set_pos(claimTitle, 8, 40);
  lv_obj_t* claimDescription = label(claimCard, "Uma leitura do QR conecta este ponto\nà sua conta de vendedor.", &chargegrid_montserrat_16, COLOR_MUTED);
  lv_obj_set_pos(claimDescription, 8, 90); lv_obj_set_width(claimDescription, 414);
  lv_obj_t* claimSteps = label(claimCard,
      "1. Abra o app ChargeGrid no celular.\n\n2. Entre na sua conta e leia o QR.\n\n3. Escolha o posto e ative seu ponto.",
      &chargegrid_montserrat_16, COLOR_TEXT);
  lv_obj_set_pos(claimSteps, 8, 156); lv_obj_set_width(claimSteps, 418);
  claimNetworkButton = lv_btn_create(claimCard);
  lv_obj_set_pos(claimNetworkButton, 8, 292); lv_obj_set_size(claimNetworkButton, 244, 48);
  lv_obj_set_style_bg_color(claimNetworkButton, COLOR_CONTROL, 0);
  lv_obj_set_style_radius(claimNetworkButton, 8, 0); lv_obj_set_style_shadow_width(claimNetworkButton, 0, 0);
  lv_obj_add_event_cb(claimNetworkButton, openConfig, LV_EVENT_CLICKED, nullptr);
  lv_obj_t* claimNetworkText = label(claimNetworkButton, "Configurar Wi-Fi", &chargegrid_montserrat_16, COLOR_TEXT);
  lv_obj_center(claimNetworkText);
  lv_obj_t* qrBorder = card(claimCard, 456, 44, 248, 248);
  lv_obj_set_style_bg_color(qrBorder, lv_color_white(), 0);
  lv_obj_set_style_radius(qrBorder, 8, 0);
  claimQr = lv_qrcode_create(qrBorder, 216, lv_color_black(), lv_color_white());
  lv_obj_center(claimQr);
  lv_obj_t* qrCaption = label(claimCard, "QR exclusivo deste ponto", &chargegrid_montserrat_14, COLOR_MUTED);
  lv_obj_set_pos(qrCaption, 456, 310); lv_obj_set_width(qrCaption, 248);
  lv_obj_set_style_text_align(qrCaption, LV_TEXT_ALIGN_CENTER, 0);
  lv_obj_add_flag(claimCard, LV_OBJ_FLAG_HIDDEN);

  configScreen = lv_obj_create(screen);
  lv_obj_set_size(configScreen, 800, 480); lv_obj_set_pos(configScreen, 0, 0);
  lv_obj_set_style_bg_color(configScreen, COLOR_BG, 0); lv_obj_set_style_radius(configScreen, 0, 0);
  lv_obj_set_style_border_width(configScreen, 0, 0); lv_obj_set_style_pad_all(configScreen, 0, 0);
  lv_obj_clear_flag(configScreen, LV_OBJ_FLAG_SCROLLABLE);
  lv_obj_t* configTitle = label(configScreen, "Configurar este ponto", &chargegrid_montserrat_24, COLOR_TEXT);
  lv_obj_set_pos(configTitle, 16, 8);
  const char* fieldNames[] = {"Wi-Fi (SSID)", "Senha (rede aberta: vazia)", "Chave do dispositivo"};
  lv_obj_t** fields[] = {&ssidInput, &passwordInput, &keyInput};
  for (int i = 0; i < 3; ++i) {
    lv_obj_t* fieldName = label(configScreen, fieldNames[i], &chargegrid_montserrat_14, COLOR_MUTED);
    lv_obj_set_pos(fieldName, 16, 58 + i * 58);
    lv_obj_set_width(fieldName, 144);
    lv_label_set_long_mode(fieldName, LV_LABEL_LONG_WRAP);
    *fields[i] = lv_textarea_create(configScreen);
    lv_obj_set_pos(*fields[i], 168, 44 + i * 58); lv_obj_set_size(*fields[i], 432, 48);
    lv_obj_set_style_bg_color(*fields[i], COLOR_CARD, 0);
    lv_obj_set_style_text_color(*fields[i], COLOR_TEXT, 0);
    lv_obj_set_style_border_color(*fields[i], COLOR_MUTED, 0);
    lv_obj_set_style_border_width(*fields[i], 1, 0);
    lv_obj_set_style_radius(*fields[i], 4, 0);
    lv_textarea_set_one_line(*fields[i], true);
    lv_obj_set_style_text_font(*fields[i], &chargegrid_montserrat_16, 0);
    lv_obj_add_event_cb(*fields[i], inputFocused, LV_EVENT_FOCUSED, nullptr);
  }
  lv_textarea_set_password_mode(passwordInput, true);
  lv_textarea_set_password_mode(keyInput, true);
  lv_textarea_set_max_length(ssidInput, 32); lv_textarea_set_max_length(passwordInput, 64); lv_textarea_set_max_length(keyInput, 192);
  configStatus = label(configScreen, "Senha vazia: rede aberta. Chave vazia: manter a atual.", &chargegrid_montserrat_14, COLOR_MUTED);
  lv_obj_set_pos(configStatus, 8, 228); lv_obj_set_width(configStatus, 590);
  lv_label_set_long_mode(configStatus, LV_LABEL_LONG_DOT);
  struct ButtonDef { const char* text; lv_event_cb_t cb; lv_color_t color; } buttons[] = {
    {"Salvar e conectar", saveConfig, COLOR_RED}, {"Limpar rede", clearConfig, COLOR_CONTROL},
    {"Voltar", closeConfig, COLOR_CONTROL}
  };
  for (int i = 0; i < 3; ++i) {
    lv_obj_t* button = lv_btn_create(configScreen);
    lv_obj_set_pos(button, 614, 44 + i * 58); lv_obj_set_size(button, 170, 48);
    lv_obj_set_style_bg_color(button, buttons[i].color, 0);
    lv_obj_set_style_radius(button, 8, 0);
    lv_obj_set_style_shadow_width(button, 0, 0);
    lv_obj_add_event_cb(button, buttons[i].cb, LV_EVENT_CLICKED, nullptr);
    lv_obj_t* text = label(button, buttons[i].text, &chargegrid_montserrat_16, lv_color_white()); lv_obj_center(text);
  }
  configKeyboard = lv_keyboard_create(configScreen);
  lv_obj_set_size(configKeyboard, 800, 220);
  lv_obj_align(configKeyboard, LV_ALIGN_BOTTOM_MID, 0, 0);
  // A fonte nativa inclui os símbolos LVGL de backspace, enter e troca de layout.
  lv_obj_set_style_text_font(configKeyboard, &lv_font_montserrat_14, 0);
  lv_obj_set_style_bg_color(configKeyboard, COLOR_CARD, LV_PART_MAIN);
  lv_obj_set_style_bg_color(configKeyboard, LV_COLOR_MAKE(0x2A, 0x2A, 0x2A), LV_PART_ITEMS);
  lv_obj_set_style_text_color(configKeyboard, COLOR_TEXT, LV_PART_ITEMS);
  lv_obj_add_flag(configScreen, LV_OBJ_FLAG_HIDDEN);
  ready = true;
  panelTick();
  refresh();
  lvgl_port_unlock();
  xTaskCreatePinnedToCore(uiTask, "chargegrid-ui", 6144, nullptr, 1, nullptr, 0);
}

void panelTick() {
  if (!ready) return;
  if (localStopRequested) {
    localStopRequested = false;
    requestLocalSafeStop();
  }
  if (configSaveRequested) {
    char ssid[sizeof(requestedSsid)], password[sizeof(requestedPassword)], key[sizeof(requestedKey)];
    taskENTER_CRITICAL(&snapshotMux);
    snprintf(ssid, sizeof(ssid), "%s", requestedSsid);
    snprintf(password, sizeof(password), "%s", requestedPassword);
    snprintf(key, sizeof(key), "%s", requestedKey);
    configSaveRequested = false;
    taskEXIT_CRITICAL(&snapshotMux);
    if (!savePanelConnection(ssid, password, key)) {
      showConfigError("Não foi possível salvar. Encerre a sessão ou revise os campos.");
    }
  }
  if (configClearRequested) {
    configClearRequested = false;
    if (!clearPanelConnection()) showConfigError("Não foi possível limpar a configuração de rede.");
  }
  // Snapshot produzido na mesma tarefa do controlador: LVGL nunca lê String ou
  // telemetria enquanto apply()/tick() as modificam na outra CPU.
  PanelSnapshot next{};
  next.showClaim = !panelOwned && state == "idle" && !sessionId.length() && validPanelClaimToken(panelClaimToken.c_str());
  if (next.showClaim) snprintf(next.claimUrl, sizeof(next.claimUrl), "chargegrid://claim?token=%s", panelClaimToken.c_str());
  if (!panelIntegrationEnabled) {
    const bool wifiConnected = panelNetworkConfigured && WiFi.status() == WL_CONNECTED;
    snprintf(next.status, sizeof(next.status), "%s", wifiConnected ? "Configure o dispositivo" : "Configure este ponto");
    snprintf(next.code, sizeof(next.code), "Código após conexão");
    snprintf(next.connection, sizeof(next.connection), "%s", wifiConnected ? "● Wi-Fi conectado" :
        (panelNetworkConfigured ? "● Conectando Wi-Fi" : "● Configuração pendente"));
    snprintf(next.soc, sizeof(next.soc), "--");
    snprintf(next.energy, sizeof(next.energy), "--");
    snprintf(next.power, sizeof(next.power), "--");
    snprintf(next.cost, sizeof(next.cost), "--");
    snprintf(next.remaining, sizeof(next.remaining), "--");
    snprintf(next.instruction, sizeof(next.instruction), "%s", wifiConnected ?
        "Wi-Fi conectado. Segure o logo por 5 segundos para informar a chave do dispositivo." :
        "Segure o logo ChargeGrid por 5 segundos para configurar Wi-Fi e dispositivo.");
    next.showStop = false; next.progress = -1;
  } else {
  snprintf(next.status, sizeof(next.status), "%s", statusTitle());
  snprintf(next.code, sizeof(next.code), "Posto %s", connectorPublicCode.c_str());
  const bool authRejected = lastSyncHttpStatus == 401 || lastSyncHttpStatus == 403;
  const bool apiOnline = WiFi.status() == WL_CONNECTED && !authRejected &&
      hasSynced && lastSyncHttpStatus == 200 && millis() - lastContact < 45000;
  next.online = apiOnline;
  next.reserved = state == "reserved";
  const char* connection = apiOnline ? "● Ponto conectado" :
      (WiFi.status() != WL_CONNECTED ? "● Wi-Fi desconectado" :
      (authRejected ? "● Chave inválida" : "● Aguardando API"));
  snprintf(next.connection, sizeof(next.connection), "%s", connection);
  const bool hasValidSessionData = sessionId.length() && hasSynced;
  snprintf(next.soc, sizeof(next.soc), hasValidSessionData ? "%.1f%%" : "--", reading.socPercent);
  if (hasValidSessionData) {
    snprintf(next.energy, sizeof(next.energy), "%.2f kWh", reading.energyWh / 1000.0f);
    snprintf(next.power, sizeof(next.power), "%.1f kW", reading.powerW / 1000.0f);
  } else {
    snprintf(next.energy, sizeof(next.energy), "--");
    snprintf(next.power, sizeof(next.power), "--");
  }
  const float estimatedCost = reading.energyWh / 1000.0f * price * (1.0f - discount / 100.0f);
  snprintf(next.cost, sizeof(next.cost), sessionId.length() && sessionPricingKnown ? "R$ %.2f" : "--", estimatedCost);
  if (state == "charging") {
    const unsigned long elapsedMinutes = (millis() - started) / 60000UL;
    const unsigned long limitMinutes = maxDurationMs / 60000UL;
    snprintf(next.remaining, sizeof(next.remaining), "%lu min", elapsedMinutes < limitMinutes ? limitMinutes - elapsedMinutes : 0UL);
  } else if (state == "reserved" && reservationDeadline > time(nullptr)) {
    snprintf(next.remaining, sizeof(next.remaining), "%ld min", ((long)(reservationDeadline - time(nullptr)) + 59) / 60L);
  } else snprintf(next.remaining, sizeof(next.remaining), "--");
  snprintf(next.instruction, sizeof(next.instruction), "%s", instruction());
  next.showStop = state == "charging";
  next.progress = hasValidSessionData ? constrain((int)reading.socPercent, 0, 100) : -1;
  }
  taskENTER_CRITICAL(&snapshotMux);
  snapshot = next;
  taskEXIT_CRITICAL(&snapshotMux);
}

#endif
