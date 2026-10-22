#pragma once
#include <vector>
struct WiFiClientSecure {
  inline static std::vector<unsigned long> handshakeTimeouts;
  void setCACert(const char*) {}
  void setHandshakeTimeout(unsigned long seconds) { handshakeTimeouts.push_back(seconds); }
  void stop() {}
};
