#pragma once
#include <Arduino.h>
#include <deque>
#include <vector>
#include <cassert>
#include "WiFiClientSecure.h"
constexpr int HTTPC_DISABLE_FOLLOW_REDIRECTS = 0;
namespace fakehttp {
struct Reply { int code; unsigned long headerMs, bodyMs; String body; };
inline std::deque<Reply> replies;
inline std::vector<String> payloads;
inline int beginFailures = 0;
inline void advance(unsigned long duration) { testMillis = uint32_t(testMillis + duration); }
}
class HTTPClient {
 public:
  void setReuse(bool value) { assert(value); }
  void setTimeout(int value) { assert(value == 3000); }
  void setConnectTimeout(int value) { assert(value == 3000); }
  void setFollowRedirects(int value) { assert(value == HTTPC_DISABLE_FOLLOW_REDIRECTS); }
  bool begin(WiFiClientSecure&, const String&) {
    if (fakehttp::beginFailures) { --fakehttp::beginFailures; return false; }
    return true;
  }
  void addHeader(const char*, const String&) {}
  int POST(const String& body) {
    assert(!fakehttp::replies.empty());
    fakehttp::payloads.push_back(body);
    reply_ = fakehttp::replies.front(); fakehttp::replies.pop_front();
    fakehttp::advance(reply_.headerMs);
    return reply_.code;
  }
  String getString() { fakehttp::advance(reply_.bodyMs); reply_.bodyMs = 0; return reply_.body; }
  void end() {}
 private:
  fakehttp::Reply reply_{0, 0, 0, ""};
};
