#ifdef CHARGEGRID_KIOSK
#include <stdio.h>
#include "ui/router.h"
#include "ui/tokens.h"
#include "ui/widgets.h"
namespace ui { namespace view_amount {
namespace t = tokens;
struct { Chrome chrome; lv_obj_t* shortcuts[4]{}; lv_obj_t* entry = nullptr; lv_obj_t* pad = nullptr; } h;
void create(lv_obj_t* root, const kiosk::KioskView& view) {
  chrome(root, h.chrome);
  h.entry = text(root, t::big(), t::text(), t::kMargin, 318, t::kLeftW, LV_TEXT_ALIGN_LEFT);
  if (view.keypad) h.pad = keypad(root, t::kFormX - 2, t::kCardY + 14);
  else for (int i = 0; i < 4; ++i)
    h.shortcuts[i] = button(root, t::kFormX + i % 2 * t::kColStep, 160 + i / 2 * 94, t::kColW, 78, ButtonStyle::Option);
}
void update(const kiosk::KioskView& view) {
  // The router recreates Amount when the keypad mode changes.
  updateChrome(h.chrome, view);
  setHidden(h.chrome.context, view.keypad);
  setHidden(h.chrome.step, view.keypad);   // o teclado ocupa o cartão inteiro
  if (view.keypad) {
    char shown[48]; snprintf(shown, sizeof(shown), "%s %s", view.entry[0] ? view.entry : "0", view.entryUnit);
    setText(h.entry, shown); setKeypadDecimal(h.pad, view.decimalKey);
  } else for (int i = 0; i < 4; ++i) setButton(h.shortcuts[i], view.options[i]);
}
void destroy() { h = {}; }
} const ViewOps viewAmount = {view_amount::create, view_amount::update, view_amount::destroy}; }
#endif
