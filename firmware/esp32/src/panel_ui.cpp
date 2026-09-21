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
const lv_color_t COLOR_BG = LV_COLOR_MAKE(0x12, 0x13, 0x14);
const lv_color_t COLOR_CARD = LV_COLOR_MAKE(0x20, 0x22, 0x23);
const lv_color_t COLOR_CONTROL = LV_COLOR_MAKE(0x34, 0x36, 0x37);
const lv_color_t COLOR_RED = LV_COLOR_MAKE(0xD7, 0x2B, 0x32);
const lv_color_t COLOR_RED_DARK = LV_COLOR_MAKE(0xA6, 0x1C, 0x29);
const lv_color_t COLOR_TEXT = LV_COLOR_MAKE(0xF5, 0xF5, 0xF5);
const lv_color_t COLOR_MUTED = LV_COLOR_MAKE(0xAA, 0xAC, 0xAF);
const lv_color_t COLOR_GREEN = LV_COLOR_MAKE(0x54, 0xC6, 0x91);
const lv_color_t COLOR_AMBER = LV_COLOR_MAKE(0xF3, 0xBC, 0x60);

lv_obj_t *statusLabel, *codeLabel, *connectionLabel, *eyebrowLabel;
lv_obj_t *energyLabel, *costLabel, *timeLabel, *sessionTimeLabel;
lv_obj_t *instructionLabel, *stopButton, *heroNoteLabel;
lv_obj_t *codeCaptionLabel, *codeHintLabel;
lv_obj_t *stepsCard, *reservationCard, *sessionCard, *messageCard;
lv_obj_t *messageTitle, *messageDetail;
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
enum class PanelMode : uint8_t { Ready, Reserved, Charging, Message };
struct PanelSnapshot {
  char eyebrow[48], status[64], code[64], connection[48], energy[24];
  char cost[24], remaining[32], instruction[128];
  char heroNote[64], codeCaption[32], codeHint[64];
  char messageTitle[64], messageDetail[128];
  char claimUrl[80];
  PanelMode mode;
  bool showClaim;
  bool showStop;
  bool online;
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
  if (state == "reserved") return "Ponto reservado";
  if (state == "stopped") return "Recarga encerrada";
  if (state == "fault") return "Ponto indisponível";
  if (panelIntegrationEnabled && WiFi.status() != WL_CONNECTED) return "Ponto indisponível";
  if (panelIntegrationEnabled && WiFi.status() == WL_CONNECTED && (lastSyncHttpStatus == 401 || lastSyncHttpStatus == 403)) return "Ponto indisponível";
  if (!hasSynced) return "Só um instante";
  if (millis() - lastContact >= 45000 && state == "idle") return "Ponto indisponível";
  if (connectorOwnershipKnown && !panelOwned) return "Em configuração";
  if (!connectorActive) return "Em breve";
  return "Pronto para você";
}

const char* instruction() {
  if (state == "charging") return "Acompanhe pelo app. Para parar, toque em Encerrar.";
  if (state == "reserved") return WiFi.status() == WL_CONNECTED ?
      "Sua reserva está ativa. Inicie pelo app antes do prazo." :
      "Sua reserva continua ativa. Aguarde a conexão para iniciar.";
  if (state == "stopped") return "Obrigado por usar ChargeGrid. Seu resumo está no app.";
  if (state == "fault") return "Este ponto está indisponível. Encontre outro no app.";
  if (WiFi.status() != WL_CONNECTED) return "Estamos reconectando. Encontre outro ponto pelo app.";
  if (lastSyncHttpStatus == 401 || lastSyncHttpStatus == 403) return "Este ponto precisa de configuração. Procure outro no app.";
  if (!hasSynced) return "Estamos preparando este ponto para você.";
  if (millis() - lastContact >= 45000) return "A conexão caiu. Encontre outro ponto pelo app.";
  if (connectorOwnershipKnown && !panelOwned) return "O responsável está preparando este ponto.";
  if (!connectorActive) return "Este ponto ainda não está aberto para recargas.";
  return "Abra o app ChargeGrid e use o código ao lado.";
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
  static bool painted = false, lastOnline = false;
  static PanelMode lastMode = PanelMode::Message;
  setTextIfChanged(eyebrowLabel, current.eyebrow);
  setTextIfChanged(statusLabel, current.status);
  setTextIfChanged(codeLabel, current.code);
  setTextIfChanged(codeCaptionLabel, current.codeCaption);
  setTextIfChanged(codeHintLabel, current.codeHint);
  setTextIfChanged(connectionLabel, current.connection);
  if (!painted || current.online != lastOnline)
    lv_obj_set_style_text_color(connectionLabel, current.online ? COLOR_GREEN : COLOR_AMBER, 0);
  if (!painted || current.mode != lastMode) {
    lv_obj_set_style_text_color(eyebrowLabel,
        current.mode == PanelMode::Reserved ? COLOR_AMBER :
        current.mode == PanelMode::Charging ? COLOR_GREEN : COLOR_RED, 0);
  }
  setTextIfChanged(energyLabel, current.energy);
  setTextIfChanged(costLabel, current.cost);
  setTextIfChanged(timeLabel, current.remaining);
  setTextIfChanged(sessionTimeLabel, current.remaining);
  setTextIfChanged(instructionLabel, current.instruction);
  setTextIfChanged(heroNoteLabel, current.heroNote);
  setTextIfChanged(messageTitle, current.messageTitle);
  setTextIfChanged(messageDetail, current.messageDetail);
  setHiddenIfChanged(stepsCard, current.mode != PanelMode::Ready);
  setHiddenIfChanged(reservationCard, current.mode != PanelMode::Reserved);
  setHiddenIfChanged(sessionCard, current.mode != PanelMode::Charging);
  setHiddenIfChanged(messageCard, current.mode != PanelMode::Message);
  setHiddenIfChanged(stopButton, !current.showStop);
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
  lastOnline = current.online; lastMode = current.mode; painted = true;
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
  lv_obj_set_pos(brand, 84, 21);
  lv_obj_t* mark = lv_img_create(screen);
  lv_img_set_src(mark, &chargegrid_logo_64x64);
  lv_img_set_pivot(mark, 0, 0);
  lv_img_set_zoom(mark, 160);
  lv_obj_set_pos(mark, 28, 14);
  lv_obj_add_flag(mark, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_add_event_cb(mark, logoEvent, LV_EVENT_ALL, nullptr);

  lv_obj_t* connectionPill = card(screen, 566, 16, 210, 44);
  lv_obj_set_style_bg_color(connectionPill, COLOR_CARD, 0);
  lv_obj_set_style_radius(connectionPill, 22, 0);
  lv_obj_set_style_pad_all(connectionPill, 0, 0);
  connectionLabel = label(connectionPill, "● Preparando", &chargegrid_montserrat_14, COLOR_AMBER);
  lv_obj_center(connectionLabel);

  lv_obj_t* hero = card(screen, 24, 78, 752, 256);
  lv_obj_set_style_bg_grad_color(hero, LV_COLOR_MAKE(0x28, 0x23, 0x25), 0);
  lv_obj_set_style_bg_grad_dir(hero, LV_GRAD_DIR_HOR, 0);
  lv_obj_t* accent = lv_obj_create(hero);
  lv_obj_set_pos(accent, 4, 22); lv_obj_set_size(accent, 5, 176);
  lv_obj_set_style_bg_color(accent, COLOR_RED, 0);
  lv_obj_set_style_border_width(accent, 0, 0);
  lv_obj_set_style_radius(accent, 3, 0);
  eyebrowLabel = label(hero, "PONTO DISPONÍVEL", &chargegrid_montserrat_14, COLOR_RED);
  lv_obj_set_pos(eyebrowLabel, 28, 26);
  statusLabel = label(hero, "Pronto para você", &chargegrid_montserrat_28, COLOR_TEXT);
  lv_obj_set_pos(statusLabel, 28, 66); lv_obj_set_width(statusLabel, 432);
  lv_label_set_long_mode(statusLabel, LV_LABEL_LONG_DOT);
  instructionLabel = label(hero, "Abra o app ChargeGrid e use o código ao lado.", &chargegrid_montserrat_18, COLOR_TEXT);
  lv_obj_set_pos(instructionLabel, 28, 117);
  lv_label_set_long_mode(instructionLabel, LV_LABEL_LONG_WRAP);
  lv_obj_set_width(instructionLabel, 414);
  heroNoteLabel = label(hero, "Simples, seguro e no seu ritmo.", &chargegrid_montserrat_14, COLOR_MUTED);
  lv_obj_set_pos(heroNoteLabel, 28, 204);

  lv_obj_t* codeCard = card(hero, 488, 14, 224, 196);
  lv_obj_set_style_bg_color(codeCard, COLOR_RED, 0);
  lv_obj_set_style_bg_grad_color(codeCard, COLOR_RED_DARK, 0);
  lv_obj_set_style_bg_grad_dir(codeCard, LV_GRAD_DIR_VER, 0);
  codeCaptionLabel = label(codeCard, "CÓDIGO DO PONTO", &chargegrid_montserrat_14, COLOR_TEXT);
  lv_obj_set_pos(codeCaptionLabel, 0, 10);
  codeLabel = label(codeCard, "--", &chargegrid_montserrat_20, lv_color_white());
  lv_obj_set_pos(codeLabel, 0, 58); lv_obj_set_width(codeLabel, 192);
  lv_label_set_long_mode(codeLabel, LV_LABEL_LONG_DOT);
  codeHintLabel = label(codeCard, "Use no app ChargeGrid", &chargegrid_montserrat_14, COLOR_TEXT);
  lv_obj_set_pos(codeHintLabel, 0, 133);

  stepsCard = card(screen, 24, 350, 752, 94);
  const char* stepTitles[] = {"Abra o app", "Use o código", "Comece a recarga"};
  const char* stepDetails[] = {"ChargeGrid no celular", "Encontre este ponto", "Confirme pelo app"};
  for (int i = 0; i < 3; ++i) {
    const int x = 6 + i * 238;
    lv_obj_t* number = lv_obj_create(stepsCard);
    lv_obj_set_pos(number, x, 12); lv_obj_set_size(number, 38, 38);
    lv_obj_set_style_bg_color(number, LV_COLOR_MAKE(0x3D, 0x25, 0x29), 0);
    lv_obj_set_style_border_width(number, 0, 0);
    lv_obj_set_style_radius(number, 19, 0);
    lv_obj_set_style_pad_all(number, 0, 0);
    char digit[2] = {static_cast<char>('1' + i), '\0'};
    lv_obj_t* numberText = label(number, digit, &chargegrid_montserrat_18, COLOR_RED);
    lv_obj_center(numberText);
    lv_obj_t* stepTitle = label(stepsCard, stepTitles[i], &chargegrid_montserrat_16, COLOR_TEXT);
    lv_obj_set_pos(stepTitle, x + 50, 7);
    lv_obj_t* stepDetail = label(stepsCard, stepDetails[i], &chargegrid_montserrat_14, COLOR_MUTED);
    lv_obj_set_pos(stepDetail, x + 50, 35);
  }

  reservationCard = card(screen, 24, 350, 752, 94);
  lv_obj_t* reservationCaption = label(reservationCard, "TEMPO PARA INICIAR", &chargegrid_montserrat_14, COLOR_AMBER);
  lv_obj_set_pos(reservationCaption, 6, 4);
  timeLabel = label(reservationCard, "--", &chargegrid_montserrat_28, COLOR_TEXT);
  lv_obj_set_pos(timeLabel, 6, 30);
  lv_obj_t* reservationHelp = label(reservationCard, "Seu ponto está guardado.\nInicie a recarga no aplicativo.", &chargegrid_montserrat_16, COLOR_TEXT);
  lv_obj_set_pos(reservationHelp, 242, 14);

  sessionCard = card(screen, 24, 350, 752, 94);
  const char* metricNames[] = {"ENERGIA", "VALOR ESTIMADO", "TEMPO RESTANTE"};
  lv_obj_t** metricValues[] = {&energyLabel, &costLabel, &sessionTimeLabel};
  for (int i = 0; i < 3; ++i) {
    const int x = 6 + i * 170;
    lv_obj_t* name = label(sessionCard, metricNames[i], &chargegrid_montserrat_14, COLOR_MUTED);
    lv_obj_set_pos(name, x, 4);
    *metricValues[i] = label(sessionCard, "--", &chargegrid_montserrat_20, COLOR_TEXT);
    lv_obj_set_pos(*metricValues[i], x, 34);
    lv_obj_set_width(*metricValues[i], 160);
    lv_label_set_long_mode(*metricValues[i], LV_LABEL_LONG_DOT);
  }
  stopButton = lv_btn_create(sessionCard);
  lv_obj_set_pos(stopButton, 548, 8); lv_obj_set_size(stopButton, 166, 56);
  lv_obj_set_style_bg_color(stopButton, COLOR_RED, 0);
  lv_obj_set_style_radius(stopButton, 8, 0);
  lv_obj_set_style_shadow_width(stopButton, 0, 0);
  lv_obj_add_event_cb(stopButton, stopClicked, LV_EVENT_CLICKED, nullptr);
  lv_obj_t* stopText = label(stopButton, "Encerrar", &chargegrid_montserrat_18, lv_color_white());
  lv_obj_center(stopText);
  lv_obj_add_flag(stopButton, LV_OBJ_FLAG_HIDDEN);

  messageCard = card(screen, 24, 350, 752, 94);
  messageTitle = label(messageCard, "Precisa de ajuda?", &chargegrid_montserrat_18, COLOR_TEXT);
  lv_obj_set_pos(messageTitle, 6, 3);
  messageDetail = label(messageCard, "Encontre outro ponto pelo app ChargeGrid.", &chargegrid_montserrat_14, COLOR_MUTED);
  lv_obj_set_pos(messageDetail, 6, 35); lv_obj_set_width(messageDetail, 690);
  lv_label_set_long_mode(messageDetail, LV_LABEL_LONG_WRAP);

  // Factory onboarding overlays operational metrics but leaves the brand and
  // connection status visible. Only a separate claim token can produce this QR.
  claimCard = card(screen, 24, 72, 752, 384);
  lv_obj_t* claimAccent = lv_obj_create(claimCard);
  lv_obj_set_pos(claimAccent, 0, 12); lv_obj_set_size(claimAccent, 5, 162);
  lv_obj_set_style_bg_color(claimAccent, COLOR_RED, 0);
  lv_obj_set_style_border_width(claimAccent, 0, 0);
  lv_obj_set_style_radius(claimAccent, 3, 0);
  lv_obj_t* claimEyebrow = label(claimCard, "CONFIGURAÇÃO DO VENDEDOR", &chargegrid_montserrat_14, COLOR_RED);
  lv_obj_set_pos(claimEyebrow, 8, 8);
  lv_obj_t* claimTitle = label(claimCard, "Ative seu ponto", &chargegrid_montserrat_28, COLOR_TEXT);
  lv_obj_set_pos(claimTitle, 8, 40);
  lv_obj_t* claimDescription = label(claimCard, "Este QR conecta o ponto à sua conta\nde vendedor no app ChargeGrid.", &chargegrid_montserrat_16, COLOR_MUTED);
  lv_obj_set_pos(claimDescription, 8, 90); lv_obj_set_width(claimDescription, 414);
  lv_obj_t* claimSteps = label(claimCard,
      "1. Entre como vendedor no app.\n\n2. Escaneie este QR.\n\n3. Defina nome, local e tarifa.",
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
  lv_obj_t* qrCaption = label(claimCard, "QR privado de vinculação", &chargegrid_montserrat_14, COLOR_MUTED);
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
    next.mode = PanelMode::Message;
    snprintf(next.eyebrow, sizeof(next.eyebrow), "NOVO PONTO");
    snprintf(next.status, sizeof(next.status), "Em preparação");
    snprintf(next.code, sizeof(next.code), "EM BREVE");
    snprintf(next.codeCaption, sizeof(next.codeCaption), "SEU PONTO");
    snprintf(next.codeHint, sizeof(next.codeHint), "Ainda não disponível");
    snprintf(next.heroNote, sizeof(next.heroNote), "ChargeGrid estará aqui em breve.");
    snprintf(next.connection, sizeof(next.connection), "%s", wifiConnected ? "● Preparando ponto" : "● Em instalação");
    snprintf(next.energy, sizeof(next.energy), "--");
    snprintf(next.cost, sizeof(next.cost), "--");
    snprintf(next.remaining, sizeof(next.remaining), "--");
    snprintf(next.instruction, sizeof(next.instruction), "Este ponto estará disponível em breve.");
    snprintf(next.messageTitle, sizeof(next.messageTitle), "Instalação do ponto");
    snprintf(next.messageDetail, sizeof(next.messageDetail), "Responsável: segure o logo por 5 segundos para configurar.");
    next.showStop = false;
  } else {
  const bool authRejected = lastSyncHttpStatus == 401 || lastSyncHttpStatus == 403;
  const bool apiOnline = WiFi.status() == WL_CONNECTED && !authRejected &&
      hasSynced && lastSyncHttpStatus == 200 && millis() - lastContact < 45000;
  next.mode = state == "charging" ? PanelMode::Charging :
      state == "reserved" ? PanelMode::Reserved :
      state == "idle" && apiOnline && connectorActive && panelOwned ? PanelMode::Ready : PanelMode::Message;
  next.online = apiOnline && (next.mode != PanelMode::Message || state == "stopped");
  snprintf(next.eyebrow, sizeof(next.eyebrow), "%s",
      next.mode == PanelMode::Charging ? "RECARGA EM ANDAMENTO" :
      next.mode == PanelMode::Reserved ? "RESERVA ATIVA" :
      next.mode == PanelMode::Ready ? "PONTO DISPONÍVEL" : "PONTO CHARGEGRID");
  snprintf(next.status, sizeof(next.status), "%s", statusTitle());
  snprintf(next.code, sizeof(next.code), "%s", connectorPublicCode.c_str());
  snprintf(next.codeCaption, sizeof(next.codeCaption), "CÓDIGO DO PONTO");
  snprintf(next.codeHint, sizeof(next.codeHint), "%s", next.mode == PanelMode::Message ?
      (state == "stopped" ? "Resumo no aplicativo" : "Indisponível agora") : "Use no app ChargeGrid");
  snprintf(next.heroNote, sizeof(next.heroNote), "%s", next.mode == PanelMode::Charging ?
      "Acompanhe tudo pelo aplicativo." : next.mode == PanelMode::Reserved ?
      "Sua reserva está protegida." : next.mode == PanelMode::Ready ?
      "Simples, seguro e no seu ritmo." : "Mais opções disponíveis no app.");
  const char* connection = apiOnline ?
      (state == "charging" ? "● Em uso" : state == "reserved" ? "● Reservado" :
      state == "stopped" ? "● Recarga concluída" : !panelOwned ? "● Aguardando vínculo" :
      !connectorActive ? "● Em preparação" : "● Pronto para uso") :
      "● Temporariamente offline";
  snprintf(next.connection, sizeof(next.connection), "%s", connection);
  const bool hasValidSessionData = sessionId.length() && hasSynced;
  if (hasValidSessionData) {
    snprintf(next.energy, sizeof(next.energy), "%.2f kWh", reading.energyWh / 1000.0f);
  } else {
    snprintf(next.energy, sizeof(next.energy), "--");
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
  snprintf(next.messageTitle, sizeof(next.messageTitle), "%s", state == "stopped" ?
      "Até a próxima" : !connectorActive ? "Em breve por aqui" : "Encontre outro ponto");
  snprintf(next.messageDetail, sizeof(next.messageDetail), "%s", state == "stopped" ?
      "Veja o resumo da sua recarga no app ChargeGrid." : !connectorActive ?
      "Outros pontos disponíveis estão no app ChargeGrid." :
      "Abra o app ChargeGrid para encontrar uma opção próxima.");
  next.showStop = state == "charging";
  }
  taskENTER_CRITICAL(&snapshotMux);
  snapshot = next;
  taskEXIT_CRITICAL(&snapshotMux);
}

#endif
