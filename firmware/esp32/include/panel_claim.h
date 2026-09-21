#pragma once
#include <cstring>

// A claim secret is distinct from the device's API credential. Tokens are
// unpadded, 32-byte base64url values issued by the factory API.
inline bool validPanelClaimToken(const char* token) {
  if (!token || std::strlen(token) != 43) return false;
  for (const char* c = token; *c; ++c) {
    if (!((*c >= 'A' && *c <= 'Z') || (*c >= 'a' && *c <= 'z') ||
          (*c >= '0' && *c <= '9') || *c == '-' || *c == '_')) return false;
  }
  return true;
}

template<class Storage>
bool savePanelClaim(Storage& storage, const char* token, bool idle, bool sessionPending, bool owned) {
  if (!idle || sessionPending || owned || storage.getBool("owned", false) || !validPanelClaimToken(token)) return false;
  return storage.putString("claim_token", token) == 43;
}

template<class Storage>
bool rememberPanelOwnership(Storage& storage) {
  // Keep a durable tombstone as well as removing the secret. A missing owned
  // field from an older API must never undo an earlier confirmation.
  const bool marked = storage.getBool("owned", false) || storage.putBool("owned", true) > 0;
  const bool cleared = !storage.isKey("claim_token") || storage.remove("claim_token");
  return marked && cleared;
}

template<class Storage>
bool preparePanelForFactoryReprovision(Storage& storage, bool idle, bool sessionPending) {
  // A local USB confirmation can retire a legacy identity without erasing
  // Wi-Fi or the session journal. Removing the old API key first prevents a
  // reboot from re-confirming the old owner before the new key is installed.
  if (!idle || sessionPending) return false;
  const bool keyCleared = !storage.isKey("device_key") || storage.remove("device_key");
  if (!keyCleared) return false;
  const bool tokenCleared = !storage.isKey("claim_token") || storage.remove("claim_token");
  if (!tokenCleared) return false;
  return storage.putBool("owned", false) > 0;
}
