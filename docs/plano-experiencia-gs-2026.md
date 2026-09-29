# ChargeGrid — plano de experiência e diferenciação para a Global Solution

Data: 29/09/2026. Status: P0 + P1 implementados e roteiro de demonstração atualizado após aprovação do usuário. Verificação local registrada em `validacao-experiencia-gs.md`. P2 permanece como segunda entrega; validação com usuários/banca e novo ensaio físico não foram realizados.

## Objetivo e premissas

Transformar a integração existente entre aplicativo, API e ESP32 em uma experiência fácil de entender, demonstrar e defender perante a banca. Direção proposta: **ChargeGrid — Recarga com confirmação, do app ao ponto.**

O enunciado, a rubrica e o prazo da turma ainda precisam ser informados. A FIAP apresenta a Global Solution como desafio prático voltado a problemas reais e impacto social, mas isso não substitui os critérios específicos da edição: https://www.fiap.com.br/graduacao/gustavoguanabara/ . O plano abaixo considera o escopo atual de mobilidade elétrica do repositório; sua aderência ao tema oficial permanece pendente.

Preservar Flet, FastAPI, PostgreSQL e o protocolo atual. A bancada usa energia e bateria simuladas; não entrega energia a veículo nem processa pagamentos. Melhorar competitividade é uma hipótese de produto, não uma promessa de premiação.

## Diagnóstico consolidado

Três subagentes trabalharam somente em análise: UX/UI, produto e funcionalidades, marca e demonstração. O orquestrador revisou código/documentação, abriu a conta demo na prévia web local e executou a suíte mobile.

| Observação | Evidência | Consequência |
| --- | --- | --- |
| Confirmação pelo equipamento, reconciliação, limites e parada local já existem. | README e docs/demo.md; serviço de estados da API. | O diferencial pode ser exposto na interface e na demonstração, sem reconstruir a integração. |
| Home prioriza resumo financeiro e guia antes da ação principal. | apps/mobile/src/chargegrid_app/screens/home.py; prévia web local. | No viewport observado de 1280 × 720, com conteúdo central de 600 px, a ação ficou abaixo da dobra. Falta validar os tamanhos de celular. |
| Lista exige abrir detalhes para consultar tarifa, potência e conector. | apps/mobile/src/chargegrid_app/screens/stations.py:199–233. | Comparação de opções exige navegação adicional. |
| API ordena postos por identificador; distância apenas restringe o raio. | apps/api/app/modules/stations/routes.py:29–56. | A seleção inicial não prioriza a opção mais próxima ou econômica. |
| Falha de atualização não tem indicação persistente uniforme. | apps/mobile/src/chargegrid_app/app.py:364–379. | Um estado antigo pode continuar parecendo atual em home/lista. |
| Alguns pares de cor no tema escuro têm contraste baixo. | ui/theme.py e ui/components.py; branco sobre verde #34C759: aproximadamente 2,22:1. | Separar cores de fundo e texto por função e verificar ambos os temas. |
| Há lacunas a investigar em seleção de abas e foco. | app.py e componentes; árvore de acessibilidade da prévia. | A prévia já expõe controles clicáveis como botões; não foi comprovada ausência de papel. Validar seleção, teclado e leitor de tela. |
| Painel escreve “kWh entregues” para dados que podem ser simulados. | apps/mobile/src/chargegrid_app/screens/operator.py:82. | Corrigir linguagem e separar origem nos agregados para sustentar a credibilidade. |
| Marca e vocabulário variam entre telas. | auth.py, app.py, onboarding.py e operator.py. | Unificar aplicação da marca e termos: posto é o local, ponto é o equipamento. |
| Captura de home do README está desatualizada. | docs/images/app-home-previa.png versus código e prévia. | Refazer evidências visuais depois da implementação aprovada. |

Validação atual: **288 testes e 58 subtestes mobile passaram**, com dois avisos de depreciação de propriedades Flet. Não foram executados nesta auditoria testes da API, novo APK, ensaio físico ou deploy. Os resultados de hardware existentes são evidências documentadas de versões anteriores.

## Escopo recomendado

### P0 — Experiência e marca

- Home com próxima ação no topo: encontrar ponto, acompanhar reserva ou retomar sessão conforme o estado da conta.
- Resumo mensal secundário; mapa e lista trabalhando juntos, sem exigir rolagem para descobrir como começar.
- Sistema visual coerente: preservar vermelho e Barlow, melhorar hierarquia, espaçamento, superfícies, contraste e estados.
- Componente único de marca; mensagem curta de valor na entrada; padronização de motorista, operador, posto e ponto.
- Estados de espera, vazio, falha, falta de conexão e recuperação com uma ação clara.
- Acessibilidade: foco, teclado, seleção de abas, texto ampliado, leitor de tela e movimento reduzido.

Aceite: ação principal visível em 360 × 800 no tamanho padrão de texto; com ampliação, conteúdo acessível sem corte ou sobreposição. Contraste mínimo proposto de 4,5:1 para texto comum e 3:1 para texto grande e elementos pertinentes. Cor nunca será a única indicação de estado.

### P1 — Escolha assistida de ponto

Filtros por conector, disponibilidade e tarifa máxima; ordenação por proximidade e preço. Cards exibem tarifa válida, potência nominal, conector e distância aproximada quando houver referência. A recomendação explica seu motivo, por exemplo “menor tarifa entre estes resultados”.

Filtros e ordenação devem ocorrer na API antes da paginação, com comportamento equivalente no cliente demo. Conectores devem ter valores normalizados. Em postos com vários pontos, preço e disponibilidade destacados devem corresponder a um mesmo ponto que satisfaça os filtros.

Aceite: mapa e lista concordam; paginação não muda o significado da ordenação; ponto indisponível não recebe chamada de reserva como se estivesse livre. Distância em linha reta é identificada como tal. Sem localização, não afirmar “mais próximo”.

Complexidade: média; envolve API, cliente, demo e telas. Não exige firmware.

### P1 — Planejamento antes da reserva

Permitir informar “até R$ X” ou “tenho Y minutos” antes de escolher o ponto e comparar estimativas. A seleção transfere a intenção para o wizard de recarga que já existe, evitando preencher tudo novamente.

Primeiro corte: intenção temporária, sem exigir novo cadastro de veículo. Cálculo compartilhado com a revisão da recarga, com hipóteses e limites explícitos. Potência nominal não será apresentada como potência garantida; não prometer parada por percentual de bateria.

Aceite: as mesmas entradas produzem a mesma estimativa no comparador e na revisão; revalidar tarifa, disponibilidade e limites ao confirmar; não perder campos ao voltar.

Complexidade: média. Persistência de plano/veículo e comparação posterior ficam fora deste corte.

### P1 — Confirmação e recuperação visíveis

Apresentar a jornada “Solicitado → Confirmado pelo ponto → Em andamento → Encerrado”, usando os fatos efetivamente disponíveis. Mostrar a última atualização e, quando necessário, “Não conseguimos atualizar — exibindo o último estado conhecido”.

Para uma linha do tempo histórica completa, primeiro fechar e implementar persistência de eventos e horários na API. Não inferir horário de confirmação a partir do momento em que o app abriu a tela. Expor somente dados apropriados ao usuário.

Aceite: nunca antecipar confirmação do dispositivo; manter medição anterior identificada quando faltar conexão; explicar a próxima ação; reconciliação não libera o ponto por suposição. Preservar regras de presença, propriedade, idempotência e concorrência.

Complexidade: média; pode subir se aprovada a trilha histórica completa. Primeira entrega usa estado atual e horários disponíveis.

### P2 — Histórico e operação

- Histórico compacto, com filtros por período e resultado e detalhe legível de cada sessão.
- Resumo de sessão com local, duração, energia registrada, custo estimado, origem e motivo do encerramento. Não é comprovante de pagamento.
- Painel do operador priorizando pontos offline, em falha ou reconciliação; corrigir “kWh entregues” e distinguir simulação nos agregados.
- Agregações no servidor, com autorização por titular/operador e períodos claramente definidos.

Aceite: fontes não se misturam em uma alegação de energia real; fuso e período coerentes; operador não acessa dados de outro operador. Não apresentar porcentagem histórica de disponibilidade sem eventos suficientes para calculá-la.

Complexidade: média. Pode ser entregue depois do núcleo se o prazo for curto.

## Demonstração e evidência para a banca

Roteiro sugerido de aproximadamente quatro minutos, a ajustar ao regulamento:

1. Explicar a hipótese de dor: incerteza ao escolher um ponto e acompanhar a confirmação.
2. Comparar opções por conector e orçamento, selecionar e reservar.
3. Mostrar a confirmação no app e no painel físico; iniciar a bancada com limite.
4. Interromper a comunicação de forma controlada, mostrar o aviso, a parada local e a reconciliação após retorno. Respeitar o prazo real do watchdog.
5. Abrir o resumo da sessão e a visão do operador; distinguir integração real de medições simuladas.

Preparar demo isolada reproduzível, evidências da versão entregue e gravação de apoio claramente identificada. Nenhuma falha física será provocada sem escopo e equipamento adequados.

Proposta de avaliação de usabilidade: cinco participantes realizam escolher ponto, reservar, iniciar e interpretar perda de conexão. Registrar conclusão sem ajuda, erros, tempo e compreensão dos estados, antes/depois quando possível. Isso será evidência exploratória, sem generalização estatística. Recrutamento e contato dependem de organização com o usuário; agentes não substituirão participantes reais.

Preparar matriz “critério da rubrica → funcionalidade → evidência”, hipótese de público/adotante, proposta de piloto e métricas. Esses itens dependem do enunciado e de validação, não serão preenchidos com resultados inventados.

## Orquestração após aprovação

No máximo três subagentes simultâneos, com o agente principal responsável por contratos, coordenação, integração e revisão. As frentes abaixo são papéis, não cinco agentes concorrentes.

| Ordem | Responsável | Entrega e limite de edição |
| --- | --- | --- |
| 1 | Agente de design e marca | Tokens, componentes comuns, aplicação da marca, navegação e home. |
| 1 | Agente de API/produto | Contratos, filtros/ordenação, proveniência e testes da API. Único responsável por modelos e migrações. |
| 1 | Agente de qualidade e narrativa | Cenários de aceite, roteiro e matriz de evidências; sem alterar telas ou contratos compartilhados. |
| 2 | Agente de descoberta | Após contratos/componentes: busca, comparação, planejamento, cliente HTTP e equivalência demo. |
| 2 | Agente de jornada | Reserva/recarga, atualização, recuperação e histórico, com arquivos separados da descoberta. |
| 2 | Agente de operação | Painel e agregados após disponibilidade da API; em vaga liberada na equipe. |
| 3 | Agente de revisão | Regressões, acessibilidade, verificação visual, integração e documentação da versão. |

Não haverá edição concorrente de app.py, api_client.py, demo.py, componentes ou modelos. Cada arquivo compartilhado terá um responsável por vez; mudanças necessárias serão encaminhadas a esse responsável. Congelar contratos antes de integrar consumidores.

Cada entrega incluirá arquivos alterados, decisões, critérios atendidos, testes e limitações. Revisão reprova confirmação falsa, quebra de autorização, duplicação de comandos ou divergência entre demo e contrato real.

## Validação de entrega

- Suíte mobile e lint; testes da API com PostgreSQL descartável para filtros, paginação, acesso, concorrência e fluxo de comandos.
- Prévia em telas pequenas e grandes, temas claro/escuro, texto ampliado, teclado e leitor de tela.
- Cenários de falha/retomada pelo simulador e, quando disponível, ensaio separado no ESP32.
- APK e backend compatíveis, documentação e capturas correspondentes à versão entregue. Publicação e mudanças de ambiente serão tratadas conforme o escopo aprovado.

## Recorte da aprovação

Recomendação: aprovar P0 + P1 + demonstração como núcleo e P2 como segunda entrega condicionada ao prazo. Permanecem fora do primeiro ciclo pagamentos, IA externa, previsões de fila, hardware de potência e alegações de CO₂ evitado. Qualquer expansão exige problema, fonte de dados e critério de validação definidos.

O usuário aprovou a execução e solicitou também verificações contra bugs e problemas. A equipe foi mobilizada em três frentes: design/home, descoberta/planejamento/API e confirmação/recuperação. O orquestrador prepara ambientes descartáveis, revisa a integração e registra as evidências.
