#ifdef CHARGEGRID_KIOSK
#include "ui/router.h"
#include "ui/tokens.h"
#include "ui/widgets.h"
namespace ui { namespace view_review {
namespace t = tokens;
struct { Chrome chrome; Metric metrics[6]; } h;
void create(lv_obj_t* root, const kiosk::KioskView&) {
  chrome(root, h.chrome);
  for (int i = 0; i < 6; ++i)
    h.metrics[i] = metric(root, t::kFormX + i % 2 * t::kColStep, 150 + i / 2 * 76, t::kColW, 70);
}
void update(const kiosk::KioskView& view) {
  updateChrome(h.chrome, view);
  for (int i = 0; i < 6; ++i) setMetric(h.metrics[i], i < view.metricCount ? &view.metrics[i] : nullptr);
}
void destroy() { h = {}; }
} const ViewOps viewReview = {view_review::create, view_review::update, view_review::destroy}; }
#endif
