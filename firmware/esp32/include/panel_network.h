#pragma once
#include <cstring>

inline bool validPanelNetwork(const char* ssid, const char* password) {
  return ssid && password && ssid[0] && std::strlen(ssid) <= 32 && std::strlen(password) <= 64;
}

// Preferences::putString returns strlen(value), so an empty password cannot
// use the usual > 0 success check. Absence means open Wi-Fi, including on boot.
template<class Storage>
bool savePanelPassword(Storage& storage, const char* password) {
  if (!password) return false;
  if (!password[0]) return !storage.isKey("wifi_pass") || storage.remove("wifi_pass");
  return storage.putString("wifi_pass", password) > 0;
}
