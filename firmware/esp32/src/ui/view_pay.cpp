#ifdef CHARGEGRID_KIOSK
#include "ui/router.h"
#include "ui/tokens.h"
#include "ui/widgets.h"
namespace ui { namespace view_pay {
namespace t = tokens;
struct { Chrome chrome; lv_obj_t* amount = nullptr; Qr qr; } h;
void create(lv_obj_t* root, const kiosk::KioskView& view) {
  chrome(root, h.chrome);
  h.amount = text(root, t::body(), t::muted(), t::kFormX, view.qr[0] ? 326 : 206, t::kFormW);
  h.qr = qr(root, t::kFormX + (t::kFormW - 200) / 2, 146, 176);
}
void update(const kiosk::KioskView& view) {
  updateChrome(h.chrome, view);
  setQr(h.qr, view.qr, view.qrCaption);
  setText(h.amount, "Preparando pagamento...");
  setHidden(h.amount, view.qr[0]);
  lv_obj_set_y(h.amount, view.qr[0] ? 326 : 206);
}
void destroy() { h = {}; }
} const ViewOps viewPay = {view_pay::create, view_pay::update, view_pay::destroy}; }
#endif
