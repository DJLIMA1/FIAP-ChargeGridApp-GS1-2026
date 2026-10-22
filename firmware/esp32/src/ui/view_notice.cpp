#ifdef CHARGEGRID_KIOSK
// TE bloqueios/erros e "Verificando pagamento" (retomada pelo sync).
#include "ui/router.h"
#include "ui/tokens.h"
#include "ui/widgets.h"

namespace ui {
namespace view_notice {
namespace t = tokens;
struct { Chrome chrome; lv_obj_t* mark = nullptr; } h;

void create(lv_obj_t* root, const kiosk::KioskView&) {
  chrome(root, h.chrome);
  h.mark = block(root, t::kCardX + (t::kCardW - 60) / 2, 220, 60, 60);
  lv_obj_set_style_radius(h.mark, LV_RADIUS_CIRCLE, 0);
}
void update(const kiosk::KioskView& view) {
  updateChrome(h.chrome, view);
  const lv_color_t tones[] = {t::muted(), t::amber(), t::green(), t::red()};
  lv_obj_set_style_bg_color(h.mark, tones[static_cast<int>(view.tone) & 3], 0);
}
void destroy() { h = {}; }
}  // namespace view_notice
const ViewOps viewNotice = {view_notice::create, view_notice::update, view_notice::destroy};
}  // namespace ui
#endif
