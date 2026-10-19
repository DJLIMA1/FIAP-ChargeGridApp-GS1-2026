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
extern String stationPresenceCode;
extern unsigned long presenceCodeReceivedAt, presenceCodeTtlMs;
extern String panelClaimToken;
extern bool panelOwned, connectorOwnershipKnown, connectorActive;
extern uint32_t version, sequence;
extern unsigned long lastContact, lastTick, started, nextSync, lastSaved, maxDurationMs;
extern float maxCost, price, discount;
// Potência simulada da sessão: min(7,2 kW nominal, max_power_kw do START). Sem o campo: nominal.
extern float chargePowerW;
constexpr float kBenchPowerW = 7200.0f;
// SoC do veículo vindo da API (START/sync). socStartPercent < 0: desconhecido.
// socSource "simulated": o ponto avança o SoC pela energia entregue e para em 100 %.
// socSource "phone": o app envia o nível real do celular; o ponto só exibe.
extern float socStartPercent, batteryKwh, phoneSocPercent;
extern String socSource;
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
bool preparePanelFactoryReset(const String& commandId, String& keyHash, String& claimHash);
bool finishPanelFactoryReset(const String& commandId);
bool probePanelFactoryIdentity(const String& payload);
String pendingPanelFactoryCommand();
String pendingPanelFactoryKey();
String isoTime();
void persist();
bool sessionSocKnown();
float currentSessionSoc(float energyWh);
void tick();
bool apply(JsonDocument& response);
void syncDevice();
// Parada física local: segura e independente da UI/rede. Nunca inicia carga.
void requestLocalSafeStop();
