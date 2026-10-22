// Totem 0.8.0: testes da máquina de estados pura (firmware/esp32/src/kiosk_flow.cpp), sem
// Arduino/LVGL. Compilado e executado por tools/validate_firmware.py. Respostas no formato do
// contrato "Totem 0.8.0" de docs/esp32-protocol.md.
#include <cassert>
#include <cstdio>
#include <cstring>
#include <string>
#include "kiosk_flow.h"

using namespace kiosk;

namespace {

constexpr const char* kOrderId = "7d0c9a52-3f1e-4b5a-9a51-2c0d5e8f1a10";
constexpr const char* kSessionId = "58967906-cabe-48d3-ae70-af6859edc100";
constexpr const char* kQr = "https://chargegrid-api-preview-djlima1s-projects.vercel.app/pay/o/7d0c9a52-3f1e-4b5a-9a51-2c0d5e8f1a10?t=QUJDREVGR0hJSktMTU5PUFFSU1RVVldY";
constexpr const char* kReceiptUrl = "https://chargegrid-api-preview-djlima1s-projects.vercel.app/pay/r/7d0c9a52-3f1e-4b5a-9a51-2c0d5e8f1a10?t=QUJDREVGR0hJSktMTU5PUFFSU1RVVldY";

std::string offerJson(const char* method, const char* label, bool available = true, const char* reason = "null",
                      const char* openOrder = "null") {
  char out[2048];
  snprintf(out, sizeof(out), R"({"ui_version":2,"enabled":true,"available":%s,"reason":%s,"reason_label":null,"open_order_id":%s,
    "method":"%s","label":"%s","currency":"BRL","public_code":"CG-7KQ2","power_kw":"7.200","speed_prices":{"max":"2.3000","reduced":"1.8400"},
    "price":{"price_per_kwh":"2.3000","base_price_per_kwh":"2.0000","demand_multiplier":"1.15",
             "reason_label":"Alta demanda","level_label":"Alta","increase_percent":15},
    "limits":{"max_total":"200.00","overstay_reserve":"30.00"},
    "modes":{"value":{"shortcuts":["10.00","20.00","40.00","60.00"],"min":"5.00","max":"170.00"},
             "time":{"shortcuts":[15,30,60],"min":5,"max":60},
             "energy":{"shortcuts":["5.0","10.0","20.0"],"min":"1.0","max":"73.9","decimals":1}},
    "overstay":{"enabled":true,"version":"ov-3","summary":"Após 10 min: R$ 1,00 por minuto, até R$ 30,00",
                "grace_minutes":10,"interval_minutes":1,"amount":"1.00","max_amount":"30.00","fee_per_minute":"1.00"},
    "hold_minutes":5,"qr_hold_minutes":10,"start_timeout_seconds":60})",
           available ? "true" : "false", reason, openOrder, method, label);
  return out;
}
std::string quoteJson(const char* method, const char* label, const char* hash = "0123456789abcdef0123456789abcdef") {
  char out[1536];
  snprintf(out, sizeof(out), R"({"quote_hash":"%s","mode":"value","amount":"20.00","minutes":null,"energy_kwh":null,
    "total":"50.00","energy_cap":"20.00","overstay_reserve":"30.00",
    "price_per_kwh":"2.3000","base_price_per_kwh":"2.0000","demand_multiplier":"1.15","discount_percent":0,
    "demand":{"multiplier":"1.15","level_label":"Alta","reason_label":"Alta demanda"},
    "estimated_energy_kwh":"8.696","max_duration_minutes":73,"power_kw":"7.200",
    "overstay":{"enabled":true,"version":"ov-3","summary":"Após 10 min: R$ 1,00 por minuto, até R$ 30,00"},
    "method":"%s","label":"%s"})", hash, method, label);
  return out;
}
std::string orderJson(const char* status, const char* method, const char* payment = "null", int expires = 300) {
  const std::string qr = strcmp(method, "simulated") == 0 ? std::string("\"") + kQr + "\"" : "null";
  char out[2048];
  snprintf(out, sizeof(out), R"({"id":"%s","status":"%s","status_label":"x","method":"%s","label":"%s",
    "expires_at":"2026-10-20T12:05:00+00:00","expires_in_seconds":%d,
    "quote":{"mode":"value","amount":"20.00","total":"50.00","energy_cap":"20.00","overstay_reserve":"30.00"},
    "qr_url":%s,"payment":%s,"session_id":null,"session":null,"receipt":null,"receipt_url":"%s","error":null})",
           kOrderId, status, method, strcmp(method, "stripe") == 0 ? "TESTE" : "SIMULADO", expires, qr.c_str(), payment, kReceiptUrl);
  return out;
}
std::string syncJson(bool kiosk, const char* method = "simulated", const char* order = "null",
                     bool session = false, const char* origin = "kiosk_totem", bool reservation = false) {
  char out[3072];
  char kioskBlock[256] = "";
  if (kiosk) snprintf(kioskBlock, sizeof(kioskBlock), R"(,"kiosk":{"enabled":true,"method":"%s","label":"%s","reason":null})",
                      method, strcmp(method, "stripe") == 0 ? "TESTE" : "SIMULADO");
  char sessionBlock[256] = "null";
  if (session) snprintf(sessionBlock, sizeof(sessionBlock), R"({"id":"%s","status":"charging","origin":"%s"})", kSessionId, origin);
  snprintf(out, sizeof(out), R"({"server_time":"2026-10-20T12:00:00+00:00","control_version":3,"overstay":null,
    "connector":{"public_code":"CG-7KQ2","owned":true,"active":true%s},
    "authorized":{"reservation":%s,"session":%s},"commands":[],"kiosk_order":%s})",
           kioskBlock, reservation ? R"({"id":"r","expires_at":"2030-01-01T00:00:00Z"})" : "null", sessionBlock, order);
  return out;
}
std::string kioskOrder(const char* status, const char* paymentStatus = nullptr, const char* qr = nullptr,
                       bool receipt = false, bool final = false, const char* method = "simulated") {
  char payment[512] = "null";
  if (paymentStatus) snprintf(payment, sizeof(payment), R"J({"id":"p","status":"%s","label":"Pago (simulado)","method":"%s","amount":"50.00","qr_url":%s%s%s})J",
                              paymentStatus, method, qr ? "\"" : "", qr ? qr : "null", qr ? "\"" : "");
  char receiptBlock[768] = "null";
  if (receipt) snprintf(receiptBlock, sizeof(receiptBlock), R"({"number":"1A2B3C4D","energy_kwh":"2.500","total":"5.00","returned":"45.00",
    "return_kind":"%s","final":%s,"end_reason":"requested","end_reason_label":"Encerrada no totem","url":"%s"})",
                        strcmp(method, "stripe") == 0 ? "released" : "simulated", final ? "true" : "false", kReceiptUrl);
  char out[2048];
  snprintf(out, sizeof(out), R"({"id":"%s","status":"%s","status_label":"x","expires_at":null,"expires_in_seconds":null,
    "session_id":"%s","payment":%s,"receipt":%s,"error":null})", kOrderId, status, kSessionId, payment, receiptBlock);
  return out;
}

struct Harness {
  Flow flow;
  Facts facts;
  uint32_t now = 1000;
  Harness(const char* method = "simulated") {
    flow.setSeed(12345);
    facts.online = true; facts.pointReady = true;
    sync(syncJson(true, method));
    step();
  }
  void sync(const std::string& json) {
    JsonDocument doc;
    assert(!deserializeJson(doc, json));
    readSync(doc.as<JsonObjectConst>(), facts.sync);
    facts.sessionAuthorized = facts.sync.sessionPresent;
    facts.reserved = facts.sync.reservationPresent;
  }
  void step(uint32_t dt = 0) { now += dt; facts.nowMs = now; flow.facts(facts); }
  ApiRequest take() { ApiRequest r; assert(flow.takeRequest(r)); return r; }
  bool hasRequest() { ApiRequest r; if (!flow.takeRequest(r)) return false; inFlightReply(r); return true; }
  void inFlightReply(const ApiRequest& r) { reply(r, 0, ""); }   // descarta (sem rede)
  void reply(const ApiRequest& r, int status, const std::string& body) {
    ApiResult result; result.kind = r.kind; result.seq = r.seq; result.status = status; result.body = body.c_str();
    flow.apiResult(result);
    // Legacy scenario helpers traverse the new optional stages. Dedicated tests below
    // drive the raw Flow to assert every new stage independently.
    if (r.kind == RequestKind::Offer && flow.state() == State::Connector) flow.touch(Action::Next, now);
    if (r.kind == RequestKind::Quote && flow.state() == State::PaymentMethod) flow.touch(Action::PayCard, now);
  }
  void touch(Action a) {
    flow.touch(a, now);
    if (a == Action::StartFlow && flow.state() == State::Welcome) flow.touch(Action::Guest, now);
    if (flow.state() == State::Power && (a == Action::Shortcut0 || a == Action::Shortcut1 || a == Action::Shortcut2 || a == Action::Shortcut3 || a == Action::KeypadOk))
      flow.touch(Action::PowerMax, now);
  }
  void keys(const char* sequence) { for (const char* c = sequence; *c; ++c) flow.key(*c, now); }
  const KioskView& view() const { return flow.view(); }
  std::string persisted() { char out[64] = "?"; return flow.takePersist(out, sizeof(out)) ? std::string(out) : std::string("<none>"); }

  // Atalhos de cenário.
  void toChoose(const char* method = "simulated", const char* label = "SIMULADO") {
    assert(flow.canStart());
    touch(Action::StartFlow);
    assert(flow.state() == State::LoadingOffer && view().screen == Screen::Notice && view().busy);
    ApiRequest r = take();
    assert(r.kind == RequestKind::Offer && std::string(r.method) == "GET" && std::string(r.path) == "/v1/devices/kiosk/offer");
    reply(r, 200, offerJson(method, label));
    assert(flow.state() == State::Choose && view().options[0].enabled);
  }
  void toReview(const char* method = "simulated", const char* label = "SIMULADO") {
    toChoose(method, label);
    touch(Action::ModeValue);
    assert(flow.state() == State::Amount);
    touch(Action::Shortcut1);
    ApiRequest r = take();
    assert(r.kind == RequestKind::Quote && std::string(r.path) == "/v1/devices/kiosk/quote");
    assert(std::string(r.body) == R"({"mode":"value","power":"max","amount":20})");
    reply(r, 200, quoteJson(method, label));
    assert(flow.state() == State::Review);
  }
  ApiRequest acceptOrder(const char* method = "simulated") {
    touch(Action::Accept);
    ApiRequest r = take();
    assert(r.kind == RequestKind::CreateOrder && std::string(r.method) == "POST" && std::string(r.path) == "/v1/devices/kiosk/orders");
    assert(std::strncmp(r.idempotencyKey, "ko-", 3) == 0 && std::strlen(r.idempotencyKey) == 19);
    assert(std::string(r.body) == R"({"mode":"value","power":"max","amount":20,"quote_hash":"0123456789abcdef0123456789abcdef","overstay_terms_version":"ov-3"})");
    reply(r, 201, orderJson("held", method));
    assert(flow.state() == State::Pay);
    assert(persisted() == kOrderId);   // NVS "kord"
    return r;
  }
  void charging(bool on, const char* origin = "kiosk_totem", const char* order = "null") {
    facts.charging = on; facts.pointReady = false;
    std::snprintf(facts.sessionId, sizeof(facts.sessionId), "%s", on ? kSessionId : "");
    sync(syncJson(true, facts.sync.kiosk.method == Method::Stripe ? "stripe" : "simulated", order, on, origin));
  }
};

std::string text(const char* value) { return value ? value : ""; }

void testReadSync() {
  SyncFacts out;
  JsonDocument doc;
  // API antiga / totem desligado: chave inexistente.
  deserializeJson(doc, syncJson(false)); readSync(doc.as<JsonObjectConst>(), out);
  assert(!out.kiosk.present && !out.kiosk.enabled && !out.order.present && out.sessionOrigin[0] == '\0');
  // Bloco nulo, booleano em texto, método desconhecido ou nulo: desligado.
  const char* invalid[] = {
      R"({"connector":{"kiosk":null},"authorized":{"session":null}})",
      R"({"connector":{"kiosk":{"enabled":"true","method":"simulated"}},"authorized":{}})",
      R"({"connector":{"kiosk":{"enabled":true,"method":"voucher","label":"X"}},"authorized":{}})",
      R"({"connector":{"kiosk":{"enabled":true,"method":null,"label":null,"reason":"payments_unavailable"}},"authorized":{}})",
      R"({"connector":{"kiosk":[]},"kiosk_order":{"id":""},"authorized":{"session":{"id":"s","origin":"hacker"}}})",
  };
  for (const char* json : invalid) {
    doc.clear(); assert(!deserializeJson(doc, json)); readSync(doc.as<JsonObjectConst>(), out);
    assert(!out.kiosk.enabled && !out.order.present && out.sessionOrigin[0] == '\0');
  }
  doc.clear(); deserializeJson(doc, syncJson(true, "stripe", kioskOrder("finished", "completed", nullptr, true, true, "stripe").c_str(), true, "app"));
  readSync(doc.as<JsonObjectConst>(), out);
  assert(out.kiosk.enabled && out.kiosk.method == Method::Stripe && text(out.kiosk.label) == "TESTE");
  assert(out.order.present && text(out.order.id) == kOrderId && text(out.order.status) == "finished");
  assert(text(out.order.paymentStatus) == "completed" && out.order.paymentMethod == Method::Stripe);
  assert(out.order.receipt.present && out.order.receipt.final && text(out.order.receipt.number) == "1A2B3C4D");
  assert(out.order.receipt.totalCents == 500 && out.order.receipt.returnedCents == 4500);
  assert(out.order.receipt.energyKwh > 2.49f && out.order.receipt.energyKwh < 2.51f);
  assert(text(out.order.receipt.url) == kReceiptUrl && text(out.order.receipt.endReason) == "requested");
  assert(text(out.sessionOrigin) == "app" && out.sessionPresent && text(out.sessionId) == kSessionId);
  // QR do pedido: só https até 160 caracteres.
  doc.clear(); deserializeJson(doc, syncJson(true, "stripe", kioskOrder("awaiting_payment", "awaiting_payment", "javascript:alert(1)", false, false, "stripe").c_str()));
  readSync(doc.as<JsonObjectConst>(), out);
  assert(out.order.present && out.order.qrUrl[0] == '\0');
  doc.clear(); deserializeJson(doc, syncJson(true, "stripe", kioskOrder("awaiting_payment", "awaiting_payment", kQr, false, false, "stripe").c_str()));
  readSync(doc.as<JsonObjectConst>(), out);
  assert(text(out.order.qrUrl) == kQr);
  puts("PASS: sync blocks connector.kiosk / kiosk_order / session.origin (absent, null, invalid, valid)");
}

void testLegacyApi() {
  Harness h;
  h.sync(syncJson(false)); h.step();   // API antiga: sem connector.kiosk
  assert(h.flow.state() == State::Off && !h.flow.canStart() && h.view().screen == Screen::None);
  h.touch(Action::StartFlow);
  assert(!h.hasRequest() && h.flow.state() == State::Off);
  // API com o bloco mas sem as rotas (404 sem kiosk_disabled): desliga por 10 min.
  Harness old;
  old.touch(Action::StartFlow);
  ApiRequest r = old.take();
  old.reply(r, 404, R"({"detail":"Not Found"})");
  assert(old.flow.state() == State::Off && old.flow.apiUnsupported() && !old.flow.canStart());
  old.step(60000); assert(old.flow.state() == State::Off);
  old.step(600000); assert(old.flow.state() == State::Idle && old.flow.canStart());
  // Totem desligado no posto (404 kiosk_disabled): aviso, sem desligar por 10 min.
  Harness disabled;
  disabled.touch(Action::StartFlow);
  r = disabled.take();
  disabled.reply(r, 404, R"({"error":{"code":"kiosk_disabled","message":"Totem desligado"}})");
  assert(disabled.flow.state() == State::Notice && !disabled.flow.apiUnsupported());
  puts("PASS: older API (no connector.kiosk, 404 routes) keeps the totem off; kiosk_disabled shows a notice");
}

void testHappySimulated() {
  Harness h;
  assert(h.flow.state() == State::Idle && h.flow.canStart() && h.view().screen == Screen::None);
  h.toReview();
  const KioskView& review = h.view();
  assert(review.screen == Screen::Review && text(review.label) == "SIMULADO");
  assert(text(review.metrics[0].value) == "R$ 2,30/kWh");
  assert(text(review.metrics[1].value) == "R$ 2,00 x 1,15 Alta demanda");
  assert(text(review.metrics[2].name) == "VALOR MÁXIMO" && text(review.metrics[2].value) == "R$ 50,00");
  assert(text(review.metrics[3].value) == "8,7 kWh" && text(review.metrics[4].value) == "73 min");
  assert(text(review.context).find("R$ 1,00 por minuto") != std::string::npos);
  assert(review.primary.action == Action::Accept && review.primary.enabled);
  h.acceptOrder();
  // T4 simulado: o totem não paga sozinho; botão rotulado (sem cobrança).
  assert(h.view().screen == Screen::Pay && text(h.view().primary.text) == "Já efetuei o pagamento");
  assert(text(h.view().qr) == kQr && !h.hasRequest());
  h.touch(Action::SimulatePay);
  ApiRequest pay = h.take();
  assert(pay.kind == RequestKind::Pay && std::string(pay.path) == std::string("/v1/devices/kiosk/orders/") + kOrderId + "/pay");
  assert(std::string(pay.idempotencyKey) == std::string("pay-") + kOrderId && std::string(pay.body) == R"({"funding_source":"card"})");
  h.reply(pay, 200, orderJson("charging", "simulated", R"J({"id":"p","status":"in_use","label":"Pago (simulado) · em uso","method":"simulated","amount":"50.00","qr_url":null})J"));
  assert(h.flow.state() == State::Starting && h.view().screen == Screen::Starting);
  // START aplicado (sessão do pedido) -> T6 ao vivo.
  h.charging(true, "kiosk_totem", kioskOrder("charging", "in_use").c_str());
  h.facts.energyKwh = 1.25f; h.facts.costCents = 288; h.facts.capCents = 2000; h.facts.appliedPowerKw = 6.0f;
  h.facts.elapsedS = 600; h.facts.remainingS = 3000; h.facts.socPercent = 47.6f;
  std::snprintf(h.facts.powerReason, sizeof(h.facts.powerReason), "Loja 24/30 kW \xC2\xB7 3 carros");
  h.step(1000);
  assert(h.flow.state() == State::Live && h.view().screen == Screen::Live);
  assert(text(h.view().metrics[0].value) == "1,25 kWh" && text(h.view().metrics[1].value) == "6,0 kW");
  assert(text(h.view().metrics[2].value) == "R$ 2,88 / R$ 20,00" && text(h.view().metrics[3].value) == "10 min / faltam 50");
  assert(text(h.view().metrics[4].value) == "47%" && text(h.view().subtitle) == "Para parar antes, toque em Encerrar." &&
         text(h.view().context) == "Potência: Loja 24/30 kW \xC2\xB7 3 carros");
  assert(!h.hasRequest());   // nada de rede durante a recarga
  // Encerrar com confirmação (T7); Não volta; Sim pede requestLocalSafeStop().
  const KioskView live = h.view();
  h.touch(Action::Stop); assert(h.flow.state() == State::ConfirmStop && h.view().screen == Screen::ConfirmStop);
  assert(text(h.view().title) == text(live.title) && h.view().socPercent == live.socPercent);
  for (int i = 0; i < live.metricCount; ++i) assert(text(h.view().metrics[i].value) == live.metrics[i].value);
  h.touch(Action::ConfirmNo); assert(h.flow.state() == State::Live && !h.flow.takeLocalStop());
  h.touch(Action::Stop); h.touch(Action::ConfirmYes);
  assert(h.flow.takeLocalStop() && !h.flow.takeLocalStop());
  h.facts.charging = false; h.facts.stopped = true; std::snprintf(h.facts.endReason, sizeof(h.facts.endReason), "requested");
  h.sync(syncJson(true, "simulated", kioskOrder("finished", "in_use", nullptr, true, false).c_str()));
  h.step(1000);
  assert(h.flow.state() == State::Receipt && h.view().screen == Screen::Receipt);
  assert(text(h.view().title) == "Recarga concluída" && text(h.view().subtitle) == "Calculando o recibo");
  h.sync(syncJson(true, "simulated", kioskOrder("finished", "completed", nullptr, true, true).c_str()));
  h.step(1000);
  assert(text(h.view().metrics[0].value) == "2,50 kWh" && text(h.view().metrics[1].value) == "R$ 5,00");
  assert(text(h.view().metrics[2].value) == "Simulado, sem cobrança" && text(h.view().metrics[3].value) == "1A2B3C4D");
  assert(text(h.view().qr) == kReceiptUrl && text(h.view().subtitle) == "Escaneie para ver o recibo completo.");
  h.touch(Action::Done);
  assert(h.flow.state() == State::Idle && h.persisted() == "");   // NVS limpa
  puts("PASS: happy path, simulated method (offer, quote, order + kord, simulated pay, START, live, confirm stop, receipt QR)");
}

void testHappyStripe() {
  Harness h("stripe");
  h.toReview("stripe", "TESTE");
  assert(text(h.view().label) == "TESTE");
  h.acceptOrder("stripe");
  // Stripe: o pagamento (e o QR) é pedido logo ao entrar em T4.
  ApiRequest pay = h.take();
  assert(pay.kind == RequestKind::Pay && std::string(pay.idempotencyKey) == std::string("pay-") + kOrderId);
  assert(h.view().screen == Screen::Pay && h.view().qr[0] == '\0' && h.view().busy);
  h.reply(pay, 200, orderJson("awaiting_payment", "stripe",
      (std::string(R"J({"id":"p","status":"awaiting_payment","label":"Aguardando (teste)","method":"stripe","amount":"50.00","qr_url":")J") + kQr + "\"}").c_str(), 600));
  assert(h.flow.state() == State::Pay && text(h.view().qr) == kQr && h.view().notice[0]);
  assert(text(h.view().qrCaption) == "Total: R$ 50,00");
  assert(h.view().primary.visible && text(h.view().primary.text) == "Já efetuei o pagamento");
  h.touch(Action::SimulatePay); ApiRequest check = h.take();
  assert(check.kind == RequestKind::GetOrder && text(check.method) == "GET");
  h.reply(check, 200, orderJson("awaiting_payment", "stripe"));
  assert(h.flow.state() == State::Pay && !h.flow.order().paid); // botão jamais confirma Stripe localmente
  // QR não vence pela inatividade de 60 s: só quando a trava acaba (10 min).
  h.step(120000); assert(h.flow.state() == State::Pay);
  h.sync(syncJson(true, "stripe", kioskOrder("awaiting_payment", "declined", kQr, false, false, "stripe").c_str()));
  h.step(1000); assert(text(h.view().notice) == "Pagamento recusado. Tente de novo pelo QR.");
  h.sync(syncJson(true, "stripe", kioskOrder("paid", "authorized", nullptr, false, false, "stripe").c_str()));
  h.step(1000);
  assert(h.flow.state() == State::Starting);
  h.charging(true, "kiosk_totem", kioskOrder("charging", "in_use", nullptr, false, false, "stripe").c_str());
  h.step(1000); assert(h.flow.state() == State::Live);
  // Parada automática (limite de valor) -> recibo com valor devolvido.
  h.facts.charging = false; h.facts.stopped = true; std::snprintf(h.facts.endReason, sizeof(h.facts.endReason), "cost_limit");
  h.sync(syncJson(true, "stripe", kioskOrder("finished", "completed", nullptr, true, true, "stripe").c_str()));
  h.step(1000);
  assert(h.flow.state() == State::Receipt && text(h.view().title) == "Valor máximo atingido");
  assert(text(h.view().metrics[2].name) == "DEVOLVIDO" && text(h.view().metrics[2].value) == "R$ 45,00");
  // Recibo volta sozinho em 60 s (sem carro conectado).
  h.step(29000); assert(h.flow.state() == State::Receipt && text(h.view().qrCaption) == "Saindo em 1 segundo");
  h.touch(Action::Continue); // touching cannot extend privacy timeout
  h.step(2000); assert(h.flow.state() == State::Idle && h.persisted() == "");
  // Trava do QR vence: cancela (libera e devolve) e volta ao início.
  Harness q("stripe");
  q.toReview("stripe", "TESTE"); q.acceptOrder("stripe");
  ApiRequest p = q.take();
  q.reply(p, 200, orderJson("awaiting_payment", "stripe",
      (std::string(R"({"status":"awaiting_payment","method":"stripe","qr_url":")") + kQr + "\"}").c_str(), 600));
  q.step(599000); assert(q.flow.state() == State::Pay);
  q.step(2000);
  assert(q.flow.state() == State::Notice);
  ApiRequest cancel = q.take();
  assert(cancel.kind == RequestKind::Cancel && std::string(cancel.path) == std::string("/v1/devices/kiosk/orders/") + kOrderId + "/cancel");
  assert(q.persisted() == "");
  puts("PASS: happy path, Stripe method (QR from POST pay, status via sync, declined, START, cost_limit receipt, QR lock expiry cancels)");
}

void testKeypad() {
  Harness h;
  h.toChoose();
  h.touch(Action::ModeValue);
  h.touch(Action::OtherValue);
  assert(h.view().keypad && !h.view().decimalKey && text(h.view().entryUnit) == "R$");
  assert(!h.view().primary.enabled);           // OK sem valor
  h.keys("0150");                               // zero à esquerda some
  assert(text(h.view().entry) == "150" && h.view().primary.enabled);
  h.keys(",");                                  // vírgula só em kWh
  assert(text(h.view().entry) == "150");
  h.keys("B"); assert(text(h.view().entry) == "15");
  h.keys("C"); assert(text(h.view().entry).empty());
  h.keys("3"); h.touch(Action::KeypadOk);       // abaixo do mínimo da oferta (R$ 5,00)
  assert(!h.hasRequest() && text(h.view().notice) == "Valor fora do limite: R$ 5,00 a R$ 170,00");
  h.keys("C"); h.keys("99999"); assert(text(h.view().entry) == "9999");   // no máximo 4 dígitos
  h.touch(Action::KeypadOk); assert(!h.hasRequest());   // acima de R$ 170,00
  h.keys("C"); h.keys("25"); h.touch(Action::KeypadOk);
  ApiRequest r = h.take();
  assert(std::string(r.body) == R"({"mode":"value","power":"max","amount":25})");
  h.reply(r, 0, "");                            // sem resposta: fica em T2 com aviso
  assert(h.flow.state() == State::Amount && text(h.view().notice) == "Sem resposta do servidor. Tente de novo.");
  h.touch(Action::Back); assert(!h.view().keypad && h.flow.state() == State::Amount);
  h.touch(Action::Back); assert(h.flow.state() == State::Choose);
  // kWh: uma vírgula, uma casa decimal.
  h.touch(Action::ModeEnergy); h.touch(Action::OtherValue);
  assert(h.view().decimalKey && text(h.view().entryUnit) == "kWh");
  h.keys(",5"); assert(text(h.view().entry) == "0,5");
  h.keys("C"); h.keys("12,57,"); assert(text(h.view().entry) == "12,5");
  h.touch(Action::KeypadOk);
  r = h.take();
  assert(std::string(r.body) == R"({"mode":"energy","power":"max","energy_kwh":12.5})");
  h.reply(r, 422, R"({"error":{"code":"amount_above_limit","message":"x"}})");
  assert(h.flow.state() == State::Amount && text(h.view().notice) == "Valor fora do limite: 1 kWh a 73,9 kWh");
  // Minutos: atalhos e corpo inteiro.
  h.touch(Action::Back); h.touch(Action::Back); h.touch(Action::ModeTime);
  assert(text(h.view().options[0].text) == "15 min" && text(h.view().options[2].text) == "60 min" && !h.view().options[3].visible);
  h.touch(Action::Shortcut1);
  r = h.take(); assert(std::string(r.body) == R"({"mode":"time","power":"max","minutes":30})");
  puts("PASS: numeric keypad (digits, leading zero, comma only in kWh, backspace, clear, min/max, 422) and shortcuts per mode");
}

void testInactivity() {
  Harness h;
  h.toChoose();
  h.step(49000); assert(!h.view().stillThere);
  h.step(1000); assert(h.view().stillThere && h.flow.state() == State::Choose);
  h.touch(Action::Continue); assert(!h.view().stillThere);
  h.step(59000); assert(h.flow.state() == State::Choose);
  h.step(1000); assert(h.flow.state() == State::Idle && !h.hasRequest());
  // T3: 90 s (aviso aos 80 s); nada a cancelar (sem pedido).
  h.toReview();
  h.step(80000); assert(h.view().stillThere);
  h.step(10000); assert(h.flow.state() == State::Idle && !h.hasRequest());
  // T4 simulado: 60 s -> cancela o pedido (libera a trava) e volta.
  h.toReview(); h.acceptOrder();
  h.step(50000); assert(h.view().stillThere && h.flow.state() == State::Pay);
  h.step(10000);
  assert(h.flow.state() == State::Notice && text(h.view().title) == "Pedido cancelado");
  ApiRequest cancel = h.take();
  assert(cancel.kind == RequestKind::Cancel && std::string(cancel.idempotencyKey) == std::string("cancel-") + kOrderId);
  h.reply(cancel, 200, orderJson("canceled", "simulated"));
  assert(h.persisted() == "");
  h.step(6000); assert(h.flow.state() == State::Idle);
  // Cancelar em T4 também cancela na hora.
  h.toReview(); h.acceptOrder();
  h.touch(Action::Cancel);
  assert(h.flow.state() == State::Notice && h.take().kind == RequestKind::Cancel);
  h.step(6000);
  // T7 volta sozinho em 10 s.
  h.charging(true, "app"); h.step();
  h.touch(Action::Stop); assert(h.flow.state() == State::ConfirmStop);
  h.step(10000); assert(h.flow.state() == State::Idle && !h.flow.takeLocalStop());
  puts("PASS: inactivity (prompt at 50/80 s, 60/90 s back to start, simulated T4 cancels the order, T7 returns in 10 s)");
}

void testBlockedAndAbort() {
  // App inicia durante T1, T2 e T3: aborta sem cobrar (sem pedido, sem cancel).
  for (int stage = 1; stage <= 3; ++stage) {
    Harness h;
    h.toChoose();
    if (stage >= 2) h.touch(Action::ModeValue);
    if (stage == 3) { h.touch(Action::Shortcut1); ApiRequest r = h.take(); h.reply(r, 200, quoteJson("simulated", "SIMULADO")); }
    h.charging(true, "app"); h.step(500);
    assert(h.flow.state() == State::Notice && text(h.view().title) == "Ponto iniciado pelo app");
    assert(text(h.view().subtitle) == "Este ponto acabou de ser iniciado pelo app. Nada foi cobrado.");
    assert(!h.hasRequest() && h.persisted() == "<none>");
  }
  // Sessão autorizada (antes do START) também aborta.
  Harness s; s.toChoose();
  s.sync(syncJson(true, "simulated", "null", true, "app")); s.step();
  assert(s.flow.state() == State::Notice);
  // Reserva chega durante T2.
  Harness r; r.toChoose(); r.touch(Action::ModeTime);
  r.sync(syncJson(true, "simulated", "null", false, "", true)); r.step();
  assert(r.flow.state() == State::Notice && text(r.view().title) == "Ponto reservado");
  // Reserva / carro conectado / manutenção / sessão: botão "Iniciar recarga" desativado.
  Harness b;
  b.facts.reserved = true; b.step(); assert(!b.flow.canStart());
  b.facts.reserved = false; b.facts.carConnected = true; b.step(); assert(!b.flow.canStart());
  b.facts.carConnected = false; b.facts.maintenance = true; b.step(); assert(!b.flow.canStart());
  b.facts.maintenance = false; b.facts.pointReady = false; b.step(); assert(!b.flow.canStart());
  b.facts.pointReady = true; b.step(); assert(b.flow.canStart());
  // Oferta diz ponto ocupado (cabo) ou reservado.
  Harness o; o.touch(Action::StartFlow);
  ApiRequest offer = o.take(); o.reply(offer, 200, offerJson("simulated", "SIMULADO", false, "\"occupied\""));
  assert(o.flow.state() == State::Notice && text(o.view().title) == "Ponto indisponível");
  // Método desconhecido na oferta: o totem nunca escolhe sozinho.
  Harness m; m.touch(Action::StartFlow);
  offer = m.take(); m.reply(offer, 200, offerJson("voucher", "X"));
  assert(m.flow.state() == State::Notice && text(m.view().title) == "Totem indisponível");
  // Recarga do app: Encerrar no totem com confirmação.
  Harness a; a.charging(true, "app"); a.step();
  assert(!a.flow.canStart());
  a.touch(Action::Stop);
  assert(a.flow.state() == State::ConfirmStop && text(a.view().title) == "Recarga em andamento" && text(a.view().context).find("iniciada pelo app") != std::string::npos);
  a.touch(Action::ConfirmYes);
  assert(a.flow.takeLocalStop() && a.flow.state() == State::Idle);
  puts("PASS: app start/session/reservation during T1-T3 aborts, reservation/car/maintenance block the button, app session stop with confirmation");
}

void testOfflineAndNetworkDrops() {
  // Sem rede: botão desativado; queda em T2 volta ao início (nada cobrado).
  Harness h;
  h.facts.online = false; h.step(); assert(!h.flow.canStart());
  h.facts.online = true; h.step();
  h.toChoose(); h.touch(Action::ModeValue);
  h.facts.online = false; h.step();
  assert(h.flow.state() == State::Notice && text(h.view().title) == "Sem conexão" && !h.hasRequest());
  // Oferta sem resposta.
  h.facts.online = true; h.step(6000);
  assert(h.flow.state() == State::Notice && h.view().primary.action == Action::Retry);
  h.touch(Action::Done);
  h.touch(Action::StartFlow); ApiRequest offer = h.take(); h.reply(offer, 0, "");
  assert(h.flow.state() == State::Notice);
  h.step(6000);
  // Queda em T4: "Verificando pagamento"; volta pelo sync com o QR ainda válido.
  Harness s("stripe");
  s.toReview("stripe", "TESTE"); s.acceptOrder("stripe");
  ApiRequest pay = s.take(); s.reply(pay, 0, "");   // sem resposta do POST pay
  assert(s.flow.state() == State::Pay && s.view().primary.action == Action::Retry);
  s.facts.online = false; s.step(1000);
  assert(s.flow.state() == State::Verifying && text(s.view().subtitle) == "Sem conexão. Seu pedido está guardado no servidor.");
  s.facts.online = true;
  s.sync(syncJson(true, "stripe", kioskOrder("awaiting_payment", "awaiting_payment", kQr, false, false, "stripe").c_str()));
  s.step(1000);
  assert(s.flow.state() == State::Pay && text(s.view().qr) == kQr && !s.hasRequest());
  // Queda em T5: retoma pelo sync quando a recarga já começou.
  s.sync(syncJson(true, "stripe", kioskOrder("paid", "authorized", nullptr, false, false, "stripe").c_str())); s.step(1000);
  assert(s.flow.state() == State::Starting);
  s.facts.online = false; s.step(1000); assert(s.flow.state() == State::Verifying);
  s.facts.online = true; s.charging(true, "kiosk_totem", kioskOrder("charging", "in_use", nullptr, false, false, "stripe").c_str());
  s.step(1000); assert(s.flow.state() == State::Live);
  // Queda em T6: o vigia de 45 s para (communication_lost) -> recibo "em conferência".
  s.facts.online = false; s.step(1000); assert(s.flow.state() == State::Live);
  s.facts.charging = false; s.facts.stopped = true;
  std::snprintf(s.facts.endReason, sizeof(s.facts.endReason), "communication_lost");
  s.step(45000);
  assert(s.flow.state() == State::Receipt && text(s.view().title) == "Recarga parada por segurança");
  assert(text(s.view().subtitle) == "Sem conexão. Recibo em conferência.");
  assert(text(s.view().qr) == kReceiptUrl);   // receipt_url do pedido já vale
  // Carro conectado (permanência): sem volta automática; Desconectar.
  s.facts.carConnected = true;
  std::snprintf(s.facts.overstayTitle, sizeof(s.facts.overstayTitle), "Recarga concluída \xC2\xB7 desconecte em 09:59");
  std::snprintf(s.facts.overstayDetail, sizeof(s.facts.overstayDetail), "Após a tolerância: R$ 1,00 a cada 1 min, até R$ 30,00.");
  s.step(120000);
  assert(s.flow.state() == State::Receipt && s.view().disconnect && text(s.view().subtitle).find("desconecte") != std::string::npos);
  assert(!s.view().qr[0]); // QR privado nunca permanece com o carro conectado após 30 s
  s.touch(Action::Disconnect); assert(s.flow.takeLocalDisconnect());
  s.facts.carConnected = false; s.step(60000);
  assert(s.flow.state() == State::Idle);
  puts("PASS: offline blocks the button, network drop in T2 (back to start), T4 (verifying, QR again via sync), T5 (resumes to live), T6 (receipt in review), overstay integration");
}

void testMissingChargersAndRetry() {
  Harness h;
  h.facts.chargerOffline = true; h.step();
  assert(!h.flow.canStart());
  h.facts.chargerOffline = false; h.step();
  h.touch(Action::StartFlow);
  assert(h.view().screen == Screen::Notice && h.view().metricCount == 0 && !h.view().options[0].visible);
  ApiRequest request = h.take();
  JsonDocument doc; deserializeJson(doc, offerJson("simulated", "SIMULADO", false, "\"offline\""));
  auto choices = doc["connectors"].to<JsonArray>();
  for (int address : {0, 2}) {
    auto c = choices.add<JsonObject>(); c["address"] = address; c["available"] = false;
    c["label"] = "Carregador sem resposta";
  }
  std::string offline; serializeJson(doc, offline);
  h.reply(request, 200, offline);
  assert(h.flow.state() == State::Notice && text(h.view().title) == "Carregador indisponível");
  assert(h.view().primary.action == Action::Retry && h.view().secondary.action == Action::Done);
  h.step(6000);
  assert(h.flow.state() == State::Notice); // Permite ler e recuperar, sem voltar sozinho em 6 s.
  h.touch(Action::Retry); request = h.take();
  assert(request.kind == RequestKind::Offer && !h.flow.order().id[0]);
  h.reply(request, 200, offerJson("simulated", "SIMULADO"));
  assert(h.flow.state() == State::Choose);
  h.touch(Action::ModeValue);
  h.facts.chargerOffline = true; h.step();
  assert(h.flow.state() == State::Notice && text(h.view().title) == "Carregador indisponível");
  h.facts.chargerOffline = false; h.step(6000);
  h.touch(Action::Retry); request = h.take();
  h.reply(request, 200, offerJson("simulated", "SIMULADO"));
  assert(h.flow.state() == State::Choose);
  h.facts.chargerOffline = true; h.step();
  h.step(Flow::kIdleTimeoutMs);
  assert(h.flow.state() == State::Idle && !h.flow.authToken()[0]);
  puts("PASS: central online/charger offline, all chargers unavailable, explicit retry, restored charger, no zero-value loading screen, private inactivity timeout");
}

void testSharedAppSessionScreens() {
  Harness h;
  h.flow.followAppSessions();
  h.sync(syncJson(false)); h.step();
  assert(h.flow.state() == State::Off); // Funciona mesmo sem autoatendimento no posto.
  h.charging(true, "app");
  h.facts.energyKwh = 2.5; h.facts.costCents = 575; h.facts.capCents = 2000;
  h.facts.appliedPowerKw = 7.2; h.facts.elapsedS = 1200; h.facts.remainingS = 600; h.facts.socPercent = 41;
  h.step();
  assert(h.flow.state() == State::Live && h.view().screen == Screen::Live);
  assert(text(h.view().title) == "Recarga em andamento" && text(h.view().metrics[0].value) == "2,50 kWh");
  h.touch(Action::Stop); assert(h.flow.state() == State::ConfirmStop);
  h.touch(Action::ConfirmNo); assert(h.flow.state() == State::Live);
  h.touch(Action::Stop); h.touch(Action::ConfirmYes); assert(h.flow.takeLocalStop());
  h.facts.charging = false; h.facts.stopped = true; h.facts.appliedPowerKw = 0;
  std::snprintf(h.facts.endReason, sizeof(h.facts.endReason), "requested");
  h.step(); assert(h.flow.state() == State::Receipt && h.view().screen == Screen::Receipt);
  h.facts.sessionId[0] = 0; h.facts.energyKwh = 0; h.facts.costCents = -1;
  h.step(1000);
  assert(text(h.view().metrics[0].value) == "2,50 kWh" && text(h.view().metrics[1].value) == "R$ 5,75");
  assert(!h.view().qr[0] && !h.hasRequest()); // Sem pedido de pagamento/recibo inventado.
  h.touch(Action::Done); assert(h.flow.state() == State::Idle);
  h.flow.followAppCharger(2); h.charging(true, "app"); h.step();
  assert(h.flow.state() == State::Live && h.flow.chargerAddress() == 2);
  h.touch(Action::Stop); h.touch(Action::ConfirmYes); assert(h.flow.takeLocalStop() && h.flow.chargerAddress() == 2);
  puts("PASS: shared app/self-service Live/Receipt renderer, app stop confirmation, final values retained after reconciliation, additional charger addressing");
}

void testRebootResume() {
  // Reboot com kord na NVS: verifica pelo GET e retoma.
  Harness h;
  h.flow.resume(kOrderId, h.now);
  assert(h.flow.state() == State::Verifying && h.view().screen == Screen::Verifying);
  h.step(100);
  ApiRequest get = h.take();
  assert(get.kind == RequestKind::GetOrder && std::string(get.method) == "GET" &&
         std::string(get.path) == std::string("/v1/devices/kiosk/orders/") + kOrderId);
  h.reply(get, 200, orderJson("paid", "simulated"));
  assert(h.flow.state() == State::Starting);
  // Pago sem START no prazo (60 s): aviso "valor devolvido" e cancelamento.
  h.step(60000);
  assert(h.flow.state() == State::Notice && text(h.view().title) == "Não foi possível iniciar");
  assert(h.take().kind == RequestKind::Cancel);
  // Pedido desconhecido: limpa e volta ao início.
  Harness u; u.flow.resume(kOrderId, u.now); u.step();
  get = u.take(); u.reply(get, 404, R"({"error":{"code":"not_found","message":"x"}})");
  assert(u.flow.state() == State::Idle && u.persisted() == "");
  // Retomada pelo bloco do sync (pedido aguardando pagamento Stripe: QR redesenhado).
  Harness s("stripe");
  s.flow.resume(kOrderId, s.now);
  s.sync(syncJson(true, "stripe", kioskOrder("awaiting_payment", "awaiting_payment", kQr, false, false, "stripe").c_str()));
  s.step();
  assert(s.flow.state() == State::Pay && text(s.view().qr) == kQr && !s.hasRequest());
  // Sem QR no bloco: pede o mesmo pagamento de novo (Idempotency-Key derivada do pedido).
  Harness n("stripe");
  n.flow.resume(kOrderId, n.now);
  n.sync(syncJson(true, "stripe", kioskOrder("held").c_str())); n.step();
  ApiRequest pay = n.take();
  assert(n.flow.state() == State::Pay && pay.kind == RequestKind::Pay && std::string(pay.idempotencyKey) == std::string("pay-") + kOrderId);
  // Reboot durante a recarga: o painel volta parado; o servidor fecha -> recibo.
  Harness r;
  r.flow.resume(kOrderId, r.now);
  r.facts.stopped = true; std::snprintf(r.facts.endReason, sizeof(r.facts.endReason), "communication_lost");
  r.sync(syncJson(true, "simulated", kioskOrder("finished", "in_use", nullptr, true, false).c_str()));
  r.step();
  assert(r.flow.state() == State::Receipt && text(r.view().metrics[3].value) == "1A2B3C4D");
  // Pedido cancelado/expirado no servidor.
  Harness c; c.flow.resume(kOrderId, c.now);
  c.sync(syncJson(true, "simulated", kioskOrder("expired").c_str())); c.step();
  assert(c.flow.state() == State::Notice && text(c.view().title) == "Pedido cancelado");
  // Falha ao iniciar informada pelo servidor.
  Harness f; f.flow.resume(kOrderId, f.now);
  f.sync(syncJson(true, "simulated", kioskOrder("failed", "in_use").c_str())); f.step();
  assert(f.flow.state() == State::Notice && text(f.view().subtitle) == "O valor foi devolvido. Nada foi cobrado.");
  // Pedido aberto informado pela oferta (NVS perdida): retoma em vez de vender outro.
  Harness o;
  o.touch(Action::StartFlow);
  ApiRequest offer = o.take();
  o.reply(offer, 200, offerJson("simulated", "SIMULADO", false, "\"kiosk_in_use\"", (std::string("\"") + kOrderId + "\"").c_str()));
  assert(o.flow.state() == State::Verifying && text(o.flow.order().id) == kOrderId);
  puts("PASS: reboot resume by kord (GET order, unknown order, sync block with/without QR, finished, expired, failed, open order from offer)");
}

void testQuoteChangedAndErrors() {
  Harness h;
  h.toReview();
  h.touch(Action::Accept);
  ApiRequest order = h.take();
  const std::string firstKey = order.idempotencyKey;
  // Sem resposta: mesma chave na nova tentativa (sem pedido duplicado).
  h.reply(order, 0, "");
  assert(h.flow.state() == State::Review && text(h.view().notice) == "Não foi possível criar o pedido. Tente de novo.");
  h.touch(Action::Accept);
  order = h.take(); assert(firstKey == order.idempotencyKey);
  // 409 quote_changed com o orçamento novo no corpo do erro: refaz T3.
  const std::string fresh = quoteJson("simulated", "SIMULADO", "ffffffffffffffffffffffffffffffff");
  h.reply(order, 409, R"({"error":{"code":"quote_changed","message":"O preço mudou","quote":)" + fresh + "}}");
  assert(h.flow.state() == State::Review && text(h.view().notice) == "O preço mudou. Confira o novo valor.");
  assert(text(h.flow.quote().hash) == "ffffffffffffffffffffffffffffffff");
  h.touch(Action::Accept);
  order = h.take();
  assert(firstKey != order.idempotencyKey);   // novo orçamento, nova chave
  assert(std::string(order.body).find("ffffffffffffffffffffffffffffffff") != std::string::npos);
  // Sem o orçamento no erro: pede outro.
  h.reply(order, 409, R"({"error":{"code":"overstay_terms_changed","message":"x"}})");
  ApiRequest quote = h.take();
  assert(quote.kind == RequestKind::Quote && h.flow.state() == State::Review && !h.view().primary.enabled);
  h.reply(quote, 200, quoteJson("simulated", "SIMULADO"));
  assert(h.flow.state() == State::Review && h.view().primary.enabled && text(h.view().notice) == "O preço mudou. Confira o novo valor.");
  // Ponto travado por outro canal.
  h.touch(Action::Accept);
  order = h.take();
  h.reply(order, 409, R"({"error":{"code":"point_unavailable","message":"x","reason":"kiosk_in_use"}})");
  assert(h.flow.state() == State::Notice && text(h.view().subtitle) == "Ponto em uso no momento. Nada foi cobrado.");
  // Pedido já aberto neste ponto: retoma.
  Harness o; o.toReview(); o.touch(Action::Accept);
  order = o.take();
  o.reply(order, 409, (std::string(R"({"error":{"code":"order_open","message":"x","order_id":")") + kOrderId + "\"}}").c_str());
  assert(o.flow.state() == State::Verifying && text(o.flow.order().id) == kOrderId);
  // Resposta velha (seq diferente) é ignorada.
  Harness v; v.touch(Action::StartFlow);
  ApiRequest offer = v.take();
  ApiResult stale; stale.kind = RequestKind::Offer; stale.seq = offer.seq + 7; stale.status = 200;
  const std::string body = offerJson("simulated", "SIMULADO"); stale.body = body.c_str();
  v.flow.apiResult(stale); assert(v.flow.state() == State::LoadingOffer && v.flow.requestInFlight());
  v.reply(offer, 200, body); assert(v.flow.state() == State::Choose);
  // Um pedido por vez: nada novo enquanto um está em voo.
  v.touch(Action::ModeValue); v.touch(Action::Shortcut0);
  ApiRequest q1; assert(v.flow.takeRequest(q1));
  v.touch(Action::Shortcut2);
  ApiRequest q2; assert(!v.flow.takeRequest(q2));
  puts("PASS: quote_changed / overstay_terms_changed redo T3, same Idempotency-Key on retry, point_unavailable, order_open, stale results, one request at a time");
}



void testAddressedKioskFlow() {
  Harness h;
  h.touch(Action::StartFlow); ApiRequest offer = h.take();
  JsonDocument doc; deserializeJson(doc, offerJson("simulated", "SIMULADO"));
  JsonArray choices = doc["connectors"].to<JsonArray>();
  for (int address : {0, 2}) {
    JsonObject c = choices.add<JsonObject>(); c["address"] = address; c["available"] = true;
    c["label"] = address ? "Tipo 2 / CG-02" : "Tipo 2 / CG-01";
  }
  std::string payload; serializeJson(doc, payload);
  // Raw result leaves the connection selector on screen.
  ApiResult result; result.kind = offer.kind; result.seq = offer.seq; result.status = 200; result.body = payload.c_str();
  h.flow.apiResult(result);
  assert(h.flow.state() == State::Connector && h.view().options[1].action == Action::Connector1);
  h.touch(Action::Connector1); offer = h.take(); assert(offer.chargerAddress == 2);
  h.reply(offer, 200, payload); assert(h.flow.chargerAddress() == 2 && h.flow.state() == State::Choose);
  h.touch(Action::ModeValue); h.touch(Action::Shortcut1); ApiRequest quote = h.take(); assert(quote.chargerAddress == 2);
  h.reply(quote, 200, quoteJson("simulated", "SIMULADO")); h.acceptOrder();
  h.touch(Action::Cancel); h.touch(Action::Done);
  assert(h.flow.chargerAddress() == 0 && h.flow.state() == State::Idle);
  ApiRequest cancel = h.take(); assert(cancel.kind == RequestKind::Cancel && cancel.chargerAddress == 2);
  Harness reboot; reboot.flow.resume(kOrderId, reboot.now, 2); reboot.step();
  assert(reboot.flow.chargerAddress() == 2 && reboot.take().chargerAddress == 2);
  puts("PASS: addressed charger selection, quote/order target, cancellation survives home navigation and reboot restores the charger address");
}

void testOptionalAccountFlow() {
  Harness h;
  auto tap = [&](Action action) { h.flow.touch(action, h.now); };
  auto replyRaw = [&](const ApiRequest& request, int status, const std::string& payload) {
    ApiResult result; result.kind = request.kind; result.seq = request.seq;
    result.status = status; result.body = payload.c_str(); h.flow.apiResult(result);
  };
  tap(Action::StartFlow);
  assert(h.flow.state() == State::Welcome && !h.flow.requestInFlight());
  tap(Action::Login);
  assert(h.flow.state() == State::Login && !h.view().password);
  h.keys("driver@example.com"); tap(Action::LoginNext);
  assert(h.view().password && text(h.view().loginEntry).empty());
  h.keys("Strong2!\"\\");
  assert(text(h.view().loginEntry) == "**********");
  tap(Action::LoginNext);
  ApiRequest login = h.take();
  assert(login.kind == RequestKind::Login && text(login.path) == "/v1/auth/login");
  JsonDocument body; assert(!deserializeJson(body, login.body));
  assert(body["password"] == "Strong2!\"\\");
  assert(text(h.view().loginEntry).empty());
  replyRaw(login, 401, R"({"error":{"code":"auth_rejected"}})");
  assert(h.flow.state() == State::Login && !h.flow.authToken()[0]);
  h.keys("Correct2!"); tap(Action::LoginNext); login = h.take();
  replyRaw(login, 200, R"({"access_token":"short-lived-user-jwt","refresh_token":"must-not-be-kept"})");
  assert(text(h.flow.authToken()) == "short-lived-user-jwt");
  ApiRequest offer = h.take();
  JsonDocument offered; assert(!deserializeJson(offered, offerJson("simulated", "SIMULADO")));
  offered["account"]["name"] = "Marina";
  offered["account"]["vehicle"]["name"] = "BYD Dolphin";
  offered["account"]["wallet"]["balance"] = "100.00";
  offered["balance_available"] = true;
  std::string offeredBody; serializeJson(offered, offeredBody);
  replyRaw(offer, 200, offeredBody);
  assert(h.flow.state() == State::Connector); tap(Action::Next);
  assert(h.view().options[2].visible && h.view().options[2].action == Action::ModeAutonomy);
  tap(Action::ModeAutonomy); tap(Action::Shortcut1);
  assert(h.flow.state() == State::Power);
  assert(text(h.view().options[0].text).find("R$ 2,30/kWh") != std::string::npos);
  assert(text(h.view().options[1].text).find("R$ 1,84/kWh") != std::string::npos);
  tap(Action::PowerReduced);
  ApiRequest quote = h.take(); body.clear(); assert(!deserializeJson(body, quote.body));
  assert(body["mode"] == "autonomy" && body["autonomy_km"] == 60 && body["power"] == "reduced");
  replyRaw(quote, 200, quoteJson("simulated", "SIMULADO"));
  assert(h.flow.state() == State::PaymentMethod && h.view().options[2].enabled);
  tap(Action::PayBalance); assert(h.flow.state() == State::Review);
  tap(Action::Accept); ApiRequest order = h.take();
  replyRaw(order, 201, orderJson("held", "simulated")); tap(Action::SimulatePay);
  ApiRequest pay = h.take(); body.clear(); deserializeJson(body, pay.body);
  assert(body["funding_source"] == "balance");
  replyRaw(pay, 401, R"({"error":{"code":"unauthorized"}})");
  assert(h.flow.state() == State::Notice && !h.flow.authToken()[0]);
  ApiRequest cancel = h.take(); assert(cancel.kind == RequestKind::Cancel);
  replyRaw(cancel, 200, orderJson("canceled", "simulated"));
  tap(Action::Done); assert(h.flow.state() == State::Idle && !h.flow.authToken()[0]);

  // No car: autonomy remains absent; a forged local action cannot select it.
  tap(Action::StartFlow); tap(Action::Login); h.keys("driver@example.com"); tap(Action::LoginNext);
  h.keys("Correct2!"); tap(Action::LoginNext); login = h.take();
  replyRaw(login, 200, R"({"access_token":"user-jwt"})"); offer = h.take();
  offered["account"]["vehicle"] = nullptr; offeredBody.clear(); serializeJson(offered, offeredBody);
  replyRaw(offer, 200, offeredBody); tap(Action::Next);
  assert(h.view().options[2].visible && !h.view().options[2].enabled && text(h.view().options[2].text).find("requer carro") != std::string::npos); tap(Action::ModeAutonomy);
  assert(h.flow.state() == State::Choose);
  h.flow.tick(h.now + Flow::kIdleTimeoutMs);
  assert(!h.flow.authToken()[0] && h.flow.state() == State::Idle);
  puts("PASS: optional login, password masking/escaping, account vehicle gate, autonomy km, reduced power, balance, expired JWT cancellation and identity timeout");
}

}  // namespace

int main() {
  testAddressedKioskFlow();
  testOptionalAccountFlow();
  testReadSync();
  testLegacyApi();
  testHappySimulated();
  testHappyStripe();
  testKeypad();
  testInactivity();
  testBlockedAndAbort();
  testOfflineAndNetworkDrops();
  testMissingChargersAndRetry();
  testSharedAppSessionScreens();
  testRebootResume();
  testQuoteChangedAndErrors();
  puts("PASS: kiosk_flow (T0-T8/TE) in simulated and Stripe modes");
  return 0;
}
