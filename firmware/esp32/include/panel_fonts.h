#pragma once

#ifdef CHARGEGRID_PANEL_ENABLED
#include <lvgl.h>

#ifdef __cplusplus
extern "C" {
#endif

extern const lv_font_t chargegrid_montserrat_14;
extern const lv_font_t chargegrid_montserrat_16;
extern const lv_font_t chargegrid_montserrat_18;
extern const lv_font_t chargegrid_montserrat_20;
extern const lv_font_t chargegrid_montserrat_24;
extern const lv_font_t chargegrid_montserrat_28;
/* Montserrat SemiBold, ASCII + acentos do português: títulos das telas. */
extern const lv_font_t chargegrid_title_32;
extern const lv_font_t chargegrid_title_40;
extern const lv_font_t chargegrid_title_52;

extern const lv_img_dsc_t chargegrid_pump_bolt;

#ifdef __cplusplus
}
#endif
#endif  // CHARGEGRID_PANEL_ENABLED
