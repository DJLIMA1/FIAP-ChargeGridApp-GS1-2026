// Testes de host da tela ⇄ carregador HCA G2 (firmware/esp32/src/charger_link.cpp): tradução
// START/STOP/SET_POWER em registradores, ACK só depois da releitura, leitura periódica,
// perda do carregador. O "cliente Modbus falso" monta ADUs reais e os entrega à lógica real
// do carregador simulado (tools/tests/fake_charger_client.h). Sem Arduino, com sanitizers.
#include <cassert>
#include <cstdio>
#include <array>
#include <cstring>
#include <string>
#include "charger_link.h"
#include "fake_charger_client.h"

namespace {

unsigned long now = 1000;

charger::LinkConfig link1() {
  charger::LinkConfig config;
  assert(charger::makeConfig("goodwe_hca_g2", "modbus_tcp", 1, "cg-hca-1.local", 502, config));
  return config;
}

void testConfig() {
  charger::LinkConfig config;
  assert(charger::makeConfig("goodwe_hca_g2", "modbus_tcp", 1, nullptr, 502, config));
  assert(config.present && config.address == 1 && config.port == 502 && std::string(config.host) == "cg-hca-1.local");
  assert(charger::makeConfig("goodwe_hca_g2", "modbus_tcp", 247, "192.168.0.50", 1502, config));
  assert(std::string(config.host) == "192.168.0.50" && config.port == 1502 && config.address == 247);
  assert(!charger::makeConfig("goodwe_hca_g2", "modbus_tcp", 0, nullptr, 502, config) && !config.present);
  assert(!charger::makeConfig("goodwe_hca_g2", "modbus_tcp", 248, nullptr, 502, config));
  assert(!charger::makeConfig("esp32_bench", "modbus_tcp", 1, nullptr, 502, config));
  assert(!charger::makeConfig("goodwe_hca_g2", "simulated", 1, nullptr, 502, config));
  assert(!charger::makeConfig(nullptr, nullptr, 1, nullptr, 502, config));
  assert(!charger::makeConfig("goodwe_hca_g2", "modbus_tcp", 1, "cg hca.local", 502, config));
  assert(!charger::makeConfig("goodwe_hca_g2", "modbus_tcp", 1, std::string(64, 'a').c_str(), 502, config));
  assert(!charger::makeConfig("goodwe_hca_g2", "modbus_tcp", 1, nullptr, 70000, config));
  FakeChargerClient client(&now);
  charger::Link link;
  assert(!link.active());
  link.setClient(&client);
  assert(!link.active());                 // sem configuração = sem carregador externo
  long applied = -1;
  assert(link.start(2000, now, &applied) == charger::Error::NoLink && client.log.empty());
  assert(link.configure(link1()) && link.active() && client.resets == 1);
  assert(!link.configure(link1()) && client.resets == 1);  // igual: não reinicia
  assert(link.configure(charger::LinkConfig{}) && !link.active());
  assert(std::string(charger::errorCode(charger::Error::Offline)) == "charger_offline");
  assert(charger::errorCode(charger::Error::None) == nullptr);
  puts("PASS: connector.charger_link validado (modelo, transporte, endereço 1..247, host/IP, padrão cg-hca-<n>.local)");
}

void testCommands() {
  FakeChargerClient client(&now);
  charger::Link link;
  link.setClient(&client);
  link.configure(link1());
  long applied = -1;
  // START 2,05 kW: modo rápido uma vez, 10029 = 20 (arredonda para baixo), 10060 = 2, releitura.
  assert(link.start(2050, now, &applied) == charger::Error::None && applied == 2000);
  assert(client.writes() == "W 10032=0|W 10029=20|W 10060=2");
  assert(client.device.relayClosed() && link.expectRunning() && link.measuredPowerW() == 2000);
  assert(link.status() == hca::kStatusCharging && link.limitRegister() == 20 && link.startStopRegister() == 2);
  // A confirmação lê 10015..10017, 10029 e 10060 depois das escritas.
  assert(client.log.back() == "R 10060x1");
  // SET_POWER 3,5 kW: só o 10029 muda (flash) + 10060 = 2 (sem flash, sempre).
  client.log.clear();
  assert(link.setPower(3550, now, &applied) == charger::Error::None && applied == 3500);
  assert(client.writes() == "W 10029=35|W 10060=2" && link.measuredPowerW() == 3500);
  client.log.clear();
  assert(link.setPower(3599, now, &applied) == charger::Error::None && applied == 3500);
  assert(client.writes() == "W 10060=2");  // 10029 igual: não regrava
  // Abaixo do mínimo (1,3 kW) pausa por 10060 = 1; o 10029 fica como estava.
  client.log.clear();
  assert(link.setPower(1300, now, &applied) == charger::Error::None && applied == 0);
  assert(client.writes() == "W 10060=1" && !client.device.relayClosed() && !link.expectRunning());
  assert(client.device.reg(hca::kMaxChargingPower) == 35 && link.measuredPowerW() == 0);
  // Retoma acima do máximo do modelo: limita a 7,0 kW.
  client.log.clear();
  assert(link.setPower(7200, now, &applied) == charger::Error::None && applied == 7000);
  assert(client.writes() == "W 10029=70|W 10060=2" && client.device.relayClosed());
  // STOP: 10060 = 1 e confirma por 10060 = 1 e 10015 = 0.
  client.log.clear();
  assert(link.stop(now) == charger::Error::None);
  assert(client.writes() == "W 10060=1" && !client.device.relayClosed() && !link.expectRunning());
  // Novo START com o mesmo limite: modo já escrito, 10029 igual → só liga.
  client.log.clear();
  assert(link.start(7000, now, &applied) == charger::Error::None && applied == 7000);
  assert(client.writes() == "W 10060=2");
  link.stop(now);
  // START com 0 W (power_limit_w = 0): começa pausado.
  client.log.clear();
  assert(link.start(0, now, &applied) == charger::Error::None && applied == 0);
  assert(client.writes() == "W 10060=1" && !client.device.relayClosed());
  // Link novo (outro endereço) reescreve o modo na próxima recarga.
  charger::LinkConfig other = link1();
  other.address = 2;
  client.device.setAddress(2);
  assert(link.configure(other));
  client.device.writeHolding(hca::kChargeMode, 1, std::array<uint16_t, 1>{1}.data());
  client.log.clear();
  assert(link.start(2000, now, &applied) == charger::Error::None);
  assert(client.writes() == "W 10032=0|W 10029=20|W 10060=2");
  puts("PASS: START/SET_POWER/STOP → 10032 (uma vez), 10029 (só se mudou, 0,1 kW para baixo, teto 7,0), 10060; pausa abaixo de 1,4 kW");
}

void testAckOnlyAfterReadback() {
  long applied = -1;
  {  // Carregador fora do ar: START falha, nada fica ligado.
    FakeChargerClient client(&now);
    charger::Link link;
    link.setClient(&client);
    link.configure(link1());
    client.offline = true;
    assert(link.start(2000, now, &applied) == charger::Error::Offline);
    assert(!link.online() && !link.expectRunning() && !client.device.relayClosed());
    assert(link.lastError() == charger::Error::Offline);
    // Recusa só depois de kStartAttempts tentativas, cada uma pedindo resolução imediata.
    assert(client.count("R 10032x1") == charger::kStartAttempts && client.urgent == charger::kStartAttempts);
  }
  {  // 1ª tentativa sem resposta (conexão velha, mDNS lento após reboot), 2ª confirma: START ok.
    FakeChargerClient client(&now);
    charger::Link link;
    link.setClient(&client);
    link.configure(link1());
    client.failNext = 1;
    applied = -1;
    assert(link.start(2000, now, &applied) == charger::Error::None && applied == 2000);
    assert(client.urgent == 2 && client.device.relayClosed() && link.online() && link.expectRunning());
    assert(client.writes() == "W 10032=0|W 10029=20|W 10060=2");
  }
  {  // Online na última leitura: a 1ª tentativa não força resolução; a recusa (0x0B) não repete.
    FakeChargerClient client(&now, 3);
    charger::Link link;
    link.setClient(&client);
    link.configure(link1());
    link.poll(now);
    assert(link.online() && client.urgent == 0);
    assert(link.start(2000, now, &applied) == charger::Error::Rejected && client.urgent == 0);
  }
  {  // Escrita do 10029 perdida (eco ok, não aplicada): a releitura não bate → falha e desliga.
    FakeChargerClient client(&now);
    charger::Link link;
    link.setClient(&client);
    link.configure(link1());
    client.dropWrites = 2;  // 10032 e 10029 perdidas; 10060 = 2 aplicada (relé fecha a 7 kW!)
    applied = -1;
    assert(link.start(2000, now, &applied) == charger::Error::ReadbackMismatch && applied == -1);
    assert(!client.device.relayClosed() && !link.expectRunning());  // desligado em seguida
    assert(client.writes() == "W 10032=0 lost|W 10029=20 lost|W 10060=2|W 10060=1");
  }
  {  // SET_POWER com o 10029 perdido: sem ACK, o limite anterior continua valendo.
    FakeChargerClient client(&now);
    charger::Link link;
    link.setClient(&client);
    link.configure(link1());
    assert(link.start(2000, now, &applied) == charger::Error::None);
    client.dropWrites = 1;
    applied = -1;
    assert(link.setPower(3000, now, &applied) == charger::Error::ReadbackMismatch && applied == -1);
    assert(client.device.relayClosed() && client.device.reg(hca::kMaxChargingPower) == 20 && link.expectRunning());
    // STOP perdido: sem ACK applied; a parada fica pendente e sai na próxima leitura.
    assert(link.setPower(3000, now, &applied) == charger::Error::None && client.device.relayClosed());
    client.dropWrites = 1;
    assert(link.stop(now) == charger::Error::ReadbackMismatch && link.pendingStop());
    assert(client.device.relayClosed());
    // Outra escrita recebe eco sem aplicar: o poll não pode apagar a pendência.
    client.dropWrites = 2;
    client.log.clear();
    now += charger::kPollMs;
    link.poll(now);
    assert(client.writes() == "W 10060=1 lost" && link.pendingStop() && client.device.relayClosed());
    // STOP realmente aplicado, mas a última leitura do readback cai: ainda não confirmado.
    client.dropWrites = 0;
    client.failReadAt = hca::kStartStop; client.failReads = 1;
    client.log.clear();
    now += charger::kPollMs;
    link.poll(now);
    assert(client.writes() == "W 10060=1" && link.pendingStop() && !client.device.relayClosed());
    assert(client.log.back() == "R 10060x1" && link.lastError() == charger::Error::Offline);
    // Só a releitura completa libera a parada; sem retomada do carregador.
    client.log.clear();
    now += charger::kPollMs;
    link.poll(now);
    assert(client.writes() == "W 10060=1" && !link.pendingStop() && !client.device.relayClosed());
  }
  {  // Endereço errado: o carregador responde exceção 0x0B → rejeitado (online, mas sem ACK).
    FakeChargerClient client(&now, 3);
    charger::Link link;
    link.setClient(&client);
    link.configure(link1());
    assert(link.start(2000, now, &applied) == charger::Error::Rejected && link.online());
    assert(!client.device.relayClosed());
  }
  puts("PASS: ACK applied só depois da releitura (offline após 2 tentativas, 2ª tentativa ok, escrita perdida no START e no SET_POWER, STOP perdido e readback interrompido → pendente até confirmar, unit id errado sem repetir)");
}

void testPollingAndLoss() {
  long applied = -1;
  {  // Leitura a cada ~1 s; carregador some → perda depois de 5 s, não antes.
    now = 100000;
    FakeChargerClient client(&now);
    charger::Link link;
    link.setClient(&client);
    link.configure(link1());
    assert(link.start(3000, now, &applied) == charger::Error::None);
    client.log.clear();
    link.poll(now + 10);
    assert(client.log.size() == 1 && client.log[0] == "R 10015x3");  // primeira leitura já
    link.poll(now + 500);
    assert(client.log.size() == 1);                                  // ainda dentro de 1 s
    link.poll(now + 1010);
    assert(client.log.size() == 2 && link.online() && !link.faulted(now + 1010, true));
    const unsigned long lastOk = now + 1010;
    client.offline = true;
    for (unsigned long t = lastOk + 1000; t < lastOk + charger::kLossMs; t += 1000) {
      link.poll(t);
      assert(!link.online() && !link.faulted(t, true));
    }
    link.poll(lastOk + charger::kLossMs);
    assert(link.faulted(lastOk + charger::kLossMs, true));
    assert(!link.faulted(lastOk + charger::kLossMs, false));  // sem sessão, não é falha de recarga
  }
  {  // A tela lendo a cada 1 s mantém o relé; a tela some → o carregador abre em 15 s.
    now = 200000;
    FakeChargerClient client(&now);
    charger::Link link;
    link.setClient(&client);
    link.configure(link1());
    assert(link.start(7000, now, &applied) == charger::Error::None);
    for (int i = 0; i < 60; ++i) {
      now += 1000;
      link.poll(now);
      assert(client.device.relayClosed() && !link.faulted(now, true));
    }
    now += 14999;
    client.device.tick(now);
    assert(client.device.relayClosed());
    now += 1;
    client.device.tick(now);
    assert(!client.device.relayClosed() && client.device.reg(hca::kStatus) == hca::kStatusAlarm);
    // A tela volta e vê o alarme: falha da recarga na hora.
    link.poll(now);
    assert(link.status() == hca::kStatusAlarm && link.faulted(now, true));
  }
  {  // Carregador reiniciou (boot seguro: relé aberto, status 1): falha depois de 3 leituras.
    now = 300000;
    FakeChargerClient client(&now);
    charger::Link link;
    link.setClient(&client);
    link.configure(link1());
    assert(link.start(2000, now, &applied) == charger::Error::None);
    client.device.boot(now, 20, 0);
    for (int i = 1; i <= charger::kStoppedPolls; ++i) {
      now += 1000;
      link.poll(now);
      assert(link.faulted(now, true) == (i == charger::kStoppedPolls));
    }
  }
  {  // Pausada (0 W) e o carregador some: a sessão também falha (não poderia retomar).
    now = 400000;
    FakeChargerClient client(&now);
    charger::Link link;
    link.setClient(&client);
    link.configure(link1());
    assert(link.start(2000, now, &applied) == charger::Error::None);
    assert(link.setPower(0, now, &applied) == charger::Error::None && !link.expectRunning());
    client.offline = true;
    now += 1000; link.poll(now);
    assert(!link.faulted(now, true));
    now += charger::kLossMs; link.poll(now);
    assert(link.faulted(now, true));
  }
  {  // Carregador ligado sem recarga na tela (tela reiniciou / outro mestre): a leitura desliga.
    now = 500000;
    FakeChargerClient client(&now);
    const uint16_t on = hca::kStartValue;
    client.device.writeHolding(hca::kStartStop, 1, &on);
    assert(client.device.relayClosed());
    charger::Link link;
    link.setClient(&client);
    link.configure(link1());
    link.poll(now);
    assert(client.writes() == "W 10060=1" && !client.device.relayClosed());
    assert(!link.faulted(now, false) && !link.faulted(now, true));
  }
  {  // Ocioso e offline: depois de 3 falhas, tenta a cada 5 s (não trava o loop a cada 1 s).
    now = 600000;
    FakeChargerClient client(&now);
    charger::Link link;
    link.setClient(&client);
    link.configure(link1());
    client.offline = true;
    for (int i = 0; i < 3; ++i) { link.poll(now); now += 1000; }
    assert(link.failures() == 3);
    client.log.clear();
    link.poll(now); link.poll(now + 3000);
    assert(client.log.empty());
    link.poll(now + 4000);  // 5 s depois da última tentativa
    assert(client.log.size() == 1);
    client.offline = false;
    link.poll(now + 9000);
    assert(link.online() && link.failures() == 0);
  }
  puts("PASS: leitura ~1 s, perda em 5 s (também pausada), alarme/reboot do carregador, desliga carregador órfão, recuo a 5 s ocioso");
}

void testBlockingClock() {
  struct ClockedClient : FakeChargerClient {
    unsigned long& time;
    uint32_t readDelay = 1000;
    explicit ClockedClient(unsigned long& value) : FakeChargerClient(&value), time(value) {}
    uint32_t nowMs(uint32_t) const override { return time; }
    bool readHolding(const charger::LinkConfig& config, uint16_t address, uint16_t count,
                     uint16_t* out, uint8_t* exception) override {
      time = uint32_t(time + readDelay);
      return FakeChargerClient::readHolding(config, address, count, out, exception);
    }
  } client(now);
  now = 0xfffffc00UL;
  client.device.boot(now, 70, 0);
  charger::Link link; link.setClient(&client); link.configure(link1());
  assert(link.start(2000, now, nullptr) == charger::Error::None);
  const uint32_t completed = now; // START atravessou wrap e demorou várias leituras.
  client.offline = true; client.readDelay = 0;
  now = uint32_t(completed + 4000); link.poll(now);
  assert(!link.faulted(now, true)); // Conta da última resposta, não do início do START.
  now = uint32_t(completed + 5000); link.poll(now);
  assert(link.faulted(now, true));
  puts("PASS: última resposta usa relógio após I/O bloqueante e atravessa wrap de millis");
}

}  // namespace

int main() {
  testConfig();
  testCommands();
  testAckOnlyAfterReadback();
  testPollingAndLoss();
  testBlockingClock();
  puts("PASS: tela ⇄ carregador HCA G2 (charger_link, cliente Modbus falso sobre a lógica real do simulado)");
  return 0;
}
