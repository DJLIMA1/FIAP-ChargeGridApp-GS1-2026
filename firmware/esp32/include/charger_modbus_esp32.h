#pragma once
// Transporte Modbus TCP da tela para os carregadores GoodWe HCA G2 (WiFiClient + mDNS), só no ESP32.
#include <Arduino.h>
#include "charger_link.h"

// Um cliente (conexão TCP + resolução) por carregador: slot 0 = o ponto da tela; 1.. = adicionais.
constexpr uint8_t kEspChargerClients = 4;
charger::ModbusClient& espChargerClient(uint8_t slot = 0);
// IP fixo do carregador do ponto da tela (fallback ao mDNS), gravado na NVS (CG_CHARGER_IP). Vazio = host.
void espChargerSetFixedIp(const String& ip);
String espChargerFixedIp();
// Uma linha de diagnóstico (IP resolvido, último IP bom, conexão, último erro de transporte).
String espChargerDescribe(uint8_t slot = 0);
