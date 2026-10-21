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

## Firmware 0.8.0 — totem de autoatendimento

Versão única `0.8.0` (`include/runtime.h`, sync e `CG_STATUS`, que agora também mostra `kiosk=off|simulated|stripe` e `kiosk_order=present|none`). Contrato: seção "Totem 0.8.0" de `docs/esp32-protocol.md`. Tudo é aditivo: sem `connector.kiosk` no sync (totem desligado no posto ou API anterior) ou com `404` em `/v1/devices/kiosk/offer`, as telas são as da 0.7.0, pixel a pixel (teste `--compare-panel`).

- **Lógica separada da tela:** `src/kiosk_flow.cpp` é C++17 puro (sem Arduino/LVGL): estados T0–T8/TE, eventos (toque, tecla, tempo, fatos do sync, resultado da API), saída `KioskView` e um `ApiRequest` por vez. O método de pagamento vem do servidor (`simulated` na conta em Modo apresentação, `stripe` na oficial); o totem nunca escolhe nem paga sozinho. Nada liga sem o `START` normal do sync.
- **Rede:** `src/kiosk_api.cpp` executa `deviceRequest()` no laço principal, na mesma conexão TLS keep-alive do sync (`deviceHttpBegin`/`deviceHttpEnd` em `api_client.cpp`), timeout de 3 s, `Idempotency-Key` (`ko-…` por orçamento; `pay-<id>`/`cancel-<id>` derivadas do pedido, seguras para repetir) e **nunca durante uma recarga**.
- **Retomada:** o id do pedido aberto fica na NVS (`kord`) desde `POST /orders`; após queda de rede ou reboot a tela "Verificando pagamento" segue `kiosk_order` do sync (ou `GET /orders/{id}`) e redesenha o QR pelo `payment.qr_url`.
- **Encerrar** continua local (`requestLocalSafeStop()`), com confirmação (T7) — inclusive para a recarga iniciada pelo app quando o totem está ligado. Com o totem desligado o botão Encerrar para na hora, como antes.
- **Telas provisórias** (`include/ui/tokens.h`, `include/ui/strings_ptbr.h`, `src/ui/widgets.cpp`, `src/ui/router.cpp`, `src/ui/view_*.cpp`): alvos ≥ 72 px, teclas 104 × 72, textos fixos só com glifos das fontes atuais (sem "—", "…", "·" nos títulos Bold; apagar = `LV_SYMBOL_BACKSPACE` da Montserrat 28). Toques entram numa fila sob `portMUX` (núcleo 0) e são entregues ao fluxo no `panelTick()` (núcleo 1). O design troca só esses arquivos.
- **Memória:** criação preguiçosa; cada tela do totem é criada ao entrar e apagada ao sair, e enquanto uma tela do totem está aberta as telas atuais são liberadas e reconstruídas ao voltar (pool de 64 KB inalterado). Pico medido no host (64 bits, superestima a placa): telas do totem 20–35 KB (≤ 53 % do pool, teclado é o maior); tela Pronto da 0.7.0 ~54 KB. Relatório em `tmp/panel-validation/kiosk-memory.txt`.
- **Pool LVGL na PSRAM (opcional, não validado em placa):** env `waveshare_panel_ui_psram_pool` (192 KB via `heap_caps_malloc(MALLOC_CAP_SPIRAM)`, `include/lvgl_psram_pool.h`). O padrão continua o pool interno de 64 KB: sem teste na placa, o risco do RGB ler o framebuffer da mesma PSRAM (banda, deriva da imagem) não compensa. Medir com `lv_mem_monitor` e observar a imagem antes de adotar.
- Flag de compilação `CHARGEGRID_KIOSK` (só no env `waveshare_panel_ui`); `esp32dev` só lê os blocos do sync.

Validação de host: `python tools/validate_firmware.py --decode-qr` compila `tools/tests/kiosk_flow_test.cpp` (fluxo nos dois modos, com sanitizers) e `tools/tests/firmware_behavior.cpp` (capturas `kiosk-*.ppm`, QR do pedido e do recibo decodificados, cobertura de glifos, memória por tela).

## Carregador externo GoodWe HCA G2 (opcional)

Com `connector.charger_link` no sync, a tela vira mestre Modbus TCP de um carregador HCA G2 simulado num ESP32 DevKit (`firmware/goodwe-hca-sim`, guia em `docs/carregador-hca-simulado.md`, contrato na seção "Carregador externo" de `docs/esp32-protocol.md`). START/STOP/SET_POWER viram escritas nos registradores e o ACK `applied` só sai depois da releitura; a potência e a energia vêm do 10015 lido a cada ~1 s; carregador sumido por 5 s na recarga → parada segura `device_fault`. Sem o bloco, nada muda (frames do painel idênticos no `--compare-panel`).

- `src/charger_link.cpp` (C++ puro, testado em `tools/tests/charger_link_test.cpp` e no controlador real em `firmware_behavior.cpp`) e `src/charger_modbus_esp32.cpp` (WiFiClient, uma conexão, timeouts de 400/300 ms, mDNS `cg-hca-<n>.local` em cache). Mapa e Modbus TCP em `firmware/shared/hca_g2` (`lib_extra_dirs`).
- Serial: `CG_CHARGER` (estado do link e leitura na hora) e `CG_CHARGER_IP <ip>|clear` (IP fixo na NVS quando o mDNS não funciona).
