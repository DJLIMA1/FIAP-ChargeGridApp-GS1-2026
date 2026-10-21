// Testes de host do carregador GoodWe HCA G2 SIMULADO (firmware/goodwe-hca-sim/lib/hca_sim_core)
// e do Modbus TCP mínimo compartilhado (firmware/shared/hca_g2). Sem Arduino, com sanitizers.
#include <cassert>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include "hca_sim_core.h"
#include "modbus_tcp.h"

namespace {

uint16_t transaction = 0;

// Faz um pedido Modbus TCP de verdade (bytes) contra o carregador.
struct Wire {
  hcasim::Charger& device;
  uint8_t unit = 1;
  uint8_t lastException = 0;
  bool read(uint16_t address, uint16_t count, uint16_t* out) {
    uint8_t request[mbtcp::kMaxAdu], response[mbtcp::kMaxAdu];
    const size_t size = mbtcp::buildReadHolding(++transaction, unit, address, count, request);
    const size_t length = mbtcp::serve(request, size, device.address(), device, response);
    lastException = 0;
    return mbtcp::parseResponse(request, response, length, out, &lastException) == mbtcp::Status::Ok;
  }
  bool write(uint16_t address, uint16_t value) {
    uint8_t request[mbtcp::kMaxAdu], response[mbtcp::kMaxAdu];
    const size_t size = mbtcp::buildWriteSingle(++transaction, unit, address, value, request);
    const size_t length = mbtcp::serve(request, size, device.address(), device, response);
    assert(length == size || length == mbtcp::kMbapSize + 2);
    lastException = 0;
    return mbtcp::parseResponse(request, response, length, nullptr, &lastException) == mbtcp::Status::Ok;
  }
  bool writeMany(uint16_t address, uint16_t count, const uint16_t* values) {
    uint8_t request[mbtcp::kMaxAdu], response[mbtcp::kMaxAdu];
    const size_t size = mbtcp::buildWriteMultiple(++transaction, unit, address, count, values, request);
    const size_t length = mbtcp::serve(request, size, device.address(), device, response);
    lastException = 0;
    return mbtcp::parseResponse(request, response, length, nullptr, &lastException) == mbtcp::Status::Ok;
  }
  uint16_t get(uint16_t address) {
    uint16_t value = 0xFFFF;
    assert(read(address, 1, &value));
    return value;
  }
};

void testBootSafe() {
  hcasim::Charger device;
  device.boot(1000, 20, 1);
  Wire wire{device};
  assert(!device.relayClosed());
  assert(wire.get(hca::kStartStop) == hca::kStopValue);
  assert(wire.get(hca::kMaxChargingPower) == 20);  // 10029 salvo (flash) volta no boot
  assert(wire.get(hca::kChargeMode) == 1);
  assert(wire.get(hca::kStatus) == hca::kStatusPlugged);
  assert(wire.get(hca::kChargingPower) == 0);
  assert(wire.get(hca::kPowerSpec) == 0 && wire.get(hca::kChargerType) == 1);  // 7 kW, monofásico
  assert(wire.get(hca::kExtVersion) == 1 && wire.get(hca::kExtSimulated) == 1 && wire.get(hca::kExtAddress) == 1);
  // Liga, depois "reset": volta aberto, 10060 = 1, energia zerada, nunca retoma sozinho.
  assert(wire.write(hca::kStartStop, hca::kStartValue) && device.relayClosed());
  device.tick(1000 + 9000);  // 9 s a 2,0 kW = 5 Wh (dentro do watchdog)
  assert(device.energyWh() == 5);
  device.boot(10000, device.reg(hca::kMaxChargingPower), device.reg(hca::kChargeMode));
  assert(!device.relayClosed() && device.reg(hca::kStartStop) == hca::kStopValue && device.energyWh() == 0);
  assert(!device.watchdogArmed());
  // Valor salvo inválido (acima do máximo) é limitado ao máximo do modelo.
  device.boot(0, 999, 9);
  assert(device.reg(hca::kMaxChargingPower) == hca::kGw7k.maxTenths && device.reg(hca::kChargeMode) == 0);
  puts("PASS: boot/reset seguro (relé aberto, 10060 = 1, 10029/10032 persistidos, energia zerada)");
}

void testRegistersAndRange() {
  hcasim::Charger device;
  device.boot(0, 70, 1);
  Wire wire{device};
  assert(wire.write(hca::kMaxChargingPower, 20) && wire.get(hca::kMaxChargingPower) == 20);
  assert(device.takePersistentChange() && !device.takePersistentChange());
  assert(wire.write(hca::kMaxChargingPower, 20) && !device.takePersistentChange());  // mesmo valor: sem flash
  assert(wire.write(hca::kMaxChargingPower, 70));  // máximo do GW7K
  assert(!wire.write(hca::kMaxChargingPower, 71) && wire.lastException == mbtcp::kIllegalValue);
  assert(wire.get(hca::kMaxChargingPower) == 70);
  assert(!wire.write(hca::kStartStop, 0) && wire.lastException == mbtcp::kIllegalValue);
  assert(!wire.write(hca::kStartStop, 3) && wire.lastException == mbtcp::kIllegalValue);
  assert(!wire.write(hca::kChargeMode, 3) && wire.lastException == mbtcp::kIllegalValue);
  assert(wire.write(hca::kChargeMode, 0) && wire.get(hca::kChargeMode) == 0);
  // Só leitura / fora do mapa: endereço ilegal.
  for (uint16_t address : {hca::kChargingPower, hca::kStatus, hca::kPowerSpec, hca::kChargerType, (uint16_t)10061,
                           (uint16_t)9999, hca::kExtEnergyLow})
    assert(!wire.write(address, 1) && wire.lastException == mbtcp::kIllegalAddress);
  // 10024/10025/10026 existem (graváveis no mapa), sem efeito no simulado.
  assert(wire.write(hca::kHouseBreaker, 32) && wire.get(hca::kHouseBreaker) == 32);
  // Leitura em bloco 10015..10060 (46 registradores) e da extensão.
  uint16_t block[46];
  assert(wire.read(hca::kChargingPower, 46, block));
  assert(block[hca::kMaxChargingPower - hca::kChargingPower] == 70 && block[hca::kStartStop - hca::kChargingPower] == 1);
  uint16_t ext[7];
  assert(wire.read(hca::kExtFirst, 7, ext) && ext[0] == 1 && ext[6] == 1);
  assert(!wire.read(10055, 10, block) && wire.lastException == mbtcp::kIllegalAddress);  // cruza 10060
  assert(!wire.read(18999, 2, block) && wire.lastException == mbtcp::kIllegalAddress);
  assert(!wire.read(hca::kExtLast, 2, block) && wire.lastException == mbtcp::kIllegalAddress);
  // FC16 é tudo ou nada.
  const uint16_t bad[] = {30, 0, 0, 9};  // 10029..10032, 10032 = 9 inválido
  assert(!wire.writeMany(hca::kMaxChargingPower, 4, bad) && wire.lastException == mbtcp::kIllegalValue);
  assert(wire.get(hca::kMaxChargingPower) == 70);
  const uint16_t good[] = {30, 0, 0, 0};
  assert(wire.writeMany(hca::kMaxChargingPower, 4, good) && wire.get(hca::kMaxChargingPower) == 30);
  const uint16_t across[] = {2, 0};  // 10060..10061: 10061 não existe
  assert(!wire.writeMany(hca::kStartStop, 2, across) && wire.lastException == mbtcp::kIllegalAddress);
  assert(wire.get(hca::kStartStop) == hca::kStopValue);
  puts("PASS: registradores FC03/FC06/FC16 (faixa 14..70 do 10029, valores ilegais, só leitura, extensão, tudo ou nada)");
}

void testRelayRules() {
  hcasim::Charger device;
  device.boot(0, 70, 0);
  Wire wire{device};
  assert(wire.write(hca::kMaxChargingPower, 20) && !device.relayClosed());  // ainda 10060 = 1
  assert(wire.write(hca::kStartStop, hca::kStartValue) && device.relayClosed());
  assert(wire.get(hca::kStatus) == hca::kStatusCharging && wire.get(hca::kChargingPower) == 20);
  assert(wire.get(hca::kExtRelay) == 1);
  assert(wire.write(hca::kMaxChargingPower, 35) && device.relayClosed() && wire.get(hca::kChargingPower) == 35);
  // Pausa abaixo do mínimo (13 = 1,3 kW < 1,4 kW): relé abre com 10060 ainda = 2.
  assert(wire.write(hca::kMaxChargingPower, 13) && !device.relayClosed());
  assert(wire.get(hca::kStatus) == hca::kStatusPlugged && wire.get(hca::kChargingPower) == 0);
  assert(wire.get(hca::kStartStop) == hca::kStartValue);
  assert(wire.write(hca::kMaxChargingPower, 0) && !device.relayClosed());
  assert(wire.write(hca::kMaxChargingPower, 14) && device.relayClosed());  // mínimo exato fecha
  assert(wire.write(hca::kStartStop, hca::kStopValue) && !device.relayClosed());
  assert(wire.get(hca::kChargingPower) == 0 && wire.get(hca::kExtRelay) == 0);
  // Unit id diferente: exceção 0x0B, nada muda e não alimenta o watchdog.
  Wire other{device, 2};
  assert(!other.write(hca::kStartStop, hca::kStartValue) && other.lastException == mbtcp::kGatewayTargetFailed);
  assert(!device.relayClosed());
  assert(device.setAddress(2) && !device.setAddress(0) && !device.setAddress(248) && device.address() == 2);
  assert(other.write(hca::kStartStop, hca::kStartValue) && device.relayClosed());
  puts("PASS: relé fecha só com 10060 = 2 e 10029 >= 14; abre com 10060 = 1 e abaixo do mínimo (pausa); unit id = endereço");
}

void testWatchdog() {
  hcasim::Charger device;
  device.boot(0, 70, 0);
  Wire wire{device};
  device.tick(60000);  // sem mestre desde o boot: watchdog desarmado
  assert(device.fault() == hca::kFaultNone && !device.watchdogArmed());
  assert(wire.write(hca::kMaxChargingPower, 20) && wire.write(hca::kStartStop, hca::kStartValue));
  assert(device.relayClosed() && device.watchdogArmed());
  // Leituras do mestre (a tela lê a cada 1 s) mantêm o relé fechado.
  for (uint32_t t = 61000; t <= 120000; t += 1000) {
    device.tick(t);
    uint16_t live[3];
    assert(wire.read(hca::kChargingPower, 3, live) && live[0] == 20);
  }
  device.tick(120000 + 14999);
  assert(device.relayClosed());
  device.tick(120000 + 15000);  // 15 s sem leitura nem escrita
  assert(!device.relayClosed() && device.fault() == hca::kFaultCommunication);
  assert(device.reg(hca::kStatus) == hca::kStatusAlarm && device.reg(hca::kStartStop) == hca::kStopValue);
  // A leitura mostra o alarme (não limpa); a próxima escrita limpa, sem religar sozinho.
  assert(wire.get(hca::kStatus) == hca::kStatusAlarm && wire.get(hca::kExtFault) == hca::kFaultCommunication);
  assert(wire.write(hca::kMaxChargingPower, 20));
  assert(device.fault() == hca::kFaultNone && !device.relayClosed() && wire.get(hca::kStatus) == hca::kStatusPlugged);
  assert(wire.write(hca::kStartStop, hca::kStartValue) && device.relayClosed());
  // Sem contato de novo por 15 s: dispara de novo.
  device.tick(200000);
  assert(!device.relayClosed() && device.fault() == hca::kFaultCommunication);
  // Falha local forçada.
  hcasim::Charger other;
  other.boot(0, 70, 0);
  Wire otherWire{other};
  assert(otherWire.write(hca::kStartStop, hca::kStartValue) && other.relayClosed());
  other.forceFault(7);
  assert(!other.relayClosed() && other.reg(hca::kStatus) == hca::kStatusAlarm && other.fault() == 7);
  puts("PASS: watchdog de 15 s (leituras alimentam, abre o relé, status 5, 10060 = 1, só a escrita limpa, sem religar)");
}

// Mestre lendo a cada 1 s (como a tela) de `from` até `to`.
void masterPolls(hcasim::Charger& device, Wire& wire, uint32_t from, uint32_t to) {
  for (uint32_t t = from + 1000; t <= to; t += 1000) {
    device.tick(t);
    uint16_t live[3];
    assert(wire.read(hca::kChargingPower, 3, live));
  }
  device.tick(to);
}

void testEnergy() {
  hcasim::Charger device;
  device.boot(0, 70, 0);
  Wire wire{device};
  assert(wire.write(hca::kStartStop, hca::kStartValue));       // 7,0 kW
  masterPolls(device, wire, 0, 1800000);                        // 30 min
  assert(device.energyWh() == 3500);
  assert(wire.write(hca::kMaxChargingPower, 20));               // 2,0 kW
  masterPolls(device, wire, 1800000, 1800000 + 900000);         // +15 min
  assert(device.energyWh() == 4000);
  assert(wire.write(hca::kStartStop, hca::kStopValue));
  masterPolls(device, wire, 2700000, 3600000);                  // aberto: não soma
  assert(device.energyWh() == 4000);
  assert(wire.get(hca::kExtEnergyHigh) == 0 && wire.get(hca::kExtEnergyLow) == 4000);
  // U32: passa de 65535 Wh.
  assert(wire.write(hca::kMaxChargingPower, 70) && wire.write(hca::kStartStop, hca::kStartValue));
  masterPolls(device, wire, 3600000, 3600000 + 10u * 3600000u);  // 10 h a 7 kW = 70 kWh
  assert(device.energyWh() == 74000);
  assert(wire.get(hca::kExtEnergyHigh) == 1 && wire.get(hca::kExtEnergyLow) == 74000 - 65536);
  // Pausa (10029 < 14) não soma.
  assert(wire.write(hca::kMaxChargingPower, 10));
  masterPolls(device, wire, 3600000 + 10u * 3600000u, 3600000 + 11u * 3600000u);
  assert(device.energyWh() == 74000);
  // Mestre some com o relé fechado: soma só até o watchdog (15 s a 7 kW ≈ 29,17 Wh).
  hcasim::Charger lost;
  lost.boot(0, 70, 0);
  Wire lostWire{lost};
  assert(lostWire.write(hca::kStartStop, hca::kStartValue));
  lost.tick(3600000);  // um tick só, 1 h depois
  assert(!lost.relayClosed() && lost.energyWh() == 29);
  puts("PASS: energia SIMULADA integra 10015 (troca de potência, aberto/pausado não somam, para no watchdog, U32 em 19001/19002)");
}

void testFraming() {
  hcasim::Charger device;
  device.boot(0, 70, 0);
  uint8_t request[mbtcp::kMaxAdu], response[mbtcp::kMaxAdu];
  size_t size = mbtcp::buildReadHolding(0x1234, 1, hca::kStartStop, 1, request);
  assert(mbtcp::frameLength(request, 5) == 0 && mbtcp::frameLength(request, size - 1) == 0);
  assert(mbtcp::frameLength(request, size) == (long)size);
  uint8_t bad[12];
  memcpy(bad, request, size);
  bad[3] = 1;  // protocolo != 0
  assert(mbtcp::frameLength(bad, size) == -1);
  size_t length = mbtcp::serve(request, size, 1, device, response);
  assert(length == 11 && response[0] == 0x12 && response[1] == 0x34 && response[7] == 3 && response[8] == 2);
  uint16_t value = 0;
  assert(mbtcp::parseResponse(request, response, length, &value, nullptr) == mbtcp::Status::Ok && value == 1);
  // Transação diferente é recusada pelo cliente.
  uint8_t other[mbtcp::kMaxAdu];
  mbtcp::buildReadHolding(0x9999, 1, hca::kStartStop, 1, other);
  assert(mbtcp::parseResponse(other, response, length, &value, nullptr) == mbtcp::Status::Mismatch);
  // Função não suportada (FC04) → exceção 01. Quantidade 0 / 126 → 03.
  request[7] = 0x04;
  length = mbtcp::serve(request, size, 1, device, response);
  assert(length == 9 && response[7] == 0x84 && response[8] == mbtcp::kIllegalFunction);
  size = mbtcp::buildReadHolding(1, 1, hca::kEmsDispatch, 0, request);
  length = mbtcp::serve(request, size, 1, device, response);
  assert(response[7] == 0x83 && response[8] == mbtcp::kIllegalValue);
  size = mbtcp::buildReadHolding(1, 1, hca::kEmsDispatch, 126, request);
  length = mbtcp::serve(request, size, 1, device, response);
  assert(response[7] == 0x83 && response[8] == mbtcp::kIllegalValue);
  uint8_t exception = 0;
  assert(mbtcp::parseResponse(request, response, length, &value, &exception) == mbtcp::Status::Exception &&
         exception == mbtcp::kIllegalValue);
  // Truncado: o servidor não responde; FC16 com contagem de bytes errada → 03.
  assert(mbtcp::serve(request, size - 1, 1, device, response) == 0);
  const uint16_t values[] = {20};
  size = mbtcp::buildWriteMultiple(2, 1, hca::kMaxChargingPower, 1, values, request);
  request[12] = 4;
  length = mbtcp::serve(request, size, 1, device, response);
  assert(response[7] == 0x90 && response[8] == mbtcp::kIllegalValue);
  assert(mbtcp::buildWriteMultiple(2, 1, 0, 0, values, request) == 0);
  puts("PASS: Modbus TCP mínimo (MBAP, quadro parcial/inválido, FC03/FC06/FC16, exceções 01/02/03/0B, transação)");
}

void testPowerRounding() {
  // Igual a GoodWeHcaG2.register_value() (chargegrid_core): para baixo em 0,1 kW, teto 7,0 kW.
  assert(hca::registerForPowerW(0) == 0 && hca::registerForPowerW(-5) == 0);
  assert(hca::registerForPowerW(1399) == 0 && hca::registerForPowerW(1400) == 14);
  assert(hca::registerForPowerW(2050) == 20 && hca::registerForPowerW(2099) == 20);
  assert(hca::registerForPowerW(7000) == 70 && hca::registerForPowerW(7200) == 70 && hca::registerForPowerW(22000) == 70);
  assert(hca::powerWForRegister(37) == 3700);
  puts("PASS: W -> 10029 (0,1 kW para baixo, mínimo 1,4 kW = pausa abaixo, máximo 7,0 kW)");
}

}  // namespace

int main() {
  testBootSafe();
  testRegistersAndRange();
  testRelayRules();
  testWatchdog();
  testEnergy();
  testFraming();
  testPowerRounding();
  puts("PASS: carregador HCA G2 simulado (lógica pura do firmware goodwe-hca-sim)");
  return 0;
}
