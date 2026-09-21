# Protocolo ESP32 v1

POST `/v1/devices/sync`, TLS validado, `Authorization: Device <device_key>`. Chave vincula dispositivo; não enviar device_id como autoridade. Corpo:
```json
{"boot_id":"uuid-ou-identificador-aleatorio","sequence":1,"firmware_version":"0.1.0","session_id":null,"physical_state":"idle","connected":false,"soc_percent":null,"energy_wh":0,"power_w":0,"source":"simulated","captured_at":"2026-09-18T12:00:00Z","end_reason":null,"acks":[{"command_id":"UUID","status":"applied","error":null}]}
```
Estados físicos idle,reserved,charging,stopped,fault. ACK status received,applied,failed. `session_id` obrigatório para energia/soc de sessão. Sequência crescente por boot; mesma sequência é repetição, menor ignorada. Novo boot: saída desenergizada; enviar idle/stopped, nunca retomar sessão sem autorização nova.

Resposta:
```json
{"server_time":"ISO8601","sync_interval_seconds":10,"control_version":1,"connector":{"id":"UUID","public_code":"CG-01","max_duration_minutes":60},"authorized":{"reservation":null,"session":null},"commands":[{"id":"UUID","type":"RESERVE","version":1,"expires_at":"ISO8601","reservation_id":"UUID","session_id":null,"parameters":{"expires_at":"ISO8601"}}]}
```
`authorized.reservation`: {id,expires_at,status}; `authorized.session`: {id,status,max_duration_minutes,max_cost,price_per_kwh,discount_percent}. Comandos RESERVE,RELEASE,START,STOP. START parameters inclui os limites autorizados e session_id. Comandos persistentes, IDs idempotentes, versão crescente por ponto/dispositivo. Ignorar comandos expirados/versões inferiores; guardar último aplicado. Após aplicar sincronizar imediatamente. RESERVE aplicado requer estado reserved; START aplicado requer charging e session_id correto; STOP requer stopped/idle e sessão correta; RELEASE requer idle/stopped e connected=false. ACK de outro dispositivo retorna 409 sem efetuar alterações.

Sync durante carga 5s, demais 10s. Comunicação ausente 45s determina parada local, guardar energia final até reconectar. API nunca interpreta offline/timeout como prova de parada. Não executar START novamente depois de reboot. Relatar session_id anterior e stopped para reconciliação. Energia acumulada Wh da sessão, não negativa/não decrescente; SoC 0–100 ou null. Fonte simulated,measured,estimated. Duração local e limite monetário independem da interface. Parada espontânea comunica end_reason (duration_limit,cost_limit,disconnected,communication_lost,fault). Comandos vencidos provocam reconciliação, não confirmação inventada.
