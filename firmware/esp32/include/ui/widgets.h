#pragma once
// Widgets das telas do totem: botão grande, bloco, métrica, teclado numérico, QR e modal.
// Os toques nunca chamam a lógica direto: viram Action/tecla na fila (router.h) e o laço
// principal entrega ao kiosk_flow.
#include <lvgl.h>
#include "kiosk_flow.h"

namespace ui {

enum class ButtonStyle : uint8_t { Primary, Secondary, Danger, Light, Option };

lv_obj_t* root(lv_obj_t* parent);
lv_obj_t* text(lv_obj_t* parent, const lv_font_t* font, lv_color_t color, int x, int y, int width,
               lv_text_align_t align = LV_TEXT_ALIGN_CENTER);
lv_obj_t* block(lv_obj_t* parent, int x, int y, int width, int height);
lv_obj_t* button(lv_obj_t* parent, int x, int y, int width, int height, ButtonStyle style);
// Texto, ação, visível/habilitado. Troca a fonte para Barlow Medium se o texto tiver glifo
// fora da Bold (ou não couber).
void setButton(lv_obj_t* button, const kiosk::ViewButton& model);
void setText(lv_obj_t* label, const char* value);
void setHidden(lv_obj_t* object, bool hidden);
// Fonte Bold tem este texto inteiro? (ASCII + ÁÀÂÃÇÉÊÍÓÔÕÚ áàâãçéêíóôõú)
bool boldCovers(const char* utf8);

struct Metric { lv_obj_t* box = nullptr; lv_obj_t* name = nullptr; lv_obj_t* value = nullptr; };
Metric metric(lv_obj_t* parent, int x, int y, int width, int height);
void setMetric(Metric& metric, const kiosk::ViewMetric* model);   // nullptr = oculta
void resizeMetric(Metric& metric, int width, int height);

// Teclado numérico 3x4 (1-9, vírgula, 0, apagar). Teclas de 104x72.
lv_obj_t* keypad(lv_obj_t* parent, int x, int y);
void setKeypadDecimal(lv_obj_t* keypad, bool decimal);

// QR em caixa branca; redesenha só quando o texto muda.
struct Qr { lv_obj_t* box = nullptr; lv_obj_t* code = nullptr; lv_obj_t* caption = nullptr; char last[kiosk::kUrlSize]{}; };
Qr qr(lv_obj_t* parent, int x, int y, int size);
void setQr(Qr& qr, const char* text, const char* caption);

// Cabeçalho comum (marca + rótulo SIMULADO/TESTE), título, subtítulo, aviso e barra de botões.
struct Chrome {
  lv_obj_t* badge = nullptr; lv_obj_t* badgeText = nullptr;
  lv_obj_t* title = nullptr; lv_obj_t* subtitle = nullptr; lv_obj_t* notice = nullptr;
  lv_obj_t* primary = nullptr; lv_obj_t* secondary = nullptr;
  lv_obj_t* modal = nullptr;   // "Ainda está aí?" (criado só quando aparece)
  lv_obj_t* root = nullptr;
  lv_obj_t* context = nullptr; lv_obj_t* step = nullptr;
  lv_obj_t* panel = nullptr;
  // Coluna do título "flui": subtítulo, contexto e aviso logo abaixo do título, o bloco
  // centrado na altura do cartão. Telas com posições próprias desligam.
  bool flow = true;
};
void chrome(lv_obj_t* root, Chrome& chrome);
void updateChrome(Chrome& chrome, const kiosk::KioskView& view);

}  // namespace ui
