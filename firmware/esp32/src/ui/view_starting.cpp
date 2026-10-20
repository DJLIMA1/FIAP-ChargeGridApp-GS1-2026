#ifdef CHARGEGRID_KIOSK
// T5 Iniciando: pagamento confirmado, aguardando o START do servidor (até 60 s).
#include "ui/router.h"
#include "ui/tokens.h"
#include "ui/widgets.h"

namespace ui {
namespace view_starting {
namespace t = tokens;
struct { Chrome chrome; lv_obj_t* mark = nullptr; } h;

void create(lv_obj_t* root, const kiosk::KioskView&) {
  chrome(root, h.chrome);
  h.mark = block(root, 360, 150, 80, 80);
  lv_obj_set_style_radius(h.mark, LV_RADIUS_CIRCLE, 0);
  lv_obj_set_style_bg_color(h.mark, t::green(), 0);
  lv_obj_set_pos(h.chrome.title, t::kMargin, 250);
  lv_obj_set_pos(h.chrome.subtitle, t::kMargin, 300);
}
void update(const kiosk::KioskView& view) { updateChrome(h.chrome, view); }
void destroy() { h = {}; }
}  // namespace view_starting
const ViewOps viewStarting = {view_starting::create, view_starting::update, view_starting::destroy};
}  // namespace ui
#endif
