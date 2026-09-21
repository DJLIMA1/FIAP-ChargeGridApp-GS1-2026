#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include "sensors.h"
extern Preferences store;
extern SimulatedSensors sensors;
extern Reading reading;
extern String bootId, sessionId, lastCommand, state, endReason;
extern String connectorPublicCode;
extern String panelClaimToken;
extern bool panelOwned, connectorOwnershipKnown, connectorActive;
extern uint32_t version, sequence;
extern unsigned long lastContact, lastTick, started, nextSync, lastSaved, maxDurationMs;
extern float maxCost, price, discount;
extern time_t reservationDeadline;
extern JsonDocument acknowledgements;
extern bool hasSynced;
extern bool sessionPricingKnown;
extern bool panelIntegrationEnabled;
extern bool panelIdentityConfigured;
extern bool panelNetworkConfigured;
extern int lastSyncHttpStatus;
const char* deviceApiBaseUrl();
const char* deviceAuthorizationKey();
const char* deviceRootCa();
bool savePanelConnection(const char* ssid, const char* password, const char* deviceKey);
bool clearPanelConnection();
void confirmPanelOwnership();
String isoTime();
void persist();
void tick();
bool apply(JsonDocument& response);
void syncDevice();
// Parada física local: segura e independente da UI/rede. Nunca inicia carga.
void requestLocalSafeStop();
