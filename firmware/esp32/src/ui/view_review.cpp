#ifdef CHARGEGRID_KIOSK
// T3 Revisar e aceitar: preço travado, demanda, valor máximo, estimativas e permanência.
#include "ui/router.h"
#include "ui/tokens.h"
#include "ui/widgets.h"

namespace ui {
namespace view_review {
namespace t = tokens;
struct { Chrome chrome; Metric metrics[6]; } h;

void create(lv_obj_t* root, const kiosk::KioskView&) {
  chrome(root, h.chrome);
  const int width = (t::kScreenW - 2 * t::kMargin - t::kGap) / 2;
  for (int i = 0; i < 6; ++i)
    h.metrics[i] = metric(root, t::kMargin + (i % 2) * (width + t::kGap), t::kContentY + (i / 2) * 66, width, 60);
}
void update(const kiosk::KioskView& view) {
  updateChrome(h.chrome, view);
  for (int i = 0; i < 6; ++i) setMetric(h.metrics[i], i < view.metricCount ? &view.metrics[i] : nullptr);
}
void destroy() { h = {}; }
}  // namespace view_review
const ViewOps viewReview = {view_review::create, view_review::update, view_review::destroy};
}  // namespace ui
#endif
