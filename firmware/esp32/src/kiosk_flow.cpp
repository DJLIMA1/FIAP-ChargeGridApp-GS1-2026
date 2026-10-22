// Totem 0.8.0: máquina de estados pura (sem Arduino/LVGL). Ver include/kiosk_flow.h.
#include "kiosk_flow.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ui/strings_ptbr.h"

namespace kiosk {
namespace {

constexpr const char* kBase = "/v1/devices/kiosk";

void copy(char* out, size_t size, const char* text) {
  if (!size) return;
  snprintf(out, size, "%s", text ? text : "");
}
bool same(const char* a, const char* b) { return a && b && strcmp(a, b) == 0; }
bool oneOf(const char* value, std::initializer_list<const char*> options) {
  if (!value || !*value) return false;
  for (const char* option : options) if (strcmp(value, option) == 0) return true;
  return false;
}

// UTF-8 -> só os caracteres das fontes do painel (U+0020-U+007E, U+00A0-U+00FF, U+2022),
// sem espaços repetidos/nas pontas. Mesmo critério de panelLatin1(), sem Arduino String.
void sanitize(char* out, size_t size, const char* text, size_t maxChars) {
  if (!size) return;
  size_t length = 0, kept = 0;
  const unsigned char* c = reinterpret_cast<const unsigned char*>(text ? text : "");
  while (*c && kept < maxChars) {
    uint32_t cp = *c; int extra = 0;
    if (cp >= 0xF0) { cp &= 0x07; extra = 3; }
    else if (cp >= 0xE0) { cp &= 0x0F; extra = 2; }
    else if (cp >= 0xC0) { cp &= 0x1F; extra = 1; }
    else if (cp >= 0x80) { ++c; continue; }
    ++c;
    bool valid = true;
    for (int i = 0; i < extra; ++i, ++c) {
      if ((*c & 0xC0) != 0x80) { valid = false; break; }
      cp = (cp << 6) | (*c & 0x3F);
    }
    if (!valid) continue;
    if (cp == ' ' && (kept == 0 || out[length - 1] == ' ')) continue;
    char encoded[3]; size_t n = 0;
    if (cp >= 0x20 && cp <= 0x7E) encoded[n++] = static_cast<char>(cp);
    else if (cp >= 0xA0 && cp <= 0xFF) {
      encoded[n++] = static_cast<char>(0xC0 | (cp >> 6));
      encoded[n++] = static_cast<char>(0x80 | (cp & 0x3F));
    } else if (cp == 0x2022) { encoded[n++] = '\xE2'; encoded[n++] = '\x80'; encoded[n++] = '\xA2'; }
    else continue;
    if (length + n >= size) break;
    memcpy(out + length, encoded, n); length += n; ++kept;
  }
  while (length && out[length - 1] == ' ') --length;
  out[length] = '\0';
}

Method methodFrom(const char* text) {
  if (same(text, "simulated")) return Method::Simulated;
  if (same(text, "stripe")) return Method::Stripe;
  return Method::Unknown;
}
// Rótulo exibido: só os dois que o contrato define (o servidor decide; nada inventado aqui).
void labelFrom(char* out, size_t size, const char* text, Method method) {
  if (same(text, "SIMULADO") || same(text, "TESTE")) copy(out, size, text);
  else if (text == nullptr || !*text) copy(out, size, method == Method::Simulated ? str::kLabelSimulated : "");
  else copy(out, size, "");
}
float number(JsonVariantConst value, float fallback) {
  if (value.is<const char*>()) {
    const char* text = value.as<const char*>();
    char* end = nullptr;
    const float parsed = strtof(text, &end);
    return end != text && isfinite(parsed) ? parsed : fallback;
  }
  if (value.is<float>() || value.is<int>() || value.is<long>()) {
    const float parsed = value.as<float>();
    return isfinite(parsed) ? parsed : fallback;
  }
  return fallback;
}
void httpsUrl(char* out, size_t size, const char* url) {
  const bool ok = url && strncmp(url, "https://", 8) == 0 && strlen(url) <= 160;
  copy(out, size, ok ? url : "");
}
// Dinheiro: "x_cents" (inteiro) tem prioridade sobre "x" (texto decimal).
int32_t money(JsonObjectConst object, const char* key) {
  char centsKey[40]; snprintf(centsKey, sizeof(centsKey), "%s_cents", key);
  JsonVariantConst cents = object[centsKey];
  if (cents.is<long>()) return static_cast<int32_t>(cents.as<long>());
  return parseCents(object[key]);
}
const char* errorCode(JsonDocument& doc) {
  const char* code = doc["error"]["code"].as<const char*>();
  if (code) return code;
  code = doc["detail"]["code"].as<const char*>();
  if (code) return code;
  return doc["code"].as<const char*>();
}
// Atalhos: lista de números/textos; vazios usam os padrões aprovados.
uint8_t readList(JsonVariantConst list, int32_t* out, float scale, const int32_t* fallback, uint8_t fallbackCount) {
  uint8_t count = 0;
  for (JsonVariantConst item : list.as<JsonArrayConst>()) {
    if (count >= kShortcuts) break;
    const float value = number(item, -1);
    if (value > 0) out[count++] = static_cast<int32_t>(lroundf(value * scale));
  }
  if (count) return count;
  for (uint8_t i = 0; i < fallbackCount; ++i) out[i] = fallback[i];
  return fallbackCount;
}
void readRange(JsonVariantConst range, float scale, int32_t& low, int32_t& high, int32_t defLow, int32_t defHigh) {
  const float min = number(range["min"], -1), max = number(range["max"], -1);
  low = min > 0 ? static_cast<int32_t>(lroundf(min * scale)) : defLow;
  high = max > 0 ? static_cast<int32_t>(lroundf(max * scale)) : defHigh;
  if (high < low) high = low;
}
// Valor escolhido em texto pt-BR para o resumo ("R$ 20,00", "30 min", "10 kWh").
void describe(char* out, size_t size, Mode mode, int32_t value) {
  if (mode == Mode::Value) formatMoney(out, size, value);
  else if (mode == Mode::Time) snprintf(out, size, "%ld min", static_cast<long>(value));
  else if (mode == Mode::Energy) {
    char kwh[16]; formatDecimal(kwh, sizeof(kwh), value / 1000.0f, value % 1000 ? 1 : 0);
    snprintf(out, size, "%s kWh", kwh);
  } else if (mode == Mode::Autonomy) snprintf(out, size, "%ld km", static_cast<long>(value));
  else copy(out, size, "");
}
void setButton(ViewButton& button, const char* text, Action action, bool enabled = true) {
  copy(button.text, sizeof(button.text), text);
  button.action = action; button.visible = true; button.enabled = enabled;
}
void addMetric(KioskView& view, const char* name, const char* value) {
  if (view.metricCount >= 6) return;
  copy(view.metrics[view.metricCount].name, sizeof(view.metrics[0].name), name);
  copy(view.metrics[view.metricCount].value, sizeof(view.metrics[0].value), value);
  ++view.metricCount;
}
// Estados do pedido (contrato "Totem 0.8.0"): held, awaiting_payment, paid, charging,
// finished, canceled, expired, failed.
bool pendingStatus(const char* s) { return oneOf(s, {"held", "awaiting_payment"}); }
bool paidStatus(const char* s) { return oneOf(s, {"paid"}); }
bool runningStatus(const char* s) { return oneOf(s, {"charging"}); }
bool doneStatus(const char* s) { return oneOf(s, {"finished"}); }
bool failedStatus(const char* s) { return oneOf(s, {"failed"}); }
bool paymentPaid(const char* s) { return oneOf(s, {"authorized", "paid", "in_use", "completed"}); }
bool canceledStatus(const char* s) { return oneOf(s, {"canceled", "expired"}); }

}  // namespace

// ---------------------------------------------------------------- formatação

void formatMoney(char* out, size_t size, int32_t cents) {
  if (cents < 0) { copy(out, size, "--"); return; }
  snprintf(out, size, "R$ %ld,%02ld", static_cast<long>(cents / 100), static_cast<long>(cents % 100));
}
void formatDecimal(char* out, size_t size, float value, int decimals) {
  snprintf(out, size, "%.*f", decimals, value);
  for (char* c = out; *c; ++c) if (*c == '.') *c = ',';
}
int32_t parseCents(JsonVariantConst value) {
  const float parsed = number(value, -1);
  if (!(parsed >= 0) || parsed > 1000000) return -1;
  return static_cast<int32_t>(lroundf(parsed * 100.0f));
}
const char* modeName(Mode mode) {
  switch (mode) {
    case Mode::Value: return "value";
    case Mode::Time: return "time";
    case Mode::Energy: return "energy";
    case Mode::Autonomy: return "autonomy";
    default: return "";
  }
}

// ---------------------------------------------------------------- leitura do sync

void readOrder(JsonObjectConst order, OrderBlock& out) {
  out = OrderBlock{};
  const char* id = order["id"].as<const char*>();
  if (order.isNull() || !id || !*id || strlen(id) >= kIdSize) return;
  out.present = true;
  copy(out.id, sizeof(out.id), id);
  sanitize(out.status, sizeof(out.status), order["status"].as<const char*>(), 23);
  const char* session = order["session_id"].as<const char*>();
  if (session && strlen(session) < kIdSize) copy(out.sessionId, sizeof(out.sessionId), session);
  JsonObjectConst payment = order["payment"].as<JsonObjectConst>();
  sanitize(out.fundingSource, sizeof(out.fundingSource), payment["funding_source"].as<const char*>(), 10);
  sanitize(out.paymentStatus, sizeof(out.paymentStatus), payment["status"].as<const char*>(), 23);
  out.paymentMethod = methodFrom(payment["method"].as<const char*>());
  labelFrom(out.paymentLabel, sizeof(out.paymentLabel), payment["label"].as<const char*>(), out.paymentMethod);
  httpsUrl(out.qrUrl, sizeof(out.qrUrl), order["qr_url"].as<const char*>());
  if (!out.qrUrl[0]) httpsUrl(out.qrUrl, sizeof(out.qrUrl), payment["qr_url"].as<const char*>());
  JsonObjectConst receipt = order["receipt"].as<JsonObjectConst>();
  if (!receipt.isNull()) {
    out.receipt.present = true;
    out.receipt.final = receipt["final"] | false;
    sanitize(out.receipt.number, sizeof(out.receipt.number), receipt["number"].as<const char*>(), 30);
    out.receipt.energyKwh = number(receipt["energy_kwh"], -1);
    out.receipt.totalCents = money(receipt, "total");
    out.receipt.returnedCents = money(receipt, "returned");
    sanitize(out.receipt.returnKind, sizeof(out.receipt.returnKind), receipt["return_kind"].as<const char*>(), 19);
    sanitize(out.receipt.endReason, sizeof(out.receipt.endReason), receipt["end_reason"].as<const char*>(), 23);
    httpsUrl(out.receipt.url, sizeof(out.receipt.url), receipt["url"].as<const char*>());
  }
  httpsUrl(out.receiptUrl, sizeof(out.receiptUrl), order["receipt_url"].as<const char*>());
}

void readSync(JsonObjectConst response, SyncFacts& out) {
  out = SyncFacts{};
  JsonObjectConst block = response["connector"]["kiosk"].as<JsonObjectConst>();
  if (!block.isNull()) {
    out.kiosk.present = true;
    out.kiosk.method = methodFrom(block["method"].as<const char*>());
    // Ligado só com booleano explícito e método conhecido: o totem nunca escolhe sozinho.
    out.kiosk.enabled = block["enabled"].is<bool>() && block["enabled"].as<bool>() &&
                        out.kiosk.method != Method::Unknown;
    labelFrom(out.kiosk.label, sizeof(out.kiosk.label), block["label"].as<const char*>(), out.kiosk.method);
  }
  readOrder(response["kiosk_order"].as<JsonObjectConst>(), out.order);
  JsonObjectConst session = response["authorized"]["session"].as<JsonObjectConst>();
  out.sessionPresent = !session.isNull();
  const char* sessionId = session["id"].as<const char*>();
  if (sessionId && strlen(sessionId) < kIdSize) copy(out.sessionId, sizeof(out.sessionId), sessionId);
  out.reservationPresent = !response["authorized"]["reservation"].isNull();
  const char* origin = session["origin"].as<const char*>();
  if (oneOf(origin, {"app", "kiosk_qr", "kiosk_totem"})) copy(out.sessionOrigin, sizeof(out.sessionOrigin), origin);
}

// ---------------------------------------------------------------- fluxo

uint32_t Flow::random() {
  // xorshift32: só para chaves de idempotência (o servidor deduplica; não é segredo).
  rng_ ^= rng_ << 13; rng_ ^= rng_ >> 17; rng_ ^= rng_ << 5;
  return rng_;
}
void Flow::newKey(char* out, size_t size, const char* prefix) {
  snprintf(out, size, "%s-%08lx%08lx", prefix, static_cast<unsigned long>(random()), static_cast<unsigned long>(random()));
}

// Sessão do nosso pedido? Pelo session_id do pedido; sem ele, pela origem; sem os dois, o
// ponto está travado para o pedido (o servidor recusa o app com kiosk_in_use).
bool Flow::sessionIsOurs(const Facts& facts) const {
  if (order_.sessionId[0]) return strcmp(order_.sessionId, facts.sessionId) == 0;
  if (facts.sync.sessionOrigin[0]) return same(facts.sync.sessionOrigin, "kiosk_totem");
  return order_.id[0] != '\0';
}

bool Flow::canStart() const {
  return enabled_ && state_ == State::Idle && haveFacts_ && facts_.online && facts_.pointReady &&
         !facts_.chargerOffline &&
         !facts_.reserved && !facts_.carConnected && !facts_.maintenance && !facts_.charging &&
         !facts_.sessionAuthorized && !order_.id[0];
}

void Flow::resume(const char* orderId, uint32_t nowMs, uint8_t chargerAddress) {
  if (!orderId || !*orderId || strlen(orderId) >= kIdSize) return;
  order_ = Order{};
  chargerAddress_ = chargerAddress;
  copy(order_.id, sizeof(order_.id), orderId);
  resumed_ = true;
  go(State::Verifying, nowMs);
}

void Flow::go(State next, uint32_t nowMs) {
  state_ = next;
  enteredAt_ = lastInput_ = nowMs;
  stillThere_ = false;
  error_[0] = '\0';
  render();
}

void Flow::clearOrder() {
  if (order_.id[0]) persistDirty_ = true;
  order_ = Order{};
  quote_ = Quote{};
  resumed_ = false; offlineStop_ = false; liveSeen_ = false; missingOrderSince_ = 0;
  receiptEndReason_[0] = '\0';
}

void Flow::toIdle(uint32_t nowMs) {
  appSession_ = false;
  const bool cancelling = queued_.kind == RequestKind::Cancel;
  clearOrder();
  clearIdentity();
  mode_ = Mode::None; entry_[0] = '\0'; keypad_ = false;
  if (!cancelling) queued_ = ApiRequest{};
  go(enabled_ ? State::Idle : State::Off, nowMs);
}

void Flow::notice(const char* title, const char* detail, Tone tone, uint32_t nowMs) {
  noticeRetry_ = false;
  copy(noticeTitle_, sizeof(noticeTitle_), title);
  copy(noticeDetail_, sizeof(noticeDetail_), detail);
  noticeTone_ = tone;
  clearOrder();
  queued_ = ApiRequest{};
  go(State::Notice, nowMs);
}

void Flow::retryNotice(const char* title, const char* detail, uint32_t nowMs) {
  retryFrom_ = state_;
  notice(title, detail, Tone::Waiting, nowMs);
  noticeRetry_ = true;
  render();
}

void Flow::queue(RequestKind kind, const char* method, const char* path, const char* body, const char* key) {
  queued_ = ApiRequest{};
  queued_.kind = kind;
  queued_.chargerAddress = chargerAddress_;
  queued_.seq = ++seq_;
  queued_.method = method;
  copy(queued_.path, sizeof(queued_.path), path);
  copy(queued_.body, sizeof(queued_.body), body);
  copy(queued_.idempotencyKey, sizeof(queued_.idempotencyKey), key);
}

bool Flow::takeRequest(ApiRequest& out) {
  if (queued_.kind == RequestKind::None || inFlight_.kind != RequestKind::None) return false;
  inFlight_ = queued_;
  queued_ = ApiRequest{};
  out = inFlight_;
  return true;
}

bool Flow::takeLocalStop() { const bool value = localStop_; localStop_ = false; return value; }
bool Flow::takeLocalDisconnect() { const bool value = localDisconnect_; localDisconnect_ = false; return value; }
bool Flow::takePersist(char* out, size_t size) {
  if (!persistDirty_) return false;
  persistDirty_ = false;
  copy(out, size, order_.id);
  return true;
}

void Flow::clearIdentity() {
  // Explicit overwrite: credentials/JWT never enter NVS, diagnostic output or KioskView.
  volatile char* buffers[] = {token_, email_, password_, loginEntry_};
  const size_t sizes[] = {sizeof(token_), sizeof(email_), sizeof(password_), sizeof(loginEntry_)};
  for (size_t i = 0; i < 4; ++i) for (size_t j = 0; j < sizes[i]; ++j) buffers[i][j] = 0;
  passwordStep_ = false;
  chargerAddress_ = 0; selectingConnector_ = false;
  offer_ = Offer{};
  paymentSource_ = Action::PayCard; reducedPower_ = false;
}

void Flow::loadOffer(uint32_t nowMs) {
  queue(RequestKind::Offer, "GET", "/v1/devices/kiosk/offer", "", "");
  go(State::LoadingOffer, nowMs);
}

void Flow::selectionBody(char* out, size_t size, bool order) {
  JsonDocument doc;
  doc["mode"] = modeName(mode_);
  if (offer_.modern) doc["power"] = reducedPower_ ? "reduced" : "max";
  if (mode_ == Mode::Value) doc["amount"] = quote_.requested / 100.0;
  else if (mode_ == Mode::Time) doc["minutes"] = quote_.requested;
  else if (mode_ == Mode::Autonomy) doc["autonomy_km"] = quote_.requested;
  else doc["energy_kwh"] = quote_.requested / 1000.0;
  if (order) {
    doc["quote_hash"] = quote_.hash;
    if (quote_.overstayVersion[0]) doc["overstay_terms_version"] = quote_.overstayVersion;
    else doc["overstay_terms_version"] = nullptr;
  }
  serializeJson(doc, out, size);
}

void Flow::requestQuote() {
  char body[512]; selectionBody(body, sizeof(body), false);
  queue(RequestKind::Quote, "POST", "/v1/devices/kiosk/quote", body, "");
}

void Flow::requestOrder() {
  if (!order_.idempotencyKey[0]) newKey(order_.idempotencyKey, sizeof(order_.idempotencyKey), "ko");
  char body[512]; selectionBody(body, sizeof(body), true);
  queue(RequestKind::CreateOrder, "POST", "/v1/devices/kiosk/orders", body, order_.idempotencyKey);
}

void Flow::requestPay() {
  char path[96]; snprintf(path, sizeof(path), "%s/orders/%s/pay", kBase, order_.id);
  // Chave derivada do pedido: repetir (falha de rede, retomada após reboot) devolve o mesmo pagamento.
  char key[kIdSize + 8]; snprintf(key, sizeof(key), "pay-%s", order_.id);
  const char* source = paymentSource_ == Action::PayBalance ? "balance" : paymentSource_ == Action::PayPix ? "pix" : "card";
  char body[64]; snprintf(body, sizeof(body), "{\"funding_source\":\"%s\"}", source);
  if (!offer_.modern) copy(body, sizeof(body), "{}");
  queue(RequestKind::Pay, "POST", path, body, key);
}

void Flow::requestCancel() {
  if (!order_.id[0]) return;
  char path[96]; snprintf(path, sizeof(path), "%s/orders/%s/cancel", kBase, order_.id);
  char key[kIdSize + 8]; snprintf(key, sizeof(key), "cancel-%s", order_.id);
  order_.cancelSent = true;
  queue(RequestKind::Cancel, "POST", path, "{}", key);
}

// Voltar ao ocioso com pedido aberto: cancela (libera a trava; o pagamento volta inteiro).
// Sem rede o servidor libera sozinho quando a trava vence e devolve o pagamento.
void Flow::abortOrder(const char* title, const char* detail, uint32_t nowMs) {
  const bool hadOrder = order_.id[0] && !order_.cancelSent;
  char id[kIdSize]; copy(id, sizeof(id), order_.id);
  notice(title, detail, Tone::Error, nowMs);
  if (hadOrder) {
    copy(order_.id, sizeof(order_.id), id);
    requestCancel();
    order_ = Order{};
    order_.cancelSent = true;
  }
  clearIdentity(); // Cancellation already captured its charger address; erase the account immediately.
}

void Flow::selectMode(Mode mode, uint32_t nowMs) {
  mode_ = mode; entry_[0] = '\0'; keypad_ = false;
  quote_ = Quote{};
  go(State::Amount, nowMs);
}

void Flow::selectValue(int32_t value, uint32_t nowMs) {
  quote_ = Quote{};
  quote_.mode = mode_;
  quote_.requested = value;
  lastInput_ = nowMs;
  go(State::Power, nowMs);
}

void Flow::submitEntry(uint32_t nowMs) {
  if (!entry_[0]) return;
  int32_t value = 0;
  if (mode_ == Mode::Energy) {
    char normalized[12]; copy(normalized, sizeof(normalized), entry_);
    for (char* c = normalized; *c; ++c) if (*c == ',') *c = '.';
    value = static_cast<int32_t>(lroundf(strtof(normalized, nullptr) * 1000.0f));
  } else {
    value = static_cast<int32_t>(strtol(entry_, nullptr, 10));
    if (mode_ == Mode::Value) value *= 100;
  }
  int32_t low = 0, high = 0;
  if (mode_ == Mode::Value) { low = offer_.valueMin; high = offer_.valueMax; }
  else if (mode_ == Mode::Time) { low = offer_.timeMin; high = offer_.timeMax; }
  else if (mode_ == Mode::Autonomy) { low = 1; high = 2000; }
  else { low = offer_.energyMin; high = offer_.energyMax; }
  if (value < low || value > high) {
    char a[24], b[24]; describe(a, sizeof(a), mode_, low); describe(b, sizeof(b), mode_, high);
    snprintf(error_, sizeof(error_), "%s%s a %s", str::kOutOfRange, a, b);
    lastInput_ = nowMs;
    return;
  }
  selectValue(value, nowMs);
}

void Flow::applyOffer(JsonObjectConst body) {
  // GET /v1/devices/kiosk/offer (docs/esp32-protocol.md, "Totem 0.8.0").
  offer_ = Offer{};
  offer_.loaded = true;
  offer_.modern = (body["ui_version"] | 0) >= 2;
  for (JsonObjectConst item : body["connectors"].as<JsonArrayConst>()) {
    if (offer_.connectorCount >= 4) break;
    auto& choice = offer_.connectors[offer_.connectorCount++];
    choice.address = item["address"] | 0;
    choice.available = item["available"] | false;
    sanitize(choice.label, sizeof(choice.label), item["label"].as<const char*>(), 46);
  }
  offer_.method = methodFrom(body["method"].as<const char*>());
  // Vende só com enabled + available e um método decidido pelo servidor.
  offer_.active = (body["enabled"] | false) && offer_.method != Method::Unknown;
  offer_.available = body["available"].is<bool>() ? body["available"].as<bool>() : true;
  sanitize(offer_.reason, sizeof(offer_.reason), body["reason"].as<const char*>(), 23);
  const char* open = body["open_order_id"].as<const char*>();
  if (open && strlen(open) < kIdSize) copy(offer_.openOrderId, sizeof(offer_.openOrderId), open);
  labelFrom(offer_.label, sizeof(offer_.label), body["label"].as<const char*>(), offer_.method);
  JsonObjectConst modes = body["modes"].as<JsonObjectConst>();
  static const int32_t kValue[] = {1000, 2000, 4000, 6000}, kTime[] = {15, 30, 60}, kEnergy[] = {5000, 10000, 20000};
  offer_.valueCount = readList(modes["value"]["shortcuts"], offer_.valueShortcuts, 100.0f, kValue, 4);
  offer_.timeCount = readList(modes["time"]["shortcuts"], offer_.timeShortcuts, 1.0f, kTime, 3);
  offer_.energyCount = readList(modes["energy"]["shortcuts"], offer_.energyShortcuts, 1000.0f, kEnergy, 3);
  readRange(modes["value"], 100.0f, offer_.valueMin, offer_.valueMax, 500, 20000);
  readRange(modes["time"], 1.0f, offer_.timeMin, offer_.timeMax, 5, 60);
  readRange(modes["energy"], 1000.0f, offer_.energyMin, offer_.energyMax, 1000, 100000);
  JsonObjectConst price = body["price"].as<JsonObjectConst>();
  offer_.pricePerKwh = number(price["price_per_kwh"], -1);
  offer_.maxPricePerKwh = number(body["speed_prices"]["max"], -1);
  offer_.reducedPricePerKwh = number(body["speed_prices"]["reduced"], -1);
  offer_.basePrice = number(price["base_price_per_kwh"], -1);
  offer_.multiplier = number(price["demand_multiplier"], -1);
  offer_.powerKw = number(body["power_kw"], -1);
  JsonObjectConst account = body["account"].as<JsonObjectConst>();
  offer_.loggedIn = token_[0] && !account.isNull();
  offer_.hasVehicle = offer_.loggedIn && account["vehicle"].is<JsonObjectConst>();
  offer_.balanceAvailable = offer_.loggedIn && (body["balance_available"] | false);
  offer_.balanceCents = parseCents(account["wallet"]["balance"]);
  sanitize(offer_.accountName, sizeof(offer_.accountName), account["name"].as<const char*>(), 40);
  sanitize(offer_.vehicleName, sizeof(offer_.vehicleName), account["vehicle"]["name"].as<const char*>(), 40);
  sanitize(offer_.connectorType, sizeof(offer_.connectorType), body["connector_type"].as<const char*>(), 24);
  sanitize(offer_.publicCode, sizeof(offer_.publicCode), body["public_code"].as<const char*>(), 24);
  if (body["payment_sources"].is<JsonArrayConst>()) {
    offer_.pixAvailable = offer_.cardAvailable = false;
    for (JsonVariantConst source : body["payment_sources"].as<JsonArrayConst>()) {
      if (same(source.as<const char*>(), "pix")) offer_.pixAvailable = true;
      if (same(source.as<const char*>(), "card")) offer_.cardAvailable = true;
    }
  }
  sanitize(offer_.demandReason, sizeof(offer_.demandReason), price["reason_label"].as<const char*>(), 48);
  JsonObjectConst overstay = body["overstay"].as<JsonObjectConst>();
  if (overstay["enabled"] | false)
    sanitize(offer_.overstaySummary, sizeof(offer_.overstaySummary), overstay["summary"].as<const char*>(), 90);
  JsonVariantConst version = overstay["version"];
  if (version.is<const char*>()) sanitize(offer_.overstayVersion, sizeof(offer_.overstayVersion), version.as<const char*>(), 40);
  else if (version.is<long>()) snprintf(offer_.overstayVersion, sizeof(offer_.overstayVersion), "%ld", version.as<long>());
  const float startTimeout = number(body["start_timeout_seconds"], 60);
  offer_.startTimeoutMs = startTimeout >= 10 && startTimeout <= 600 ? static_cast<uint32_t>(startTimeout * 1000) : kStartTimeoutMs;
}

bool Flow::applyQuote(JsonObjectConst body) {
  // POST /v1/devices/kiosk/quote: total = valor pré-autorizado (energia + reserva da permanência).
  const char* hash = body["quote_hash"].as<const char*>();
  if (!hash || !*hash || strlen(hash) >= sizeof(quote_.hash)) return false;
  copy(quote_.hash, sizeof(quote_.hash), hash);
  quote_.loaded = true;
  quote_.mode = mode_;
  quote_.amountCents = money(body, "total");
  quote_.energyCapCents = money(body, "energy_cap");
  quote_.pricePerKwh = number(body["price_per_kwh"], -1);
  quote_.basePrice = number(body["base_price_per_kwh"], -1);
  quote_.multiplier = number(body["demand_multiplier"], number(body["demand"]["multiplier"], -1));
  sanitize(quote_.demandReason, sizeof(quote_.demandReason), body["demand"]["reason_label"].as<const char*>(), 48);
  quote_.energyKwh = number(body["estimated_energy_kwh"], -1);
  quote_.minutes = static_cast<int32_t>(number(body["max_duration_minutes"], -1));
  sanitize(quote_.autonomyNote, sizeof(quote_.autonomyNote), body["autonomy_note"].as<const char*>(), 110);
  JsonObjectConst overstay = body["overstay"].as<JsonObjectConst>();
  quote_.overstaySummary[0] = '\0';
  if (overstay["enabled"] | false)
    sanitize(quote_.overstaySummary, sizeof(quote_.overstaySummary), overstay["summary"].as<const char*>(), 90);
  JsonVariantConst version = overstay["version"];
  if (version.is<const char*>()) sanitize(quote_.overstayVersion, sizeof(quote_.overstayVersion), version.as<const char*>(), 40);
  else if (version.is<long>()) snprintf(quote_.overstayVersion, sizeof(quote_.overstayVersion), "%ld", version.as<long>());
  else quote_.overstayVersion[0] = '\0';
  const Method method = methodFrom(body["method"].as<const char*>());
  labelFrom(quote_.label, sizeof(quote_.label), body["label"].as<const char*>(), method != Method::Unknown ? method : offer_.method);
  if (!quote_.label[0]) copy(quote_.label, sizeof(quote_.label), offer_.label);
  // Novo orçamento = novo pedido possível: nova chave de idempotência.
  order_.idempotencyKey[0] = '\0';
  return quote_.amountCents > 0;
}

void Flow::applyOrder(JsonObjectConst body) {
  // Pedido (resposta de orders, pay, cancel e GET).
  const char* id = body["id"].as<const char*>();
  if (id && *id && strlen(id) < kIdSize) {
    if (strcmp(order_.id, id) != 0) persistDirty_ = true;
    copy(order_.id, sizeof(order_.id), id);
  }
  const char* status = body["status"].as<const char*>();
  if (status) sanitize(order_.status, sizeof(order_.status), status, 23);
  JsonObjectConst payment = body["payment"].as<JsonObjectConst>();
  Method method = methodFrom(body["method"].as<const char*>());
  if (method == Method::Unknown) method = methodFrom(payment["method"].as<const char*>());
  if (method != Method::Unknown) order_.method = method;
  else if (order_.method == Method::Unknown) order_.method = offer_.method;
  const int32_t amount = money(body["quote"].as<JsonObjectConst>(), "total");
  if (amount > 0) order_.amountCents = amount;
  else if (order_.amountCents <= 0) order_.amountCents = quote_.amountCents;
  char url[kUrlSize];
  httpsUrl(url, sizeof(url), body["qr_url"].as<const char*>());
  if (!url[0]) httpsUrl(url, sizeof(url), payment["qr_url"].as<const char*>());
  if (url[0]) copy(order_.qrUrl, sizeof(order_.qrUrl), url);
  httpsUrl(url, sizeof(url), body["receipt_url"].as<const char*>());
  if (url[0]) copy(order_.receiptUrl, sizeof(order_.receiptUrl), url);
  const char* session = body["session_id"].as<const char*>();
  if (session && strlen(session) < kIdSize) copy(order_.sessionId, sizeof(order_.sessionId), session);
  const float expires = number(body["expires_in_seconds"], -1);
  if (expires > 0 && expires <= 3600) order_.expiresAtMs = now_ + static_cast<uint32_t>(expires * 1000);
}

void Flow::onPaid(uint32_t nowMs) {
  order_.paid = true;
  go(State::Starting, nowMs);
}

void Flow::enterReceipt(uint32_t nowMs) {
  // Parada sem a API (vigia de 45 s) ou tela reiniciada com a sessão aberta.
  offlineStop_ = offlineStop_ || same(facts_.endReason, "communication_lost") ||
                 same(facts_.endReason, "device_reboot") || !facts_.online;
  go(State::Receipt, nowMs);
}

// Estado do pedido pelo servidor (bloco kiosk_order do sync ou GET /orders/{id}).
void Flow::followOrder(const OrderBlock& block, uint32_t nowMs) {
  if (!block.present || strcmp(block.id, order_.id) != 0) return;
  missingOrderSince_ = 0;
  if (same(block.fundingSource, "balance")) paymentSource_ = Action::PayBalance;
  copy(order_.status, sizeof(order_.status), block.status);
  if (block.sessionId[0]) copy(order_.sessionId, sizeof(order_.sessionId), block.sessionId);
  if (block.paymentMethod != Method::Unknown) order_.method = block.paymentMethod;
  if (order_.method == Method::Unknown) order_.method = facts_.sync.kiosk.method;
  if (block.qrUrl[0]) copy(order_.qrUrl, sizeof(order_.qrUrl), block.qrUrl);
  if (block.receiptUrl[0]) copy(order_.receiptUrl, sizeof(order_.receiptUrl), block.receiptUrl);
  const bool paid = paidStatus(block.status) || paymentPaid(block.paymentStatus);
  if (failedStatus(block.status)) {
    if (state_ == State::Receipt || state_ == State::Live) return;
    notice(str::kStartFailedTitle, str::kStartFailedDetail, Tone::Error, nowMs);
    return;
  }
  if (canceledStatus(block.status)) {
    if (state_ == State::Receipt || state_ == State::Live) return;
    notice(str::kCanceledTitle, str::kCanceledDetail, Tone::Neutral, nowMs);
    return;
  }
  if (block.receipt.endReason[0]) copy(receiptEndReason_, sizeof(receiptEndReason_), block.receipt.endReason);
  if (doneStatus(block.status)) {
    if (state_ != State::Receipt) enterReceipt(nowMs);
    return;
  }
  if (runningStatus(block.status)) {
    if (facts_.charging) { if (state_ != State::Live && state_ != State::ConfirmStop) { liveSeen_ = true; go(State::Live, nowMs); } }
    else if (state_ == State::Verifying || state_ == State::Pay) onPaid(nowMs);
    else if (state_ == State::Live) enterReceipt(nowMs);
    return;
  }
  if (paid) {
    if (state_ == State::Pay || state_ == State::Verifying) onPaid(nowMs);
    return;
  }
  if (pendingStatus(block.status) || !block.status[0]) {
    if (state_ == State::Verifying) {
      go(State::Pay, nowMs);
      if (order_.method == Method::Stripe && !order_.qrUrl[0]) requestPay();
      order_.expiresAtMs = nowMs + (order_.method == Method::Stripe ? kQrTimeoutMs : kHoldMs);
    }
    if (state_ == State::Pay && same(block.paymentStatus, "declined")) copy(error_, sizeof(error_), str::kPayDeclined);
  }
}

void Flow::facts(const Facts& incoming) {
  facts_ = incoming; haveFacts_ = true;
  now_ = incoming.nowMs;
  const uint32_t now = now_;
  if (apiUnsupported_ && now - apiUnsupportedAt_ >= 600000UL) apiUnsupported_ = false;  // tenta de novo a cada 10 min
  enabled_ = incoming.sync.kiosk.present && incoming.sync.kiosk.enabled &&
             incoming.sync.kiosk.method != Method::Unknown && !apiUnsupported_;
  if (followAppSessions_ && !order_.id[0] && incoming.charging &&
      !same(incoming.sync.sessionOrigin, "kiosk_totem") &&
      (state_ == State::Idle || state_ == State::Off ||
       (appSession_ && state_ == State::Receipt && !same(incoming.sessionId, lastSessionFacts_.sessionId)))) {
    const uint8_t address = chargerAddress_;
    clearIdentity();
    chargerAddress_ = address;
    appSession_ = true;
    offlineStop_ = false;
    go(State::Live, now);
  }
  if (incoming.charging) lastSessionFacts_ = incoming;
  else if (incoming.stopped && incoming.sessionId[0] && same(incoming.sessionId, lastSessionFacts_.sessionId)) {
    const uint32_t elapsed = lastSessionFacts_.elapsedS;
    lastSessionFacts_ = incoming;
    if (lastSessionFacts_.elapsedS < elapsed) lastSessionFacts_.elapsedS = elapsed;
  }
  const bool foreignSession = incoming.sessionAuthorized && !sessionIsOurs(incoming);
  switch (state_) {
    case State::Off:
      if (enabled_) go(State::Idle, now);
      break;
    case State::Idle:
      if (!enabled_) go(State::Off, now);
      break;
    case State::Welcome: case State::Login: case State::Connector: case State::Power: case State::PaymentMethod:
    case State::LoadingOffer: case State::Choose: case State::Amount: case State::Review:
      // Antes de aceitar não há trava: qualquer mudança no ponto volta ao início, nada cobrado.
      if (!incoming.online) retryNotice(str::kOfflineTitle, "A central está reconectando. Aguarde e tente novamente. Nada foi cobrado.", now);
      else if (incoming.charging || incoming.sessionAuthorized) notice(str::kAppStartedTitle, str::kAppStartedDetail, Tone::Error, now);
      else if (incoming.reserved) notice(str::kReservedTitle, str::kReservedDetail, Tone::Error, now);
      else if (incoming.chargerOffline) retryNotice("Carregador indisponível", "A central está online, mas este carregador não responde. Aguarde e tente novamente.", now);
      else if (incoming.carConnected || incoming.maintenance || !incoming.pointReady) notice(str::kBusyTitle, str::kBusyDetail, Tone::Error, now);
      else if (!enabled_) notice(str::kUnavailableTitle, str::kUnavailableDetail, Tone::Neutral, now);
      break;
    case State::Pay:
      if (!incoming.online) { go(State::Verifying, now); break; }
      if (foreignSession || incoming.reserved) { abortOrder(str::kAppStartedTitle, str::kCanceledDetail, now); break; }
      followOrder(incoming.sync.order, now);
      break;
    case State::Starting:
      if (incoming.charging && !foreignSession) { liveSeen_ = true; go(State::Live, now); break; }
      if (!incoming.online) { go(State::Verifying, now); break; }
      followOrder(incoming.sync.order, now);
      break;
    case State::Live:
      liveSeen_ = true;
      if (!incoming.charging) enterReceipt(now);
      break;
    case State::ConfirmStop:
      if (returnFrom_ == State::Live && !incoming.charging) enterReceipt(now);
      else if (returnFrom_ != State::Live && !incoming.charging) go(enabled_ ? State::Idle : State::Off, now);
      break;
    case State::Receipt:
      followOrder(incoming.sync.order, now);
      break;
    case State::Verifying:
      if (incoming.charging && !foreignSession && order_.id[0]) { liveSeen_ = true; go(State::Live, now); break; }
      if (!incoming.online) break;
      if (incoming.sync.order.present && strcmp(incoming.sync.order.id, order_.id) == 0) {
        followOrder(incoming.sync.order, now);
      } else if (!requestInFlight() && queued_.kind == RequestKind::None &&
                 (!missingOrderSince_ || now - missingOrderSince_ >= 10000UL)) {
        // Sem o bloco no sync: pergunta direto (uma vez a cada 10 s).
        if (!missingOrderSince_) missingOrderSince_ = now;
        char path[96]; snprintf(path, sizeof(path), "%s/orders/%s", kBase, order_.id);
        queue(RequestKind::GetOrder, "GET", path, "", "");
        if (now - enteredAt_ >= kResumeGiveUpMs) toIdle(now);
      }
      break;
    case State::Notice:
      break;
  }
  tick(now);
  render();
}

void Flow::tick(uint32_t now) {
  now_ = now;
  const uint32_t idle = now - lastInput_, inState = now - enteredAt_;
  bool prompt = false;
  switch (state_) {
    case State::LoadingOffer:
      if (inState >= 15000UL && !requestInFlight()) toIdle(now);
      break;
    case State::Welcome: case State::Login: case State::Connector: case State::Power: case State::PaymentMethod:
    case State::Choose: case State::Amount:
      if (idle >= kIdleTimeoutMs) { toIdle(now); return; }
      prompt = idle >= kPromptMs;
      break;
    case State::Review:
      if (idle >= kReviewTimeoutMs) { toIdle(now); return; }
      prompt = idle >= kReviewPromptMs;
      break;
    case State::Pay:
      if (order_.method == Method::Stripe) {
        // QR: até a trava do pedido vencer (10 min).
        if (order_.expiresAtMs && (int32_t)(now - order_.expiresAtMs) >= 0) { abortOrder(str::kCanceledTitle, str::kCanceledDetail, now); return; }
      } else {
        if (idle >= kIdleTimeoutMs) { abortOrder(str::kCanceledTitle, str::kCanceledDetail, now); return; }
        prompt = idle >= kPromptMs;
      }
      break;
    case State::Starting:
      if (inState >= (offer_.loaded ? offer_.startTimeoutMs : kStartTimeoutMs)) {
        // Pago sem START no prazo: o servidor devolve (start_kiosk); pedimos o cancelamento também.
        abortOrder(str::kStartFailedTitle, str::kStartFailedDetail, now);
        return;
      }
      break;
    case State::ConfirmStop:
      if (inState >= kConfirmTimeoutMs) { go(returnFrom_ == State::Live ? State::Live : (enabled_ ? State::Idle : State::Off), now); return; }
      break;
    case State::Receipt:
      // Privacy timeout is anchored to entering the receipt, never prolonged by touch.
      // Keep overstay/disconnect controls while a car remains connected, but hide the QR.
      if (inState >= kReceiptTimeoutMs && !facts_.carConnected) { toIdle(now); return; }
      render();
      break;
    case State::Notice:
      if (noticeRetry_ ? idle >= kIdleTimeoutMs : inState >= kNoticeMs) { toIdle(now); return; }
      break;
    default:
      break;
  }
  if (prompt != stillThere_) { stillThere_ = prompt; render(); }
}

void Flow::touch(Action action, uint32_t now) {
  now_ = now;
  lastInput_ = now;
  if (action == Action::Continue) { stillThere_ = false; render(); return; }
  switch (state_) {
    case State::Off: case State::Idle:
      if (action == Action::StartFlow && canStart()) {
        clearIdentity();
        go(State::Welcome, now);
      } else if (action == Action::Stop && haveFacts_ && facts_.charging) {
        // Recarga iniciada pelo app: Encerrar no totem pede confirmação.
        returnFrom_ = state_;
        go(State::ConfirmStop, now);
      }
      break;
    case State::Welcome:
      if (action == Action::Guest) { clearIdentity(); loadOffer(now); }
      else if (action == Action::Login) { clearIdentity(); go(State::Login, now); }
      else if (action == Action::Back || action == Action::Cancel) toIdle(now);
      break;
    case State::Login:
      if (requestInFlight() || queued_.kind != RequestKind::None) break;
      if (action == Action::Back) {
        if (passwordStep_) { passwordStep_ = false; copy(loginEntry_, sizeof(loginEntry_), email_); render(); }
        else { clearIdentity(); go(State::Welcome, now); }
      } else if (action == Action::LoginNext && loginEntry_[0]) {
        if (!passwordStep_) {
          if (!strchr(loginEntry_, '@') || !strchr(loginEntry_, '.')) { copy(error_, sizeof(error_), "Informe um e-mail válido."); break; }
          copy(email_, sizeof(email_), loginEntry_); loginEntry_[0] = 0; passwordStep_ = true;
          error_[0] = 0;
        } else {
          copy(password_, sizeof(password_), loginEntry_);
          JsonDocument doc; doc["email"] = email_; doc["password"] = password_;
          char body[512]; serializeJson(doc, body, sizeof(body));
          queue(RequestKind::Login, "POST", "/v1/auth/login", body, "");
          memset(password_, 0, sizeof(password_)); memset(loginEntry_, 0, sizeof(loginEntry_));
          memset(body, 0, sizeof(body));
        }
      }
      break;
    case State::Connector:
      if (action >= Action::Connector0 && action <= Action::Connector3) {
        const int index = static_cast<int>(action) - static_cast<int>(Action::Connector0);
        if (index < offer_.connectorCount && offer_.connectors[index].available) {
          chargerAddress_ = offer_.connectors[index].address;
          selectingConnector_ = true;
          loadOffer(now);
        }
      }
      else if (action == Action::Next && offer_.available) go(State::Choose, now);
      else if (action == Action::Back) { clearIdentity(); go(State::Welcome, now); }
      break;
    case State::Power:
      if (requestInFlight() || queued_.kind != RequestKind::None) break;
      if (action == Action::PowerMax || (action == Action::PowerReduced && offer_.modern)) {
        reducedPower_ = action == Action::PowerReduced;
        requestQuote();
      } else if (action == Action::Back) go(State::Amount, now);
      break;
    case State::PaymentMethod:
      if (action == Action::PayBalance && offer_.balanceAvailable && offer_.balanceCents >= quote_.amountCents) {
        paymentSource_ = action; go(State::Review, now);
      } else if ((action == Action::PayPix && offer_.pixAvailable) || (action == Action::PayCard && offer_.cardAvailable)) {
        paymentSource_ = action; go(State::Review, now);
      } else if (action == Action::Back) go(State::Power, now);
      break;
    case State::LoadingOffer:
      if (action == Action::Back || action == Action::Cancel) toIdle(now);
      break;
    case State::Choose:
      if (action == Action::ModeValue) selectMode(Mode::Value, now);
      else if (action == Action::ModeTime) selectMode(Mode::Time, now);
      else if (action == Action::ModeEnergy) selectMode(Mode::Energy, now);
      else if (action == Action::ModeAutonomy && offer_.loggedIn && offer_.hasVehicle) selectMode(Mode::Autonomy, now);
      else if (action == Action::Back) go(State::Connector, now);
      else if (action == Action::Cancel) toIdle(now);
      break;
    case State::Amount: {
      if (queued_.kind == RequestKind::Quote || inFlight_.kind == RequestKind::Quote) break;  // aguardando orçamento
      static const int32_t kmList[] = {30, 60, 100, 150};
      const int32_t* list = mode_ == Mode::Autonomy ? kmList : mode_ == Mode::Value ? offer_.valueShortcuts : mode_ == Mode::Time ? offer_.timeShortcuts : offer_.energyShortcuts;
      const uint8_t count = mode_ == Mode::Autonomy ? 4 : mode_ == Mode::Value ? offer_.valueCount : mode_ == Mode::Time ? offer_.timeCount : offer_.energyCount;
      const int index = action == Action::Shortcut0 ? 0 : action == Action::Shortcut1 ? 1 :
                        action == Action::Shortcut2 ? 2 : action == Action::Shortcut3 ? 3 : -1;
      if (index >= 0 && index < count && !keypad_) { error_[0] = '\0'; selectValue(list[index], now); }
      else if (action == Action::OtherValue) { keypad_ = true; entry_[0] = '\0'; error_[0] = '\0'; }
      else if (action == Action::KeypadOk) submitEntry(now);
      else if (action == Action::Back) {
        if (keypad_) { keypad_ = false; entry_[0] = '\0'; error_[0] = '\0'; }
        else go(State::Choose, now);
      } else if (action == Action::Cancel) toIdle(now);
      break;
    }
    case State::Review:
      if (requestInFlight() || queued_.kind != RequestKind::None) break;
      if (action == Action::Accept && quote_.loaded) { error_[0] = '\0'; requestOrder(); }
      else if (action == Action::Back) go(State::PaymentMethod, now);
      else if (action == Action::Cancel) toIdle(now);
      break;
    case State::Pay:
      if (action == Action::Cancel) {
        abortOrder(str::kCanceledTitle, str::kCanceledDetail, now);
      } else if (requestInFlight() || queued_.kind != RequestKind::None) {
        break;
      } else if (action == Action::SimulatePay) {
        error_[0] = '\0';
        if (order_.method == Method::Simulated) requestPay();
        else {
          char path[96]; snprintf(path, sizeof(path), "%s/orders/%s", kBase, order_.id);
          queue(RequestKind::GetOrder, "GET", path, "", "");
        }
      } else if (action == Action::Retry) {
        error_[0] = '\0'; requestPay();
      }
      break;
    case State::Live:
      if (action == Action::Stop) { returnFrom_ = State::Live; go(State::ConfirmStop, now); }
      break;
    case State::ConfirmStop:
      if (action == Action::ConfirmYes) {
        localStop_ = true;   // requestLocalSafeStop() no laço principal
        go(returnFrom_ == State::Live ? State::Live : (enabled_ ? State::Idle : State::Off), now);
      } else if (action == Action::ConfirmNo) {
        go(returnFrom_ == State::Live ? State::Live : (enabled_ ? State::Idle : State::Off), now);
      }
      break;
    case State::Receipt:
      if (action == Action::Done) toIdle(now);
      else if (action == Action::Disconnect && facts_.carConnected) localDisconnect_ = true;
      break;
    case State::Notice:
      if (action == Action::Done || action == Action::Cancel) toIdle(now);
      else if (action == Action::Retry && noticeRetry_ && !requestInFlight()) {
        if (retryFrom_ == State::Login || retryFrom_ == State::Welcome) go(retryFrom_, now);
        else loadOffer(now);
      }
      break;
    case State::Starting: case State::Verifying:
      break;
  }
  render();
}

void Flow::key(char k, uint32_t now) {
  now_ = now;
  lastInput_ = now;
  if (state_ == State::Login) {
    if (requestInFlight() || queued_.kind != RequestKind::None) return;
    size_t n = strlen(loginEntry_);
    if (k == '\b') { if (n) loginEntry_[n - 1] = 0; }
    else if (k >= 32 && k <= 126 && n + 1 < sizeof(loginEntry_)) { loginEntry_[n] = k; loginEntry_[n + 1] = 0; }
    error_[0] = 0; render(); return;
  }
  if (state_ != State::Amount || !keypad_) return;
  size_t length = strlen(entry_);
  const char* comma = strchr(entry_, ',');
  if (k >= '0' && k <= '9') {
    if (comma && strlen(comma + 1) >= 1) return;               // uma casa decimal em kWh
    if (!comma && length >= (mode_ == Mode::Energy ? 3u : 4u)) return;
    if (length == 1 && entry_[0] == '0' && !comma) length = 0;  // sem zero à esquerda
    if (length + 1 < sizeof(entry_)) { entry_[length] = k; entry_[length + 1] = '\0'; }
  } else if (k == ',') {
    if (mode_ != Mode::Energy || comma) return;
    if (!length) { entry_[0] = '0'; length = 1; }
    if (length + 1 < sizeof(entry_)) { entry_[length] = ','; entry_[length + 1] = '\0'; }
  } else if (k == 'B') {
    if (length) entry_[length - 1] = '\0';
  } else if (k == 'C') {
    entry_[0] = '\0';
  } else return;
  error_[0] = '\0';
  render();
}

void Flow::apiResult(const ApiResult& result) {
  if (result.kind == RequestKind::None || result.seq != inFlight_.seq) return;  // resposta velha
  inFlight_ = ApiRequest{};
  const uint32_t now = now_;
  JsonDocument doc;
  const bool parsed = result.body && *result.body && !deserializeJson(doc, result.body);
  JsonObjectConst body = parsed ? doc.as<JsonObjectConst>() : JsonObjectConst();
  const bool ok = result.status >= 200 && result.status < 300 && parsed;
  const char* code = parsed ? errorCode(doc) : nullptr;
  if (result.kind != RequestKind::Login && result.status == 401 && (token_[0] || same(code, "login_required"))) {
    memset(token_, 0, sizeof(token_));
    if (order_.id[0]) abortOrder("Login expirado", "Entre novamente para continuar. O pedido foi cancelado.", now);
    else notice("Login expirado", "Entre novamente ou continue sem login.", Tone::Error, now);
    render(); return;
  }
  switch (result.kind) {
    case RequestKind::Login:
      if (state_ != State::Login) break;
      if (ok && body["access_token"].is<const char*>() && strlen(body["access_token"].as<const char*>()) < sizeof(token_)) {
        copy(token_, sizeof(token_), body["access_token"].as<const char*>());
        memset(email_, 0, sizeof(email_));
        loadOffer(now);
      } else {
        copy(error_, sizeof(error_), result.status == 401 ? "E-mail ou senha incorretos. Tente novamente." : "Não foi possível entrar. Tente novamente.");
      }
      break;
    case RequestKind::Offer:
      if (state_ != State::LoadingOffer) break;
      if (ok) {
        applyOffer(body);
        if (token_[0] && (!offer_.modern || !offer_.loggedIn)) {
          clearIdentity();
          notice("Atualização pendente", "O acesso à conta ainda não está disponível neste serviço. Continue sem login.", Tone::Neutral, now);
        }
        else if (!offer_.active) notice(str::kUnavailableTitle, str::kUnavailableDetail, Tone::Neutral, now);
        else if (offer_.available) {
          go(selectingConnector_ ? State::Choose : State::Connector, now); selectingConnector_ = false;
        }
        else if (same(offer_.reason, "kiosk_in_use") && offer_.openOrderId[0]) resume(offer_.openOrderId, now, chargerAddress_);
        else if (!selectingConnector_ && offer_.connectorCount && offer_.connectors[0].available) go(State::Connector, now);
        else if (!selectingConnector_ && offer_.connectorCount > 1 &&
                 (offer_.connectors[1].available || offer_.connectors[2].available || offer_.connectors[3].available)) go(State::Connector, now);
        else if (same(offer_.reason, "reserved")) notice(str::kReservedTitle, str::kReservedDetail, Tone::Error, now);
        else if (same(offer_.reason, "charging")) notice(str::kAppStartedTitle, str::kAppStartedDetail, Tone::Error, now);
        else if (same(offer_.reason, "offline")) retryNotice(
            facts_.online ? "Carregador indisponível" : str::kOfflineTitle,
            facts_.online ? "A central está online, mas não há carregador disponível. Aguarde e tente novamente." :
                "A central está reconectando. Aguarde e tente novamente.", now);
        else notice(str::kBusyTitle, str::kBusyDetail, Tone::Error, now);
      } else if (result.status == 404 && !same(code, "kiosk_disabled")) {
        // API anterior ao totem (rota inexistente): desliga, telas atuais; tenta de novo em 10 min.
        apiUnsupported_ = true; apiUnsupportedAt_ = now; enabled_ = false;
        toIdle(now);
      } else if (result.status == 404 || result.status == 503) {
        notice(str::kUnavailableTitle, str::kUnavailableDetail, Tone::Neutral, now);
      } else if (result.status == 409) {
        notice(str::kBusyTitle, str::kInUseDetail, Tone::Error, now);
      } else {
        retryNotice("Não foi possível consultar", "Aguarde e tente novamente. Nenhum pedido foi criado.", now);
      }
      break;
    case RequestKind::Quote:
      if (state_ != State::Amount && state_ != State::Power && state_ != State::Review) break;
      if (!ok && state_ == State::Power) go(State::Amount, now);
      if (ok && applyQuote(body)) {
        const bool changed = state_ == State::Review;
        go(changed ? State::Review : State::PaymentMethod, now);
        if (changed) copy(error_, sizeof(error_), str::kQuoteChanged);
      } else if (result.status == 409) {
        notice(str::kBusyTitle, str::kInUseDetail, Tone::Error, now);
      } else if (result.status == 503 || same(code, "kiosk_disabled")) {
        notice(str::kUnavailableTitle, str::kUnavailableDetail, Tone::Neutral, now);
      } else if (result.status == 422 || result.status == 400) {
        char a[24], b[24];
        int32_t low = mode_ == Mode::Value ? offer_.valueMin : mode_ == Mode::Time ? offer_.timeMin : offer_.energyMin;
        int32_t high = mode_ == Mode::Value ? offer_.valueMax : mode_ == Mode::Time ? offer_.timeMax : offer_.energyMax;
        describe(a, sizeof(a), mode_, low); describe(b, sizeof(b), mode_, high);
        if (state_ == State::Review) go(State::Amount, now);
        const char* message = body["error"]["message"].as<const char*>();
        if (message && (mode_ == Mode::Autonomy || same(code, "vehicle_required") || same(code, "battery_full"))) sanitize(error_, sizeof(error_), message, 90);
        else snprintf(error_, sizeof(error_), "%s%s a %s", str::kOutOfRange, a, b);
      } else {
        copy(error_, sizeof(error_), str::kNetworkError);
      }
      break;
    case RequestKind::CreateOrder:
      if (state_ != State::Review) break;
      if (ok) {
        applyOrder(body);
        if (!order_.id[0]) { copy(error_, sizeof(error_), str::kOrderError); break; }
        persistDirty_ = true;
        if (order_.method == Method::Unknown) order_.method = offer_.method;
        if (!order_.expiresAtMs) order_.expiresAtMs = now + kHoldMs;
        go(State::Pay, now);
        if (order_.method == Method::Stripe) requestPay();      // QR do pedido logo ao entrar
      } else if (result.status == 409 && (same(code, "quote_changed") || same(code, "overstay_terms_changed"))) {
        JsonObjectConst fresh = body["error"]["quote"].as<JsonObjectConst>();
        if (fresh.isNull()) fresh = body["quote"].as<JsonObjectConst>();
        if (!fresh.isNull() && applyQuote(fresh)) { go(State::Review, now); copy(error_, sizeof(error_), str::kQuoteChanged); }
        else { quote_.loaded = false; copy(error_, sizeof(error_), str::kQuoteChanged); requestQuote(); }
      } else if (result.status == 409 && same(code, "order_open")) {
        const char* open = body["error"]["order_id"].as<const char*>();
        if (open && *open) resume(open, now);
        else notice(str::kBusyTitle, str::kInUseDetail, Tone::Error, now);
      } else if (result.status == 409 || result.status == 423) {
        notice(str::kBusyTitle, str::kInUseDetail, Tone::Error, now);
      } else if (result.status == 503 || result.status == 404) {
        notice(str::kUnavailableTitle, str::kUnavailableDetail, Tone::Neutral, now);
      } else {
        copy(error_, sizeof(error_), str::kOrderError);         // mesma chave na nova tentativa
      }
      break;
    case RequestKind::Pay:
      if (state_ != State::Pay) break;
      if (ok) {
        applyOrder(body);
        const char* status = body["status"].as<const char*>();
        const char* paymentStatus = body["payment"]["status"].as<const char*>();
        if (paidStatus(status) || runningStatus(status) || paymentPaid(paymentStatus)) onPaid(now);
        else if (failedStatus(status)) notice(str::kStartFailedTitle, str::kStartFailedDetail, Tone::Error, now);
        else if (canceledStatus(status)) notice(str::kCanceledTitle, str::kCanceledDetail, Tone::Neutral, now);
        else if (order_.method == Method::Stripe && order_.qrUrl[0]) {
          if (!order_.expiresAtMs) order_.expiresAtMs = now + kQrTimeoutMs;
        }
      } else if (result.status == 402) {
        copy(error_, sizeof(error_), "Saldo insuficiente. Cancele e escolha outra forma de pagamento.");
      } else if (result.status == 409 || result.status == 410 || result.status == 404) {
        notice(str::kCanceledTitle, str::kCanceledDetail, Tone::Error, now);
      } else {
        copy(error_, sizeof(error_), str::kNetworkError);       // 502/timeout: repetir com a mesma chave
      }
      break;
    case RequestKind::Cancel:
      break;  // o aviso já está na tela; sem rede a trava vence sozinha no servidor
    case RequestKind::GetOrder:
      if (state_ != State::Verifying && state_ != State::Pay) break;
      if (ok) {
        OrderBlock block; readOrder(body, block);
        if (block.present && strcmp(block.id, order_.id) == 0) {
          const float expires = number(body["expires_in_seconds"], -1);
          if (expires > 0 && expires <= 3600) order_.expiresAtMs = now + static_cast<uint32_t>(expires * 1000);
          if (!order_.receiptUrl[0]) httpsUrl(order_.receiptUrl, sizeof(order_.receiptUrl), body["receipt_url"].as<const char*>());
          followOrder(block, now);
        }
      } else if (result.status == 404) {
        toIdle(now);   // pedido desconhecido (ou de outro ponto): nada a retomar
      }
      break;
    case RequestKind::None:
      break;
  }
  render();
}

void Flow::handle(const Event& event) {
  switch (event.type) {
    case EventType::Touch: touch(event.action, event.nowMs); break;
    case EventType::Key: key(event.key, event.nowMs); break;
    case EventType::Tick: tick(event.nowMs); break;
    case EventType::Facts: if (event.facts) facts(*event.facts); break;
    case EventType::ApiResult: if (event.result) apiResult(*event.result); break;
  }
}

// ---------------------------------------------------------------- view

void Flow::render() {
  // Montada fora da pilha (laço do Arduino): ~2 KB.
  KioskView& next = scratch_;
  next = KioskView{};
  next.stillThere = stillThere_;
  next.keypad = state_ == State::Amount && keypad_;
  const bool busy = requestInFlight() || queued_.kind != RequestKind::None;
  next.busy = busy;
  copy(next.notice, sizeof(next.notice), error_);
  next.tone = error_[0] ? Tone::Error : Tone::Neutral;
  const char* label = order_.id[0] && quote_.label[0] ? quote_.label : offer_.label[0] ? offer_.label : facts_.sync.kiosk.label;
  char text[96], a[32], b[32];
  switch (state_) {
    case State::Off: case State::Idle:
      next.screen = Screen::None;
      break;
    case State::Welcome:
      next.screen = Screen::Welcome;
      copy(next.title, sizeof(next.title), "Sua recarga, do seu jeito.");
      copy(next.subtitle, sizeof(next.subtitle), "Entre para usar seu saldo e seu carro. Você também pode continuar sem conta.");
      setButton(next.options[0], "Entrar na minha conta", Action::Login);
      setButton(next.options[1], "Continuar sem login", Action::Guest);
      copy(next.context, sizeof(next.context), "Com login: saldo do app e autonomia com carro cadastrado. Sem login: Pix ou cartão.");
      setButton(next.secondary, str::kBack, Action::Back);
      break;
    case State::Login:
      next.screen = Screen::Login;
      next.password = passwordStep_;
      copy(next.title, sizeof(next.title), "Entre na sua conta");
      copy(next.subtitle, sizeof(next.subtitle), passwordStep_ ? "Digite sua senha. Ao concluir, seus dados serão apagados desta tela." : "Use o mesmo e-mail e senha da sua conta ChargeGrid.");
      if (passwordStep_) {
        const size_t n = strlen(loginEntry_);
        memset(next.loginEntry, '*', n); next.loginEntry[n] = 0;
      } else copy(next.loginEntry, sizeof(next.loginEntry), loginEntry_);
      setButton(next.primary, busy ? "Entrando..." : passwordStep_ ? "Entrar" : "Continuar", Action::LoginNext, loginEntry_[0] && !busy);
      setButton(next.secondary, str::kBack, Action::Back, !busy);
      break;
    case State::Connector:
      next.screen = Screen::Connector;
      copy(next.title, sizeof(next.title), "Escolha a conexão");
      copy(next.subtitle, sizeof(next.subtitle), "Este totem controla o conector abaixo. Confira se ele é compatível com seu veículo.");
      if (offer_.connectorCount > 1)
        copy(next.subtitle, sizeof(next.subtitle), "Toque em um carregador disponível e compatível com seu veículo.");
      formatDecimal(a, sizeof(a), offer_.powerKw, 1);
      snprintf(text, sizeof(text), "%s - %s kW", offer_.connectorType[0] ? offer_.connectorType : "Conector", a);
      setButton(next.options[0], text, Action::Next);
      if (offer_.connectorCount) {
        for (uint8_t i = 0; i < offer_.connectorCount; ++i)
          setButton(next.options[i], offer_.connectors[i].label,
                    static_cast<Action>(static_cast<int>(Action::Connector0) + i), offer_.connectors[i].available);
      }
      snprintf(next.context, sizeof(next.context), "Ponto %s. Conecte o cabo ao carro antes de confirmar o pagamento.", offer_.publicCode);
      if (!offer_.publicCode[0]) copy(next.context, sizeof(next.context), "Conecte o cabo ao carro antes de confirmar o pagamento.");
      setButton(next.primary, "Próximo passo", Action::Next, offer_.available);
      if (offer_.connectorCount > 1 || (offer_.connectorCount && !offer_.available)) next.primary.visible = false;
      setButton(next.secondary, str::kBack, Action::Back);
      copy(next.label, sizeof(next.label), label);
      break;
    case State::Power:
      next.screen = Screen::Power;
      copy(next.title, sizeof(next.title), "Potência e velocidade");
      copy(next.subtitle, sizeof(next.subtitle), "Escolha a velocidade. O limite do ponto e do seu carro será respeitado.");
      formatDecimal(a, sizeof(a), offer_.powerKw, 1);
      if (offer_.maxPricePerKwh >= 0) {
        formatMoney(b, sizeof(b), static_cast<int32_t>(offer_.maxPricePerKwh * 100 + .5f));
        snprintf(text, sizeof(text), "Máxima - %s kW - %s/kWh", a, b);
      } else snprintf(text, sizeof(text), "Máxima - até %s kW", a);
      setButton(next.options[0], text, Action::PowerMax, !busy);
      formatDecimal(a, sizeof(a), offer_.powerKw / 2, 1);
      if (offer_.reducedPricePerKwh >= 0) {
        formatMoney(b, sizeof(b), static_cast<int32_t>(offer_.reducedPricePerKwh * 100 + .5f));
        snprintf(text, sizeof(text), "Reduzida - %s kW - %s/kWh", a, b);
      } else snprintf(text, sizeof(text), "Reduzida - até %s kW", a);
      if (offer_.modern) setButton(next.options[1], text, Action::PowerReduced, !busy);
      copy(next.context, sizeof(next.context), "A potência disponível pode variar durante a recarga.");
      setButton(next.secondary, str::kBack, Action::Back, !busy);
      copy(next.label, sizeof(next.label), label);
      break;
    case State::PaymentMethod:
      next.screen = Screen::PaymentMethod;
      copy(next.title, sizeof(next.title), "Como deseja pagar?");
      copy(next.subtitle, sizeof(next.subtitle), "Escolha a forma de pagamento para esta recarga.");
      if (!offer_.modern) setButton(next.options[0], "Cartão ou Pix", Action::PayCard);
      else {
        if (offer_.pixAvailable) setButton(next.options[0], "Pix", Action::PayPix);
        if (offer_.cardAvailable) setButton(next.options[1], "Cartão de crédito / débito", Action::PayCard);
      }
      if (offer_.loggedIn) {
        formatMoney(a, sizeof(a), offer_.balanceCents);
        snprintf(text, sizeof(text), "Saldo do app - %s", a);
        setButton(next.options[2], text, Action::PayBalance, offer_.balanceAvailable && offer_.balanceCents >= quote_.amountCents);
      }
      copy(next.context, sizeof(next.context), offer_.method == Method::Simulated ? "Modo apresentação: Pix, cartão e saldo são simulados, sem cobrança real." : "Pagamento seguro pelo QR. A confirmação vem do servidor.");
      if (offer_.loggedIn && !offer_.balanceAvailable) copy(next.notice, sizeof(next.notice), "Saldo simulado disponível apenas em postos de apresentação.");
      setButton(next.secondary, str::kBack, Action::Back);
      copy(next.label, sizeof(next.label), label);
      break;
    case State::LoadingOffer:
      next.screen = Screen::Notice;
      copy(next.title, sizeof(next.title), "Preparando sua recarga");
      copy(next.subtitle, sizeof(next.subtitle), "Consultando carregadores, disponibilidade e tarifas. Só um instante.");
      next.tone = Tone::Waiting;
      setButton(next.secondary, str::kBack, Action::Back);
      copy(next.label, sizeof(next.label), facts_.sync.kiosk.label);
      break;
    case State::Choose:
      next.screen = Screen::Choose;
      copy(next.title, sizeof(next.title), str::kChooseTitle);
      copy(next.subtitle, sizeof(next.subtitle), str::kChooseCable);
      setButton(next.options[0], str::kModeValue, Action::ModeValue);
      setButton(next.options[1], str::kModeTime, Action::ModeTime);
      setButton(next.options[2], !offer_.loggedIn ? "Por autonomia (requer login)" :
                !offer_.hasVehicle ? "Autonomia (requer carro cadastrado)" : "Por autonomia",
                Action::ModeAutonomy, offer_.loggedIn && offer_.hasVehicle);
      copy(next.context, sizeof(next.context), offer_.loggedIn ? (offer_.hasVehicle ? offer_.vehicleName : "Cadastre um carro no perfil do app para liberar a autonomia.") : "Para usar autonomia e saldo, volte e entre na sua conta.");
      setButton(next.secondary, str::kBack, Action::Back);
      copy(next.label, sizeof(next.label), label);
      break;
    case State::Amount: {
      next.screen = Screen::Amount;
      copy(next.label, sizeof(next.label), label);
      copy(next.title, sizeof(next.title), mode_ == Mode::Value ? str::kAmountValueTitle :
           mode_ == Mode::Time ? str::kAmountTimeTitle : mode_ == Mode::Autonomy ? "Qual autonomia deseja?" : str::kAmountEnergyTitle);
      static const int32_t kmList[] = {30, 60, 100, 150};
      const int32_t* list = mode_ == Mode::Autonomy ? kmList : mode_ == Mode::Value ? offer_.valueShortcuts : mode_ == Mode::Time ? offer_.timeShortcuts : offer_.energyShortcuts;
      const uint8_t count = mode_ == Mode::Autonomy ? 4 : mode_ == Mode::Value ? offer_.valueCount : mode_ == Mode::Time ? offer_.timeCount : offer_.energyCount;
      const Action actions[] = {Action::Shortcut0, Action::Shortcut1, Action::Shortcut2, Action::Shortcut3};
      for (uint8_t i = 0; i < count && i < kShortcuts; ++i) {
        describe(a, sizeof(a), mode_, list[i]);
        setButton(next.options[i], a, actions[i], !busy);
      }
      copy(next.entryUnit, sizeof(next.entryUnit), mode_ == Mode::Value ? "R$" : mode_ == Mode::Time ? "min" : mode_ == Mode::Autonomy ? "km" : "kWh");
      next.decimalKey = mode_ == Mode::Energy;
      copy(next.entry, sizeof(next.entry), entry_);
      // Estimativa local (rotulada): energia/custo pelo preço e potência da oferta.
      const float price = offer_.pricePerKwh, power = offer_.powerKw;
      if (price > 0) {
        if (mode_ == Mode::Value) {
          formatDecimal(a, sizeof(a), 1.0f / price, 2);
          snprintf(text, sizeof(text), "%sR$ 1,00 = %s kWh", str::kEstimatePrefix, a);
        } else if (mode_ == Mode::Time && power > 0) {
          formatDecimal(a, sizeof(a), power, 1);
          snprintf(text, sizeof(text), "%sem 60 min, até %s kWh", str::kEstimatePrefix, a);
        } else {
          formatMoney(a, sizeof(a), static_cast<int32_t>(lroundf(price * 100)));
          snprintf(text, sizeof(text), "%s%s por kWh", str::kEstimatePrefix, a);
        }
        copy(next.subtitle, sizeof(next.subtitle), text);
      } else copy(next.subtitle, sizeof(next.subtitle), str::kEstimateNote);
      if (mode_ == Mode::Autonomy) {
        copy(next.subtitle, sizeof(next.subtitle), "Escolha quantos km quer adicionar. O cálculo usa o consumo do seu carro.");
        copy(next.context, sizeof(next.context), offer_.vehicleName);
      }
      if (next.keypad) {
        setButton(next.primary, str::kKeypadOk, Action::KeypadOk, entry_[0] && !busy);
        setButton(next.secondary, str::kBack, Action::Back);
      } else {
        setButton(next.primary, str::kOtherValue, Action::OtherValue, !busy);
        setButton(next.secondary, str::kBack, Action::Back);
      }
      if (busy && !error_[0]) copy(next.notice, sizeof(next.notice), str::kLoading);
      break;
    }
    case State::Review:
      next.screen = Screen::Review;
      copy(next.title, sizeof(next.title), str::kReviewTitle);
      copy(next.label, sizeof(next.label), quote_.label[0] ? quote_.label : label);
      describe(a, sizeof(a), quote_.mode, quote_.requested);
      snprintf(text, sizeof(text), "Você escolheu %s. Nada liga sem o pagamento confirmado.", a);
      copy(next.subtitle, sizeof(next.subtitle), text);
      if (quote_.pricePerKwh > 0) {
        formatMoney(a, sizeof(a), static_cast<int32_t>(lroundf(quote_.pricePerKwh * 100)));
        snprintf(text, sizeof(text), "%s/kWh", a);
        addMetric(next, str::kMetricPrice, text);
      }
      if (quote_.multiplier > 0 && quote_.basePrice > 0) {
        formatMoney(a, sizeof(a), static_cast<int32_t>(lroundf(quote_.basePrice * 100)));
        formatDecimal(b, sizeof(b), quote_.multiplier, 2);
        if (quote_.demandReason[0]) snprintf(text, sizeof(text), "%s x %s %s", a, b, quote_.demandReason);
        else snprintf(text, sizeof(text), "%s x %s", a, b);
        addMetric(next, str::kMetricDemand, text);
      }
      formatMoney(a, sizeof(a), quote_.amountCents);
      addMetric(next, str::kMetricCap, a);
      if (quote_.energyKwh > 0) {
        formatDecimal(a, sizeof(a), quote_.energyKwh, 1);
        snprintf(text, sizeof(text), "%s kWh", a);
        addMetric(next, str::kMetricEnergyEst, text);
      }
      if (quote_.minutes > 0) {
        snprintf(text, sizeof(text), "%ld min", static_cast<long>(quote_.minutes));
        addMetric(next, str::kMetricTimeEst, text);
      }
      addMetric(next, str::kMetricOverstay, quote_.overstaySummary[0] ? "Condições ao lado" : "Sem taxa");
      snprintf(next.context, sizeof(next.context), "Pagamento: %s. %s", paymentSource_ == Action::PayBalance ? "Saldo do app" : paymentSource_ == Action::PayPix ? "Pix" : "Cartão", quote_.overstaySummary[0] ? quote_.overstaySummary : "Sem taxa de permanência.");
      setButton(next.primary, str::kAccept, Action::Accept, quote_.loaded && !busy);
      if (quote_.autonomyNote[0] && !error_[0]) copy(next.notice, sizeof(next.notice), quote_.autonomyNote);
      setButton(next.secondary, str::kBack, Action::Back, !busy);
      if (busy && !error_[0]) copy(next.notice, sizeof(next.notice), str::kLoading);
      break;
    case State::Pay:
      next.screen = Screen::Pay;
      copy(next.title, sizeof(next.title), str::kPayTitle);
      copy(next.label, sizeof(next.label), label);
      formatMoney(a, sizeof(a), order_.amountCents > 0 ? order_.amountCents : quote_.amountCents);
      copy(next.qr, sizeof(next.qr), order_.qrUrl);
      copy(next.subtitle, sizeof(next.subtitle), order_.qrUrl[0] ? "Escaneie o QR para pagar. Depois confirme abaixo." : str::kPayCreating);
      snprintf(text, sizeof(text), "Total: %s", a);
      copy(next.qrCaption, sizeof(next.qrCaption), text);
      setButton(next.primary, "Já efetuei o pagamento", Action::SimulatePay, !busy);
      if (!error_[0] && order_.qrUrl[0]) { copy(next.notice, sizeof(next.notice), str::kPayWaiting); next.tone = Tone::Waiting; }
      if (error_[0] && !order_.qrUrl[0] && order_.method == Method::Stripe)
        setButton(next.primary, str::kRetry, Action::Retry, !busy);
      addMetric(next, str::kMetricCap, a);
      setButton(next.secondary, str::kCancel, Action::Cancel);
      break;
    case State::Starting:
      next.screen = Screen::Starting;
      copy(next.title, sizeof(next.title), str::kStartingTitle);
      copy(next.subtitle, sizeof(next.subtitle), str::kStartingDetail);
      copy(next.label, sizeof(next.label), label);
      next.tone = Tone::Success;
      break;
    case State::Live: case State::ConfirmStop: {
      next.screen = Screen::Live;
      next.socPercent = facts_.socPercent;
      copy(next.label, sizeof(next.label), label);
      const bool paused = facts_.appliedPowerKw == 0;
      copy(next.title, sizeof(next.title), paused ? str::kLivePaused : str::kLiveTitle);
      formatDecimal(a, sizeof(a), facts_.energyKwh, 2);
      snprintf(text, sizeof(text), "%s kWh", a);
      addMetric(next, str::kMetricEnergy, text);
      if (facts_.appliedPowerKw >= 0) { formatDecimal(a, sizeof(a), facts_.appliedPowerKw, 1); snprintf(text, sizeof(text), "%s kW", a); }
      else copy(text, sizeof(text), "--");
      addMetric(next, str::kMetricPower, text);
      formatMoney(a, sizeof(a), facts_.costCents);
      formatMoney(b, sizeof(b), facts_.capCents);
      snprintf(text, sizeof(text), facts_.capCents >= 0 ? "%s / %s" : "%s", a, b);
      addMetric(next, str::kMetricCost, text);
      snprintf(text, sizeof(text), "%lu min / faltam %lu", static_cast<unsigned long>(facts_.elapsedS / 60),
               static_cast<unsigned long>((facts_.remainingS + 59) / 60));
      addMetric(next, str::kMetricTime, text);
      if (facts_.socPercent >= 0) {
        snprintf(text, sizeof(text), "%d%%", facts_.socPercent >= 100 ? 100 : static_cast<int>(facts_.socPercent));
        addMetric(next, str::kMetricBattery, text);
      }
      // O motivo da potência (ex.: "Máx. do carregador") é contexto, não o subtítulo.
      copy(next.subtitle, sizeof(next.subtitle), str::kLiveHint);
      if (facts_.powerReason[0]) snprintf(next.context, sizeof(next.context), "Potência: %s", facts_.powerReason);
      setButton(next.primary, str::kStop, Action::Stop);
      if (state_ == State::ConfirmStop) {
        next.screen = Screen::ConfirmStop;
        copy(next.context, sizeof(next.context), returnFrom_ == State::Live ? str::kConfirmDetail : str::kConfirmAppDetail);
        setButton(next.primary, str::kYes, Action::ConfirmYes);
        setButton(next.secondary, str::kNo, Action::ConfirmNo);
      }
      break;
    }
    case State::Receipt: {
      next.screen = Screen::Receipt;
      copy(next.label, sizeof(next.label), label);
      const bool ours = facts_.sync.order.present && strcmp(facts_.sync.order.id, order_.id) == 0;
      const OrderReceipt receipt = ours ? facts_.sync.order.receipt : OrderReceipt{};
      const Facts& finalFacts = lastSessionFacts_.sessionId[0] &&
          (!facts_.sessionId[0] || same(facts_.sessionId, lastSessionFacts_.sessionId)) ? lastSessionFacts_ : facts_;
      const char* reason = facts_.endReason[0] ? facts_.endReason : receiptEndReason_[0] ? receiptEndReason_ : finalFacts.endReason;
      copy(next.title, sizeof(next.title), offlineStop_ ? str::kReceiptOffline : same(reason, "battery_full") ? str::kReceiptFull :
           same(reason, "cost_limit") ? str::kReceiptCost : same(reason, "duration_limit") ? str::kReceiptTime : str::kReceiptTitle);
      const float kwh = receipt.energyKwh >= 0 ? receipt.energyKwh : finalFacts.energyKwh;
      formatDecimal(a, sizeof(a), kwh, 2);
      snprintf(text, sizeof(text), "%s kWh", a);
      addMetric(next, str::kMetricEnergy, text);
      formatMoney(a, sizeof(a), receipt.totalCents >= 0 ? receipt.totalCents : finalFacts.costCents);
      addMetric(next, str::kMetricTotal, a);
      const bool simulated = order_.method == Method::Simulated || same(receipt.returnKind, "simulated");
      if (simulated && paymentSource_ != Action::PayBalance) addMetric(next, str::kMetricReturned, str::kSimulatedNoCharge);
      else if (receipt.returnedCents >= 0) { formatMoney(a, sizeof(a), receipt.returnedCents); addMetric(next, str::kMetricReturned, a); }
      if (receipt.number[0]) addMetric(next, str::kMetricReceipt, receipt.number);
      if (appSession_) {
        snprintf(text, sizeof(text), "%lu min", static_cast<unsigned long>((finalFacts.elapsedS + 59) / 60));
        addMetric(next, str::kMetricTime, text);
      }
      const char* url = receipt.url[0] ? receipt.url : order_.receiptUrl;
      const uint32_t elapsed = now_ - enteredAt_;
      if (url[0] && elapsed < kReceiptTimeoutMs) {
        copy(next.qr, sizeof(next.qr), url);
        const unsigned long seconds = (kReceiptTimeoutMs - elapsed + 999) / 1000;
        snprintf(next.qrCaption, sizeof(next.qrCaption), "Saindo em %lu %s", seconds, seconds == 1 ? "segundo" : "segundos");
      }
      if (facts_.carConnected && facts_.overstayTitle[0]) {
        copy(next.subtitle, sizeof(next.subtitle), facts_.overstayTitle);
        copy(next.notice, sizeof(next.notice), facts_.overstayDetail);
        next.disconnect = true;
        setButton(next.secondary, str::kDisconnect, Action::Disconnect);
      } else {
        copy(next.subtitle, sizeof(next.subtitle), appSession_ ? "Veja também o resumo e o comprovante no app ChargeGrid." : receipt.final ? str::kReceiptFinal :
             offlineStop_ ? str::kReceiptOfflineDetail : str::kReceiptPending);
      }
      if (!next.qr[0] && !facts_.carConnected && elapsed < kReceiptTimeoutMs) {
        const unsigned long seconds = (kReceiptTimeoutMs - elapsed + 999) / 1000;
        snprintf(next.notice, sizeof(next.notice), "Saindo em %lu %s", seconds, seconds == 1 ? "segundo" : "segundos");
      }
      setButton(next.primary, str::kDone, Action::Done);
      break;
    }
    case State::Notice:
      next.screen = Screen::Notice;
      copy(next.title, sizeof(next.title), noticeTitle_);
      copy(next.subtitle, sizeof(next.subtitle), noticeDetail_);
      next.tone = noticeTone_;
      if (noticeRetry_) {
        setButton(next.primary, "Tentar novamente", Action::Retry, !busy);
        setButton(next.secondary, str::kDone, Action::Done);
      } else setButton(next.primary, str::kDone, Action::Done);
      break;
    case State::Verifying:
      next.screen = Screen::Verifying;
      copy(next.title, sizeof(next.title), str::kVerifyingTitle);
      copy(next.subtitle, sizeof(next.subtitle), haveFacts_ && !facts_.online ? str::kVerifyingOffline : str::kVerifyingDetail);
      next.tone = Tone::Waiting;
      copy(next.label, sizeof(next.label), facts_.sync.kiosk.label);
      break;
  }
  next.revision = view_.revision;
  if (memcmp(&next, &view_, sizeof(next)) != 0) {
    next.revision = view_.revision + 1;
    view_ = next;
  }
}

}  // namespace kiosk
