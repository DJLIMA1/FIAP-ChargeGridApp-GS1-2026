# API ChargeGrid v1

Base `/v1`, JSON, UUIDs e datas UTC ISO 8601. Bearer JWT de pessoa nas rotas de domínio, logout e alteração de senha; cadastro, login, refresh, solicitação de recuperação e verificação por código são públicos com limite de tentativas. Sync usa `Authorization: Device <chave>`. Erro: `{"error":{"code":"point_unavailable","message":"Ponto indisponível"}}`. Validação retorna 422. Respostas de listas: `{"items":[],"total":0,"limit":50,"offset":0}`. `GET .../current` retorna recurso ou `null`.

Auth: POST `/auth/register` {email,password,name,account_type?:"consumer"|"vendor"}; `/auth/login` {email,password}; `/auth/refresh` {refresh_token}; `/auth/logout` com Bearer. O tipo de conta é escolhido no cadastro e o padrão para clientes antigos é `consumer`; login não recebe tipo. Cadastro novo sem confirmação pendente, login e refresh retornam `{access_token,refresh_token,expires_in,token_type:"bearer",user:{id,email}}`. Cadastro inclui `requires_email_confirmation`, calculado conforme a resposta do provedor: `false` com sessão imediata, `true` quando a conta depende de confirmação. Cadastro de e-mail já existente recebe resposta neutra sem sessão, sem afirmar que uma mensagem foi enviada. Senhas são preservadas exatamente, inclusive espaços; cadastro e nova senha exigem 8–128 caracteres, login aceita 1–128 para compatibilidade com contas legadas. O provedor pode recusar senhas fracas. Os endpoints `/auth/verify-email` e `/auth/resend-signup` permanecem compatíveis, embora o projeto atual não exija confirmação.

Recuperação: POST `/auth/password/forgot` {email} solicita e-mail com link; `/auth/password/reset` {email,code,password} mantém suporte a código OTP. O link padrão abre `/auth/confirmed`, fora da base `/v1`, que apresenta o formulário quando recebe `type=recovery` e o token no fragmento da URL. A página remove o fragmento imediatamente, mantém o token apenas em memória e chama POST `/auth/password/update` {password} com Bearer válido. Ambos os fluxos de redefinição revogam as sessões de atualização no provedor e pedem novo login. Tokens de acesso já emitidos podem permanecer válidos até sua expiração. A entrega de e-mail ainda depende do SMTP configurado no Supabase; indisponibilidade ou limite do provedor retornam erro, não uma confirmação falsa de envio.

`GET/PATCH /me`: `{id,name,account_type,phone,vehicle_description,operator_enabled,created_at}`; PATCH aceita apenas name,phone,vehicle_description. `account_type` é persistido no primeiro acesso a partir dos metadados do cadastro e não é alterado por logins posteriores. Escolher `vendor` permite iniciar o vínculo por QR; somente a prova de posse de um equipamento habilita `operator_enabled`. Vendedores ainda sem equipamento podem usar recargas. Operadores e proprietários legados são preservados. `GET /me/summary`: `{month:"YYYY-MM",currency:"BRL",estimated_cost,energy_wh,sessions_count}` para sessões encerradas com carga no mês civil de São Paulo; custo é estimativa, não pagamento.

`GET /stations` filtros lat,lng,radius_km,limit,offset; `GET /stations/{id}`. Posto: `{id,owner_id,name,address,latitude,longitude,active,connectors:[]}`. `owner_id` pode ser null somente para equipamento de fábrica sem dono, que permanece inativo. Ponto: `{id,station_id,public_code,connector_type,power_kw,price_per_kwh,max_duration_minutes,active,control_version,available,online,physical_state,availability_status,reserved_until}`. `availability_status` usa `available`, `reserved`, `charging`, `offline`, `reconciling`, `disabled`, `fault` ou `occupied`; clientes não devem chamar todo ponto indisponível de ocupado.

A descoberta também aceita `connector_type`, `available_only` (padrão `false`), `max_price_per_kwh` (0 a 10000) e `sort=default|price|distance`. Distância exige `lat` e `lng` juntos e é calculada em linha reta, não como rota. Tipo de conector ignora caixa/separadores e reconhece aliases como `Tipo 2`/`Type-2` e `CCS`/`CCS2`. Filtros e ordenação são aplicados antes de `limit`/`offset`.

Cada item da listagem acrescenta `discovery: {point, matching_connector_ids, available_points, distance_km}`. `point` é o ponto elegível de menor tarifa no posto, ou `null` quando não há ponto elegível. Preço, potência, conector e estado apresentados em uma comparação devem vir desse mesmo ponto. O campo `connectors` original permanece completo; `matching_connector_ids` identifica quais atendem à comparação. Sem `available_only`, um ponto ocupado/offline pode ter a menor tarifa e deve manter seu estado explícito. `available_only` usa o estado reconciliado do serviço, não apenas a presença de um sinal recente. A disponibilidade continua sendo revalidada nas operações de reserva/início.

Consultas padrão e por distância sem filtros adicionais preservam paginação SQL. Comparações por tarifa/disponibilidade avaliam os estados dos candidatos após restringir os atributos estáticos no SQL; o custo cresce com a quantidade de pontos candidatos. Essa implementação atende o piloto, mas requer medição e otimização antes de expandir para catálogos grandes.
POST `/stations` {name,address,latitude,longitude} cria apenas um agrupamento do vendedor habilitado; PATCH aceita esses campos e active. POST `/stations/{id}/connectors` não cria mais equipamentos: responde 409 `claim_required`, orientando o vínculo por QR. PATCH `/connectors/{id}` mantém edição dos campos e active, apenas pelo proprietário e sem operação ativa.

## Propriedade por QR de fábrica

POST `/ownership/claim` {token,station_id?:UUID}, com Bearer de vendedor ou operador legado. `token` é o segredo aleatório base64url de 43 caracteres contido em `chargegrid://claim?token=...`; não é `public_code`, UUID nem chave de dispositivo. Resposta 200: `{station_id,connector_id,already_claimed,message}`. O segredo é enviado no corpo HTTPS, nunca na URL HTTP ou em logs.

O provisionamento administrativo cria um ponto com chave de dispositivo própria e um segredo de propriedade independente. O banco guarda somente SHA-256 dos dois. A primeira claim vincula o posto de fábrica ao vendedor ou, quando `station_id` é informado, adiciona o ponto a um posto que já pertence à mesma pessoa. Essa operação habilita a gestão do vendedor por prova de posse. Posto/ponto novos continuam inativos até revisão e ativação pelo dono. O QR deve ser entregue ao comprador, não publicado como QR de recarga.

Claims concorrentes são serializadas: mesmo dono pode repetir com segurança (`already_claimed:true`); outro dono recebe 409 `already_owned`. Um QR usado não transfere o ponto para outro posto (409 `already_claimed`), nem altera proprietários legados. Consumidor recebe 403 `vendor_required`; segredo desconhecido recebe 404 `invalid_claim`; posto de destino alheio recebe 404. Há limite persistente de 15 tentativas por usuário/minuto, inclusive falhas (429). Respostas públicas não incluem claim, token ou hash.

POST `/connectors/{id}/device`, `/devices/{id}/rotate-key`: `{device_id,device_key}` chave mostrada uma vez. POST `/devices/{id}/revoke`: `{revoked:true}`.

GET `/connectors/{id}/device`, exclusivo do proprietário habilitado do posto: `{device_id,connector_id,firmware_version,last_seen,online,physical_state,connected,reconciled}`. Permite reencontrar o dispositivo para manutenção, rotação ou revogação depois de fechar a tela; nunca devolve chave, hash ou segredo de propriedade. Retorna 404 quando não existe dispositivo ativo, inclusive após revogação, ou quando o ponto pertence a outro operador; consumidores e vendedores sem equipamento vinculado recebem 403. Provisionar/rotacionar uma chave de comunicação não muda o dono do ponto.

GET `/devices/{id}/factory-reset` consulta o estado da restauração, inclusive durante uma reserva/recarga, sem alterar o dispositivo. POST na mesma rota solicita a restauração e continua exigindo equipamento livre, online e firmware compatível. Comando expirado permite reativar o ponto ou renovar a credencial; um novo sync livre confirma sua disponibilidade. ACK tardio não executa a restauração. Restauração aplicada mantém o ponto antigo aposentado e exige novo vínculo por QR.

POST `/reservations` {connector_id}, header `Idempotency-Key` obrigatório; 202 reserva `{id,user_id,connector_id,status,created_at,confirmation_deadline,expires_at}`. Estados pending_device,confirmed,cancelling,cancelled,expired,consumed. GET `/reservations/current`; POST `/reservations/{id}/cancel` 202 mesma representação.

Todas as representações de reserva e sessão (criação, consulta individual/atual, cancelamento/parada e itens de histórico) incluem também `{station_id,station_name,station_address,connector:{id,public_code,connector_type,power_kw,price_per_kwh,max_duration_minutes}}`. Esse contexto usa os dados públicos atuais do ponto/posto e não inclui dono, dispositivo, chave, hash ou segredo. A tarifa contratada continua no `price_per_kwh` da sessão; a tarifa do ponto no contexto pode mudar depois. As rotas `/current` reconciliam expiração antes de retornar o estado e devolvem `null` se a operação deixou de estar ativa enquanto aguardavam o lock.

POST `/charging-sessions` {presence_code,public_code?:string,reservation_id?:UUID,coupon_code?:string,max_duration_minutes:30,max_cost?:decimal} Idempotency-Key obrigatório; 202 sessão. `presence_code` tem formato `#F` seguido de cinco dígitos, é exibido apenas no painel físico, muda a cada cinco minutos e é validado pela API no início da recarga. A reserva ou o `public_code` opcional identificam o ponto quando já foi selecionado; sem eles, a API procura o código temporário entre os postos e exige que o ponto disponível seja único. Código inválido, vencido ou ambíguo retorna 422; há limite de dez tentativas por usuário a cada cinco minutos. POST `/charging-sessions/{id}/stop` mesmo header, 202. GET `/charging-sessions/current`, `/{id}`, `/me/charging-sessions`, `/stations/{id}/charging-sessions` (proprietário). Sessão: `{id,user_id,connector_id,reservation_id,status,created_at,started_at,ended_at,max_duration_minutes,max_cost,price_per_kwh,discount_percent,energy_wh,soc_percent,source,last_measurement_at,cost_estimate,end_reason,online}`. Históricos são ordenados por `created_at` decrescente, com UUID apenas para desempate; registros antigos usam início/fim conhecido como data de criação aproximada. Estados starting,charging,stopping,completed,failed,interrupted. Uma tentativa que nunca iniciou termina como `failed`; reinicialização após início termina como `interrupted`. SoC ausente é null. GET `/operator/summary`: `{stations,total_sessions,total_energy_wh,total_estimated_cost}`.

GET `/operator/charging-sessions` lista o histórico de todos os postos do operador autenticado, com `limit`/`offset`, envelope paginado e a mesma representação contextual de sessão. Exige operador habilitado e filtra exclusivamente seus postos, em ordem decrescente de criação.

GET `/coupons` filtro station_id; POST {code,description,discount_percent,station_id?:UUID,valid_until}; PATCH `/coupons/{id}` aceita description,discount_percent,valid_until,active. Cupom global vale somente nos postos de seu operador. Criar, alterar a validade ou reativar um cupom exige validade futura com fuso horário. Editar descrição/desconto ou desativar cupom vencido continua permitido sem reenviar a validade; campos omitidos permanecem intactos. Valores monetários serializados como strings decimais; nenhum pagamento real.

Idempotência reserva/início/parada: mesmo usuário/operação/chave/corpo devolve recurso original; corpo diferente retorna 409. Cancelamento é naturalmente idempotente. Sem contato por 45s proíbe novas autorizações. Reserva vence chegada 10 minutos após ACK, confirmação 30s; expiração inicia liberação, disponibilidade só retorna após reconciliação física. Reiniciar o ESP32 não cancela uma reserva válida: a API reaplica a reserva com seu prazo original, sem estender o vencimento. Isso é diferente de uma recarga em andamento, que é interrompida com segurança após reboot.

## Modo Motorista

`GET/PUT /driver/profile` (veículo e preferências de turno/refeições), `POST /driver/plan` {soc_percent,lat?,lng?,radius_km?,mode?:"auto"|"full_shift",vehicle?,preferences?,context?,live_signals?} e `POST /driver/next-stop` planejam recargas para motoristas de app com o motor `chargegrid_core.driver`. Postos expõem `amenities:[{kind,name,distance_m}]` (`restaurante`, `cafe`, `banheiro`, `shopping`, `conveniencia`), editáveis pelo dono em PATCH `/stations/{id}`. Demanda é estimativa; clima da Open-Meteo é opcional, com fallback silencioso e origem em `demand.source`/`demand.signals`. Detalhes em [modo-motorista.md](modo-motorista.md).

## Assistente de IA

Rotas autenticadas (Bearer). A chave do OpenRouter fica somente no backend. As ferramentas da IA apenas **leem** dados do
usuário autenticado e nunca reservam, iniciam ou cobram. Os limites são compartilhados por todas as rotas de IA: 20
pedidos a cada 10 minutos e 200 por dia por usuário, além de um teto global diário. Ao exceder, a resposta é 429
`ai_rate_limited`. O uso é registrado em `ai_usage` apenas com metadados: tokens, custo, latência, modelo e nomes das
ferramentas. Detalhes e escolha do modelo em [ia-openrouter.md](ia-openrouter.md).

POST `/ai/chat`

Corpo: `{messages:[{role:"user"|"assistant",content:string≤2000}] (1–12, a última do usuário), context?:{mode:"driver"|"owner",screen?:string,lat?:number,lng?:number}}`.

Resposta 200: `{reply,suggested_actions,tools_used,model}`. Cada item de `suggested_actions` tem o formato
`{type,label,station_id?,connector_id?,session_id?}`, com `type` entre `open_station`, `reserve`, `open_reservation`,
`open_charging`, `open_history`, `open_operator`, `search_stations` e `open_driver`. O app abre a tela correspondente,
e a ação com efeito segue o fluxo normal, com confirmação. As ferramentas de dono só ficam disponíveis com
`operator_enabled`.

Erros: 503 `ai_unavailable`/`ai_busy`/`ai_quota` (IA desligada ou provedor indisponível; não há troca para modelo caro),
504 `ai_timeout` e 422 para histórico inválido.

POST `/ai/search`

Corpo: `{query:string 2–300, lat?, lng?}`. Converte a busca em linguagem natural em filtros estruturados.

Resposta 200: `{filters:{near?:{label,lat,lng},radius_km?,text?,connector_type?,min_power_kw?,max_price_per_kwh?,available_only?,sort?,amenities?},unsupported:[string],explanation,params,model}`.
`params` traz os parâmetros da tela/`GET /stations` (`lat,lng,radius,connector_type,max_price_per_kwh,available_only,sort`).
Sem IA, ou se ela falhar, responde por regras com `model:"chargegrid-regras"`.

POST `/ai/session-insight`

Corpo: `{session_id}`. Só aceita sessões do próprio usuário; para as demais, a resposta é 404.

Resposta 200: `{session_id,summary,tips:[string],comparison:{cost_brl,energy_kwh,price_per_kwh,avg_cost_brl,avg_price_per_kwh,cost_vs_avg_percent,peak_hour,history_sessions},generated_at,model}`.

POST `/ai/owner-insights`

Exige operador habilitado; caso contrário, 403. Corpo opcional: `{days?:7–90}` (padrão 30). **Contrato estável,
consumido pelo dashboard web:**

```json
{"summary": "string",
 "recommendations": [{"title": "string", "detail": "string", "impact": "alto|médio|baixo",
                      "kind": "pricing|operations|marketing"}],
 "generated_at": "ISO-8601 UTC",
 "model": "deepseek/deepseek-v4.1-flash | chargegrid-regras"}
```

As recomendações vêm dos indicadores dos postos do dono: receita e energia estimadas, sessões por hora, ocupação,
interrupções/falhas e pontos offline. A IA apenas redige a partir desses números. Se a resposta da IA for inválida, a
rota devolve as recomendações por regras.

## Banco e papel de execução

Migrações usam `MIGRATION_DATABASE_URL`, uma conexão administrativa direta. A aplicação usa `DATABASE_URL` pelo pooler em modo transação com prepared statements automáticos desativados. A migração cria o papel sem login `chargegrid_api`, remove acesso público e de `anon`/`authenticated`, ativa RLS e concede uma política somente ao papel da API. O administrador deve executar `GRANT chargegrid_api TO <usuario_sql_da_api>`; esse usuário não deve ser dono das tabelas nem ter `BYPASSRLS`. A Data API do schema deve permanecer desativada. Nunca conceder `chargegrid_api` aos papéis Supabase `anon` ou `authenticated`.

A versão atual exige `alembic upgrade head` até `d85af641bc01`. Além da migração anterior de tipo de conta e cronologia, ela permite posto de fábrica sem dono e cria `device_claims` com auditoria, unicidade e RLS. O runtime recebe somente SELECT/UPDATE nessa tabela: criar claims exige a credencial administrativa da ferramenta de fábrica. Nenhum owner legado é alterado. Aplicar a migração antes de publicar o código correspondente. Downgrade recusa remover a nulabilidade enquanto houver postos sem dono, evitando apagar equipamento para retornar ao esquema antigo.

A migração `a71c3e5d9b20` (assistente de IA, sobre `e7d3c1a95b42`) cria `ai_usage` somente com metadados de uso: usuário, função, status, modelo, tokens, custo, latência e nomes das ferramentas. Ela não guarda perguntas nem respostas. Aplica RLS, e somente o papel `chargegrid_api` recebe SELECT/INSERT.
