#include "modbus_tcp.h"

namespace mbtcp {
namespace {

uint16_t be16(const uint8_t* data) { return static_cast<uint16_t>((data[0] << 8) | data[1]); }
void put16(uint8_t* data, uint16_t value) {
  data[0] = static_cast<uint8_t>(value >> 8);
  data[1] = static_cast<uint8_t>(value & 0xFF);
}
size_t header(uint8_t* out, uint16_t transaction, uint8_t unit, size_t pduLength) {
  put16(out, transaction);
  put16(out + 2, 0);
  put16(out + 4, static_cast<uint16_t>(pduLength + 1));
  out[6] = unit;
  return kMbapSize;
}
size_t exception(const uint8_t* adu, uint8_t function, uint8_t code, uint8_t* out) {
  header(out, be16(adu), adu[6], 2);
  out[7] = static_cast<uint8_t>(function | 0x80);
  out[8] = code;
  return kMbapSize + 2;
}

}  // namespace

long frameLength(const uint8_t* buffer, size_t length) {
  if (length < 6) return 0;
  const uint16_t protocol = be16(buffer + 2), size = be16(buffer + 4);
  if (protocol != 0 || size < 2 || size + 6 > kMaxAdu) return -1;
  return length >= size + 6u ? static_cast<long>(size + 6) : 0;
}

size_t serve(const uint8_t* adu, size_t length, uint8_t unitId, RegisterBank& bank, uint8_t* out) {
  if (length < kMbapSize + 1 || frameLength(adu, length) != static_cast<long>(length)) return 0;
  const uint8_t function = adu[7];
  if (adu[6] != unitId) return exception(adu, function, kGatewayTargetFailed, out);
  const uint8_t* pdu = adu + kMbapSize;
  const size_t pduLength = length - kMbapSize;
  if (function == kReadHolding) {
    if (pduLength != 5) return exception(adu, function, kIllegalValue, out);
    const uint16_t address = be16(pdu + 1), count = be16(pdu + 3);
    if (count < 1 || count > kMaxReadCount) return exception(adu, function, kIllegalValue, out);
    uint16_t values[kMaxReadCount];
    const uint8_t error = bank.readHolding(address, count, values);
    if (error) return exception(adu, function, error, out);
    header(out, be16(adu), unitId, 2 + count * 2u);
    out[7] = function;
    out[8] = static_cast<uint8_t>(count * 2);
    for (uint16_t i = 0; i < count; ++i) put16(out + 9 + i * 2, values[i]);
    return kMbapSize + 2 + count * 2u;
  }
  if (function == kWriteSingle) {
    if (pduLength != 5) return exception(adu, function, kIllegalValue, out);
    const uint16_t address = be16(pdu + 1), value = be16(pdu + 3);
    const uint8_t error = bank.writeHolding(address, 1, &value);
    if (error) return exception(adu, function, error, out);
    for (size_t i = 0; i < length; ++i) out[i] = adu[i];  // Eco do pedido.
    return length;
  }
  if (function == kWriteMultiple) {
    if (pduLength < 6) return exception(adu, function, kIllegalValue, out);
    const uint16_t address = be16(pdu + 1), count = be16(pdu + 3);
    const uint8_t bytes = pdu[5];
    if (count < 1 || count > kMaxWriteCount || bytes != count * 2 || pduLength != 6u + bytes)
      return exception(adu, function, kIllegalValue, out);
    uint16_t values[kMaxWriteCount];
    for (uint16_t i = 0; i < count; ++i) values[i] = be16(pdu + 6 + i * 2);
    const uint8_t error = bank.writeHolding(address, count, values);
    if (error) return exception(adu, function, error, out);
    header(out, be16(adu), unitId, 5);
    out[7] = function;
    put16(out + 8, address);
    put16(out + 10, count);
    return kMbapSize + 5;
  }
  return exception(adu, function, kIllegalFunction, out);
}

size_t buildReadHolding(uint16_t transaction, uint8_t unit, uint16_t address, uint16_t count, uint8_t* out) {
  header(out, transaction, unit, 5);
  out[7] = kReadHolding;
  put16(out + 8, address);
  put16(out + 10, count);
  return kMbapSize + 5;
}

size_t buildWriteSingle(uint16_t transaction, uint8_t unit, uint16_t address, uint16_t value, uint8_t* out) {
  header(out, transaction, unit, 5);
  out[7] = kWriteSingle;
  put16(out + 8, address);
  put16(out + 10, value);
  return kMbapSize + 5;
}

size_t buildWriteMultiple(uint16_t transaction, uint8_t unit, uint16_t address, uint16_t count,
                          const uint16_t* values, uint8_t* out) {
  if (count < 1 || count > kMaxWriteCount) return 0;
  header(out, transaction, unit, 6 + count * 2u);
  out[7] = kWriteMultiple;
  put16(out + 8, address);
  put16(out + 10, count);
  out[12] = static_cast<uint8_t>(count * 2);
  for (uint16_t i = 0; i < count; ++i) put16(out + 13 + i * 2, values[i]);
  return kMbapSize + 6 + count * 2u;
}

Status parseResponse(const uint8_t* request, const uint8_t* response, size_t length, uint16_t* values,
                     uint8_t* exceptionCode) {
  if (frameLength(response, length) != static_cast<long>(length) || length < kMbapSize + 2) return Status::Malformed;
  if (be16(response) != be16(request) || response[6] != request[6]) return Status::Mismatch;
  const uint8_t function = request[7];
  if (response[7] == (function | 0x80)) {
    if (length != kMbapSize + 2) return Status::Malformed;
    if (exceptionCode) *exceptionCode = response[8];
    return Status::Exception;
  }
  if (response[7] != function) return Status::Mismatch;
  if (function == kReadHolding) {
    const uint16_t count = be16(request + 10);
    if (response[8] != count * 2 || length != kMbapSize + 2 + count * 2u) return Status::Malformed;
    for (uint16_t i = 0; i < count; ++i) values[i] = be16(response + 9 + i * 2);
    return Status::Ok;
  }
  if (function == kWriteSingle || function == kWriteMultiple) {
    if (length != kMbapSize + 5) return Status::Malformed;
    for (size_t i = 8; i < 12; ++i)
      if (response[i] != request[i]) return Status::Mismatch;
    return Status::Ok;
  }
  return Status::Mismatch;
}

}  // namespace mbtcp
