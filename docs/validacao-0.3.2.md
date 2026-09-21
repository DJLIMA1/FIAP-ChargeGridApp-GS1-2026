# Validação da primeira vinculação física 0.3.2 — 21/09/2026

## Resultado

- O ESP32 conectado ao Mac foi migrado de `CG-PAINEL-01` para o novo ponto de fábrica `CG-PAINEL-02`, sem apagar o Wi-Fi. O LCD físico agora mostra **Vincule seu ponto** e o QR de propriedade; a leitura do framebuffer da placa decodificou exatamente a credencial privada provisionada.
- A API publicada confirma que o novo ponto está online, sem dono e inativo, inclusive após reiniciar o ESP32. Ele não fica disponível aos consumidores antes de o vendedor concluir o assistente e publicar.
- O ponto antigo foi desativado e sua chave revogada. O posto de bancada e outro conector nele permaneceram ativos; reservas, sessões e histórico não foram apagados.
- Para encontrar o fluxo: entrar no app 0.3.2 com uma conta de vendedor → **Meus postos** → **Escanear QR da tela**. Uma conta nova vê **Configure sua primeira tela** com o mesmo botão. Após a leitura, confirmar o vínculo e concluir localização, conector/tarifa, revisão e publicação. O QR desaparece do ESP32 após o vínculo.

## Verificações

- App: `99 passed, 10 subtests passed`; Ruff sem erros. O teste do painel de vendedor confirma a orientação visível e a navegação para o leitor.
- Firmware: `tools/validate_firmware.py` passou nos testes de controle, QR e 12 quadros LVGL; `pio run -d firmware/esp32 -e waveshare_panel_ui` compilou. O teste de host cobre a recusa de migração com operação pendente ou falha no NVS e a remoção segura da identidade antiga.
- ESP32 físico: firmware 0.3.2 gravado apenas em `0x10000`, hash conferido pelo esptool. Antes da migração, `idle`, Wi-Fi conectado, sincronizado com HTTP 200, sem sessão. O comando USB exigiu confirmação do código público. A nova chave e o QR foram instalados por USB sem ecoar seus valores.
- APK: `versionName=0.3.2`, `versionCode=16`, permissões de câmera e Internet presentes, assinatura v2 válida. O conteúdo empacotado contém a orientação **CONFIGURAR UMA NOVA TELA**.

## Artefatos locais

- `builds/chargegrid-0.3.2.apk` — SHA-256 `e0babb9104f719cabd70687b54afe14427ca9f53fd8fae665c1c0b2f2ad93ab1`.
- `builds/chargegrid-waveshare-7-0.3.2.zip` — SHA-256 `0bee8d85ea3a83b370755c4f63e9c9d0df56de6a127ff97379d57dd3f034f4a2`.

Os artefatos em `builds/` não entram no Git. A credencial do QR e sua captura física também não são publicadas nem anexadas. A leitura com uma câmera Android real e o vínculo com uma conta pessoal ainda dependem de usar o APK num aparelho Android; não havia telefone Android conectado durante esta validação. O ponto permanece propositalmente sem dono para o primeiro vínculo do usuário.
