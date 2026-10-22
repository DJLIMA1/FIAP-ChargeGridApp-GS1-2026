# Autoatendimento e acompanhamento compartilhado — 0.9.2

## Alterações

- Escolha por valor, tempo ou autonomia. A opção por energia saiu da interface. Autonomia exige login e carro cadastrado.
- O cálculo, o arredondamento e o aviso de limite da bateria foram extraídos das regras existentes do app para `chargegrid_core.charge_plan`. API e app chamam a mesma função; não há um segundo cálculo no firmware.
- A etiqueta SIMULADO/TESTE do topo foi removida. A confirmação de pagamentos de apresentação continua identificando a simulação.
- Recargas iniciadas pelo app e pelo autoatendimento usam os mesmos componentes LVGL de acompanhamento, confirmação de parada e finalização. As telas antigas ficam como referência de regressão e não são escolhidas para uma recarga no perfil de produção da Waveshare.
- O acompanhamento também funciona com o autoatendimento desligado no posto e para um carregador adicional. A parada continua endereçando somente o carregador exibido.
- O resumo mantém energia, valor e duração depois que a API limpa a sessão ativa. Para sessões do app, o comprovante completo continua no app; não se inventa um QR de pedido do totem.
- Carregador sem resposta e central sem internet são estados diferentes. Sem carregador disponível, a tela informa isso e não oferece iniciar. Uma falha antes do pagamento pode ser repetida sem o antigo retorno automático de seis segundos; o prazo de privacidade por inatividade permanece.
- Um HTTP 5xx isolado não apaga uma sincronização válida: autenticação rejeitada e o prazo de 45 segundos continuam sendo respeitados.

## Driver do LCD

O SDK é o Espressif Arduino **3.1.1-h**, correspondente ao Arduino 3.1.1 já usado. O build confirma cache de dados de 64 bytes e XIP na PSRAM. São mantidos dois framebuffers, troca no VSYNC, bounce buffer de 20 linhas e o clock original de **16 MHz**.

A tentativa intermediária 0.9.1 com 10 MHz foi rejeitada na observação física: o usuário relatou alternância de cores embora a captura do framebuffer mostrasse a interface correta. A 0.9.2 restaura os 16 MHz do perfil Waveshare. A imagem de um framebuffer não comprova sozinha estabilidade óptica; a confirmação visual da placa faz parte da entrega.

Referências do fabricante: [SDK Arduino compatível](https://github.com/esp-arduino-libs/arduino-esp32-sdk#for-sdks-suffixed-with--h) e [orientações de RGB/PSRAM](https://docs.espressif.com/projects/esp-faq/en/latest/software-framework/peripherals/lcd.html).

## Validação

- API: 34 testes de autoatendimento e contas passaram em PostgreSQL descartável, incluindo equivalência com o plano de autonomia e solicitação abaixo de 1 kWh por quilômetros.
- App: 791 testes e 129 subtestes passaram.
- Firmware: controladores e LVGL real passaram nos testes de host, incluindo falta/retorno do carregador, recuperação de HTTP, captura de telas comuns, parada endereçada e retenção do resumo.
- Com os mesmos dados, as imagens de acompanhamento de uma sessão do app e de uma sessão do totem são idênticas byte a byte.
- A consistência das versões de pacote/QA e a cópia de `chargegrid_core` passaram nos três testes de ferramentas. Ruff e `git diff --check` passaram.
- Build físico: RAM estática 144.208/327.680 bytes; flash 2.009.146/6.553.600 bytes.

## Entrega

A API `chargegrid-cp8tgjxto-djlima1s-projects.vercel.app` foi publicada e o alias compartilhado `chargegrid-api-preview-djlima1s-projects.vercel.app` foi atualizado com a autorização já concedida. Nenhuma nova migração foi necessária nesta correção.

A 0.9.2 foi gravada somente em `0x10000`, com hash verificado pelo esptool, preservando NVS, identidade e Wi-Fi. O pacote está em `builds/chargegrid-waveshare-7-0.9.2.zip` (SHA-256 `0f3469cfbcd1bbd6bdf0743731e66e0cfdad221de60750e9b6003a068ff8c85b`).

O boot físico confirmou **firmware=0.9.2, wifi=connected, identity=configured, synced=yes, http=200**, com a central ociosa e sem sessão. A captura física `tmp/kiosk-validation/physical-0.9.2.png` mostrou a etapa de pagamento sem a etiqueta no topo; os logs registraram oferta/orçamento HTTP 200, criação de pedido HTTP 201 e pagamento HTTP 200 na placa. O usuário confirmou a imagem após restaurar 16 MHz: “Funcionou, aparentemente tá legal.” Logs em `tmp/kiosk-validation/physical-0.9.2.log`; capturas de host em `tmp/kiosk-validation/kiosk-shared-*`.
