#pragma once
// Mapa Modbus do GoodWe HCA G2 usado pelo carregador simulado (firmware/goodwe-hca-sim)
// e pela tela (firmware/esp32). C++ puro, sem Arduino: compila no host para os testes.
//
// SEM VALIDAÇÃO EM HARDWARE. Endereços, tipos e escalas iguais a
// packages/chargegrid_core/chargegrid_core/chargers/goodwe_hca_g2.py e
// docs/adaptador-hca-g2.md (documento do fabricante "AC EV Charger Gen2 Modbus Protocol"
// V1.0.15, não publicado pela GoodWe, via transcrições públicas).
#include <stdint.h>

namespace hca {

// Holding registers (FC03 lê, FC06/FC16 escrevem), sem deslocamento de endereço.
constexpr uint16_t kEmsDispatch = 10000;
constexpr uint16_t kChargingPower = 10015;     // RO, U16, 0,1 kW
constexpr uint16_t kStatus = 10017;            // RO, enum (abaixo)
constexpr uint16_t kKeepMinPower = 10024;      // RW, nunca escrito pela tela
constexpr uint16_t kDynamicLoad = 10025;       // RW, nunca escrito pela tela
constexpr uint16_t kHouseBreaker = 10026;      // RW, nunca escrito pela tela
constexpr uint16_t kMaxChargingPower = 10029;  // RW, U16, 0,1 kW (grava flash: só escrever quando muda)
constexpr uint16_t kChargeMode = 10032;        // RW, 0 rápido, 1 FV, 2 FV + bateria
constexpr uint16_t kPowerSpec = 10058;         // RO, 0 = 7 kW, 1 = 11 kW, 2 = 22 kW
constexpr uint16_t kChargerType = 10059;       // RO, 0 = trifásico, 1 = monofásico
constexpr uint16_t kStartStop = 10060;         // RW, 1 = desliga, 2 = liga

// Faixa oficial lida pelo simulado (FC03): 10000..10060.
constexpr uint16_t kOfficialFirst = 10000, kOfficialLast = 10060;

constexpr uint16_t kStopValue = 1, kStartValue = 2, kFastMode = 0;

// 10017 (Charging Station Status), códigos do mapa: 0 livre, 1 plugado, 2 handshake,
// 3 carregando, 4 concluído, 5 alarme, 8 falha ao iniciar. O simulado usa só:
//   1 = parado/pausado (relé aberto; a tomada está sempre "plugada"),
//   3 = carregando (relé fechado),
//   5 = alarme (relé aberto por falha: watchdog de comunicação).
constexpr uint16_t kStatusFree = 0, kStatusPlugged = 1, kStatusHandshake = 2, kStatusCharging = 3,
                   kStatusFinished = 4, kStatusAlarm = 5, kStatusStartFailed = 8;

// Extensão SIMULADA (fora da faixa oficial, só leitura): o mapa V1.0.15 transcrito não
// tem registrador de energia. Nenhum HCA G2 real responde a estes endereços.
constexpr uint16_t kExtFirst = 19000;
constexpr uint16_t kExtVersion = 19000;    // 1 = esta extensão
constexpr uint16_t kExtEnergyHigh = 19001; // energia simulada desde o boot, U32 em Wh (palavra alta)
constexpr uint16_t kExtEnergyLow = 19002;  // (palavra baixa)
constexpr uint16_t kExtRelay = 19003;      // 0 aberto, 1 fechado
constexpr uint16_t kExtFault = 19004;      // 0 nenhuma, 1 watchdog de comunicação (15 s sem mestre)
constexpr uint16_t kExtAddress = 19005;    // endereço (unit id) configurado
constexpr uint16_t kExtSimulated = 19006;  // sempre 1: potência e energia são SIMULADAS
constexpr uint16_t kExtLast = 19006;
constexpr uint16_t kFaultNone = 0, kFaultCommunication = 1;

// Modelo simulado: GW7K-HCA-20, monofásico, 10029 em 14..70 (1,4..7,0 kW).
struct Model {
  const char* name;
  uint16_t minTenths, maxTenths;
  uint8_t phases;
  uint16_t powerSpec, chargerType;
};
constexpr Model kGw7k{"GW7K-HCA-20", 14, 70, 1, 0, 1};

constexpr uint16_t kDefaultPort = 502;
constexpr uint8_t kDefaultAddress = 1, kMaxAddress = 247;
constexpr uint32_t kWatchdogMs = 15000;

// Valor do 10029 para um pedido em W: arredonda para baixo em 0,1 kW e limita ao máximo;
// 0 = pausar (abaixo do mínimo de 6 A por fase). Igual a GoodWeHcaG2.register_value().
inline uint16_t registerForPowerW(long watts, const Model& model = kGw7k) {
  if (watts <= 0) return 0;
  const long tenths = watts / 100;
  if (tenths < model.minTenths) return 0;
  return static_cast<uint16_t>(tenths > model.maxTenths ? model.maxTenths : tenths);
}
inline long powerWForRegister(uint16_t tenths) { return static_cast<long>(tenths) * 100L; }

}  // namespace hca
