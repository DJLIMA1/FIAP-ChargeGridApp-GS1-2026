#pragma once
// Modbus TCP mínimo (MBAP + FC03/FC06/FC16), C++ puro e sem alocação dinâmica.
// Servidor: carregador simulado (firmware/goodwe-hca-sim). Cliente: tela (firmware/esp32).
// Testado no host (tools/tests/hca_sim_test.cpp, charger_link_test.cpp e
// tools/tests/test_hca_sim_e2e.py, que fala Modbus TCP de verdade com o servidor de host).
#include <stddef.h>
#include <stdint.h>

namespace mbtcp {

constexpr size_t kMbapSize = 7;      // transação(2) protocolo(2) tamanho(2) unidade(1)
constexpr size_t kMaxAdu = 260;      // MBAP + PDU de até 253 bytes
constexpr uint16_t kMaxReadCount = 125, kMaxWriteCount = 123;

constexpr uint8_t kReadHolding = 0x03, kWriteSingle = 0x06, kWriteMultiple = 0x10;
constexpr uint8_t kIllegalFunction = 0x01, kIllegalAddress = 0x02, kIllegalValue = 0x03,
                  kDeviceFailure = 0x04, kGatewayTargetFailed = 0x0B;

// Banco de holding registers do servidor. Retorna 0 (ok) ou o código de exceção Modbus.
// Uma escrita múltipla só é aplicada se todos os valores forem válidos.
class RegisterBank {
 public:
  virtual ~RegisterBank() = default;
  virtual uint8_t readHolding(uint16_t address, uint16_t count, uint16_t* out) = 0;
  virtual uint8_t writeHolding(uint16_t address, uint16_t count, const uint16_t* values) = 0;
};

// Tamanho total do quadro no início do buffer: 0 = incompleto, -1 = inválido (fechar a
// conexão: protocolo != 0 ou tamanho fora do limite).
long frameLength(const uint8_t* buffer, size_t length);

// Atende um ADU completo. Escreve a resposta em `out` (>= kMaxAdu bytes) e retorna o seu
// tamanho. Unidade diferente de `unitId`: exceção 0x0B sem tocar no banco (não conta como
// contato do mestre).
size_t serve(const uint8_t* adu, size_t length, uint8_t unitId, RegisterBank& bank, uint8_t* out);

// Cliente: monta pedidos (retorna o tamanho).
size_t buildReadHolding(uint16_t transaction, uint8_t unit, uint16_t address, uint16_t count, uint8_t* out);
size_t buildWriteSingle(uint16_t transaction, uint8_t unit, uint16_t address, uint16_t value, uint8_t* out);
size_t buildWriteMultiple(uint16_t transaction, uint8_t unit, uint16_t address, uint16_t count,
                          const uint16_t* values, uint8_t* out);

enum class Status : uint8_t { Ok, Exception, Malformed, Mismatch };
// Confere a resposta ao pedido `request` (mesma transação, unidade e função). Leitura:
// copia `count` registradores para `values`. Exceção: `exceptionCode` recebe o código.
Status parseResponse(const uint8_t* request, const uint8_t* response, size_t length, uint16_t* values,
                     uint8_t* exceptionCode);

}  // namespace mbtcp
