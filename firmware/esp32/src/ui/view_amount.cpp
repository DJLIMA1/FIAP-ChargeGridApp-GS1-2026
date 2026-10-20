#ifdef CHARGEGRID_KIOSK
// T2 Quanto: atalhos + "Outro valor" com teclado numérico (vírgula só em kWh).
#include <stdio.h>
#include "ui/router.h"
#include "ui/strings_ptbr.h"
#include "ui/tokens.h"
#include "ui/widgets.h"

namespace ui {
namespace view_amount {
namespace t = tokens;
struct {
  Chrome chrome;
  lv_obj_t* shortcuts[kiosk::kShortcuts]{};
  lv_obj_t* entryBox = nullptr; lv_obj_t* entry = nullptr; lv_obj_t* pad = nullptr; lv_obj_t* clear = nullptr;
  bool keypad = false;
} h;

void clearClicked(lv_event_t*) { pushKey('C'); }

void buildShortcuts(lv_obj_t* root) {
  const int width = (t::kScreenW - 2 * t::kMargin - 3 * t::kGap) / 4;
  for (size_t i = 0; i < kiosk::kShortcuts; ++i)
    h.shortcuts[i] = button(root, t::kMargin + static_cast<int>(i) * (width + t::kGap), 180, width, 120, ButtonStyle::Option);
}
void buildKeypad(lv_obj_t* root) {
  h.entryBox = block(root, t::kMargin, t::kContentY, 360, 88);
  h.entry = text(h.entryBox, t::big(), t::text(), 0, 16, 360);
  h.pad = keypad(root, 430, 150);
  h.clear = lv_btn_create(root);
  lv_obj_set_pos(h.clear, t::kMargin, 300); lv_obj_set_size(h.clear, 360, t::kMinTarget);
  lv_obj_set_style_bg_color(h.clear, t::control(), 0);
  lv_obj_set_style_radius(h.clear, t::kRadius, 0);
  lv_obj_set_style_shadow_width(h.clear, 0, 0);
  lv_obj_add_event_cb(h.clear, clearClicked, LV_EVENT_CLICKED, nullptr);
  lv_obj_t* label = lv_label_create(h.clear);
  lv_label_set_text(label, kiosk::str::kKeypadClear);
  lv_obj_set_style_text_font(label, t::button(), 0);
  lv_obj_set_style_text_color(label, t::text(), 0);
  lv_obj_center(label);
}
// Atalhos e teclado nunca existem juntos (memória): troca destrói um e cria o outro.
void layout(const kiosk::KioskView& view) {
  if (view.keypad == h.keypad && (h.shortcuts[0] || h.pad)) return;
  h.keypad = view.keypad;
  for (auto& shortcut : h.shortcuts) if (shortcut) { lv_obj_del(shortcut); shortcut = nullptr; }
  for (lv_obj_t** obj : {&h.entryBox, &h.pad, &h.clear}) if (*obj) { lv_obj_del(*obj); *obj = nullptr; }
  h.entry = nullptr;
  if (view.keypad) buildKeypad(h.chrome.root); else buildShortcuts(h.chrome.root);
  lv_obj_move_foreground(h.chrome.notice);
}

void create(lv_obj_t* root, const kiosk::KioskView& view) {
  chrome(root, h.chrome);
  h.keypad = !view.keypad;   // força layout()
  layout(view);
}
void update(const kiosk::KioskView& view) {
  layout(view);
  updateChrome(h.chrome, view);
  if (view.keypad) {
    char shown[32];
    if (view.entry[0]) {
      if (view.entryUnit[0] == 'R') snprintf(shown, sizeof(shown), "R$ %s", view.entry);
      else snprintf(shown, sizeof(shown), "%s %s", view.entry, view.entryUnit);
    } else snprintf(shown, sizeof(shown), "%s", view.entryUnit);
    setText(h.entry, shown);
    setKeypadDecimal(h.pad, view.decimalKey);
    // Barra à esquerda do teclado: Voltar + OK.
    lv_obj_set_pos(h.chrome.secondary, t::kMargin, t::kBarY); lv_obj_set_width(h.chrome.secondary, 170);
    lv_obj_set_pos(h.chrome.primary, t::kMargin + 170 + t::kGap, t::kBarY); lv_obj_set_width(h.chrome.primary, 174);
    lv_obj_set_width(lv_obj_get_child(h.chrome.primary, 0), 158);
    lv_obj_center(lv_obj_get_child(h.chrome.primary, 0));
    lv_obj_set_width(lv_obj_get_child(h.chrome.secondary, 0), 154);
    lv_obj_set_pos(h.chrome.notice, t::kMargin, 254); lv_obj_set_width(h.chrome.notice, 360);
  } else {
    for (size_t i = 0; i < kiosk::kShortcuts; ++i) setButton(h.shortcuts[i], view.options[i]);
    lv_obj_set_pos(h.chrome.notice, t::kMargin, 320); lv_obj_set_width(h.chrome.notice, t::kScreenW - 2 * t::kMargin);
  }
}
void destroy() { h = {}; }
}  // namespace view_amount
const ViewOps viewAmount = {view_amount::create, view_amount::update, view_amount::destroy};
}  // namespace ui
#endif
