# ChargeGrid 0.2.0 — validação e entrega

Revisão de 21/09/2026. Os testes abaixo distinguem código controlado, serviços reais e hardware físico. Não representam garantia de ausência de todos os defeitos.

## Correções entregues

- Tipo de conta persistido no cadastro (`consumer`/`vendor`); login somente por e-mail e senha. Vendedor novo aguarda aprovação administrativa para gerenciar postos, sem autoatribuição de privilégios.
- Senhas não são mais aparadas: espaços fazem parte da credencial. Login aceita credenciais legadas; contas novas exigem pelo menos oito caracteres. Erros de rede/provedor/campos são apresentados, e clique + Enter não duplica a operação.
- Refresh concorrente único, chaves de idempotência preservadas em falhas incertas e liberadas depois de uma sessão terminal conhecida. Uma nova recarga no mesmo ponto não reutiliza a sessão antiga.
- Tema claro/escuro consistente, preferência persistida, campos alinhados, botões de 48 px, navegação compacta, SafeArea, retrato no mobile e Back com destinos lógicos.
- Página inicial atualiza estado e resumo sem perder rolagem; telas de recarga atualizam ações após confirmação/parada. Validações de coordenadas, duração, custo, cupons e perfil.
- Gestão usa nomes dos postos para cupons, identifica ativos/inativos e recupera automaticamente o dispositivo vinculado. O endpoint de consulta exige operador proprietário e nunca retorna chave ou hash.
- Recuperação por link tem formulário funcional e endpoint de alteração de senha. **Entrega do e-mail ainda requer SMTP próprio**; não é declarada como validada.
- Histórico cronológico; correção de estados após falha/reinício; bloqueios de banco atualizam objetos antes de aceitar telemetria/comandos ou credenciais de dispositivo revogadas.
- API executada em São Paulo (`gru1`), junto ao banco, com menos consultas redundantes. Medição real de chamadas aquecidas: `/me` 1,203 → 0,202 s; `/stations` 2,463 → 0,128 s; `/me/summary` 1,353 → 0,101 s. Amostra pontual, não SLA.
- ESP32 com layout redesenhado, limite monetário respeitado, manutenção bloqueada durante operações, watchdog e parada local. Wi-Fi e identidade preservados no NVS.

## Testes reproduzidos pelo coordenador

| Camada | Evidência |
| --- | --- |
| API | 56 testes em PostgreSQL local real, nenhum ignorado; regras, autorização, concorrência, JWT, contratos e autenticação. Chamadas ao provedor são controladas nesses testes. |
| Mobile | 64 testes de controles/callbacks e transporte, incluindo concorrência, tema, navegação, recarga, polling, cupons e redescoberta do dispositivo. |
| Ferramentas | 29 testes: simulador e administração; integração de importação executada em PostgreSQL descartável, sem acesso à base legada do usuário; aprovação de vendedor também executada em banco local real. |
| Firmware | Compilações `waveshare_panel_ui` e `esp32dev`; 21 verificações executando o controlador/UI reais em host, sete quadros LVGL, teclado/botão, replay, limite e watchdog. |
| API publicada/Auth real | Cadastro, perfil persistido, login, refresh, logout e novo login com consumidor/vendedor; aprovação isolada da conta fictícia. Alteração real da senha de teste, rejeição da senha antiga e preservação de espaços. |
| Integração HTTP | Posto/pontos/dispositivos, reserva idempotente + ACK/cancelamento, cupom, início/telemetria/parada, isolamento entre contas, histórico e resumo. `tools/qa_live.py` permite repetir com identidades explicitamente fornecidas. |
| Interface real no navegador | Login/logout/novo login, tipos no cadastro, campos preservados, erro de formulário, claro/escuro, conta, lista/mapa, reserva, recarga, histórico e gestão. Larguras de 360 e 390 px e altura reduzida para validar rolagem. Prévia apenas preenche credenciais fictícias; botões/callbacks e API são os reais, sem autenticação simulada. |
| ESP32 físico via interface | Reserva confirmou na placa; primeira sessão iniciou e encerrou pelo app: **60,392 Wh**, **R$ 0,0906** estimados. Segunda iniciou diretamente e encerrou pelo comando local: **12,084 Wh**, **R$ 0,0181** estimados. Ambas `completed`, origem `simulated`, histórico cronológico. |
| Limite automático físico | Terceira sessão enviada pela API com teto R$ 0,01: ESP32 encerrou sozinho em **6,666 Wh / R$ 0,0100**, motivo `cost_limit`. Home mudou de ocupado/iniciando para disponível/sem sessão e atualizou de quatro para cinco sessões sem navegar. |
| Encerramento físico | Placa online/disponível, sem sessão/reserva ativa, potência zero. Porta serial fechada depois da reconciliação; heartbeat confirmado depois do fechamento. |

Resultados HTTP estruturados: [qa-live-results.json](qa-live-results.json). Testes e limitações mobile: [mobile-qa-notes.md](mobile-qa-notes.md). Captura do framebuffer real e comandos físicos: [waveshare-panel.md](waveshare-panel.md).

Total Python: **149 testes aprovados**, zero ignorados. Ruff limpo. O APK foi verificado com `apksigner` (assinatura v2 válida) e o pacote interno foi inspecionado: URL pública estável correta, sem `.env`, credenciais de QA, testes ou caches locais.

## Artefatos e uso

- APK: `builds/chargegrid-0.2.0.apk`, pacote `br.com.ffive.chargegrid`, versão 0.2.0, build 10. Instale a atualização; um APK antigo continua contendo o código/configuração antigos.
- API estável: <https://chargegrid-api-preview-djlima1s-projects.vercel.app/v1>. Mesmo endereço no APK e no firmware. Implantação de preview, não promoção para produção.
- Firmware já instalado: `builds/chargegrid-waveshare-7-0.2.0.zip`. Inclui binários, hashes e captura física; não contém chaves, senha de Wi-Fi nem dump de NVS.
- Contas fictícias consumidor/vendedor: `builds/chargegrid-demo-acessos.json`, arquivo privado modo 0600 e ignorado pelo Git. Não publicar. A senha do consumidor de teste contém espaços significativos: copiar o valor integral.
- Ponto físico: `CG-PAINEL-01`. `CG-QA-SIM` fica offline quando o simulador de teste não está executando; isso é esperado.
- Migração aditiva aplicada: `c74ef532ab90` (tipo de conta e data de criação das sessões), após backup privado do esquema público. Nenhum usuário anterior foi promovido ou removido.

SHA-256 APK: `881e8b83c045e61f5082a867c269e4740e365f68176aba6f712c9614990bb2e6`.

SHA-256 firmware ZIP: `f440a876ddfca6f07cb699f63fff34d403558434c09f41a91287a3e25f5561fb`.

## Limites explícitos

1. A bancada transmite telemetria **simulada**. Não há relé, carregador real, cobrança ou pagamento.
2. SMTP próprio não estava disponível. O fluxo por link está implementado, mas entrega à caixa postal não foi validada e pode falhar. Confirmação de e-mail está desativada neste MVP; reativá-la exige configuração de entrega antes do uso público.
3. Não havia Android conectado nem emulador instalado. O APK foi compilado, inspecionado e teve sua configuração pública conferida, mas rotação, teclado virtual, suspensão e Back **não foram testados num Android físico**. Testes de layout no navegador não substituem essa etapa.
4. Tokens de sessão ficam somente em memória: após fechar/reabrir o app, é necessário entrar novamente. A recarga física não depende de manter o app aberto.
5. Mapas/geocodificação dependem de serviços externos; a interface usa mapa esquemático quando indisponíveis. O teste usou apenas endereço fictício.
6. A ativação da camada de acessibilidade HTML do Flutter web escureceu alguns campos na ferramenta de teste. A comparação sem essa camada mostrou os valores brancos corretos; controles Python também registraram cor branca, habilitados e opacidade 1. Não foi aplicada uma alteração global ao APK para contornar esse comportamento da prévia web.
