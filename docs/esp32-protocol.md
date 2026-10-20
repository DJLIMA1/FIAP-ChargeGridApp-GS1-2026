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
- `kiosk_url`: string ou `null`. Presente só quando o vendedor ligou “pagamento pelo QR do painel”, a Stripe está configurada, o ponto está ativo e sem sessão/reserva. Contém o código #F atual (sem `#F`), então muda com ele. O painel mostra um QR desse texto na tela “Pronto” com a legenda “Sem o app? Pague aqui · TESTE”. Quem escaneia escolhe R$ 10/20/40 e paga na Checkout da Stripe pelo próprio celular.
- `payment`: `null` ou o pagamento do painel mais recente ainda não usado (`awaiting_payment`, `declined`, `authorized`, `paid`; até 35 min). O painel pode mostrar “Aguardando pagamento (teste)” e “Pagamento confirmado — iniciando”.
- Depois da confirmação o fluxo é o de sempre: a API emite `START` (com `max_cost` = teto pago; o painel para sozinho em `cost_limit`), o painel aplica e confirma com ACK. Nada liga sem pagamento confirmado pelo servidor; o QR em si não autoriza nada.

## Potência ao vivo — SET_POWER (firmware 0.5.0, API b7d2f4a91c36)

Aditivo. A API precisa ir para o ar **antes** do firmware: `SyncInput` recusa campos desconhecidos (`extra="forbid"`), então um firmware 0.5.0 numa API antiga receberia 422. Firmware antigo nunca recebe `SET_POWER` nem START com potência 0: a API só envia para quem declara a capacidade. Sem declaração, o ponto é tratado como carga fixa (a potência com que começou). Atenção: comando desconhecido **não** é ignorado pelo firmware 0.4.0, ele responde `failed unknown_command`; por isso a negociação.

**Corpo do sync (novos campos, opcionais):**
```json
{"capabilities": ["set_power_v1"], "applied_power_w": 6000,
 "charger": {"model": "simulated_bench", "variant": null, "transport": "simulated",
             "min_power_w": 1400, "max_power_w": 7200, "step_w": 100, "phases": 1}}
```
- `capabilities`: enviado em todo sync; sync sem o campo apaga a capacidade (firmware rebaixado deixa de receber SET_POWER).
- `applied_power_w`: limite instalado agora (W), 0 fora de recarga ou pausado. É a verdade do equipamento: resolve ACK perdido.
- `charger`: o equipamento declara o que controla. O piso (`min_power_w`) e o máximo entram na divisão (HCA trifásico: 4.200 W). `transport` é `simulated` enquanto não houver hardware real.

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

## Permanência após a recarga

Campos aditivos; firmware anterior ignora e continua funcionando (ele desconecta ao parar, então nunca gera permanência).

**START `parameters.overstay`** (só quando o motorista aceitou a taxa): `{"grace_minutes":10,"interval_minutes":1,"amount":"1.00","max_amount":"30.00"}` (minutos inteiros, valores em texto decimal). Com o campo, o equipamento **mantém `connected=true` depois da parada** (qualquer motivo) até o cabo ser desconectado — na bancada, pelo botão "Desconectar" (simulado). Sem o campo, comportamento antigo: desconecta ao parar. Após um reboot o cabo volta como `connected=false` (a API encerra a permanência com `device_reboot`, cobrando só até a última evidência). O corpo do sync não muda: `connected` já existe.

**Resposta do sync, nível de cima:** `"overstay": {"session_id":"UUID","status":"grace"|"billing"|"capped"|"no_fee","grace_remaining_seconds":462,"fee_due":"3.00","max_fee":"30.00","amount":"1.00","interval_minutes":1}` ou `null`. Vem fora de `authorized` porque a sessão já terminou. O painel mostra "Recarga concluída — desconecte em mm:ss" (contagem local a partir de `grace_remaining_seconds`, como o código #F) e depois "Taxa de permanência: R$ x". `no_fee`: "Recarga concluída — desconecte o cabo". Intervalo de sync: o ocioso (5 s); ao desconectar, sincronizar imediatamente.

A API conta só tempo confirmado: cada sync com `connected=true` soma até 45 s desde o anterior; intervalo maior não é cobrado; repetição de `sequence` não soma; `connected=false` encerra. Novo START continua exigindo o ponto livre (`connected=false`).

