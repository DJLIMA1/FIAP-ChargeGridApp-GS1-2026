#pragma once
// Router das telas do totem: tela -> view; cria ao entrar, apaga ao sair (criação preguiçosa).
// Enquanto uma tela do totem está aberta, as telas atuais do painel são liberadas (memória do
// pool LVGL) e reconstruídas ao voltar. Fila de toques: produzida no núcleo 0 (callbacks LVGL),
// consumida no núcleo 1 (panelTick), protegida por portMUX.
#include <lvgl.h>
#include "kiosk_flow.h"

namespace ui {

struct Input { bool key = false; kiosk::Action action = kiosk::Action::None; char value = 0; };
void pushAction(kiosk::Action action);
void pushKey(char key);
bool popInput(Input& out);

struct ViewOps {
  void (*create)(lv_obj_t* root, const kiosk::KioskView& view);
  void (*update)(const kiosk::KioskView& view);
  void (*destroy)();   // só zera os ponteiros; o router apaga a árvore
};
extern const ViewOps viewChoose, viewAmount, viewReview, viewPay, viewStarting, viewLive,
    viewConfirmStop, viewReceipt, viewNotice, viewLogin;

// releasePanel/restorePanel: liberam e reconstroem as telas atuais.
void routerInit(lv_obj_t* screen, void (*releasePanel)(), void (*restorePanel)());
// true = uma tela do totem está na frente (o refresh das telas atuais não roda).
bool routerUpdate(const kiosk::KioskView& view);
kiosk::Screen routerScreen();
lv_obj_t* routerRoot();

}  // namespace ui
