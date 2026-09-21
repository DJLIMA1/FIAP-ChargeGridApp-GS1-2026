# Componentes de terceiros do painel

- `src/lvgl_v8_port.cpp` e `include/lvgl_v8_port.h`: template `simple_port` do [ESP32_Display_Panel 1.0.4](https://github.com/esp-arduino-libs/ESP32_Display_Panel/tree/v1.0.4), Espressif Systems, licença CC0-1.0. Os cabeçalhos SPDX originais foram preservados.
- `include/esp_panel_*_conf.h` e `include/esp_utils_conf.h`: templates de configuração do mesmo projeto, com seleção local da placa `BOARD_WAVESHARE_ESP32_S3_TOUCH_LCD_7`; licenças e cabeçalhos SPDX originais preservados.
- [ESP32_Display_Panel 1.0.4](https://github.com/esp-arduino-libs/ESP32_Display_Panel/tree/v1.0.4): biblioteca Apache-2.0, obtida pelo PlatformIO com suas dependências declaradas.
- [LVGL 8.4.0](https://github.com/lvgl/lvgl/tree/v8.4.0): biblioteca MIT, obtida pelo PlatformIO.

O ícone embarcado foi derivado do ativo do próprio projeto `apps/mobile/assets/icon.png` e permanece sob os termos do projeto ChargeGrid.
