#ifdef CHARGEGRID_LVGL_PSRAM_POOL
#include <esp_heap_caps.h>
#include <stdio.h>
#include "lvgl_psram_pool.h"

void* chargegrid_lvgl_pool_alloc(size_t size) {
  void* pool = heap_caps_malloc(size, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!pool) {
    // Sem PSRAM livre: tenta a SRAM (192 KB raramente cabem; o LVGL para no assert).
    printf("[lvgl] PSRAM pool of %u bytes unavailable; trying internal RAM\n", (unsigned)size);
    pool = heap_caps_malloc(size, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
  }
  return pool;
}
#endif
