#ifdef CHARGEGRID_KIOSK
// T8 Recibo: motivo, kWh, total, devolvido/simulado, número e QR do recibo completo.
// Com permanência: contagem/taxa e Desconectar (mesmas regras da tela atual).
#include "ui/router.h"
#include "ui/tokens.h"
#include "ui/widgets.h"

namespace ui {
namespace view_receipt {
namespace t = tokens;
struct { Chrome chrome; Metric metrics[4]; Qr qr; } h;

void create(lv_obj_t* root, const kiosk::KioskView&) {
  chrome(root, h.chrome);
  lv_obj_set_width(h.chrome.title, 470);
  lv_obj_set_width(h.chrome.subtitle, 470);
  lv_obj_set_style_text_align(h.chrome.title, LV_TEXT_ALIGN_LEFT, 0);
  lv_obj_set_style_text_align(h.chrome.subtitle, LV_TEXT_ALIGN_LEFT, 0);
  lv_obj_set_pos(h.chrome.notice, t::kMargin, 318);
  lv_obj_set_width(h.chrome.notice, 470);
  lv_obj_set_style_text_align(h.chrome.notice, LV_TEXT_ALIGN_LEFT, 0);
  lv_obj_set_style_bg_color(h.chrome.secondary, t::text(), 0);
  lv_obj_set_style_text_color(lv_obj_get_child(h.chrome.secondary, 0), t::ink(), 0);
  const int width = (470 - t::kGap) / 2;
  for (int i = 0; i < 4; ++i)
    h.metrics[i] = metric(root, t::kMargin + (i % 2) * (width + t::kGap), t::kContentY + (i / 2) * 76, width, 68);
  h.qr = qr(root, 536, 88, 200);
}
void update(const kiosk::KioskView& view) {
  updateChrome(h.chrome, view);
  for (int i = 0; i < 4; ++i) setMetric(h.metrics[i], i < view.metricCount ? &view.metrics[i] : nullptr);
  setQr(h.qr, view.qr, view.qrCaption);
}
void destroy() { h = {}; }
}  // namespace view_receipt
const ViewOps viewReceipt = {view_receipt::create, view_receipt::update, view_receipt::destroy};
}  // namespace ui
#endif
