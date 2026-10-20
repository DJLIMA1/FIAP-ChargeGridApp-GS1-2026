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

POST `/charging-sessions` {presence_code,public_code?:string,reservation_id?:UUID,coupon_code?:string,max_duration_minutes:30,max_cost?:decimal,soc_percent?:0–100,battery_kwh?:5–250,soc_source?:"simulated"|"phone"} Idempotency-Key obrigatório; 202 sessão. `presence_code` tem formato `#F` seguido de cinco dígitos, é exibido apenas no painel físico, muda a cada cinco minutos e é validado pela API no início da recarga. A reserva ou o `public_code` opcional identificam o ponto quando já foi selecionado; sem eles, a API procura o código temporário entre os postos e exige que o ponto disponível seja único. Código inválido, vencido ou ambíguo retorna 422; há limite de dez tentativas por usuário a cada cinco minutos. POST `/charging-sessions/{id}/stop` mesmo header, 202. GET `/charging-sessions/current`, `/{id}`, `/me/charging-sessions`, `/stations/{id}/charging-sessions` (proprietário). Sessão: `{id,user_id,connector_id,reservation_id,status,created_at,started_at,ended_at,max_duration_minutes,max_cost,price_per_kwh,discount_percent,energy_wh,soc_percent,start_soc_percent,battery_kwh,soc_source,source,last_measurement_at,cost_estimate,end_reason,online}`. Históricos são ordenados por `created_at` decrescente, com UUID apenas para desempate; registros antigos usam início/fim conhecido como data de criação aproximada. Estados starting,charging,stopping,completed,failed,interrupted. Uma tentativa que nunca iniciou termina como `failed`; reinicialização após início termina como `interrupted`. SoC ausente é null. GET `/operator/summary`: `{stations,total_sessions,total_energy_wh,total_estimated_cost}`.

GET `/operator/charging-sessions` lista o histórico de todos os postos do operador autenticado, com `limit`/`offset`, envelope paginado e a mesma representação contextual de sessão. Exige operador habilitado e filtra exclusivamente seus postos, em ordem decrescente de criação.

GET `/coupons` filtro station_id; POST {code,description,discount_percent,station_id?:UUID,valid_until}; PATCH `/coupons/{id}` aceita description,discount_percent,valid_until,active. Cupom global vale somente nos postos de seu operador. Criar, alterar a validade ou reativar um cupom exige validade futura com fuso horário. Editar descrição/desconto ou desativar cupom vencido continua permitido sem reenviar a validade; campos omitidos permanecem intactos. Valores monetários serializados como strings decimais; nenhum pagamento real.

Idempotência reserva/início/parada: mesmo usuário/operação/chave/corpo devolve recurso original; corpo diferente retorna 409. Cancelamento é naturalmente idempotente. Sem contato por 45s proíbe novas autorizações. Reserva vence chegada 15 minutos após ACK (`RESERVATION_MINUTES`, o mesmo prazo exibido no app), confirmação 30s; expiração inicia liberação, disponibilidade só retorna após reconciliação física. Reiniciar o ESP32 não cancela uma reserva válida: a API reaplica a reserva com seu prazo original, sem estender o vencimento. Isso é diferente de uma recarga em andamento, que é interrompida com segurança após reboot.

## Bateria do carro (SoC) e bateria cheia

No início, `soc_percent` (SoC inicial do carro), `battery_kwh` (capacidade útil) e `soc_source` são opcionais; `soc_source` assume `simulated` quando só o SoC é informado. A sessão guarda `start_soc_percent` (fixo), `soc_percent` (atual, decimal string ou null), `battery_kwh` e `soc_source`. Clientes antigos sem esses campos continuam iguais (todos null). A chave de idempotência do início considera esses campos quando enviados.

- `simulated`: a cada medição do equipamento a API calcula `soc_percent = min(100, start_soc_percent + energy_wh/1000/battery_kwh*100)`; um SoC enviado pelo próprio equipamento prevalece.
- `phone` (Modo apresentação): POST `/charging-sessions/{id}/soc` {soc_percent:0–100}, somente o dono da sessão e com a sessão `starting`/`charging`. Atualiza o SoC atual (pode diminuir), muda `soc_source` para `phone` e devolve a sessão completa (200). Sessão de outra pessoa ou inexistente: 404; sessão `stopping`/encerrada: 409 `session_not_active`; corpo inválido: 422; limite de 60 chamadas/min por usuário (429). Em sessões `phone` o SoC do equipamento e a energia não alteram `soc_percent`.

Ao chegar a 100 % com a sessão ativa (energia derivada, equipamento ou `/soc`), a API faz o mesmo que uma parada solicitada: sessão `stopping`, `end_reason: "battery_full"` já registrado e um único `STOP` com `parameters.reason = "battery_full"`. Após a confirmação física a sessão termina `completed` com `end_reason: "battery_full"`, independentemente do motivo informado pelo equipamento. Chamadas repetidas não emitem nova parada. Detalhes do protocolo do equipamento em [esp32-protocol.md](esp32-protocol.md).

## Tarifa: base, por horário e por demanda

O dono define só dados base; o cálculo é do ChargeGrid (`chargegrid_core.pricing`, o mesmo na API e na conta demo do app). `GET /stations/{id}/pricing` (dono) devolve `{rules, status, connectors}`. `PUT /stations/{id}/pricing` grava `rules` validadas (`422 invalid_pricing` com a mensagem em pt-BR). O PUT é parcial: o corpo é aplicado campo a campo sobre as regras salvas, e o que não vier continua como está (o app 0.6.8 não conhece `schedule` e não o apaga).

- `demand`: `enabled`, `max_increase_percent` (0–100) e `sensitivity` (`low`/`medium`/`high`);
- `schedule` (**tarifação por horário**): `enabled` e `intervals` (até 12) `[{start, end, days, prices}]`. `start`/`end` em `HH:MM`, diferentes. `days` (0 = segunda, ao menos um) é o dia em que o horário **começa**: `Seg 22:00–06:00` vai de segunda à noite até terça de manhã, e domingo à noite continua na segunda. `prices` é a tarifa base de cada conector nesse horário (`{connector_id: "1.2000"}`, R$ 0 a R$ 100). Preços de conectores de outro posto são descartados. Horários não podem se sobrepor ("Os horários 18:00–21:00 e 20:00–22:00 se sobrepõem (Sáb)."). Fora dos horários, com a tarifação inativa ou para um conector sem preço no horário, vale `connectors.price_per_kwh`;
- `rotation`: `start_after_min`, `interval_min` e `amount` da taxa de ocupação. Fica registrada; ainda não é cobrada automaticamente;
- `peak` (legado): o antigo "horário de pico". Continua aceito e devolvido para o app 0.6.8, mas **não entra mais no cálculo**; `status.peak_now` é sempre `false`. Regras antigas salvas no banco continuam válidas (sem `schedule`, vale o padrão: ativa e sem horários).

**Sinais medidos pelo servidor em cada posto:** conectores publicados e online; recargas ativas e reservas; ocupação média dos últimos 15 min, ponderada pelo tempo; recargas iniciadas na última hora; média de inícios no mesmo dia da semana e horário nas 4 semanas anteriores; e o horário local (`America/Sao_Paulo`, para a tarifação por horário).

**Cálculo da demanda:**
1. Ocupação combinada = 60% a de agora + 40% a média.
2. Abaixo de 50% de ocupação não há pressão.
3. A tendência compara a última hora com a média histórica, com suavização de Laplace.
4. Posto lotado com reserva aguardando soma pressão.
5. A sensibilidade curva a pressão.
6. Multiplicador = `1 + teto × pressão`, em passos de 0,05× para baixo. Abaixo de 1,05× fica 1×.

**Preço:** tarifa base do horário (ou base do conector) × multiplicador. O teto da demanda vale sobre a base do horário.

`status` traz `multiplier`, `increase_percent`, `pressure` (0–100), `level` (`low`/`normal`/`high`/`very_high`) com `level_label`, `factors`, `schedule_now` (o horário vigente com `index`, `start`, `end`, `days`, `prices`, ou `null`) e o motivo `reason`/`reason_label`: `demand_schedule` ("Alta demanda · Horário 22:00–06:00"; "Demanda muito alta" no nível `very_high`), `demand` ("Alta demanda"), `schedule` ("Horário 22:00–06:00") ou `normal` ("Preço normal"). Cada conector traz `base_price_per_kwh` (do conector), `current_base_price_per_kwh` (do horário) e `current_price_per_kwh` (× demanda).

**Para o motorista:** `GET /stations` e `GET /stations/{id}` trazem `demand` (`multiplier`, `level`, `level_label`, `increase_percent`, `reason`, `reason_label`). Em cada conector há `price_per_kwh` (base do conector), `current_base_price_per_kwh` e `dynamic_price_per_kwh` (base do horário × multiplicador). As regras do dono (`pricing`) e os preços dos horários não são públicos.

**Trava do preço:** o preço é travado como num app de corrida. `POST /reservations` grava `demand_multiplier`. A recarga daquela reserva usa esse multiplicador e a base do horário vigente em `reservations.created_at` (sem coluna nova; se o dono editar o horário durante os 15 min da reserva, vale a regra editada para aquele momento). Sem reserva, `POST /charging-sessions` usa a base do horário e o multiplicador de agora. A sessão guarda `base_price_per_kwh` (a base do horário), `demand_multiplier` e `price_per_kwh` = base × multiplicador. É esse preço que o totem recebe e que a API usa no custo, de modo que mudanças posteriores não alteram uma recarga em curso. A reserva (`GET /reservations/current`) mostra o preço travado quando ele difere da base do conector.

Migração `a7c2e9d4b6f1` (`apps/api/sql/migracao_a7c2e9d4b6f1.sql`). A tarifação por horário não precisa de migração: fica em `stations.pricing`.

**No app:** a tela **Tarifa** do posto mostra a tarifa atual, a tarifa base e o motivo (atualizada a cada 30 s). O cálculo (base do horário × demanda, nível, pressão e fatores) só aparece ao tocar em **Detalhes**. Abaixo ficam quatro entradas, sem campos na visão geral: **Tarifa base** (`R$ … /kWh` por conector), **Tarifação por horário** (lista, Status e editor de cada horário: início e fim pelo seletor do sistema, dias por botões e `R$ … /kWh` por conector), **Tarifa por demanda** (`até + … %`, sensibilidade e simulação) e **Taxa de rotatividade** (`… min`, `R$`). O voltar segue editor → lista de horários → Tarifa → posto; o antigo `page=peak` abre a Tarifa. O motorista vê "Demanda alta agora: tarifa 1,3× a base" ao escolher o conector quando há acréscimo de demanda; com só a tarifa do horário, o resumo do ponto mostra "(tarifa do horário)", nunca "demanda 1×". O resumo e a estimativa da recarga usam o preço dinâmico.

## Telas do posto no app (vendedor)

**Estações → posto** reúne tudo em quatro entradas, sem repetição:

- **Dados da estação:** nome, endereço com sugestões e status.
- **Conectores:** pontos de recarga do posto. Cada um tem a edição de tipo, potência, tempo por recarga e equipamento (credencial e restauração). Também ficam aqui "Revisar e ativar ponto" e "Vincular outra tela a este posto".
- **Potência por conector.**
- **Tarifa:** tarifa atual, base e motivo; tarifa base por conector, tarifação por horário, tarifa por demanda e taxa de rotatividade.

Saíram "Configurações adicionais" e a antiga tela "Pontos e equipamentos". O preço por kWh existe só em **Tarifa**. Latitude e longitude não aparecem mais: o cadastro (onboarding e novo posto) e a edição do endereço gravam as coordenadas da sugestão escolhida ou da busca pela API própria. Em conta real, um endereço sem resultado é recusado com "Não encontramos este endereço…". Na demo, usa-se o centro de São Paulo.

## Código público do ponto

Pontos novos recebem um código curto: `CG-` + 4 caracteres sem 0/O e 1/I (`app.service.new_public_code`, ex.: `CG-L6MX`). Antes eram `CG-` + 12 hexadecimais. A migração `d1e8f3a2c7b5` encurta os códigos longos existentes; outros formatos (`CG-PAINEL-03`, códigos da demo) ficam iguais. O totem recebe o código novo na próxima sincronização.

## Fluxos do motorista no posto

A tela do posto mostra os conectores e dois botões; não lista mais os pontos nem o aviso do código #F, que ficava repetido.

- **Reservar estação** (`booking`, `kind=reserve`): conector → reserva (ponto guardado por 15 min a partir da confirmação do posto + taxa) → cobrança (tempo, valor ou autonomia) → potência → pagamento → revisar → **Confirmar reserva**. Em **Recarga Agendada**, o app mostra "Chegue até" e o botão **Cheguei: informar código**. Os horários fictícios (00:00, 00:30…) saíram, porque a API reserva a partir de agora.
- **Carregar agora** (`kind=now`): conector → cobrança → potência → pagamento → revisar → **Confirmar e iniciar no ponto** → código #F → início. Não há etapa de reserva nem taxa.

O plano da busca (por valor, tempo ou autonomia) chega ao assistente já preenchido.

## Autocomplete de endereço

`GET /geo/address-suggestions?q=<texto ou CEP>[&lat=&lng=]` (usuário autenticado, 60 consultas/min) devolve `{items:[{label,street,number,district,city,state,postcode,latitude,longitude,place?}],available,attribution}`. É um endpoint próprio, sem chave e sem custo: texto livre consulta o [Photon](https://photon.komoot.io) (geocodificador do OpenStreetMap feito para busca enquanto se digita; o Nominatim proíbe esse uso), limitado ao Brasil e com viés por `lat/lng`; um CEP de 8 dígitos consulta o [ViaCEP](https://viacep.com.br) e o Photon completa as coordenadas. `label` segue o formato dos endereços salvos (`Rua X, 123, Bairro, Cidade - UF`); se a rua vier sem número, o número digitado é aproveitado. Cache em memória (24 h; falha, 60 s), timeout de 2,5 s e falha silenciosa (`available: false`, lista vazia): o cadastro continua aceitando o texto digitado. Menos de 3 caracteres (e não CEP) não consulta ninguém. A interface mostra a atribuição exigida pelo OpenStreetMap.

Uso: app (cadastro da estação no onboarding e **Dados da estação**; espera 350 ms sem digitação, descarta respostas antigas; a localização do posto vem do endereço: da sugestão escolhida ou, sem escolha, da primeira sugestão da busca; o app não pede latitude/longitude) e painel web (**Dados da estação**: combobox acessível com ↑/↓, Enter e Esc; o **Salvar** envia endereço + coordenadas). A conta demo do app e o mock do painel respondem com endereços fixos de São Paulo, sem rede.

## Modo Motorista

`GET/PUT /driver/profile` (veículo e preferências de turno/refeições), `POST /driver/plan` {soc_percent,lat?,lng?,radius_km?,mode?:"auto"|"full_shift",vehicle?,preferences?,context?,live_signals?} e `POST /driver/next-stop` planejam recargas para motoristas de app com o motor `chargegrid_core.driver`. Postos expõem `amenities:[{kind,name,distance_m}]` (`restaurante`, `cafe`, `banheiro`, `shopping`, `conveniencia`), editáveis pelo dono em PATCH `/stations/{id}`. Demanda é estimativa; clima da Open-Meteo é opcional, com fallback silencioso e origem em `demand.source`/`demand.signals`. Detalhes em [modo-motorista.md](modo-motorista.md).

## Dashboard do proprietário (`/owner/*`)

Somente leitura, para contas com `operator_enabled` (senão 403). Escopo: postos cujo `owner_id` é o usuário; `station_id` opcional é validado como no restante da API (posto de outro dono → 404). Período: `from`/`to` ISO 8601 **com fuso** (padrão: últimos 7 dias; até 366 dias; `to` > `from`, senão 422 `invalid_period`). Valores decimais são strings. Fuso de relatório: `America/Sao_Paulo`. Cálculos em `chargegrid_core.analytics` (mesmos usados pela demo e pelo dashboard).

- `GET /owner/overview?from&to&station_id` → `{period, station_id, kpis:{revenue, energy_wh, energy_kwh, sessions, average_ticket, occupancy_percent, uptime_percent, reservations, no_shows, no_show_percent, interrupted_sessions, failed_sessions, active_sessions, points, points_online}, stations:{total, active, points, points_published, points_online}, ranking:[{connector_id, station_id, station_name, public_code, revenue, energy_kwh, sessions, occupancy_percent}], generated_at}`. Receita/energia/sessões: sessões `completed`/`interrupted` com energia > 0 e `ended_at` na janela (atribuição integral ao término). Ocupação: minutos com sessão iniciada (recortados na janela) ÷ (pontos publicados × minutos da janela). Disponibilidade: retrato atual de pontos publicados online (sem histórico de estados). Ticket médio/percentuais `null` quando não há denominador.
- `GET /owner/timeseries?metric=all|revenue|energy_kwh|sessions&granularity=hour|day` → `{granularity, timezone, basis:"ended_at", buckets:[ISO local], series:{revenue:[], energy_kwh:[], sessions:[]}}` com baldes vazios preenchidos; `hour` aceita até 31 dias.
- `GET /owner/heatmap` → `{days:["Seg"..."Dom"], hours:[0..23], cells:[[7×24]], max, peak_hours:[{hour, sessions}], basis:"started_at"}`.
- `GET /owner/sessions?status=a,b&q=&limit&offset` e `GET /owner/reservations?...` → páginas `{items,total,limit,offset}` filtradas por `created_at` na janela. Projeção sem identidade do motorista: sessão `{id, station_id, station_name, connector_id, public_code, status, created_at, started_at, ended_at, duration_minutes, energy_kwh, price_per_kwh, discount_percent, cost_estimate, source, end_reason}`; reserva `{id, station_id, station_name, connector_id, public_code, status, created_at, expires_at, no_show}` (`no_show` = `expired`). `q` busca nome do posto, código do ponto ou prefixo do ID.
- `GET /owner/export/sessions.csv|sessions.json|reservations.csv|reservations.json` com os mesmos filtros: CSV RFC 4180 (vírgula, decimal com ponto, UTF-8, cabeçalho em português, células com `= + - @` neutralizadas); JSON com envelope `{schema_version, dataset, generated_at, timezone, currency, units, filters, total, notes, items}`. `Cache-Control: no-store`, `Content-Disposition` com nome do arquivo. Acima de 10 000 linhas: 413 `export_too_large`.
- `GET /owner/alerts` → `{items:[{kind, severity, title, detail, station_id, connector_id, station_name, public_code, at}]}`; tipos `device_offline`, `device_fault`, `no_device`, `command_failed` (falhou/expirou nas últimas 24 h) e `point_idle` (publicado e online, sem recarga há 72 h).
- `GET /owner/live` → `{items:[ponto + {station_name, station_active, has_device, device_id, online, last_seen, firmware_version, physical_state, availability_status, reserved_until, retired, session:{id,status,started_at,energy_wh,cost_estimate,soc_percent,power_w,source,last_measurement_at}|null}]}`. `power_w` é a última telemetria da sessão. O estado segue as mesmas regras de `availability_status`, com número fixo de consultas.

Ações de gestão continuam nos endpoints existentes (PATCH `/stations/{id}`, PATCH `/connectors/{id}`, `/coupons`, `/devices/*`). Índices de apoio: migração `a3f1c9d2e7b4`. Insights de IA: POST `/ai/owner-insights` (contrato `{summary, recommendations:[{title, detail, impact, kind}], generated_at, model}`); o dashboard trata 404/erro como estado vazio.

## Previsão de ocupação (`/owner/forecast`, `/stations/{id}/best-times`)

Detalhes do método, dados e métricas: [previsao-ocupacao.md](previsao-ocupacao.md). Somente leitura; `Cache-Control: no-store`; horários em ISO 8601 com `-03:00`.

- `GET /owner/forecast?station_id&horizon_hours=1..36` (dono do posto; 30/min) → `{station_id, generated_at, timezone, as_of, horizon_hours, connectors, status:"ok"|"no_history", method:"gbm"|"baseline", method_reason, model:{version, trained_on, library, selected, offline_test:{period, baseline, gbm, daily, unseen_stations}}, coverage:{days_measured, days_synthetic, first_hour}, includes_synthetic, notes[], accuracy:{window_days, origins, status:"ok"|"insufficient_history", baseline:{mae_pp, wape, accuracy_percent}, gbm, daily:{baseline|gbm:{peak_days, peak_hit_percent, energy_day_wape, energy_day_accuracy_percent}}}, band, energy_basis, hours:[{start, occupancy_percent, baseline_percent, low_percent|null, high_percent|null, energy_kwh, expected_multiplier, full}], peaks:[{start, end, max_percent, label}], idle:[{start, end, min_percent, label}], suggestions:[{kind:"enable_demand"|"raise_demand_cap"|"schedule_peak"|"schedule_idle", title, detail, window, action:{type:"pricing_rules", patch, preview?:[{connector_id, public_code, from, to}]}}]}`. `patch` é aplicado pelo `PUT /stations/{id}/pricing` existente (PUT parcial). O modelo só entra quando vence a média no teste offline e no backtest de 14 dias do posto.
- `GET /owner/occupancy-history?station_id&weeks=1..8` → `{days, hours, occupancy_percent:[[7×24]], energy_kwh:[[7×24]], samples:[[7×24]], max_occupancy_percent, from, to, coverage, includes_synthetic, notes}` (média por dia da semana e hora; `null` = sem dados).
- `GET /stations/{station_id}/best-times?hours=3..24` (qualquer usuário autenticado, posto ativo; 60/min) → `{hours:[{start, expected_price_per_kwh, level, level_label}], best:{start, end, price_from, saving_vs_now_percent|null, reason, level_label}, now:{price_per_kwh}, stable, note, method, generated_for, timezone, includes_synthetic}`. Preço esperado = tarifa do horário × multiplicador previsto; sempre "Estimativa", travado ao reservar/iniciar. Sem números de ocupação do dono.
- Agregados duráveis: `connector_hourly_stats` e `aggregate_watermarks` (migração `c5f0a7e3d912`); rollup idempotente dentro de `/internal/keepalive` (resposta `{status, rollup:{from, to, rows}|{status:"failed"}}`). `tools/maintenance.py` só apaga telemetria já agregada.

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

Corpo: `{session_id}`. Só aceita sessões do próprio usuário; para as demais, a resposta é 404. Sessões ainda não encerradas (diferentes de `completed`/`interrupted`) recebem 409 `session_not_finished`.

Resposta 200: `{session_id,summary,tips:[string],comparison:{cost_brl,energy_kwh,price_per_kwh,avg_cost_brl,avg_price_per_kwh,cost_vs_avg_percent,peak_hour,history_sessions},generated_at,model}`.

POST `/ai/owner-insights`

Exige operador habilitado; caso contrário, 403. Corpo opcional, o mesmo filtro do dashboard:
`{from?:ISO-8601, to?:ISO-8601, station_id?:UUID, days?:1–366}`. Sem `from`, analisa os últimos `days` dias (padrão 30)
até `to` ou agora; janela inválida → 422 `invalid_period`; posto de outro dono → 404. **Contrato estável, consumido pelo
dashboard web:**

```json
{"summary": "string",
 "recommendations": [{"title": "string", "detail": "string", "impact": "high|medium|low",
                      "kind": "pricing|operations|marketing"}],
 "generated_at": "ISO-8601 UTC",
 "model": "deepseek/deepseek-v4.1-flash | chargegrid-regras"}
```

Os indicadores são os mesmos de `/owner/overview`, `/owner/heatmap` e `/owner/alerts` (`chargegrid_core.analytics`):
receita e energia estimadas, ticket médio, ocupação, disponibilidade, interrupções/falhas, no-show de reservas,
sessões por hora e alertas de pontos. A IA apenas redige a partir desses números (sem raciocínio estendido, ~2–5 s).
Se a resposta da IA for inválida ou indisponível, a rota devolve as recomendações por regras.

## Banco e papel de execução

Migrações usam `MIGRATION_DATABASE_URL`, uma conexão administrativa direta. A aplicação usa `DATABASE_URL` pelo pooler em modo transação com prepared statements automáticos desativados. A migração cria o papel sem login `chargegrid_api`, remove acesso público e de `anon`/`authenticated`, ativa RLS e concede uma política somente ao papel da API. O administrador deve executar `GRANT chargegrid_api TO <usuario_sql_da_api>`; esse usuário não deve ser dono das tabelas nem ter `BYPASSRLS`. A Data API do schema deve permanecer desativada. Nunca conceder `chargegrid_api` aos papéis Supabase `anon` ou `authenticated`.

A versão atual exige `alembic upgrade head` até `d85af641bc01`. Além da migração anterior de tipo de conta e cronologia, ela permite posto de fábrica sem dono e cria `device_claims` com auditoria, unicidade e RLS. O runtime recebe somente SELECT/UPDATE nessa tabela: criar claims exige a credencial administrativa da ferramenta de fábrica. Nenhum owner legado é alterado. Aplicar a migração antes de publicar o código correspondente. Downgrade recusa remover a nulabilidade enquanto houver postos sem dono, evitando apagar equipamento para retornar ao esquema antigo.

A migração `a71c3e5d9b20` (assistente de IA, sobre `a3f1c9d2e7b4`) cria `ai_usage` somente com metadados de uso: usuário, função, status, modelo, tokens, custo, latência e nomes das ferramentas. Ela não guarda perguntas nem respostas. Aplica RLS, e somente o papel `chargegrid_api` recebe SELECT/INSERT.

A migração `b8e4f2a6c913` (sobre `a71c3e5d9b20`) revoga `PUBLIC`, `anon` e `authenticated` de `device_claims`, `session_events`, `driver_profiles` e `ai_usage`, como a migração inicial faz com as demais tabelas: no Supabase, os privilégios padrão do schema `public` concedem ALL (inclusive TRUNCATE, que o RLS não cobre) a esses papéis em toda tabela nova. O downgrade não devolve os privilégios. Detalhes da revisão em [revisao-integracao-2026-10.md](revisao-integracao-2026-10.md).
