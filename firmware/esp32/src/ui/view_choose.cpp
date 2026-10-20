#ifdef CHARGEGRID_KIOSK
// T1 Como cobrar: por valor, por tempo ou por energia.
#include "ui/router.h"
#include "ui/strings_ptbr.h"
#include "ui/tokens.h"
#include "ui/widgets.h"

namespace ui {
namespace view_choose {
namespace t = tokens;
struct { Chrome chrome; lv_obj_t* options[3]{}; } h;

void create(lv_obj_t* root, const kiosk::KioskView&) {
  chrome(root, h.chrome);
  static const char* hints[] = {kiosk::str::kModeValueHint, kiosk::str::kModeTimeHint, kiosk::str::kModeEnergyHint};
  const int width = (t::kScreenW - 2 * t::kMargin - 2 * t::kGap) / 3;
  for (int i = 0; i < 3; ++i) {
    h.options[i] = button(root, t::kMargin + i * (width + t::kGap), 176, width, 180, ButtonStyle::Option);
    lv_obj_t* hint = lv_label_create(h.options[i]);
    lv_label_set_text(hint, hints[i]);
    lv_obj_set_style_text_font(hint, t::small(), 0);
    lv_obj_set_style_text_color(hint, t::muted(), 0);
    lv_obj_set_style_text_align(hint, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_width(hint, width - 24);
    lv_obj_align(hint, LV_ALIGN_BOTTOM_MID, 0, -18);
  }
}
void update(const kiosk::KioskView& view) {
  updateChrome(h.chrome, view);
  for (int i = 0; i < 3; ++i) setButton(h.options[i], view.options[i]);
}
void destroy() { h = {}; }
}  // namespace view_choose
const ViewOps viewChoose = {view_choose::create, view_choose::update, view_choose::destroy};
}  // namespace ui
#endif
