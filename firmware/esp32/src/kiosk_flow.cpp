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
  } else copy(out, size, "");
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
         !facts_.reserved && !facts_.carConnected && !facts_.maintenance && !facts_.charging &&
         !facts_.sessionAuthorized && !order_.id[0];
}

void Flow::resume(const char* orderId, uint32_t nowMs) {
  if (!orderId || !*orderId || strlen(orderId) >= kIdSize) return;
  order_ = Order{};
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
  clearOrder();
  mode_ = Mode::None; entry_[0] = '\0'; keypad_ = false;
  queued_ = ApiRequest{};
  go(enabled_ ? State::Idle : State::Off, nowMs);
}

void Flow::notice(const char* title, const char* detail, Tone tone, uint32_t nowMs) {
  copy(noticeTitle_, sizeof(noticeTitle_), title);
  copy(noticeDetail_, sizeof(noticeDetail_), detail);
  noticeTone_ = tone;
  clearOrder();
  queued_ = ApiRequest{};
  go(State::Notice, nowMs);
}

void Flow::queue(RequestKind kind, const char* method, const char* path, const char* body, const char* key) {
  queued_ = ApiRequest{};
  queued_.kind = kind;
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

void Flow::requestQuote() {
  char body[160];
  const char* field = mode_ == Mode::Value ? "amount" : mode_ == Mode::Time ? "minutes" : "energy_kwh";
  char value[24];
  if (mode_ == Mode::Value) snprintf(value, sizeof(value), "\"%ld.%02ld\"", static_cast<long>(quote_.requested / 100), static_cast<long>(quote_.requested % 100));
  else if (mode_ == Mode::Time) snprintf(value, sizeof(value), "%ld", static_cast<long>(quote_.requested));
  else snprintf(value, sizeof(value), "\"%ld.%01ld\"", static_cast<long>(quote_.requested / 1000), static_cast<long>((quote_.requested % 1000) / 100));
  snprintf(body, sizeof(body), "{\"mode\":\"%s\",\"%s\":%s}", modeName(mode_), field, value);
  char path[64]; snprintf(path, sizeof(path), "%s/quote", kBase);
  queue(RequestKind::Quote, "POST", path, body, "");
}

void Flow::requestOrder() {
  if (!order_.idempotencyKey[0]) newKey(order_.idempotencyKey, sizeof(order_.idempotencyKey), "ko");
  char body[256];
  const char* field = mode_ == Mode::Value ? "amount" : mode_ == Mode::Time ? "minutes" : "energy_kwh";
  char value[24];
  if (mode_ == Mode::Value) snprintf(value, sizeof(value), "\"%ld.%02ld\"", static_cast<long>(quote_.requested / 100), static_cast<long>(quote_.requested % 100));
  else if (mode_ == Mode::Time) snprintf(value, sizeof(value), "%ld", static_cast<long>(quote_.requested));
  else snprintf(value, sizeof(value), "\"%ld.%01ld\"", static_cast<long>(quote_.requested / 1000), static_cast<long>((quote_.requested % 1000) / 100));
  char version[48] = "null";
  if (quote_.overstayVersion[0]) snprintf(version, sizeof(version), "\"%s\"", quote_.overstayVersion);
  snprintf(body, sizeof(body), "{\"quote_hash\":\"%s\",\"mode\":\"%s\",\"%s\":%s,\"overstay_terms_version\":%s}",
           quote_.hash, modeName(mode_), field, value, version);
  char path[64]; snprintf(path, sizeof(path), "%s/orders", kBase);
  queue(RequestKind::CreateOrder, "POST", path, body, order_.idempotencyKey);
}

void Flow::requestPay() {
  char path[96]; snprintf(path, sizeof(path), "%s/orders/%s/pay", kBase, order_.id);
  // Chave derivada do pedido: repetir (falha de rede, retomada após reboot) devolve o mesmo pagamento.
  char key[kIdSize + 8]; snprintf(key, sizeof(key), "pay-%s", order_.id);
  queue(RequestKind::Pay, "POST", path, "{}", key);
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
  requestQuote();
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
  offer_.basePrice = number(price["base_price_per_kwh"], -1);
  offer_.multiplier = number(price["demand_multiplier"], -1);
  offer_.powerKw = number(body["power_kw"], -1);
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
  httpsUrl(url, sizeof(url), payment["qr_url"].as<const char*>());
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
  offlineStop_ = offlineStop_ || same(facts_.endReason, "communication_lost") || !facts_.online;
  go(State::Receipt, nowMs);
}

// Estado do pedido pelo servidor (bloco kiosk_order do sync ou GET /orders/{id}).
void Flow::followOrder(const OrderBlock& block, uint32_t nowMs) {
  if (!block.present || strcmp(block.id, order_.id) != 0) return;
  missingOrderSince_ = 0;
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
  const bool foreignSession = incoming.sessionAuthorized && !sessionIsOurs(incoming);
  switch (state_) {
    case State::Off:
      if (enabled_) go(State::Idle, now);
      break;
    case State::Idle:
      if (!enabled_) go(State::Off, now);
      break;
    case State::LoadingOffer: case State::Choose: case State::Amount: case State::Review:
      // Antes de aceitar não há trava: qualquer mudança no ponto volta ao início, nada cobrado.
      if (!incoming.online) notice(str::kOfflineTitle, str::kOfflineDetail, Tone::Error, now);
      else if (incoming.charging || incoming.sessionAuthorized) notice(str::kAppStartedTitle, str::kAppStartedDetail, Tone::Error, now);
      else if (incoming.reserved) notice(str::kReservedTitle, str::kReservedDetail, Tone::Error, now);
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
      if (idle >= kReceiptTimeoutMs && !facts_.carConnected) { toIdle(now); return; }
      break;
    case State::Notice:
      if (inState >= kNoticeMs) { toIdle(now); return; }
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
        char path[64]; snprintf(path, sizeof(path), "%s/offer", kBase);
        queue(RequestKind::Offer, "GET", path, "", "");
        go(State::LoadingOffer, now);
      } else if (action == Action::Stop && haveFacts_ && facts_.charging) {
        // Recarga iniciada pelo app: Encerrar no totem pede confirmação.
        returnFrom_ = state_;
        go(State::ConfirmStop, now);
      }
      break;
    case State::LoadingOffer:
      if (action == Action::Back || action == Action::Cancel) toIdle(now);
      break;
    case State::Choose:
      if (action == Action::ModeValue) selectMode(Mode::Value, now);
      else if (action == Action::ModeTime) selectMode(Mode::Time, now);
      else if (action == Action::ModeEnergy) selectMode(Mode::Energy, now);
      else if (action == Action::Back || action == Action::Cancel) toIdle(now);
      break;
    case State::Amount: {
      if (queued_.kind == RequestKind::Quote || inFlight_.kind == RequestKind::Quote) break;  // aguardando orçamento
      const int32_t* list = mode_ == Mode::Value ? offer_.valueShortcuts : mode_ == Mode::Time ? offer_.timeShortcuts : offer_.energyShortcuts;
      const uint8_t count = mode_ == Mode::Value ? offer_.valueCount : mode_ == Mode::Time ? offer_.timeCount : offer_.energyCount;
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
      else if (action == Action::Back) { quote_ = Quote{}; go(State::Amount, now); }
      else if (action == Action::Cancel) toIdle(now);
      break;
    case State::Pay:
      if (action == Action::Cancel) {
        abortOrder(str::kCanceledTitle, str::kCanceledDetail, now);
      } else if (requestInFlight() || queued_.kind != RequestKind::None) {
        break;
      } else if (action == Action::SimulatePay && order_.method == Method::Simulated) {
        error_[0] = '\0'; requestPay();
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
      if (action == Action::Done) toIdle(now);
      break;
    case State::Starting: case State::Verifying:
      break;
  }
  render();
}

void Flow::key(char k, uint32_t now) {
  now_ = now;
  lastInput_ = now;
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
  switch (result.kind) {
    case RequestKind::Offer:
      if (state_ != State::LoadingOffer) break;
      if (ok) {
        applyOffer(body);
        if (!offer_.active) notice(str::kUnavailableTitle, str::kUnavailableDetail, Tone::Neutral, now);
        else if (offer_.available) go(State::Choose, now);
        else if (same(offer_.reason, "kiosk_in_use") && offer_.openOrderId[0]) resume(offer_.openOrderId, now);
        else if (same(offer_.reason, "reserved")) notice(str::kReservedTitle, str::kReservedDetail, Tone::Error, now);
        else if (same(offer_.reason, "charging")) notice(str::kAppStartedTitle, str::kAppStartedDetail, Tone::Error, now);
        else if (same(offer_.reason, "offline")) notice(str::kOfflineTitle, str::kOfflineDetail, Tone::Error, now);
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
        notice(str::kOfflineTitle, str::kNetworkError, Tone::Error, now);
      }
      break;
    case RequestKind::Quote:
      if (state_ != State::Amount && state_ != State::Review) break;
      if (ok && applyQuote(body)) {
        const bool changed = state_ == State::Review;
        go(State::Review, now);
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
        snprintf(error_, sizeof(error_), "%s%s a %s", str::kOutOfRange, a, b);
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
      } else if (result.status == 409 || result.status == 410 || result.status == 404) {
        notice(str::kCanceledTitle, str::kCanceledDetail, Tone::Error, now);
      } else {
        copy(error_, sizeof(error_), str::kNetworkError);       // 502/timeout: repetir com a mesma chave
      }
      break;
    case RequestKind::Cancel:
      break;  // o aviso já está na tela; sem rede a trava vence sozinha no servidor
    case RequestKind::GetOrder:
      if (state_ != State::Verifying) break;
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
    case State::LoadingOffer:
      next.screen = Screen::Choose;
      copy(next.title, sizeof(next.title), str::kChooseTitle);
      copy(next.subtitle, sizeof(next.subtitle), str::kLoading);
      setButton(next.options[0], str::kModeValue, Action::ModeValue, false);
      setButton(next.options[1], str::kModeTime, Action::ModeTime, false);
      setButton(next.options[2], str::kModeEnergy, Action::ModeEnergy, false);
      setButton(next.secondary, str::kBack, Action::Back);
      copy(next.label, sizeof(next.label), facts_.sync.kiosk.label);
      break;
    case State::Choose:
      next.screen = Screen::Choose;
      copy(next.title, sizeof(next.title), str::kChooseTitle);
      copy(next.subtitle, sizeof(next.subtitle), str::kChooseCable);
      setButton(next.options[0], str::kModeValue, Action::ModeValue);
      setButton(next.options[1], str::kModeTime, Action::ModeTime);
      setButton(next.options[2], str::kModeEnergy, Action::ModeEnergy);
      setButton(next.secondary, str::kBack, Action::Back);
      copy(next.label, sizeof(next.label), label);
      break;
    case State::Amount: {
      next.screen = Screen::Amount;
      copy(next.label, sizeof(next.label), label);
      copy(next.title, sizeof(next.title), mode_ == Mode::Value ? str::kAmountValueTitle :
           mode_ == Mode::Time ? str::kAmountTimeTitle : str::kAmountEnergyTitle);
      const int32_t* list = mode_ == Mode::Value ? offer_.valueShortcuts : mode_ == Mode::Time ? offer_.timeShortcuts : offer_.energyShortcuts;
      const uint8_t count = mode_ == Mode::Value ? offer_.valueCount : mode_ == Mode::Time ? offer_.timeCount : offer_.energyCount;
      const Action actions[] = {Action::Shortcut0, Action::Shortcut1, Action::Shortcut2, Action::Shortcut3};
      for (uint8_t i = 0; i < count && i < kShortcuts; ++i) {
        describe(a, sizeof(a), mode_, list[i]);
        setButton(next.options[i], a, actions[i], !busy);
      }
      copy(next.entryUnit, sizeof(next.entryUnit), mode_ == Mode::Value ? "R$" : mode_ == Mode::Time ? "min" : "kWh");
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
      addMetric(next, str::kMetricOverstay, quote_.overstaySummary[0] ? quote_.overstaySummary : "Sem taxa");
      setButton(next.primary, str::kAccept, Action::Accept, quote_.loaded && !busy);
      setButton(next.secondary, str::kBack, Action::Back, !busy);
      if (busy && !error_[0]) copy(next.notice, sizeof(next.notice), str::kLoading);
      break;
    case State::Pay:
      next.screen = Screen::Pay;
      copy(next.title, sizeof(next.title), str::kPayTitle);
      copy(next.label, sizeof(next.label), label);
      formatMoney(a, sizeof(a), order_.amountCents > 0 ? order_.amountCents : quote_.amountCents);
      if (order_.method == Method::Simulated) {
        copy(next.subtitle, sizeof(next.subtitle), str::kPaySimHint);
        snprintf(text, sizeof(text), "Simular pagamento de %s (sem cobrança)", a);
        setButton(next.primary, text, Action::SimulatePay, !busy);
      } else {
        copy(next.subtitle, sizeof(next.subtitle), order_.qrUrl[0] ? str::kPayStripeHint : str::kPayCreating);
        copy(next.qr, sizeof(next.qr), order_.qrUrl);
        snprintf(text, sizeof(text), "%s %s", str::kPayStripeCaption, a);
        copy(next.qrCaption, sizeof(next.qrCaption), text);
        if (!error_[0] && order_.qrUrl[0]) { copy(next.notice, sizeof(next.notice), str::kPayWaiting); next.tone = Tone::Waiting; }
        if (error_[0] && !order_.qrUrl[0]) setButton(next.primary, str::kRetry, Action::Retry, !busy);
      }
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
      if (state_ == State::ConfirmStop) {
        next.screen = Screen::ConfirmStop;
        const bool own = returnFrom_ == State::Live;
        copy(next.title, sizeof(next.title), own ? str::kConfirmTitle : str::kConfirmAppTitle);
        copy(next.subtitle, sizeof(next.subtitle), own ? str::kConfirmDetail : str::kConfirmAppDetail);
        setButton(next.primary, str::kYes, Action::ConfirmYes);
        setButton(next.secondary, str::kNo, Action::ConfirmNo);
        if (own) copy(next.label, sizeof(next.label), label);
        break;
      }
      next.screen = Screen::Live;
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
      if (facts_.powerReason[0]) copy(next.subtitle, sizeof(next.subtitle), facts_.powerReason);
      else copy(next.subtitle, sizeof(next.subtitle), str::kLiveHint);
      setButton(next.primary, str::kStop, Action::Stop);
      break;
    }
    case State::Receipt: {
      next.screen = Screen::Receipt;
      copy(next.label, sizeof(next.label), label);
      const bool ours = facts_.sync.order.present && strcmp(facts_.sync.order.id, order_.id) == 0;
      const OrderReceipt receipt = ours ? facts_.sync.order.receipt : OrderReceipt{};
      const char* reason = facts_.endReason[0] ? facts_.endReason : receiptEndReason_;
      copy(next.title, sizeof(next.title), offlineStop_ ? str::kReceiptOffline : same(reason, "battery_full") ? str::kReceiptFull :
           same(reason, "cost_limit") ? str::kReceiptCost : same(reason, "duration_limit") ? str::kReceiptTime : str::kReceiptTitle);
      const float kwh = receipt.energyKwh >= 0 ? receipt.energyKwh : facts_.energyKwh;
      formatDecimal(a, sizeof(a), kwh, 2);
      snprintf(text, sizeof(text), "%s kWh", a);
      addMetric(next, str::kMetricEnergy, text);
      formatMoney(a, sizeof(a), receipt.totalCents >= 0 ? receipt.totalCents : facts_.costCents);
      addMetric(next, str::kMetricTotal, a);
      const bool simulated = order_.method == Method::Simulated || same(receipt.returnKind, "simulated");
      if (simulated) addMetric(next, str::kMetricReturned, str::kSimulatedNoCharge);
      else if (receipt.returnedCents >= 0) { formatMoney(a, sizeof(a), receipt.returnedCents); addMetric(next, str::kMetricReturned, a); }
      if (receipt.number[0]) addMetric(next, str::kMetricReceipt, receipt.number);
      const char* url = receipt.url[0] ? receipt.url : order_.receiptUrl;
      if (url[0]) {
        copy(next.qr, sizeof(next.qr), url);
        copy(next.qrCaption, sizeof(next.qrCaption), str::kReceiptQrCaption);
      }
      if (facts_.carConnected && facts_.overstayTitle[0]) {
        copy(next.subtitle, sizeof(next.subtitle), facts_.overstayTitle);
        copy(next.notice, sizeof(next.notice), facts_.overstayDetail);
        next.disconnect = true;
        setButton(next.secondary, str::kDisconnect, Action::Disconnect);
      } else {
        copy(next.subtitle, sizeof(next.subtitle), receipt.final ? str::kReceiptFinal :
             offlineStop_ ? str::kReceiptOfflineDetail : str::kReceiptPending);
      }
      setButton(next.primary, str::kDone, Action::Done);
      break;
    }
    case State::Notice:
      next.screen = Screen::Notice;
      copy(next.title, sizeof(next.title), noticeTitle_);
      copy(next.subtitle, sizeof(next.subtitle), noticeDetail_);
      next.tone = noticeTone_;
      setButton(next.primary, str::kDone, Action::Done);
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
