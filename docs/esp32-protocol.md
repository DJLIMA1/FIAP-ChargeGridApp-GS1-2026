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

Sync durante carga 5s, demais 10s. Comunicação ausente 45s determina parada local, guardar energia final até reconectar. API nunca interpreta offline/timeout como prova de parada. Não executar START novamente depois de reboot. Relatar session_id anterior e stopped para reconciliação. Energia acumulada Wh da sessão, não negativa/não decrescente; SoC 0–100 ou null. Fonte simulated,measured,estimated. Duração local e limite monetário independem da interface. Parada espontânea comunica end_reason (duration_limit,cost_limit,disconnected,communication_lost,fault). Comandos vencidos provocam reconciliação, não confirmação inventada.

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
