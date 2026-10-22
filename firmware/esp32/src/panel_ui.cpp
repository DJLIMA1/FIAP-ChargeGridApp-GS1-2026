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
#ifdef CHARGEGRID_KIOSK
#include "kiosk_flow.h"
#include "extra_chargers.h"
#include "ui/router.h"
#include "ui/strings_ptbr.h"
#endif


// O port da placa deve chamar lv_disp_drv_register/lv_indev_drv_register antes
// de panelSetup(). A escolha do port depende do modelo Waveshare 7 ou 7B.
//
// Layout: o design de referência do totem é 2:1 (800x400 a 0,25x); o painel é 5:3.
// Em vez de faixas pretas, as posições verticais são esticadas em 1,2 (400 -> 480)
// e a interface ocupa os 800x480 inteiros.
namespace {
// Fundo e gradiente usam valores exatos de RGB565 (R/B em múltiplos de 8, G de 4):
// qualquer outro tom "pula" de matiz entre as faixas do degradê no painel de 16 bits.
const lv_color_t COLOR_BG = LV_COLOR_MAKE(0x18, 0x1C, 0x20);
const lv_color_t COLOR_BG_TOP = LV_COLOR_MAKE(0x20, 0x24, 0x28);
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
lv_obj_t *batteryCard, *socLabel, *socDetailLabel, *socBar;
lv_obj_t *messageTitle, *messageDetail;
lv_obj_t *alertTitle, *alertSub, *alertBrand, *alertLogoPad;
lv_obj_t *pumpBody, *pumpSide, *pumpScreen, *pumpBolt, *pumpNozzle, *pumpHose;
lv_obj_t *configScreen, *configKeyboard, *ssidInput, *passwordInput, *configStatus;
lv_obj_t *claimCard, *claimQr, *claimNetworkButton;
char lastClaimQr[80]{};
// 0.7.0: QR de pagamento (modo teste) na tela Pronto e botão "Desconectar" da permanência.
lv_obj_t *kioskCard, *kioskTitle, *kioskDetail, *kioskQrBox, *kioskQr, *disconnectButton;
char lastKioskQr[164]{};
// 0.8.0: botão "Iniciar recarga" do totem na tela Pronto (oculto com o totem desligado).
lv_obj_t* kioskStartButton = nullptr;
lv_obj_t* kioskAlertStartButton = nullptr;
lv_obj_t* panelScreen = nullptr;
unsigned long logoPressedAt = 0, clearArmedAt = 0;
volatile bool configSaveRequested = false, configClearRequested = false;
char requestedSsid[33]{}, requestedPassword[65]{};
unsigned long lastRefresh = 0;
bool ready = false;
volatile bool localStopRequested = false;
volatile bool localDisconnectRequested = false;
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
  char kioskUrl[164], kioskDetail[80];
  uint8_t kioskTone; // 0 neutro, 1 aguardando, 2 confirmado, 3 recusado
  bool showKiosk, showDisconnect;
  bool showKioskStart;   // 0.8.0: totem ligado e ponto livre na tela Pronto
  char soc[8], socDetail[32];
  uint8_t socProgress;
  bool showSoc;
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
#ifdef CHARGEGRID_KIOSK
void kioskStartClicked(lv_event_t*) { ui::pushAction(kiosk::Action::StartFlow); }
#endif
void disconnectClicked(lv_event_t*) { localDisconnectRequested = true; }

// Números em pt-BR (vírgula decimal) para os textos novos do painel.
void decimalComma(char* out, size_t size, const char* format, float value) {
  snprintf(out, size, format, value);
  for (char* c = out; *c; ++c) if (*c == '.') *c = ',';
}
void brl(char* out, size_t size, float value) { decimalComma(out, size, "R$ %.2f", value); }

// Permanência: o carro continua conectado depois de parar (START com overstay).
bool overstayView() { return reading.connected && (state == "stopped" || state == "idle"); }

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

bool batteryFullStop() { return state == "stopped" && endReason == "battery_full"; }

const char* statusTitle() {
  if (state == "charging") return chargePowerW > 0 ? "Recarga em andamento" : "Recarga pausada";
  if (overstayView()) return batteryFullStop() ? "Bateria cheia" : "Recarga concluída";
  if (batteryFullStop()) return "Bateria cheia";
  if (state == "reserved") return "Ponto reservado";
  if (state == "stopped") return "Recarga encerrada";
  if (state == "fault") return "Ponto indisponível";
  if (panelIntegrationEnabled && WiFi.status() != WL_CONNECTED) return "Ponto indisponível";
  if (panelIntegrationEnabled && WiFi.status() == WL_CONNECTED && (lastSyncHttpStatus == 401 || lastSyncHttpStatus == 403)) return "Ponto indisponível";
  if (!hasSynced) return "Só um instante";
  if (millis() - lastContact >= 45000 && state == "idle") return "Ponto indisponível";
  if (connectorOwnershipKnown && !panelOwned) return "Em configuração";
  if (!connectorActive) return "Em breve";
  if (chargerLink.configured() && !chargerLink.online()) return "Carregador indisponível";
  return "Pronto para você";
}

const char* instruction() {
  if (state == "charging") return "Acompanhe pelo app. Para parar, toque em Encerrar.";
  if (overstayView()) return "Retire o cabo do carro e toque em Desconectar.";
  if (state == "reserved") return WiFi.status() == WL_CONNECTED ?
      "Sua reserva está ativa. Inicie pelo app antes do prazo." :
      "Sua reserva continua ativa. Aguarde a conexão para iniciar.";
  if (batteryFullStop()) return "A recarga parou sozinha em 100%. Seu resumo está no app.";
  if (state == "stopped") return "Obrigado por usar ChargeGrid. Seu resumo está no app.";
  if (state == "fault") return "Este ponto está indisponível. Encontre outro no app.";
  if (WiFi.status() != WL_CONNECTED) return "Estamos reconectando. Encontre outro ponto pelo app.";
  if (lastSyncHttpStatus == 401 || lastSyncHttpStatus == 403) return "Este ponto precisa de configuração. Procure outro no app.";
  if (!hasSynced) return "Estamos preparando este ponto para você.";
  if (millis() - lastContact >= 45000) return "A conexão caiu. Encontre outro ponto pelo app.";
  if (connectorOwnershipKnown && !panelOwned) return "O responsável está preparando este ponto.";
  if (!connectorActive) return "Estamos fazendo alguns ajustes para melhorar sua experiência.";
  if (chargerLink.configured() && !chargerLink.online()) return "A central está online, mas o carregador não responde. Aguarde a reconexão.";
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

// Estado do último desenho das telas atuais. Zerado quando as telas são reconstruídas
// depois de uma tela do totem (objetos novos começam com os valores padrão).
struct RefreshCache {
  bool painted = false, lastOnline = false;
  PanelMode lastMode = PanelMode::Message;
  uint8_t lastCodeProgress = 255, lastSocProgress = 255, lastKioskTone = 255;
  bool lastKioskStart = false;
} cache;

#ifdef CHARGEGRID_KIOSK
kiosk::KioskView kioskSnapshot{};   // publicado em panelTick sob snapshotMux
#endif

void refresh() {
  PanelSnapshot current;
#ifdef CHARGEGRID_KIOSK
  static kiosk::KioskView kioskCurrent;
  taskENTER_CRITICAL(&snapshotMux);
  current = snapshot;
  kioskCurrent = kioskSnapshot;
  taskEXIT_CRITICAL(&snapshotMux);
  // Tela do totem na frente: as telas atuais estão liberadas e não são atualizadas.
  if (ui::routerUpdate(kioskCurrent)) return;
#else
  taskENTER_CRITICAL(&snapshotMux);
  current = snapshot;
  taskEXIT_CRITICAL(&snapshotMux);
#endif
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
  bool& painted = cache.painted;
  bool& lastOnline = cache.lastOnline;
  PanelMode& lastMode = cache.lastMode;
  const bool alert = !current.showClaim &&
      (current.mode == PanelMode::Unavailable || current.mode == PanelMode::Maintenance);
  setTextIfChanged(statusLabel, current.status);
  setTextIfChanged(alertTitle, current.alertTitle);
  setTextIfChanged(codeLabel, current.code);
  setTextIfChanged(codeCaptionLabel, current.codeCaption);
  setTextIfChanged(codeHintLabel, current.codeHint);
  setTextIfChanged(codeTimerLabel, current.codeTimer);
  uint8_t& lastCodeProgress = cache.lastCodeProgress;
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
  setTextIfChanged(socLabel, current.soc);
  setTextIfChanged(socDetailLabel, current.socDetail);
  uint8_t& lastSocProgress = cache.lastSocProgress;
  if (lastSocProgress != current.socProgress) {
    lv_bar_set_value(socBar, current.socProgress, LV_ANIM_OFF);
    lastSocProgress = current.socProgress;
  }
  const PanelMode mode = current.mode;
  const bool dark = !alert;
  const bool detail = dark && !current.showClaim;
  setHiddenIfChanged(darkRoot, !dark);
  setHiddenIfChanged(alertRoot, !alert);
  setHiddenIfChanged(leftBlock, !detail);
  setHiddenIfChanged(codeCard, !(detail && (mode == PanelMode::Ready || mode == PanelMode::Reserved)));
  setHiddenIfChanged(rowLineTop, !detail);
  setHiddenIfChanged(rowLineBottom, !detail);
  const bool kiosk = detail && mode == PanelMode::Ready && current.showKiosk;
  setHiddenIfChanged(stepsCard, !(detail && mode == PanelMode::Ready) || kiosk);
  setHiddenIfChanged(kioskCard, !kiosk);
  setHiddenIfChanged(kioskQrBox, !kiosk);
  // Com o QR de pagamento, o cartão do código sobe e as linhas param antes do QR.
  const int codeY = kiosk ? 118 : 130, codeHeight = kiosk ? 172 : 180, lineWidth = kiosk ? 531 : 711;
  if (lv_obj_get_y(codeCard) != codeY) { lv_obj_set_y(codeCard, codeY); lv_obj_set_height(codeCard, codeHeight); }
  if (lv_obj_get_width(rowLineTop) != lineWidth) {
    lv_obj_set_width(rowLineTop, lineWidth); lv_obj_set_width(rowLineBottom, lineWidth);
  }
  if (kiosk && std::strcmp(lastKioskQr, current.kioskUrl) != 0 &&
      lv_qrcode_update(kioskQr, current.kioskUrl, std::strlen(current.kioskUrl)) == LV_RES_OK)
    snprintf(lastKioskQr, sizeof(lastKioskQr), "%s", current.kioskUrl);
  setTextIfChanged(kioskDetail, current.kioskDetail);
  uint8_t& lastKioskTone = cache.lastKioskTone;
  if (lastKioskTone != current.kioskTone) {
    const lv_color_t tones[] = {COLOR_MUTED, COLOR_AMBER, COLOR_GREEN, LV_COLOR_MAKE(0xFF, 0x6B, 0x70)};
    lv_obj_set_style_text_color(kioskDetail, tones[current.kioskTone & 3], 0);
    lastKioskTone = current.kioskTone;
  }
  setHiddenIfChanged(reservationCard, !(detail && mode == PanelMode::Reserved));
  setHiddenIfChanged(sessionCard, !(detail && mode == PanelMode::Charging));
  setHiddenIfChanged(messageCard, !(detail && mode == PanelMode::Message));
  setHiddenIfChanged(stopButton, !(detail && current.showStop));
  setHiddenIfChanged(disconnectButton, !(detail && current.showDisconnect && !current.showStop));
  // Bateria do veículo: acima do botão (Encerrar/Desconectar); centrada no fim da sessão.
  const bool battery = detail && current.showSoc &&
      (mode == PanelMode::Charging || mode == PanelMode::Message);
  setHiddenIfChanged(batteryCard, !battery);
  const bool actionButton = current.showStop || current.showDisconnect;
  const int batteryY = actionButton ? 112 : 152, stopY = battery ? 270 : 188;
  const int stopHeight = battery ? 56 : 64;
  if (lv_obj_get_y(batteryCard) != batteryY) lv_obj_set_y(batteryCard, batteryY);
  if (lv_obj_get_y(stopButton) != stopY) {
    lv_obj_set_y(stopButton, stopY); lv_obj_set_height(stopButton, stopHeight);
  }
  if (lv_obj_get_y(disconnectButton) != stopY) {
    lv_obj_set_y(disconnectButton, stopY); lv_obj_set_height(disconnectButton, stopHeight);
  }
  setHiddenIfChanged(codeProgressBar, mode != PanelMode::Ready && mode != PanelMode::Reserved);
  setHiddenIfChanged(codeTimerLabel, mode != PanelMode::Ready && mode != PanelMode::Reserved);
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
#ifdef CHARGEGRID_KIOSK
  // Totem ligado: "Iniciar recarga" à esquerda, sob o título, terminando na mesma linha do
  // cartão do código ("Tem o app?"). Desligado: nada muda (mesmos objetos, mesmas posições).
  const bool kioskStart = detail && current.showKioskStart;
  setHiddenIfChanged(kioskStartButton, !kioskStart);
  setHiddenIfChanged(kioskAlertStartButton, !(alert && current.showKioskStart));
  if (kioskStart != cache.lastKioskStart || !painted) {
    lv_obj_set_y(leftBlock, kioskStart ? 118 : 124);
    lv_obj_set_height(leftBlock, kioskStart ? 120 : 200);
    lv_obj_set_style_pad_row(leftBlock, kioskStart ? 10 : 36, 0);
    cache.lastKioskStart = kioskStart;
  }
#endif
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
  lv_obj_t* text_ = label(button, text, &chargegrid_body_17, textColor);
  lv_obj_center(text_);
  return button;
}

void buildDark(lv_obj_t* screen) {
  darkRoot = plain(screen, 0, 0, 800, 480);
  gradient(darkRoot, COLOR_BG_TOP, COLOR_BG);

  logoMark(darkRoot, 39, 43, 120);
  lv_obj_t* brand = label(darkRoot, "ChargeGrid", &chargegrid_brand_30, COLOR_TEXT);
  lv_obj_set_pos(brand, 73, 40);

  // Estado de conexão: ponto colorido + texto, alinhados à direita.
  lv_obj_t* pill = plain(darkRoot, 450, 38, 300, 36);
  lv_obj_set_flex_flow(pill, LV_FLEX_FLOW_ROW);
  lv_obj_set_flex_align(pill, LV_FLEX_ALIGN_END, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
  lv_obj_set_style_pad_column(pill, 10, 0);
  connectionDot = shape(pill, 0, 0, 11, 11, LV_RADIUS_CIRCLE);
  lv_obj_set_style_bg_color(connectionDot, COLOR_AMBER, 0);
  lv_obj_set_style_shadow_width(connectionDot, 12, 0);
  lv_obj_set_style_shadow_opa(connectionDot, LV_OPA_40, 0);
  lv_obj_set_style_shadow_color(connectionDot, COLOR_AMBER, 0);
  connectionLabel = label(pill, "Preparando", &chargegrid_body_17, COLOR_TEXT);

  // Título + subtítulo, centrados na faixa entre o cabeçalho e os passos.
  leftBlock = plain(darkRoot, 39, 124, 390, 200);
  lv_obj_set_flex_flow(leftBlock, LV_FLEX_FLOW_COLUMN);
  lv_obj_set_flex_align(leftBlock, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);
  lv_obj_set_style_pad_row(leftBlock, 36, 0);
  statusLabel = label(leftBlock, "Pronto para você", &chargegrid_title_48, COLOR_TEXT);
  lv_obj_set_width(statusLabel, 390);
  lv_label_set_long_mode(statusLabel, LV_LABEL_LONG_WRAP);
  instructionLabel = label(leftBlock, "Abra o app ChargeGrid e use o código ao lado para iniciar a recarga.",
                           &chargegrid_body_19, COLOR_MUTED);
  lv_obj_set_width(instructionLabel, 350);
  lv_label_set_long_mode(instructionLabel, LV_LABEL_LONG_WRAP);

  // Cartão do código do ponto (também usado para o tempo da reserva).
  codeCard = card(darkRoot, 439, 130, 311, 180);
  lv_obj_set_style_radius(codeCard, 16, 0);
  gradient(codeCard, LV_COLOR_MAKE(0x56, 0x29, 0x2E), LV_COLOR_MAKE(0x1C, 0x17, 0x1B));
  lv_obj_set_style_border_width(codeCard, 1, 0);
  lv_obj_set_style_border_color(codeCard, LV_COLOR_MAKE(0x45, 0x34, 0x39), 0);
  codeCaptionLabel = label(codeCard, "CÓDIGO DO PONTO", &chargegrid_body_14, LV_COLOR_MAKE(0xE6, 0xDA, 0xDC));
  lv_obj_set_style_text_letter_space(codeCaptionLabel, 3, 0);
  lv_obj_set_pos(codeCaptionLabel, 24, 34);
  codeLabel = label(codeCard, "--", &chargegrid_code_72, lv_color_white());
  lv_obj_set_pos(codeLabel, 24, 66); lv_obj_set_width(codeLabel, 270);
  lv_label_set_long_mode(codeLabel, LV_LABEL_LONG_DOT);
  codeHintLabel = label(codeCard, "", &chargegrid_body_14, COLOR_TEXT);
  lv_obj_add_flag(codeHintLabel, LV_OBJ_FLAG_HIDDEN);
  codeTimerLabel = label(codeCard, "Aguardando código", &chargegrid_body_14, LV_COLOR_MAKE(0xC9, 0xB9, 0xBC));
  lv_obj_set_pos(codeTimerLabel, 24, 138);
  codeProgressBar = lv_bar_create(codeCard);
  lv_obj_set_pos(codeProgressBar, 24, 162); lv_obj_set_size(codeProgressBar, 263, 4);
  lv_bar_set_range(codeProgressBar, 0, 100);
  lv_obj_set_style_bg_color(codeProgressBar, LV_COLOR_MAKE(0x3B, 0x2A, 0x2F), LV_PART_MAIN);
  lv_obj_set_style_bg_color(codeProgressBar, COLOR_TEXT, LV_PART_INDICATOR);

  // Cartão da bateria do carro (SoC sincronizado pela API: mesmo valor do app).
  batteryCard = card(darkRoot, 439, 112, 311, 146);
  lv_obj_set_style_radius(batteryCard, 16, 0);
  gradient(batteryCard, LV_COLOR_MAKE(0x20, 0x44, 0x30), LV_COLOR_MAKE(0x18, 0x1C, 0x20));
  lv_obj_set_style_border_width(batteryCard, 1, 0);
  lv_obj_set_style_border_color(batteryCard, LV_COLOR_MAKE(0x2C, 0x48, 0x38), 0);
  lv_obj_t* socCaption = label(batteryCard, "BATERIA DO VEÍCULO", &chargegrid_body_14, COLOR_SOFT);
  lv_obj_set_style_text_letter_space(socCaption, 3, 0);
  lv_obj_set_pos(socCaption, 24, 20);
  socLabel = label(batteryCard, "--", &chargegrid_code_72, lv_color_white());
  lv_obj_set_pos(socLabel, 22, 34);
  socDetailLabel = label(batteryCard, "", &chargegrid_body_17, COLOR_SOFT);
  lv_obj_align(socDetailLabel, LV_ALIGN_TOP_RIGHT, -24, 84);
  socBar = lv_bar_create(batteryCard);
  lv_obj_set_pos(socBar, 24, 122); lv_obj_set_size(socBar, 263, 8);
  lv_bar_set_range(socBar, 0, 100);
  lv_obj_set_style_bg_color(socBar, LV_COLOR_MAKE(0x28, 0x34, 0x30), LV_PART_MAIN);
  lv_obj_set_style_bg_color(socBar, COLOR_GREEN, LV_PART_INDICATOR);
  lv_obj_add_flag(batteryCard, LV_OBJ_FLAG_HIDDEN);

  stopButton = lv_btn_create(darkRoot);
  lv_obj_set_pos(stopButton, 439, 188); lv_obj_set_size(stopButton, 311, 64);
  lv_obj_set_style_bg_color(stopButton, COLOR_RED, 0);
  lv_obj_set_style_radius(stopButton, 14, 0);
  lv_obj_set_style_shadow_width(stopButton, 0, 0);
  lv_obj_add_event_cb(stopButton, stopClicked, LV_EVENT_CLICKED, nullptr);
  lv_obj_t* stopText = label(stopButton, "Encerrar", &chargegrid_body_22, lv_color_white());
  lv_obj_center(stopText);
  lv_obj_add_flag(stopButton, LV_OBJ_FLAG_HIDDEN);

  // Permanência: o motorista confirma que retirou o cabo (mesmo lugar do Encerrar).
  disconnectButton = lv_btn_create(darkRoot);
  lv_obj_set_pos(disconnectButton, 439, 188); lv_obj_set_size(disconnectButton, 311, 64);
  lv_obj_set_style_bg_color(disconnectButton, lv_color_white(), 0);
  lv_obj_set_style_radius(disconnectButton, 14, 0);
  lv_obj_set_style_shadow_width(disconnectButton, 0, 0);
  lv_obj_add_event_cb(disconnectButton, disconnectClicked, LV_EVENT_CLICKED, nullptr);
  lv_obj_t* disconnectText = label(disconnectButton, "Desconectar", &chargegrid_body_22, LV_COLOR_MAKE(0x10, 0x10, 0x10));
  lv_obj_center(disconnectText);
  lv_obj_add_flag(disconnectButton, LV_OBJ_FLAG_HIDDEN);

#ifdef CHARGEGRID_KIOSK
  // Totem: botão grande na coluna do título; a base coincide com a do cartão do código
  // (130 + 180 = 310). Só aparece com o totem ligado.
  kioskStartButton = lv_btn_create(darkRoot);
  lv_obj_set_pos(kioskStartButton, 39, 246); lv_obj_set_size(kioskStartButton, 380, 64);
  lv_obj_set_style_bg_color(kioskStartButton, COLOR_RED, 0);
  lv_obj_set_style_radius(kioskStartButton, 14, 0);
  lv_obj_set_style_shadow_width(kioskStartButton, 0, 0);
  lv_obj_add_event_cb(kioskStartButton, kioskStartClicked, LV_EVENT_CLICKED, nullptr);
  lv_obj_t* kioskStartText = label(kioskStartButton, kiosk::str::kStartButton, &chargegrid_brand_30, lv_color_white());
  lv_obj_center(kioskStartText);
  lv_obj_add_flag(kioskStartButton, LV_OBJ_FLAG_HIDDEN);
#endif

  rowLineTop = hline(darkRoot, 340);
  rowLineBottom = hline(darkRoot, 432);

  // Linha inferior (passos / reserva / métricas / mensagem), mesma faixa.
  stepsCard = plain(darkRoot, 39, 341, 711, 90);
  const char* stepTitles[] = {"Abra o app ChargeGrid", "Use o código deste ponto", "Comece a recarga"};
  // títulos em Barlow Condensed Medium 17 px para caber com as setas.
  const char* stepDetails[] = {"No seu celular", "Digite no app", "Comece pelo app"};
  // A segunda seta repete os vãos da primeira (texto → seta → próximo número),
  // medidos pela largura real do texto de cada passo.
  auto stepTextEnd = [&](int i, int x) {
    lv_point_t title, detail;
    lv_txt_get_size(&title, stepTitles[i], &chargegrid_body_17, 0, 0, LV_COORD_MAX, LV_TEXT_FLAG_NONE);
    lv_txt_get_size(&detail, stepDetails[i], &chargegrid_body_14, 0, 0, LV_COORD_MAX, LV_TEXT_FLAG_NONE);
    return x + 46 + LV_MAX(title.x, detail.x);
  };
  int stepX[] = {6, 241, 0};
  int chevronX[] = {219, 0};
  const int gapBeforeChevron = chevronX[0] - stepTextEnd(0, stepX[0]);
  const int gapAfterChevron = stepX[1] - chevronX[0];
  chevronX[1] = stepTextEnd(1, stepX[1]) + gapBeforeChevron;
  stepX[2] = chevronX[1] + gapAfterChevron;
  for (int i = 0; i < 3; ++i) {
    lv_obj_t* tile = shape(stepsCard, stepX[i], 23, 38, 44, 4);
    lv_obj_set_style_bg_color(tile, lv_color_white(), 0);
    char digits[3] = {'0', static_cast<char>('1' + i), '\0'};
    lv_obj_t* number = label(tile, digits, &chargegrid_brand_30, LV_COLOR_MAKE(0x10, 0x10, 0x10));
    lv_obj_center(number);
    lv_obj_t* stepTitle = label(stepsCard, stepTitles[i], &chargegrid_body_17, COLOR_TEXT);
    lv_obj_set_pos(stepTitle, stepX[i] + 46, 23);
    lv_obj_t* stepDetail = label(stepsCard, stepDetails[i], &chargegrid_body_14, COLOR_MUTED);
    lv_obj_set_pos(stepDetail, stepX[i] + 46, 46);
    if (i < 2) chevron(stepsCard, chevronX[i], 34);
  }

  reservationCard = plain(darkRoot, 39, 341, 711, 90);
  // Prazo da reserva separado do código temporário e da sua validade.
  lv_obj_t* reservationCaption = label(reservationCard, "Inicie em", &chargegrid_body_14, COLOR_MUTED);
  lv_obj_set_pos(reservationCaption, 8, 14);
  timeLabel = label(reservationCard, "--", &chargegrid_brand_30, COLOR_TEXT);
  lv_obj_set_pos(timeLabel, 8, 36);
  lv_obj_t* reservationHelp = label(reservationCard, "Seu ponto está guardado. Inicie a recarga no aplicativo.", &chargegrid_body_19, COLOR_SOFT);
  lv_obj_set_pos(reservationHelp, 190, 30);
  lv_obj_set_width(reservationHelp, 500);

  sessionCard = plain(darkRoot, 39, 341, 711, 90);
  const char* metricNames[] = {"ENERGIA", "VALOR ESTIMADO", "TEMPO RESTANTE"};
  lv_obj_t** metricValues[] = {&energyLabel, &costLabel, &sessionTimeLabel};
  for (int i = 0; i < 3; ++i) {
    const int x = 8 + i * 236;
    lv_obj_t* name = label(sessionCard, metricNames[i], &chargegrid_body_14, COLOR_MUTED);
    lv_obj_set_style_text_letter_space(name, 2, 0);
    lv_obj_set_pos(name, x, 18);
    *metricValues[i] = label(sessionCard, "--", &chargegrid_brand_30, COLOR_TEXT);
    lv_obj_set_pos(*metricValues[i], x, 42);
    lv_obj_set_width(*metricValues[i], 220);
    lv_label_set_long_mode(*metricValues[i], LV_LABEL_LONG_DOT);
  }

  // Pagamento sem app (modo teste): legenda na linha inferior, QR à direita dela.
  kioskCard = plain(darkRoot, 39, 341, 531, 90);
  kioskTitle = label(kioskCard, "Sem o app? Pague aqui · TESTE", &chargegrid_body_22, COLOR_TEXT);
  lv_obj_set_pos(kioskTitle, 8, 18);
  kioskDetail = label(kioskCard, "", &chargegrid_body_17, COLOR_MUTED);
  lv_obj_set_pos(kioskDetail, 8, 50); lv_obj_set_width(kioskDetail, 515);
  lv_label_set_long_mode(kioskDetail, LV_LABEL_LONG_DOT);
  lv_obj_add_flag(kioskCard, LV_OBJ_FLAG_HIDDEN);
  kioskQrBox = shape(darkRoot, 584, 302, 166, 166, 12);
  lv_obj_set_style_bg_color(kioskQrBox, lv_color_white(), 0);
  kioskQr = lv_qrcode_create(kioskQrBox, 150, lv_color_black(), lv_color_white());
  lv_obj_center(kioskQr);
  lv_obj_add_flag(kioskQrBox, LV_OBJ_FLAG_HIDDEN);

  messageCard = plain(darkRoot, 39, 341, 711, 90);
  messageTitle = label(messageCard, "Precisa de ajuda?", &chargegrid_body_22, COLOR_TEXT);
  lv_obj_set_pos(messageTitle, 8, 18);
  messageDetail = label(messageCard, "Encontre outro ponto pelo app ChargeGrid.", &chargegrid_body_17, COLOR_MUTED);
  lv_obj_set_pos(messageDetail, 8, 50); lv_obj_set_width(messageDetail, 690);
  lv_label_set_long_mode(messageDetail, LV_LABEL_LONG_DOT);

  // Tela de vinculação (ponto sem dono). Só um token de claim separado gera o QR.
  // Transparente: o cabeçalho (logo + estado "Aguardando vínculo") continua visível.
  claimCard = plain(darkRoot, 0, 0, 800, 480);
  lv_obj_t* claimTitle = label(claimCard, "Ative seu ponto", &chargegrid_title_48, COLOR_TEXT);
  lv_obj_set_pos(claimTitle, 39, 130);
  const char* claimStepText[] = {"Entre como vendedor no app.", "Escaneie este QR Code.", "Defina nome, local e tarifa."};
  for (int i = 0; i < 3; ++i) {
    const int y = 218 + i * 36;
    lv_obj_t* tile = shape(claimCard, 39, y, 30, 28, 3);
    lv_obj_set_style_bg_color(tile, lv_color_white(), 0);
    char digits[3] = {'0', static_cast<char>('1' + i), '\0'};
    lv_obj_t* number = label(tile, digits, &chargegrid_body_19, LV_COLOR_MAKE(0x10, 0x10, 0x10));
    lv_obj_center(number);
    lv_obj_t* text = label(claimCard, claimStepText[i], &chargegrid_body_17, COLOR_SOFT);
    lv_obj_set_pos(text, 82, y + 3);
  }
  claimNetworkButton = lv_btn_create(claimCard);
  lv_obj_set_pos(claimNetworkButton, 39, 352); lv_obj_set_size(claimNetworkButton, 200, 48);
  lv_obj_set_style_bg_color(claimNetworkButton, COLOR_CONTROL, 0);
  lv_obj_set_style_border_width(claimNetworkButton, 1, 0);
  lv_obj_set_style_border_color(claimNetworkButton, LV_COLOR_MAKE(0x34, 0x3A, 0x44), 0);
  lv_obj_set_style_radius(claimNetworkButton, 10, 0); lv_obj_set_style_shadow_width(claimNetworkButton, 0, 0);
  lv_obj_add_event_cb(claimNetworkButton, openConfig, LV_EVENT_CLICKED, nullptr);
  lv_obj_t* claimNetworkText = label(claimNetworkButton, "Configurar Wi-Fi", &chargegrid_body_17, COLOR_TEXT);
  lv_obj_center(claimNetworkText);
  lv_obj_t* qrBorder = shape(claimCard, 507, 100, 243, 324, 14);
  lv_obj_set_style_bg_color(qrBorder, lv_color_white(), 0);
  claimQr = lv_qrcode_create(qrBorder, 200, lv_color_black(), lv_color_white());
  lv_obj_align(claimQr, LV_ALIGN_TOP_MID, 0, 28);
  lv_obj_t* qrCaption = label(qrBorder, "QR privado de vinculação", &chargegrid_body_17, LV_COLOR_MAKE(0x20, 0x20, 0x20));
  lv_obj_align(qrCaption, LV_ALIGN_BOTTOM_MID, 0, -20);
  lv_obj_clear_flag(claimCard, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_add_flag(claimCard, LV_OBJ_FLAG_HIDDEN);
}

void buildAlert(lv_obj_t* screen) {
  alertRoot = plain(screen, 0, 0, 800, 480);
  gradient(alertRoot, LV_COLOR_MAKE(0xEC, 0x17, 0x1B), LV_COLOR_MAKE(0xC1, 0x07, 0x0B));

  // Ilustração do carregador (translúcida, sangra na borda direita/inferior).
  pumpBody = shape(alertRoot, 502, 68, 244, 520, 52);
  pumpSide = shape(alertRoot, 706, 96, 40, 500, 28);
  lv_obj_set_style_bg_opa(pumpSide, LV_OPA_60, 0);
  pumpScreen = shape(alertRoot, 527, 102, 154, 265, 24);
  pumpBolt = lv_img_create(alertRoot);
  lv_img_set_src(pumpBolt, &chargegrid_pump_bolt);
  lv_obj_set_pos(pumpBolt, 563, 151);
  lv_obj_set_style_img_recolor_opa(pumpBolt, LV_OPA_COVER, 0);
  pumpNozzle = shape(alertRoot, 722, 162, 52, 137, 22);
  static lv_point_t hose[] = {{0, 0}, {6, 43}, {11, 91}, {10, 127}, {-2, 151}, {-26, 161}};
  pumpHose = lv_line_create(alertRoot);
  lv_line_set_points(pumpHose, hose, 6);
  lv_obj_set_pos(pumpHose, 772, 296);
  lv_obj_set_style_line_width(pumpHose, 9, 0);
  lv_obj_set_style_line_rounded(pumpHose, true, 0);

  alertLogoPad = shape(alertRoot, 54, 104, 38, 38, 7);
  logoMark(alertLogoPad, 3, 3, 128);
  alertBrand = label(alertRoot, "ChargeGrid", &chargegrid_brand_34, lv_color_white());
  lv_obj_set_pos(alertBrand, 100, 103);

  alertTitle = label(alertRoot, "Ponto Indisponível", &chargegrid_alert_68, lv_color_white());
  lv_obj_set_width(alertTitle, 440);
  lv_label_set_long_mode(alertTitle, LV_LABEL_LONG_WRAP);
  lv_obj_set_style_text_line_space(alertTitle, -12, 0);
  lv_obj_set_pos(alertTitle, 54, 163);
  alertSub = label(alertRoot, "", &chargegrid_body_22, lv_color_white());
  lv_obj_set_width(alertSub, 370);
#ifdef CHARGEGRID_KIOSK
  kioskAlertStartButton = lv_btn_create(alertRoot);
  lv_obj_set_pos(kioskAlertStartButton, 54, 388); lv_obj_set_size(kioskAlertStartButton, 390, 64);
  lv_obj_set_style_bg_color(kioskAlertStartButton, lv_color_white(), 0);
  lv_obj_set_style_radius(kioskAlertStartButton, 14, 0);
  lv_obj_add_event_cb(kioskAlertStartButton, kioskStartClicked, LV_EVENT_CLICKED, nullptr);
  lv_obj_t* alternate = label(kioskAlertStartButton, "Usar outro carregador", &chargegrid_brand_30, lv_color_black());
  lv_obj_center(alternate); lv_obj_add_flag(kioskAlertStartButton, LV_OBJ_FLAG_HIDDEN);
#endif
  lv_label_set_long_mode(alertSub, LV_LABEL_LONG_WRAP);
  lv_obj_set_pos(alertSub, 54, 324);
  lv_obj_add_flag(alertRoot, LV_OBJ_FLAG_HIDDEN);
}

#ifdef CHARGEGRID_KIOSK
// Pool LVGL de 64 KB: enquanto uma tela do totem está aberta, as telas atuais (escuras e
// alerta, ~40 KB no host) são apagadas e reconstruídas ao voltar. A tela de manutenção
// (Wi-Fi) fica, porque é aberta por cima delas.
void releasePanelScreens() {
  lv_obj_del(darkRoot);
  lv_obj_del(alertRoot);
  darkRoot = alertRoot = nullptr;
  kioskStartButton = nullptr;
  kioskAlertStartButton = nullptr;
}
void restorePanelScreens() {
  buildDark(panelScreen);
  buildAlert(panelScreen);
  lv_obj_move_foreground(configScreen);
  cache = RefreshCache{};
  memset(lastKioskQr, 0, sizeof(lastKioskQr));
  memset(lastClaimQr, 0, sizeof(lastClaimQr));
}
#endif
}  // namespace

#ifdef CHARGEGRID_KIOSK
kiosk::Flow kioskFlow;

namespace {
void copyText(char* out, size_t size, const char* text) { snprintf(out, size, "%s", text ? text : ""); }

// Fatos do ponto para o fluxo do totem (mesma tarefa de apply()/tick(): sem corrida).
void kioskFacts(kiosk::Facts& f, const PanelSnapshot& next) {
  f.nowMs = millis();
  const bool authRejected = lastSyncHttpStatus == 401 || lastSyncHttpStatus == 403;
  f.online = panelIntegrationEnabled && WiFi.status() == WL_CONNECTED && !authRejected &&
             hasSynced && millis() - lastContact < 45000;
  f.chargerOffline = chargerLink.configured() && !chargerLink.online();
  f.pointReady = panelIntegrationEnabled && next.mode == PanelMode::Ready && !next.showClaim;
  f.reserved = state == "reserved" || kioskSync.reservationPresent;
  f.carConnected = overstayView();
  f.maintenance = !connectorActive || (connectorOwnershipKnown && !panelOwned);
  f.charging = state == "charging";
  f.stopped = state == "stopped";
  f.sessionAuthorized = kioskSync.sessionPresent;
  copyText(f.sessionId, sizeof(f.sessionId), sessionId.c_str());
  copyText(f.endReason, sizeof(f.endReason), endReason.c_str());
  f.energyKwh = sessionId.length() ? reading.energyWh / 1000.0f : 0;
  const float estimatedCost = reading.energyWh / 1000.0f * price * (1.0f - discount / 100.0f);
  f.costCents = sessionId.length() && sessionPricingKnown ? static_cast<int32_t>(lroundf(estimatedCost * 100)) : -1;
  f.capCents = maxCost >= 0 ? static_cast<int32_t>(lroundf(maxCost * 100)) : -1;
  f.appliedPowerKw = state == "charging" ? (sessionAppliedPowerKw >= 0 ? sessionAppliedPowerKw : chargePowerW / 1000.0f) : -1;
  copyText(f.powerReason, sizeof(f.powerReason), powerReasonShort.c_str());
  f.socPercent = sessionId.length() && sessionSocKnown() ? reading.socPercent : -1;
  if (state == "charging") {
    const unsigned long elapsed = millis() - started;
    f.elapsedS = elapsed / 1000UL;
    f.remainingS = elapsed < maxDurationMs ? (maxDurationMs - elapsed) / 1000UL : 0;
  }
  if (f.carConnected) {
    copyText(f.overstayTitle, sizeof(f.overstayTitle), next.messageTitle);
    copyText(f.overstayDetail, sizeof(f.overstayDetail), next.messageDetail);
  }
  f.sync = kioskSync;
  // A busy/offline charger does not hide other free chargers of this central.
  const auto stage = kioskFlow.state();
  const bool selecting = stage == kiosk::State::Idle || stage == kiosk::State::Off || stage == kiosk::State::Welcome ||
      stage == kiosk::State::Login || stage == kiosk::State::LoadingOffer || stage == kiosk::State::Connector;
  if (!kioskFlow.chargerAddress() && selecting && panelOwned && f.online) {
    for (const extra::Slot& slot : extra::slots) {
      if (slot.used && slot.active && slot.state == "idle" && !slot.connected && slot.link.online()) {
        f.pointReady = true; f.charging = false; f.reserved = false; f.carConnected = false;
        f.sessionAuthorized = false; f.maintenance = false;
        f.chargerOffline = false;
        break;
      }
    }
  }
  if (kioskFlow.chargerAddress()) {
    for (const extra::Slot& slot : extra::slots) {
      if (!slot.used || slot.address != kioskFlow.chargerAddress()) continue;
      f.online = f.online && millis() - slot.lastContact < kiosk::Flow::kResumeGiveUpMs;
      f.pointReady = slot.active && slot.state == "idle" && !slot.connected;
      f.chargerOffline = slot.link.configured() && !slot.link.online();
      f.reserved = slot.state == "reserved" || slot.kioskSync.reservationPresent;
      f.carConnected = false;
      f.maintenance = !slot.active;
      f.charging = slot.state == "charging"; f.stopped = slot.state == "stopped";
      f.sessionAuthorized = slot.kioskSync.sessionPresent;
      copyText(f.sessionId, sizeof(f.sessionId), slot.sessionId.c_str());
      copyText(f.endReason, sizeof(f.endReason), slot.endReason.c_str());
      f.energyKwh = slot.energyWh / 1000;
      f.costCents = static_cast<int32_t>(lroundf(f.energyKwh * slot.price * (1 - slot.discount / 100) * 100));
      f.capCents = slot.maxCost >= 0 ? static_cast<int32_t>(lroundf(slot.maxCost * 100)) : -1;
      f.appliedPowerKw = slot.limitW / 1000;
      f.socPercent = -1;
      f.elapsedS = f.charging ? (millis() - slot.started) / 1000 : 0;
      f.remainingS = f.elapsedS * 1000 < slot.maxDurationMs ? slot.maxDurationMs / 1000 - f.elapsedS : 0;
      f.powerReason[0] = 0; f.overstayTitle[0] = 0; f.overstayDetail[0] = 0;
      f.sync = slot.kioskSync;
      if (!f.sync.kiosk.present) f.sync.kiosk = kioskSync.kiosk;
      break;
    }
  }
}

void kioskTick(PanelSnapshot& next) {
  if (kioskFlow.state() == kiosk::State::Idle || kioskFlow.state() == kiosk::State::Off) {
    uint8_t address = 0;
    if (state != "charging") for (const auto& slot : extra::slots) {
      if (slot.used && slot.state == "charging" && std::strcmp(slot.kioskSync.sessionOrigin, "kiosk_totem") != 0) {
        address = slot.address; break;
      }
    }
    kioskFlow.followAppCharger(address);
  }
  static kiosk::Facts facts;   // ~1 KB: fora da pilha da tarefa
  facts = kiosk::Facts{};
  kioskFacts(facts, next);
  kioskFlow.facts(facts);
  ui::Input input;
  while (ui::popInput(input)) {
    if (input.key) kioskFlow.key(input.value, millis());
    else kioskFlow.touch(input.action, millis());
  }
  if (kioskFlow.takeLocalStop()) {
    if (!kioskFlow.chargerAddress()) requestLocalSafeStop();
    else for (extra::Slot& slot : extra::slots) if (slot.used && slot.address == kioskFlow.chargerAddress()) {
      extra::stop(slot, "requested"); slot.syncNow = true; requestImmediateSync();
    }
  }
  if (kioskFlow.takeLocalDisconnect()) requestLocalDisconnect();
  char order[kiosk::kIdSize];
  if (kioskFlow.takePersist(order, sizeof(order))) kioskPersistOrder(order);
  next.showKioskStart = kioskFlow.canStart();
  if (next.showKioskStart && next.mode == PanelMode::Ready) {
    snprintf(next.instruction, sizeof(next.instruction), "%s", kiosk::str::kStartHint);
    snprintf(next.codeCaption, sizeof(next.codeCaption), "%s", kiosk::str::kCodeCaption);
  }
}
}  // namespace

void kioskResume(const char* orderId, uint32_t seed, uint8_t chargerAddress) {
  kioskFlow.setSeed(seed);
  kioskFlow.resume(orderId, millis(), chargerAddress);
}
#endif

void panelSetup() {
  if (!chargegridPanelHardwareSetup()) {
    Serial.println("[panel] profile LCD/touch ausente; controlador segue sem UI");
    return;
  }
  lvgl_port_lock(-1);
  lv_obj_t* screen = lv_scr_act();
  panelScreen = screen;
  lv_obj_set_style_bg_color(screen, COLOR_BG, 0);
  lv_obj_clear_flag(screen, LV_OBJ_FLAG_SCROLLABLE);

  buildDark(screen);
  buildAlert(screen);

  configScreen = lv_obj_create(screen);
  lv_obj_set_size(configScreen, 800, 480); lv_obj_set_pos(configScreen, 0, 0);
  lv_obj_set_style_bg_color(configScreen, COLOR_BG, 0); lv_obj_set_style_radius(configScreen, 0, 0);
  lv_obj_set_style_border_width(configScreen, 0, 0); lv_obj_set_style_pad_all(configScreen, 0, 0);
  lv_obj_clear_flag(configScreen, LV_OBJ_FLAG_SCROLLABLE);
  lv_obj_t* configTitle = label(configScreen, "Configurar este ponto", &chargegrid_body_22, COLOR_TEXT);
  lv_obj_set_pos(configTitle, 16, 8);
  const char* fieldNames[] = {"Wi-Fi (SSID)", "Senha (rede aberta: vazia)"};
  lv_obj_t** fields[] = {&ssidInput, &passwordInput};
  for (int i = 0; i < 2; ++i) {
    lv_obj_t* fieldName = label(configScreen, fieldNames[i], &chargegrid_body_17, COLOR_MUTED);
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
    lv_obj_set_style_text_font(*fields[i], &chargegrid_body_17, 0);
    lv_obj_add_event_cb(*fields[i], inputFocused, LV_EVENT_FOCUSED, nullptr);
  }
  lv_textarea_set_password_mode(passwordInput, true);
  lv_textarea_set_max_length(ssidInput, 32); lv_textarea_set_max_length(passwordInput, 64);
  configStatus = label(configScreen, "Senha vazia: rede aberta. Identidade do dispositivo preservada.", &chargegrid_body_17, COLOR_MUTED);
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
#ifdef CHARGEGRID_KIOSK
  ui::routerInit(screen, releasePanelScreens, restorePanelScreens);
  kioskFlow.followAppSessions(); // acompanhamento e finalização únicos, inclusive com totem desligado
#endif
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
#ifdef CHARGEGRID_KIOSK
    // Totem ligado: Encerrar de uma recarga do app pede confirmação (T7). Em qualquer
    // outro estado do fluxo a parada é imediata, como sempre.
    if (kioskFlow.state() == kiosk::State::Idle && state == "charging") kioskFlow.touch(kiosk::Action::Stop, millis());
    else
#endif
    requestLocalSafeStop();
  }
  if (localDisconnectRequested) {
    localDisconnectRequested = false;
    requestLocalDisconnect();
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
      hasSynced && millis() - lastContact < 45000;
  const bool chargerOffline = apiOnline && chargerLink.configured() && !chargerLink.online();
  const bool unavailable = state != "stopped" &&
      (chargerOffline || std::strcmp(statusTitle(), "Ponto indisponível") == 0);
  const bool overstay = overstayView();
  next.mode = state == "charging" ? PanelMode::Charging :
      overstay ? PanelMode::Message :
      state == "reserved" ? PanelMode::Reserved :
      state == "idle" && apiOnline && !chargerOffline && connectorActive && panelOwned ? PanelMode::Ready :
      unavailable ? PanelMode::Unavailable :
      state == "idle" && apiOnline && panelOwned && !connectorActive ? PanelMode::Maintenance :
      PanelMode::Message;
  next.online = apiOnline && (next.mode != PanelMode::Message || state == "stopped" || overstay);
  snprintf(next.status, sizeof(next.status), "%s", statusTitle());
  snprintf(next.alertTitle, sizeof(next.alertTitle), "%s",
      next.mode == PanelMode::Maintenance ? "Estamos em manutenção" : chargerOffline ? "Carregador indisponível" : "Ponto Indisponível");
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
      (state == "charging" ? "Em uso" : overstay ? "Carro conectado" : state == "reserved" ? "Reservado" :
      state == "stopped" ? "Recarga concluída" : !panelOwned ? "Aguardando vínculo" :
      !connectorActive ? "Em preparação" : chargerOffline ? "Central online" : "Pronto para uso") :
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
  // Potência aplicada confirmada pela API (nunca o alvo) e o motivo curto da divisão.
  if (state == "charging" && sessionAppliedPowerKw >= 0) {
    char kw[16]; decimalComma(kw, sizeof(kw), "%.1f", sessionAppliedPowerKw);
    if (sessionAppliedPowerKw <= 0)
      snprintf(next.instruction, sizeof(next.instruction), "Pausada para dividir a potência%s%s",
               powerReasonShort.length() ? ": " : " do posto.", powerReasonShort.c_str());
    else if (powerReasonShort.length())
      snprintf(next.instruction, sizeof(next.instruction), "Potência %s kW · %s", kw, powerReasonShort.c_str());
    else
      snprintf(next.instruction, sizeof(next.instruction), "Potência %s kW. Para parar, toque em Encerrar.", kw);
  }
  // Pagamento pelo QR do painel (sempre modo teste na API atual).
  const char* testMark = paymentTest ? " (teste)" : "";
  char amount[24] = "";
  if (paymentAmount > 0) { char value[20]; brl(value, sizeof(value), paymentAmount); snprintf(amount, sizeof(amount), " · %s", value); }
  if (paymentStatus == "awaiting_payment") {
    snprintf(next.kioskDetail, sizeof(next.kioskDetail), "Aguardando pagamento%s%s", testMark, amount);
    next.kioskTone = 1;
  } else if (paymentStatus == "authorized" || paymentStatus == "paid") {
    snprintf(next.kioskDetail, sizeof(next.kioskDetail), "Pagamento confirmado%s · iniciando", testMark);
    next.kioskTone = 2;
  } else if (paymentStatus == "declined") {
    snprintf(next.kioskDetail, sizeof(next.kioskDetail), "Pagamento recusado%s. Tente de novo.", testMark);
    next.kioskTone = 3;
  } else {
    snprintf(next.kioskDetail, sizeof(next.kioskDetail), "Escaneie com a câmera do celular e escolha o valor.");
    next.kioskTone = 0;
  }
  if (next.mode == PanelMode::Ready) {
    next.showKiosk = kioskUrl.length() > 0 && kioskUrl.length() < sizeof(next.kioskUrl);
    if (next.showKiosk) {
      snprintf(next.kioskUrl, sizeof(next.kioskUrl), "%s", kioskUrl.c_str());
      snprintf(next.instruction, sizeof(next.instruction), "Use o código ao lado no app ChargeGrid ou pague pelo QR, sem app.");
    } else if (paymentStatus.length()) {
      snprintf(next.instruction, sizeof(next.instruction), "%s", next.kioskDetail);
    }
  }
  // O código temporário continua visível durante a reserva. O prazo já aparece
  // no cartão de reserva e em remaining, sem substituir código/validade.
  // SoC só aparece quando a API informou (simulado pela energia ou nível do celular).
  next.showSoc = sessionId.length() && hasSynced && (state == "charging" || state == "stopped") &&
      sessionSocKnown();
  if (next.showSoc) {
    const float soc = batteryFullStop() ? 100.0f : constrain(reading.socPercent, 0.0f, 100.0f);
    // Arredonda para baixo: "100%" só com a bateria realmente cheia.
    const int whole = soc >= 100.0f ? 100 : min(99, static_cast<int>(soc));
    snprintf(next.soc, sizeof(next.soc), "%d%%", whole);
    next.socProgress = static_cast<uint8_t>(whole);
    if (socSource == "phone") snprintf(next.socDetail, sizeof(next.socDetail), "Nível do celular");
    else snprintf(next.socDetail, sizeof(next.socDetail), "Início %d%%", static_cast<int>(socStartPercent + 0.5f));
  } else {
    snprintf(next.soc, sizeof(next.soc), "--");
  }
  snprintf(next.messageTitle, sizeof(next.messageTitle), "%s", state == "stopped" ?
      "Até a próxima" : "Encontre outro ponto");
  snprintf(next.messageDetail, sizeof(next.messageDetail), "%s", state == "stopped" ?
      "Veja o resumo da sua recarga no app ChargeGrid." :
      "Abra o app ChargeGrid para encontrar uma opção próxima.");
  next.showStop = state == "charging";
  if (overstay) {
    // Contagem local a partir de grace_remaining_seconds; a taxa vem sempre da API.
    char fee[20] = "", cap[20] = "", rate[20] = "";
    if (overstayFeeDue >= 0) brl(fee, sizeof(fee), overstayFeeDue);
    if (overstayMaxFee >= 0) brl(cap, sizeof(cap), overstayMaxFee);
    if (overstayAmount > 0) brl(rate, sizeof(rate), overstayAmount);
    const unsigned long elapsed = (millis() - overstayReceivedAt) / 1000UL;
    const long grace = overstayGraceSeconds > (long)elapsed ? overstayGraceSeconds - (long)elapsed : 0L;
    if (overstayStatus == "grace")
      snprintf(next.messageTitle, sizeof(next.messageTitle), "Recarga concluída · desconecte em %02ld:%02ld", grace / 60L, grace % 60L);
    else if ((overstayStatus == "billing" || overstayStatus == "capped") && fee[0])
      snprintf(next.messageTitle, sizeof(next.messageTitle), "Taxa de permanência: %s%s", fee,
               overstayStatus == "capped" ? " (valor máximo)" : "");
    else snprintf(next.messageTitle, sizeof(next.messageTitle), "Recarga concluída · desconecte o carro");
    if (overstayStatus == "no_fee")
      snprintf(next.messageDetail, sizeof(next.messageDetail), "Sem taxa de permanência neste ponto.");
    else if (overstayStatus.length() && overstayStatus != "closed" && rate[0] && overstayIntervalMinutes > 0)
      snprintf(next.messageDetail, sizeof(next.messageDetail), "Após a tolerância: %s a cada %ld min%s%s.", rate,
               overstayIntervalMinutes, cap[0] ? ", até " : "", cap);
    else snprintf(next.messageDetail, sizeof(next.messageDetail), "Veja o resumo da sua recarga no app ChargeGrid.");
    next.showDisconnect = true;
  }
  }
  // "Bateria cheia" fica visível por alguns segundos: a API encerra a sessão no mesmo
  // sync e o ponto voltaria a "Pronto" antes de o motorista ver o motivo da parada.
  static PanelSnapshot batteryFullHeld{};
  static unsigned long batteryFullHoldUntil = 0;
  if (batteryFullStop()) {
    batteryFullHeld = next; batteryFullHoldUntil = millis() + 10000UL;
    if (!batteryFullHoldUntil) batteryFullHoldUntil = 1;
  } else if (batteryFullHoldUntil && (long)(millis() - batteryFullHoldUntil) < 0 &&
             state == "idle" && !sessionId.length() && !next.showClaim && !reading.connected) {
    next = batteryFullHeld;
  } else batteryFullHoldUntil = 0;
#ifdef CHARGEGRID_KIOSK
  kioskTick(next);
  taskENTER_CRITICAL(&snapshotMux);
  snapshot = next;
  kioskSnapshot = kioskFlow.view();
  taskEXIT_CRITICAL(&snapshotMux);
#else
  taskENTER_CRITICAL(&snapshotMux);
  snapshot = next;
  taskEXIT_CRITICAL(&snapshotMux);
#endif
}

#endif
