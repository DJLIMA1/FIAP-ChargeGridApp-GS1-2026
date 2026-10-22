# Autoatendimento, reserva e tarifas por velocidade — 0.9.3

## Interface

- O código rotativo `#F` permanece no cartão superior durante a reserva. O prazo para iniciar fica separado na faixa inferior, sem substituir o código.
- O pagamento mostra um QR e o botão **Já efetuei o pagamento**. O valor permanece como informação auxiliar. O checkout de apresentação é somente leitura: abrir o QR não confirma pagamento nem debita saldo. A confirmação de Stripe continua sendo verificada no servidor.
- Confirmar o encerramento mantém o cartão, energia, potência, valor e tempo da recarga; mudam as ações e a instrução. O mesmo renderer atende sessões iniciadas pelo app e pelo totem.
- O comprovante mostra uma contagem de 30 segundos. Toques não renovam esse prazo. Depois disso, o QR desaparece; quando há veículo conectado, permanece a ação para desconectar e as regras de permanência. O histórico do aplicativo continua disponível.
- A autonomia aparece desativada para visitantes com **(requer login)**. Contas sem carro cadastrado recebem a indicação correspondente.

## Tarifas

API, aplicativo e tela distinguem velocidade máxima e reduzida. A reduzida tem desconto padrão de 20%; o dono configura ambos os valores no menu de tarifas existente. Para cobrança paga, a reduzida deve ser menor que a máxima; ambos podem ser zero em um ponto gratuito.

Horários configurados usam o preço máximo absoluto daquele intervalo e a proporção entre as velocidades. Reserva e pré-pagamento guardam o preço e a velocidade contratados; uma redução automática por divisão da rede não muda a tarifa sozinha. Orçamento, cobrança, reembolso e comprovante usam a mesma seleção.

A oferta também respeita a potência confirmada do carregador. Por exemplo, conector cadastrado com 22 kW ligado a hardware de 7 kW oferece máxima de 7 kW e reduzida de 3,5 kW.

Os campos são aditivos em `Station.pricing` e `price_terms`. Esta revisão não requer nova migração.

## Validação e entrega

- API: 467 testes completos; depois do último ajuste de validação estrita, 91 testes focados passaram.
- Core: 251 testes passaram; cópias API/mobile sincronizadas.
- App: 798 testes e 129 subtestes; depois do último ajuste do modo demonstração, 107 testes focados e 25 subtestes passaram.
- Firmware: testes de controlador, fluxo e LVGL real, QR decodificado, retenção das métricas, limite de 30 segundos e código durante reserva.
- A API foi publicada em [chargegrid-h5yy37xua](https://chargegrid-h5yy37xua-djlima1s-projects.vercel.app) e o endereço compartilhado [ChargeGrid API](https://chargegrid-api-preview-djlima1s-projects.vercel.app) foi atualizado com a autorização já concedida.

O driver mantém os 16 MHz, o SDK e os buffers da 0.9.2 cuja imagem foi aprovada pelo usuário. A compilação final foi gravada somente em `0x10000`, com hash verificado pelo esptool, preservando NVS, Wi-Fi e identidade. O boot físico confirmou **firmware=0.9.3, wifi=connected, identity=configured, synced=yes, http=200**, sem sessão ativa. Logs em `tmp/kiosk-validation/flash-0.9.3-final.log` e `physical-0.9.3.log`.

O aplicativo é entregue como APK local 0.8.7 (build 47). A instalação em um telefone não faz parte da validação física desta revisão, pois não há Android conectado.

- Firmware: `builds/chargegrid-waveshare-7-0.9.3.zip`, SHA-256 `a9bf02d7fcb97881571f93f5e352282f9fa34da9935b8829128dae64a410b64c`. O binário do pacote corresponde ao build gravado e todos os hashes internos foram verificados.
- Android: `builds/chargegrid-0.8.7.apk`, SHA-256 `1bc48e863763359adb9cbbaf60d1631b4ca05a9bb5d6478b10c249a32101bae8`. Versão/build confirmados por `apkanalyzer` e factory JNI do MapLibre validada após R8. O core compilado embarcado corresponde ao empacotamento final.
- Capturas do LVGL real: `tmp/kiosk-validation/panel-reserved.png`, `kiosk-power.png`, `kiosk-pay-simulated.png`, `kiosk-confirm-stop.png`, `kiosk-receipt.png` e `kiosk-receipt-expired-connected.png`.
