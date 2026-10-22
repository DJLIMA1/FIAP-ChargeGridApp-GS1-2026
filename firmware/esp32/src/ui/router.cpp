#ifdef CHARGEGRID_KIOSK
#include <Arduino.h>
#include "ui/router.h"
#include "ui/widgets.h"

namespace ui {
namespace {
// Fila circular de toques/teclas (núcleo 0 -> núcleo 1).
constexpr uint8_t kQueueSize = 16;
Input queue[kQueueSize];
uint8_t head = 0, tail = 0;
portMUX_TYPE queueMux = portMUX_INITIALIZER_UNLOCKED;

void push(const Input& input) {
  taskENTER_CRITICAL(&queueMux);
  const uint8_t next = static_cast<uint8_t>((head + 1) % kQueueSize);
  if (next != tail) { queue[head] = input; head = next; }   // cheia: descarta o toque novo
  taskEXIT_CRITICAL(&queueMux);
}

lv_obj_t* screenObject = nullptr;
lv_obj_t* viewRoot = nullptr;
void (*release)() = nullptr;
void (*restore)() = nullptr;
bool panelReleased = false;
kiosk::Screen current = kiosk::Screen::None;
const ViewOps* ops = nullptr;
uint32_t revision = 0;
bool currentKeypad = false;

const ViewOps* opsFor(kiosk::Screen screen) {
  switch (screen) {
    case kiosk::Screen::Choose: return &viewChoose;
    case kiosk::Screen::Welcome: case kiosk::Screen::Connector:
    case kiosk::Screen::Power: case kiosk::Screen::PaymentMethod: return &viewChoose;
    case kiosk::Screen::Login: return &viewLogin;
    case kiosk::Screen::Amount: return &viewAmount;
    case kiosk::Screen::Review: return &viewReview;
    case kiosk::Screen::Pay: return &viewPay;
    case kiosk::Screen::Starting: return &viewStarting;
    case kiosk::Screen::Live: return &viewLive;
    case kiosk::Screen::ConfirmStop: return &viewLive;
    case kiosk::Screen::Receipt: return &viewReceipt;
    case kiosk::Screen::Notice: case kiosk::Screen::Verifying: return &viewNotice;
    default: return nullptr;
  }
}

void closeView() {
  if (ops) ops->destroy();
  if (viewRoot) lv_obj_del(viewRoot);
  viewRoot = nullptr; ops = nullptr; current = kiosk::Screen::None;
}
}  // namespace

void pushAction(kiosk::Action action) { Input input; input.action = action; push(input); }
void pushKey(char key) { Input input; input.key = true; input.value = key; push(input); }
bool popInput(Input& out) {
  bool found = false;
  taskENTER_CRITICAL(&queueMux);
  if (tail != head) { out = queue[tail]; tail = static_cast<uint8_t>((tail + 1) % kQueueSize); found = true; }
  taskEXIT_CRITICAL(&queueMux);
  return found;
}

void routerInit(lv_obj_t* screen, void (*releasePanel)(), void (*restorePanel)()) {
  screenObject = screen; release = releasePanel; restore = restorePanel;
}

bool routerUpdate(const kiosk::KioskView& view) {
  const ViewOps* next = opsFor(view.screen);
  if (!next) {
    if (viewRoot) closeView();
    if (panelReleased && restore) { restore(); panelReleased = false; }
    return false;
  }
  if (next != ops || (view.screen == kiosk::Screen::Amount && view.keypad != currentKeypad)) {
    if (viewRoot) closeView();          // apaga a anterior antes de criar a nova (pico menor)
    if (!panelReleased && release) { release(); panelReleased = true; }
    viewRoot = nullptr;
    current = view.screen; ops = next;
    currentKeypad = view.keypad;
    revision = view.revision - 1;
    viewRoot = root(screenObject);
    ops->create(viewRoot, view);
  }
  current = view.screen;
  if (view.revision != revision) { ops->update(view); revision = view.revision; }
  return true;
}

kiosk::Screen routerScreen() { return current; }
lv_obj_t* routerRoot() { return viewRoot; }

}  // namespace ui
#endif
