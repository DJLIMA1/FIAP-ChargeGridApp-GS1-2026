# Planejamento consolidado de funcionalidades do ChargeGrid

Planejamento de 1 de outubro de 2026, elaborado por dez subagentes dedicados após a análise dos doze pitches GoodWe FIAP e a inspeção do aplicativo. Os documentos descrevem propostas, dependências e critérios de aceite; não representam funcionalidades já implementadas. Esta rodada não altera o produto, o banco, o firmware ou ambientes publicados.

O objetivo é demonstrar uma jornada coerente: encontrar o ponto, entender e aceitar o preço, iniciar uma recarga simulada sob um limite de instalação, consultar o mesmo estado no app e em outra IA, receber avisos e obter um relatório verificável. Carteira e previsão entram depois que essa jornada estiver estável.

## Preferências incorporadas

- **RFID excluído.** O fluxo atual de propriedade e presença por QR continua como base.
- **Chat no app com IA gratuita do OpenRouter**, modelo substituível por configuração e execução das ferramentas pelo mesmo MCP usado externamente. O endereço MCP deverá ser público via HTTPS, com acesso autenticado, consentimento e permissões por conta/posto. Não há fallback pago silencioso.
- **Exportação com opções e quatro formatos:** CSV, JSON, XLSX e PDF, compartilhando filtros, seleção de colunas, prévia, agregados e regras de acesso.
- **Medição e controle simulados em código agora**, com potência variável e evidência de aplicação. A fronteira de adaptadores prepara SEMS+, sem inventar endpoints ou apresentar integração real como pronta.
- **Separação solar/rede adiada.** Não será dependência da gestão de demanda, previsão ou relatórios.

As [diretrizes](00-diretrizes.md) registram o escopo comum. A [análise dos pitches](../analise-pitches-goodwe-fiap-2026.md) preserva a origem competitiva das propostas; o ranking é uma avaliação da transcrição, não resultado oficial da banca.

## Uma frente por subagente

| Frente | Entrega planejada | Dependência principal | Prioridade sugerida |
|---|---|---|---|
| [01 — Simulação e SEMS+](01-simulacao-sems.md) | Medição variável, controle confirmado e adaptador futuro | Contrato de potência e evidências do dispositivo | Base imediata |
| [02 — Gestão de demanda](02-demanda.md) | Limite agregado, distribuição justa e explicação das decisões | Simulador com redução/pausa confirmadas | Diferencial central |
| [03 — Pagamentos](03-pagamentos.md) | Checkout sandbox, conciliação e devolução da sobra | Orçamento aceito, término validado, executor durável | Jornada comercial |
| [04 — Tarifação](04-tarifacao.md) | Regras por horário e preço congelado no aceite | Orçamento compartilhado com pagamento/sessão | Jornada comercial |
| [05 — Carteira](05-carteira.md) | Créditos e saldo separados por origem, ledger e reservas | Pagamento avulso e acerto estáveis | Posterior |
| [06 — Notificações e overstay](06-notificacoes-overstay.md) | Inbox, aviso de liberação, fila e permanência após fim | Eventos persistidos e conexão independente da carga | Experiência da demo |
| [07 — Atendimento](07-suporte.md) | Chamado, contexto técnico autorizado e resposta humana | Identidade, histórico e eventos permitidos | Experiência da demo |
| [08 — OpenRouter e MCP](08-chat-mcp.md) | IA interna e acesso externo ao mesmo catálogo autorizado | Serviços comuns, modelo gratuito e OAuth compatível | Diferencial central |
| [09 — Relatórios](09-exportacao-indicadores.md) | Indicadores, prévia e CSV/JSON/XLSX/PDF consistentes | Agregação única e proveniência dos dados | Diferencial central |
| [10 — Previsão](10-previsao-demanda.md) | Estimativa de demanda com cobertura e incerteza | Histórico por intervalo suficiente | Posterior |

Todos os planos incluem a base atual, mudanças propostas, responsabilidades, falhas, etapas e critérios de aceite. As prioridades acima refletem dependência e valor de demonstração; não estimam prazo ou esforço sem dimensionamento da equipe.

## Contratos que precisam ser únicos

**Identidade e autorização.** REST, MCP e chat usam os mesmos serviços de negócio com contexto autenticado. O modelo não escolhe titular ou operador pelo texto. Consultas de dados pessoais continuam limitadas ao titular; operadores veem somente os postos permitidos e projeções técnicas necessárias. O JWT atual do app não vira automaticamente um token OAuth para o recurso MCP.

**Preço e financiamento.** Um `charging_quote` reúne ponto, validade, versão da regra, tarifa, desconto, duração e teto em centavos. O aceite congela o snapshot; pedido e sessão reutilizam esse contrato. Mudança de horário, balanceamento ou atualização de preço não modifica silenciosamente um aceite existente. Alterar condições exige orçamento e aceite novos. Novas rotas REST propostas seguem o prefixo `/v1` do projeto.

Separar prazo para aceitar a oferta, prazo para pagar e prazo/condições para iniciar. A proposta de cinco minutos para aceite não expira automaticamente um pedido já aceito durante o checkout. Reserva mantém sua regra vigente e não congela preço nem renova por pagamento. Cupom incorporado no aceite segue o snapshot, sem revalidação silenciosa de preço no START.

Pagamento avulso é a primeira forma de financiar a sessão; carteira não é pré-requisito. Quando ela existir, usar uma referência de financiamento tipada para distinguir pedido do gateway e reserva de saldo. Um hold de carteira não deve criar um pagamento fictício confirmado. Separar dinheiro adiantado, custo estimado, consumo final e restituição devida/concluída. Depósito de carteira não é receita de recarga.

**Potência e medição.** Potência nominal, desejada, aplicada e observada são fatos distintos. Redução solicitada não libera capacidade para outro carro antes da confirmação necessária. START incorpora o limite inicial antes de energizar; ajuste de potência não sobrescreve START, STOP ou RELEASE pendentes. Energia acumulada considera potência efetivamente aplicada ao longo do tempo. Ausência de comunicação não confirma parada nem permite extrapolar energia para cobrar.

**Pausa, término e liberação.** Pausa do balanceamento conserva a sessão e a conexão; não dispara overstay. Fim da recarga não significa cabo desconectado. Para a demo, simular conexão independentemente de potência, permitindo um veículo permanecer conectado após o fim. Sem sensor de vaga, desconexão do cabo é um proxy identificado; não comprova que o estacionamento está vazio. Fila e avisos precisam respeitar o estado realmente observado e sua validade.

**Proveniência e finanças.** `measurement_source` distingue simulado, medido e estimado; `payment_environment` distingue mock, sandbox e produção. Esses eixos são independentes. Troca de adaptador não reclassifica histórico. Custos ausentes não viram zero, soma de estimativas não vira receita e redução de pico não prova economia de kWh.

Relatórios de consumo por horário e previsão exigem agregados por intervalo, não apenas totais finais. A manutenção disponível pode remover telemetria após sete dias quando executada com `--apply`; não há comprovação de que essa limpeza esteja ativa. Produzir agregados duráveis com cobertura e proveniência antes de qualquer remoção. O alvo inicial da previsão é W médio dos carregadores em janelas de cinco minutos, horizonte de 30–60 minutos; isso não representa pico instantâneo ou demanda faturável.

**Eventos e execução durável.** Eventos de negócio, inbox/outbox, idempotência e processamento após commit devem ser infraestrutura compartilhada para pagamentos, avisos e atendimento. A função atual tem limite de 30 segundos: nada que dependa de continuidade pode usar apenas um timer ou tarefa em memória após a resposta. Grandes exportações exigem executor e armazenamento privados, ou limite explícito de volume enquanto eles não existirem.

Antes das migrações, fechar também uma ordem única de aquisição de locks para os recursos de cada fluxo. Os planos de carteira/fila preservam perfil antes de ponto; o balanceamento acrescenta instalação/circuitos. A ordem combinada precisa evitar que um worker segure ponto ou carteira e depois solicite um recurso adquirido antes por outro fluxo. Ordenar conjuntos por ID, revalidar sob lock e nunca manter uma transação aberta aguardando gateway, usuário ou dispositivo.

## Ordem recomendada

1. **Fechar contratos e duas provas pequenas:** potência variável confirmada no simulador; consultas MCP iguais para duas contas isoladas, com um modelo gratuito validado. Validar SDK/revisão MCP, servidor OAuth, middleware e limites Vercel antes de expandir catálogo.
2. **Entregar simulação + gestão de demanda:** testar três carros, limite agregado, redução confirmada antes do aumento e falha de conexão. Registrar decisões para explicação no app/MCP e nos relatórios.
3. **Entregar relatórios e chat sobre fatos existentes:** agregação operacional única, filtros e quatro formatos. Chat inicialmente consultivo, com referências, origem, horário e fallback local identificado. A consulta MCP deve ser um snapshot sem emitir comandos por efeitos laterais de expiração.
4. **Completar preço e pagamento avulso:** tabela por horário, orçamento congelado, checkout sandbox, webhook autenticado, acerto e restituição. Relatórios financeiros só entram com os fatos da conciliação; a demo pode continuar operacional se a homologação externa não estiver pronta.
5. **Completar avisos, fila e suporte:** inbox durável, liberação observada, permanência após fim e atendimento com contexto permitido. Primeiro overstay informa; cobrança exige condições aceitas e evidências adicionais.
6. **Adicionar carteira e previsão se houver margem:** créditos de demonstração separados do dinheiro e estimador simples comparado a um baseline. Não expandir essas frentes antes dos aceites da jornada principal.

As etapas podem avançar em paralelo quando compartilham contratos já fechados. A sequência não obriga concluir todos os pagamentos antes de começar relatórios operacionais ou o MCP consultivo.

## Demonstração sugerida para a banca

Usar dados e cenários identificados como simulados. Mostrar três carros dividindo a capacidade; elevar a carga do prédio e explicar a redução/pausa com base no registro da decisão. Iniciar uma sessão com preço aceito, observar a potência aplicada e encerrar mantendo o cabo conectado para demonstrar aviso de permanência. Desconectar, ofertar a vaga à fila e expirar a oferta sem reserva automática indevida.

Perguntar no chat o que ocorreu e repetir a consulta em um cliente MCP externo autenticado. A resposta deve usar os mesmos fatos e não disparar comandos físicos. Exportar XLSX e PDF do período, mostrando números iguais aos do app; CSV e JSON ficam disponíveis para análise e integração. Se o pagamento sandbox estiver homologado, incluir teto pré-pago, consumo final simulado e restituição confirmada, com rótulos distintos para energia e ambiente financeiro.

O argumento competitivo é a coerência entre controle, transparência e interoperabilidade. Cada promessa exibida precisa ser sustentada por estado observado, registro ou integração demonstrada. A previsão só será apresentada como validada se superar uma referência simples em dados não usados no ajuste.

## Pendências para a implementação

- Definir teto/circuitos/margem e validade das observações de carga predial; não ativar uma configuração elétrica desconhecida.
- Selecionar modelo gratuito com ferramentas, autorização OAuth e clientes externos que farão parte da matriz de compatibilidade. A revisão MCP deve ser fixada e testada, conforme o [plano específico](08-chat-mcp.md).
- Homologar conta sandbox, checkout, eventos e estorno no provedor; manter o adaptador mock identificado para desenvolvimento local.
- Definir executor durável, cotas, retenção e limites de volume dos relatórios e eventos.
- Definir operadores responsáveis por atendimento e revisão financeira; prazos propostos não são garantias já existentes.
- Obter documentação, permissões e capacidades efetivas SEMS+/GoodWe antes de implementar qualquer adaptador real.

Essas decisões não bloqueiam o planejamento entregue. Nenhuma publicação, pagamento ou integração real foi executada nesta rodada.
