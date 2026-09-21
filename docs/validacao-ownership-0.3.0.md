# Ownership por QR e reconciliação — 21/09/2026

## Entrega

- App 0.3.0, build 14: `builds/chargegrid-0.3.0.apk`.
- API de prévia: `https://chargegrid-api-preview-djlima1s-projects.vercel.app/v1`, implantação `chargegrid-jj6xskkrg-djlima1s-projects.vercel.app`.
- Migração aditiva `d85af641bc01` aplicada; proprietários anteriores preservados.
- Firmware 0.3.0 instalado na Waveshare conectada, gravando apenas 0x10000. Wi-Fi aberto `beleza`, identidade e NVS preservados.
- Pacote de firmware: `builds/chargegrid-waveshare-7-0.3.0.zip`.

## Novo fluxo

Fábrica provisiona posto/ponto inativos, chave de dispositivo e token de propriedade distintos. O comprador entra como vendedor, abre **Vincular equipamento**, escaneia o QR e confirma. A API vincula uma única vez e libera a gestão sem aprovação administrativa. Repetição pelo mesmo dono é idempotente; outro dono não pode assumir o ponto. Depois, o vendedor configura endereço/tarifa e ativa posto e ponto.

O QR privado não é o código público usado para iniciar recarga. O banco guarda somente o hash do token. No painel, a confirmação explícita da API remove token e QR. Equipamentos legados não são desvinculados nem ganham QR que permita tomada de posse.

Uma reserva válida não é liberada por desligar o ESP32. O servidor reenvia `RESERVE` após reboot/divergência; o ACK não muda o prazo. App distingue Reservado, Em recarga, Offline, Sincronizando, Desativado, Falha, Ocupado e Disponível. Enquanto o equipamento não confirma o estado, outra pessoa não pode usar o ponto.

## Validações executadas

- **API: 86 testes em PostgreSQL real**, incluindo 11 de ownership e 19 de reboot/disponibilidade: concorrência, replay, invasão entre contas, consumidor recusado, expiração/cancelamento soberanos e prazo imutável.
- **Mobile: 97 testes, 10 subtestes**, incluindo callbacks reais de scan/claim, cancelamento de câmera, segredo limpo após sucesso, nova tentativa após falha e rotas de Voltar.
- **Ferramentas: 43 testes**, com integração de importação em PostgreSQL descartável.
- **Leitor Android: 8 testes Flutter** com fronteira de câmera simulada; análise estática aprovada. Decodificação ML Kit incluída no APK, sem upload de imagens nem dependência de decoder remoto.
- **Firmware:** ambos os targets compilados; controlador real exercitado no host, 12 telas LVGL, QR offline/online decodificado e ausência verificada após vinculação/legado.
- **HTTP remoto real:** conta consumidora recusada, vendedor vincula equipamento novo, replay seguro, ponto inicialmente inativo, reserva confirmada, novo boot restaura reserva sem alterar `expires_at`, cancelamento confirmado. Ponto QA deixado inativo.
- **ESP32 físico:** idle/HTTP 200 → reserva → reset RTS com novo marcador ROM → reserved com mesmo ID/prazo → cancelamento → idle e API disponível. Repetido com validação explícita de novo boot. Nenhuma recarga iniciada nesse teste.
- **Navegador 390×844:** tela de vinculação inspecionada; código público recusado, botão reabilitado após erro, aviso de câmera exclusiva do APK, confirmação de descarte ao voltar.
- **APK:** versão/build, permissão CAMERA, modelo ML Kit empacotado e assinatura verificados.

Os acessos QA antigos foram recusados também pelo deploy anterior e pelo provedor. Foram criadas contas fictícias isoladas para os testes; nenhuma senha existente foi alterada. Credenciais e artefatos de fábrica ficam em `/tmp` privado, não no Git/APK.

## Limites explícitos

- Não havia celular Android conectado. A leitura pela câmera física do APK ainda precisa de validação no aparelho; testes de widget não substituem isso. No navegador há entrada manual do código privado.
- O QR foi decodificado a partir da renderização LVGL real no host, não escaneado com câmera apontada ao LCD. O painel físico existente já tem proprietário; seu dono foi preservado.
- O equipamento é uma bancada simulada: não mede nem energiza um carregador real.
- Entrega geral de e-mails de recuperação continua dependendo de SMTP próprio, fora desta alteração.

## Integridade

- APK SHA-256: `bc9cf72193873c8b3e31c0364a6e41caaa86d3aba5694d8190da59420faf11d9`.
- firmware.bin SHA-256: `ad8dbce714634b3bbd8bc7d643de935065c1ad48077552d8cfc816a520053235`.
