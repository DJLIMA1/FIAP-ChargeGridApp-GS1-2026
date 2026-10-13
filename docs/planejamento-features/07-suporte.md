# Chamados e atendimento humano

Planejamento de 01/10/2026. Propõe implementação futura; não cria chamados, envia mensagens, altera código ou concede acesso nesta rodada. RFID e separação solar/rede ficam excluídos.

## Estado atual e objetivo

[Ajuda local](../../apps/mobile/src/chargegrid_app/screens/help.py) oferece orientação determinística e declara que não abre chamados. O [chat](../../apps/mobile/src/chargegrid_app/screens/chat.py) consulta recursos da própria conta, sem IA externa nem atendimento humano. Não existem modelos, rotas ou fila persistente de suporte.

[Eventos de sessão](../../apps/api/app/modules/charging/routes.py) são exclusivos do motorista titular. Operadores habilitados consultam histórico dos próprios postos; isso não autoriza entregar o endpoint de eventos pessoais a eles. [Propriedade](../../apps/api/app/service.py) e [autenticação](../../apps/api/app/security.py) permanecem autoridades.

O MVP deve permitir relatar um problema, obter protocolo persistente e acompanhar uma resposta humana do operador responsável pelo posto. Precisa funcionar sem IA: o assistente facilita o preenchimento, mas não é requisito para criar ou acompanhar o chamado.

## Fluxo mínimo e fila real

Adicionar “Relatar problema” em detalhes da recarga, ponto e posto. Sessão e ponto são vínculos opcionais; para encaminhar ao operador, o posto responsável deve estar definido. Categorias iniciais: início/parada pendente, conexão/telemetria, reserva, divergência de valor e outra ocorrência naquele posto. Dúvidas gerais de conta continuam na ajuda local enquanto não houver uma equipe administrativa cadastrada; não gerar protocolo que prometa um destinatário humano inexistente.

Motorista revisa categoria, descrição curta, posto, contexto técnico selecionado e quem o receberá. Confirmar cria protocolo e mostra “enviado ao operador do posto; aguardando atendimento”. Não anunciar atendimento imediato, horário ou SLA sem acordo real. Mesmo com fila habilitada, ausência de atendente online não significa abandono: mostrar última movimentação e manter a espera explícita.

Operador ganha painel dos chamados dos seus postos, filtros por estado/categoria e ordem por abertura. No MVP, atribuição é ao proprietário autenticado; não inventar agentes com permissão global. Ele assume o chamado, responde uma orientação curta, solicita esclarecimento ou registra resolução. O titular acompanha e pode acrescentar esclarecimento ou reabrir uma resolução. Conversa contínua, múltiplos atendentes e anexos ficam para fases posteriores; comentários curtos persistidos bastam.

## Estados e eventos auditáveis

Estados propostos: `open`, `in_progress`, `awaiting_user`, `resolved`, `closed`. Assumir passa para atendimento; solicitar esclarecimento indica espera do titular; responder devolve ao atendimento; resolução exige texto e autor. Titular pode reabrir `resolved` ou encerrar voluntariamente. Após `closed`, novo chamado referencia o anterior. Resolução administrativa não modifica recarga, disponibilidade, pagamento ou estorno.

Registrar eventos append-only: abertura, assunção, comentário, mudança de estado, resolução, reabertura e revogação de contexto. Protocolo, horários UTC, versão e autoria permitem reconstruir a sequência. Corrigir resposta ou resolução usa novo evento com referência ao anterior, sem reescrever o histórico. Uma política futura de retenção/redação de conteúdo pessoal deve coexistir com a auditoria mínima; “append-only” não significa guardar segredos indefinidamente.

## Contexto técnico e acesso

Backend monta contexto a partir de recursos autorizados, sem aceitar fatos técnicos fornecidos pelo modelo como evidência. Envelope proposto: `schema_version`, `source`, `as_of`, referências internas, `data` e `warnings`. Mostrar ao titular o que será compartilhado e guardar versão da autorização com o chamado.

Projeção mínima ao operador: identificação pública do ponto, estado da sessão relacionado ao incidente, solicitação pendente/confirmada, última atualização, origem simulada/medida/estimada e código técnico conhecido. Valores necessários à divergência incluem tarifa aceita e estimativa claramente rotulada; confirmação financeira só entra depois da frente 03. Não copiar conversa inteira, histórico de deslocamentos, outras sessões ou todos os eventos pessoais. Uma lista pequena de fatos permitidos é produzida pelo serviço de suporte, sem abrir a rota privada de eventos.

Excluir `device_key`, token JWT, QR de vinculação, código de presença, telefone e dados bancários. Referência de sessão não concede leitura irrestrita. Usuário sem sessão vinculada pode descrever problema de um ponto publicamente disponível, sem receber informação sobre quem o ocupa.

Validar autorização em cada leitura e escrita. Operador precisa estar habilitado, ser destinatário do chamado e continuar proprietário do posto. Perda de propriedade revoga seu acesso; novo dono não herda automaticamente conteúdo pessoal anterior. Titular conserva acesso e vê encaminhamento suspenso. Reencaminhar exige revisão do destinatário/contexto pelo titular e novo evento. Solicitação administrativa de desligamento ou devolução financeira segue seus próprios serviços e confirmações, fora do suporte.

## Contratos propostos

Propor `apps/api/app/modules/support/` com serviço único consumido por REST e MCP. Tabelas futuras: `support_tickets` com titular, posto, vínculos opcionais, destinatário, protocolo, categoria, estado e versão; `support_events` com chave deduplicada, autoria, tipo e conteúdo limitado; `support_context_snapshots` com projeção/versionamento e autorização. Não reutilizar `SessionEvent` para mensagens: fatos da recarga e atendimento têm domínios distintos.

Endpoints sob `/v1`: `POST /support-tickets`, `GET /me/support-tickets`, `GET /support-tickets/{id}`, `GET /operator/support-tickets`, `POST /support-tickets/{id}/comments` e `POST /support-tickets/{id}/transitions`. Listas são paginadas; resposta inclui protocolo, versão, estado, destinatário e últimas movimentações permitidas. Toda mutação recebe `Idempotency-Key`; mesma chave/corpo retorna a operação existente, corpo diferente gera conflito. Transições também recebem `expected_version`, evitando resolução e reabertura concorrentes silenciosas.

Proposta inicial de limites: descrição até 1.000 caracteres, comentário até 1.500, categorias enumeradas e rate limit por titular. A [API atual](../../apps/api/app/main.py) limita corpo a 16 KB; não colocar binários ou conversa completa no JSON. [Vercel](../../apps/api/vercel.json) possui janela de 30 segundos: criação e resposta são transações curtas, sem esperar modelo, push ou atendente.

Gravar evento e trabalho na `notification_outbox` da frente 06 na mesma transação. Após commit, executor durável gera inbox deduplicada para destinatário autorizado. Falha de notificação não desfaz chamado: consultas continuam mostrando seu estado. Polling usa o coordenador comum, sem outro timer concorrente; app fechado não recebe promessa de alerta até existir entrega externa validada.

## IA, falhas e responsabilidades

Seguir a frente 08: OpenRouter gratuito e substituível, ferramentas MCP compartilhadas. `prepare_action` prepara formulário; `get_help` orienta; consultas de suporte usam os mesmos serviços e escopos. Usuário revisa antes de criar. A IA não assume identidade, marca resolução, para hardware ou concede estorno. Texto malicioso no chamado continua sendo conteúdo, nunca instrução de ferramenta.

Offline mostra último fato recebido e incerteza. Watchdog ou reboot só são explicados quando evidência válida os registra; ausência de comunicação não comprova parada física. Simulação permanece identificada, sem diagnóstico de veículo, cabo ou rede elétrica reais. Sugestão de reconectar não reinicia automaticamente uma sessão encerrada.

Flet conserva rascunho em falha, repete a mesma chave após timeout e impede envio duplicado; limpa contexto e respostas ao trocar de conta. API valida vínculos, destinatário, estado e projeção. Simulador apenas fornece fatos; abrir ou resolver chamado não altera sua máquina. Uploads, canais externos e integração CRM exigem escopo posterior.

## Etapas, aceite e demo

1. Definir categorias, destinatários, schemas e projeção; implementar chamados/eventos e autorização.
2. Adicionar formulário revisável, acompanhamento do titular e fila do operador; integrar inbox/outbox da frente 06.
3. Integrar preparação MCP e contexto da simulação; depois considerar anexos, atendentes adicionais e política de prazo.

Aceites futuros: duas contas não consultam chamados entre si; operador alheio não recebe detalhes; eventos pessoais permanecem bloqueados; origem/horário aparecem; repetição não duplica protocolo/comentário; transição antiga falha com conflito; erro de inbox não perde chamado; alteração de propriedade suspende encaminhamento; resolução não altera energia ou finanças. Nenhum teste foi executado nesta rodada documental.

Demo: interromper uma recarga simulada com fato confirmado, pedir explicação ao chat e revisar contexto. Abrir chamado; operador do posto recebe item na fila, responde e registra resolução. Titular recebe atualização e reabre com esclarecimento. Mostrar um caso offline como inconclusivo e outra conta bloqueada. O diferencial demonstrado é continuidade do atendimento com evidências, permissões e acompanhamento verificáveis.
