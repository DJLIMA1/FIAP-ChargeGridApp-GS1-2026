# Diretrizes do planejamento de funcionalidades ChargeGrid

Planejamento solicitado em 1 de outubro de 2026 após a comparação dos doze pitches da banca GoodWe FIAP. O trabalho desta rodada produz propostas de implementação e critérios de aceite. Não altera código, banco, firmware ou ambientes publicados.

## Escopo confirmado pelo usuário

- RFID fica excluído.
- A aba Chat dentro do aplicativo deve usar um modelo gratuito do OpenRouter, facilmente substituível, junto de MCP para compartilhar o padrão e evitar duplicação de regras. O mesmo MCP deve ter endereço público e acesso seguro para outras IAs fora do aplicativo. Esta preferência foi esclarecida pelo usuário durante a rodada; não há decisão pendente sobre as duas experiências. MCP é a interface de ferramentas, não o modelo de IA.
- Exportação deve oferecer múltiplas opções e formatos, junto de indicadores comerciais.
- Medição e controle devem funcionar por simulação em código neste ciclo, deixando uma fronteira preparada para futura integração autorizada com SEMS+.
- Separação entre solar e rede fica fora deste ciclo, inclusive como dependência obrigatória da gestão de demanda, da previsão e dos relatórios.

## Frentes dedicadas

1. Simulação de medição e controle e preparação para SEMS+.
2. Gestão agregada da demanda e balanceamento.
3. Pagamentos e conciliação.
4. Tarifação por horário e condições de demanda.
5. Carteira e saldo.
6. Notificações, liberação, fila e overstay.
7. Chamados e atendimento humano.
8. Chat com IA por MCP.
9. Indicadores e exportação em diferentes formatos.
10. Previsão de demanda energética.

O planejamento de carteira e previsão não significa que sejam prioridade de implementação imediata. A sequência final depende das necessidades da banca, da experiência e das dependências entre módulos.

## Base a preservar

Preservar Flet, FastAPI, PostgreSQL, autenticação, propriedade do equipamento, reservas, idempotência, ACK, eventos observados e reconciliação. Existem mudanças locais ainda não commitadas. Não executar deploy, migrações remotas, transações financeiras ou atuação física nesta rodada.

O painel atual utiliza sensores simulados com potência de 7.200 W durante carga. O protocolo não possui um comando de ajuste dinâmico de potência. O cálculo e o controle novos precisam distinguir estado desejado, aplicação confirmada e medida observada; configuração nominal não comprova aplicação.

Firmware sincroniza a cada cinco segundos em recarga e dez fora dela; após 45 segundos sem contato, a bancada encerra localmente. O servidor não transforma ausência de comunicação em confirmação de parada. Dados devem manter origem explícita: simulados, medidos ou estimados. A mudança de adaptador não autoriza reclassificar dados simulados como medidos.

## Entregas esperadas de cada frente

Cada plano deve inspecionar os arquivos relevantes e incluir estado atual, proposta mínima, etapas, responsabilidades de app/API/dispositivo, contratos propostos, dependências, cenários de falha, critérios de aceite e demonstração para a banca. Caminhos existentes e fatos devem ser verificáveis; novos endpoints e esquemas devem ser identificados como propostas.

Pesquisas externas devem usar fontes primárias e separar recursos documentados de hipóteses. Não supor endpoints, permissões ou protocolos de integração SEMS+ sem documentação oficial. Não assumir que IA, pagamento, ocupação física ou indicadores financeiros já estejam implementados.

Cada responsável escreve somente seu documento de planejamento, sem alterar arquivos compartilhados. O documento consolidado registra a ordem e as decisões comuns após revisão das dez frentes.

## Decisões comuns de integração

O backend permanece a autoridade para identidade, propriedade, preços e estados. O MCP deve reutilizar os serviços de negócio; o chat interno e clientes externos consomem o mesmo contrato de ferramentas. Um endereço público não libera sessões, dados financeiros ou operações sem autenticação e autorização. O modelo nunca determina o titular pelo texto do usuário.

OpenRouter é o provedor solicitado para o chat. Catálogo gratuito, suporte a chamadas de ferramentas e limites precisam ser verificados na implementação; o plano deve prever troca de modelo por configuração e indisponibilidade sem migrar silenciosamente para modelo pago. Credenciais ficam no backend.
