# Painel do posto — Waveshare ESP32-S3-Touch-LCD-7

O profile é exclusivo da **ESP32-S3-Touch-LCD-7** sem B, 800 × 480. Usa Arduino 3.1.1, LVGL 8.4, `ESP32_Display_Panel` 1.0.4, flash DIO a 40 MHz, 16 MB e PSRAM OPI. O modelo 7B é diferente e não deve receber esta imagem.

O firmware reflete somente estados recebidos da API. A tela principal apresenta disponibilidade, código público, instruções simples, reserva com prazo e, durante a sessão, energia, valor estimado, tempo restante e botão Encerrar. Informações de rede e identidade ficam na tela de manutenção, acessada ao segurar a marca; a interface do cliente não mostra potência, SoC nem telemetria de bancada. Este MVP ainda usa `SimulatedSensors` durante sessões: não mede um carro nem aciona relé ou carregador. START continua autorizado somente pelo servidor.

## Compilar e gravar

```bash
pio run -d firmware/esp32 -e waveshare_panel_ui
```

O alias `waveshare_panel_demo` gera a mesma imagem. O pacote atual é `builds/chargegrid-waveshare-7-0.3.5.zip`. Para atualizar uma placa configurada, grave **somente firmware.bin em 0x10000**, com ponto ocioso e nenhuma reserva/sessão pendente. Não use `erase_flash` nem imagem mesclada: preserve NVS, identidade, Wi-Fi e diário de sessão.

## Configurar pelo touch

1. Segure o logo ChargeGrid por cerca de 5 segundos.
2. Digite SSID de Wi-Fi 2,4 GHz e senha. A chave individual já vem provisionada de fábrica; deixe vazia para preservá-la. Manutenção de equipamentos legados fica em **Conta → Meus equipamentos e postos → Posto → Ponto**. A partir do firmware 0.2.1, deixe a senha vazia para redes abertas; isso remove a senha anterior, sem alterar a identidade do dispositivo. Redes abertas não protegem o enlace Wi-Fi, mas a comunicação com a API continua usando HTTPS com certificado validado.
3. Toque em **Salvar e conectar**; o painel reinicia no modo integrado.

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

O firmware 0.3.5 compilou e passou em `tools/validate_firmware.py --decode-qr`; a API passou nos testes com PostgreSQL descartável. A placa física não foi atualizada nem restaurada nesta etapa porque não apareceu uma porta serial conectada. O pacote `builds/chargegrid-waveshare-7-0.3.5.zip` tem SHA-256 `385b66419a8f0f814744730d271b7a03f15d8429725985058c8527b94cb26868` e não contém NVS nem segredos.
