#pragma once
#include "WiFi.h"
struct MdnsStub {
  bool available=true;
  int queries=0,starts=0,ends=0;
  IPAddress result{192,168,0,21};
  bool begin(const char*) { ++starts;return true; }
  void end() { ++ends; }
  IPAddress queryHost(const char*,uint32_t timeout) {
    ++queries;
    if (available) return result;
    delay(timeout);return IPAddress(0,0,0,0);
  }
};
inline MdnsStub MDNS;
