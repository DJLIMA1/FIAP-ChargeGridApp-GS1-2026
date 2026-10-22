#pragma once
// Totem de autoatendimento (firmware 0.8.0): máquina de estados pura (C++17, sem Arduino/LVGL).
//
// Entrada: Event {Touch, Key, Tick (timeout), Facts (estado do ponto + blocos do sync), ApiResult}.
// Saída: KioskView (struct simples, só char[]/números) para as views e no máximo um ApiRequest
// por vez, executado pelo laço principal (kiosk_api). O totem nunca escolhe o método de
// pagamento: ele vem da oferta do servidor (simulated ou stripe). Nada liga sem o servidor
// confirmar o pagamento; o START continua sendo um comando normal do sync.
#include <stddef.h>
#include <stdint.h>
#include <ArduinoJson.h>

namespace kiosk {

constexpr size_t kIdSize = 48;      // UUID (36) com folga
constexpr size_t kUrlSize = 200;    // QR do pedido/recibo (a API limita a 160)
constexpr size_t kLabelSize = 16;
constexpr size_t kShortcuts = 4;

enum class Method : uint8_t { Unknown, Simulated, Stripe };
enum class Mode : uint8_t { None, Value, Time, Energy, Autonomy };

// ---------------------------------------------------------------- blocos do sync (aditivos)
// connector.kiosk {enabled, method, label}. Ausente/nulo/inválido (API antiga): totem desligado.
struct SyncKiosk {
  bool present = false;
  bool enabled = false;
  Method method = Method::Unknown;
  char label[kLabelSize]{};   // "SIMULADO" | "TESTE" | ""
};
// kiosk_order.receipt (até 10 min depois do fim).
struct OrderReceipt {
  bool present = false;
  bool final = false;
  char number[32]{};
  float energyKwh = -1;
  int32_t totalCents = -1;
  int32_t returnedCents = -1;
  char returnKind[20]{};      // "released" | "refunded" | "simulated"
  char endReason[24]{};
  char url[kUrlSize]{};
};
// kiosk_order {id, status, session_id, payment{status,label,method}, receipt{...}}.
struct OrderBlock {
  bool present = false;
  char id[kIdSize]{};
  char status[24]{};
  char sessionId[kIdSize]{};
  char paymentStatus[24]{};
  char paymentLabel[kLabelSize]{};
  char fundingSource[12]{};
  Method paymentMethod = Method::Unknown;
  char qrUrl[kUrlSize]{};     // payment.qr_url: QR do pedido ainda válido (retomada)
  char receiptUrl[kUrlSize]{};// receipt_url do pedido (GET /orders/{id})
  OrderReceipt receipt;
};
struct SyncFacts {
  SyncKiosk kiosk;
  OrderBlock order;
  bool sessionPresent = false;      // authorized.session
  char sessionId[kIdSize]{};
  bool reservationPresent = false;  // authorized.reservation
  char sessionOrigin[16]{};   // authorized.session.origin: "app" | "kiosk_qr" | "kiosk_totem" | ""
};
// Leitura aditiva da resposta do sync (chamada em apply()). Nunca falha: campo inválido = ausente.
void readSync(JsonObjectConst response, SyncFacts& out);
// Pedido do totem no JSON das rotas (/orders/{id} e kiosk_order) para a mesma estrutura.
void readOrder(JsonObjectConst order, OrderBlock& out);

// ---------------------------------------------------------------- fatos do ponto (a cada laço)
struct Facts {
  uint32_t nowMs = 0;
  bool online = false;          // API respondeu há < 45 s
  bool pointReady = false;      // tela "Pronto": ocioso, ativo, vinculado, sem sessão/reserva
  bool chargerOffline = false;  // central online, mas o carregador Modbus não responde
  bool reserved = false;        // reserva confirmada (estado reserved ou authorized.reservation)
  bool carConnected = false;    // permanência: carro ainda conectado fora de recarga
  bool maintenance = false;     // ponto/posto inativo
  bool charging = false;
  bool stopped = false;
  bool sessionAuthorized = false; // authorized.session presente
  char sessionId[kIdSize]{};
  char endReason[24]{};
  float energyKwh = 0;
  int32_t costCents = -1;       // valor estimado da sessão (preço travado)
  int32_t capCents = -1;        // teto (max_cost)
  float appliedPowerKw = -1;    // potência aplicada confirmada pela API
  char powerReason[48]{};
  float socPercent = -1;        // -1 = desconhecido
  uint32_t elapsedS = 0, remainingS = 0;
  // Permanência (textos já montados pelo painel, mesmas regras da tela atual).
  char overstayTitle[72]{};
  char overstayDetail[128]{};
  SyncFacts sync;
};

// ---------------------------------------------------------------- API do dispositivo
enum class RequestKind : uint8_t { None, Login, Offer, Quote, CreateOrder, Pay, Cancel, GetOrder };
struct ApiRequest {
  uint8_t chargerAddress = 0;
  RequestKind kind = RequestKind::None;
  uint32_t seq = 0;
  const char* method = "GET";
  char path[96]{};
  char body[512]{};
  char idempotencyKey[kIdSize + 8]{};
};
struct ApiResult {
  RequestKind kind = RequestKind::None;
  uint32_t seq = 0;
  int status = 0;               // HTTP; <= 0 = sem resposta (rede, timeout, recusado localmente)
  const char* body = nullptr;
};

// ---------------------------------------------------------------- toque/tecla
enum class Action : uint8_t {
  None, StartFlow, Back, Cancel, ModeValue, ModeTime, ModeEnergy,
  Shortcut0, Shortcut1, Shortcut2, Shortcut3, OtherValue, KeypadOk,
  Accept, SimulatePay, Stop, ConfirmYes, ConfirmNo, Done, Continue, Disconnect, Retry,
  Guest, Login, LoginNext, ModeAutonomy, Next, PowerMax, PowerReduced, PayBalance, PayPix, PayCard,
  Connector0, Connector1, Connector2, Connector3,
};
// Teclas do teclado numérico: '0'-'9', ',' (só kWh), 'B' apagar, 'C' limpar.

enum class EventType : uint8_t { Touch, Key, Tick, Facts, ApiResult };
struct Event {
  EventType type = EventType::Tick;
  uint32_t nowMs = 0;
  Action action = Action::None;
  char key = 0;
  const Facts* facts = nullptr;
  const ApiResult* result = nullptr;
};

// ---------------------------------------------------------------- view
// T0 é a tela "Pronto" atual (painel) com o botão "Iniciar recarga"; Screen::None mantém as
// telas atuais. As demais telas substituem o painel enquanto o fluxo está aberto.
enum class Screen : uint8_t {
  None, Choose /*T1*/, Amount /*T2*/, Review /*T3*/, Pay /*T4*/, Starting /*T5*/, Live /*T6*/,
  ConfirmStop /*T7*/, Receipt /*T8*/, Notice /*TE*/, Verifying,
  Welcome, Login, Connector, Power, PaymentMethod,
};
enum class Tone : uint8_t { Neutral, Waiting, Success, Error };
struct ViewButton {
  char text[48]{};
  Action action = Action::None;
  bool visible = false;
  bool enabled = false;
};
struct ViewMetric {
  char name[24]{};
  char value[96]{};
};
struct KioskView {
  Screen screen = Screen::None;
  uint32_t revision = 0;        // muda a cada alteração (a UI só redesenha quando muda)
  char title[64]{};
  char subtitle[128]{};
  char label[kLabelSize]{};     // SIMULADO / TESTE (sempre visível quando o servidor manda)
  char notice[96]{};            // aviso/erro em linha
  Tone tone = Tone::Neutral;
  bool busy = false;            // aguardando a API
  ViewButton options[kShortcuts];   // T1 modos / T2 atalhos
  ViewButton primary, secondary;
  ViewMetric metrics[6];
  uint8_t metricCount = 0;
  bool keypad = false;          // T2 "Outro valor"
  bool decimalKey = false;      // vírgula só em kWh
  char entry[16]{};             // valor digitado (pt-BR)
  char entryUnit[8]{};          // "R$", "min", "kWh"
  char qr[kUrlSize]{};          // QR do pedido (T4 stripe) ou do recibo (T8)
  char qrCaption[48]{};
  bool stillThere = false;      // "Ainda está aí?" (overlay com Continuar)
  bool disconnect = false;      // permanência: botão Desconectar no recibo
  bool password = false;
  char loginEntry[128]{};       // password is always masked, never copied here
  char context[192]{};
  float socPercent = -1;
};

enum class State : uint8_t {
  Off,        // totem desligado (compilação, connector.kiosk ou API antiga)
  Idle,       // T0
  LoadingOffer, Choose, Amount, Review, Pay, Starting, Live, ConfirmStop, Receipt, Notice, Verifying,
  Welcome, Login, Connector, Power, PaymentMethod,
};

struct Offer {
  bool modern = false;
  bool loaded = false;
  bool active = false;       // enabled + método decidido pelo servidor
  bool available = true;     // ponto livre agora
  char reason[24]{};         // kiosk_in_use | reserved | charging | occupied | ...
  char openOrderId[kIdSize]{};
  uint32_t startTimeoutMs = 60000;
  Method method = Method::Unknown;
  char label[kLabelSize]{};
  int32_t valueShortcuts[kShortcuts]{};   // centavos
  int32_t timeShortcuts[kShortcuts]{};    // minutos
  int32_t energyShortcuts[kShortcuts]{};  // Wh (kWh * 1000)
  uint8_t valueCount = 0, timeCount = 0, energyCount = 0;
  int32_t valueMin = 0, valueMax = 0;     // centavos
  int32_t timeMin = 0, timeMax = 0;       // minutos
  int32_t energyMin = 0, energyMax = 0;   // Wh
  float pricePerKwh = -1, basePrice = -1, multiplier = -1, powerKw = -1;
  float maxPricePerKwh = -1, reducedPricePerKwh = -1;
  char demandReason[64]{};
  char overstaySummary[96]{};
  char overstayVersion[44]{};  // a API aceita até 40
  bool loggedIn = false, hasVehicle = false, balanceAvailable = false;
  bool pixAvailable = true, cardAvailable = true;
  int32_t balanceCents = 0;
  char accountName[64]{}, vehicleName[64]{}, connectorType[32]{}, publicCode[32]{};
  struct ConnectorChoice { uint8_t address = 0; bool available = false; char label[48]{}; } connectors[4];
  uint8_t connectorCount = 0;
};
struct Quote {
  bool loaded = false;
  Mode mode = Mode::None;
  int32_t requested = 0;        // centavos / minutos / Wh
  char hash[80]{};
  int32_t amountCents = -1;     // valor pré-autorizado (teto + reserva da permanência)
  int32_t energyCapCents = -1;
  float pricePerKwh = -1, basePrice = -1, multiplier = -1;
  float energyKwh = -1;
  int32_t minutes = -1;
  char demandReason[64]{};
  char overstaySummary[96]{};
  char overstayVersion[44]{};  // a API aceita até 40
  char label[kLabelSize]{};
  char autonomyNote[128]{};
};
struct Order {
  char id[kIdSize]{};
  char status[24]{};
  char sessionId[kIdSize]{};
  char qrUrl[kUrlSize]{};
  char receiptUrl[kUrlSize]{};
  char idempotencyKey[kIdSize]{};   // reusado ao repetir POST /orders após falha de rede
  Method method = Method::Unknown;
  int32_t amountCents = -1;
  uint32_t expiresAtMs = 0;         // trava local (5 min; 10 min com QR)
  bool paid = false;
  bool cancelSent = false;
};

class Flow {
 public:
  // Tempos (ms). Públicos para os testes.
  static constexpr uint32_t kIdleTimeoutMs = 60000, kPromptMs = 50000;
  static constexpr uint32_t kReviewTimeoutMs = 90000, kReviewPromptMs = 80000;
  static constexpr uint32_t kQrTimeoutMs = 600000, kHoldMs = 300000;
  static constexpr uint32_t kStartTimeoutMs = 60000, kConfirmTimeoutMs = 10000;
  static constexpr uint32_t kReceiptTimeoutMs = 30000, kNoticeMs = 6000;
  static constexpr uint32_t kResumeGiveUpMs = 120000;

  void setSeed(uint32_t seed) { rng_ = seed ? seed : 0x9E3779B9u; }
  // Retomada após reboot: id salvo na NVS ("kord"). Vazio: nada a retomar.
  void resume(const char* orderId, uint32_t nowMs, uint8_t chargerAddress = 0);
  void handle(const Event& event);
  void touch(Action action, uint32_t nowMs);
  void key(char key, uint32_t nowMs);
  void tick(uint32_t nowMs);
  void facts(const Facts& facts);
  void apiResult(const ApiResult& result);
  // O painel usa o mesmo acompanhamento/recibo para sessões iniciadas pelo app.
  void followAppSessions(bool enabled = true) { followAppSessions_ = enabled; }
  void followAppCharger(uint8_t address) {
    if (followAppSessions_ && (state_ == State::Off || state_ == State::Idle) && !order_.id[0]) chargerAddress_ = address;
  }

  // Próximo pedido à API (um por vez). Depois de executar, chame apiResult() com o mesmo seq.
  bool takeRequest(ApiRequest& out);
  bool requestInFlight() const { return inFlight_.kind != RequestKind::None; }
  // Efeitos locais pedidos pelo fluxo (consumidos pelo laço principal).
  bool takeLocalStop();
  bool takeLocalDisconnect();
  // Pedido a salvar na NVS ("" = apagar). true só quando mudou.
  bool takePersist(char* out, size_t size);

  State state() const { return state_; }
  bool enabled() const { return enabled_; }
  // Botão "Iniciar recarga" na tela Pronto.
  bool canStart() const;
  // Tela do totem por cima das telas atuais.
  bool active() const { return view_.screen != Screen::None; }
  const KioskView& view() const { return view_; }
  const Offer& offer() const { return offer_; }
  const Quote& quote() const { return quote_; }
  const Order& order() const { return order_; }
  bool apiUnsupported() const { return apiUnsupported_; }
  const char* authToken() const { return token_; }
  uint8_t chargerAddress() const { return chargerAddress_; }

 private:
  void go(State next, uint32_t nowMs);
  void toIdle(uint32_t nowMs);
  void notice(const char* title, const char* detail, Tone tone, uint32_t nowMs);
  void retryNotice(const char* title, const char* detail, uint32_t nowMs);
  void queue(RequestKind kind, const char* method, const char* path, const char* body, const char* key);
  void requestQuote();
  void requestOrder();
  void requestPay();
  void requestCancel();
  void abortOrder(const char* title, const char* detail, uint32_t nowMs);
  void clearOrder();
  void selectMode(Mode mode, uint32_t nowMs);
  void selectValue(int32_t value, uint32_t nowMs);
  void submitEntry(uint32_t nowMs);
  void applyOffer(JsonObjectConst body);
  bool applyQuote(JsonObjectConst body);
  void applyOrder(JsonObjectConst body);
  void followOrder(const OrderBlock& block, uint32_t nowMs);
  void onPaid(uint32_t nowMs);
  void enterReceipt(uint32_t nowMs);
  void render();
  void loadOffer(uint32_t nowMs);
  void clearIdentity();
  void selectionBody(char* out, size_t size, bool order);
  bool sessionIsOurs(const Facts& facts) const;
  void newKey(char* out, size_t size, const char* prefix);
  uint32_t random();

  State state_ = State::Off;
  bool enabled_ = false;
  bool apiUnsupported_ = false;    // GET /offer 404: API antiga
  uint32_t apiUnsupportedAt_ = 0;
  uint32_t enteredAt_ = 0, lastInput_ = 0, now_ = 0;
  uint32_t rng_ = 0x9E3779B9u;
  uint32_t seq_ = 0;
  ApiRequest queued_, inFlight_;
  Facts facts_;
  Facts lastSessionFacts_;
  bool followAppSessions_ = false, appSession_ = false;
  bool haveFacts_ = false;
  Offer offer_;
  Quote quote_;
  Order order_;
  Mode mode_ = Mode::None;
  bool keypad_ = false;
  bool stillThere_ = false;
  char entry_[12]{};
  char error_[96]{};
  char noticeTitle_[64]{}, noticeDetail_[128]{};
  Tone noticeTone_ = Tone::Neutral;
  bool noticeRetry_ = false;
  State retryFrom_ = State::LoadingOffer;
  State returnFrom_ = State::Idle;  // T7 volta para cá
  bool localStop_ = false, localDisconnect_ = false;
  bool persistDirty_ = false;
  bool resumed_ = false;           // pedido vindo da NVS (sem dados locais)
  bool offlineStop_ = false;       // T6 terminou sem rede (recibo em conferência)
  bool liveSeen_ = false;
  char receiptEndReason_[24]{};
  uint32_t missingOrderSince_ = 0;
  KioskView view_;
  KioskView scratch_;
  char token_[2048]{}, email_[128]{}, password_[128]{}, loginEntry_[128]{};
  bool passwordStep_ = false, reducedPower_ = false;
  Action paymentSource_ = Action::PayCard;
  uint8_t chargerAddress_ = 0;
  bool selectingConnector_ = false;
};

// Formatação pt-BR (vírgula decimal), só ASCII/Latin-1.
void formatMoney(char* out, size_t size, int32_t cents);          // "R$ 20,00"
void formatDecimal(char* out, size_t size, float value, int decimals); // "6,5"
int32_t parseCents(JsonVariantConst value);                         // "20.00" | 20 -> 2000; inválido -1
const char* modeName(Mode mode);                                    // "value" | "time" | "energy"

}  // namespace kiosk
