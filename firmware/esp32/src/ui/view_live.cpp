#ifdef CHARGEGRID_KIOSK
// T6 Ao vivo: energia, potência aplicada + motivo, custo/teto, tempo, bateria; Encerrar.
#include "ui/router.h"
#include "ui/tokens.h"
#include "ui/widgets.h"

namespace ui {
namespace view_live {
namespace t = tokens;
struct { Chrome chrome; Metric metrics[6]; } h;

void create(lv_obj_t* root, const kiosk::KioskView&) {
  chrome(root, h.chrome);
  lv_obj_set_style_bg_color(h.chrome.primary, t::red(), 0);
  lv_obj_set_style_text_color(lv_obj_get_child(h.chrome.primary, 0), t::text(), 0);
  const int width = (t::kScreenW - 2 * t::kMargin - 2 * t::kGap) / 3;
  for (int i = 0; i < 6; ++i)
    h.metrics[i] = metric(root, t::kMargin + (i % 3) * (width + t::kGap), t::kContentY + (i / 3) * 96, width, 84);
}
void update(const kiosk::KioskView& view) {
  updateChrome(h.chrome, view);
  for (int i = 0; i < 6; ++i) setMetric(h.metrics[i], i < view.metricCount ? &view.metrics[i] : nullptr);
}
void destroy() { h = {}; }
}  // namespace view_live
const ViewOps viewLive = {view_live::create, view_live::update, view_live::destroy};
}  // namespace ui
#endif
