#pragma once
// Tokens visuais das telas do totem (provisórias). O design entra trocando este arquivo,
// widgets.cpp e view_*.cpp; a lógica (kiosk_flow) não muda.
#include <lvgl.h>
#include "panel_fonts.h"

namespace ui {
namespace tokens {
// Cores (RGB565 exatos, as mesmas superfícies das telas atuais).
inline lv_color_t bg() { return LV_COLOR_MAKE(0x18, 0x1C, 0x20); }
inline lv_color_t card() { return LV_COLOR_MAKE(0x20, 0x24, 0x28); }
inline lv_color_t control() { return LV_COLOR_MAKE(0x2C, 0x32, 0x3A); }
inline lv_color_t line() { return LV_COLOR_MAKE(0x34, 0x3A, 0x44); }
inline lv_color_t red() { return LV_COLOR_MAKE(0xD7, 0x2B, 0x32); }
inline lv_color_t text() { return LV_COLOR_MAKE(0xF5, 0xF5, 0xF5); }
inline lv_color_t soft() { return LV_COLOR_MAKE(0xD6, 0xDA, 0xE0); }
inline lv_color_t muted() { return LV_COLOR_MAKE(0x9A, 0xA2, 0xAE); }   // AA sobre bg
inline lv_color_t green() { return LV_COLOR_MAKE(0x1E, 0xDF, 0x5A); }
inline lv_color_t amber() { return LV_COLOR_MAKE(0xFF, 0xC6, 0x2E); }
inline lv_color_t danger() { return LV_COLOR_MAKE(0xFF, 0x6B, 0x70); }
inline lv_color_t ink() { return LV_COLOR_MAKE(0x10, 0x10, 0x10); }
inline lv_color_t disabled() { return LV_COLOR_MAKE(0x26, 0x2B, 0x31); }

// Espaçamentos e raios.
constexpr int kMargin = 39;          // mesma margem das telas atuais
constexpr int kGap = 16;
constexpr int kRadius = 14;
constexpr int kMinTarget = 72;       // alvo de toque mínimo (px)
constexpr int kKeyWidth = 104, kKeyHeight = 72;
// Faixas verticais: cabeçalho, título, subtítulo, conteúdo, barra de botões.
constexpr int kHeaderY = 24, kTitleY = 72, kSubtitleY = 122, kContentY = 160, kBarY = 392;
constexpr int kScreenW = 800, kScreenH = 480;

// Fontes por papel. Títulos/botões: Barlow Bold (só ASCII + acentos pt-BR).
// Texto e dados da API: Barlow Medium (Latin-1 + U+2022).
inline const lv_font_t* brand() { return &chargegrid_brand_30; }
inline const lv_font_t* title() { return &chargegrid_brand_34; }
inline const lv_font_t* big() { return &chargegrid_title_48; }
inline const lv_font_t* button() { return &chargegrid_brand_30; }
inline const lv_font_t* body() { return &chargegrid_body_19; }
inline const lv_font_t* bodyLarge() { return &chargegrid_body_22; }
inline const lv_font_t* small() { return &chargegrid_body_17; }
inline const lv_font_t* caption() { return &chargegrid_body_14; }
// LV_SYMBOL_BACKSPACE só existe nas Montserrat embutidas do LVGL.
inline const lv_font_t* symbol() {
#if LV_FONT_MONTSERRAT_28
  return &lv_font_montserrat_28;
#else
  return &lv_font_montserrat_14;
#endif
}
}  // namespace tokens
}  // namespace ui
