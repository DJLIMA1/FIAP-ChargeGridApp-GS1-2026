# Validação da experiência 0.3.1 — 21/09/2026

## Fluxos cobertos

- O QR de propriedade abre a configuração inicial do vendedor. O assistente salva nome/endereço/coordenadas, conector/tarifa e permite revisão antes de publicar. Erros numéricos impedem requisições; voltar e deixar para depois preservam o rascunho inativo.
- O painel de vendedor identifica pontos online, offline e com configuração pendente, oferecendo retomada do assistente.
- Na lista do consumidor, postos e conectores disponíveis aparecem primeiro; reservado, sincronizando, offline e falha têm sinais distintos. Polling sem mudança não reconstrói os cartões.
- O firmware evita flushes LVGL periódicos com estado inalterado; uma mudança real continua renderizando. A API preserva reservas confirmadas após reboot do ESP32 até expiração ou cancelamento.

## Execução

- App: `98 passed, 10 subtests passed`; Ruff sem erros.
- API em PostgreSQL descartável: `87 passed`; o teste HTTP da publicação confirma que nem mesmo uma ativação parcial expõe a estação enquanto ela permanece inativa.
- Ferramentas com PostgreSQL descartável: `43 passed`.
- Firmware: `tools/validate_firmware.py` passou (controlador, interface LVGL e 12 quadros); `pio run -d firmware/esp32 -e waveshare_panel_ui` passou.
- Prévia Flet do assistente em 390 × 844: as três etapas foram abertas e revisadas visualmente. O teste visual web não substitui interação no APK Android físico.
- ESP32 físico: antes da gravação, a API confirmou ponto disponível, sem reserva/sessão. Gravado somente `firmware.bin` em `0x10000`; esptool verificou o hash. Após reboot, o serial registrou `firmware=0.3.1`, `state=idle`, `wifi=connected`, `synced=yes`, `http=200`, `session=none`. A API voltou a reportar o ponto disponível.
- APK: `versionName=0.3.1`, `versionCode=15`, câmera e Internet no manifesto; assinatura v2 verificada. O conteúdo empacotado contém o assistente e a correção final da navegação.

## Artefatos locais

- `builds/chargegrid-0.3.1.apk` — SHA-256 `b70f48b04d7912cb6da3e79d01e4a3631d9dc2c2cd1aed01f6b43ab89904f19e`.
- `builds/chargegrid-waveshare-7-0.3.1.zip` — SHA-256 `572e2d4c059d2bd9b53e7890a873b36f54aa80d815e93734b14af5cd70ec693c`.

Os artefatos em `builds/` não são versionados. O LCD físico não foi medido com instrumentação de cintilação; a evidência direta é a ausência de flushes LVGL quando o estado não muda e a reconexão do dispositivo real após a gravação. A leitura do QR pela câmera Android física permanece pendente de um aparelho Android conectado.
