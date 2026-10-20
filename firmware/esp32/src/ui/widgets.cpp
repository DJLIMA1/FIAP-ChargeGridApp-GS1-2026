#ifdef CHARGEGRID_KIOSK
#include <string.h>
#include <stdint.h>
#include "ui/widgets.h"
#include "ui/router.h"
#include "ui/strings_ptbr.h"
#include "ui/tokens.h"

namespace ui {
namespace {
namespace t = tokens;

void plainStyle(lv_obj_t* obj) {
  lv_obj_set_style_bg_opa(obj, LV_OPA_TRANSP, 0);
  lv_obj_set_style_border_width(obj, 0, 0);
  lv_obj_set_style_radius(obj, 0, 0);
  lv_obj_set_style_pad_all(obj, 0, 0);
  lv_obj_clear_flag(obj, LV_OBJ_FLAG_SCROLLABLE);
}
void actionClicked(lv_event_t* event) {
  lv_obj_t* target = lv_event_get_current_target(event);
  if (lv_obj_has_state(target, LV_STATE_DISABLED)) return;
  pushAction(static_cast<kiosk::Action>(reinterpret_cast<uintptr_t>(lv_obj_get_user_data(target))));
}
void keyClicked(lv_event_t* event) {
  lv_obj_t* target = lv_event_get_current_target(event);
  if (lv_obj_has_state(target, LV_STATE_DISABLED)) return;
  pushKey(static_cast<char>(reinterpret_cast<uintptr_t>(lv_obj_get_user_data(target))));
}
lv_color_t fill(ButtonStyle style) {
  switch (style) {
    case ButtonStyle::Primary: return t::text();
    case ButtonStyle::Danger: return t::red();
    case ButtonStyle::Light: return t::text();
    case ButtonStyle::Option: return t::card();
    default: return t::control();
  }
}
lv_color_t ink(ButtonStyle style) {
  return style == ButtonStyle::Primary || style == ButtonStyle::Light ? t::ink() : t::text();
}
}  // namespace

bool boldCovers(const char* utf8) {
  static const uint16_t accents[] = {0xC0, 0xC1, 0xC2, 0xC3, 0xC7, 0xC9, 0xCA, 0xCD, 0xD3, 0xD4, 0xD5, 0xDA,
                                     0xE0, 0xE1, 0xE2, 0xE3, 0xE7, 0xE9, 0xEA, 0xED, 0xF3, 0xF4, 0xF5, 0xFA};
  const unsigned char* c = reinterpret_cast<const unsigned char*>(utf8 ? utf8 : "");
  while (*c) {
    uint32_t cp = *c;
    if (cp < 0x80) { if (cp < 0x20 || cp > 0x7E) return false; ++c; continue; }
    if ((cp & 0xE0) == 0xC0 && (c[1] & 0xC0) == 0x80) { cp = ((cp & 0x1F) << 6) | (c[1] & 0x3F); c += 2; }
    else return false;
    bool found = false;
    for (uint16_t accent : accents) if (accent == cp) { found = true; break; }
    if (!found) return false;
  }
  return true;
}

lv_obj_t* root(lv_obj_t* parent) {
  lv_obj_t* obj = lv_obj_create(parent);
  plainStyle(obj);
  lv_obj_set_pos(obj, 0, 0);
  lv_obj_set_size(obj, t::kScreenW, t::kScreenH);
  lv_obj_set_style_bg_opa(obj, LV_OPA_COVER, 0);
  lv_obj_set_style_bg_color(obj, t::bg(), 0);
  return obj;
}

lv_obj_t* text(lv_obj_t* parent, const lv_font_t* font, lv_color_t color, int x, int y, int width,
               lv_text_align_t align) {
  lv_obj_t* label = lv_label_create(parent);
  lv_label_set_text(label, "");
  lv_obj_set_style_text_font(label, font, 0);
  lv_obj_set_style_text_color(label, color, 0);
  lv_obj_set_style_text_align(label, align, 0);
  lv_obj_set_pos(label, x, y);
  lv_obj_set_width(label, width);
  lv_label_set_long_mode(label, LV_LABEL_LONG_WRAP);
  return label;
}

lv_obj_t* block(lv_obj_t* parent, int x, int y, int width, int height) {
  lv_obj_t* obj = lv_obj_create(parent);
  plainStyle(obj);
  lv_obj_set_pos(obj, x, y);
  lv_obj_set_size(obj, width, height);
  lv_obj_set_style_bg_opa(obj, LV_OPA_COVER, 0);
  lv_obj_set_style_bg_color(obj, t::card(), 0);
  lv_obj_set_style_radius(obj, t::kRadius, 0);
  return obj;
}

lv_obj_t* button(lv_obj_t* parent, int x, int y, int width, int height, ButtonStyle style) {
  lv_obj_t* btn = lv_btn_create(parent);
  lv_obj_set_pos(btn, x, y);
  lv_obj_set_size(btn, width, height < t::kMinTarget ? t::kMinTarget : height);
  lv_obj_set_style_bg_color(btn, fill(style), 0);
  lv_obj_set_style_bg_color(btn, t::disabled(), LV_STATE_DISABLED);
  lv_obj_set_style_radius(btn, t::kRadius, 0);
  lv_obj_set_style_shadow_width(btn, 0, 0);
  lv_obj_set_style_pad_all(btn, 8, 0);
  if (style == ButtonStyle::Option) {
    lv_obj_set_style_border_width(btn, 2, 0);
    lv_obj_set_style_border_color(btn, t::line(), 0);
  }
  lv_obj_add_event_cb(btn, actionClicked, LV_EVENT_CLICKED, nullptr);
  lv_obj_t* label = lv_label_create(btn);
  lv_label_set_text(label, "");
  lv_obj_set_style_text_font(label, t::button(), 0);
  lv_obj_set_style_text_color(label, ink(style), 0);
  lv_obj_set_style_text_color(label, t::muted(), LV_STATE_DISABLED);
  lv_obj_set_style_text_align(label, LV_TEXT_ALIGN_CENTER, 0);
  lv_obj_set_width(label, width - 16);
  lv_label_set_long_mode(label, LV_LABEL_LONG_WRAP);
  lv_obj_center(label);
  return btn;
}

void setText(lv_obj_t* label, const char* value) {
  if (!label) return;
  if (strcmp(lv_label_get_text(label), value ? value : "") != 0) lv_label_set_text(label, value ? value : "");
}

void setHidden(lv_obj_t* object, bool hidden) {
  if (!object || lv_obj_has_flag(object, LV_OBJ_FLAG_HIDDEN) == hidden) return;
  if (hidden) lv_obj_add_flag(object, LV_OBJ_FLAG_HIDDEN);
  else lv_obj_clear_flag(object, LV_OBJ_FLAG_HIDDEN);
}

void setButton(lv_obj_t* btn, const kiosk::ViewButton& model) {
  if (!btn) return;
  setHidden(btn, !model.visible);
  if (!model.visible) return;
  lv_obj_set_user_data(btn, reinterpret_cast<void*>(static_cast<uintptr_t>(model.action)));
  if (model.enabled) lv_obj_clear_state(btn, LV_STATE_DISABLED);
  else lv_obj_add_state(btn, LV_STATE_DISABLED);
  lv_obj_t* label = lv_obj_get_child(btn, 0);
  // Texto com glifo fora da Bold (ou longo demais para uma linha): Barlow Medium 22.
  lv_point_t size;
  lv_txt_get_size(&size, model.text, t::button(), 0, 0, LV_COORD_MAX, LV_TEXT_FLAG_NONE);
  // Largura pedida (estilo), não as coordenadas: na criação o layout ainda não rodou.
  const lv_coord_t width = lv_obj_get_style_width(btn, LV_PART_MAIN);
  const lv_font_t* font = boldCovers(model.text) && size.x <= width - 24 ? t::button() : t::bodyLarge();
  if (lv_obj_get_style_text_font(label, 0) != font) lv_obj_set_style_text_font(label, font, 0);
  setText(label, model.text);
  lv_obj_center(label);
}

Metric metric(lv_obj_t* parent, int x, int y, int width, int height) {
  Metric m;
  m.box = block(parent, x, y, width, height);
  m.name = text(m.box, t::caption(), t::muted(), 16, 8, width - 32, LV_TEXT_ALIGN_LEFT);
  lv_obj_set_style_text_letter_space(m.name, 2, 0);
  m.value = text(m.box, t::bodyLarge(), t::text(), 16, 28, width - 32, LV_TEXT_ALIGN_LEFT);
  lv_label_set_long_mode(m.value, LV_LABEL_LONG_DOT);
  lv_obj_set_height(m.value, height - 32);
  return m;
}

void setMetric(Metric& m, const kiosk::ViewMetric* model) {
  setHidden(m.box, model == nullptr);
  if (!model) return;
  setText(m.name, model->name);
  setText(m.value, model->value);
}

lv_obj_t* keypad(lv_obj_t* parent, int x, int y) {
  static const char keys[] = {'1', '2', '3', '4', '5', '6', '7', '8', '9', ',', '0', 'B'};
  lv_obj_t* pad = lv_obj_create(parent);
  plainStyle(pad);
  lv_obj_set_pos(pad, x, y);
  lv_obj_set_size(pad, 3 * t::kKeyWidth + 2 * 8, 4 * t::kKeyHeight + 3 * 8);
  for (int i = 0; i < 12; ++i) {
    lv_obj_t* key = lv_btn_create(pad);
    lv_obj_set_pos(key, (i % 3) * (t::kKeyWidth + 8), (i / 3) * (t::kKeyHeight + 8));
    lv_obj_set_size(key, t::kKeyWidth, t::kKeyHeight);
    lv_obj_set_style_bg_color(key, t::control(), 0);
    lv_obj_set_style_bg_color(key, t::disabled(), LV_STATE_DISABLED);
    lv_obj_set_style_radius(key, 12, 0);
    lv_obj_set_style_shadow_width(key, 0, 0);
    lv_obj_set_user_data(key, reinterpret_cast<void*>(static_cast<uintptr_t>(keys[i])));
    lv_obj_add_event_cb(key, keyClicked, LV_EVENT_CLICKED, nullptr);
    lv_obj_t* label = lv_label_create(key);
    if (keys[i] == 'B') {
      // Barlow não tem o símbolo: LV_SYMBOL_BACKSPACE da Montserrat embutida.
      lv_label_set_text(label, LV_SYMBOL_BACKSPACE);
      lv_obj_set_style_text_font(label, t::symbol(), 0);
    } else {
      const char digit[2] = {keys[i], '\0'};
      lv_label_set_text(label, digit);
      lv_obj_set_style_text_font(label, t::title(), 0);
    }
    lv_obj_set_style_text_color(label, t::text(), 0);
    lv_obj_set_style_text_color(label, t::disabled(), LV_STATE_DISABLED);
    lv_obj_center(label);
  }
  return pad;
}

void setKeypadDecimal(lv_obj_t* pad, bool decimal) {
  if (!pad) return;
  lv_obj_t* comma = lv_obj_get_child(pad, 9);
  if (decimal) lv_obj_clear_state(comma, LV_STATE_DISABLED);
  else lv_obj_add_state(comma, LV_STATE_DISABLED);
}

Qr qr(lv_obj_t* parent, int x, int y, int size) {
  Qr q;
  q.box = block(parent, x, y, size + 24, size + 24);
  lv_obj_set_style_bg_color(q.box, lv_color_white(), 0);
  q.code = lv_qrcode_create(q.box, size, lv_color_black(), lv_color_white());
  lv_obj_center(q.code);
  q.caption = text(parent, t::small(), t::soft(), x - 20, y + size + 32, size + 64);
  return q;
}

void setQr(Qr& q, const char* value, const char* caption) {
  const bool show = value && *value;
  setHidden(q.box, !show);
  setHidden(q.caption, !show);
  if (!show) return;
  if (strcmp(q.last, value) != 0 && lv_qrcode_update(q.code, value, strlen(value)) == LV_RES_OK)
    snprintf(q.last, sizeof(q.last), "%s", value);
  setText(q.caption, caption);
}

void chrome(lv_obj_t* rootObj, Chrome& c) {
  c = Chrome{};
  c.root = rootObj;
  lv_obj_t* brand = text(rootObj, t::brand(), t::text(), t::kMargin, t::kHeaderY, 300, LV_TEXT_ALIGN_LEFT);
  lv_label_set_text(brand, "ChargeGrid");
  c.badge = block(rootObj, t::kScreenW - t::kMargin - 150, t::kHeaderY, 150, 36);
  lv_obj_set_style_bg_color(c.badge, t::amber(), 0);
  lv_obj_set_style_radius(c.badge, 18, 0);
  c.badgeText = text(c.badge, t::small(), t::ink(), 0, 7, 150);
  c.title = text(rootObj, t::title(), t::text(), t::kMargin, t::kTitleY, t::kScreenW - 2 * t::kMargin);
  c.subtitle = text(rootObj, t::body(), t::muted(), t::kMargin, t::kSubtitleY, t::kScreenW - 2 * t::kMargin);
  c.notice = text(rootObj, t::small(), t::soft(), t::kMargin, 360, t::kScreenW - 2 * t::kMargin);
  c.secondary = button(rootObj, t::kMargin, t::kBarY, 230, t::kMinTarget, ButtonStyle::Secondary);
  c.primary = button(rootObj, t::kMargin + 230 + t::kGap, t::kBarY, t::kScreenW - 2 * t::kMargin - 230 - t::kGap,
                     t::kMinTarget, ButtonStyle::Primary);
}

void updateChrome(Chrome& c, const kiosk::KioskView& view) {
  setHidden(c.badge, !view.label[0]);
  setText(c.badgeText, view.label);
  setText(c.title, view.title);
  setText(c.subtitle, view.subtitle);
  setText(c.notice, view.notice);
  const lv_color_t tones[] = {t::soft(), t::amber(), t::green(), t::danger()};
  lv_obj_set_style_text_color(c.notice, tones[static_cast<int>(view.tone) & 3], 0);
  setButton(c.primary, view.primary);
  setButton(c.secondary, view.secondary);
  // Só um botão: ocupa a barra inteira (alvo maior, centrado).
  if (view.primary.visible && !view.secondary.visible) {
    lv_obj_set_x(c.primary, t::kMargin); lv_obj_set_width(c.primary, t::kScreenW - 2 * t::kMargin);
  } else {
    lv_obj_set_x(c.primary, t::kMargin + 230 + t::kGap);
    lv_obj_set_width(c.primary, t::kScreenW - 2 * t::kMargin - 230 - t::kGap);
  }
  if (view.primary.visible) {
    lv_obj_t* label = lv_obj_get_child(c.primary, 0);
    lv_obj_set_width(label, lv_obj_get_style_width(c.primary, LV_PART_MAIN) - 16);
    setButton(c.primary, view.primary);
  }
  // "Ainda está aí?": criado só quando aparece (memória) e apagado ao sumir.
  if (view.stillThere && !c.modal) {
    c.modal = lv_obj_create(c.root);
    plainStyle(c.modal);
    lv_obj_set_pos(c.modal, 0, 0);
    lv_obj_set_size(c.modal, t::kScreenW, t::kScreenH);
    lv_obj_set_style_bg_opa(c.modal, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(c.modal, t::bg(), 0);
    lv_obj_t* box = block(c.modal, 150, 110, 500, 260);
    lv_obj_t* title = text(box, t::title(), t::text(), 0, 28, 500);
    lv_label_set_text(title, kiosk::str::kStillThereTitle);
    lv_obj_t* detail = text(box, t::body(), t::muted(), 30, 84, 440);
    lv_label_set_text(detail, kiosk::str::kStillThereDetail);
    lv_obj_t* resume = button(box, 30, 160, 440, t::kMinTarget, ButtonStyle::Primary);
    kiosk::ViewButton model;
    snprintf(model.text, sizeof(model.text), "%s", kiosk::str::kContinue);
    model.action = kiosk::Action::Continue; model.visible = true; model.enabled = true;
    setButton(resume, model);
  } else if (!view.stillThere && c.modal) {
    lv_obj_del(c.modal);
    c.modal = nullptr;
  }
}

}  // namespace ui
#endif
