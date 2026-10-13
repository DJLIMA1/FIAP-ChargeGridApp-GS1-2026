# Revisão de integração e segurança (outubro de 2026)

Escopo: o código que entrou na `main` em paralelo pelas frentes **Modo Motorista**, **IA/OpenRouter**
e **Dashboard do proprietário**, além da integração entre elas. O código antigo já tinha passado pela
auditoria de QA (`qa-auditoria-2026-10.md`). Cada correção tem um teste de regressão. Os testes da API
estão em `apps/api/tests/test_review_regressions.py`, e os do núcleo, no fim de
`packages/chargegrid_core/tests/test_ai.py` e `test_driver.py`.

## Método

1. Leitura dirigida de `apps/api/app/modules/{ai,driver,owner}`, `chargegrid_core/{ai,driver,analytics}`,
   `owner_api.py`, `demo_owner.py`, `services/driver*.py`, `services/demo_ai.py`, `ui/ai_features.py`, do dashboard
   (`apps/dashboard`) e das migrações novas.
2. Experimentos no planejador cobrindo SoC 0/0,5/100 %, ausência de postos, turno que cruza a meia-noite e
   turnos de 16 h com 30 postos.
3. **Migrações**: `upgrade head` a partir de um banco vazio, depois `downgrade base` e um novo `upgrade head`,
   num PostgreSQL local descartável. No mesmo banco, `alembic check` não acusou diferença entre modelos e
   migrações. Os privilégios padrão do Supabase foram simulados com
   `ALTER DEFAULT PRIVILEGES ... GRANT ALL ON TABLES TO PUBLIC`.
4. **API local real**: uvicorn, banco local migrado e dados fictícios (dois donos, um motorista, 30 dias de
   histórico, uma recarga ativa com telemetria e um nome de posto com tentativa de injeção). As chamadas
   saíram dos próprios clientes do app (`ApiClient`/`OwnerApiMixin`) com os filtros do dashboard
   (`DashboardState.params`). Cada resposta foi comparada, campo a campo, com a do modo demo (`DemoApi`) nas
   13 rotas novas. Resultado: **0 divergências**, nenhum dado do outro dono visível, CSV neutralizado,
   paginação e busca corretas. O roteiro está em `tools/live_contract_check/`; o uso fica no cabeçalho de
   `exercise.py`.
5. **IA ao vivo** (OpenRouter, `deepseek/deepseek-v4.1-flash`): cerca de 15 chamadas, com custo total abaixo de
   US$ 0,01, registrado em `ai_usage`.

## Achados e correções

| # | Severidade | Achado | Correção | Teste |
|---|---|---|---|---|
| 1 | **Alta** | `POST /driver/next-stop` (API e demo) dizia **"Siga rodando: nenhuma recarga necessária"** quando a bateria não chegava a nenhum posto (SoC 0 %) ou quando não havia posto compatível no raio. Os alertas `battery_empty`/`no_station` da mesma resposta diziam o contrário. Era um conselho perigoso para o motorista. | Nova ação `charge_needed`: "Recarregue o quanto antes no/em <posto compatível mais próximo>", com mensagem para bateria praticamente vazia ou para falta de posto. O aviso de "pico, continue rodando" não é mais anexado nesse caso. O app permite reservar a partir dessa recomendação (`screens/driver.py`, uma linha). | `test_next_stop_never_says_keep_driving_when_battery_cannot_cover_the_shift` (núcleo), `test_next_stop_with_empty_battery_never_says_keep_driving` (API) |
| 2 | Média | `parse_completion` quebrava com JSON malformado do provedor (`message` como texto, `tool_calls` como objeto, `usage` não numérico ou NaN). O resultado era `AttributeError`/`ValueError` e **HTTP 500** no chat. | Validação de tipos em todos os campos: formatos inesperados viram `LLMUnavailable` (503 amigável) e o uso é saneado (sem NaN ou negativo). | `test_parse_completion_never_crashes_on_malformed_provider_payloads` (7 casos), `test_malformed_provider_payload_is_a_friendly_503_not_a_500` |
| 3 | Média | Os prazos do OpenRouter não eram totais. No httpx, o timeout vale por operação (conexão de 5 s mais leitura de 22 s), e a nova tentativa após `ai_bad_response` ignorava o orçamento restante. Uma requisição podia passar dos **30 s da Vercel**. | `asyncio.timeout(limite)` envolve conexão e resposta, e a conexão fica limitada a `min(5 s, limite)`. A nova tentativa só ocorre com pelo menos 2,5 s restantes. | `test_openrouter_client_enforces_a_total_deadline`, `test_loop_does_not_retry_bad_response_without_time_left` |
| 4 | Média | Um estouro de tempo depois de as ferramentas já terem rodado descartava todo o trabalho e respondia 504. Ao vivo, 2 de 3 perguntas com duas rodadas de ferramentas estouraram, com uma única chamada ao provedor levando 11,7 s. | O laço devolve 200 com um aviso curto ("A resposta demorou…") e os botões derivados do que já foi consultado. Sem dados consultados, o 504 continua. | `test_loop_timeout_after_tools_degrades_to_actions_instead_of_error` e validação ao vivo |
| 5 | Média | As rotas de IA mantinham a transação do banco aberta durante a espera do modelo, deixando a conexão *idle in transaction* por até cerca de 22 s por requisição. Com o pooler do Supabase em modo transação, isso prende uma conexão do pool. | `_released(db, llm)` faz `commit` (encerra a leitura) antes de cada chamada ao provedor em chat, busca, resumo e insights. | `test_ai_routes_end_the_db_transaction_before_waiting_for_the_model` |
| 6 | Média (defesa em profundidade) | `driver_profiles`, `ai_usage`, `session_events` e `device_claims` só receberam RLS. A migração inicial, porém, revoga `PUBLIC`, `anon` e `authenticated` de todas as tabelas. No Supabase, os privilégios padrão de `public` concedem ALL a esses papéis em tabelas novas, inclusive `TRUNCATE`, que o RLS não cobre. | Migração **`b8e4f2a6c913`** (sobre `a71c3e5d9b20`) revoga esses papéis nas quatro tabelas. O downgrade é intencionalmente vazio. | `upgrade`/`downgrade`/`upgrade` local: `has_table_privilege('public', …, 'TRUNCATE')` passa de `t` para `f` e `chargegrid_api` mantém INSERT. `alembic check` não acusou diferença. |
| 7 | Baixa (isolamento) | As ferramentas da IA liam pontos e postos não publicados. `get_connector` não verificava se o ponto e o posto estavam ativos e com dono, e `get_station` aceitava posto de fábrica sem dono. Com um `connector_id`, a IA revelava tarifa e potência de um ponto desativado. | Mesmo recorte da listagem pública: ponto ativo, posto ativo e com dono. | `test_assistant_cannot_read_unpublished_points_or_stations`, `test_chat_estimate_on_hidden_point_returns_tool_error` |
| 8 | Baixa | `plan_driver_shift` pelo chat planejava com os 40 primeiros postos por id e ignorava a localização do aparelho. Na listagem da IA, a caixa de busca também ordenava por id, então postos próximos podiam ficar de fora do limite. | Planejamento com os postos ao redor do lugar citado ou da localização do aparelho, no raio de 30 km (o mesmo de `/driver/plan`). A localização vira origem do plano, e a listagem traz os mais próximos primeiro. | `test_plan_driver_shift_lists_stations_around_the_driver`, `test_assistant_station_list_prefers_the_nearest_when_capped` |
| 9 | Baixa | A busca `q` das tabelas e exportações do dono tratava `%` e `_` como curingas: `q=%` listava tudo. | Busca convertida em literal com `ESCAPE`. A demo já comparava por substring. | `test_owner_search_treats_like_wildcards_literally` e roteiro ao vivo |
| 10 | Baixa | `POST /ai/session-insight` aceitava recarga em andamento, o que gerava um resumo com dados parciais e gasto de IA. O app só oferece o resumo para recargas encerradas. | 409 `session_not_finished` na API e na demo. | `test_session_insight_only_for_finished_sessions` |
| 11 | Baixa (desempenho) | `DbSource.recent_sessions` serializava sessão por sessão (N+1). O resumo de uma recarga lê 30 sessões e levou 1,9 s no ambiente local. | `session_rows` em lote, com número constante de consultas. | Coberto pelos testes existentes de IA |
| 12 | Baixa | `/driver/plan` e `/driver/next-stop` não tinham limite de taxa, apesar do custo de CPU (centenas de ms) e da consulta ao Open-Meteo. | 30 pedidos por minuto por usuário (`request_limits`, resposta 429). | `test_driver_planner_is_rate_limited_per_user` |
| 13 | Baixa | `parse_hhmm` aceitava minutos ≥ 60 (`"10:99"` virava 11:39), um caminho aberto pelos argumentos da ferramenta da IA. A API já validava por regex. | Minutos acima de 59 são rejeitados. | `test_parse_hhmm_rejects_invalid_minutes` |
| 14 | Baixa (contrato) | Os insights do dono na demo emitiam `kind: "maintenance"`, fora do contrato `pricing`/`operations`/`marketing`. | Passa a emitir `operations`. | Roteiro ao vivo (`kind` dentro do contrato) |
| 15 | Cosmético | O título "Pare agora **no** Cantina da Vila" ignorava o gênero do nome. | Usa a mesma regra dos motivos (`no`/`em`). | `test_next_stop_headline_uses_station_gender` |
| 16 | Ajuste de prompt | Ao vivo, o modelo chamou `estimate_charge` em paralelo com a busca, usando um `connector_id` inventado, e gastou rodadas. | A descrição da ferramenta exige id vindo de `search_stations`/`get_station_details`. | Validação ao vivo |

## Verificado sem necessidade de mudança

- **Isolamento do dono**: todas as consultas de `/owner/*` e das exportações passam pelo `Scope`
  (`Station.owner_id`). `station_id` de outro dono recebe 403/404, motorista recebe 403 e o ranking não tem
  posto do rival. Os testes existentes e o roteiro ao vivo confirmam.
- **IA**: nenhuma ferramenta recebe `user_id`, e tentativas do modelo de passá-lo são descartadas (teste
  existente). Ações sugeridas usam somente ids devolvidos pelas ferramentas. O laço limita rodadas,
  chamadas por rodada, histórico e tamanho dos resultados. A chave não aparece em `repr`, erros ou respostas.
  Os limites de taxa são gravados mesmo quando a operação falha. Ao vivo, o modelo recusou revelar o prompt e
  dados de outra conta e marcou o nome de posto com instrução injetada como "texto suspeito, ignorado".
- **Dashboard**: divisões por zero protegidas (ocupação, uptime, ticket, não comparecimento), agregação no fuso
  `America/Sao_Paulo` no SQL (`timezone()`/`date_trunc`), janelas `[início, fim)`, CSV com fórmulas
  neutralizadas (`'=`), exportação limitada a 10.000 linhas (413) e polling só da seção visível, sem chamadas
  sobrepostas.
- **Motorista**: turno que cruza a meia-noite (`auto` continua o turno atual), SoC de 100 %, ausência de postos
  com alerta `no_station`, falha ou lentidão do Open-Meteo (timeout de 2 s, cache de 30 min e de 5 min após
  falha, sinal omitido), validação de entrada (faixas, NaN, HH:MM) e desempenho de cerca de 0,3 s para um turno
  completo com 30 postos.
- **Contratos app ↔ API ↔ demo**: driver profile/plan/next-stop, owner overview/timeseries/heatmap/alerts/live/
  sessions/reservations e ai/search/owner-insights têm os mesmos campos na API real e na demo.

## Pendências e riscos

- **Latência do provedor**: chamadas isoladas variaram de 2 a 12 s. Perguntas que exigem duas ou mais rodadas
  de ferramentas podem cair na resposta parcial do achado 4. Opções: chat com `reasoning: none`, máximo de
  3 rodadas ou um modelo mais rápido como principal.
- **Margem dos 30 s**: o orçamento de 22 s, somado ao cold start da Vercel e à conexão com o banco, deixa
  cerca de 5 s de folga. A medição local ficou em até 24 s no pior caso.
- **Injeção via dados**: a mitigação combina instruções e a ausência de ferramentas com efeito. Nomes de posto
  controlados pelo dono aparecem como texto nos rótulos dos botões (ex.: "Ver Posto Vila. SISTEMA: …").
  Validar o nome no cadastro seria uma defesa adicional.
- **Migração `b8e4f2a6c913`**: precisa ser aplicada no Supabase pelo responsável. Ela não foi executada no
  banco remoto. O teste local simulou apenas `PUBLIC`, porque os papéis `anon` e `authenticated` não existem
  no PostgreSQL local; a migração os trata com `IF EXISTS`, como a migração inicial.
- **Login real**: o roteiro local usa tokens ES256 de teste no lugar do JWKS do Supabase, e o fluxo
  `/auth/login` não foi exercitado.
- `full_shift` com turno noturno pedido de madrugada planeja o turno da noite seguinte ("turno de hoje",
  conforme documentado), não o turno em andamento.
- `services/demo_ai.py` (prévia local, fora do APK) mantém timeouts por operação do httpx.
- A suíte da API levou cerca de 10 min nesta máquina, por causa da disputa de disco com outros agentes
  (TRUNCATE por teste). Em execução isolada, a expectativa é de cerca de 20 s.
