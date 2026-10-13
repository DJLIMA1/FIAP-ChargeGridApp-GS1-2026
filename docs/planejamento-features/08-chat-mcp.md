# Chat com OpenRouter gratuito e MCP compartilhado

Proposta de implementação — 1 de outubro de 2026. Este documento planeja a feature; nenhum modelo foi chamado, serviço exposto ou código do produto alterado nesta rodada.

## Objetivo e estado atual

A aba Chat deve responder com uma IA gratuita do OpenRouter, substituível por configuração. O mesmo conjunto de ferramentas MCP deve atender o chat interno e clientes externos autenticados, compartilhando autorização, consultas e regras de negócio. MCP define a interface de ferramentas; OpenRouter fornece o modelo que decide quais consultas solicitar.

Hoje, `apps/mobile/src/chargegrid_app/screens/chat.py` reconhece intenções por texto, oferece orientação local e consulta recarga, reserva e histórico pelas rotas existentes. A conversa fica em memória, muda com a conta e distingue demonstração. Não existe chamada LLM nem dependência MCP em `apps/api/pyproject.toml`. Devemos preservar o assistente local como fallback identificado.

`apps/api/app/security.py` valida JWT Supabase com audiência `authenticated`. `app/service.py` exige operador habilitado e propriedade do posto. `modules/charging/routes.py` restringe detalhes e eventos da sessão ao motorista titular; operador vê histórico e resumo dos próprios postos. Esses limites continuam valendo para ferramentas. Nome, papel ou identificador escrito no prompt não altera identidade nem propriedade.

## Arquitetura mínima

Propor módulos `app/modules/assistant` e `app/mcp`, extraindo consultas das rotas para serviços reutilizáveis quando necessário. REST, MCP e orquestrador chamam esses serviços com um contexto autenticado: titular, cliente, escopos e recurso autorizado. Evitar copiar consultas e regras para o prompt ou implementar MCP como acesso irrestrito ao banco.

Fluxo interno: Flet envia mensagem à API autenticada; backend consulta `tools/list`, converte `inputSchema` para funções OpenRouter, recebe `tool_calls`, valida cada chamada e executa `tools/call`. Os resultados estruturados voltam ao modelo; resposta e referências voltam ao app. O backend, responsável pela execução, limita o ciclo. Esse comportamento corresponde ao [tool calling documentado pelo OpenRouter](https://openrouter.ai/docs/guides/features/tool-calling).

Usar cliente MCP com transporte interno suportado pelo SDK para o mesmo dispatcher, sem depender de chamadas HTTP à própria função Vercel. Caso o SDK escolhido exija HTTP, introduzir credencial de delegação curta, específica para MCP e derivada do usuário autenticado; nunca repassar seu JWT Supabase com audiência diferente. A definição e o handler das ferramentas permanecem únicos. Cliente externo acessa esse mesmo servidor via HTTPS.

Não haverá atuação adicional no dispositivo por causa do chat. Medições do simulador manterão `source=simulated`; configuração futura SEMS+ entra no adaptador de equipamentos, sem trocar ferramentas do assistente. RFID e separação solar/rede ficam excluídos.

## Modelo gratuito e troca simples

Propor `OPENROUTER_API_KEY`, `ASSISTANT_MODEL`, `ASSISTANT_FREE_FALLBACK_MODELS`, `ASSISTANT_ENABLED` e limites de tempo/tokens no backend. Segredo nunca vai para APK, navegador, MCP público ou logs. Preferir um modelo gratuito específico validado para português e ferramentas; `openrouter/free` é alternativa configurável que seleciona gratuitamente conforme capacidades, mas varia o modelo e dificulta reproduzir a apresentação. [Free Models Router](https://openrouter.ai/docs/cookbook/get-started/free-models-router-playground).

Valor inicial proposto para a prova de integração: `ASSISTANT_MODEL=openrouter/free`, validando as chamadas de ferramentas no piloto. Antes da apresentação, escolher no catálogo um candidato gratuito específico aprovado nos cenários em português e mudar somente essa configuração. Assim, o plano tem uma opção inicial concreta sem congelar uma variante que pode desaparecer ou exigir pagamento.

Na implementação, consultar catálogo e conferir `supported_parameters` contendo `tools`, contexto e preços efetivamente zero nos campos aplicáveis. Fixar candidatos aprovados por avaliação e registrar modelo realmente usado. Não adicionar `:free` arbitrariamente: a variante precisa existir no catálogo. [Catálogo oficial](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties), [variantes gratuitas](https://openrouter.ai/docs/guides/routing/model-variants/free).

Gratuidade não garante capacidade contínua. Verificar quota da chave por `GET /api/v1/key`; aplicar orçamento global compartilhado, porque um turno com ferramenta pode exigir duas inferências. Respeitar `429` e `Retry-After`, indisponibilidade e limites da conta. Falha passa apenas para candidato gratuito validado, se houver tempo; depois, orientação local sinalizada. Nunca migrar silenciosamente para modelo pago, habilitar plugins pagos ou abrir contas para contornar quota. [Limites OpenRouter](https://openrouter.ai/docs/api_reference/limits).

## Catálogo proposto e contratos

Todas as ferramentas terão schemas de entrada/saída, tamanho limitado, unidades, paginação e erros estáveis. Identidade vem da autenticação, nunca de `user_id` enviado pelo modelo. Não expor SQL, URL arbitrária ou ferramenta genérica de executar endpoints.

Há um detalhe importante: as rotas atuais de reserva/recarga corrente chamam `lock_point`, que pode emitir RELEASE/STOP pela política de expiração. Para manter o MCP inicialmente consultivo, extrair leitura de snapshot sem esse efeito e conservar a política automática nos fluxos existentes, com indicação de atualização/pendência. Não anunciar consulta como leitura pura se ela executar conciliação com efeitos.

| Ferramenta proposta | Entrada e retorno | Autorização |
|---|---|---|
| `search_stations` | Filtros/localização opcional; pontos, tarifa e disponibilidade observada | `stations:read`; localização só quando necessária |
| `get_current_reservation` | Sem titular informado; reserva e prazo | `account:read`, própria conta |
| `get_current_session` | Sessão ativa, energia, estimativa, estado e atualização | `account:read`, própria conta |
| `list_my_sessions` | Período e cursor, máximo inicial de 20 registros | `account:read`, próprio histórico |
| `get_session_events` | `session_id`; eventos e origem | `account:read`, motorista titular; sem ampliar acesso do operador |
| `get_operator_summary` | Período/posto opcional; agregados identificados como estimados | `operator:read` e ownership |
| `get_help` | Tópico enumerado; orientação versionada | Escopo de leitura básico |
| `prepare_action` | Tipo enumerado e parâmetros; proposta para revisão | Escopo correspondente, sem executar a ação |

Envelope de resultado proposto: `data`, `as_of`, `source`, `references`, `warnings`. Valores financeiros devem distinguir estimativa, cobrança e pagamento confirmado. MCP publica `structuredContent` conforme `outputSchema`, além de conteúdo textual compatível. Cache de catálogo é separado por autorização; dados privados não entram em cache público. [Ferramentas MCP](https://modelcontextprotocol.io/specification/2026-07-28/server/tools).

Rotas propostas: `POST /v1/chat/messages` recebe `conversation_id` opcional, `message_id` e texto limitado, sem histórico arbitrário com mensagens de sistema; retorna resposta, modelo/modo, referências, consultas e cartões de revisão. Conversas persistidas devem ser privadas, limitadas e apagáveis. Retentativa de `message_id` devolve resultado existente para evitar duplicar inferências.

`POST /mcp` oferece as ferramentas. Preparação de reserva, cancelamento, chamado ou exportação produz proposta vinculada ao titular, parâmetros, prazo e versão do recurso; ação final usa tela normal ou URL HTTPS própria com login e confirmação. Nenhuma ferramenta `mark_paid`, estorno ou comando de hardware será exposta. O LLM não confirma em nome do usuário. No primeiro MVP, preparação pode ser somente navegação contextual, sem persistência.

## MCP público seguro e compatibilidade

URL pública significa endpoint alcançável; dados continuam protegidos. Propor OAuth 2.1 com Authorization Code e PKCE, consentimento por cliente, revogação e escopos mínimos. Publicar Protected Resource Metadata e discovery do authorization server; respostas `401/403` incluem desafio adequado. Validar assinatura, emissor, validade e audiência ligada à URL canônica MCP, além de propriedade a cada consulta. [Autorização MCP](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization).

O login Supabase atual não comprova capacidade de emitir tokens MCP com `resource` e escopos. A primeira etapa deve validar um authorization server compatível e o mapeamento do subject para `Profile.id`; nunca contornar audiência ou entregar token administrativo ao cliente. MCP não aceita tokens de outros recursos nem os retransmite ao OpenRouter/SEMS+. Restringir redirects, proteger discovery contra SSRF e seguir tratamento de credenciais por cliente. [Segurança MCP](https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/security_best_practices).

A revisão oficial consultada é `2026-07-28`, com núcleo stateless, metadados por pedido e descoberta `server/discover`, diferente dos exemplos antigos com `initialize`. Fixar versão do SDK Python e provar suporte à revisão escolhida antes de codificar. Para clientes externos anteriores, validar modo de compatibilidade anunciado em matriz; não prometer funcionamento com toda IA. [Publicação oficial](https://blog.modelcontextprotocol.io/posts/2026-07-28/), [SDK Python](https://github.com/modelcontextprotocol/python-sdk).

Preferir respostas JSON rápidas via Streamable HTTP. Conferir headers `MCP-Protocol-Version`, `Mcp-Method`, `Mcp-Name` e correspondência com corpo; rejeitar `Origin` inválido. CORS permitirá somente origens aprovadas e headers efetivamente exigidos pela revisão; CORS não substitui autorização. [Transporte MCP](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http).

## Limites, falhas e responsabilidades

O `app/main.py` limita corpo a 16 KB e CORS REST; `apps/api/vercel.json` limita execução a 30 segundos. Planejar mensagem até 500 caracteres inicialmente, contexto curto no servidor, no máximo duas inferências e três consultas por turno, orçamento total inferior a 25 segundos e chamadas canceláveis. Resultados paginados ficam pequenos; exportações grandes retornam job/identificador e download autorizado, nunca arquivo/base64 na resposta MCP.

Mount ASGI exige verificar lifespan do SDK, leitura/replay do body pelo middleware atual e headers/erros; não basta montar uma subapp presumindo que tudo funciona. Não depender de streams eternos, memória compartilhada entre instâncias ou sessões locais. Trabalhos maiores migram para fila/worker, com polling autenticado, como fase posterior.

Rate limit por usuário, cliente OAuth, ferramenta e quota global protege dados e gratuidade. Prompt injection em nomes, chamados ou resultados não autoriza novas ferramentas: schemas, escopos e ownership prevalecem. Redigir campos sensíveis, omitir telefone/email, segredos, códigos de presença e credenciais de equipamento; só enviar ao provedor o necessário, informando isso no chat. Auditoria registra titular, cliente, ferramenta, recurso, resultado e duração com identificadores protegidos, sem token nem prompt completo por padrão.

Flet mostra consulta em andamento, origem dos dados, horário, ações para revisão e fallback; descarta resposta de conta anterior. API controla conversa, modelo, quotas, autorização e serviços. Simulador/dispositivo segue protocolo atual. Timeout não declara ação concluída, equipamento parado ou pagamento recebido.

## Etapas, dependências e aceite

1. Extrair serviços autorizados e fixar SDK/revisão, schemas, escopos, modelo gratuito e avaliação em português.
2. Implementar consultas MCP e ponte OpenRouter; integrar Flet, referências, fallback local e orçamento de tempo.
3. Validar OAuth/discovery e cliente externo autenticado antes de publicar endpoint; medir mount/middleware em ambiente equivalente à Vercel.
4. Acrescentar propostas revisáveis e ferramentas de pagamentos, suporte, demanda/exportação apenas após contratos das outras frentes. Valores de receita/margem dependem da conciliação; explicação de potência depende de decisões registradas; SEMS+ não bloqueia o MVP simulado.

Aceite exige consultas iguais no app e cliente externo; troca de modelo sem editar código; nenhuma saída paga; bloqueio entre duas contas e operadores; token de audiência errada rejeitado; conversa isolada; catálogo coerente com escopos; erro previsível para quota/timeout; nenhuma mutação financeira ou atuação física disparada pelo LLM. Testes devem incluir texto malicioso em dados, resposta inventada, ferramenta desconhecida, proposta expirada, 413 e headers incompatíveis.

Demo: perguntar no app pela recarga simulada e explicar uma interrupção usando eventos reais do registro; trocar modelo por configuração; repetir consulta em cliente MCP externo autorizado; tentar outra conta e mostrar bloqueio; simular quota esgotada e apresentar orientação local. Isso evidencia reaproveitamento e confiança, sem apresentar IA gratuita como serviço ilimitado.
