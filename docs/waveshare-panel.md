# Painel do posto — Waveshare ESP32-S3-Touch-LCD-7

O profile é exclusivo da **ESP32-S3-Touch-LCD-7** sem B, 800 × 480. Usa Arduino 3.1.1, LVGL 8.4, `ESP32_Display_Panel` 1.0.4, flash DIO a 40 MHz, 16 MB e PSRAM OPI. O modelo 7B é diferente e não deve receber esta imagem.

O firmware é operacional e reflete somente estados recebidos da API. Sem configuração, mostra **Configure este ponto**, sem código ou números fictícios. SoC, energia, potência e custo ficam `--` até existir sessão sincronizada. Este MVP ainda usa `SimulatedSensors` durante sessões e identifica a origem discretamente como `Bancada • dados simulados`; não mede um carro nem aciona relé ou carregador. START continua autorizado somente pelo servidor.

## Compilar e gravar

```bash
pio run -d firmware/esp32 -e waveshare_panel_ui
```

O alias `waveshare_panel_demo` gera a mesma imagem. O pacote em [`builds/chargegrid-waveshare-7.zip`](../builds/chargegrid-waveshare-7.zip) contém componentes, imagem mesclada e hashes. Para atualizar uma placa configurada, grave os componentes nos offsets documentados no README do pacote; isso preserva o NVS. Use a imagem mesclada em `0x0` somente na instalação inicial, pois ela preenche intervalos e pode substituir configuração e estado existentes.

## Configurar pelo touch

1. Segure o logo ChargeGrid por cerca de 5 segundos.
2. Digite SSID de Wi-Fi 2,4 GHz, senha e a chave individual provisionada no app em **Conta → Operador aprovado → Posto → Ponto**.
3. Toque em **Salvar e conectar**; o painel reinicia no modo integrado.

Rede e identidade são independentes: o painel pode associar ao Wi-Fi sem chave, mas só inicia a sincronização autenticada depois que uma chave individual estiver configurada.

Senha e chave são mascaradas, nunca reaparecem preenchidas e não são registradas no serial. Uma chave vazia preserva a chave existente. **Limpar rede** exige confirmação e remove apenas SSID/senha. Salvar/limpar a rede é bloqueado durante reserva ou recarga. Depois de uma parada, a rede pode ser corrigida para permitir reconciliação, mas a identidade não pode ser trocada enquanto existe sessão pendente.

Configuração de bancada fica no namespace NVS `cg-config`, separado do estado idempotente do protocolo em `chargegrid`. A tela escondida não é autenticação e o NVS não é armazenamento criptografado.

A origem é fixa em `https://chargegrid-api-preview-djlima1s-projects.vercel.app`, sem `/v1`; o cliente adiciona esse caminho. TLS usa GTS Root R1, válido até 2036, e não usa conexão insegura nem segue redirecionamentos. Os estados visuais distinguem configuração pendente, Wi-Fi desconectado, aguardando API, chave inválida e API autenticada.

## Validação

Na placa física, o firmware `0.2.0` iniciou em DIO/40 MHz, confirmou CH422G, LCD, GT911 ID 911 e `Board begin success`. A atualização por offsets preservou o NVS e reconectou à rede existente. O diagnóstico serial distingue identidade ausente de uma chave rejeitada pela API.

Após provisionar a identidade individual pela API, o painel físico autenticou com HTTP 200 e permaneceu `idle`, com potência/energia zero. A API na região São Paulo (`gru1`), próxima ao banco, eliminou os timeouts de 3 segundos observados antes. Uma captura serial do framebuffer real comprova a renderização no LCD; ela é liberada somente sem reserva/sessão ativa.

Também foi exercitado o fluxo integrado com o aplicativo real e o ponto `CG-PAINEL-01`: reserva pelo app → `reserved` no ESP32 → início pelo app → `charging`, com energia crescente e 7.200 W simulados → parada solicitada pelo app → `idle`, potência zero e sessão reconciliada. Uma segunda sessão iniciou diretamente pelo app, sem reserva, e foi encerrada pelo comando local `CG_STOP`, que usa a mesma função segura do botão: a placa relatou `stopped/power_w=0` e depois `idle/session=none/HTTP 200`. A porta serial foi fechada somente nesse estado seguro. Os testes de toque no botão e teclado executam eventos LVGL no host; não representam um toque humano no vidro.

`python tools/validate_firmware.py` compila os próprios arquivos `charging_controller.cpp`, `sensors.cpp` e `panel_ui.cpp` para um framebuffer LVGL 800 × 480, com interfaces de hardware substituídas. Exercita START autorizado/rejeitado, comandos repetidos, proibição de retomar sessão parada, watchdog de 45 s, teto de custo, evento de toque para encerrar e teclas `q`/backspace. Gera telas de disponível, reservado, recarga, encerrado, chave inválida, configuração pendente e manutenção. Este teste valida a renderização do código, sem representar uma fotografia do LCD físico.

No pitch integrado, reserve e inicie pelo app; o painel apenas reflete comandos do servidor. **Encerrar recarga** encerra uma sessão ativa com `end_reason=requested`.
