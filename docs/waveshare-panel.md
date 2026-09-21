# Painel do posto — Waveshare ESP32-S3-Touch-LCD-7

O profile é exclusivo da **ESP32-S3-Touch-LCD-7** sem B, 800 × 480. Usa Arduino 3.1.1, LVGL 8.4, `ESP32_Display_Panel` 1.0.4, flash DIO a 40 MHz, 16 MB e PSRAM OPI. O modelo 7B é diferente e não deve receber esta imagem.

O firmware é operacional e reflete somente estados recebidos da API. Sem configuração, mostra **Configure este ponto**, sem código ou números fictícios. SoC, energia, potência e custo ficam `--` até existir sessão sincronizada. Este MVP ainda usa `SimulatedSensors` durante sessões e identifica a origem discretamente como `Bancada • dados simulados`; não mede um carro nem aciona relé ou carregador. START continua autorizado somente pelo servidor.

## Compilar e gravar

```bash
pio run -d firmware/esp32 -e waveshare_panel_ui
```

O alias `waveshare_panel_demo` gera a mesma imagem. O pacote atual é `builds/chargegrid-waveshare-7-0.3.2.zip`. Para atualizar uma placa configurada, grave **somente firmware.bin em 0x10000**, com ponto ocioso e nenhuma reserva/sessão pendente. Não use `erase_flash` nem imagem mesclada: preserve NVS, identidade, Wi-Fi e diário de sessão.

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
