# Adaptador GoodWe HCA G2 (simulado)

O adaptador traduz a potência que o ChargeGrid decide para cada ponto em registradores Modbus do carregador AC GoodWe HCA G2. **Ele não está ligado a nenhum equipamento real.** O transporte é simulado e rotulado como tal, e o mapa de registradores não foi validado em hardware. A frase certa para o pitch é: "adaptador compatível com o mapa Modbus V1.0.15 do HCA G2, sem validação em hardware". Não dizer "OCPP" nem "API oficial".

## Onde mora e como é escolhido

| Peça | Arquivo | Papel |
| --- | --- | --- |
| Contrato | `packages/chargegrid_core/chargegrid_core/chargers/base.py` | `ChargerDriver`, `Transport`, `apply_power()` (escreve e só confirma pela releitura) |
| Mapa e tradução | `packages/chargegrid_core/chargegrid_core/chargers/goodwe_hca_g2.py` | Puro, sem rede: W → registradores, releitura → W aplicado, proveniência por registrador |
| Transporte simulado | `tools/edge/modbus_sim.py` | Banco de holding registers em memória, recusa valores fora da faixa, falhas injetáveis; o transporte real recusa abrir conexão |
| Borda | `tools/device_simulator.py --charger goodwe-hca-g2 --hca-model GW7K-HCA-20` | Recebe `SET_POWER` da API, escreve os registradores, relê e só então manda o ACK `applied` |

A API serverless não alcança Modbus numa rede local, então a decisão sai da API em W (protocolo neutro, `SET_POWER`) e a tradução acontece na borda (simulador hoje; um gateway local no futuro). A escolha é da borda: o equipamento declara no sync `charger: {model: "goodwe_hca_g2", variant, transport: "simulated", min_power_w, max_power_w, step_w, phases}`. A API guarda em `devices.charger`, usa o piso e o máximo na divisão (4,2 kW num modelo trifásico) e mostra no painel do vendedor (`GET /v1/stations/{id}/power` → `points[].charger`). O vendedor não troca o modelo: a verdade vem do equipamento.

## Registradores usados

| Endereço | Nome | Uso | Escala | Grava flash |
| --- | --- | --- | --- | --- |
| 10029 | Maximum Charging Power | setpoint de potência do ponto | U16, 0,1 kW; 14–70 (7 kW mono), 42–110 (11 kW tri), 42–220 (22 kW tri) | sim: só escreve quando o valor muda |
| 10060 | Liga/desliga recarga | pausa abaixo do mínimo (1) e retoma (2) | 1 = desliga, 2 = liga | não |
| 10032 | Modo de carga avançado | escrito uma vez: 0 = rápido (sem FV/bateria) | enum | sim |
| 10015, 10017, 10058, 10059 | potência medida, status, modelo, fases | leitura | 0,1 kW / enum | — |

Não existe setpoint de corrente em ampères: o único controle de potência por ponto é o 10029. A corrente por fase mostrada em tela é aproximada (`P / (230 V × fases)`) e marcada como não verificada.

**Nunca escritos:** 10024 (manter potência mínima), 10025 (gestão dinâmica de carga do próprio carregador) e 10026 (corrente do disjuntor de entrada da casa). O 10026 é um limite do local, usado pela gestão dinâmica do carregador; não é teto por ponto. Um repositório de outra equipe o trata como teto do ponto, e isso diverge do documento. O teste `test_never_writes_site_or_dlm_registers` garante isso.

## Fontes e grau de confiança

| Informação | Fonte | Confiança |
| --- | --- | --- |
| Endereços, tipos, escalas e faixas | Documento do fabricante "AC EV Charger Gen2 Modbus Protocol" V1.0.15 (12/09/2025), **não publicado pela GoodWe**, nas transcrições: [STIG4 hca-g2-modbus-map.md e drivers/modbus_map.py](https://github.com/STIG4-Solutions/chargegrid-challenge/blob/de90b86f2a87d657b7fbaa33c4299680b48865a4/docs/references/goodwe/hca-g2-modbus-map.md), [Home Assistant sems_wallbox docs/modbus-protocol.md](https://github.com/prezervos/goodwe-wallbox-sems-home-assistant/blob/beaa176660d0e8ebfc3f6d0131c8d2ec8e26ee3c/docs/modbus-protocol.md), [evcc charger/goodwe.go](https://github.com/evcc-io/evcc/blob/106eda351b8c294020a876d309e0ffb7117ddda1/charger/goodwe.go) ("not vendor-verified"), [DaviZuolo07 backend/demanda.py](https://github.com/DaviZuolo07/GoodWe_MVP/blob/5ed7f652e2240ae8eb5ecede74d45be463873df5/backend/demanda.py) | `vendor_doc_unpublished` |
| Unit ID 247, FC03 para ler, FC06 para escrever, sem deslocamento de endereço | evcc e Home Assistant (não estão no documento) | `community_observed`, configurável |
| Conversão de potência em corrente pelo carregador | não especificada | `unverified` |
| Modelos, fases, corrente nominal e protocolo "Modbus TCP" | [Datasheet oficial HCA G2](https://en.goodwe.com/Ftp/EN/Downloads/Datasheet/GW_HCA-G2_Datasheet-EN.pdf) | oficial |
| Mínimo de 6 A por fase (1,4 kW mono, 4,2 kW tri) | Manual do usuário G2, seção 3.5 (transcrição PT-BR da STIG4) | manual do fabricante |

O HCA G2 não tem OCPP nem API SEMS+ para carregadores. Há relatos de comunidade sobre instabilidade da conexão Modbus TCP em equipamento real (abrir a conexão interromper a recarga); por isso o transporte real fica desabilitado (`ModbusTcpTransport` recusa abrir conexão) até termos hardware para validar.

## Como funciona um ajuste

1. A API decide 2,0 kW para o ponto e envia `SET_POWER {power_limit_w: 2000}`.
2. O adaptador calcula as escritas: `10029 ← 20` (só se mudou) e `10060 ← 2` (se estava pausado). Abaixo de 1,4 kW (ou 4,2 kW trifásico), escreve só `10060 ← 1` (pausa).
3. O transporte simulado aplica e registra `[SIMULADO] FC06 unit 247 reg 10029 <- 20`.
4. O adaptador relê 10029/10060. Só se a releitura bater o equipamento manda ACK `applied` com `applied_power_w: 2000`. Escrita perdida → ACK `failed` `readback_mismatch` e o limite anterior continua; a API reenvia uma vez e depois para o ponto.

## Como testar

```bash
cd packages/chargegrid_core && python -m pytest -q tests/test_hca_g2.py
python -m pytest -q tools/tests/test_modbus_sim.py          # na raiz do repositório
cd apps/api && pytest -q tests/test_live_power.py -k hca   # API + simulador HCA (Postgres local)
```

No terminal, `python tools/device_simulator.py --charger goodwe-hca-g2 --hca-model GW7K-HCA-20 --api https://…` com `CHARGEGRID_DEVICE_KEY` mostra cada escrita simulada. `--hca-fail-writes 2` perde as duas primeiras escritas para mostrar que não há ACK sem releitura.

## Demo com 1 painel físico e 2 pontos simulados

Posto da demo: limite contratado de 30 kW, loja em 12 kW (`PUT /v1/stations/{id}/power-site {"site_limit_kw": 30, "rebalance_enabled": true}` e `PUT …/building-load {"building_load_kw": 12}`). Os dois pontos simulados são equipamentos provisionados pela fábrica e vinculados ao mesmo posto; as chaves e as contas de motorista de demo ficam só no ambiente.

```bash
export CHARGEGRID_DEMO_DEVICE_KEYS="<chave ponto 2>,<chave ponto 3>"
export CHARGEGRID_DEMO_DRIVERS="motorista2@…:<senha>,motorista3@…:<senha>"
export CHARGEGRID_DEMO_OWNER="vendedor@…:<senha>"
python tools/demo_rebalance.py --api https://… --station <id do posto> --hca 2
```

Roteiro: o painel físico carrega sozinho a 7,2 kW → `entra 1` (as duas recargas ficam em 7,2 kW, cabem em 18 kW) → `entra 2` (o carro novo começa só na folga; o painel físico reduz para 6,0 kW depois do ACK; só então o carro novo sobe para 6,0 kW) → `loja 24` (os três caem para 2,0 kW; o painel mostra "Loja 24/30 kW · 3 carros") → `status` (soma em uso e a última decisão) → `sai 1` (os outros sobem para 3,0 kW). O carro 2 mostra as escritas `[SIMULADO]` nos registradores do HCA G2.

O painel físico só reduz sozinho com o firmware 0.5.0 (SET_POWER), previsto para a próxima onda. Com o firmware 0.4.0 ele continua funcionando, mas entra na divisão como carga fixa (`power_state: fixed`): os pontos simulados se ajustam em volta dele.
