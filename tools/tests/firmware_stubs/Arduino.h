#pragma once
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <ctime>
using String = std::string;
using std::min;
using std::max;
template<class T> T constrain(T value, T low, T high) { return min(high, max(low, value)); }
extern unsigned long testMillis;
inline unsigned long millis() { return testMillis; }
struct SerialStub { void println(const char*) {} };
inline SerialStub Serial;
using portMUX_TYPE = int;
#define portMUX_INITIALIZER_UNLOCKED 0
#define taskENTER_CRITICAL(x) (void)(x)
#define taskEXIT_CRITICAL(x) (void)(x)
#define pdMS_TO_TICKS(x) (x)
inline void vTaskDelay(int) {}
inline void xTaskCreatePinnedToCore(void(*)(void*), const char*, int, void*, int, void*, int) {}
