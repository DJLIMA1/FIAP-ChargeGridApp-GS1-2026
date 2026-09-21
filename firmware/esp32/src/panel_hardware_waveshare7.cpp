#ifdef CHARGEGRID_PANEL_ENABLED

#include <Arduino.h>
#include <esp_display_panel.hpp>
#include "lvgl_v8_port.h"

using namespace esp_panel::board;
using namespace esp_panel::drivers;

namespace {
Board* board = nullptr;
}

bool chargegridPanelHardwareSetup() {
  Serial.println("[panel] Waveshare ESP32-S3-Touch-LCD-7 800x480");
  board = new Board();
  if (!board || !board->init()) return false;

  // O bounce buffer reduz drift no RGB quando Wi-Fi e PSRAM estão ativos.
  auto* lcd = board->getLCD();
  auto* bus = lcd ? lcd->getBus() : nullptr;
  if (lcd && bus && bus->getBasicAttributes().type == ESP_PANEL_BUS_TYPE_RGB) {
    static_cast<BusRGB*>(bus)->configRGB_BounceBufferSize(lcd->getFrameWidth() * 10);
  }
  if (!board->begin()) return false;
  return lvgl_port_init(board->getLCD(), board->getTouch());
}

bool chargegridPanelCapture() {
  auto* lcd = board ? board->getLCD() : nullptr;
  auto* frame = lcd ? static_cast<uint16_t*>(lcd->getFrameBufferByIndex(0)) : nullptr;
  if (!frame) return false;
  constexpr size_t width = 400, height = 240, bytes = width * height * sizeof(uint16_t);
  auto* copy = static_cast<uint16_t*>(heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (!copy) return false;
  if (!lvgl_port_lock(100)) { heap_caps_free(copy); return false; }
  for (size_t y = 0; y < height; ++y)
    for (size_t x = 0; x < width; ++x) copy[y * width + x] = frame[(y * 2) * 800 + x * 2];
  lvgl_port_unlock();
  Serial.printf("CG_FRAME_RGB565 %u %u %u\n", (unsigned)width, (unsigned)height, (unsigned)bytes);
  Serial.write(reinterpret_cast<uint8_t*>(copy), bytes);
  Serial.flush();
  Serial.println("\nCG_FRAME_END");
  heap_caps_free(copy);
  return true;
}

#endif
