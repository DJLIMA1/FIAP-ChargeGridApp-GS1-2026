# Firmware ESP32 e painel ChargeGrid

O target base continua disponível com `pio run -d firmware/esp32 -e esp32dev`. Para a **Waveshare ESP32-S3-Touch-LCD-7** sem B, use:

```bash
pio run -d firmware/esp32 -e waveshare_panel_ui
```

O target usa Arduino 3.1.1, LVGL 8.4, flash DIO/40 MHz, 16 MB e PSRAM OPI. `waveshare_panel_demo` é um alias compatível e gera a mesma imagem unificada.

No primeiro boot, o painel mostra **Configure este ponto**, sem dados fictícios. Segure o logo ChargeGrid por aproximadamente 5 segundos para abrir a manutenção, digite SSID 2,4 GHz e senha e toque em **Salvar e conectar**. A senha fica mascarada e não entra no log. A chave individual é provisionada separadamente via USB (`CG_KEY`); não aparece na tela. **Limpar rede** preserva a identidade. Trocar a identidade é recusado durante sessão pendente.

O Wi-Fi associa mesmo sem uma chave de dispositivo. A sincronização com a API continua bloqueada até que rede e chave estejam configuradas.

Quando a API envia `presence_code`, o painel mostra o código `#F` do posto, a contagem regressiva e a barra de validade. Com uma API anterior, o código público do ponto continua visível até a atualização do servidor.

A API é fixa em `https://chargegrid-api-preview-djlima1s-projects.vercel.app`, validada com GTS Root R1. O protocolo continua em `POST /v1/devices/sync`, com START somente por comando do servidor e parada local `end_reason=requested`.

O painel é uma bancada simulada: não aciona relé ou carregador e não mede um veículo. Mesmo no modo integrado, os dados vêm de `SimulatedSensors` e aparecem identificados como simulados.

O firmware `0.2.0` usa o mesmo vermelho e superfícies escuras do app, status legíveis, contagem de reserva arredondada para cima e botão **Encerrar recarga** de 52 px. O limite de custo corta a integração de energia no instante autorizado, inclusive durante bloqueio de uma chamada HTTP. Alterar/limpar rede é bloqueado durante reserva ou recarga; trocar identidade também exige ausência de sessão pendente e reinicia apenas os contadores de comandos da identidade antiga.

Validação local do controlador e da tela LVGL reais (sem abrir serial):

```bash
python tools/validate_firmware.py
```

Execute a partir da raiz do repositório após compilar o target. Os testes geram sete frames em `tmp/panel-validation` e exercitam autorização, replay, watchdog, custo, parada por toque, contagem regressiva e teclado. Dependências: clang/clang++ e bibliotecas instaladas pelo PlatformIO.

Diagnóstico serial a 115200: `CG_STATUS` mostra estado, rede, HTTP e energia sem segredos; `CG_STOP` solicita a mesma parada segura do botão. `CG_KEY` recebe a chave na linha seguinte sem eco e preserva o Wi-Fi. `CG_WIFI` pede SSID e senha (sem eco) e conecta. Atalho no Mac: `tools/cg-wifi "Nome da rede" senha` (detecta a porta; detalhes em `docs/waveshare-panel.md`). O helper `tools/panel_serial.py` aceita `--action status|stop|key|boot|screen|wifi`; para provisionar, use `--action key --key-file <arquivo-local-protegido> --port <porta>`. Não existe comando serial START. `--action screen` captura o framebuffer físico do LCD em PPM 400 × 240, somente em `idle` e sem sessão pendente. A transmissão dura cerca de 17 segundos; ela é recusada durante reserva ou recarga e não permite START.

O helper precisa de `pyserial` (já incluído no ambiente PlatformIO). No macOS, alguns drivers CH340 reiniciam a placa ao abrir a porta: abra **antes** do fluxo de recarga e mantenha `--action live --seconds 7200` durante a validação. Esse modo aceita `status`, `stop`, `screen` e `quit` pelo stdin, sem reabrir a porta. Abrir/fechar ferramentas seriais no meio de uma recarga pode interrompê-la; um reboot nunca retoma automaticamente uma sessão.

Veja [docs/waveshare-panel.md](../../docs/waveshare-panel.md) para o fluxo completo e [builds/chargegrid-waveshare-7-0.3.6.zip](../../builds/chargegrid-waveshare-7-0.3.6.zip) para o firmware, componentes de recuperação e hashes. Em atualizações, grave somente `firmware.bin` em `0x10000` para preservar o NVS.

## Firmware 0.7.0

Versão única (`CHARGEGRID_FIRMWARE_VERSION` em `include/runtime.h`, enviada no sync e mostrada no `CG_STATUS`). Tudo é aditivo; o fluxo anterior continua igual quando a API não manda os campos novos:

- **Potência ao vivo:** o sync declara `capabilities: ["set_power_v1"]`, `applied_power_w` e `charger` (`esp32_bench`, `simulated`, 1.400–7.200 W, passo 100 W). `SET_POWER` aplica o limite (arredonda para baixo no passo; 0 W pausa sem encerrar) e confirma com `applied_power_w`. START usa `power_limit_w` quando presente (inclusive 0); sem ele, `max_power_kw` como antes. A tela mostra a potência aplicada confirmada pela API e o motivo curto.
- **Pagamento pelo QR (teste):** com `connector.kiosk_url`, a tela Pronto mostra o QR "Sem o app? Pague aqui · TESTE" e o estado de `connector.payment`.
- **Permanência:** START com `parameters.overstay` mantém o carro conectado depois de parar e mostra **Desconectar**, a tolerância (contagem local) e a taxa informada pela API. Reboot volta desconectado.
- **API anterior:** se o sync receber 422 (campos novos recusados), o painel reenvia no formato 0.6 e segue como carga fixa; tenta os campos novos de novo a cada 10 min, só ocioso.

Pré-visualização das telas do totem no host: `python firmware/esp32/preview/render.py --output tmp/panel-preview` (LVGL real, sem serial/hardware). Veja "Redesign do totem" em `docs/waveshare-panel.md`.
