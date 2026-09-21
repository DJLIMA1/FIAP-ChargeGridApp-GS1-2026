#pragma once
#include "Arduino.h"
struct Preferences {
  void putUInt(const char*, unsigned int) {}
  void putString(const char*, const String&) {}
  void putFloat(const char*, float) {}
};
