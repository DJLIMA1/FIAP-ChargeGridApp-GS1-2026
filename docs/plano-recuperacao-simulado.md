# Recuperação criteriosa da branch Simulado

## Base e preservação — 26/09/2026

- Branch antiga verificada no remoto: `origin/Simulado` (`7966e85`).
- Main oficial verificada: `origin/main` (`66a89bf`); a única mudança desde a base comum `22f6e1e` é o README.
- Base local preservada: `8ab7df8`, que acrescenta o código de presença #F, mais correções locais documentadas em `validacao-retomada-0.3.7.md`.
- Não substituir a integração real com API/ESP pelo estado JSON nem pela simulação acelerada da branch antiga.

## Inventário comparado com o código (não só com o README)

| Recurso da Simulado | Situação atual / decisão |
| --- | --- |
| Tema claro/escuro, cadastro, perfil | Já existem; preservar persistência e autenticação Supabase. |
| Alterar senha | Recuperação já existe; acrescentar acesso autenticado na Conta, com confirmação e novo login. Não recuperar a redefinição insegura só pelo e-mail. |
| Painéis distintos de consumidor/vendedor | Gestão e resumo já existem, mas navegação é sempre de consumidor. Recuperar abas contextuais e troca explícita de modo sem alterar permissões. |
| Recarga por tempo ou valor | API já tem duração e teto de custo; expor modos explícitos com contexto do ponto e aviso de estimativa. Sem inventar pagamento confirmado ou medida física. |
| Localização salva | Busca/geocodificação/mapas já existem; acrescentar busca salva por conta neste dispositivo, somente mediante ação explícita, com remoção. Não coletar GPS/IP silenciosamente. |
| Chat | O código antigo responde sempre uma frase fixa e afirma registrar mensagens. Substituído por conversa local com orientações e consultas somente leitura da conta, com limites claros (sem IA/atendimento humano). |
| Cupons e histórico de vendedor | Já existem. Corrigir paginação/expiração e dar acesso direto; identificar posto/ponto em histórico e acompanhamento. |
| Cadastro de posto/ponto | Já existe com QR e propriedade verificável. Melhorar distinção endereço/equipamento, resumo e etapas; posto existente não deve obrigar edição do endereço compartilhado. |
| Dados empresariais/bancários | Eram valores fixos com botão “Em breve”. Não importar placeholders, dados fictícios ou coleta financeira sem finalidade. |
| Bluetooth, Pix, timer acelerado, JSON de contas | Simulações incompatíveis com a integração atual; não portar como funcionalidades reais. |

## Execução paralela após revisão dos achados

1. **Backend:** contexto público seguro em reservas/sessões; precisão de telemetria no replay; recuperação de STOP/RELEASE falhos; leitura de reset em ponto ocupado; expiração de reset sem bloqueio eterno. Testes em PostgreSQL descartável.
2. **Consumidor:** identificação persistente de seleção; limite da reserva; atalho #F reconhecendo reserva; paginação viva; busca por modos; tempo/valor; busca salva por conta. Testes de callbacks reais.
3. **Vendedor:** estado correto do dispositivo; cadastro guiado, manutenção explicada e resumo responsivo; cupons paginados e expiração; estados honestos de pausa/restauração.
4. **Integração:** polling iniciado dinamicamente; navegação por modo; Conta/senha e ajuda interativa; revisão cruzada, regressões e inspeção visual local.

## Critérios de aceite

- Nenhuma credencial, QR privado ou segredo de presença em contexto público.
- Em contas reais, ação confirmada somente pela API/equipamento. A conta demo tem estado local explicitamente simulado, sem fallback para a API real.
- Recarga, reserva e histórico identificam o destino quando a API fornece o novo contexto.
- Formulários preservam inputs no polling; navegação protege alterações não salvas.
- Testes abrangem falha, repetição, limites, expiração e isolamento entre contas.
- Publicação remota, migração de produção, APK e gravação física no ESP são etapas distintas: só declarar realizadas com evidência.

## Entrega e validação — 27/09/2026

As quatro frentes foram implementadas e revisadas em paralelo. A revisão cruzada adicional corrigiu atalhos que abriam a gestão mantendo o modo consumidor, preservou a tarifa histórica da sessão (não a tarifa atual do ponto) e tornou honesta a mensagem sobre troca de senha: o provedor revoga a renovação, mas um JWT emitido pode continuar válido até expirar.

### Recursos recuperados/adaptados

- Recarga por tempo ou teto de valor estimado, sempre com duração máxima e confirmação do equipamento.
- Navegação contextual de vendedor, alternância de modo e histórico geral dos próprios postos.
- Busca salva por conta no dispositivo, mediante clique explícito, com remoção.
- Alteração autenticada de senha, confirmação e limpeza da sessão local.
- Chat com conversa em memória por conta, orientações locais e consultas somente leitura de recarga/reserva/histórico; substitui a seção Ajuda sem alegar IA, atendente ou registro de chamado.

### Fluxos e correções

- Posto/endereço versus ponto/equipamento explicados no vínculo; ponto adicional segue diretamente à tarifa, preservando o endereço compartilhado e a desativação do posto.
- Resumos responsivos com identidade do destino em seleção, reserva, recarga e histórico; campos de erro têm altura flexível.
- Reserva usa o limite do ponto; o atalho #F recupera reserva confirmada sem escondê-la atrás da última sessão.
- Busca por endereço/coordenadas explícita, paginação atualizada durante polling e formulário preservado.
- Cupons paginados; vencidos podem ser desativados sem reescrever data/fuso; reativação exige validade futura.
- Estado correto do dispositivo após provisionar/reprovisionar; manutenção agrupada; polling de reset inicia na tela atual.
- Replay de telemetria respeita precisão persistida; comandos STOP/RELEASE falhos são recuperados sem liberar indevidamente o ponto.
- Reset expirado não bloqueia recuperação eternamente; consulta do status em ponto ocupado não libera operações perigosas.
- Contexto de API inclui só identidade pública do posto/ponto, sem segredos/chaves de dispositivo.

### Evidências

| Validação | Resultado |
| --- | --- |
| Mobile — suíte completa com demo e revisão de UX | 288 testes + 58 subtests aprovados; 2 avisos de depreciação de campos Flet |
| API — PostgreSQL 16 descartável | 117 testes aprovados; 2 avisos de depreciação das dependências de teste |
| Ferramentas — schema criado por migrações | 44 testes aprovados |
| Alembic em banco vazio de teste | `upgrade head` aprovado |
| Ruff + `git diff --check` | Aprovados |
| Firmware — `tools/validate_firmware.py --decode-qr` | Controlador, reconciliação, limites, reset e 12 frames LVGL/QR aprovados no host |
| Prévia web | Entrada, busca compacta, reserva, início/progresso, troca de modo, vendedor e novo posto inspecionados a 390 px; Conta e campos nos temas claro/escuro a 360 px |

A primeira prévia usou fixtures somente de leitura. A prévia atual abre o aplicativo normal com uma conta demo que permite alterações em memória. Reproduzir com `PYTHONPATH=apps/mobile/src .venv/bin/python tools/preview_mobile_flows.py` e abrir `http://127.0.0.1:8855`. A inspeção visual web não equivale à homologação Android completa.

### Revisão de UX com as referências enviadas — 27/09/2026

- Três agentes dividiram início, recarga e chat; integração e revisão cruzada ficaram com o agente principal. As capturas fornecidas orientaram fundo escuro, Barlow condensada, campos claros, resumos de revisão brancos e CTAs vermelhos, sem importar telas fictícias de pagamento.
- Início prioriza reserva/recarga ativa; conta livre mostra resumo mensal, ação de recarregar e lista curta de postos. Dicas levam ao chat. Não inventa proximidade, descontos ou localização.
- Início de recarga segue **Confirmar ponto → Definir limites → Revisar recarga**. Só a revisão envia POST. Campos e modo ficam preservados em memória ao voltar e consultar histórico. Por valor mantém tempo máximo ajustável de segurança.
- Após falha de transporte, a revisão protege o mesmo corpo/chave do pedido, permite consultar estado ou repetir e impede editar limites de um início ainda não resolvido. Voltar sai ao posto/lista mantendo o pedido protegido, sem loop entre etapas.
- Reserva expirada/cancelada não prende o rascunho: é possível confirmar novamente o código no mesmo ponto sem associação à reserva antiga. Pedido incerto não sofre essa limpeza.
- Postos seguem seleção em dois níveis: lista compacta com endereço/disponibilidade e “Ver pontos”; detalhe com identidade única do posto, cartões separados por ponto, potência/tarifa/limite e ações de iniciar no local ou reservar. Não há “Tenho o código #F” nem atalho genérico equivalente no início/chat: o código rotativo deve ser lido no equipamento no momento da confirmação de presença. A disponibilidade respeita sinais negativos de posto/ponto desativado, offline, aposentado ou em falha; polling detecta alterações no mesmo objeto sem remontar a busca.
- Início agora segue resumo mensal → guia → mapa visível → Recarregar agora, conforme a posição da referência. O cartão branco no mapa abre os pontos do posto e mostra disponibilidade/tarifa conhecidas, sem inferir GPS, distância ou economia. Contas reais usam cartografia clara OSM com crédito/cache; ausência de coordenadas ou rede tem estado honesto. A demo usa recorte vetorial local da Praça da Sé com marcador nas coordenadas do exemplo; outras coordenadas não reaproveitam esse marcador.
- Revisão do mapa conforme o guia: proporção 563:389, cantos de 18 px, marcador azul-marinho com raio, cartão branco lateral com sombra e selo azul de vagas. Início e lista usam o mesmo componente; o mapa genérico compartilha moldura, cores e atribuição. Botão vermelho imediatamente abaixo no padrão compartilhado do app (48 px, texto de 16 px, espaçamento de 16 px), sem crescer em telas largas. A demo rasteriza a fonte vetorial local para preservar os nomes das vias no Flutter. Validado no preview em 390×844 e 600×1000, incluindo abertura do posto pelo cartão; redimensionamento não faz nova consulta de mapa. A faixa de atribuição foi substituída por `© OpenStreetMap` compacto no canto inferior direito, com link para a origem/licença; o crédito obrigatório não é ocultado.
- Cupom e ajuste do tempo máximo usam cartões compactos, sem as bordas e centralização do ExpansionTile. Os campos se expandem na largura do cartão, mantêm valores/estado ao fechar e voltar e têm cabeçalho com valor atual. Cupom informado não é apresentado como desconto já aplicado. A revisão também corrigiu o nome da propriedade de ícone Flet para que a seta acompanhe a expansão.
- Chat substitui a seção Ajuda, mantém conversa e rascunho por conta e consulta somente leitura de histórico/reserva/recarga. Identifica dados simulados, custo estimado e escopo pessoal versus vendedor. Não envia perguntas a modelo externo nem registra chamados.
- A rolagem nativa acompanha a última resposta após o layout, inclusive ao retornar ao chat; novas mensagens são acrescentadas sem remontar as anteriores. O Guia oferece uma pergunta sugerida, enviada somente após o toque do usuário em “Perguntar” no chat montado. A inspeção visual confirmou três perguntas e sete mensagens preservadas: o problema investigado era a posição da rolagem, não perda da conversa. O teste de serialização também verifica a estabilidade dos controles existentes.
- Conta abre em modo de leitura e tem edição explícita. Navegação protege alterações não salvas. Dados selecionáveis e bolhas têm rótulos de acessibilidade.
- Logout, login e expiração descartam rascunhos/conversa e também chaves/IDs operacionais da conta anterior; preferência de tema é preservada.
- Testes completos do mobile e Ruff passaram. Prévia inspecionada a 390 × 844 e 360 × 800: etapas, retorno com limites preservados, início simulado após revisão, chat com dados da conta e edição protegida. API/firmware não foram alterados nesta revisão visual; evidências anteriores permanecem acima.

### Conta demo e direção visual do Figma

- Entrada por botão dedicado ou `demo@chargegrid.example` / `demo1234`; credenciais reconhecidas localmente, sem cadastro no Supabase.
- Estado separado por instância e reiniciado ao sair/reconectar; perfil, equipamentos, cupons, reserva, recarga e histórico modificáveis somente em memória.
- Alternância consumidor/vendedor em Conta; vínculo simulado sem câmera, manutenção fictícia e código `#F12345` explícito.
- Progresso por relógio injetável, respeitando duração e teto de custo; consultas não avançam a simulação por contagem de polling.
- Mapa local geográfico da Praça da Sé na tela inicial (dados OSM vetoriais, com crédito); visão esquemática explícita nos demais locais. Busca pelos locais de exemplo; nenhum HTTP/geocoding/download de tiles ou persistência de busca na execução da demo. O gerador de desenvolvimento consulta uma área pública limitada via Overpass, fora do aplicativo.
- A prévia não possui dropdown de cenários; usa os mesmos fluxos e navegação do aplicativo.
- Na lista de postos, a busca fica recolhida inicialmente e o mapa aparece uma única vez, antes dos resultados, sem o dropdown redundante “Ver mapa dos postos”. O detalhe prioriza pontos e ações, sem repetir o mapa do posto selecionado. O polling preserva filtros e expansão da busca e atualiza o cartão do mapa quando nome, tarifa ou disponibilidade mudam. A revisão visual corrigiu contraste das dicas e rótulos que cruzavam a borda dos campos.
- Contextos e screenshots do Figma `Core (Projeto)` (`CdhvPkmGhIvy3l1roJNino`), lista de vendedor `365:3786` e edição `365:3859`, orientaram cartões compactos, cantos de 4 px, Barlow, campos brancos e navegação discreta. Marca e ícones SVG originais ficam em `apps/mobile/assets/figma/`.
- O Figma atingiu o limite de leituras do plano após esses dois contextos. A direção foi aplicada aos componentes compartilhados; não se afirma fidelidade de telas cujo contexto não pôde ser obtido.

**Não realizados:** commit/push, deploy/migração remota, geração de APK, gravação no ESP e teste físico ponta a ponta. Código e correções anteriores permanecem preservados no workspace. Antes de distribuir o novo app, publicar a API compatível com o contexto de reserva/sessão e o histórico geral de vendedor.
