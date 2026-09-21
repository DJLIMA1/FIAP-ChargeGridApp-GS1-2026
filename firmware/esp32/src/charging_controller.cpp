#include "runtime.h"
#include <time.h>
String isoTime() {
  time_t now = time(nullptr);
  struct tm utc;
  gmtime_r(&now, &utc);
  char buffer[25];
  strftime(buffer, sizeof(buffer), "%Y-%m-%dT%H:%M:%SZ", &utc);
  return String(buffer);
}
time_t parseTime(const char* value) {
  if (!value) return 0;
  struct tm utc{};
  if (!strptime(value, "%Y-%m-%dT%H:%M:%S", &utc)) return 0;
  return mktime(&utc); // TZ é UTC.
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
  reading.connected = false;
  endReason = reason;
  persist();
}
void requestLocalSafeStop() {
  if (state == "charging") {
    stop("requested");
    nextSync = millis();
  }
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
    // O relógio local limita a energia, mesmo durante falha HTTP.
    unsigned long overdueContact = now - lastContact > 45000 ? now - lastContact - 45000 : 0;
    unsigned long overdueDuration = now - started > maxDurationMs ? now - started - maxDurationMs : 0;
    unsigned long overdue = max(overdueContact, overdueDuration);
    unsigned long permittedElapsed = elapsed > overdue ? elapsed - overdue : 0;
    const float effectivePrice = price * (1 - discount / 100);
    if (maxCost >= 0 && effectivePrice > 0) {
      const float remainingWh = max(0.0f, maxCost * 1000 / effectivePrice - reading.energyWh);
      const unsigned long costElapsed = (unsigned long)(remainingWh * 3600000 / 7200);
      permittedElapsed = min(permittedElapsed, costElapsed);
    }
    reading = sensors.read(true, permittedElapsed);
    if (now - lastSaved >= 30000) { persist(); lastSaved = now; }
    if (now - lastContact >= 45000) stop("communication_lost");
    else if (now - started >= maxDurationMs) stop("duration_limit");
    else if (maxCost >= 0 && (reading.energyWh / 1000 * effectivePrice >= maxCost || permittedElapsed < elapsed - min(elapsed, overdue))) stop("cost_limit");
  } else if (state == "reserved" && reservationDeadline && time(nullptr) >= reservationDeadline) {
    state = "idle";
  }
}
bool apply(JsonDocument& response) {
  acknowledgements.to<JsonArray>();
  connectorPublicCode = response["connector"]["public_code"] | "--";
  JsonObjectConst connector = response["connector"].as<JsonObjectConst>();
  if (connector["owned"].is<bool>()) {
    connectorOwnershipKnown = true;
    if (connector["owned"].as<bool>()) confirmPanelOwnership();
  }
  if (connector["active"].is<bool>()) connectorActive = connector["active"].as<bool>();
  JsonObject authorization = response["authorized"].as<JsonObject>();
  reservationDeadline = parseTime(authorization["reservation"]["expires_at"]);
  JsonObject authorizedSession = authorization["session"].as<JsonObject>();
  if (!authorizedSession.isNull() && authorizedSession["id"].as<String>() == sessionId) {
    price = authorizedSession["price_per_kwh"].as<float>();
    discount = authorizedSession["discount_percent"] | 0.0f;
    sessionPricingKnown = true;
  }
  if (state == "stopped" && ((!authorization["session"].isNull() && authorization["session"]["id"].as<String>() != sessionId) || (!authorization["reservation"].isNull() && authorization["session"].isNull()))) {
    sessionId = ""; reading.energyWh = 0; endReason = ""; sessionPricingKnown = false;
  }
  bool changed = false;
  uint32_t current = response["control_version"] | 0;
  time_t serverTime = parseTime(response["server_time"]);
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
        reading.energyWh = 0; persist(); // Sessão salva antes de autorizar a bancada.
        sensors.start(); reading = sensors.read(true, 0);
        started = lastTick = millis(); state = "charging"; endReason = "";
      }
    } else if (type == "RESERVE") {
      JsonObject reservation = response["authorized"]["reservation"].as<JsonObject>();
      if (connectorOwnershipKnown && !panelOwned) error = "point_unowned";
      else if (!connectorActive) error = "point_inactive";
      else if (reservation.isNull() || reservation["id"].as<String>() != command["reservation_id"].as<String>() || sessionId.length()) error = "unauthorized_reservation";
      else { state = "reserved"; reservationDeadline = parseTime(reservation["expires_at"]); }
    } else if (type == "STOP") {
      if (sessionId.length() && sessionId != command["session_id"].as<String>()) error = "session_mismatch";
      else stop("requested");
    } else if (type == "RELEASE") {
      if (state == "charging") error = "charging_requires_stop";
      else { state = "idle"; reading.connected = false; }
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
    if (!error) { version = incoming; lastCommand = id; persist(); changed = true; }
  }
  version = max(version, current);
  if (state != "charging" && response["authorized"]["session"].isNull() && acknowledgements.size() == 0) {
    sessionId = ""; reading.energyWh = 0; endReason = ""; sessionPricingKnown = false;
    if (response["authorized"]["reservation"].isNull()) state = "idle";
  }
  persist();
  return changed;
}
