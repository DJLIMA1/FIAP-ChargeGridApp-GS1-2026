#ifdef CHARGEGRID_KIOSK
// T7 Confirmar encerramento (também para recarga iniciada pelo app). Volta sozinho em 10 s.
#include "ui/router.h"
#include "ui/tokens.h"
#include "ui/widgets.h"

namespace ui {
namespace view_confirm_stop {
namespace t = tokens;
struct { Chrome chrome; } h;

void create(lv_obj_t* root, const kiosk::KioskView&) {
  chrome(root, h.chrome);
  lv_obj_set_pos(h.chrome.title, t::kMargin, 170);
  lv_obj_set_pos(h.chrome.subtitle, t::kMargin, 226);
  lv_obj_set_style_bg_color(h.chrome.primary, t::red(), 0);
  lv_obj_set_style_text_color(lv_obj_get_child(h.chrome.primary, 0), t::text(), 0);
}
void update(const kiosk::KioskView& view) { updateChrome(h.chrome, view); }
void destroy() { h = {}; }
}  // namespace view_confirm_stop
const ViewOps viewConfirmStop = {view_confirm_stop::create, view_confirm_stop::update, view_confirm_stop::destroy};
}  // namespace ui
#endif
