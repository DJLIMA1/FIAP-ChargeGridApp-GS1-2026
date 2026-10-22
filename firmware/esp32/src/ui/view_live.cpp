#ifdef CHARGEGRID_KIOSK
#include <stdio.h>
#include <string.h>
#include "ui/router.h"
#include "ui/strings_ptbr.h"
#include "ui/tokens.h"
#include "ui/widgets.h"
namespace ui { namespace view_live {
namespace t = tokens;
// Mesmo desenho da recarga do painel (tela Pronto → Em uso): título à esquerda, cartão da
// bateria e Encerrar à direita, métricas na faixa entre as duas linhas finas.
struct Cell { lv_obj_t* name = nullptr; lv_obj_t* value = nullptr; };
struct {
  Chrome chrome; Cell cells[4];
  lv_obj_t* battery = nullptr; lv_obj_t* soc = nullptr; lv_obj_t* bar = nullptr;
} h;
constexpr int kCardX = 439, kCardW = 311, kRowTop = 340, kRowBottom = 432;
// Energia e potência são curtas; valor/teto e tempo ganham a largura para caber na Bold 30.
constexpr int kCellX[] = {0, 140, 280, 496}, kCellW[] = {140, 140, 216, 215};

lv_obj_t* hairline(lv_obj_t* root, int y) {
  lv_obj_t* line = block(root, t::kMargin, y, 711, 1);
  lv_obj_set_style_radius(line, 0, 0);
  lv_obj_set_style_bg_color(line, t::disabled(), 0);
  return line;
}

void create(lv_obj_t* root, const kiosk::KioskView&) {
  chrome(root, h.chrome);
  h.chrome.flow = false;
  setHidden(h.chrome.panel, true); setHidden(h.chrome.step, true);
  lv_obj_set_style_text_font(h.chrome.title, t::big(), 0);
  lv_obj_set_pos(h.chrome.title, t::kMargin, 112); lv_obj_set_width(h.chrome.title, 390);
  lv_obj_set_width(h.chrome.subtitle, 350);
  lv_obj_set_width(h.chrome.context, 350);

  h.battery = block(root, kCardX, 112, kCardW, 146);
  lv_obj_set_style_radius(h.battery, 16, 0);
  lv_obj_set_style_bg_color(h.battery, LV_COLOR_MAKE(0x20, 0x44, 0x30), 0);
  lv_obj_set_style_bg_grad_color(h.battery, LV_COLOR_MAKE(0x18, 0x1C, 0x20), 0);
  lv_obj_set_style_bg_grad_dir(h.battery, LV_GRAD_DIR_VER, 0);
  lv_obj_set_style_border_width(h.battery, 1, 0);
  lv_obj_set_style_border_color(h.battery, LV_COLOR_MAKE(0x2C, 0x48, 0x38), 0);
  lv_obj_t* caption = text(h.battery, t::caption(), t::soft(), 24, 20, 263, LV_TEXT_ALIGN_LEFT);
  lv_obj_set_style_text_letter_space(caption, 3, 0);
  lv_label_set_text(caption, "BATERIA DO VEÍCULO");
  h.soc = text(h.battery, &chargegrid_code_72, t::text(), 22, 34, 263, LV_TEXT_ALIGN_LEFT);
  h.bar = lv_bar_create(h.battery);
  lv_obj_set_pos(h.bar, 24, 122); lv_obj_set_size(h.bar, 263, 8);
  lv_bar_set_range(h.bar, 0, 100);
  lv_obj_set_style_bg_color(h.bar, LV_COLOR_MAKE(0x28, 0x34, 0x30), LV_PART_MAIN);
  lv_obj_set_style_bg_color(h.bar, t::green(), LV_PART_INDICATOR);

  hairline(root, kRowTop); hairline(root, kRowBottom);
  for (int i = 0; i < 4; ++i) {
    const int x = t::kMargin + 8 + kCellX[i];
    h.cells[i].name = text(root, t::caption(), t::muted(), x, kRowTop + 18, kCellW[i] - 12, LV_TEXT_ALIGN_LEFT);
    lv_obj_set_style_text_letter_space(h.cells[i].name, 2, 0);
    h.cells[i].value = text(root, t::brand(), t::text(), x, kRowTop + 42, kCellW[i] - 12, LV_TEXT_ALIGN_LEFT);
    lv_label_set_long_mode(h.cells[i].value, LV_LABEL_LONG_DOT);
  }
  lv_obj_set_style_bg_color(h.chrome.primary, t::red(), 0);
  lv_obj_set_style_text_color(lv_obj_get_child(h.chrome.primary, 0), t::text(), 0);
}

void update(const kiosk::KioskView& view) {
  updateChrome(h.chrome, view);
  // Confirmar o encerramento: o cartão da bateria dá lugar a "Não" e "Sim, encerrar".
  const bool confirm = view.secondary.visible;
  const bool soc = view.socPercent >= 0 && !confirm;
  if (confirm) {
    // A pergunta vira o título; o detalhe (contexto) entra no lugar da dica.
    const bool app = strcmp(view.context, kiosk::str::kConfirmAppDetail) == 0;
    setText(h.chrome.title, app ? kiosk::str::kConfirmAppTitle : kiosk::str::kConfirmTitle);
    setText(h.chrome.subtitle, view.context);
    setText(h.chrome.context, "");
  }
  setHidden(h.battery, !soc);
  if (soc) {
    char shown[8];
    const int percent = view.socPercent >= 100 ? 100 : static_cast<int>(view.socPercent);
    snprintf(shown, sizeof(shown), "%d%%", percent);
    setText(h.soc, shown);
    lv_bar_set_value(h.bar, percent, LV_ANIM_OFF);
  }
  // Sem bateria conhecida o Encerrar sobe e cresce, como no painel.
  lv_obj_set_pos(h.chrome.primary, kCardX, confirm ? 264 : soc ? 270 : 188);
  lv_obj_set_size(h.chrome.primary, kCardW, soc ? 56 : 64);
  if (confirm) {
    lv_obj_set_pos(h.chrome.secondary, kCardX, 188);
    lv_obj_set_size(h.chrome.secondary, kCardW, 64);
  }
  for (lv_obj_t* btn : {h.chrome.primary, h.chrome.secondary}) {
    lv_obj_set_width(lv_obj_get_child(btn, 0), kCardW - 16);
    lv_obj_center(lv_obj_get_child(btn, 0));
  }
  // Subtítulo e motivo da potência logo abaixo do título (que pode ter duas linhas).
  lv_obj_update_layout(h.chrome.title);
  const int below = 112 + lv_obj_get_height(h.chrome.title) + 14;
  lv_obj_set_y(h.chrome.subtitle, below);
  lv_obj_update_layout(h.chrome.subtitle);
  lv_obj_set_y(h.chrome.context, below + lv_obj_get_height(h.chrome.subtitle) + 8);
  for (int i = 0; i < 4; ++i) {
    const bool shown = i < view.metricCount;
    setHidden(h.cells[i].name, !shown); setHidden(h.cells[i].value, !shown);
    if (!shown) continue;
    setText(h.cells[i].name, view.metrics[i].name);
    // Valores da API podem ter glifos fora da Bold ou não caber: cai para a Medium.
    lv_point_t size;
    lv_txt_get_size(&size, view.metrics[i].value, t::brand(), 0, 0, LV_COORD_MAX, LV_TEXT_FLAG_NONE);
    const lv_font_t* font = boldCovers(view.metrics[i].value) && size.x <= kCellW[i] - 12 ? t::brand() : t::bodyLarge();
    if (lv_obj_get_style_text_font(h.cells[i].value, 0) != font) lv_obj_set_style_text_font(h.cells[i].value, font, 0);
    setText(h.cells[i].value, view.metrics[i].value);
  }
}
void destroy() { h = {}; }
} const ViewOps viewLive = {view_live::create, view_live::update, view_live::destroy}; }
#endif
