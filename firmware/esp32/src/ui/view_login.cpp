#ifdef CHARGEGRID_KIOSK
#include <string.h>
#include "ui/router.h"
#include "ui/tokens.h"
#include "ui/widgets.h"

namespace ui { namespace view_login {
namespace t = tokens;
struct { Chrome chrome; lv_obj_t* entry = nullptr; lv_obj_t* keyboard = nullptr; bool upper = false, symbols = false; } h;
static const char* lower[] = {
  "1","2","3","4","5","6","7","8","9","0","\n",
  "q","w","e","r","t","y","u","i","o","p","\n",
  "a","s","d","f","g","h","j","k","l","@","\n",
  "z","x","c","v","b","n","m",".","-","_","\n",
  "Maiús.","Símbolos","Espaço","Apagar",""};
static const char* upper[] = {
  "1","2","3","4","5","6","7","8","9","0","\n",
  "Q","W","E","R","T","Y","U","I","O","P","\n",
  "A","S","D","F","G","H","J","K","L","@","\n",
  "Z","X","C","V","B","N","M",".","-","_","\n",
  "Minús.","Símbolos","Espaço","Apagar",""};
static const char* symbols[] = {
  "!","@","#","$","%","^","&","*","(",")","\n",
  "-","_","=","+","[","]","{","}",";",":","\n",
  "'","\"",",",".","/","?","\\","|","~","`","\n",
  "1","2","3","4","5","6","7","8","<",">","\n",
  "Letras","Espaço","Apagar",""};
void keyboardMap() {
  lv_btnmatrix_set_map(h.keyboard, h.symbols ? symbols : h.upper ? upper : lower);
  const uint16_t start = 40;
  for (uint16_t i = start; i < (h.symbols ? 43 : 44); ++i)
    lv_btnmatrix_set_btn_width(h.keyboard, i, i == start + (h.symbols ? 1 : 2) ? 4 : 2);
}
void clicked(lv_event_t*) {
  const uint16_t id = lv_btnmatrix_get_selected_btn(h.keyboard);
  const char* key = lv_btnmatrix_get_btn_text(h.keyboard, id);
  if (!key) return;
  if (!strcmp(key, "Maiús.") || !strcmp(key, "Minús.")) { h.upper = !h.upper; keyboardMap(); }
  else if (!strcmp(key, "Símbolos") || !strcmp(key, "Letras")) { h.symbols = !h.symbols; keyboardMap(); }
  else if (!strcmp(key, "Apagar")) pushKey('\b');
  else if (!strcmp(key, "Espaço")) pushKey(' ');
  else if (strlen(key) == 1) pushKey(key[0]);
}
void create(lv_obj_t* root, const kiosk::KioskView&) {
  chrome(root, h.chrome);
  h.chrome.flow = false;
  setHidden(h.chrome.panel, true);
  setHidden(h.chrome.step, true); setHidden(h.chrome.context, true);
  lv_obj_set_pos(h.chrome.title, t::kMargin, 92); lv_obj_set_width(h.chrome.title, 560);
  lv_obj_set_pos(h.chrome.subtitle, t::kMargin, 136); lv_obj_set_width(h.chrome.subtitle, 560);
  lv_obj_set_pos(h.chrome.notice, t::kMargin, 218); lv_obj_set_width(h.chrome.notice, 711);
  block(root, t::kMargin, 174, 555, 42);
  h.entry = text(root, t::bodyLarge(), t::text(), t::kMargin + 12, 182, 530, LV_TEXT_ALIGN_LEFT);
  lv_label_set_long_mode(h.entry, LV_LABEL_LONG_DOT); lv_obj_set_height(h.entry, 28);
  h.keyboard = lv_btnmatrix_create(root);
  lv_obj_set_pos(h.keyboard, t::kMargin, 248); lv_obj_set_size(h.keyboard, 711, 216);
  lv_obj_set_style_bg_color(h.keyboard, t::bg(), 0);
  lv_obj_set_style_border_width(h.keyboard, 0, 0); lv_obj_set_style_pad_all(h.keyboard, 0, 0);
  lv_obj_set_style_pad_row(h.keyboard, 6, 0); lv_obj_set_style_pad_column(h.keyboard, 6, 0);
  lv_obj_set_style_bg_color(h.keyboard, t::control(), LV_PART_ITEMS);
  lv_obj_set_style_text_color(h.keyboard, t::text(), LV_PART_ITEMS);
  lv_obj_set_style_text_font(h.keyboard, t::bodyLarge(), LV_PART_ITEMS);
  lv_obj_set_style_shadow_width(h.keyboard, 0, LV_PART_ITEMS);
  lv_obj_set_style_radius(h.keyboard, 8, LV_PART_ITEMS);
  keyboardMap(); lv_obj_add_event_cb(h.keyboard, clicked, LV_EVENT_VALUE_CHANGED, nullptr);
}
void update(const kiosk::KioskView& view) {
  updateChrome(h.chrome, view);
  setHidden(h.chrome.badge, true);
  lv_obj_set_pos(h.chrome.primary, 606, 174); lv_obj_set_width(h.chrome.primary, 144);
  lv_obj_set_pos(h.chrome.secondary, 606, 104); lv_obj_set_width(h.chrome.secondary, 144);
  for (lv_obj_t* btn : {h.chrome.primary, h.chrome.secondary}) {
    lv_obj_set_width(lv_obj_get_child(btn, 0), 128); lv_obj_center(lv_obj_get_child(btn, 0));
  }
  setText(h.entry, view.loginEntry[0] ? view.loginEntry : view.password ? "Sua senha" : "Seu e-mail");
  if (view.busy) lv_obj_add_state(h.keyboard, LV_STATE_DISABLED);
  else lv_obj_clear_state(h.keyboard, LV_STATE_DISABLED);
}
void destroy() { h = {}; }
} const ViewOps viewLogin = {view_login::create, view_login::update, view_login::destroy}; }
#endif
