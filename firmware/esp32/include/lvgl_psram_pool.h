#pragma once
// Pool do LVGL na PSRAM (só no env waveshare_panel_ui_psram_pool, NÃO validado em placa).
// lv_mem.c chama LV_MEM_POOL_ALLOC(LV_MEM_SIZE) uma vez, em lv_init().
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif
void* chargegrid_lvgl_pool_alloc(size_t size);
#ifdef __cplusplus
}
#endif
