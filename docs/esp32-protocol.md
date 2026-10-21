# Protocolo ESP32 v1

POST `/v1/devices/sync`, TLS validado, `Authorization: Device <device_key>`. Chave vincula dispositivo; não enviar device_id como autoridade. Corpo:
```json
{"boot_id":"uuid-ou-identificador-aleatorio","sequence":1,"firmware_version":"0.1.0","session_id":null,"physical_state":"idle","connected":false,"soc_percent":null,"energy_wh":0,"power_w":0,"source":"simulated","captured_at":"2026-09-18T12:00:00Z","end_reason":null,"acks":[{"command_id":"UUID","status":"applied","error":null}]}
```
Estados físicos idle,reserved,charging,stopped,fault. ACK status received,applied,failed. `session_id` obrigatório para energia/soc de sessão. Sequência crescente por boot; mesma sequência é repetição, menor ignorada. Novo boot: saída desenergizada; enviar idle/stopped, nunca retomar sessão sem autorização nova.

Resposta:
```json
{"server_time":"ISO8601","sync_interval_seconds":10,"control_version":1,"connector":{"id":"UUID","public_code":"CG-01","max_duration_minutes":60,"owned":true,"active":true,"presence_code":"#F12345","presence_expires_at":"ISO8601"},"authorized":{"reservation":null,"session":null},"commands":[{"id":"UUID","type":"RESERVE","version":1,"expires_at":"ISO8601","reservation_id":"UUID","session_id":null,"parameters":{"expires_at":"ISO8601"}}]}
```
Horários são ISO 8601 **com fuso**: `server_time` e `presence_expires_at` saem em UTC (`+00:00`), mas os que vêm do banco (`commands[].expires_at`, `authorized.reservation.expires_at`, `parameters.expires_at` do RESERVE) saem no fuso da sessão do PostgreSQL e com microssegundos, por exemplo `2026-10-20T04:09:50.703479-03:00`. O equipamento deve aplicar o deslocamento antes de comparar; ler só `AAAA-MM-DDTHH:MM:SS` como UTC faz um comando válido parecer vencido há 3 h (o firmware 0.7.0 antes da correção de 20/10/2026 fazia isso e ignorava os comandos em silêncio com o banco fora de UTC; o simulador sempre usou `fromisoformat`).

`authorized.reservation`: {id,expires_at,status}; `authorized.session`: {id,status,max_duration_minutes,max_cost,price_per_kwh,discount_percent}. Comandos RESERVE,RELEASE,START,STOP. START parameters inclui os limites autorizados e session_id. Comandos persistentes, IDs idempotentes, versão crescente por ponto/dispositivo. Ignorar comandos expirados/versões inferiores; guardar último aplicado. Após aplicar sincronizar imediatamente. RESERVE aplicado requer estado reserved; START aplicado requer charging e session_id correto; STOP requer stopped/idle e sessão correta; RELEASE requer idle/stopped e connected=false. ACK de outro dispositivo retorna 409 sem efetuar alterações.

`presence_code` é comum aos pontos do mesmo posto, muda a cada cinco minutos e só é enviado ao dispositivo autenticado. A tela exibe o tempo restante e uma barra de progresso. O app envia esse código junto com `public_code` ao solicitar início; a API confere o código atual do posto. `presence_code` é nulo enquanto o posto ou o ponto estiver inativo. A chave do dispositivo continua privada e serve apenas para autenticar a sincronização.

Sync de 1 s com sessão, reserva ou comando pendente; ocioso, 5 s (antes 5/10 s; reduzido em 19/10/2026 para app e totem mostrarem os mesmos números e o START/STOP chegar rápido). O firmware do painel mantém a conexão TLS aberta entre syncs (keep-alive), sem novo handshake a cada envio. Comunicação ausente 45s determina parada local, guardar energia final até reconectar. API nunca interpreta offline/timeout como prova de parada. Não executar START novamente depois de reboot. Relatar session_id anterior e stopped para reconciliação. Energia acumulada Wh da sessão, não negativa/não decrescente; SoC 0–100 ou null. Fonte simulated,measured,estimated. Duração local e limite monetário independem da interface. Parada espontânea comunica end_reason (duration_limit,cost_limit,disconnected,communication_lost,fault). Comandos vencidos provocam reconciliação, não confirmação inventada.

Energia é normalizada a três casas decimais e SoC a duas, com arredondamento decimal half-up antes de persistir ou comparar um replay. Repetir a medição final nessa precisão é permitido; mudar o resultado final continua recusado. STOP/RELEASE com ACK `failed` ou prazo vencido são reemitidos com nova versão enquanto a mesma sessão/reserva ainda aguarda reconciliação. Falhas de versões antigas não substituem comandos mais recentes, e o ponto só volta a ficar disponível após confirmação física compatível.

## Reserva e ownership — 0.3.0

Uma reserva confirmada sobrevive ao reboot até o prazo original expirar ou o consumidor cancelar. Após reboot ou divergência física, a API emite um novo `RESERVE` com versão maior. O ACK de restauração não renova `expires_at`. Durante a restauração o ponto não fica disponível; cancelamento e expiração prevalecem sobre comandos antigos. A ausência de rede nunca é prova de ponto livre.

`connector.owned` não informa a identidade do dono. Na fábrica, o equipamento recebe duas credenciais distintas: chave da API e token privado de ownership. A tela mostra `chargegrid://claim?token=...` enquanto não vinculado. Um `owned: true` booleano explícito remove o token local e oculta o QR definitivamente. Campo ausente de API anterior não apaga o token. `connector.active` exige posto e ponto ativos; a vinculação por si só não libera recarga.

## Bateria do carro (SoC) e parada por bateria cheia — 0.6.0

Campos novos são aditivos; firmware anterior ignora chaves desconhecidas e continua funcionando.

**START `parameters`** (além de `session_id`, `max_duration_minutes`, `max_cost`, `price_per_kwh`, `discount_percent`):
```json
{"soc_percent": 42.5, "battery_kwh": 60.0, "soc_source": "simulated"}
```
- `soc_percent`: SoC inicial do carro (0–100, número JSON ou `null` quando o app não informou).
- `battery_kwh`: capacidade útil (5–250, número JSON ou `null`).
- `soc_source`: `"simulated"` (valor aleatório/simulado; a API deriva o SoC pela energia), `"phone"` (Modo apresentação: o app envia a bateria real do celular via API) ou `null` (sessão sem dados de bateria).
Os três são números/strings JSON simples (não strings decimais), para leitura direta com `as<float>()`.

**`authorized.session` na resposta do sync** acrescenta, para a sessão ativa:
```json
{"soc_percent": 57.25, "start_soc_percent": 42.5, "battery_kwh": 60.0, "soc_source": "simulated"}
```
`soc_percent` é o SoC atual calculado pela API (número ou `null`) e é o valor que o painel deve exibir — é o mesmo que o app mostra. Atualiza a cada sync (5 s durante carga).

**SoC enviado pelo dispositivo** (`soc_percent` no corpo do sync):
- Envie `null`, a menos que o equipamento tenha uma medição/simulação PRÓPRIA. Nunca reenvie o `soc_percent` recebido da API: para sessões `simulated` o valor do dispositivo prevalece sobre o derivado, e ecoar o valor da API congelaria o SoC.
- Sessão `simulated` com `battery_kwh` e SoC inicial: sem SoC do dispositivo a API calcula `soc = min(100, start_soc + energy_wh/1000/battery_kwh*100)`.
- Sessão `phone`: o SoC vem do app (`POST /v1/charging-sessions/{id}/soc`); o valor do dispositivo é ignorado.

**Bateria cheia:** quando o SoC atual chega a 100 com a sessão em `charging` (derivado da energia, informado pelo dispositivo ou enviado pelo app), a API passa a sessão para `stopping` e emite um `STOP` normal com `parameters: {"reason": "battery_full"}`. O firmware aplica como qualquer STOP (desenergiza, ACK `applied`, estado `stopped`/`idle`) e pode enviar `end_reason: "battery_full"`; a sessão termina `completed` com `end_reason: "battery_full"` mesmo que o firmware informe outro motivo ou nenhum. O STOP é emitido uma única vez (sessão já em `stopping` não gera outro). Na tela, o painel pode mostrar "Bateria cheia" ao receber esse STOP.

## Pagamento no painel (QR) — 0.7.0

Campos aditivos no bloco `connector` da resposta do sync; firmware anterior ignora e continua funcionando. Pagamento sempre em **modo teste** (Stripe).

```json
{"connector": {"kiosk_url": "https://<api>/pay/k/CG-7KQ2?c=12345",
               "payment": {"status": "awaiting_payment", "status_label": "Aguardando pagamento", "amount": "20.00", "environment": "test"}}}
```
- `kiosk_url`: string ou `null`. Presente só quando o vendedor ligou “pagamento pelo QR do painel”, a Stripe está configurada, o ponto está ativo e sem sessão/reserva. Contém o código #F atual (sem `#F`), então muda com ele. O firmware só aceita `https://` com até 160 caracteres (o simulador idem) e mostra um QR desse texto na tela “Pronto” com a legenda “Sem o app? Pague aqui · TESTE”. Quem escaneia escolhe R$ 10/20/40 e paga na Checkout da Stripe pelo próprio celular.
- `payment`: `null` ou o pagamento do painel mais recente ainda não usado (`awaiting_payment`, `declined`, `authorized`, `paid`; até 35 min). O painel pode mostrar “Aguardando pagamento (teste)” e “Pagamento confirmado — iniciando”.
- Depois da confirmação o fluxo é o de sempre: a API emite `START` (com `max_cost` = teto de energia do pagamento, isto é, o valor pré-autorizado menos a reserva do teto da taxa de permanência quando o posto cobra; o painel para sozinho em `cost_limit`), o painel aplica e confirma com ACK. Nada liga sem pagamento confirmado pelo servidor; o QR em si não autoriza nada.

## Potência ao vivo — SET_POWER (firmware 0.7.0, API b7d2f4a91c36)

Aditivo. A API precisa ir para o ar **antes** do firmware: `SyncInput` recusa campos desconhecidos (`extra="forbid"`), então um firmware 0.7.0 numa API antiga receberia 422 (`{"error":{"code":"validation_error","fields":[{"field":"capabilities",...}]}}`). O firmware 0.7.0 só volta ao corpo 0.6 (sem `capabilities`, `applied_power_w`, `charger`) quando o 422 aponta um desses campos; os 422 de regra da API (`invalid_time`, `energy_regression`, `session_required`) não rebaixam o corpo, porque sem `capabilities` a API passaria a tratar o ponto como carga fixa. O simulador (`tools/device_simulator.py`) declara a versão atual do painel, 0.8.0 (`--legacy`: 0.4.0, sem SET_POWER). Firmware antigo nunca recebe `SET_POWER` nem START com potência 0: a API só envia para quem declara a capacidade. Sem declaração, o ponto é tratado como carga fixa (a potência com que começou). Atenção: comando desconhecido **não** é ignorado pelo firmware 0.4.0, ele responde `failed unknown_command`; por isso a negociação.

**Corpo do sync (novos campos, opcionais):**
```json
{"capabilities": ["set_power_v1"], "applied_power_w": 6000,
 "charger": {"model": "simulated_bench", "variant": null, "transport": "simulated",
             "min_power_w": 1400, "max_power_w": 7200, "step_w": 100, "phases": 1}}
```
- `capabilities`: enviado em todo sync; sync sem o campo apaga a capacidade (firmware rebaixado deixa de receber SET_POWER).
- `applied_power_w`: limite instalado agora (W), 0 fora de recarga ou pausado. É a verdade do equipamento: resolve ACK perdido.
- `charger`: o equipamento declara o que controla (painel: `model: "esp32_bench"`; simulador: `"simulated_bench"`, os dois com piso 1.400 W, máximo 7.200 W, passo 100 W). No painel, pedido abaixo do piso vira pausa (0 W) e o valor é arredondado para baixo no passo, nunca acima do pedido. O piso (`min_power_w`) e o máximo entram na divisão (HCA trifásico: 4.200 W). `transport` é `simulated` enquanto não houver hardware real.

**START (`parameters`):** `power_limit_w` (inteiro, pode ser **0** = começa pausado até os outros pontos confirmarem a redução) e `power_decision_id`. `max_power_kw` continua para o firmware antigo, nunca abaixo do piso. O firmware novo usa `power_limit_w` quando presente.

**Comando novo:**
```json
{"id":"UUID","type":"SET_POWER","version":7,"expires_at":"ISO8601","session_id":"UUID","reservation_id":null,
 "parameters":{"power_limit_w":6000,"previous_power_w":7200,"direction":"reduce","attempt":1,
               "decision_id":123,"reason":"site","reason_short":"Loja 24/30 kW · 3 carros"}}
```
- Aplicar só com `state == charging` e `session_id` igual; senão ACK `failed` `no_active_session`. `0` pausa: estado continua `charging`, energia para de subir, a duração continua contando. Pausa não é fim de recarga.
- ACK: `{"command_id":"UUID","status":"applied","applied_power_w":6000}`. A API aceita se `applied_power_w ≤ pedido + 1 W` (o equipamento pode arredondar para baixo, ex.: HCA em 0,1 kW) e grava o valor informado. Acima do pedido → comando `failed` `applied_power_mismatch`. Reentrega do mesmo `id`: confirmar de novo com o valor aplicado.
- Energia: integrar a potência antiga até o instante da troca e a nova daí em diante. Proteger as contas de tempo restante contra potência 0 (sem divisão por zero).
- Prazo de 15 s. A API nunca emite SET_POWER com START/STOP/RELEASE/RESERVE/FACTORY_RESET pendente no mesmo ponto, e no máximo um SET_POWER em voo; STOP sempre substitui um SET_POWER pendente. SET_POWER não marca o ponto como `reconciling`.
- Redução sem confirmação (ACK `failed` ou prazo vencido): a API reenvia uma vez (`attempt: 2`); na segunda falha manda `STOP` com `reason: "power_limit_unconfirmed"`. Enquanto a redução não é confirmada, nenhum outro ponto aumenta. Ponto offline mantém a capacidade reservada até reconciliar; o watchdog local de 45 s continua valendo.

**`authorized.session` (resposta) acrescenta:** `applied_power_kw`, `target_power_kw`, `power_state` (`applied`, `reducing`, `raising`, `waiting`, `paused`, `fixed` ou `null` sem rebalanceamento) e `power_reason_short` (até 40 caracteres, só Latin-1, cabe nas fontes do painel; ex.: `"Loja 24/30 kW · 3 carros"`). O painel mostra `applied_power_kw` depois do ACK, nunca o alvo.

**Limite de taxa:** 120 syncs/min por dispositivo (antes 40/min, que derrubava cerca de 1/3 dos syncs de 1 s com 429).

## Permanência (firmware 0.7.0)

Contrato real (`apps/api/app/overstay.py`, `modules/devices/service.py`). Campos aditivos; firmware anterior ignora e continua funcionando (ele desconecta ao parar, então nunca gera permanência). Não existe ACK de permanência: o equipamento só confirma o `STOP` como sempre e relata o cabo pelo campo `connected` que já existe no corpo do sync.

**START `parameters.overstay`** (só quando o motorista aceitou a taxa; sem termos aceitos a chave não vem):
```json
{"overstay": {"grace_minutes": 10, "interval_minutes": 1, "amount": "1.00", "max_amount": "30.00"}}
```
Minutos inteiros; `amount` (por intervalo completo depois da tolerância) e `max_amount` (teto) em texto decimal. O firmware 0.7.0 só usa a presença do objeto: com ele, **continua com `connected=true` depois de parar por qualquer motivo** (STOP da API, Encerrar local, `cost_limit`, `duration_limit`, `battery_full`, `communication_lost`) até o cabo sair; sem ele, desconecta ao parar como antes.

**O que o equipamento relata:**
1. Ao aplicar o STOP: `physical_state: "stopped"`, `session_id` da sessão, `connected: true`, `end_reason`, ACK `applied`. A API encerra a sessão e, se ela terminou `completed` com `connected=true` nesse mesmo sync (sem reboot), abre a permanência no horário do servidor. Sessão `failed`/`interrupted` (`fault`, `communication_lost`, `device_reboot`) nunca abre.
2. Depois que `authorized.session` vira `null`: `physical_state: "idle"`, `session_id: null`, `energy_wh: 0`, `connected: true`. Cada sync aceito com `connected=true` soma o tempo desde a última evidência, até 45 s; intervalo maior (offline) não é cobrado (`overstay_gap`); repetição de `sequence` não soma.
3. Cabo desconectado (botão "Desconectar" na bancada, só fora de recarga): `connected: false` e sync imediato. O primeiro sync com `connected=false` fecha (`disconnected`).
4. `RELEASE` e reboot sempre relatam `connected=false`. Um `boot_id` novo fecha a permanência com `device_reboot`, cobrando só até a última evidência de conexão. Sem notícia do equipamento por 15 min a API fecha com `observation_lost`.

**Resposta do sync, nível de cima** (fora de `authorized`, porque a sessão já terminou), ou `null` sem permanência aberta neste ponto:
```json
{"overstay": {"session_id": "UUID", "status": "grace", "grace_remaining_seconds": 600, "fee_due": "0.00",
              "max_fee": "30.00", "amount": "1.00", "interval_minutes": 1}}
```
- `status`: `grace` (tolerância), `billing` (cobrando), `capped` (no teto) ou `no_fee` (permanência registrada sem termos aceitos: `max_fee`, `amount` e `interval_minutes` vêm `null`, `fee_due` `"0.00"`). `closed` existe na sessão e no recibo, mas o bloco do sync some (`null`) ao fechar.
- `grace_remaining_seconds` inteiro; `fee_due`, `max_fee`, `amount` em texto decimal; `interval_minutes` inteiro.
- O painel mostra "Recarga concluída · desconecte em mm:ss" (contagem local a partir de `grace_remaining_seconds`, como o código #F), depois "Taxa de permanência: R$ x" (com "(valor máximo)" em `capped`) e o botão "Desconectar"; `no_fee`: "Recarga concluída · desconecte o carro" e "Sem taxa de permanência neste ponto". O simulador imprime o mesmo no terminal. Intervalo de sync: o ocioso (5 s).

Com o cabo conectado o ponto fica `occupied`: novo START (app ou pagamento pelo QR, `point_unavailable`) só depois de `connected=false`. O painel não mostra o QR de pagamento enquanto o carro está conectado, mesmo que `kiosk_url` venha preenchido.

## Totem 0.8.0 (autoatendimento sem celular)

Contrato definitivo do totem (firmware 0.8.0, API com a migração `f4b9d2c7e1a3`). Tudo é **aditivo**: com o totem desligado no posto (`stations.kiosk_mode = false`, padrão) a resposta do sync não muda (as chaves novas nem aparecem) e o firmware 0.7.0 continua idêntico. Firmware 0.8.0 numa API antiga: sem `connector.kiosk` no sync e `404` nos endpoints abaixo → totem desligado, telas atuais.

Princípios: o totem usa **as mesmas regras do app** (orçamento `payments.service.quote`/`locked_terms`, termos de permanência, `charging.service.start`, encerramento e recibo), com um perfil convidado por ponto ("Visitante do painel CG-XXXX"), sem identificar o motorista. **Nada liga sem pagamento confirmado no servidor.** O método de pagamento é decidido **pelo servidor** a partir do modo da conta do **dono** do posto: conta em *Modo apresentação* → `simulated` (rotulado `SIMULADO`, acerto local, nenhuma chamada à Stripe); conta oficial → `stripe` (modo teste, rotulado `TESTE`, QR do pedido abrindo a Checkout hospedada, mesma pré-autorização/captura/devolução do app). O equipamento nunca escolhe nem força o simulado. **Encerrar continua local** (`requestLocalSafeStop`, sem endpoint novo), inclusive para recarga iniciada pelo app (com confirmação na tela).

### Sync (só resposta; o corpo do sync não muda)

**`connector.kiosk`** — presente só com o totem ligado no posto; ausente (chave inexistente) com ele desligado:
```json
{"connector": {"kiosk": {"enabled": true, "method": "simulated", "label": "SIMULADO", "reason": null}}}
```
- `enabled`: o totem pode vender agora (posto e ponto ativos, com dono, método disponível). Não considera se o ponto está livre: reserva, sessão e cabo conectado continuam vindo de `authorized`/`overstay`/estado físico e bloqueiam o botão "Carregar agora" no firmware.
- `method`: `"simulated"` | `"stripe"` | `null`; `label`: `"SIMULADO"` | `"TESTE"` | `null`.
- `reason`: `null` ou `"payments_unavailable"` (conta oficial e Stripe não configurada no servidor → totem indisponível, `enabled: false`) ou `"point_disabled"` (posto/ponto inativo ou sem dono).

**`kiosk_order`** (nível de cima, como `overstay`) — presente só com o totem ligado; `null` ou o pedido mais recente deste ponto enquanto aberto/em recarga e até **10 min** depois de fechar:
```json
{"kiosk_order": {
  "id": "UUID", "status": "charging", "status_label": "Recarga em andamento",
  "expires_at": null, "expires_in_seconds": null, "session_id": "UUID",
  "payment": {"id": "UUID", "status": "in_use", "label": "Pago (simulado) · em uso", "method": "simulated",
              "amount": "50.00", "qr_url": null},
  "receipt": {"number": "1A2B3C4D", "energy_kwh": "2.500", "total": "5.00", "returned": "45.00",
              "return_kind": "simulated", "final": true, "end_reason": "cost_limit",
              "end_reason_label": "Limite de valor atingido", "url": "https://<api>/pay/r/UUID?t=..."},
  "error": null}}
```
- `status`: `held` (aceito; ponto travado para o totem, aguardando pagar) · `awaiting_payment` (QR da Stripe na tela) · `paid` (pagamento confirmado; START sendo emitido) · `charging` (sessão criada; segue `authorized.session`) · `finished` (recarga encerrada; recibo pode ainda não ser final) · `canceled` (cancelado pelo totem antes do START; nada cobrado) · `expired` (trava venceu sem pagamento confirmado; nada cobrado) · `failed` (pago, mas não foi possível iniciar no prazo; valor devolvido/liberado inteiro). Abertos: `held`, `awaiting_payment`, `paid`.
- `expires_at`/`expires_in_seconds`: fim da trava enquanto aberto (ISO 8601 UTC e segundos inteiros, para contagem local como o #F), `null` fora disso.
- `payment`: `null` antes de pagar; `qr_url` (https, ≤160 caracteres) só em `awaiting_payment` — permite redesenhar o QR depois de um reboot. `label` termina em "(simulado)" ou "(teste)".
- `receipt`: `null` até existir sessão. `total` = valor cobrado depois do acerto (antes: estimativa pela energia registrada + permanência); `returned`/`return_kind` (`"released"` cartão, `"refunded"` Pix, `"simulated"`) só depois do acerto; `final: true` quando o valor não muda mais (sessão encerrada, permanência fechada/ausente e acerto concluído). `url` é o recibo completo do visitante (HTML+PDF), para o QR da tela T8. Textos de `status_label`, `label` e `end_reason_label` só usam Latin-1 (cabem nas fontes `body_*`; os títulos devem usar `strings_ptbr.h`).
- `error`: `null` ou `{"code","message"}` do último problema (ex.: `{"code":"kiosk_start","message":"Não foi possível iniciar; valor devolvido"}` em `failed`).
- Firmware novo guarda `id` na NVS (`kord`) a partir de `POST /orders` e retoma pelo sync depois de queda de rede ou reboot; pedido desconhecido em estado final é ignorado.

**`authorized.session.origin`** (sempre presente com sessão ativa; firmware antigo ignora): `"app"` (iniciada pelo app) | `"kiosk_qr"` (pagamento pelo QR `/pay/k` da tela Pronto) | `"kiosk_totem"` (pedido do totem). A tela "Recarga iniciada pelo app" usa `origin == "app"`.

**Intervalo:** `sync_interval_seconds` é 1 também enquanto houver pedido do totem aberto (status do QR/START chega em ~1 s). O servidor avança o pedido aberto a cada sync (vence a trava, emite o START do pagamento confirmado, acerta o simulado). Com Stripe, a confirmação vem pelo webhook ou por uma verificação na Stripe feita **depois** de gravar o sync (no máximo a cada 3 s, sem segurar a trava do ponto); o START aparece em `commands` no sync seguinte.

### Endpoints do dispositivo (`/v1/devices/kiosk/*`)

Só `Authorization: Device <chave>` (Bearer de pessoa → `401 unauthorized`). O ponto é **sempre o da chave**; pedido de outro ponto → `404 not_found`. JSON; valores em reais como texto decimal (`"20.00"`), kWh com até 1 casa (`"10.5"`, aceita número JSON), minutos inteiros. Erros no formato da API: `{"error":{"code","message",...}}`. Totem desligado no posto → `404 kiosk_disabled` em todos. Timeout recomendado no firmware: 3 s (o `POST .../pay` com Stripe cria a Checkout e pode levar ~3 s: repetir com a mesma `Idempotency-Key` é seguro).

**`GET /v1/devices/kiosk/offer`** (30/min) — tela T0/T1/T2:
```json
{"enabled": true, "available": true, "reason": null, "reason_label": null, "open_order_id": null,
 "method": "simulated", "label": "SIMULADO", "currency": "BRL", "public_code": "CG-7KQ2", "power_kw": "7.200",
 "price": {"price_per_kwh": "2.3000", "base_price_per_kwh": "2.0000", "demand_multiplier": "1.15",
           "reason_label": "Alta demanda", "level_label": "Alta", "increase_percent": 15},
 "limits": {"max_total": "200.00", "overstay_reserve": "30.00"},
 "modes": {"value": {"shortcuts": ["10.00", "20.00", "40.00", "60.00"], "min": "5.00", "max": "170.00"},
           "time": {"shortcuts": [15, 30, 60], "min": 5, "max": 60},
           "energy": {"shortcuts": ["5.0", "10.0", "20.0"], "min": "1.0", "max": "73.9", "decimals": 1}},
 "overstay": {"enabled": true, "version": "...", "summary": "...", "grace_minutes": 10, "interval_minutes": 1,
              "amount": "1.00", "max_amount": "30.00", "fee_per_minute": "1.00"},
 "hold_minutes": 5, "qr_hold_minutes": 10, "start_timeout_seconds": 60}
```
- `enabled`/`method`/`label`/`reason` como em `connector.kiosk` (`reason_label` em texto). `available`: ponto livre agora; senão `reason` = `kiosk_in_use` (pedido do totem aberto; `open_order_id` traz o id para retomar) · `reserved` · `charging` · `occupied` (cabo conectado/permanência) · `reconciling` · `offline` · `fault` · `disabled`.
- `price`: tarifa vigente (base do horário × demanda) e o motivo, a mesma do app.
- `modes`: atalhos filtrados pelos limites. Teto por pedido **R$ 200** sobre o total pré-autorizado (energia + reserva do teto da taxa de permanência): `value.max = 200 − reserva`; `time.max` = menor entre a duração máxima do ponto e o tempo cujo teto cabe; `energy.max` = kWh cujo teto cabe. Mínimos: R$ 5,00, 5 min, 1,0 kWh. A estimativa local da tela T2 é só indicativa; vale o orçamento.
- `overstay`: termos públicos vigentes (`enabled: false` e `null` nos demais sem taxa).

**`POST /v1/devices/kiosk/quote`** (30/min) — T3. Corpo: `{"mode":"value","amount":"20.00"}` | `{"mode":"time","minutes":30}` | `{"mode":"energy","energy_kwh":"10.0"}`. Reaproveita `payments.service.quote` com o convidado (mesmo teto, termos travados, motivo da demanda e reserva de permanência do app). Resposta:
```json
{"quote_hash": "32 hex", "mode": "value", "amount": "20.00", "minutes": null, "energy_kwh": null,
 "total": "50.00", "energy_cap": "20.00", "overstay_reserve": "30.00",
 "price_per_kwh": "2.3000", "base_price_per_kwh": "2.0000", "demand_multiplier": "1.15", "discount_percent": 0,
 "demand": {"multiplier": "1.15", "level_label": "Alta", "reason_label": "Alta demanda"},
 "estimated_energy_kwh": "8.696", "max_duration_minutes": 73, "power_kw": "7.200",
 "overstay": {"...": "termos públicos, como na oferta"}, "method": "simulated", "label": "SIMULADO"}
```
`total` é o valor pré-autorizado (simulado ou Stripe). `quote_hash` é opaco (hoje 32 hex; aceite até 64) e muda se tarifa, demanda, termos de permanência, potência ou método mudarem. Erros: `422 invalid_quote` (falta o campo do modo / abaixo do mínimo do provedor), `422 amount_below_minimum`, `422 amount_above_limit` (total > R$ 200), `503 payments_unavailable`, `422 validation_error`.

**`POST /v1/devices/kiosk/orders`** (`Idempotency-Key` obrigatória, 6 por 5 min) — "Aceitar e pagar". Corpo: `{"quote_hash": "...", "mode": "value", "amount": "20.00", "overstay_terms_version": "..." | null}` (o mesmo campo do modo do orçamento). Sob a trava do ponto (a mesma de `start()`), recalcula o orçamento: diferente → `409 quote_changed` (o corpo do erro traz `quote` novo; refaça T3). Cria o pedido `held` com os termos travados e **trava o ponto por 5 min** (app e reserva recebem `409 point_unavailable` com `reason: "kiosk_in_use"`). Responde `201` com o **pedido** (abaixo); repetir com a mesma chave devolve o mesmo pedido. Erros: `409 point_unavailable` (+ `reason` como em `available`), `409 order_open` (já existe pedido aberto neste ponto; `order_id` no erro), `409 quote_changed`, `409 overstay_terms_changed`, `503 payments_unavailable`, `422 idempotency_key_required`, `409 idempotency_conflict`, `429 rate_limited`.

**Pedido** (resposta de `orders`, `pay`, `cancel` e `GET`):
```json
{"id": "UUID", "status": "held", "status_label": "Pedido aceito · aguardando pagamento",
 "method": "simulated", "label": "SIMULADO", "expires_at": "ISO8601", "expires_in_seconds": 300,
 "quote": {"mode": "value", "amount": "20.00", "minutes": null, "energy_kwh": null, "total": "50.00",
           "energy_cap": "20.00", "overstay_reserve": "30.00", "price_per_kwh": "2.3000",
           "estimated_energy_kwh": "8.696", "max_duration_minutes": 73},
 "payment": null, "session_id": null,
 "session": null,
 "receipt": null, "receipt_url": "https://<api>/pay/r/UUID?t=<token>", "error": null}
```
`payment`, `receipt`, `error` como em `kiosk_order`; `session`: `null` ou `{"status","energy_kwh","cost","started_at","ended_at","end_reason"}`. `receipt_url` (≤160 caracteres) já vale desde a criação (mostra o status até existir recarga).

**`POST /v1/devices/kiosk/orders/{id}/pay`** (`Idempotency-Key`, 10 por 5 min) — T4. Corpo `{}` ou `{"method": "simulated"|"stripe"}` só como conferência: se não for o método decidido pelo servidor → `409 method_mismatch` e nada é criado (o dispositivo não força o simulado). Métodos reservados, ocultos e recusados com `409 method_unavailable`: `"voucher"` (voucher do caixa) e `"card_terminal"` (maquininha física).
- `simulated` (dono em Modo apresentação): cria o pagamento `provider: "simulated"` já `paid` (sem Stripe) e emite o START uma única vez; resposta com `status` `charging` (ou `paid` se o ponto ainda reconcilia; o START sai no próximo sync, até o prazo de 10 min, senão `failed`).
- `stripe` (dono oficial): cria o pagamento aguardando e a Checkout hospedada; `payment.qr_url = "https://<api>/pay/o/<id>?t=<token>"` (≤160) e o pedido vai a `awaiting_payment` com a trava estendida a **10 min** desde agora. A confirmação vem pelo webhook/verificação; então o servidor emite o START (mesmo `start_kiosk` do QR do painel).
- Erros: `409 order_not_payable` (pedido não está `held`/`awaiting_payment`), `409 order_expired`, `409 method_changed` (o dono trocou de modo depois do orçamento; o pedido é cancelado), `409 method_mismatch`, `409 method_unavailable`, `503 payments_unavailable`, `502 payment_provider_error` (repetir com a mesma chave).

**`POST /v1/devices/kiosk/orders/{id}/cancel`** (20 por 5 min) — Voltar/Cancelar/inatividade antes do START: libera a trava na hora; Checkout expirada, autorização liberada ou valor devolvido inteiro (simulado: acerto local). Idempotente em pedido já fechado. Depois do START → `409 order_in_use` (use Encerrar local).

**`GET /v1/devices/kiosk/orders/{id}`** (120/min) — status atual (verifica a Stripe no máximo a cada 3 s, emite START pendente, conclui o acerto). Enquanto `held`, cada consulta (e cada `pay`) **renova a trava para 5 min**; `awaiting_payment` não renova (vence 10 min depois do QR); `paid` dura até o prazo de início do pagamento (10 min).

**Trava do ponto:** um pedido aberto por ponto. Trava vencida libera o ponto **na hora** (a disponibilidade ignora trava vencida; o pedido vira `expired` no próximo contato e o pagamento não confirmado é cancelado; pagamento tardio na Stripe é devolvido inteiro). Antes de "Aceitar" não há trava: se chegar sessão/reserva no sync, o firmware aborta ("Este ponto acabou de ser iniciado pelo app").

### Páginas do visitante (fora de `/v1`, HTML, CSP restritiva)

- `GET /pay/o/{order_id}?t=<token>` — QR do pedido (Stripe): redireciona (303) à Checkout hospedada enquanto aguarda; depois, à página do recibo/status.
- `GET /pay/r/{order_id}?t=<token>` — status e recibo do visitante (a partir de `receipts.service`), com atualização automática até ficar final; `GET /pay/r/{order_id}.pdf?t=<token>` — PDF do recibo (depois que a recarga existe). Pagamento simulado aparece rotulado **SIMULADO** (cabeçalho e recibo: "Pagamento simulado: nenhum dinheiro real foi movimentado").
- Token: 24 bytes (32 caracteres base64url), um por pedido, entregue só ao dispositivo autenticado; derivado (HMAC) de um segredo do posto que nunca sai do servidor + sal aleatório do pedido; o banco guarda só o sal e o SHA-256. Sem dado pessoal. Token errado → 404.

## Carregador GoodWe do conector (charger_link)

**Estação = a TELA** (painel ESP32-S3, o dispositivo com chave); **cada ponto é um carregador** GoodWe HCA G2 (hoje o simulado num ESP32 DevKit, `docs/carregador-hca-simulado.md`) com endereço Modbus. A tela é o mestre Modbus TCP dos carregadores na rede local e comanda **um ou mais** deles (seção "Vários carregadores por tela"); a API continua falando só com a tela, e os comandos **não mudam** (START/STOP/SET_POWER/RESERVE/RELEASE). Sem `charger_link` (API antiga ou bloco inválido) a tela segue idêntica a antes: relé/simulação interna e `charger.model = "esp32_bench"`.

**Toda recarga com `charger_link` é no carregador (Modbus). Não existe mais recarga na simulação interna da tela quando há `charger_link`:**
- START: a tela tenta o carregador **na hora**, mesmo que a última leitura tenha falhado: até 2 tentativas curtas; a 2ª refaz a conexão e resolve o nome já (mDNS com até 1,2 s, sem esperar o recuo), e o último IP bom continua valendo se o mDNS não responder. Só com a releitura confirmando sai o ACK `applied`; sem resposta → ACK `failed` com `charger_offline` (a API encerra a sessão com `end_reason: "charger_offline"`, "Carregador offline — use outro ponto desta estação"). Exceção Modbus (`charger_rejected`) ou releitura diferente (`charger_readback_mismatch`) não são repetidas. Se o carregador chegou a ligar, a tela manda `10060 ← 1`.
- Fora de recarga a tela lê o carregador sempre (~1 s online; offline, a cada 5 s, com consulta mDNS a cada 5 s) e reporta `charger.link`: a API usa isso para a disponibilidade **por carregador** (carregador offline = só aquele ponto indisponível, `unavailable_reason: "charger_offline"`; a estação só fica offline sem contato da tela).
- O sync com a API tem prioridade sobre a leitura Modbus no laço: com o sync vencido, a leitura espera a próxima volta (no máximo ~0,8 s por carregador offline por volta). O vigia de 45 s sem a API nunca depende do Modbus.
- Teste real de 21/10 (sessão `425336ed…`, ponto `CG-4HPF`): a tela aceitou o START com o link `offline` havia 1,5 min e carregou na simulação ("mestre=nunca" no carregador). Nos syncs o link ficava `online` alguns minutos depois de cada boot da tela e caía para `offline` até o próximo reboot. Causa: depois de uma falha a tela descartava o IP e dependia só do mDNS (multicast, 500 ms a cada 15 s) com o Wi-Fi da tela em economia de energia. Correções: START estrito acima, Wi-Fi da tela sem economia (`WiFi.setSleep(false)`), mDNS reiniciado quando o IP da tela muda (ou após 3 consultas sem resposta), último IP bom como reserva. O `communication_lost` daquela sessão veio de um **reboot da tela** no meio da recarga (novo `boot_id`, `sequence` 1, 11 s depois do sync anterior), não do vigia de 45 s: a tela agora relata `end_reason: "device_reboot"` nesse caso (e imprime `reset_reason` no boot e no `CG_STATUS`).

**Resposta do sync, `connector.charger_link`** (a API manda para todo conector; `null`/ausente só em API antiga):
```json
{"model": "goodwe_hca_g2", "transport": "modbus_tcp", "address": 1, "host": "cg-hca-1.local"}
```
- `address`: unit id Modbus 1–247 (o `charger_address` do conector = `CG_ADDR` do ESP). `host`: nome mDNS ou IP (`[A-Za-z0-9.-]`, até 63); sem `host`, a tela usa `cg-hca-<address>.local`. `port` opcional (padrão 502). Outro `model`/`transport` ou endereço fora da faixa = só a simulação interna (como API antiga).
- A troca do link só vale fora de recarga. Fallback de IP fixo na tela pelo serial: `CG_CHARGER_IP <ip>` (NVS; `clear` volta ao host).

**Corpo do sync, `charger`**: limites do carregador quando ele responde (ou na recarga por Modbus); offline, os de sempre com `link: "offline"`. `address`/`link` sempre que há `charger_link`.
```json
{"model": "goodwe_hca_g2", "variant": "GW7K-HCA-20", "transport": "modbus_tcp", "address": 1, "link": "online",
 "min_power_w": 1400, "max_power_w": 7000, "step_w": 100, "phases": 1}
{"model": "esp32_bench", "transport": "simulated", "address": 1, "link": "offline",
 "min_power_w": 1400, "max_power_w": 7200, "step_w": 100, "phases": 1}
```
- `link`: `online` se a última leitura/escrita teve resposta, `offline` senão. `address` e `link` são campos do `ChargerInfo` (API b7c4e2a9d1f3+). `applied_power_w` continua sendo o limite instalado (no 10029; 0 pausado/fora de recarga); `power_w`/`energy_wh` vêm do 10015 lido a cada ~1 s. `source` continua `"simulated"` (no carregador simulado a potência também é SIMULADA). `capabilities` inclui `multi_charger_v1` (tela que comanda vários carregadores).

**Tradução na tela** (todas FC06; ACK `applied` só depois da releitura de 10029/10060/10015..10017):

| Comando | Escritas | Confirmação |
| --- | --- | --- |
| START | `10032 ← 0` (uma vez por link, só se diferente), `10029 ← limite` (só se mudou), `10060 ← 2`; limite < 1.400 W: só `10060 ← 1` | 10029 = limite, 10060 = 2, 10017 ∈ {2, 3}; pausado: 10060 = 1 e 10015 = 0 |
| SET_POWER | igual ao START sem o 10032; < 1.400 W pausa com `10060 ← 1` | idem; `applied_power_w` = 10029 × 100 (0,1 kW para baixo, teto 7.000 W) |
| STOP | `10060 ← 1` | 10060 = 1 e 10015 = 0 |

- ACK `failed`: `charger_offline`, `charger_rejected` (exceção Modbus) ou `charger_readback_mismatch`. START com falha não cria sessão local (a API manda o STOP `charger_offline`/`start_failed`, que a tela confirma sem depender do carregador; a sessão termina `failed` com esse motivo). SET_POWER com falha mantém o limite anterior. STOP de uma recarga sem confirmação: a tela para a sessão do mesmo jeito (sync `stopped`) e reenvia `10060 ← 1` a cada leitura; o ACK sai `failed`.
- **Perda do carregador** durante a recarga: sem resposta por 5 s (inclusive pausada), 10017 = 5/8 ou parado sozinho por 3 leituras → parada segura local com `end_reason: "device_fault"` e sync imediato. O carregador abre o relé sozinho depois de 15 s sem contato do mestre.
- Uma conexão TCP por carregador, timeouts curtos (400 ms conexão, 400 ms resposta, mDNS 500 ms — 1,2 s no START); o LVGL roda em outra tarefa. Diagnóstico pelo serial do painel: `CG_CHARGER` (link, `recarga=modbus|recusada_carregador_offline`, IP resolvido e último IP bom, e os carregadores adicionais).

### Vários carregadores por tela (`multi_charger_v1`)

- A resposta do sync **da tela** traz `chargers: [{address, connector_id, public_code, charger_link}]`: os carregadores adicionais do posto ligados a ela (criados por "Adicionar carregador", `POST /v1/connectors/{id}/chargers`). API antiga: ausente (nenhum).
- Para cada um, a tela faz um **sync endereçado**: o mesmo `POST /v1/devices/sync`, com a mesma chave, e `charger_address: N` no corpo. Corpo e resposta têm o formato do sync de um ponto (sessão, comandos, ACKs, `charger`, `applied_power_w`), mas valem para o carregador N; na API cada carregador tem sessão, comandos e estado próprios (linha própria em `devices`, `parent_device_id` = a tela). Endereço sem carregador desta tela → 409 `charger_not_linked`; `charger_address` igual ao do ponto da tela = o sync de sempre.
- Firmware: até 3 carregadores adicionais (`firmware/esp32/src/extra_chargers.cpp`, testado no host). O ponto da tela continua com a interface do painel; os adicionais não têm interface na tela (iniciados/encerrados pelo app; o código de presença da tela vale para a estação toda). Mesmas regras: START estrito por Modbus, energia pelo 10015, SET_POWER por releitura, perda → `device_fault`, vigia de 45 s por carregador, diário na NVS (`x<endereço>s/e/v/c`, lista `xaddrs`) e reboot → `device_reboot`. Sem SoC próprio (a API deriva da energia), sem permanência e sem totem nos adicionais. Sync endereçado recusado (409/422) pausa aquele carregador por 10 min. Um carregador que a tela deixa de sincronizar fica offline (`charger_offline`) só ele.
