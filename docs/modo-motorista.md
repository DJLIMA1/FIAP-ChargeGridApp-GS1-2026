# Modo Motorista — planejamento de turno e recarga para motoristas de app

Motoristas de Uber/99 com carro elétrico perdem dinheiro de duas formas: parando para recarregar
no horário em que as corridas pagam mais e fazendo paradas extras que poderiam coincidir com o
almoço ou o jantar. O Modo Motorista monta o turno inteiro, decidindo **quando**, **onde** e
**quanto** recarregar para maximizar o lucro líquido estimado.

> Tudo é **estimativa**. Não existe API pública oficial de demanda da Uber/99; a curva de demanda é
> uma heurística e a disponibilidade futura dos postos é presumida.

## Onde está o código

| Camada | Arquivo |
|---|---|
| Motor puro (stdlib, determinístico) | `packages/chargegrid_core/chargegrid_core/driver/` (`vehicles.py`, `demand.py`, `models.py`, `planner.py`, `service.py`) — copiado para app e API por `tools/sync_core.py` |
| API | `apps/api/app/modules/driver/` (`routes.py`, `schemas.py`, `weather.py`); migração `e7d3c1a95b42_driver_mode.py` |
| App | `screens/driver.py`, `services/driver.py`, `services/driver_demo.py`, `preferences.py` (`DriverProfileStore`), cartão na Home |
| Testes | `packages/chargegrid_core/tests/test_driver.py`, `apps/api/tests/test_driver.py`, `apps/mobile/tests/test_driver_mode.py` |

## Entradas

- **Veículo**: presets aproximados (BYD Dolphin, Dolphin Mini, Seal, Yuan Plus, GWM Ora 03, Renault
  Kwid E-Tech, Volvo EX30, Chevrolet Bolt EV e Spark EUV, JAC E-JS1) com bateria útil, consumo
  urbano, potência AC/DC máxima e conectores aceitos. Valores ajustáveis; sempre rotulados como estimativa.
- **Estado atual**: SoC (%), localização opcional.
- **Preferências**: janela do turno (até 16 h, pode cruzar a meia-noite), refeições (almoço, jantar,
  lanche: horário, duração, flexibilidade ±min ou "flexível"), km/h rodando, ganho médio R$/h (ou R$/km),
  reserva mínima, alvo máximo de carga (ex.: 80% em carga rápida), carregador em casa e sua tarifa.
- **Postos** (do banco ou da demo): potência, tipo de conector, tarifa (inclusive por horário,
  `price_schedule`, quando existir), disponibilidade atual/fila e **comodidades** (restaurante, café,
  banheiro, shopping, conveniência — nome e distância opcionais).

## Modelo

1. **Curva de demanda** (`demand.py`): multiplicador por dia da semana × hora, interpolado em blocos de
   15 min. Dias úteis com picos ~6h30–9h30 e ~17h–20h e leve alta no almoço; sexta e sábado à noite
   fortes; madrugada fraca; domingo/feriado com padrão próprio. Sinais extras implementam a interface
   `DemandSignal` e só multiplicam a curva: clima por hora da Open-Meteo (chuva ↑ 20–35%,
   calor/frio extremo ↑ 5%), "está chovendo" informado pelo motorista, bônus opcional de aeroporto.
   A resposta informa a origem (`heuristica`, `heuristica+open-meteo`, `heuristica+informado`).
2. **Ganho e consumo por slot**: ganho = R$/h × multiplicador; km rodados crescem levemente com a demanda;
   energia = km × consumo.
3. **Curva de carga simplificada**: potência efetiva = mín(posto, carro AC/DC); DC constante até 80%
   e queda linear até 25% da potência em 100%; AC plano até 90%. Solução analítica (sem integração numérica).
4. **Parada** = deslocamento (linha reta × 1,3 a 24 km/h) + fila (ocupado agora: 15–30 min;
   futuro: 5 min) + carga, ocupando slots inteiros. Uma refeição num posto com restaurante/café/shopping
   (até 400 m a pé) vira **refeição + recarga**: o tempo de comer já seria perdido, então a carga não
   custa oportunidade; só o trajeto além de 10 min conta como tempo extra.
5. **Otimização** (`planner.py`): programação dinâmica sobre (slot, refeições feitas, SoC em faixas de 3%)
   com poda por dominância de Pareto e feixe de 12 estados por combinação de refeições. Ações: rodar,
   recarregar (1–4 slots em DC, 2–8 em AC, até o alvo máximo ou "só o necessário" para fechar o turno),
   refeição sozinha ou refeição + recarga. Os postos são pré-ranqueados por slot pelo custo efetivo por kWh
   (energia + ganho perdido no deslocamento) — 3 melhores para recarga e 2 melhores com comodidade
   para cada refeição.
   - Objetivo: **ganhos − custo de recarga − energia gasta da bateria × custo de repor em casa**
     (= lucro líquido estimado). Parar no pico perde o ganho alto daquele horário, então o pico é
     evitado naturalmente.
   - SoC abaixo da reserva é fortemente penalizado (restrição macia, para sempre devolver um plano com
     alertas); refeição fora da janela, idem. Desvio do horário preferido custa R$ 0,08/min.
   - Tempo típico: dezenas de ms para 30 postos e turno de 12 h (meta < 200 ms; teste em CI usa folga).
6. **Estratégia ingênua** para comparação: roda até ficar abaixo de max(reserva + 5%, 20%), vai ao posto
   mais próximo e carrega até o alvo; come no horário preferido sem acoplar recarga. As duas estratégias
   são simuladas pela mesma função, e o plano nunca é pior que a ingênua (salvaguarda explícita).
7. **Próxima parada agora**: replaneja do slot atual até o fim do turno (ou 4 h fora do turno) e devolve
   "pare agora", "siga rodando — próxima parada às HH:MM" ou "nenhuma recarga necessária", com as três
   melhores opções de parada imediata ranqueadas por custo efetivo por kWh (tarifa + ganho perdido).

## Saída

`blocks` (linha do tempo: rodando, recarga, refeição, refeição + recarga, pausa), `slots` (SoC e
demanda a cada 15 min), `stops` (posto, ponto, horário, kWh, custo, minutos de carga, desvio, fila,
ganho que deixa de fazer, comodidade usada e motivo em linguagem natural, por exemplo
"Jantar às 20h no Posto X (restaurante a 50 m) — carrega 3,2 kWh enquanto você come — evita parar no
pico de demanda das 16h45 às 19h45"), `peaks`, `alerts` (`needs_charge`, `no_station`,
`reserve_violated`, `battery_empty`, `peak`, `queue`, `rain`, `meal_not_coupled`, `no_charge_needed`),
`totals`, `baseline` e `comparison` (ganho a mais, economia em recarga, minutos de pico evitados).

## API (`/v1`, Bearer)

- `GET /driver/profile` → `{vehicle, preferences, saved, updated_at, presets}` (padrão se nada salvo).
- `PUT /driver/profile` `{vehicle:{preset?|usable_battery_kwh, consumption_kwh_per_100km, max_ac_kw,
  max_dc_kw, connectors, name}, preferences:{shift_start, shift_end, meals:[{kind, start, duration_minutes,
  flex_minutes, flexible, enabled}], km_per_hour, earnings_per_hour, earnings_per_km, reserve_percent,
  max_charge_percent, home_charging, home_price_per_kwh, city}}` — upsert; campos ausentes usam o padrão.
- `POST /driver/plan` `{soc_percent, lat?, lng?, radius_km=30, mode="auto"|"full_shift", vehicle?,
  preferences?, context:{rain?, holiday, airport}, live_signals=true}` → plano. `auto` planeja do agora até
  o fim do turno em andamento (ou o próximo turno); `full_shift` mostra o turno de hoje inteiro (ou o de
  amanhã). Usa até 40 postos ativos (mais próximos quando há localização) com disponibilidade real.
- `POST /driver/next-stop` mesmo corpo sem `mode` → `{status, recommendation, alternatives, alerts, demand}`.
- `PATCH /stations/{id}` (dono) aceita `amenities: [{kind, name?, distance_m?}]` (até 12); a descoberta
  (`GET /stations`) expõe `amenities`.

Open-Meteo: `https://api.open-meteo.com/v1/forecast` (gratuita, sem chave), timeout de 2 s, cache por
região (~11 km) de 30 min (5 min após falha), falha silenciosa para a heurística. Status em
`demand.signals`: `ok`, `indisponivel`, `sem_localizacao`, `desativado` (ou `demo`).

Migração `e7d3c1a95b42` (após `9c4a2b8e1170`): coluna `stations.amenities JSONB NOT NULL DEFAULT '[]'`
com checagem de array (≤ 12) e tabela `driver_profiles(user_id PK → profiles, vehicle, preferences,
updated_at)` com RLS e política para `chargegrid_api`.

## App e demonstração

Entrada pelo cartão **Modo motorista de app** na Home (rota `driver`). A tela permite escolher o carro,
informar a bateria, ajustar turno, ganhos e refeições, e tocar **Planejar meu turno** ou
**Próxima parada agora**. O resultado mostra lucro estimado vs. estratégia ingênua, alertas, linha do
tempo colorida com faixa de pico, gráfico de SoC com linha de reserva e cartões de parada com
"Ver posto" e "Reservar" (quando a parada é agora). Preferências ficam no aparelho
(`driver_profile.json`) e, logado, também na API.

No **modo demo** as rotas `/driver/*` rodam localmente com o mesmo motor. Ao abrir o Modo Motorista, a
demo acrescenta uma rede parceira fictícia (Shopping Eldorado com praça de alimentação, Cantina da Vila
com carregador, Posto Paulista 24h, Hub Rápido Marginal Tietê, Congonhas etc.), que passa a aparecer
também na busca de postos e pode ser reservada. Roteiro sugerido para a banca: modo "Turno completo",
local "Praça da Sé", bateria 45–65% → mostrar a refeição acoplada, a faixa de pico sem paradas e o
ganho sobre a estratégia ingênua; depois bateria 16% → "Próxima parada agora" → Reservar.

## Limitações honestas

- Demanda é **estimativa** por horário; não há dados oficiais nem ao vivo de aplicativos. O clima é o único
  sinal ao vivo e apenas ajusta a curva.
- Ganho/h é a média informada pelo motorista; tarifa dinâmica, corridas longas e deslocamento vazio não
  são modelados individualmente.
- Distâncias em linha reta (× 1,3) e velocidade urbana fixa; sem trânsito ou rota real.
- Disponibilidade e fila só são conhecidas para agora; para horários futuros usamos 5 min de espera.
- Curva de carga, consumo e presets de veículos são aproximações; temperatura da bateria e ar-condicionado
  não entram.
- A otimização usa faixas de SoC e poda: é próxima do ótimo, não garantidamente ótima — por isso o plano é
  sempre comparado (e nunca pior) que a estratégia ingênua.
- A edição de comodidades pelo dono existe na API (e na demo) e no dashboard web do proprietário
  (`apps/dashboard`, seção Postos e pontos → Comodidades); ainda não há formulário na tela de operador do app.
