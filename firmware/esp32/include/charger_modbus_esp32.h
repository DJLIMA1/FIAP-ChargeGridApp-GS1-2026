#pragma once
// Transporte Modbus TCP da tela para o carregador HCA G2 (WiFiClient + mDNS), só no ESP32.
#include <Arduino.h>
#include "charger_link.h"

charger::ModbusClient& espChargerClient();
// IP fixo (fallback ao mDNS), gravado na NVS pela tela (CG_CHARGER_IP). Vazio = usar o host.
void espChargerSetFixedIp(const String& ip);
String espChargerFixedIp();
// Uma linha de diagnóstico (IP resolvido, conexão, último erro de transporte).
String espChargerDescribe();
