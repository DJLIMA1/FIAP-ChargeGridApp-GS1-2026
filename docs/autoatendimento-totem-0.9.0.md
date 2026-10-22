# Autoatendimento da central — firmware 0.9.0

Revisão posterior: [correções e interface compartilhada da 0.9.2](autoatendimento-totem-0.9.2.md). Esta página registra a entrega inicial.

Referência visual: os SVGs de `Core (Projeto)-9`, adaptados para os 800 × 480 pixels da Waveshare 7. A interface usa a composição em duas colunas, superfícies escuras, marca vermelha e controles brancos. As opções ocupam toda a largura interna; textos de revisão e recibo ajustam a fonte para caber.

## Fluxo

1. Escolher **Entrar na minha conta** ou **Continuar sem login**.
2. Selecionar um carregador disponível da central. Carregadores ocupados ficam desabilitados; o carregador principal desativado não bloqueia os outros.
3. Escolher valor, tempo ou energia. **Autonomia** aparece somente com login confirmado e carro válido salvo no perfil.
4. Informar o limite com atalhos ou teclado.
5. Escolher potência máxima ou reduzida, respeitando ponto e carro.
6. Escolher Pix, cartão ou saldo. O servidor informa os meios habilitados. O saldo exige login, saldo suficiente e posto em modo apresentação.
7. Revisar preço, demanda, teto, estimativas e permanência, e aceitar.
8. Pagar: no modo apresentação, confirmação explicitamente simulada; na Stripe de teste, QR da página segura. Não há uma maquininha física fictícia nem um botão que confirme sozinho um pagamento real.
9. Aguardar o START normal do servidor e acompanhar potência, energia, custo e tempo. SoC desconhecido permanece `--`.
10. Encerrar com confirmação e consultar o recibo. A sobra do saldo simulado é devolvida uma única vez.

Os textos dos mockups são referências de produto, não instruções operacionais. Em particular, o “Já paguei” do desenho não substitui confirmação do servidor.

## Integração

- Preserva a integração revisada de `origin/main` (`d546de4`), incluindo central multicarregadores, START estrito por Modbus, reconexão, retenção de STOP até releitura e isolamento por carregador. A cópia inicial estava 15 commits atrás dessa revisão; as mudanças foram integradas sem resetar as alterações locais existentes.
- A oferta do totem declara `ui_version: 2` e lista até quatro carregadores gerenciados pela central, correspondendo ao controlador principal e aos três slots adicionais do firmware.
- `X-Kiosk-Charger-Address` endereça as rotas ao carregador selecionado. O servidor valida que ele pertence à central autenticada. Pedido e endereço ficam em `kord`/`kadr` para retomada após reboot. Cancelamentos mantêm seu endereço mesmo ao voltar ao início.
- Login usa `/v1/auth/login`. As rotas do dispositivo continuam exigindo a chave da central; `X-Kiosk-Authorization: Bearer <JWT>` autentica a pessoa separadamente. E-mail, senha e JWT ficam somente em RAM; a senha é mascarada, o refresh token é descartado, e conclusão, cancelamento ou inatividade apagam a identidade.
- As credenciais e a chave do dispositivo não aparecem em logs ou QRs. QRs são somente os links de pagamento/recibo emitidos pela API.
- O perfil do carro continua disponível em `/driver/profile`, mesmo com o planejador Motorista descontinuado. `/me/vehicle` oferece o mesmo cadastro.
- A migração aditiva `b6d2e8f1a490`, posterior à `d3f8a1c6e2b7` já existente no banco, cria `simulated_wallets`, com RLS e acesso somente pelo backend. Migração aplicada e revisão conferida.
- `/me/wallet` e `/me/wallet/simulate` compartilham o saldo **simulado** por conta. O app importa uma única vez o saldo local antigo, consulta o saldo atual e usa chaves idempotentes para operações e devoluções. Esse saldo não financia Stripe nem representa dinheiro real.
- APKs antigos continuam com sua carteira local. Para compartilhar esse saldo com a central, o celular precisa executar o app atualizado deste código; esta entrega não publica uma atualização de APK.
- API antiga sem `ui_version: 2`: visitante continua com o contrato anterior; potência reduzida e meios separados não são enviados como campos desconhecidos. Login informa a atualização pendente, sem fingir que a conta foi vinculada.

## Validação e entrega

- API completa: **454 testes passaram**, com PostgreSQL descartável e migrações. Revalidação dos 34 testes específicos após o ajuste do principal desativado: passaram.
- App completo, com a integração atual da central: **791 testes e 129 subtestes passaram**.
- Firmware: compilação `waveshare_panel_ui` aprovada; RAM estática 142.372/327.680 bytes e flash 1.829.696/6.553.600 bytes.
- Controladores reais compilados no host: autorização, watchdog, reconexão, múltiplos carregadores, STOP por releitura, login, autonomia, potência, saldo, retomada e cancelamento endereçado passaram, incluindo sanitizers.
- Capturas do LVGL real em `tmp/kiosk-validation`, com verificação dos glifos e decodificação dos QRs. As 20 capturas anteriores, com o totem desligado, permaneceram idênticas.
- Pacote em `builds/chargegrid-waveshare-7-0.9.0.zip`; inclui somente firmware, componentes de recuperação, hashes e prévias, sem NVS ou segredos.
- Preview mais recente da API: `https://chargegrid-qiu45ypt8-djlima1s-projects.vercel.app` (`READY` no Vercel). Com autorização explícita, o alias compartilhado `chargegrid-api-preview-djlima1s-projects.vercel.app` foi direcionado para esse deployment.
- Firmware **0.9.0 gravado na tela física** após a reconexão USB, somente em `0x10000`, sem apagar a NVS. O esptool verificou o hash; o boot e o status serial confirmaram a versão nova e a identidade preservada, sem sessão pendente.
- O autoatendimento foi habilitado (`kiosk_mode=true`) no posto **Lab-Goodwe FIAP**, da central **CG-4HPF**. As configurações de pagamento existentes foram preservadas.
- Após o usuário reconectar o Wi-Fi, o status físico confirmou **firmware=0.9.0, wifi=connected, identity=configured, synced=yes, http=200, kiosk=simulated**, estado ocioso, sem sessão e potência zero. Evidência em `tmp/kiosk-validation/panel-live.log`.
- A captura física final `tmp/kiosk-validation/panel-online.png`, obtida após confirmar HTTP 200, mostrou **Pronto para você**, código rotativo e botão **Iniciar autoatendimento**. O LCD foi conferido visualmente pela imagem de seu framebuffer. A validação dos fluxos com eventos de toque é executada no LVGL real no host; não se declara uma recarga física paga nesta entrega.
- As ferramentas de pacote e de QA de reboot usam a versão 0.9.0; os dois testes de consistência passaram.

Na atualização da tela já configurada, gravar somente `firmware.bin` em `0x10000`, com a central sem sessões ativas. Preservar NVS, Wi-Fi, identidade e diário; não usar `erase_flash`.
