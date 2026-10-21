// Cliente HTTP de produção + agenda pura, sem rede/hardware. Relógio avança inclusive no corpo HTTP.
#include <cassert>
#include <cstdio>
#include <vector>
#include "runtime.h"
#include "extra_chargers.h"
#include "HTTPClient.h"

unsigned long testMillis = 1000, nextSync = 0, lastContact = 1000;
String bootId = "host-test", sessionId, state = "idle";
uint32_t sequence = 0;
bool hasSynced = false;
int lastSyncHttpStatus = 0;
static std::vector<uint32_t> ticks;
static int services = 0, transitionAtService = 0;
static bool watchdogExpired = false;
static bool sendingAck = false;
static String pendingReset;
const char* deviceApiBaseUrl() { return "https://host-test.example"; }
const char* deviceAuthorizationKey() { return "host-test-key"; }
const char* deviceRootCa() { return "public-test-ca"; }
void persist() {}
void fillSyncBody(JsonDocument& body, bool) { body["acks"] = sendingAck ? 1 : 0; }
bool syncRejectedExtensions(const char*) { return false; }
void tickAllSessions() {
  ticks.push_back(testMillis);
  if (uint32_t(testMillis - lastContact) >= 45000) watchdogExpired = true;
}
void tick() { tickAllSessions(); } // Compila também o cliente antigo na prova de regressão.
void serviceChargerLinks() {
  ++services;
  if (services == transitionAtService) requestImmediateSync();
}
bool apply(JsonDocument& reply) { sendingAck = reply["changed"] | false; return sendingAck; }
String pendingPanelFactoryCommand() { return pendingReset; }
String pendingPanelFactoryKey() { return String(43, 'x'); }
bool finishPanelFactoryReset(const String&) { return true; }
namespace extra {
Slot slots[kMaxSlots];
bool syncable(const Slot& slot, unsigned long now) {
  return slot.used && (!slot.unsupported || syncschedule::due(now, slot.unsupportedUntil));
}
void fillBody(Slot& slot, JsonDocument& body) { body["charger_address"] = slot.address; }
bool apply(Slot& slot, JsonDocument&, unsigned long now) { slot.lastContact = now; return false; }
void markUnsupported(Slot& slot, unsigned long now) { slot.unsupported = true; slot.unsupportedUntil = now + kUnsupportedMs; }
bool busy() {
  for (const auto& slot : slots)
    if (syncable(slot, millis()) && (slot.state == "charging" || slot.syncNow || slot.acks.size())) return true;
  return false;
}
}
// O stub usa std::string, cuja operação equivalente existe no C++20.
#define startsWith starts_with
#ifndef API_SOURCE
#define API_SOURCE "../../firmware/esp32/src/api_client.cpp"
#endif
#include API_SOURCE
#undef startsWith

static String response(bool changed = false, unsigned interval = 1) {
  return String("{\"authorized\":{},\"commands\":[],\"factory_reset_confirmed\":\"\",\"changed\":") + (changed ? "true" : "false") +
      ",\"sync_interval_seconds\":" + std::to_string(interval) + "}";
}
static void enqueue(int code, unsigned header, unsigned body, const String& reply = response()) {
  fakehttp::replies.push_back({code, header, body, reply});
}
static void clearSlots() { for (auto& slot : extra::slots) slot = extra::Slot(); }
int main() {
  // Ordem usada pelo loop real: polling obrigatório, depois decisão sync com a hora atual.
  std::vector<char> order;
  int polls = 0, syncs = 0;
  uint32_t clock = 0, deadline = 0;
  for (int turn = 0; turn < 100; ++turn) {
    syncschedule::networkTurn([&] { order.push_back('t'); }, [&] { ++polls; clock += 400; }, [&] {
      if (syncschedule::due(clock, deadline)) { ++syncs; clock += 1500; deadline = clock; }
    });
  }
  assert(polls == 100 && syncs == 100 && order.size() == 300);
  assert(syncschedule::due(0x20, 0xfffffff0));
  assert(!syncschedule::due(0xfffffff0, 0x20));
  assert(syncschedule::afterBatch(0xfffffff0, 100, false) == 84);

  // Três filhos lentos excedem 1s: prazo final ainda futuro e safety/poll entre HTTPs.
  for (int i = 0; i < 3; ++i) { extra::slots[i].used = true; extra::slots[i].address = i + 2; }
  enqueue(200, 300, 100);
  for (int i = 0; i < 3; ++i) enqueue(200, 700, 300);
  const unsigned before = testMillis;
  syncDevice();
  if (testMillis != before + 3400) fprintf(stderr, "batch elapsed=%lu requests=%zu remaining=%zu services=%d\n",testMillis-before,fakehttp::payloads.size(),fakehttp::replies.size(),services);
  assert(testMillis == before + 3400);
  assert(nextSync == testMillis + 1000 && !syncschedule::due(testMillis, nextSync));
  assert(services == 4 && ticks.size() == 4);
  assert(ticks.back() == testMillis && extra::slots[2].lastContact == testMillis);
  for (auto timeout : WiFiClientSecure::handshakeTimeouts) assert(timeout == 3);

  // Transição durante o ÚLTIMO envio não pode ser perdida pelo agendamento do lote.
  clearSlots(); transitionAtService = services + 1;
  enqueue(200, 200, 50);
  syncDevice();
  assert(nextSync == testMillis);
  transitionAtService = 0;
  enqueue(200, 100, 0);
  syncDevice();
  assert(nextSync == testMillis + 1000); // Sem nova transição: não fica em loop imediato.

  // Comando aplicado pede ACK já; a resposta seguinte volta à cadência normal.
  enqueue(200, 100, 0, response(true)); syncDevice();
  assert(nextSync == testMillis && sendingAck);
  enqueue(200, 100, 0); syncDevice();
  assert(nextSync == testMillis + 1000);
  JsonDocument ackBody; deserializeJson(ackBody, fakehttp::payloads.back());
  assert(ackBody["acks"] == 1);

  // Raiz saudável, filho falhando: retém evento/ACK, mas não repete lote em busyloop.
  auto& child = extra::slots[0]; child.used = true; child.address = 2; child.syncNow = true;
  for (int code : {503, -1, 200}) {
    enqueue(200, 100, 0, response(false, 5));
    enqueue(code, 200, 0, "invalid-json");
    syncDevice();
    assert(child.syncNow && nextSync == uint32_t(testMillis + 1000));
    fakehttp::advance(1000);
  }
  enqueue(200, 100, 0, response(false, 5)); enqueue(409, 100, 0);
  syncDevice();
  assert(child.syncNow && child.unsupported && nextSync == uint32_t(testMillis + 5000));
  enqueue(200, 100, 0, response(false, 5)); syncDevice();
  assert(nextSync == uint32_t(testMillis + 5000)); // Pausa 10min do filho não apressa a raiz.
  clearSlots();

  // Falha longa inclui corpo/espera no vigia e agenda o backoff a partir da conclusão.
  watchdogExpired = false;
  enqueue(-1, 46000, 0); syncDevice();
  assert(watchdogExpired && nextSync == uint32_t(testMillis + 5000));
  const unsigned retry = nextSync;
  requestImmediateSync(); requestImmediateSync();
  assert(nextSync == retry); // Estado local não reinicia a espera de erro.
  fakehttp::advance(5000);
  enqueue(-1, 2000, 0); syncDevice();
  assert(nextSync == uint32_t(testMillis + 10000));
  fakehttp::advance(10000);
  enqueue(200, 200, 0, response(false, 5)); syncDevice();
  assert(nextSync == uint32_t(testMillis + 5000));
  requestImmediateSync(); assert(nextSync == testMillis); // Recuperou: transições voltam a ser imediatas.

  // Begin falho também respeita o backoff e não exige reiniciar a central.
  fakehttp::beginFailures = 1; syncDevice();
  assert(nextSync == uint32_t(testMillis + 5000));
  fakehttp::advance(5000);
  testMillis = 0xffffff00UL; lastContact = testMillis;
  enqueue(200, 400, 0); syncDevice();
  assert(testMillis == 144 && nextSync == 1144);

  pendingReset = "test-reset";
  enqueue(200, 10, 0, "{\"connector\":{\"owned\":false,\"active\":false}}");
  assert(probePanelFactoryIdentity("{}"));
  assert(WiFiClientSecure::handshakeTimeouts.size() == 2);
  for (auto timeout : WiFiClientSecure::handshakeTimeouts) assert(timeout == 3);
  puts("PASS: agenda real HTTP (lote lento, fairness, transição, ACK, backoff, vigia, wrap e TLS compartilhado/probe)");
}
