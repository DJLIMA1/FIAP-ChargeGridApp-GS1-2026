#ifdef CHARGEGRID_KIOSK
// T4 Pagamento: simulado (botão "Simular pagamento") ou Stripe (QR do pedido), conforme o
// método decidido pelo servidor.
#include "ui/router.h"
#include "ui/tokens.h"
#include "ui/widgets.h"

namespace ui {
namespace view_pay {
namespace t = tokens;
struct { Chrome chrome; lv_obj_t* amount = nullptr; Qr qr; } h;

void create(lv_obj_t* root, const kiosk::KioskView&) {
  chrome(root, h.chrome);
  h.amount = text(root, t::big(), t::text(), t::kMargin, 200, t::kScreenW - 2 * t::kMargin);
  h.qr = qr(root, 536, 88, 200);
}
void update(const kiosk::KioskView& view) {
  updateChrome(h.chrome, view);
  const bool withQr = view.qr[0] != '\0';
  setQr(h.qr, view.qr, view.qrCaption);
  setText(h.amount, view.metricCount ? view.metrics[0].value : "");
  const int left = withQr ? 470 : t::kScreenW - 2 * t::kMargin;
  lv_obj_set_width(h.chrome.title, left);
  lv_obj_set_width(h.chrome.subtitle, left);
  lv_obj_set_width(h.amount, left);
  lv_obj_set_pos(h.chrome.notice, t::kMargin, withQr ? 290 : 300);
  lv_obj_set_width(h.chrome.notice, left);
  lv_obj_set_style_text_align(h.chrome.title, withQr ? LV_TEXT_ALIGN_LEFT : LV_TEXT_ALIGN_CENTER, 0);
  lv_obj_set_style_text_align(h.chrome.subtitle, withQr ? LV_TEXT_ALIGN_LEFT : LV_TEXT_ALIGN_CENTER, 0);
  lv_obj_set_style_text_align(h.amount, withQr ? LV_TEXT_ALIGN_LEFT : LV_TEXT_ALIGN_CENTER, 0);
  lv_obj_set_style_text_align(h.chrome.notice, withQr ? LV_TEXT_ALIGN_LEFT : LV_TEXT_ALIGN_CENTER, 0);
}
void destroy() { h = {}; }
}  // namespace view_pay
const ViewOps viewPay = {view_pay::create, view_pay::update, view_pay::destroy};
}  // namespace ui
#endif
