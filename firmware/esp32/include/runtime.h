#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include "sensors.h"
// Versão única do firmware (sync, CG_STATUS e pacote).
#define CHARGEGRID_FIRMWARE_VERSION "0.7.0"
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

// ---- 0.7.0: campos aditivos (firmware/API anteriores continuam funcionando) ----
// Potência ao vivo (SET_POWER). A bancada declara o carregador simulado que controla.
constexpr int kChargerMinPowerW = 1400, kChargerMaxPowerW = 7200, kChargerStepW = 100;
// Limite que a bancada instala para um pedido em W: arredonda para baixo no passo,
// nunca acima do pedido nem do máximo; abaixo do piso (ou 0) pausa a recarga.
float chargerLimitW(float requestedW);
// authorized.session: potência aplicada confirmada pela API (kW, < 0 = não informada)
// e motivo curto já reduzido a Latin-1 (cabe nas fontes do painel), até 40 caracteres.
extern float sessionAppliedPowerKw;
extern String powerReasonShort;
// Texto UTF-8 só com caracteres das fontes do painel (U+0020-U+007E, U+00A0-U+00FF, U+2022).
String panelLatin1(const char* text, size_t maxChars);
// Corpo do sync sem boot_id/sequence. extensions=false gera o corpo 0.6 para uma API
// anterior (SyncInput recusa campos desconhecidos com 422).
void fillSyncBody(JsonDocument& body, bool extensions);
// Pagamento no painel (modo teste): URL do QR (vazia = sem QR) e último pagamento.
extern String kioskUrl, paymentStatus;
extern float paymentAmount;
extern bool paymentTest;
// Permanência: START com parameters.overstay mantém o carro conectado após parar.
extern bool overstayEnabled;
extern String overstayStatus;
extern long overstayGraceSeconds;
extern unsigned long overstayReceivedAt;
extern float overstayFeeDue, overstayMaxFee, overstayAmount;
extern long overstayIntervalMinutes;
// Toque em "Desconectar": só fora de recarga; limpa a conexão e força um sync imediato.
bool requestLocalDisconnect();
// Estado seguro após reboot (chamado no setup depois de ler o diário da sessão).
void applyBootSafety();
