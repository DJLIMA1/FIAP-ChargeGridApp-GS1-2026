#pragma once
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
using std::min;
using std::max;
class String : public std::string {
 public:
  using std::string::string;
  String(const std::string& value) : std::string(value) {}
  explicit String(unsigned value) : std::string(std::to_string(value)) {}
  bool endsWith(const char* suffix) const { return size() >= strlen(suffix) && compare(size()-strlen(suffix),strlen(suffix),suffix)==0; }
  void remove(size_t from) { erase(from); }
  friend String operator+(const String& left, uint8_t right) {
    return String(static_cast<const std::string&>(left) + std::to_string(right));
  }
};
extern unsigned long testMillis;
inline unsigned long millis() { return testMillis; }
inline void delay(unsigned long ms) { testMillis = uint32_t(testMillis + ms); }
