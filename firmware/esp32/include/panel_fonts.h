#pragma once

#ifdef CHARGEGRID_PANEL_ENABLED
#include <lvgl.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Barlow Condensed (OFL), o rosto condensado do design de referência.
   Bold: marca, títulos, código e números. Medium: texto corrido (U+0020-U+00FF e U+2022). */
extern const lv_font_t chargegrid_brand_30;
extern const lv_font_t chargegrid_brand_34;
extern const lv_font_t chargegrid_title_48;
extern const lv_font_t chargegrid_alert_68;
extern const lv_font_t chargegrid_code_72;
extern const lv_font_t chargegrid_body_14;
extern const lv_font_t chargegrid_body_17;
extern const lv_font_t chargegrid_body_19;
extern const lv_font_t chargegrid_body_22;

extern const lv_img_dsc_t chargegrid_pump_bolt;

#ifdef __cplusplus
}
#endif
#endif  // CHARGEGRID_PANEL_ENABLED
