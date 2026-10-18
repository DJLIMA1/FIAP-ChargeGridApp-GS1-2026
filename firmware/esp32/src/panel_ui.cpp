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
//
// Layout: o design de referência do totem é 2:1; aqui ele é escalado em 0,4
// (800 px de largura) e centralizado verticalmente no painel 800x480 (UI_Y).
namespace {
constexpr int UI_Y = 40;
// Fundo e gradiente usam valores exatos de RGB565 (R/B em múltiplos de 8, G de 4):
// qualquer outro tom "pula" de matiz entre as faixas do degradê no painel de 16 bits.
const lv_color_t COLOR_BG = LV_COLOR_MAKE(0x10, 0x18, 0x20);
const lv_color_t COLOR_BG_TOP = LV_COLOR_MAKE(0x18, 0x1C, 0x20);
const lv_color_t COLOR_CARD = LV_COLOR_MAKE(0x20, 0x24, 0x28);
const lv_color_t COLOR_CONTROL = LV_COLOR_MAKE(0x23, 0x28, 0x30);
const lv_color_t COLOR_LINE = LV_COLOR_MAKE(0x26, 0x2B, 0x31);
const lv_color_t COLOR_RED = LV_COLOR_MAKE(0xD7, 0x2B, 0x32);
const lv_color_t COLOR_TEXT = LV_COLOR_MAKE(0xF5, 0xF5, 0xF5);
const lv_color_t COLOR_SOFT = LV_COLOR_MAKE(0xD6, 0xDA, 0xE0);
const lv_color_t COLOR_MUTED = LV_COLOR_MAKE(0x7A, 0x82, 0x8E);
const lv_color_t COLOR_GREEN = LV_COLOR_MAKE(0x1E, 0xDF, 0x5A);
const lv_color_t COLOR_AMBER = LV_COLOR_MAKE(0xFF, 0xC6, 0x2E);

lv_obj_t *statusLabel, *codeLabel, *connectionLabel, *connectionDot;
lv_obj_t *energyLabel, *costLabel, *timeLabel, *sessionTimeLabel;
lv_obj_t *instructionLabel, *stopButton;
lv_obj_t *codeCaptionLabel, *codeHintLabel;
lv_obj_t *codeTimerLabel, *codeProgressBar, *codeCard;
lv_obj_t *darkRoot, *alertRoot, *leftBlock, *rowLineTop, *rowLineBottom;
lv_obj_t *stepsCard, *reservationCard, *sessionCard, *messageCard;
lv_obj_t *messageTitle, *messageDetail;
lv_obj_t *alertTitle, *alertSub, *alertBrand, *alertLogoPad;
lv_obj_t *pumpBody, *pumpSide, *pumpScreen, *pumpBolt, *pumpNozzle, *pumpHose;
lv_obj_t *configScreen, *configKeyboard, *ssidInput, *passwordInput, *configStatus;
lv_obj_t *claimCard, *claimQr, *claimNetworkButton;
char lastClaimQr[80]{};
unsigned long logoPressedAt = 0, clearArmedAt = 0;
volatile bool configSaveRequested = false, configClearRequested = false;
char requestedSsid[33]{}, requestedPassword[65]{};
unsigned long lastRefresh = 0;
bool ready = false;
volatile bool localStopRequested = false;
portMUX_TYPE snapshotMux = portMUX_INITIALIZER_UNLOCKED;
enum class PanelMode : uint8_t { Ready, Reserved, Charging, Message, Unavailable, Maintenance };
struct PanelSnapshot {
  char status[64], alertTitle[40], code[64], connection[48], energy[24];
  char cost[24], remaining[32], instruction[128];
  char codeCaption[32], codeHint[64];
  char codeTimer[40];
  uint8_t codeProgress;
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

// Contêiner transparente sem borda, padding nem rolagem.
lv_obj_t* plain(lv_obj_t* parent, int x, int y, int width, int height) {
  lv_obj_t* value = lv_obj_create(parent);
  lv_obj_set_pos(value, x, y);
  lv_obj_set_size(value, width, height);
  lv_obj_set_style_bg_opa(value, LV_OPA_TRANSP, 0);
  lv_obj_set_style_border_width(value, 0, 0);
  lv_obj_set_style_radius(value, 0, 0);
  lv_obj_set_style_pad_all(value, 0, 0);
  lv_obj_clear_flag(value, LV_OBJ_FLAG_SCROLLABLE);
  return value;
}

lv_obj_t* card(lv_obj_t* parent, int x, int y, int width, int height) {
  lv_obj_t* value = plain(parent, x, y, width, height);
  lv_obj_set_style_bg_opa(value, LV_OPA_COVER, 0);
  lv_obj_set_style_bg_color(value, COLOR_CARD, 0);
  lv_obj_set_style_radius(value, 12, 0);
  return value;
}

// Bloco liso (sem bordas) para a ilustração do carregador.
lv_obj_t* shape(lv_obj_t* parent, int x, int y, int width, int height, int radius) {
  lv_obj_t* value = plain(parent, x, y, width, height);
  lv_obj_set_style_bg_opa(value, LV_OPA_COVER, 0);
  lv_obj_set_style_radius(value, radius, 0);
  return value;
}

void gradient(lv_obj_t* target, lv_color_t top, lv_color_t bottom) {
  lv_obj_set_style_bg_opa(target, LV_OPA_COVER, 0);
  lv_obj_set_style_bg_color(target, top, 0);
  lv_obj_set_style_bg_grad_color(target, bottom, 0);
  lv_obj_set_style_bg_grad_dir(target, LV_GRAD_DIR_VER, 0);
}

lv_obj_t* hline(lv_obj_t* parent, int y) {
  lv_obj_t* line = plain(parent, 39, y, 711, 1);
  lv_obj_set_style_bg_opa(line, LV_OPA_COVER, 0);
  lv_obj_set_style_bg_color(line, COLOR_LINE, 0);
  return line;
}

void stopClicked(lv_event_t*) { localStopRequested = true; }

void inputFocused(lv_event_t* event) {
  lv_keyboard_set_textarea(configKeyboard, static_cast<lv_obj_t*>(lv_event_get_target(event)));
}
void closeConfig(lv_event_t*) {
  lv_textarea_set_text(passwordInput, "");
  clearArmedAt = 0;
  lv_obj_add_flag(configScreen, LV_OBJ_FLAG_HIDDEN);
}
void openConfig(lv_event_t*) {
  lv_textarea_set_text(passwordInput, "");
  lv_label_set_text(configStatus, "Senha vazia: rede aberta. Identidade do dispositivo preservada.");
  lv_obj_clear_flag(configScreen, LV_OBJ_FLAG_HIDDEN);
}
void saveConfig(lv_event_t*) {
  const char* ssid = lv_textarea_get_text(ssidInput);
  const char* password = lv_textarea_get_text(passwordInput);
  if (!validPanelNetwork(ssid, password)) {
    lv_label_set_text(configStatus, "Informe o SSID. Para rede aberta, deixe a senha vazia.");
    return;
  }
  taskENTER_CRITICAL(&snapshotMux);
  snprintf(requestedSsid, sizeof(requestedSsid), "%s", ssid);
  snprintf(requestedPassword, sizeof(requestedPassword), "%s", password);
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
  if (!connectorActive) return "Estamos fazendo alguns ajustes para melhorar sua experiência.";
  return "Abra o app ChargeGrid e use o código ao lado para iniciar a recarga.";
}

// Cores da ilustração e do texto nas telas de alerta (vermelha / manutenção).
void applyAlertTheme(bool maintenance) {
  const lv_color_t top = maintenance ? lv_color_make(0xFE, 0xA5, 0x03) : lv_color_make(0xEC, 0x17, 0x1B);
  const lv_color_t bottom = maintenance ? lv_color_make(0xFD, 0x98, 0x02) : lv_color_make(0xC1, 0x07, 0x0B);
  const lv_color_t ink = maintenance ? lv_color_make(0x1B, 0x1B, 0x1B) : lv_color_white();
  gradient(alertRoot, top, bottom);
  lv_obj_set_style_text_color(alertTitle, ink, 0);
  lv_obj_set_style_text_color(alertSub, ink, 0);
  lv_obj_set_style_text_color(alertBrand, ink, 0);
  lv_obj_set_style_bg_color(alertLogoPad, maintenance ? lv_color_make(0x1B, 0x1B, 0x1B) : lv_color_white(), 0);
  const lv_color_t body = maintenance ? lv_color_make(0xFB, 0xB0, 0x0C) : lv_color_make(0xF3, 0x2B, 0x2D);
  const lv_color_t screen = maintenance ? lv_color_make(0xF0, 0x90, 0x04) : lv_color_make(0xA8, 0x0A, 0x0C);
  const lv_color_t side = maintenance ? lv_color_make(0xE6, 0x8A, 0x04) : lv_color_make(0x95, 0x08, 0x0A);
  lv_obj_set_style_bg_color(pumpBody, body, 0);
  lv_obj_set_style_bg_color(pumpSide, side, 0);
  lv_obj_set_style_bg_color(pumpScreen, screen, 0);
  lv_obj_set_style_bg_color(pumpNozzle, body, 0);
  lv_obj_set_style_img_recolor(pumpBolt, body, 0);
  lv_obj_set_style_line_color(pumpHose, body, 0);
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
  const bool alert = !current.showClaim &&
      (current.mode == PanelMode::Unavailable || current.mode == PanelMode::Maintenance);
  setTextIfChanged(statusLabel, current.status);
  setTextIfChanged(alertTitle, current.alertTitle);
  setTextIfChanged(codeLabel, current.code);
  setTextIfChanged(codeCaptionLabel, current.codeCaption);
  setTextIfChanged(codeHintLabel, current.codeHint);
  setTextIfChanged(codeTimerLabel, current.codeTimer);
  static uint8_t lastCodeProgress = 255;
  if (lastCodeProgress != current.codeProgress) {
    lv_bar_set_value(codeProgressBar, current.codeProgress, LV_ANIM_OFF);
    lastCodeProgress = current.codeProgress;
  }
  setTextIfChanged(connectionLabel, current.connection);
  if (!painted || current.online != lastOnline)
    lv_obj_set_style_bg_color(connectionDot, current.online ? COLOR_GREEN : COLOR_AMBER, 0);
  if (!painted || current.mode != lastMode)
    applyAlertTheme(current.mode == PanelMode::Maintenance);
  setTextIfChanged(energyLabel, current.energy);
  setTextIfChanged(costLabel, current.cost);
  setTextIfChanged(timeLabel, current.remaining);
  setTextIfChanged(sessionTimeLabel, current.remaining);
  setTextIfChanged(instructionLabel, current.instruction);
  setTextIfChanged(alertSub, current.instruction);
  setTextIfChanged(messageTitle, current.messageTitle);
  setTextIfChanged(messageDetail, current.messageDetail);
  const PanelMode mode = current.mode;
  const bool dark = !alert;
  const bool detail = dark && !current.showClaim;
  setHiddenIfChanged(darkRoot, !dark);
  setHiddenIfChanged(alertRoot, !alert);
  setHiddenIfChanged(leftBlock, !detail);
  setHiddenIfChanged(codeCard, !(detail && (mode == PanelMode::Ready || mode == PanelMode::Reserved)));
  setHiddenIfChanged(rowLineTop, !detail);
  setHiddenIfChanged(rowLineBottom, !detail);
  setHiddenIfChanged(stepsCard, !(detail && mode == PanelMode::Ready));
  setHiddenIfChanged(reservationCard, !(detail && mode == PanelMode::Reserved));
  setHiddenIfChanged(sessionCard, !(detail && mode == PanelMode::Charging));
  setHiddenIfChanged(messageCard, !(detail && mode == PanelMode::Message));
  setHiddenIfChanged(stopButton, !(detail && current.showStop));
  setHiddenIfChanged(codeProgressBar, mode != PanelMode::Ready);
  setHiddenIfChanged(codeTimerLabel, mode != PanelMode::Ready);
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

lv_obj_t* logoMark(lv_obj_t* parent, int x, int y, int zoom) {
  lv_obj_t* mark = lv_img_create(parent);
  lv_img_set_src(mark, &chargegrid_logo_64x64);
  lv_img_set_pivot(mark, 0, 0);
  lv_img_set_zoom(mark, zoom);
  lv_obj_set_pos(mark, x, y);
  lv_obj_add_flag(mark, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_add_event_cb(mark, logoEvent, LV_EVENT_ALL, nullptr);
  return mark;
}

// Seta fina ">" entre os passos.
void chevron(lv_obj_t* parent, int x, int y) {
  static lv_point_t points[3] = {{0, 0}, {9, 11}, {0, 22}};
  lv_obj_t* line = lv_line_create(parent);
  lv_line_set_points(line, points, 3);
  lv_obj_set_pos(line, x, y);
  lv_obj_set_style_line_width(line, 2, 0);
  lv_obj_set_style_line_color(line, COLOR_MUTED, 0);
  lv_obj_set_style_line_rounded(line, true, 0);
}

lv_obj_t* primaryButton(lv_obj_t* parent, const char* text, lv_event_cb_t cb, int x, int y,
                        int width, int height, lv_color_t color, lv_color_t textColor) {
  lv_obj_t* button = lv_btn_create(parent);
  lv_obj_set_pos(button, x, y); lv_obj_set_size(button, width, height);
  lv_obj_set_style_bg_color(button, color, 0);
  lv_obj_set_style_radius(button, 10, 0);
  lv_obj_set_style_shadow_width(button, 0, 0);
  lv_obj_add_event_cb(button, cb, LV_EVENT_CLICKED, nullptr);
  lv_obj_t* text_ = label(button, text, &chargegrid_montserrat_16, textColor);
  lv_obj_center(text_);
  return button;
}

void buildDark(lv_obj_t* screen) {
  darkRoot = plain(screen, 0, 0, 800, 480);
  gradient(darkRoot, COLOR_BG_TOP, COLOR_BG);

  logoMark(darkRoot, 39, UI_Y + 22, 160);
  lv_obj_t* brand = label(darkRoot, "ChargeGrid", &chargegrid_montserrat_24, COLOR_TEXT);
  lv_obj_set_pos(brand, 90, UI_Y + 26);

  // Estado de conexão: ponto colorido + texto, alinhados à direita.
  lv_obj_t* pill = plain(darkRoot, 450, UI_Y + 26, 300, 36);
  lv_obj_set_flex_flow(pill, LV_FLEX_FLOW_ROW);
  lv_obj_set_flex_align(pill, LV_FLEX_ALIGN_END, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
  lv_obj_set_style_pad_column(pill, 10, 0);
  connectionDot = shape(pill, 0, 0, 11, 11, LV_RADIUS_CIRCLE);
  lv_obj_set_style_bg_color(connectionDot, COLOR_AMBER, 0);
  lv_obj_set_style_shadow_width(connectionDot, 12, 0);
  lv_obj_set_style_shadow_opa(connectionDot, LV_OPA_40, 0);
  lv_obj_set_style_shadow_color(connectionDot, COLOR_AMBER, 0);
  connectionLabel = label(pill, "Preparando", &chargegrid_montserrat_16, COLOR_TEXT);

  // Título + subtítulo, centrados na faixa entre o cabeçalho e os passos.
  leftBlock = plain(darkRoot, 39, 128, 390, 190);
  lv_obj_set_flex_flow(leftBlock, LV_FLEX_FLOW_COLUMN);
  lv_obj_set_flex_align(leftBlock, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);
  lv_obj_set_style_pad_row(leftBlock, 12, 0);
  statusLabel = label(leftBlock, "Pronto para você", &chargegrid_title_40, COLOR_TEXT);
  lv_obj_set_width(statusLabel, 390);
  lv_label_set_long_mode(statusLabel, LV_LABEL_LONG_WRAP);
  instructionLabel = label(leftBlock, "Abra o app ChargeGrid e use o código ao lado para iniciar a recarga.",
                           &chargegrid_montserrat_18, COLOR_MUTED);
  lv_obj_set_width(instructionLabel, 350);
  lv_label_set_long_mode(instructionLabel, LV_LABEL_LONG_WRAP);

  // Cartão do código do ponto (também usado para o tempo da reserva).
  codeCard = card(darkRoot, 439, UI_Y + 104, 311, 160);
  lv_obj_set_style_radius(codeCard, 16, 0);
  gradient(codeCard, LV_COLOR_MAKE(0x56, 0x29, 0x2E), LV_COLOR_MAKE(0x1C, 0x17, 0x1B));
  lv_obj_set_style_border_width(codeCard, 1, 0);
  lv_obj_set_style_border_color(codeCard, LV_COLOR_MAKE(0x45, 0x34, 0x39), 0);
  codeCaptionLabel = label(codeCard, "CÓDIGO DO PONTO", &chargegrid_montserrat_14, LV_COLOR_MAKE(0xE6, 0xDA, 0xDC));
  lv_obj_set_style_text_letter_space(codeCaptionLabel, 3, 0);
  lv_obj_set_pos(codeCaptionLabel, 24, 22);
  codeLabel = label(codeCard, "--", &chargegrid_title_52, lv_color_white());
  lv_obj_set_pos(codeLabel, 24, 46); lv_obj_set_width(codeLabel, 270);
  lv_label_set_long_mode(codeLabel, LV_LABEL_LONG_DOT);
  codeHintLabel = label(codeCard, "", &chargegrid_montserrat_14, COLOR_TEXT);
  lv_obj_add_flag(codeHintLabel, LV_OBJ_FLAG_HIDDEN);
  codeTimerLabel = label(codeCard, "Aguardando código", &chargegrid_montserrat_14, LV_COLOR_MAKE(0xC9, 0xB9, 0xBC));
  lv_obj_set_pos(codeTimerLabel, 24, 116);
  codeProgressBar = lv_bar_create(codeCard);
  lv_obj_set_pos(codeProgressBar, 24, 140); lv_obj_set_size(codeProgressBar, 263, 4);
  lv_bar_set_range(codeProgressBar, 0, 100);
  lv_obj_set_style_bg_color(codeProgressBar, LV_COLOR_MAKE(0x3B, 0x2A, 0x2F), LV_PART_MAIN);
  lv_obj_set_style_bg_color(codeProgressBar, COLOR_TEXT, LV_PART_INDICATOR);

  stopButton = lv_btn_create(darkRoot);
  lv_obj_set_pos(stopButton, 439, UI_Y + 150); lv_obj_set_size(stopButton, 311, 64);
  lv_obj_set_style_bg_color(stopButton, COLOR_RED, 0);
  lv_obj_set_style_radius(stopButton, 14, 0);
  lv_obj_set_style_shadow_width(stopButton, 0, 0);
  lv_obj_add_event_cb(stopButton, stopClicked, LV_EVENT_CLICKED, nullptr);
  lv_obj_t* stopText = label(stopButton, "Encerrar", &chargegrid_montserrat_20, lv_color_white());
  lv_obj_center(stopText);
  lv_obj_add_flag(stopButton, LV_OBJ_FLAG_HIDDEN);

  rowLineTop = hline(darkRoot, 324);
  rowLineBottom = hline(darkRoot, 397);

  // Linha inferior (passos / reserva / métricas / mensagem), mesma faixa.
  stepsCard = plain(darkRoot, 39, 325, 711, 72);
  const char* stepTitles[] = {"Abra o app ChargeGrid", "Use o código deste ponto", "Comece a recarga"};
  // Montserrat é mais larga que a fonte do design: títulos em 14 px para caber com as setas.
  const char* stepDetails[] = {"No seu celular", "Digite no app", "Conecte e carregue"};
  const int stepX[] = {8, 250, 508};
  const int chevronX[] = {232, 490};
  for (int i = 0; i < 3; ++i) {
    lv_obj_t* tile = shape(stepsCard, stepX[i], 20, 36, 34, 4);
    lv_obj_set_style_bg_color(tile, lv_color_white(), 0);
    char digits[3] = {'0', static_cast<char>('1' + i), '\0'};
    lv_obj_t* number = label(tile, digits, &chargegrid_montserrat_20, LV_COLOR_MAKE(0x10, 0x10, 0x10));
    lv_obj_center(number);
    lv_obj_t* stepTitle = label(stepsCard, stepTitles[i], &chargegrid_montserrat_14, COLOR_TEXT);
    lv_obj_set_pos(stepTitle, stepX[i] + 46, 21);
    lv_obj_t* stepDetail = label(stepsCard, stepDetails[i], &chargegrid_montserrat_14, COLOR_MUTED);
    lv_obj_set_pos(stepDetail, stepX[i] + 46, 40);
    if (i < 2) chevron(stepsCard, chevronX[i], 25);
  }

  reservationCard = plain(darkRoot, 39, 325, 711, 72);
  // O prazo aparece no cartão de destaque; timeLabel segue atualizado, porém oculto.
  timeLabel = label(reservationCard, "--", &chargegrid_montserrat_14, COLOR_TEXT);
  lv_obj_add_flag(timeLabel, LV_OBJ_FLAG_HIDDEN);
  lv_obj_t* reservationHelp = label(reservationCard, "Seu ponto está guardado. Inicie a recarga no aplicativo.", &chargegrid_montserrat_18, COLOR_SOFT);
  lv_obj_set_pos(reservationHelp, 8, 26);

  sessionCard = plain(darkRoot, 39, 325, 711, 72);
  const char* metricNames[] = {"ENERGIA", "VALOR ESTIMADO", "TEMPO RESTANTE"};
  lv_obj_t** metricValues[] = {&energyLabel, &costLabel, &sessionTimeLabel};
  for (int i = 0; i < 3; ++i) {
    const int x = 8 + i * 236;
    lv_obj_t* name = label(sessionCard, metricNames[i], &chargegrid_montserrat_14, COLOR_MUTED);
    lv_obj_set_style_text_letter_space(name, 2, 0);
    lv_obj_set_pos(name, x, 12);
    *metricValues[i] = label(sessionCard, "--", &chargegrid_montserrat_24, COLOR_TEXT);
    lv_obj_set_pos(*metricValues[i], x, 34);
    lv_obj_set_width(*metricValues[i], 220);
    lv_label_set_long_mode(*metricValues[i], LV_LABEL_LONG_DOT);
  }

  messageCard = plain(darkRoot, 39, 325, 711, 72);
  messageTitle = label(messageCard, "Precisa de ajuda?", &chargegrid_montserrat_20, COLOR_TEXT);
  lv_obj_set_pos(messageTitle, 8, 12);
  messageDetail = label(messageCard, "Encontre outro ponto pelo app ChargeGrid.", &chargegrid_montserrat_16, COLOR_MUTED);
  lv_obj_set_pos(messageDetail, 8, 40); lv_obj_set_width(messageDetail, 690);
  lv_label_set_long_mode(messageDetail, LV_LABEL_LONG_DOT);

  // Tela de vinculação (ponto sem dono). Só um token de claim separado gera o QR.
  // Transparente: o cabeçalho (logo + estado "Aguardando vínculo") continua visível.
  claimCard = plain(darkRoot, 0, 0, 800, 480);
  lv_obj_t* claimTitle = label(claimCard, "Ative seu ponto", &chargegrid_title_40, COLOR_TEXT);
  lv_obj_set_pos(claimTitle, 39, UI_Y + 106);
  const char* claimStepText[] = {"Entre como vendedor no app.", "Escaneie este QR Code.", "Defina nome, local e tarifa."};
  for (int i = 0; i < 3; ++i) {
    const int y = UI_Y + 190 + i * 34;
    lv_obj_t* tile = shape(claimCard, 39, y, 30, 26, 3);
    lv_obj_set_style_bg_color(tile, lv_color_white(), 0);
    char digits[3] = {'0', static_cast<char>('1' + i), '\0'};
    lv_obj_t* number = label(tile, digits, &chargegrid_montserrat_16, LV_COLOR_MAKE(0x10, 0x10, 0x10));
    lv_obj_center(number);
    lv_obj_t* text = label(claimCard, claimStepText[i], &chargegrid_montserrat_18, COLOR_SOFT);
    lv_obj_set_pos(text, 82, y + 2);
  }
  claimNetworkButton = lv_btn_create(claimCard);
  lv_obj_set_pos(claimNetworkButton, 39, UI_Y + 295); lv_obj_set_size(claimNetworkButton, 200, 44);
  lv_obj_set_style_bg_color(claimNetworkButton, COLOR_CONTROL, 0);
  lv_obj_set_style_border_width(claimNetworkButton, 1, 0);
  lv_obj_set_style_border_color(claimNetworkButton, LV_COLOR_MAKE(0x34, 0x3A, 0x44), 0);
  lv_obj_set_style_radius(claimNetworkButton, 10, 0); lv_obj_set_style_shadow_width(claimNetworkButton, 0, 0);
  lv_obj_add_event_cb(claimNetworkButton, openConfig, LV_EVENT_CLICKED, nullptr);
  lv_obj_t* claimNetworkText = label(claimNetworkButton, "Configurar Wi-Fi", &chargegrid_montserrat_16, COLOR_TEXT);
  lv_obj_center(claimNetworkText);
  lv_obj_t* qrBorder = shape(claimCard, 507, UI_Y + 81, 243, 274, 14);
  lv_obj_set_style_bg_color(qrBorder, lv_color_white(), 0);
  claimQr = lv_qrcode_create(qrBorder, 200, lv_color_black(), lv_color_white());
  lv_obj_align(claimQr, LV_ALIGN_TOP_MID, 0, 22);
  lv_obj_t* qrCaption = label(qrBorder, "QR privado de vinculação", &chargegrid_montserrat_14, LV_COLOR_MAKE(0x20, 0x20, 0x20));
  lv_obj_align(qrCaption, LV_ALIGN_BOTTOM_MID, 0, -14);
  lv_obj_clear_flag(claimCard, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_add_flag(claimCard, LV_OBJ_FLAG_HIDDEN);
}

void buildAlert(lv_obj_t* screen) {
  alertRoot = plain(screen, 0, 0, 800, 480);
  gradient(alertRoot, LV_COLOR_MAKE(0xEC, 0x17, 0x1B), LV_COLOR_MAKE(0xC1, 0x07, 0x0B));

  // Ilustração do carregador (translúcida, sangra na borda direita/inferior).
  pumpBody = shape(alertRoot, 500, UI_Y + 56, 246, 440, 52);
  pumpSide = shape(alertRoot, 690, UI_Y + 80, 56, 420, 28);
  lv_obj_set_style_bg_opa(pumpSide, LV_OPA_60, 0);
  pumpScreen = shape(alertRoot, 526, UI_Y + 86, 154, 222, 24);
  pumpBolt = lv_img_create(alertRoot);
  lv_img_set_src(pumpBolt, &chargegrid_pump_bolt);
  lv_obj_set_pos(pumpBolt, 563, UI_Y + 129);
  lv_obj_set_style_img_recolor_opa(pumpBolt, LV_OPA_COVER, 0);
  pumpNozzle = shape(alertRoot, 722, UI_Y + 136, 52, 114, 22);
  static lv_point_t hose[] = {{0, 0}, {6, 36}, {11, 76}, {10, 106}, {-2, 126}, {-26, 134}};
  pumpHose = lv_line_create(alertRoot);
  lv_line_set_points(pumpHose, hose, 6);
  lv_obj_set_pos(pumpHose, 772, UI_Y + 250);
  lv_obj_set_style_line_width(pumpHose, 9, 0);
  lv_obj_set_style_line_rounded(pumpHose, true, 0);

  alertLogoPad = shape(alertRoot, 54, UI_Y + 86, 36, 36, 7);
  logoMark(alertLogoPad, 3, 3, 120);
  alertBrand = label(alertRoot, "ChargeGrid", &chargegrid_montserrat_24, lv_color_white());
  lv_obj_set_pos(alertBrand, 99, UI_Y + 90);

  alertTitle = label(alertRoot, "Ponto Indisponível", &chargegrid_title_52, lv_color_white());
  lv_obj_set_width(alertTitle, 440);
  lv_label_set_long_mode(alertTitle, LV_LABEL_LONG_WRAP);
  lv_obj_set_style_text_line_space(alertTitle, -4, 0);
  lv_obj_set_pos(alertTitle, 54, UI_Y + 134);
  alertSub = label(alertRoot, "", &chargegrid_montserrat_18, lv_color_white());
  lv_obj_set_width(alertSub, 420);
  lv_label_set_long_mode(alertSub, LV_LABEL_LONG_WRAP);
  lv_obj_set_pos(alertSub, 54, UI_Y + 276);
  lv_obj_add_flag(alertRoot, LV_OBJ_FLAG_HIDDEN);
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

  buildDark(screen);
  buildAlert(screen);

  configScreen = lv_obj_create(screen);
  lv_obj_set_size(configScreen, 800, 480); lv_obj_set_pos(configScreen, 0, 0);
  lv_obj_set_style_bg_color(configScreen, COLOR_BG, 0); lv_obj_set_style_radius(configScreen, 0, 0);
  lv_obj_set_style_border_width(configScreen, 0, 0); lv_obj_set_style_pad_all(configScreen, 0, 0);
  lv_obj_clear_flag(configScreen, LV_OBJ_FLAG_SCROLLABLE);
  lv_obj_t* configTitle = label(configScreen, "Configurar este ponto", &chargegrid_montserrat_24, COLOR_TEXT);
  lv_obj_set_pos(configTitle, 16, 8);
  const char* fieldNames[] = {"Wi-Fi (SSID)", "Senha (rede aberta: vazia)"};
  lv_obj_t** fields[] = {&ssidInput, &passwordInput};
  for (int i = 0; i < 2; ++i) {
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
    lv_obj_set_style_radius(*fields[i], 10, 0);
    lv_textarea_set_one_line(*fields[i], true);
    lv_obj_set_style_text_font(*fields[i], &chargegrid_montserrat_16, 0);
    lv_obj_add_event_cb(*fields[i], inputFocused, LV_EVENT_FOCUSED, nullptr);
  }
  lv_textarea_set_password_mode(passwordInput, true);
  lv_textarea_set_max_length(ssidInput, 32); lv_textarea_set_max_length(passwordInput, 64);
  configStatus = label(configScreen, "Senha vazia: rede aberta. Identidade do dispositivo preservada.", &chargegrid_montserrat_14, COLOR_MUTED);
  lv_obj_set_pos(configStatus, 8, 228); lv_obj_set_width(configStatus, 590);
  lv_label_set_long_mode(configStatus, LV_LABEL_LONG_DOT);
  struct ButtonDef { const char* text; lv_event_cb_t cb; lv_color_t color; lv_color_t ink; } buttons[] = {
    {"Salvar e conectar", saveConfig, lv_color_white(), lv_color_black()},
    {"Limpar rede", clearConfig, COLOR_CONTROL, COLOR_TEXT},
    {"Voltar", closeConfig, COLOR_CONTROL, COLOR_TEXT}
  };
  for (int i = 0; i < 3; ++i)
    primaryButton(configScreen, buttons[i].text, buttons[i].cb, 614, 44 + i * 58, 170, 48,
                  buttons[i].color, buttons[i].ink);
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
    char ssid[sizeof(requestedSsid)], password[sizeof(requestedPassword)];
    taskENTER_CRITICAL(&snapshotMux);
    snprintf(ssid, sizeof(ssid), "%s", requestedSsid);
    snprintf(password, sizeof(password), "%s", requestedPassword);
    configSaveRequested = false;
    taskEXIT_CRITICAL(&snapshotMux);
    if (!savePanelConnection(ssid, password, "")) {
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
    snprintf(next.status, sizeof(next.status), "Em preparação");
    snprintf(next.code, sizeof(next.code), "EM BREVE");
    snprintf(next.codeCaption, sizeof(next.codeCaption), "SEU PONTO");
    snprintf(next.codeHint, sizeof(next.codeHint), "Ainda não disponível");
    snprintf(next.connection, sizeof(next.connection), "%s", wifiConnected ? "Preparando ponto" : "Em instalação");
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
  const bool unavailable = state != "stopped" && std::strcmp(statusTitle(), "Ponto indisponível") == 0;
  next.mode = state == "charging" ? PanelMode::Charging :
      state == "reserved" ? PanelMode::Reserved :
      state == "idle" && apiOnline && connectorActive && panelOwned ? PanelMode::Ready :
      unavailable ? PanelMode::Unavailable :
      state == "idle" && apiOnline && panelOwned && !connectorActive ? PanelMode::Maintenance :
      PanelMode::Message;
  next.online = apiOnline && (next.mode != PanelMode::Message || state == "stopped");
  snprintf(next.status, sizeof(next.status), "%s", statusTitle());
  snprintf(next.alertTitle, sizeof(next.alertTitle), "%s",
      next.mode == PanelMode::Maintenance ? "Estamos em manutenção" : "Ponto Indisponível");
  const unsigned long codeElapsed = millis() - presenceCodeReceivedAt;
  const unsigned long codeRemaining = codeElapsed < presenceCodeTtlMs ? presenceCodeTtlMs - codeElapsed : 0UL;
  const bool rotatingCodeKnown = stationPresenceCode.length() == 7 &&
      stationPresenceCode[0] == '#' && stationPresenceCode[1] == 'F';
  const bool codeVisible = apiOnline && connectorActive && panelOwned &&
      rotatingCodeKnown && codeRemaining > 0;
  const bool legacyCodeVisible = apiOnline && connectorActive && panelOwned &&
      !rotatingCodeKnown && connectorPublicCode != "--";
  snprintf(next.code, sizeof(next.code), "%s", codeVisible ? stationPresenceCode.c_str() :
      legacyCodeVisible ? connectorPublicCode.c_str() : "--");
  snprintf(next.codeCaption, sizeof(next.codeCaption), "CÓDIGO DO PONTO");
  snprintf(next.codeHint, sizeof(next.codeHint), "%s", codeVisible || legacyCodeVisible ?
      "Use no app ChargeGrid" : rotatingCodeKnown && apiOnline ?
      "Atualizando código" : "Indisponível agora");
  if (codeVisible)
    snprintf(next.codeTimer, sizeof(next.codeTimer), "Troca em %02lu:%02lu",
        codeRemaining / 60000UL, (codeRemaining / 1000UL) % 60UL);
  else
    snprintf(next.codeTimer, sizeof(next.codeTimer), "%s", legacyCodeVisible ?
        "Código #F em breve" : rotatingCodeKnown && apiOnline ?
        "Novo código em instantes" : "Aguardando código");
  next.codeProgress = codeVisible ? static_cast<uint8_t>(min(100UL, (codeRemaining * 100UL) / 300000UL)) : 0;
  const char* connection = apiOnline ?
      (state == "charging" ? "Em uso" : state == "reserved" ? "Reservado" :
      state == "stopped" ? "Recarga concluída" : !panelOwned ? "Aguardando vínculo" :
      !connectorActive ? "Em preparação" : "Pronto para uso") :
      "Temporariamente offline";
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
  if (next.mode == PanelMode::Reserved) {
    // O cartão de destaque mostra o prazo da reserva no lugar do código.
    snprintf(next.codeCaption, sizeof(next.codeCaption), "TEMPO PARA INICIAR");
    snprintf(next.code, sizeof(next.code), "%s", next.remaining);
  }
  snprintf(next.messageTitle, sizeof(next.messageTitle), "%s", state == "stopped" ?
      "Até a próxima" : "Encontre outro ponto");
  snprintf(next.messageDetail, sizeof(next.messageDetail), "%s", state == "stopped" ?
      "Veja o resumo da sua recarga no app ChargeGrid." :
      "Abra o app ChargeGrid para encontrar uma opção próxima.");
  next.showStop = state == "charging";
  }
  taskENTER_CRITICAL(&snapshotMux);
  snapshot = next;
  taskEXIT_CRITICAL(&snapshotMux);
}

#endif
