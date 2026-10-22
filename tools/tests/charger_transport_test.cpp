// Transporte ESP32 real com sockets/mDNS falsos; ADUs atendidos pelo simulador real.
#include <cassert>
#include <cstdio>
#include "WiFi.h"
#include "ESPmDNS.h"
#include "charger_modbus_esp32.h"
unsigned long testMillis=1000;
#ifndef TRANSPORT_SOURCE
#define TRANSPORT_SOURCE "../../firmware/esp32/src/charger_modbus_esp32.cpp"
#endif
#include TRANSPORT_SOURCE

int main() {
  const IPAddress oldIp(192,168,0,21),newIp(192,168,0,22);
  fakenet::peers.reserve(2);fakenet::peers.emplace_back(oldIp);fakenet::peers.emplace_back(newIp);
  auto& old=fakenet::peers[0];auto& fresh=fakenet::peers[1];
  charger::LinkConfig config;
  assert(charger::makeConfig("goodwe_hca_g2","modbus_tcp",1,nullptr,502,config));
  auto& client=espChargerClient(0);
  uint16_t live[3];uint8_t exception=0;
  assert(client.readHolding(config,hca::kChargingPower,3,live,&exception));
  assert(MDNS.queries==1 && fakenet::connections.back()==oldIp);

  // IP antigo aceita TCP mas parou de responder Modbus: redescobre novo IP sem reset.
  old.reply=false;MDNS.result=newIp;delay(5000);
  assert(!client.readHolding(config,hca::kChargingPower,3,live,&exception));
  delay(1000);
  assert(client.readHolding(config,hca::kChargingPower,3,live,&exception));
  assert(MDNS.queries==2 && fakenet::connections.back()==newIp);

  // Escrita sem envio também invalida resolução. Não exige reboot/START urgente.
  fresh.writeFail=true;MDNS.result=oldIp;old.reply=true;delay(5000);
  assert(!client.writeSingle(config,hca::kStartStop,hca::kStopValue,&exception));
  fresh.writeFail=false;
  assert(client.readHolding(config,hca::kChargingPower,3,live,&exception));
  assert(fakenet::connections.back()==oldIp && MDNS.queries==3);

  // mDNS indisponível: conserva último IP bom e respeita recuo de 5s entre consultas.
  old.reply=false;delay(5000);
  assert(!client.readHolding(config,hca::kChargingPower,3,live,&exception));
  old.reply=true;MDNS.available=false;
  const int beforeQueries=MDNS.queries;
  assert(client.readHolding(config,hca::kChargingPower,3,live,&exception));
  assert(MDNS.queries==beforeQueries+1 && fakenet::connections.back()==oldIp);

  // IP fixo tem precedência, inclusive depois da falha; não redireciona para outro aparelho.
  espChargerSetFixedIp(oldIp.toString());MDNS.available=true;MDNS.result=newIp;
  const int fixedQueries=MDNS.queries;
  assert(client.readHolding(config,hca::kChargingPower,3,live,&exception));
  old.reply=false;
  assert(!client.readHolding(config,hca::kChargingPower,3,live,&exception));
  assert(!client.readHolding(config,hca::kChargingPower,3,live,&exception));
  old.reply=true;
  assert(client.readHolding(config,hca::kChargingPower,3,live,&exception));
  assert(MDNS.queries==fixedQueries && fakenet::connections.back()==oldIp);

  // Retomada de STOP pendente com transporte real preserva a confirmação da 69b77c9.
  espChargerSetFixedIp("");MDNS.result=oldIp;
  charger::Link link;link.setClient(&client);link.configure(config);
  assert(link.start(2000,testMillis,nullptr)==charger::Error::None && old.charger.relayClosed());
  old.reply=false;
  assert(link.stop(testMillis)==charger::Error::Offline && link.pendingStop());
  MDNS.result=newIp;delay(5000);
  link.poll(testMillis);
  assert(!link.pendingStop() && !fresh.charger.relayClosed());
  assert(!fresh.runWrites.empty());
  for (auto run:fresh.runWrites) assert(run==hca::kStopValue);
  puts("PASS: transporte ESP32 real (timeout/write → novo IP sem reboot, lastGood, fixedIP, STOP pendente confirmado)");
}
