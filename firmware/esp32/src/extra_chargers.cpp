#include "extra_chargers.h"
#include <math.h>
#include <stdio.h>
#include <string.h>
#include "runtime.h"

namespace extra {

Slot slots[kMaxSlots];
static charger::ModbusClient* clients[kMaxSlots] = {};

void setClient(uint8_t index, charger::ModbusClient* client) {
  if (index >= kMaxSlots) return;
  clients[index] = client;
  slots[index].link.setClient(client);
}

static float number(JsonVariantConst value, float fallback) {
  if (value.is<const char*>()) {
    const char* text = value.as<const char*>();
    char* end = nullptr;
    const float parsed = strtof(text, &end);
    return end != text ? parsed : fallback;
  }
  return value.is<float>() ? value.as<float>() : fallback;
}

static bool linkConfig(JsonObjectConst link, charger::LinkConfig& out) {
  if (link.isNull()) return false;
  return charger::makeConfig(link["model"].as<const char*>(), link["transport"].as<const char*>(),
                             link["address"].is<long>() ? link["address"].as<long>() : 0L,
                             link["host"].as<const char*>(),
                             link["port"].is<long>() ? link["port"].as<long>() : (long)hca::kDefaultPort, out);
}

static void key(char* out, size_t size, uint8_t address, char kind) { snprintf(out, size, "x%u%c", address, kind); }

static void persistIndex() {
  String addresses;
  for (const Slot& item : slots)
    if (item.used) {
      char part[6];
      snprintf(part, sizeof(part), "%s%u", addresses.length() ? "," : "", item.address);
      addresses += part;
    }
  store.putString("xaddrs", addresses);
}

// Diário da sessão do carregador adicional na NVS ("x<endereço><s|e|v|c>") e a lista "xaddrs".
void persist(Slot& slot) {
  if (slot.used) {
    char name[8];
    key(name, sizeof(name), slot.address, 's'); store.putString(name, slot.sessionId);
    key(name, sizeof(name), slot.address, 'e'); store.putFloat(name, slot.energyWh);
    key(name, sizeof(name), slot.address, 'v'); store.putUInt(name, slot.version);
    key(name, sizeof(name), slot.address, 'c'); store.putString(name, slot.lastCommand);
  }
  persistIndex();
}

static void clearSession(Slot& slot) {
  slot.sessionId = ""; slot.energyWh = 0; slot.endReason = ""; slot.limitW = 0;
}

static void release(Slot& slot) {
  slot.link.configure(charger::LinkConfig{});
  const uint8_t address = slot.address;
  slot.used = false; slot.address = 0; slot.version = 0; slot.lastCommand = ""; slot.state = "idle";
  slot.active = true; slot.connected = false; slot.unsupported = false; slot.syncNow = false;
  clearSession(slot);
  slot.acks.clear();
  char name[8];
  key(name, sizeof(name), address, 's'); store.putString(name, "");
}

static Slot* find(uint8_t address) {
  for (Slot& slot : slots)
    if (slot.used && slot.address == address) return &slot;
  return nullptr;
}

static Slot* claim(uint8_t address, unsigned long now) {
  Slot* slot = find(address);
  if (slot) return slot;
  for (uint8_t i = 0; i < kMaxSlots; ++i)
    if (!slots[i].used) {
      slot = &slots[i];
      slot->used = true; slot->address = address; slot->state = "idle"; slot->lastContact = now;
      slot->lastTick = now; slot->acks.to<JsonArray>();
      slot->link.setClient(clients[i]);
      return slot;
    }
  return nullptr;  // mais carregadores que slots: os excedentes ficam sem a tela (offline na API)
}

void configure(JsonArrayConst chargers, unsigned long now) {
  bool listed[kMaxSlots] = {};
  for (JsonObjectConst item : chargers) {
    charger::LinkConfig config;
    const long address = item["address"].is<long>() ? item["address"].as<long>() : 0L;
    if (!linkConfig(item["charger_link"].as<JsonObjectConst>(), config) || config.address != address) continue;
    Slot* slot = claim(static_cast<uint8_t>(address), now);
    if (!slot) continue;
    listed[slot - slots] = true;
    // A sessão pode já ter sido conciliada pela API enquanto o STOP físico ainda falha.
    // Preserve o endpoint antigo até confirmar a parada nele.
    if (slot->state != "charging" && !slot->link.pendingStop()) slot->link.configure(config);
  }
  for (uint8_t i = 0; i < kMaxSlots; ++i)
    if (slots[i].used && !listed[i] && slots[i].state != "charging" && !slots[i].sessionId.length() &&
        !slots[i].link.pendingStop()) {
      release(slots[i]);
      persistIndex();
    }
}

void restore(uint8_t address, const char* sessionId, float energyWh, uint32_t version, const char* lastCommand,
             unsigned long now) {
  if (!address || address > hca::kMaxAddress) return;
  Slot* slot = claim(address, now);
  if (!slot) return;
  slot->version = version;
  slot->lastCommand = lastCommand ? lastCommand : "";
  slot->sessionId = sessionId ? sessionId : "";
  slot->energyWh = slot->sessionId.length() ? energyWh : 0;
  // Saída desenergizada; a sessão anterior só é relatada (a API encerra/concilia).
  if (slot->sessionId.length()) { slot->state = "stopped"; slot->endReason = "device_reboot"; }
}

static JsonObject ack(Slot& slot, const String& id, const char* status, const char* error = nullptr) {
  JsonObject item = slot.acks.as<JsonArray>().add<JsonObject>();
  item["command_id"] = id;
  item["status"] = status;
  item["error"] = error;
  return item;
}

charger::Error stop(Slot& slot, const char* reason) {
  slot.state = "stopped";
  slot.connected = false;  // sem permanência nos carregadores adicionais
  slot.endReason = reason;
  persist(slot);
  return slot.link.active() ? slot.link.stop(millis()) : charger::Error::None;
}

void tick(Slot& slot, unsigned long now) {
  const unsigned long elapsed = now - slot.lastTick;
  slot.lastTick = now;
  if (slot.state == "charging") {
    const float powerW = (float)slot.link.measuredPowerW();  // 10015 (SIMULADO no simulador)
    const unsigned long overdueContact = now - slot.lastContact > kContactLossMs ? now - slot.lastContact - kContactLossMs : 0;
    const unsigned long overdueDuration = now - slot.started > slot.maxDurationMs ? now - slot.started - slot.maxDurationMs : 0;
    const unsigned long overdue = max(overdueContact, overdueDuration);
    unsigned long permitted = elapsed > overdue ? elapsed - overdue : 0;
    const float effectivePrice = slot.price * (1 - slot.discount / 100);
    bool costCapped = false;
    if (slot.maxCost >= 0 && effectivePrice > 0 && powerW > 0) {
      const float remainingWh = max(0.0f, slot.maxCost * 1000 / effectivePrice - slot.energyWh);
      const unsigned long costElapsed = (unsigned long)(remainingWh * 3600000 / powerW);
      if (costElapsed < permitted) { permitted = costElapsed; costCapped = true; }
    }
    slot.energyWh += powerW * permitted / 3600000.0f;
    if (now - slot.lastSaved >= 30000) { persist(slot); slot.lastSaved = now; }
    if (now - slot.lastContact >= kContactLossMs) stop(slot, "communication_lost");
    else if (now - slot.started >= slot.maxDurationMs) stop(slot, "duration_limit");
    else if (slot.maxCost >= 0 && (slot.energyWh / 1000 * effectivePrice >= slot.maxCost || costCapped)) stop(slot, "cost_limit");
  } else if (slot.state == "reserved" && slot.reservationDeadline && time(nullptr) >= slot.reservationDeadline) {
    slot.state = "idle";
  }
}

void service(unsigned long now) {
  for (Slot& slot : slots) {
    if (!slot.used) continue;
    now = millis(); // Cada slot pode esperar operações bloqueantes dos anteriores.
    tick(slot, now);
    if (!slot.link.active()) continue;
    const bool wasOnline = slot.link.online();
    slot.link.poll(now);
    if (wasOnline != slot.link.online()) { slot.syncNow = true; requestImmediateSync(); }
    now = millis();
    if (slot.state == "charging" && slot.link.faulted(now, true)) {
      tick(slot, now);
      if (slot.state == "charging") { stop(slot, "device_fault"); slot.syncNow = true; requestImmediateSync(); }
    }
  }
}

void fillBody(Slot& slot, JsonDocument& body) {
  const bool charging = slot.state == "charging";
  body["firmware_version"] = CHARGEGRID_FIRMWARE_VERSION;
  if (slot.sessionId.length()) body["session_id"] = slot.sessionId; else body["session_id"] = nullptr;
  body["physical_state"] = slot.state; body["connected"] = charging || slot.connected;
  body["soc_percent"] = nullptr;  // SoC derivado pela API (sem bateria simulada nos adicionais)
  body["energy_wh"] = slot.energyWh;
  body["power_w"] = charging ? slot.link.measuredPowerW() : 0L;
  body["source"] = "simulated"; body["captured_at"] = isoTime();
  if (slot.endReason.length()) body["end_reason"] = slot.endReason; else body["end_reason"] = nullptr;
  body["acks"] = slot.acks.as<JsonArray>();
  JsonArray capabilities = body["capabilities"].to<JsonArray>();
  capabilities.add("set_power_v1"); capabilities.add("multi_charger_v1");
  body["applied_power_w"] = charging ? lroundf(slot.limitW) : 0L;
  JsonObject info = body["charger"].to<JsonObject>();
  if (slot.link.online() || charging) {
    info["model"] = "goodwe_hca_g2"; info["variant"] = hca::kGw7k.name; info["transport"] = "modbus_tcp";
    info["min_power_w"] = hca::powerWForRegister(hca::kGw7k.minTenths);
    info["max_power_w"] = hca::powerWForRegister(hca::kGw7k.maxTenths);
    info["step_w"] = 100; info["phases"] = hca::kGw7k.phases;
  } else {
    info["model"] = "esp32_bench"; info["transport"] = "simulated";
    info["min_power_w"] = kChargerMinPowerW; info["max_power_w"] = kChargerMaxPowerW;
    info["step_w"] = kChargerStepW; info["phases"] = 1;
  }
  info["address"] = slot.address;
  info["link"] = slot.link.online() ? "online" : "offline";
  body["charger_address"] = slot.address;
}

// Potência inicial: power_limit_w (0 = pausado) ou max_power_kw; sem campo, o máximo do carregador.
static float startPower(JsonObjectConst parameters, JsonObjectConst session) {
  if (!parameters["power_limit_w"].isNull()) {
    const float limit = number(parameters["power_limit_w"], -1);
    if (limit >= 0 && limit <= 1000000) return chargerLinkLimitW(limit);
  }
  float cap = number(parameters["max_power_kw"], -1);
  if (!(cap >= 0.1f && cap <= 1000)) cap = number(session["max_power_kw"], -1);
  return chargerLinkLimitW(cap >= 0.1f && cap <= 1000 ? cap * 1000.0f : 7000.0f);
}

bool apply(Slot& slot, JsonDocument& response, unsigned long now) {
  slot.acks.to<JsonArray>();
  slot.lastContact = now;
  JsonObjectConst connector = response["connector"].as<JsonObjectConst>();
  if (connector["active"].is<bool>()) slot.active = connector["active"].as<bool>();
  charger::LinkConfig config;
  if (slot.state != "charging" && !slot.link.pendingStop() &&
      linkConfig(connector["charger_link"].as<JsonObjectConst>(), config) &&
      config.address == slot.address)
    slot.link.configure(config);
  JsonObjectConst authorization = response["authorized"].as<JsonObjectConst>();
  slot.reservationDeadline = parseTime(authorization["reservation"]["expires_at"]);
  JsonObjectConst session = authorization["session"].as<JsonObjectConst>();
  if (!session.isNull() && session["id"].as<String>() == slot.sessionId) {
    slot.price = number(session["price_per_kwh"], slot.price);
    slot.discount = number(session["discount_percent"], 0);
  }
  if (slot.state == "stopped" && ((!session.isNull() && session["id"].as<String>() != slot.sessionId) ||
                                  (!authorization["reservation"].isNull() && session.isNull())))
    clearSession(slot);
  bool changed = false;
  const uint32_t current = response["control_version"] | 0;
  const time_t serverTime = parseTime(response["server_time"]);
  for (JsonObjectConst command : response["commands"].as<JsonArrayConst>()) {
    const String id = command["id"].as<String>();
    const String type = command["type"].as<String>();
    const uint32_t incoming = command["version"] | 0;
    if (id == slot.lastCommand) {
      if (type == "START" && slot.state != "charging") ack(slot, id, "failed", "previous_session_requires_reconciliation");
      else if (type == "RESERVE" && slot.state != "reserved") ack(slot, id, "failed", "reservation_requires_reconciliation");
      else if (type == "SET_POWER") {
        if (slot.state == "charging" && slot.sessionId == command["session_id"].as<String>())
          ack(slot, id, "applied")["applied_power_w"] = lroundf(slot.limitW);
        else ack(slot, id, "failed", "no_active_session");
      } else ack(slot, id, "applied");
      continue;
    }
    if (incoming <= slot.version || incoming < current || parseTime(command["expires_at"]) <= serverTime) continue;
    const char* error = nullptr;
    if (type == "START") {
      if (!slot.active) error = "point_inactive";
      else if (session.isNull() || session["id"].as<String>() != command["session_id"].as<String>()) error = "unauthorized_session";
      else if (slot.sessionId.length() || slot.link.pendingStop()) error = "previous_session_requires_reconciliation";
      else if (!slot.link.active()) error = charger::errorCode(charger::Error::NoLink);
      else {
        const float limit = startPower(command["parameters"].as<JsonObjectConst>(), session);
        // Mesmo START estrito do ponto da tela: só confirmado pela releitura do carregador.
        const charger::Error linkError = slot.link.start(lroundf(limit), now, nullptr);
        if (linkError != charger::Error::None) error = charger::errorCode(linkError);
        else {
          slot.sessionId = command["session_id"].as<String>();
          slot.maxDurationMs = (session["max_duration_minutes"] | 60UL) * 60000UL;
          slot.maxCost = session["max_cost"].isNull() ? -1 : number(session["max_cost"], -1);
          slot.price = number(session["price_per_kwh"], 0);
          slot.discount = number(session["discount_percent"], 0);
          slot.limitW = limit; slot.energyWh = 0; slot.endReason = "";
          slot.started = slot.lastTick = slot.lastSaved = millis(); // Só após confirmar START.
          slot.state = "charging"; slot.connected = true;
        }
      }
    } else if (type == "RESERVE") {
      JsonObjectConst reservation = authorization["reservation"].as<JsonObjectConst>();
      if (!slot.active) error = "point_inactive";
      else if (reservation.isNull() || reservation["id"].as<String>() != command["reservation_id"].as<String>() ||
               slot.sessionId.length()) error = "unauthorized_reservation";
      else { slot.state = "reserved"; slot.reservationDeadline = parseTime(reservation["expires_at"]); }
    } else if (type == "STOP") {
      if (slot.sessionId.length() && slot.sessionId != command["session_id"].as<String>()) error = "session_mismatch";
      else {
        const char* reason = command["parameters"]["reason"].as<const char*>();
        const bool wasCharging = slot.state == "charging";
        if (wasCharging) tick(slot, now);  // energia até o instante da parada
        charger::Error result = charger::Error::None;
        if (!(slot.state == "stopped" && slot.endReason.length()))
          result = stop(slot, reason && strcmp(reason, "battery_full") == 0 ? "battery_full" : "requested");
        else if (slot.link.active() && slot.link.pendingStop()) result = slot.link.stop(now);
        if (wasCharging && result != charger::Error::None) error = charger::errorCode(result);
      }
    } else if (type == "SET_POWER") {
      const float requested = number(command["parameters"]["power_limit_w"], -1);
      if (slot.state != "charging" || slot.sessionId != command["session_id"].as<String>()) error = "no_active_session";
      else if (!(requested >= 0 && requested <= 1000000)) error = "invalid_power_limit";
      else {
        tick(slot, now);
        if (slot.state != "charging") error = "no_active_session";
        else {
          const float limit = chargerLinkLimitW(requested);
          const charger::Error linkError = slot.link.setPower(lroundf(limit), now, nullptr);
          if (linkError != charger::Error::None) error = charger::errorCode(linkError);
          else slot.limitW = limit;
        }
      }
    } else if (type == "RELEASE") {
      if (slot.state == "charging") error = "charging_requires_stop";
      else { slot.state = "idle"; slot.connected = false; }
    } else error = "unknown_command";  // FACTORY_RESET etc. são da tela, nunca de um carregador
    JsonObject result = ack(slot, id, error ? "failed" : "applied", error);
    if (!error && type == "SET_POWER") result["applied_power_w"] = lroundf(slot.limitW);
    if (!error) { slot.version = incoming; slot.lastCommand = id; changed = true; }
  }
  slot.version = max(slot.version, current);
  if (slot.state != "charging" && session.isNull() && slot.acks.size() == 0) {
    clearSession(slot);
    if (authorization["reservation"].isNull()) slot.state = "idle";
  }
  persist(slot);
  return changed;
}

void markUnsupported(Slot& slot, unsigned long now) {
  slot.unsupported = true;
  slot.unsupportedUntil = now + kUnsupportedMs;
}

bool syncable(const Slot& slot, unsigned long now) {
  return slot.used && (!slot.unsupported || (long)(now - slot.unsupportedUntil) >= 0);
}

bool busy() {
  for (const Slot& slot : slots)
    if (syncable(slot, millis()) && (slot.state == "charging" || slot.state == "reserved" || slot.acks.size() || slot.syncNow))
      return true;
  return false;
}

}  // namespace extra
