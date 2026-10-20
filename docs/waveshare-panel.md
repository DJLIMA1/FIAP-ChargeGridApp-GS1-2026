# Painel do posto — Waveshare ESP32-S3-Touch-LCD-7

O profile é exclusivo da **ESP32-S3-Touch-LCD-7** sem B, 800 × 480. Usa Arduino 3.1.1, LVGL 8.4, `ESP32_Display_Panel` 1.0.4, flash DIO a 40 MHz, 16 MB e PSRAM OPI. O modelo 7B é diferente e não deve receber esta imagem.

O firmware reflete somente estados recebidos da API. A tela principal apresenta disponibilidade, código público, instruções simples, reserva com prazo e, durante a sessão, energia, valor estimado, tempo restante e botão Encerrar. Informações de rede e identidade ficam na tela de manutenção, acessada ao segurar a marca; a interface do cliente não mostra potência nem telemetria de bancada; o SoC do carro só aparece durante/ao fim da sessão quando a API o informa (ver abaixo). Este MVP ainda usa `SimulatedSensors` durante sessões: não mede um carro nem aciona relé ou carregador. START continua autorizado somente pelo servidor.

## Compilar e gravar

```bash
pio run -d firmware/esp32 -e waveshare_panel_ui
```

O alias `waveshare_panel_demo` gera a mesma imagem. O pacote atual é `builds/chargegrid-waveshare-7-0.3.5.zip`. Para atualizar uma placa configurada, grave **somente firmware.bin em 0x10000**, com ponto ocioso e nenhuma reserva/sessão pendente. Não use `erase_flash` nem imagem mesclada: preserve NVS, identidade, Wi-Fi e diário de sessão.

## Configurar pelo touch

1. Segure o logo ChargeGrid por cerca de 5 segundos.
2. Digite SSID de Wi-Fi 2,4 GHz e senha. A chave individual já vem provisionada de fábrica; deixe vazia para preservá-la. Manutenção de equipamentos legados fica em **Conta → Meus equipamentos e postos → Posto → Ponto**. A partir do firmware 0.2.1, deixe a senha vazia para redes abertas; isso remove a senha anterior, sem alterar a identidade do dispositivo. Redes abertas não protegem o enlace Wi-Fi, mas a comunicação com a API continua usando HTTPS com certificado validado.
3. Toque em **Salvar e conectar**; o painel reinicia no modo integrado.

## Configurar o Wi-Fi pelo terminal (USB)

Com o painel ligado ao Mac por USB, na raiz do repositório:

```bash
tools/cg-wifi "Nome da rede" senha
```

Sem a senha (`tools/cg-wifi "Nome da rede"`), ela é pedida sem eco e não fica no histórico do shell. A porta (`/dev/cu.wchusbserial*`, `usbserial*`, `usbmodem*`) é detectada sozinha; com mais de uma placa, use `CG_PORT=/dev/cu.xxx tools/cg-wifi ...`. O script usa o Python do `.venv` (precisa de `pyserial`) e chama `tools/panel_serial.py --action wifi --ssid ... [--password ...]`, que envia `CG_WIFI`, responde SSID e senha e termina com o IP obtido ou com o erro do firmware (rede não encontrada, senha errada, bloqueio durante reserva/recarga). Rede 2,4 GHz, SSID até 32 bytes e senha até 64. A rede fica salva no NVS e a identidade é preservada. Validado em 19/10/2026 na placa física: a rede `S23 Ultra de Murillo` conectou e a placa sincronizou com HTTP 200.

Rede e identidade são independentes: o painel pode associar ao Wi-Fi sem chave, mas só inicia a sincronização autenticada depois que uma chave individual estiver configurada.

O suporte a redes abertas do firmware 0.2.1 foi validado na placa física: atualização somente em `0x10000`, configuração por serial com senha vazia, chave existente preservada e sincronização HTTP 200. Após reiniciar, o painel reconectou automaticamente e permaneceu `idle`, sem sessão e com potência zero. Os testes de host cobrem senha anterior removida, falha de gravação, SSID obrigatório e envio do formulário com senha vazia.

Senha e chave são mascaradas, nunca reaparecem preenchidas e não são registradas no serial. Uma chave vazia preserva a chave existente. **Limpar rede** exige confirmação e remove apenas SSID/senha. Salvar/limpar a rede é bloqueado durante reserva ou recarga. Depois de uma parada, a rede pode ser corrigida para permitir reconciliação, mas a identidade não pode ser trocada enquanto existe sessão pendente.

Configuração de bancada fica no namespace NVS `cg-config`, separado do estado idempotente do protocolo em `chargegrid`. A tela escondida não é autenticação e o NVS não é armazenamento criptografado.

A origem é fixa em `https://chargegrid-api-preview-djlima1s-projects.vercel.app`, sem `/v1`; o cliente adiciona esse caminho. TLS usa GTS Root R1, válido até 2036, e não usa conexão insegura nem segue redirecionamentos. Os estados visuais distinguem configuração pendente, Wi-Fi desconectado, aguardando API, chave inválida e API autenticada.

## Validação

Na placa física, o firmware `0.2.0` iniciou em DIO/40 MHz, confirmou CH422G, LCD, GT911 ID 911 e `Board begin success`. A atualização por offsets preservou o NVS e reconectou à rede existente. O diagnóstico serial distingue identidade ausente de uma chave rejeitada pela API.

Após provisionar a identidade individual pela API, o painel físico autenticou com HTTP 200 e permaneceu `idle`, com potência/energia zero. A API na região São Paulo (`gru1`), próxima ao banco, eliminou os timeouts de 3 segundos observados antes. Uma captura serial do framebuffer real comprova a renderização no LCD; ela é liberada somente sem reserva/sessão ativa.

Também foi exercitado o fluxo integrado com o aplicativo real e o ponto `CG-PAINEL-01`: reserva pelo app → `reserved` no ESP32 → início pelo app → `charging`, com energia crescente e 7.200 W simulados → parada solicitada pelo app → `idle`, potência zero e sessão reconciliada. Uma segunda sessão iniciou diretamente pelo app, sem reserva, e foi encerrada pelo comando local `CG_STOP`, que usa a mesma função segura do botão: a placa relatou `stopped/power_w=0` e depois `idle/session=none/HTTP 200`. A porta serial foi fechada somente nesse estado seguro. Os testes de toque no botão e teclado executam eventos LVGL no host; não representam um toque humano no vidro.

`python tools/validate_firmware.py` compila os próprios arquivos `charging_controller.cpp`, `sensors.cpp` e `panel_ui.cpp` para um framebuffer LVGL 800 × 480, com interfaces de hardware substituídas. Exercita START autorizado/rejeitado, comandos repetidos, proibição de retomar sessão parada, watchdog de 45 s, teto de custo, evento de toque para encerrar e teclas `q`/backspace. Gera telas de disponível, reservado, recarga, encerrado, chave inválida, configuração pendente e manutenção. Este teste valida a renderização do código, sem representar uma fotografia do LCD físico.

No pitch integrado, reserve e inicie pelo app; o painel apenas reflete comandos do servidor. **Encerrar recarga** encerra uma sessão ativa com `end_reason=requested`.

## Vinculação de fábrica e validação 0.3.0

`tools/provision_point.py` cria um ponto novo sem dono, inativo, com chave do dispositivo e token de propriedade independentes. O JSON e SVG gerados são privados. Provisione a chave com `CG_KEY`; para o token, envie `CG_CLAIM`, aguarde `Claim token (input hidden):` e envie exatamente os 43 caracteres base64url. Nunca coloque a chave da API no QR. O comando recusa equipamentos já vinculados ou fora de idle/sem sessão.

O QR aparece também offline, acompanhado da opção de configurar Wi-Fi. O vendedor usa **Escanear QR da tela** no APK; após confirmação, configura posto/ponto e ativa ambos. Quando a API informa `owned: true`, o firmware persiste a propriedade e remove o token/QR. Não existe transferência de dono por reescaneamento. Unidades legadas mantêm seus proprietários e não passam a exibir QR de reivindicação.

O app 0.3.2 abre um assistente após a leitura: **1. localização** (nome, endereço e coordenadas, com busca opcional), **2. ponto e tarifa** (conector, potência, preço por kWh e duração máxima), **3. revisão e publicação**. As duas primeiras etapas são salvas na API; sair antes da última mantém o ponto inativo, identificado como configuração pendente em **Meus postos**. A publicação ativa primeiro o ponto e depois a estação; se a segunda requisição falhar, a estação permanece privada e a publicação pode ser tentada de novo. Um ESP32 offline pode ser publicado, mas só ficará disponível aos consumidores quando reconectar. O botão Voltar do Android retorna à etapa anterior sem perder o que já foi salvo.

Em 21/09/2026, o firmware 0.3.0 foi gravado na placa física apenas em 0x10000. A rede aberta `beleza` e a identidade foram preservadas. O teste `tools/qa_panel_reboot.py` confirmou: idle/HTTP 200 → reserva confirmada → reset via RTS com marcador de boot ROM → reserved e mesmo `expires_at` → cancelamento → idle e API disponível. Nenhuma recarga foi iniciada nesse teste.

`python tools/validate_firmware.py --decode-qr` executa o controlador real no host, renderiza 12 telas LVGL e decodifica os QR offline/online com Pillow/zxing-cpp; verifica também ausência do QR após vinculação e em equipamento legado. Isso não substitui leitura por câmera Android física, ainda não testada.

Em 21/09/2026, o firmware 0.3.1 foi compilado e gravado na placa física apenas em `0x10000` após confirmação de `available=true`, sem reserva ou sessão ativa. O hash da gravação foi verificado pelo esptool; a placa reiniciou com a rede `beleza` e a identidade preservadas, retornando `state=idle`, `wifi=connected`, `synced=yes`, `HTTP 200`, `session=none`. A mudança evita invalidar controles LVGL quando o snapshot não mudou: no teste de host, um refresh ocioso repetido gerou zero flushes, enquanto uma transição real gerou redraw. Ainda não foi feita uma medição instrumental de cintilação diretamente no LCD.

## Tela física pronta para primeira vinculação — 0.3.2

A unidade conectada ao Mac era legada e já possuía proprietário; por isso o QR não aparecia apesar de o fluxo existir no app. Após autorização explícita, o firmware 0.3.2 foi gravado somente em `0x10000`. O comando local `CG_MIGRATE`, disponível apenas por USB e após confirmação do código público, exigiu painel online, ocioso, sincronizado com HTTP 200 e sem sessão. Ele removeu a identidade antiga do NVS, preservando a rede Wi-Fi. Uma nova chave de dispositivo e um token de propriedade independentes foram então instalados de um artefato privado.

O novo ponto `CG-PAINEL-02` foi criado sem dono e inativo. O ponto físico anterior `CG-PAINEL-01` foi desativado e sua chave revogada; o posto de bancada e seu outro ponto permaneceram ativos, com histórico preservado. O framebuffer capturado diretamente do LCD mostrou o QR de vinculação, e um decodificador confirmou correspondência exata ao token privado sem expô-lo em arquivos versionados. O ESP32 sincronizou com a API em `idle`, Wi-Fi conectado, HTTP 200. Deixe o painel ligado nessa tela e, no app 0.3.2, entre como vendedor → **Meus postos** → **Escanear QR da tela** → conclua localização, tarifa e publicação. Após o vínculo, o QR desaparece do LCD.

O QR é uma credencial de propriedade; a captura da tela física e o `provisioning.json` ficam privados em `tmp/` e `/tmp`, respectivamente, e não entram no pacote de firmware nem no Git. Não execute `CG_MIGRATE` para uma unidade em produção sem antes preparar uma nova identidade e auditar o histórico.

## Redução das piscadas do LCD — 0.3.3

O usuário relatou piscadas ocasionais mesmo após a otimização que evitou redraws periódicos. O ESP32-S3 usava um framebuffer RGB; o LVGL escrevia nele enquanto o LCD o lia. O port agora usa o modo 3 recomendado pela biblioteca (`double-buffer` + `direct-mode`) e troca os buffers no VSYNC. O bounce buffer foi ampliado de 10 para 20 linhas para dar mais margem às transferências entre PSRAM e LCD durante o uso de Wi-Fi. A [documentação da Espressif](https://docs.espressif.com/projects/esp-idf/en/v5.3.1/esp32s3/api-reference/peripherals/lcd/rgb_lcd.html) descreve que atrasos de transferência nessa interface podem produzir flicker, mesmo com o framebuffer correto.

O firmware 0.3.3 compilou e passou em `tools/validate_firmware.py`. Foi gravado na placa física somente em `0x10000`, com hash conferido pelo esptool. O boot registrou `Avoid tearing is enabled, mode: 3`; depois, `state=idle`, Wi-Fi conectado, HTTP 200, sem sessão. A captura posterior do framebuffer mostrou a tela normal de `CG-PAINEL-02`, já vinculada. Em sete consultas ao longo de 30 segundos, a API confirmou o ponto com proprietário, ativo, online e disponível. Uma captura estática e logs não medem piscadas na luz emitida pelo LCD; a eliminação completa do sintoma ainda depende de observação visual prolongada da placa.

O pacote local é `builds/chargegrid-waveshare-7-0.3.3.zip` (SHA-256 `2fd48faea0634ecddcd42a90aeebd3ddacb92e54e1fa3ead00dc4ca05d0dfc15`). Não inclui NVS, chaves ou QR privado.

## Interface para o cliente — 0.3.4

A tela principal agora usa a marca vermelha com o símbolo de estação do login e mostra somente a próxima ação útil. Quando livre, exibe o código público e três passos curtos; quando reservada, prioriza o prazo da reserva; durante a sessão, mostra energia, custo estimado, tempo restante e Encerrar; e, se estiver indisponível, comunica isso sem mensagens de infraestrutura. O QR privado aparece somente na vinculação de fábrica para o vendedor. O rodapé de demonstração foi removido a pedido, mas a natureza simulada dos sensores permanece documentada aqui e no app.

`tools/generate_brand_assets.py` regenera o ícone Android, a abertura do app e o bitmap RGB565 do painel a partir de `apps/mobile/assets/brand_mark.svg`. O glyph é o mesmo `EV_STATION` usado pelo login. `tools/validate_firmware.py --decode-qr` valida os estados renderizados, a ausência de redraw sem mudança e a legibilidade/privacidade do QR.

Antes da gravação física, a API confirmou `CG-PAINEL-02` vinculado, publicado, online e disponível. A versão 0.3.4 foi gravada somente em `0x10000`, com hash verificado; NVS e rede `beleza` foram preservados. O boot registrou novamente `Avoid tearing is enabled, mode: 3` e o status serial mostrou `idle`, Wi-Fi conectado, HTTP 200 e nenhuma sessão. O framebuffer lido da placa exibe a nova tela e não contém o rodapé anterior. A captura do framebuffer não mede cintilação óptica; essa observação exige acompanhar o LCD aceso ao longo do tempo.

O pacote local `builds/chargegrid-waveshare-7-0.3.4.zip` tem SHA-256 `cc447520e93c0d79eb991148b4ee222cb42587f4958fccd8f1ef9ef245910e16` e contém somente binários, instruções e capturas sem segredo de vinculação.

## Restauração de fábrica — 0.3.5

O vendedor abre **Meus postos → Editar posto → Editar ponto / dispositivo → Restaurar ESP32 de fábrica**. O aplicativo pede confirmação e acompanha o comando até o equipamento responder. A API exige firmware 0.3.5 ou superior, equipamento online e ocioso, sem reserva nem recarga. Ao aceitar o pedido, desativa o ponto antigo; ele e seu histórico permanecem associados ao vendedor. Se o comando falhar ou expirar, o aplicativo mostra esse estado e permite tentar novamente.

O ESP32 gera localmente uma nova chave de API e um token privado de vinculação, persistindo-os antes de confirmar somente seus hashes à API. A API cria uma nova identidade de fábrica sem proprietário e revoga a credencial antiga na mesma transação. Depois da confirmação, o ESP32 apaga Wi-Fi, vínculo e diário operacional, reinicia e apresenta um QR novo. Se a resposta da confirmação se perder, o firmware verifica a identidade nova antes de concluir, evitando apagar as credenciais sem uma identidade válida no servidor. O novo QR deve ser escaneado pelo vendedor para configurar outro ponto.

O firmware 0.3.5 compilou e passou em `tools/validate_firmware.py --decode-qr`; a API passou nos testes com PostgreSQL descartável. Após a reconexão da placa, o estado serial mostrou 0.3.4, `idle`, Wi-Fi conectado, HTTP 200 e nenhuma sessão. Gravei somente `firmware.bin` em `0x10000`; o esptool verificou o hash. Após o reboot, a placa mostrou 0.3.5 com a identidade e o Wi-Fi preservados, `idle`, HTTP 200 e nenhuma sessão. O comando de restauração de fábrica **não** foi acionado na placa durante essa validação. O pacote `builds/chargegrid-waveshare-7-0.3.5.zip` tem SHA-256 `385b66419a8f0f814744730d271b7a03f15d8429725985058c8527b94cb26868` e não contém NVS nem segredos.

### Recuperação física após a primeira tentativa

O primeiro pedido pelo app foi aceito, mas a confirmação do ESP32 retornou erro 500: o papel `chargegrid_api` tinha apenas `SELECT, UPDATE` em `device_claims`, enquanto a nova identidade exige `INSERT`. A migração `5e92acb01877` adiciona somente esse privilégio. Ela foi testada em PostgreSQL descartável e aplicada no banco do projeto; a revisão e a permissão efetiva foram conferidas.

A pedido do proprietário, a placa foi restaurada diretamente antes da correção da API: conferi `idle`/sem sessão, salvei uma cópia privada temporária da NVS e apaguei somente sua partição `0x9000`–`0xdfff`. O boot confirmou Wi-Fi e identidade ausentes. Com acesso administrativo, criei `CG-PAINEL-03` como ponto de fábrica inativo e sem dono e provisionei sua nova chave e token pelo USB, sem mostrar os segredos no terminal. O Wi-Fi permaneceu apagado. A captura real do framebuffer mostrou um único QR, decodificado localmente e comparado com o token novo sem divulgá-lo. A cópia temporária da NVS antiga foi apagada após essa validação. `CG-PAINEL-02` permanece inativo e associado ao dono para preservar o histórico. A restauração via botão do app ainda não foi repetida fisicamente depois da correção, para não retirar novamente o ponto de fábrica recém-criado.

## Redesign do totem (tema de referência)

As telas seguem o design de referência do totem (2:1; as posições verticais são esticadas em 1,2 para preencher os 800 × 480 do painel, sem faixas vazias): fundo escuro em degradê com marca e estado de conexão (ponto verde/âmbar) no topo, ou fundo vermelho/âmbar com a ilustração do carregador.

| Estado do firmware | Tela |
| --- | --- |
| Ponto sem dono com token de vinculação | **Ative seu ponto**: três passos numerados, botão **Configurar Wi-Fi** e QR privado (conteúdo e ciclo de vida do QR inalterados) |
| `idle`, ativo, com dono e API online | **Pronto para você**: cartão **CÓDIGO DO PONTO** com o `#F…` rotativo (barra e "Troca em mm:ss") e os passos Abra o app → Use o código → Comece a recarga |
| Falha, Wi-Fi caído, chave rejeitada ou contato perdido | Vermelha **Ponto Indisponível** com a mensagem de reconexão |
| Ponto com dono, online, mas desativado pelo responsável (`connectorActive=false`) | Âmbar **Estamos em manutenção** |
| `reserved` / `charging` / `stopped` / preparação | Mesmo tema escuro: prazo no cartão de destaque, métricas + **Encerrar**, mensagem de despedida |

Na faixa de passos da tela **Pronto para você**, a segunda seta (antes do 03) repete os vãos da primeira: a posição é calculada pela largura real do título/detalhe de cada passo (`lv_txt_get_size`), em vez de coordenadas fixas que deixavam a seta colada em "Use o código deste ponto". Conferido em 19/10/2026 na captura do framebuffer da placa física.

Tela de configuração Wi-Fi (segurar o logo 5 s) usa o mesmo fundo; **Salvar e conectar** é o botão branco principal. O pool do LVGL subiu para 64 KB (`LV_MEM_SIZE` em `platformio.ini`; a UI usa ~47 KB). A tipografia é Barlow Condensed (OFL, `include/panel_font_barlow_OFL.txt`; TTFs em `apps/mobile/assets/`), o rosto condensado do design: Bold para marca, títulos, código e números (`panel_font_brand_30/34`, `title_48`, `alert_68`, `code_72`) e Medium para o texto (`panel_font_body_14/17/19/22`, U+0020–U+00FF e U+2022; o 17 inclui o ● do DejaVu para campos de senha). Todas geradas com `lv_font_conv --bpp 4 --no-compress`; o raio da ilustração é o bitmap alpha `src/panel_font_pump_bolt.c` (o nome casa com o glob de `tools/validate_firmware.py`). Cores de fundo/degradê usam valores exatos de RGB565 para não mudar de matiz entre as faixas.

Pré-visualização no host (LVGL real + `src/panel_ui.cpp`, sem hardware): `python firmware/esp32/preview/render.py --output tmp/panel-preview [--reference <pasta com 1.jpg..4.jpg>]` gera `totem-*.png` (800 × 480) e comparações com o design.

## Case impresso

O [case inclinado](case-tela-waveshare-7/README.md) para esta placa tem moldura e corpo em cunha baixa, com a tela deitada a 30° da mesa (estilo console de balcão), lisos e sem nome, apoiados direto na mesa. As peças se unem por pressão, chaves impressas e cola, sem parafusos; a tela fica prensada entre a moldura e molas impressas. Cada peça sai em metades para caber em impressoras de 180 mm. O README traz as medidas oficiais da tela, o pacote para a faculdade (STL e configurações de impressão), testes do encaixe e a verificação digital. Nada foi impresso ainda.

## Bateria do carro (SoC) e "Bateria cheia" — firmware 0.4.0

Protocolo: `docs/esp32-protocol.md`, seção "Bateria do carro (SoC) e parada por bateria cheia". O START lê `soc_percent`, `battery_kwh` e `soc_source` de `parameters` (com `authorized.session` como reserva); campos ausentes ou `null` mantêm o comportamento anterior, sem cartão de bateria e sem parada por bateria. O SoC inicial, a capacidade e a fonte ficam na NVS (`soc0`, `batt`, `socsrc`) só no START, para que uma sessão interrompida por reboot reporte um SoC final coerente.

- `simulated` com `battery_kwh`: o ponto calcula `min(100, início + energia_kWh / battery_kwh × 100)` e o envia em `soc_percent` (o valor do ponto prevalece na API, pela mesma fórmula). A energia nunca passa da capacidade livre, mesmo com a rede bloqueada; ao chegar em 100 % o ponto para localmente como nos outros limites (`stop("battery_full")`, potência zero) e sincroniza na hora com `end_reason: "battery_full"`.
- `phone` (Modo apresentação): o ponto exibe o `authorized.session.soc_percent` recebido a cada sync (nível real do celular enviado pelo app) e nunca o recalcula; envia `soc_percent: null`. A parada vem da API: um STOP com `parameters.reason == "battery_full"` é aplicado como STOP normal, reportado com `end_reason: "battery_full"`.
- Sessão sem dados de bateria: `soc_percent: null` (o antigo `20 + energia/600` da bancada não é mais enviado).
- Um STOP chegando depois de uma parada local mantém o motivo original já reportado.

Tela: durante a recarga, o cartão "BATERIA DO VEÍCULO" (Barlow Condensed 72 px, barra verde e "Início 35%" ou "Nível do celular") fica acima do **Encerrar**, que encolhe para 56 px. O número é truncado (99,6 % aparece como 99%), então "100%" só aparece com a bateria cheia. Ao parar por bateria cheia, o título vira "Bateria cheia" com o cartão em 100% centrado na coluna direita; como a API encerra a sessão no mesmo sync, esse estado fica 10 s na tela antes de voltar para "Pronto para você" (interrompido por nova reserva/recarga). Pré-visualizações: `.venv/bin/python firmware/esp32/preview/render.py` gera `totem-6-charging` (simulado), `totem-6-charging-legacy` (sem SoC), `totem-9-charging-phone` e `totem-10-battery-full`. Custo medido: LVGL +1,8 KB de heap de objetos (48,6 KB de 64 KB), RAM estática +0,9 KB, nenhuma fonte nova.

`tools/device_simulator.py` segue as mesmas regras (subida simulada, repasse do celular, `battery_full` local e via STOP) e é coberto por `tools/tests/test_device_simulator.py`.


## Latência entre totem e app (19/10/2026)

O totem calcula energia e valor localmente a cada 0,5 s. O app só vê o que o totem já enviou à API. Com sync de 5 s em recarga e consulta do app a cada 5 s, o celular podia ficar até ~10 s atrás da tela (ex.: totem em R$ 2,20 e app em R$ 2,19). Mudanças:

- API: `sync_interval_seconds` = 1 s com sessão, reserva ou comando pendente; 5 s ocioso (antes 5/10 s). O START/STOP pedido pelo app chega ao totem em até ~1 s quando há reserva e em até 5 s sem ela.
- Firmware: `syncDevice()` reaproveita o `WiFiClientSecure`/`HTTPClient` com keep-alive; o handshake TLS (1–2 s no ESP32) só se repete após uma falha (`code <= 0`).
- App: a tela "Recarga em andamento" consulta a sessão a cada 1 s (antes 5 s); o detalhe da reserva, a cada 2 s. No modo apresentação, o nível do celular só é reenviado quando muda.

Diferença esperada agora: até ~2 s (1 s do totem + 1 s do app + rede). Custo: um totem em recarga faz ~3.600 requisições por hora, e o app outras ~3.600; ocioso, o totem faz 720 por hora. Ver a estimativa de volume em `docs/planejamento-mvp.md` antes de escalar para muitos pontos.
