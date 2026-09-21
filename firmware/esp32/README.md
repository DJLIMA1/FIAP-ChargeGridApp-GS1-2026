# Firmware ESP32 e painel ChargeGrid

O target base continua disponível com `pio run -d firmware/esp32 -e esp32dev`. Para a **Waveshare ESP32-S3-Touch-LCD-7** sem B, use:

```bash
pio run -d firmware/esp32 -e waveshare_panel_ui
```

O target usa Arduino 3.1.1, LVGL 8.4, flash DIO/40 MHz, 16 MB e PSRAM OPI. `waveshare_panel_demo` é um alias compatível e gera a mesma imagem unificada.

No primeiro boot, o painel mostra **Configure este ponto**, sem dados fictícios. Segure o logo ChargeGrid por aproximadamente 5 segundos para abrir a manutenção, digite SSID 2,4 GHz, senha e chave individual e toque em **Salvar e conectar**. Senha/chave ficam mascaradas e não entram no log. **Limpar rede** preserva a identidade. Trocar a identidade é recusado durante sessão pendente.

O Wi-Fi associa mesmo sem uma chave de dispositivo. A sincronização com a API continua bloqueada até que rede e chave estejam configuradas.

A API é fixa em `https://chargegrid-api-preview-djlima1s-projects.vercel.app`, validada com GTS Root R1. O protocolo continua em `POST /v1/devices/sync`, com START somente por comando do servidor e parada local `end_reason=requested`.

O painel é uma bancada simulada: não aciona relé ou carregador e não mede um veículo. Mesmo no modo integrado, os dados vêm de `SimulatedSensors` e aparecem identificados como simulados.

O firmware `0.2.0` usa o mesmo vermelho e superfícies escuras do app, status legíveis, contagem de reserva arredondada para cima e botão **Encerrar recarga** de 52 px. O limite de custo corta a integração de energia no instante autorizado, inclusive durante bloqueio de uma chamada HTTP. Alterar/limpar rede é bloqueado durante reserva ou recarga; trocar identidade também exige ausência de sessão pendente e reinicia apenas os contadores de comandos da identidade antiga.

Validação local do controlador e da tela LVGL reais (sem abrir serial):

```bash
python tools/validate_firmware.py
```

Execute a partir da raiz do repositório após compilar o target. Os testes geram sete frames em `tmp/panel-validation` e exercitam autorização, replay, watchdog, custo, parada por toque, contagem regressiva e teclado. Dependências: clang/clang++ e bibliotecas instaladas pelo PlatformIO.

Diagnóstico serial a 115200: `CG_STATUS` mostra estado, rede, HTTP e energia sem segredos; `CG_STOP` solicita a mesma parada segura do botão. `CG_KEY` recebe a chave na linha seguinte sem eco e preserva o Wi-Fi. O helper `tools/panel_serial.py` aceita `--action status|stop|key|boot|screen`; para provisionar, use `--action key --key-file <arquivo-local-protegido> --port <porta>`. Não existe comando serial START. `--action screen` captura o framebuffer físico do LCD em PPM 400 × 240, somente em `idle` e sem sessão pendente. A transmissão dura cerca de 17 segundos; ela é recusada durante reserva ou recarga e não permite START.

O helper precisa de `pyserial` (já incluído no ambiente PlatformIO). No macOS, alguns drivers CH340 reiniciam a placa ao abrir a porta: abra **antes** do fluxo de recarga e mantenha `--action live --seconds 7200` durante a validação. Esse modo aceita `status`, `stop`, `screen` e `quit` pelo stdin, sem reabrir a porta. Abrir/fechar ferramentas seriais no meio de uma recarga pode interrompê-la; um reboot nunca retoma automaticamente uma sessão.

Veja [docs/waveshare-panel.md](../../docs/waveshare-panel.md) para o fluxo completo e [builds/chargegrid-waveshare-7.zip](../../builds/chargegrid-waveshare-7.zip) para os componentes, imagem inicial e hashes. Em atualizações, grave os componentes por offsets para preservar o NVS; a imagem mesclada em `0x0` é indicada somente para instalação inicial.
