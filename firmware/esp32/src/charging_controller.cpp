#include "runtime.h"
#include "extra_chargers.h"
#include <time.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
// Estado 0.7.0 definido aqui (e não em main.cpp) para os testes de host o reutilizarem.
float sessionAppliedPowerKw = -1;
String powerReasonShort;
String kioskUrl, paymentStatus;
float paymentAmount = -1;
bool paymentTest = false;
bool overstayEnabled = false;
String overstayStatus;
long overstayGraceSeconds = 0;
unsigned long overstayReceivedAt = 0;
float overstayFeeDue = -1, overstayMaxFee = -1, overstayAmount = -1;
long overstayIntervalMinutes = 0;
// 0.8.0: blocos do totem no sync (definidos aqui para os testes de host).
kiosk::SyncFacts kioskSync;
// Carregador GoodWe HCA G2 do conector (connector.charger_link; todo conector é um carregador).
// API antiga, sem charger_link: nada abaixo é chamado.
charger::Link chargerLink;
// Sessão no carregador GoodWe (Modbus): true em toda recarga com charger_link; false só com uma
// API antiga, sem charger_link (simulação interna da tela, como antes).
bool sessionOnCharger = false;
static charger::Error chargerStopResult = charger::Error::None;
float chargerLinkLimitW(float requestedW) {
  return (float)hca::powerWForRegister(hca::registerForPowerW(lroundf(requestedW)));
}
// A API serializa Decimal como texto ("42.50"); aceita número ou texto numérico.
static float jsonNumber(JsonVariantConst value, float fallback) {
  if (value.is<const char*>()) {
    const char* text = value.as<const char*>();
    char* end = nullptr;
    const float parsed = strtof(text, &end);
    return end != text ? parsed : fallback;
  }
  return value.is<float>() ? value.as<float>() : fallback;
}
static bool validSocSource(const char* source) {
  return source && (strcmp(source, "simulated") == 0 || strcmp(source, "phone") == 0);
}
static void resetSessionSoc() {
  socStartPercent = -1; batteryKwh = 0; phoneSocPercent = -1; socSource = "";
}
// Lê soc_percent/battery_kwh/soc_source do START (campos ausentes: firmware antigo/API antiga).
static void readStartSoc(JsonObjectConst source) {
  if (source.isNull()) return;
  const float soc = jsonNumber(source["soc_percent"], -1);
  if (soc >= 0 && soc <= 100) socStartPercent = soc;
  const float battery = jsonNumber(source["battery_kwh"], 0);
  if (battery >= 1 && battery <= 1000) batteryKwh = battery;
  const char* kind = source["soc_source"].as<const char*>();
  if (validSocSource(kind)) socSource = kind;
}
float chargerLimitW(float requestedW) {
  if (!(requestedW > 0)) return 0;
  const float capped = min(requestedW, (float)kChargerMaxPowerW);
  const float stepped = floorf(capped / kChargerStepW) * kChargerStepW;
  return stepped >= kChargerMinPowerW ? stepped : 0;
}
static bool validPowerLimit(float watts) { return watts >= 0 && watts <= 1000000; }
String panelLatin1(const char* text, size_t maxChars) {
  char out[64 * 3 + 1]{};
  size_t length = 0, kept = 0;
  maxChars = min(maxChars, (size_t)64);
  const unsigned char* c = reinterpret_cast<const unsigned char*>(text ? text : "");
  while (*c && kept < maxChars) {
    uint32_t cp = *c; int extra = 0;
    if (cp >= 0xF0) { cp &= 0x07; extra = 3; }
    else if (cp >= 0xE0) { cp &= 0x0F; extra = 2; }
    else if (cp >= 0xC0) { cp &= 0x1F; extra = 1; }
    else if (cp >= 0x80) { ++c; continue; } // Byte de continuação solto: descarta.
    ++c;
    bool valid = true;
    for (int i = 0; i < extra; ++i, ++c) {
      if ((*c & 0xC0) != 0x80) { valid = false; break; }
      cp = (cp << 6) | (*c & 0x3F);
    }
    if (!valid) continue;
    // Sem espaço no início nem espaços repetidos (ex.: onde havia um travessão).
    if (cp == ' ' && (kept == 0 || out[length - 1] == ' ')) continue;
    if (cp >= 0x20 && cp <= 0x7E) out[length++] = static_cast<char>(cp);
    else if (cp >= 0xA0 && cp <= 0xFF) {
      out[length++] = static_cast<char>(0xC0 | (cp >> 6));
      out[length++] = static_cast<char>(0x80 | (cp & 0x3F));
    } else if (cp == 0x2022) { out[length++] = '\xE2'; out[length++] = '\x80'; out[length++] = '\xA2'; }
    else continue; // Fora das fontes do painel (ex.: travessão, emoji): omitido.
    ++kept;
  }
  while (length && out[length - 1] == ' ') out[--length] = '\0';
  return String(out);
}
// Potência inicial do START: power_limit_w (0 = começa pausado) prevalece quando presente;
// sem o campo, max_power_kw legado (parameters prevalecem sobre a sessão) ou o nominal.
static float readStartPower(JsonObjectConst parameters, JsonObjectConst session) {
  if (!parameters["power_limit_w"].isNull()) {
    const float limit = jsonNumber(parameters["power_limit_w"], -1);
    if (validPowerLimit(limit)) return chargerLimitW(limit);
  }
  float cap = jsonNumber(parameters["max_power_kw"], -1);
  if (!(cap >= 0.1f && cap <= 1000)) cap = jsonNumber(session["max_power_kw"], -1);
  return cap >= 0.1f && cap <= 1000 ? min(kBenchPowerW, cap * 1000.0f) : kBenchPowerW;
}
static void persistSessionSoc() {
  store.putFloat("soc0", socStartPercent);
  store.putFloat("batt", batteryKwh);
  store.putString("socsrc", socSource);
}
static float batteryFullWh() {
  if (socSource != "simulated" || socStartPercent < 0 || batteryKwh <= 0) return -1;
  return (100.0f - socStartPercent) / 100.0f * batteryKwh * 1000.0f;
}
bool sessionSocKnown() {
  if (socSource == "phone") return phoneSocPercent >= 0;
  return batteryFullWh() >= 0;
}
float currentSessionSoc(float energyWh) {
  if (socSource == "phone" && phoneSocPercent >= 0) return phoneSocPercent;
  if (batteryFullWh() >= 0) return min(100.0f, socStartPercent + energyWh / (10.0f * batteryKwh));
  return min(100.0f, 20.0f + energyWh / 600.0f); // Bancada legada, sem SoC da API.
}
String isoTime() {
  time_t now = time(nullptr);
  struct tm utc;
  gmtime_r(&now, &utc);
  char buffer[25];
  strftime(buffer, sizeof(buffer), "%Y-%m-%dT%H:%M:%SZ", &utc);
  return String(buffer);
}
// ISO 8601 da API: frações de segundo e fuso opcionais ("Z", "+00:00", "-03:00", "-0300").
// A API serializa os horários vindos do banco no fuso da sessão do PostgreSQL (expires_at
// pode chegar com -03:00); ignorar o fuso faria um comando válido parecer vencido.
time_t parseTime(const char* value) {
  if (!value) return 0;
  struct tm utc{};
  const char* rest = strptime(value, "%Y-%m-%dT%H:%M:%S", &utc);
  if (!rest) return 0;
  if (*rest == '.') while (*++rest >= '0' && *rest <= '9') {}
  long offset = 0;
  if (*rest == '+' || *rest == '-') {
    const int sign = *rest == '-' ? -1 : 1;
    int digits[4], count = 0;
    for (const char* c = rest + 1; *c && count < 4; ++c) {
      if (*c == ':' && count == 2) continue;
      if (*c < '0' || *c > '9') break;
      digits[count++] = *c - '0';
    }
    if (count != 2 && count != 4) return 0;
    const long hours = digits[0] * 10 + digits[1];
    const long minutes = count == 4 ? digits[2] * 10 + digits[3] : 0;
    if (hours > 23 || minutes > 59) return 0;
    offset = sign * (hours * 3600 + minutes * 60);
  }
  return mktime(&utc) - offset; // TZ é UTC; sem fuso: UTC (formato anterior).
}
void persist() {
  store.putUInt("version", version);
  store.putString("command", lastCommand);
  store.putString("session", sessionId);
  store.putFloat("energy", reading.energyWh);
}
void stop(const char* reason) {
  state = "stopped";
  reading.powerW = 0;
  // Com permanência o carro continua conectado até o toque em "Desconectar".
  reading.connected = overstayEnabled;
  endReason = reason;
  persist();
  // Sessão no carregador GoodWe: 10060 = 1 confirmado por leitura (sem resposta, tenta de novo
  // na leitura periódica e o watchdog de 15 s do carregador abre o relé). Sessão simulada: só local.
  chargerStopResult = sessionOnCharger && chargerLink.active() ? chargerLink.stop(millis()) : charger::Error::None;
}
// Reboot: saída desenergizada, carro tratado como desconectado (conservador) e sessão
// anterior apenas relatada para reconciliação, nunca retomada.
void applyBootSafety() {
  reading.powerW = 0;
  reading.connected = false;
  overstayEnabled = false;
  chargePowerW = kBenchPowerW;
  sessionOnCharger = false;
  // A tela reiniciou com a sessão aberta (não foi o vigia de 45 s sem a API): motivo verdadeiro.
  if (sessionId.length()) { state = "stopped"; endReason = "device_reboot"; }
}
void requestLocalSafeStop() {
  if (state == "charging") {
    stop("requested");
    nextSync = millis();
  }
}
bool requestLocalDisconnect() {
  if (state == "charging" || !reading.connected) return false;
  reading.connected = false;
  overstayEnabled = false;
  nextSync = millis(); // A API encerra a permanência no próximo sync.
  return true;
}
JsonObject ack(const String& id, const char* status, const char* error = nullptr) {
  JsonObject item = acknowledgements.as<JsonArray>().add<JsonObject>();
  item["command_id"] = id;
  item["status"] = status;
  item["error"] = error;
  return item;
}
void tick() {
  unsigned long now = millis();
  unsigned long elapsed = now - lastTick;
  lastTick = now;
  if (state == "charging") {
    // Sessão no carregador GoodWe: integra a potência lida no 10015 (SIMULADA no simulador).
    const float powerW = sessionOnCharger ? (float)chargerLink.measuredPowerW() : chargePowerW;
    // O relógio local limita a energia, mesmo durante falha HTTP.
    unsigned long overdueContact = now - lastContact > 45000 ? now - lastContact - 45000 : 0;
    unsigned long overdueDuration = now - started > maxDurationMs ? now - started - maxDurationMs : 0;
    unsigned long overdue = max(overdueContact, overdueDuration);
    unsigned long permittedElapsed = elapsed > overdue ? elapsed - overdue : 0;
    const float effectivePrice = price * (1 - discount / 100);
    bool costCapped = false, fullCapped = false;
    // Pausado (0 W): nenhum limite de tempo derivado da potência (sem divisão por zero).
    if (maxCost >= 0 && effectivePrice > 0 && powerW > 0) {
      const float remainingWh = max(0.0f, maxCost * 1000 / effectivePrice - reading.energyWh);
      const unsigned long costElapsed = (unsigned long)(remainingWh * 3600000 / powerW);
      if (costElapsed < permittedElapsed) { permittedElapsed = costElapsed; costCapped = true; }
    }
    // Bateria simulada: não entrega energia além dos 100 %, mesmo com a rede bloqueada.
    const float fullWh = batteryFullWh();
    if (fullWh >= 0 && powerW > 0) {
      const float remainingWh = max(0.0f, fullWh - reading.energyWh);
      const unsigned long fullElapsed = (unsigned long)(remainingWh * 3600000 / powerW);
      if (fullElapsed < permittedElapsed) { permittedElapsed = fullElapsed; fullCapped = true; }
    }
    reading = sensors.read(true, permittedElapsed, powerW);
    reading.socPercent = currentSessionSoc(reading.energyWh);
    if (now - lastSaved >= 30000) { persist(); lastSaved = now; }
    if (now - lastContact >= 45000) stop("communication_lost");
    else if (now - started >= maxDurationMs) stop("duration_limit");
    else if (fullWh >= 0 && (fullCapped || reading.energyWh >= fullWh - 0.01f)) {
      reading.socPercent = 100;
      stop("battery_full");
      nextSync = millis(); // A API encerra com battery_full no próximo sync.
    }
    else if (maxCost >= 0 && (reading.energyWh / 1000 * effectivePrice >= maxCost || costCapped)) stop("cost_limit");
  } else if (state == "reserved" && reservationDeadline && time(nullptr) >= reservationDeadline) {
    state = "idle";
  }
}
// Pagamento no painel (connector.kiosk_url / connector.payment), modo teste. Ausente: sem QR.
static void readKiosk(JsonObjectConst connector) {
  const char* url = connector["kiosk_url"].as<const char*>();
  kioskUrl = url && strlen(url) <= 160 && strncmp(url, "https://", 8) == 0 ? url : "";
  JsonObjectConst payment = connector["payment"].as<JsonObjectConst>();
  const char* status = payment["status"].as<const char*>();
  const bool known = status && (strcmp(status, "awaiting_payment") == 0 || strcmp(status, "authorized") == 0 ||
      strcmp(status, "paid") == 0 || strcmp(status, "declined") == 0);
  paymentStatus = known ? status : "";
  paymentAmount = known ? jsonNumber(payment["amount"], -1) : -1;
  paymentTest = known && payment["environment"] == "test";
}
// Permanência (overstay no nível de cima da resposta). null/ausente: sem permanência.
static void readOverstay(JsonObjectConst overstay) {
  const char* status = overstay["status"].as<const char*>();
  const bool known = status && (strcmp(status, "grace") == 0 || strcmp(status, "billing") == 0 ||
      strcmp(status, "capped") == 0 || strcmp(status, "closed") == 0 || strcmp(status, "no_fee") == 0);
  overstayStatus = known ? status : "";
  overstayGraceSeconds = known ? max(0L, (long)jsonNumber(overstay["grace_remaining_seconds"], 0)) : 0;
  overstayReceivedAt = millis();
  overstayFeeDue = known ? jsonNumber(overstay["fee_due"], -1) : -1;
  overstayMaxFee = known ? jsonNumber(overstay["max_fee"], -1) : -1;
  overstayAmount = known ? jsonNumber(overstay["amount"], -1) : -1;
  overstayIntervalMinutes = known ? (long)jsonNumber(overstay["interval_minutes"], 0) : 0;
}
// Potência aplicada e motivo da sessão ativa (authorized.session). Só exibição.
static void readSessionPower(JsonObjectConst session) {
  const float applied = jsonNumber(session["applied_power_kw"], -1);
  sessionAppliedPowerKw = applied >= 0 && applied <= 1000 ? applied : -1;
  powerReasonShort = panelLatin1(session["power_reason_short"].as<const char*>(), 40);
}
void fillSyncBody(JsonDocument& body, bool extensions) {
  body["firmware_version"] = CHARGEGRID_FIRMWARE_VERSION;
  if (sessionId.length()) body["session_id"] = sessionId; else body["session_id"] = nullptr;
  body["physical_state"] = state; body["connected"] = reading.connected;
  // SoC próprio só na fonte simulada com bateria conhecida (o valor do ponto prevalece
  // na API). Fonte phone ou sessão sem dados de bateria: null, nunca eco da API.
  if (sessionId.length() && socSource == "simulated" && sessionSocKnown()) body["soc_percent"] = reading.socPercent;
  else body["soc_percent"] = nullptr;
  body["energy_wh"] = reading.energyWh; body["power_w"] = reading.powerW;
  body["source"] = "simulated"; body["captured_at"] = isoTime();
  if (endReason.length()) body["end_reason"] = endReason; else body["end_reason"] = nullptr;
  body["acks"] = acknowledgements.as<JsonArray>();
  if (!extensions) return;
  JsonArray capabilities = body["capabilities"].to<JsonArray>();
  capabilities.add("set_power_v1");
  capabilities.add("multi_charger_v1");  // estação: comanda os carregadores adicionais (sync endereçado)
  // Limite instalado agora: 0 fora de recarga ou pausado (resolve ACK perdido na API).
  body["applied_power_w"] = state == "charging" ? lroundf(chargePowerW) : 0L;
  JsonObject charger = body["charger"].to<JsonObject>();
  // Limites do carregador GoodWe quando ele responde (ou na recarga por Modbus); offline, os de
  // sempre com link "offline" (o START seria recusado com charger_offline).
  const bool viaCharger = chargerLink.active() && (state == "charging" ? sessionOnCharger : chargerLink.online());
  if (viaCharger) {
    // Carregador GoodWe HCA G2 do conector (simulado no ESP32 DevKit) por Modbus TCP na rede local.
    charger["model"] = "goodwe_hca_g2"; charger["variant"] = hca::kGw7k.name;
    charger["transport"] = "modbus_tcp";
    charger["min_power_w"] = hca::powerWForRegister(hca::kGw7k.minTenths);
    charger["max_power_w"] = hca::powerWForRegister(hca::kGw7k.maxTenths);
    charger["step_w"] = 100; charger["phases"] = hca::kGw7k.phases;
  } else {
    // Bancada/simulação interna (API sem charger_link) ou carregador offline: limites de sempre.
    charger["model"] = "esp32_bench"; charger["transport"] = "simulated";
    charger["min_power_w"] = kChargerMinPowerW; charger["max_power_w"] = kChargerMaxPowerW;
    charger["step_w"] = kChargerStepW; charger["phases"] = 1;
  }
  if (chargerLink.active()) {
    // Endereço do carregador do conector e se ele responde agora (offline = START recusado).
    charger["address"] = chargerLink.config().address;
    charger["link"] = chargerLink.online() ? "online" : "offline";
  }
}
// connector.charger_link (aditivo; a API manda para todo conector): ausente/null/inválido = API
// antiga, só a simulação interna. A troca só vale fora de recarga; uma recarga em andamento
// termina com o carregador que a iniciou.
static void readChargerLink(JsonObjectConst connector) {
  charger::LinkConfig config;
  JsonObjectConst link = connector["charger_link"].as<JsonObjectConst>();
  if (!link.isNull())
    charger::makeConfig(link["model"].as<const char*>(), link["transport"].as<const char*>(),
                        link["address"].is<long>() ? link["address"].as<long>() : 0L,
                        link["host"].as<const char*>(),
                        link["port"].is<long>() ? link["port"].as<long>() : (long)hca::kDefaultPort, config);
  if (state != "charging") chargerLink.configure(config);
}
void chargerLinkService() {
  if (!chargerLink.active()) return;
  const unsigned long now = millis();
  chargerLink.poll(now); // Também fora de recarga: o link online/offline vai no sync (disponibilidade).
  // Sessão no carregador: sumiu por 5 s, alarme ou parou sozinho → parada segura local.
  if (state == "charging" && sessionOnCharger && chargerLink.faulted(now, true)) {
    tick(); // Integra a energia até a perda.
    if (state == "charging") {
      // Mesma parada segura local; o motivo vai no próximo sync (imediato).
      stop("device_fault");
      nextSync = millis();
    }
  }
}
static bool extensionField(const char* field) {
  if (!field) return false;
  for (const char* name : {"capabilities", "applied_power_w", "charger"}) {
    const size_t length = strlen(name);
    if (strncmp(field, name, length) == 0 && (field[length] == '\0' || field[length] == '.')) return true;
  }
  return false;
}
bool syncRejectedExtensions(const char* body) {
  JsonDocument doc;
  if (!body || deserializeJson(doc, body)) return false;
  // API ChargeGrid: {"error":{"code":"validation_error","fields":[{"field":"capabilities",...}]}}.
  // invalid_time, energy_regression e session_required também são 422, mas não são campos 0.7.0.
  if (doc["error"]["code"] == "validation_error") {
    for (JsonObjectConst item : doc["error"]["fields"].as<JsonArrayConst>())
      if (extensionField(item["field"].as<const char*>())) return true;
    return false;
  }
  // FastAPI sem o tratador próprio: {"detail":[{"loc":["body","capabilities"],...}]}.
  for (JsonObjectConst item : doc["detail"].as<JsonArrayConst>())
    if (item["loc"][0] == "body" && extensionField(item["loc"][1].as<const char*>())) return true;
  return false;
}
bool apply(JsonDocument& response) {
  acknowledgements.to<JsonArray>();
  connectorPublicCode = response["connector"]["public_code"] | "--";
  JsonObjectConst connector = response["connector"].as<JsonObjectConst>();
  readKiosk(connector);
  readChargerLink(connector);
  // Carregadores adicionais desta tela (sync endereçado por cada um); API antiga: nenhum.
  extra::configure(response["chargers"].as<JsonArrayConst>(), millis());
  readOverstay(response["overstay"].as<JsonObjectConst>());
  // Totem 0.8.0: leitura aditiva; sem os blocos (API antiga ou totem desligado) = desligado.
  kiosk::readSync(response.as<JsonObjectConst>(), kioskSync);
  if (connector["owned"].is<bool>()) {
    connectorOwnershipKnown = true;
    if (connector["owned"].as<bool>()) confirmPanelOwnership();
  }
  if (connector["active"].is<bool>()) connectorActive = connector["active"].as<bool>();
  JsonObject authorization = response["authorized"].as<JsonObject>();
  reservationDeadline = parseTime(authorization["reservation"]["expires_at"]);
  JsonObject authorizedSession = authorization["session"].as<JsonObject>();
  sessionAppliedPowerKw = -1; powerReasonShort = "";
  if (!authorizedSession.isNull() && authorizedSession["id"].as<String>() == sessionId) {
    readSessionPower(authorizedSession);
    price = authorizedSession["price_per_kwh"].as<float>();
    discount = authorizedSession["discount_percent"] | 0.0f;
    sessionPricingKnown = true;
    // SoC da sessão ativa: o app pode trocar a fonte para o celular durante a recarga.
    const char* kind = authorizedSession["soc_source"].as<const char*>();
    if (validSocSource(kind)) socSource = kind;
    if (batteryKwh <= 0) {
      const float battery = jsonNumber(authorizedSession["battery_kwh"], 0);
      if (battery >= 1 && battery <= 1000) batteryKwh = battery;
    }
    if (socStartPercent < 0) {
      const float start = jsonNumber(authorizedSession["start_soc_percent"], -1);
      if (start >= 0 && start <= 100) socStartPercent = start;
    }
    if (socSource == "phone") {
      // Nível real do celular enviado pelo app: o ponto exibe e reporta, nunca recalcula.
      const float phone = jsonNumber(authorizedSession["soc_percent"], -1);
      if (phone >= 0 && phone <= 100) phoneSocPercent = phone;
      else if (phoneSocPercent < 0) phoneSocPercent = socStartPercent;
    }
    reading.socPercent = currentSessionSoc(reading.energyWh);
  }
  if (state == "stopped" && ((!authorization["session"].isNull() && authorization["session"]["id"].as<String>() != sessionId) || (!authorization["reservation"].isNull() && authorization["session"].isNull()))) {
    sessionId = ""; reading.energyWh = 0; endReason = ""; sessionPricingKnown = false; resetSessionSoc();
  }
  bool changed = false;
  uint32_t current = response["control_version"] | 0;
  time_t serverTime = parseTime(response["server_time"]);
  time_t presenceExpires = parseTime(connector["presence_expires_at"]);
  stationPresenceCode = connector["presence_code"].as<String>();
  presenceCodeReceivedAt = millis();
  presenceCodeTtlMs = stationPresenceCode.length() && presenceExpires > serverTime
      ? static_cast<unsigned long>(presenceExpires - serverTime) * 1000UL : 0UL;
  for (JsonObject command : response["commands"].as<JsonArray>()) {
    String id = command["id"].as<String>();
    String type = command["type"].as<String>();
    uint32_t incoming = command["version"] | 0;
    if (id == lastCommand) {
      if (type == "FACTORY_RESET") {
        String keyHash, claimHash;
        if (preparePanelFactoryReset(id, keyHash, claimHash)) {
          JsonObject result = ack(id, "applied");
          result["new_device_key_hash"] = keyHash;
          result["new_claim_token_hash"] = claimHash;
        } else ack(id, "failed", "factory_reset_unavailable");
      }
      else if (type == "START" && state != "charging") ack(id, "failed", "previous_session_requires_reconciliation");
      else if (type == "RESERVE" && state != "reserved") ack(id, "failed", "reservation_requires_reconciliation");
      else if (type == "SET_POWER") {
        // Reentrega do mesmo SET_POWER: confirma de novo com o valor instalado agora.
        if (state == "charging" && sessionId == command["session_id"].as<String>())
          ack(id, "applied")["applied_power_w"] = lroundf(chargePowerW);
        else ack(id, "failed", "no_active_session");
      }
      else ack(id, "applied");
      continue;
    }
    if (incoming <= version || incoming < current || parseTime(command["expires_at"]) <= serverTime) continue;
    const char* error = nullptr;
    String resetKeyHash, resetClaimHash;
    if (type == "START") {
      JsonObject session = response["authorized"]["session"].as<JsonObject>();
      if (connectorOwnershipKnown && !panelOwned) error = "point_unowned";
      else if (!connectorActive) error = "point_inactive";
      else if (session.isNull() || session["id"].as<String>() != command["session_id"].as<String>()) error = "unauthorized_session";
      else if (sessionId.length()) error = "previous_session_requires_reconciliation";
      else {
        sessionId = command["session_id"].as<String>();
        maxDurationMs = (session["max_duration_minutes"] | 60UL) * 60000UL;
        maxCost = session["max_cost"].isNull() ? -1 : session["max_cost"].as<float>();
        price = session["price_per_kwh"].as<float>();
        discount = session["discount_percent"] | 0.0f;
        sessionPricingKnown = true;
        resetSessionSoc();
        readStartSoc(session);
        readStartSoc(command["parameters"].as<JsonObjectConst>()); // parameters prevalecem.
        const float requestedPowerW = readStartPower(command["parameters"].as<JsonObjectConst>(), session);
        // Com charger_link a recarga é SEMPRE no carregador GoodWe do endereço: o START tenta o
        // carregador agora (mesmo que a última leitura tenha falhado) e só aceita confirmado.
        // Sem charger_link (API antiga): simulação interna da tela, como antes.
        sessionOnCharger = chargerLink.active();
        chargePowerW = sessionOnCharger ? chargerLinkLimitW(requestedPowerW) : requestedPowerW;
        overstayEnabled = command["parameters"]["overstay"].is<JsonObjectConst>();
        if (socStartPercent >= 0 && !socSource.length()) socSource = "simulated";
        if (socSource == "phone") phoneSocPercent = socStartPercent;
        reading.energyWh = 0; persistSessionSoc(); persist(); // Sessão salva antes de autorizar a bancada.
        // Carregador GoodWe: liga e confirma pela leitura antes de aceitar a sessão. Sem resposta
        // depois das tentativas → ACK failed charger_offline (a API encerra a sessão com esse
        // motivo); nada de relé interno/simulação. Se chegou a ligar, o Link pede 10060 = 1.
        const charger::Error linkError = sessionOnCharger
            ? chargerLink.start(lroundf(chargePowerW), millis(), nullptr) : charger::Error::None;
        if (linkError != charger::Error::None) {
          error = charger::errorCode(linkError);
          sessionOnCharger = false;
          sessionId = ""; sessionPricingKnown = false; overstayEnabled = false; chargePowerW = kBenchPowerW;
          resetSessionSoc(); persistSessionSoc(); persist();
        } else {
          sensors.start(); reading = sensors.read(true, 0, chargePowerW);
          if (sessionOnCharger) reading.powerW = chargerLink.measuredPowerW();
          reading.socPercent = currentSessionSoc(reading.energyWh);
          started = lastTick = millis(); state = "charging"; endReason = "";
        }
      }
    } else if (type == "RESERVE") {
      JsonObject reservation = response["authorized"]["reservation"].as<JsonObject>();
      if (connectorOwnershipKnown && !panelOwned) error = "point_unowned";
      else if (!connectorActive) error = "point_inactive";
      else if (reservation.isNull() || reservation["id"].as<String>() != command["reservation_id"].as<String>() || sessionId.length()) error = "unauthorized_reservation";
      else { state = "reserved"; reservationDeadline = parseTime(reservation["expires_at"]); }
    } else if (type == "STOP") {
      if (sessionId.length() && sessionId != command["session_id"].as<String>()) error = "session_mismatch";
      else {
        // Parada pedida pela API ao celular chegar a 100 %: reporta o motivo real,
        // porque o end_reason do ponto prevalece no encerramento da sessão.
        const char* reason = command["parameters"]["reason"].as<const char*>();
        const bool full = (reason && strcmp(reason, "battery_full") == 0) ||
            (socSource == "phone" && phoneSocPercent >= 100);
        const bool wasCharging = state == "charging";
        // Uma parada local já reportada (ex.: battery_full) mantém o motivo original.
        if (!(state == "stopped" && endReason.length())) stop(full ? "battery_full" : "requested");
        else if (sessionOnCharger && chargerLink.active()) chargerStopResult = chargerLink.stop(millis());
        // Sessão no carregador GoodWe: parar só tem ACK applied com 10060 = 1 e 10015 = 0
        // relidos. A sessão termina de qualquer forma (o sync reporta stopped); sem recarga
        // em andamento a parada do carregador é só um reforço e não falha o comando.
        if (wasCharging && sessionOnCharger && chargerStopResult != charger::Error::None)
          error = charger::errorCode(chargerStopResult);
      }
    } else if (type == "SET_POWER") {
      const float requested = jsonNumber(command["parameters"]["power_limit_w"], -1);
      if (state != "charging" || !sessionId.length() || sessionId != command["session_id"].as<String>()) error = "no_active_session";
      else if (!validPowerLimit(requested)) error = "invalid_power_limit";
      else {
        tick(); // Integra a potência antiga até o instante da troca.
        if (state != "charging") error = "no_active_session";
        else if (sessionOnCharger) {
          // Sessão no carregador GoodWe: 10029 (só se mudou) ou pausa por 10060 = 1, confirmado por leitura.
          const float limit = chargerLinkLimitW(requested);
          const charger::Error linkError = chargerLink.setPower(lroundf(limit), millis(), nullptr);
          if (linkError != charger::Error::None) error = charger::errorCode(linkError);
          else { chargePowerW = limit; reading.powerW = chargerLink.measuredPowerW(); }
        } else {
          chargePowerW = chargerLimitW(requested); // 0 pausa: continua charging, sem energia.
          reading.powerW = chargePowerW;
        }
      }
    } else if (type == "RELEASE") {
      if (state == "charging") error = "charging_requires_stop";
      else { state = "idle"; reading.connected = false; overstayEnabled = false; }
    } else if (type == "FACTORY_RESET") {
      if (state != "idle" || sessionId.length() || reading.connected || reading.powerW > 0 ||
          !response["authorized"]["reservation"].isNull() ||
          !response["authorized"]["session"].isNull()) error = "factory_reset_requires_idle";
      else if (!preparePanelFactoryReset(id, resetKeyHash, resetClaimHash)) error = "factory_reset_storage_failed";
    } else error = "unknown_command";
    JsonObject result = ack(id, error ? "failed" : "applied", error);
    if (!error && type == "FACTORY_RESET") {
      result["new_device_key_hash"] = resetKeyHash;
      result["new_claim_token_hash"] = resetClaimHash;
    }
    if (!error && type == "SET_POWER") result["applied_power_w"] = lroundf(chargePowerW);
    if (!error) { version = incoming; lastCommand = id; persist(); changed = true; }
  }
  version = max(version, current);
  if (state != "charging" && response["authorized"]["session"].isNull() && acknowledgements.size() == 0) {
    sessionId = ""; reading.energyWh = 0; endReason = ""; sessionPricingKnown = false; resetSessionSoc();
    if (response["authorized"]["reservation"].isNull()) state = "idle";
  }
  persist();
  return changed;
}
