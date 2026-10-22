#ifdef CHARGEGRID_KIOSK
#include "ui/router.h"
#include "ui/tokens.h"
#include "ui/widgets.h"
namespace ui {
namespace view_choose {
namespace t = tokens;
struct { Chrome chrome; lv_obj_t* options[4]{}; } h;
void create(lv_obj_t* root, const kiosk::KioskView&) {
  chrome(root, h.chrome);
  for (int i = 0; i < 4; ++i) {
    h.options[i] = button(root, t::kFormX, 150 + i * 56, t::kFormW, 52, ButtonStyle::Option);
    lv_obj_set_style_text_align(lv_obj_get_child(h.options[i], 0), LV_TEXT_ALIGN_LEFT, 0);
  }
}
void update(const kiosk::KioskView& view) {
  updateChrome(h.chrome, view);
  int count = 0;
  for (int i = 0; i < 4; ++i) if (view.options[i].visible) ++count;
  int row = 0;
  for (int i = 0; i < 4; ++i) {
    setButton(h.options[i], view.options[i]);
    if (view.options[i].visible) lv_obj_set_y(h.options[i], (count < 4 ? 158 : 150) + row++ * (count < 4 ? 66 : 56));
  }
}
void destroy() { h = {}; }
}
const ViewOps viewChoose = {view_choose::create, view_choose::update, view_choose::destroy};
}
#endif
