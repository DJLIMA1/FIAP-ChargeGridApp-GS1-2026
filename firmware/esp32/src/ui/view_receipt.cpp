#ifdef CHARGEGRID_KIOSK
#include "ui/router.h"
#include "ui/tokens.h"
#include "ui/widgets.h"
namespace ui { namespace view_receipt {
namespace t = tokens;
struct { Chrome chrome; Metric metrics[4]; Qr qr; } h;
void create(lv_obj_t* root, const kiosk::KioskView&) {
  chrome(root, h.chrome);
  h.chrome.flow = false;
  lv_obj_set_y(h.chrome.title, 150); lv_obj_set_y(h.chrome.subtitle, 222);
  for (int i = 0; i < 4; ++i) h.metrics[i] = metric(root, t::kMargin + i % 2 * t::kColStep, 284 + i / 2 * 60, t::kColW, 54);
  h.qr = qr(root, t::kFormX + (t::kFormW - 200) / 2, 146, 176);
}
void update(const kiosk::KioskView& view) {
  updateChrome(h.chrome, view);
  setHidden(h.chrome.context, true);
  if (view.secondary.visible) {
    // Two complete touch targets: "Desconectar" must never wrap into the footer.
    const int half = (t::kFormW - 12) / 2;
    lv_obj_set_width(h.chrome.secondary, half);
    lv_obj_set_pos(h.chrome.primary, t::kFormX + half + 12, t::kBarY);
    lv_obj_set_width(h.chrome.primary, half);
    for (lv_obj_t* button : {h.chrome.secondary, h.chrome.primary})
      lv_obj_set_width(lv_obj_get_child(button, 0), half - 16);
    setButton(h.chrome.secondary, view.secondary);
    setButton(h.chrome.primary, view.primary);
  }
  for (int i = 0; i < 4; ++i) {
    // Com QR: 2x2 na coluna do título. Sem QR: 2x2 dentro do cartão, mais altas.
    if (view.qr[0]) resizeMetric(h.metrics[i], 167, 54);
    else resizeMetric(h.metrics[i], t::kColW, 70);
    lv_obj_set_pos(h.metrics[i].box, view.qr[0] ? t::kMargin + i % 2 * 183 : t::kFormX + i % 2 * t::kColStep,
                   view.qr[0] ? 284 + i / 2 * 60 : 150 + i / 2 * 80);
    setMetric(h.metrics[i], i < view.metricCount ? &view.metrics[i] : nullptr);
  }
  setQr(h.qr, view.qr, view.qrCaption);
  lv_obj_set_y(h.chrome.notice, view.qr[0] ? 404 : 290);
}
void destroy() { h = {}; }
} const ViewOps viewReceipt = {view_receipt::create, view_receipt::update, view_receipt::destroy}; }
#endif
