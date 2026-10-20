# Acompanhamento e previsão de ocupação

Para o dono do posto: histórico de ocupação e de energia por dia da semana e hora, a previsão das próximas 36 horas ("amanhã 17h–19h deve lotar"), o acerto medido e sugestões que usam o preço dinâmico e a tarifa por horário que já existem. Para o motorista: o "melhor horário para carregar" de cada posto.

Código: `packages/chargegrid_core/chargegrid_core/forecast/` (núcleo, Python puro), `apps/api/app/modules/forecast/` (API), `apps/owner-web/src/pages/Forecast.tsx` (painel), `apps/mobile/src/chargegrid_app/ui/forecast.py` (app).

## Dados duráveis

A telemetria pode ser apagada depois de 7 dias (`tools/maintenance.py --apply`). Por isso o histórico por hora fica em `connector_hourly_stats` (migração `c5f0a7e3d912`), com uma linha para cada conector e hora UTC:

| Campo | Origem |
| --- | --- |
| `busy_seconds` | Sessões (`started_at`–`ended_at`), recortadas por hora. As sessões nunca são apagadas, então a ocupação sempre pode ser reconstruída. |
| `energy_wh` | Diferença entre leituras de telemetria da mesma sessão. Nunca somamos valores cumulativos. Uma regressão do contador (reboot) vira a nova referência e não gera energia negativa. Um trecho que cruza a virada da hora é dividido pelo tempo. Sem telemetria, a energia da sessão é espalhada no seu intervalo (`energy_basis = session_spread`). A soma por hora é sempre igual à energia final da sessão. |
| `origin` | `measured`, `simulated` (bancada) ou `synthetic` (demonstração rotulada). Na mesma hora, o dado real vence o sintético. |

O rollup roda no keepalive diário (`/internal/keepalive`, sem cron novo). Ele recalcula as horas fechadas desde a marca d'água menos 72 h, troca as linhas medidas/simuladas e avança `aggregate_watermarks.rolled_until`. Pode rodar de novo sem duplicar nada. A leitura junta a tabela com as horas posteriores à marca, calculadas na hora com o mesmo agregador, sem gravar. A manutenção só apaga telemetria anterior ao menor valor entre 7 dias e a marca menos 72 h. Se o rollup nunca rodou, nenhuma telemetria é apagada.

## Métodos

**Baseline (média suavizada).** `b(t) = (n·m_dh + 2·m_h) / (n + 2)`:

- `m_dh`: média da mesma hora nas 4 semanas anteriores, com pesos 0,4 / 0,3 / 0,2 / 0,1;
- `m_h`: média da mesma hora nos 7 dias mais recentes;
- `n`: número de semanas encontradas.

Usa só dados anteriores à origem da previsão.

**Modelo.** `GradientBoostingRegressor` do scikit-learn (perda absoluta, 400 árvores de profundidade 3, taxa 0,1, subamostra 0,8). Ele aprende o resíduo `ocupação − baseline` a partir destas variáveis:

- hora, dia da semana, fim de semana, feriado nacional;
- o baseline e a média da mesma hora nos últimos 7 dias;
- a ocupação das últimas 3 h e o desvio em relação ao esperado;
- a tendência das últimas 24 h;
- o horizonte da previsão e o número de conectores;
- quantas semanas há de histórico;
- a razão da tarifa do horário;
- a mesma hora do dia anterior e o nível dos últimos 7 dias.

O treino é **offline**, em `tools/forecast/train_occupancy.py`. O scikit-learn fica só em `tools/requirements-ml.txt` e nunca vai para a API. As árvores são exportadas para `chargegrid_core/forecast/model_v1.py` (Python puro, cerca de 117 KB) e avaliadas sem dependências na API, no app e na conta demo. Elas caem nas mesmas folhas que o scikit-learn: o artefato traz 24 previsões de referência, conferidas com tolerância de 1e-9.

**Energia prevista** = média do mesmo dia e hora × conectores × kWh por hora ocupada no histórico do posto. O modelo com perda absoluta estima a hora típica (a mediana), que é ótima para o erro por hora mas subestima a soma do dia. Por isso a energia usa a média.

## Avaliação e a regra de uso

Histórico sintético `syn-v1` (`chargegrid_core/forecast/synthetic.py`, determinístico pela semente), com 36 postos e 210 dias:

- **Arquétipos:** shopping, escritório, residencial e rodovia.
- **Fatores na taxa de chegadas:** tendência semanal, amadurecimento de posto novo, ruído diário, feriados, dias de chuva comuns a todos os postos, eventos locais e tarifa por horário com elasticidade −1,2.
- **Capacidade:** com o posto cheio, quem chega desiste.
- **Energia:** limitada a 60 kWh por sessão.

As sessões passam pelo mesmo agregador da produção. Tudo é hipótese do gerador e nada aqui é dado real.

Divisão no tempo (origens às 0h, 6h, 12h e 18h, horizonte de 36 h):

- treino: dias 28–139, só postos de treino, com alvo antes do dia 140;
- validação: dias 140–174, para escolher o número de árvores;
- **teste único:** dias 175–209 de todos os postos, incluindo 8 que o modelo nunca viu.

| Teste offline (174 960 horas) | Média | Modelo |
| --- | --- | --- |
| MAE da ocupação por hora | 16,08 p.p. | **14,98 p.p.** (−6,8%) |
| WAPE da ocupação por hora | 70,7% | **65,9%** |
| Só postos não vistos: MAE | 15,91 p.p. | **14,63 p.p.** |
| Acerto do horário de pico (janela de 3 h, ±1 h) | 56,6% | 57,2% |
| Acerto da energia do dia (100% − WAPE) | **75,4%** | 68,5% |

A ocupação de uma única hora num posto de 1 a 4 conectores é muito ruidosa (chegadas aleatórias), por isso o WAPE horário é alto para os dois métodos. Por isso a tela destaca o MAE em pontos percentuais, o acerto do pico e o acerto da energia do dia.

**Regra:** o modelo só é usado quando o seu WAPE fica em no máximo 95% do WAPE da média. Isso vale **no teste offline** (`selected = gbm` no artefato) **e** no backtest do próprio posto, que refaz a previsão em cada meia-noite dos últimos 14 dias usando só dados anteriores. Com menos de 7 origens válidas, fica a média. A resposta sempre traz `method`, o motivo e as métricas dos dois métodos. A faixa p10–p90 vem dos erros do backtest; com menos de 30 erros por faixa de horizonte, fica "não calibrada".

Reprodutibilidade: `python tools/forecast/train_occupancy.py --check`, que não precisa do scikit-learn, e o teste `test_model_metrics_are_reproducible_from_the_synthetic_protocol` recalculam as métricas do subconjunto de verificação e comparam com o artefato.

## Sugestões

Só usam instrumentos que já existem, e cada uma traz um `patch` aceito por `PUT /v1/stations/{id}/pricing`:

- **Pico previsto (≥ 80%):** ativar o preço dinâmico, aumentar o acréscimo máximo para 30%, ou criar um horário com tarifa base 10% maior.
- **Horário vazio (< 15% por 3 h ou mais entre 8h e 22h):** horário com tarifa base 10% menor, que o motorista vê como melhor horário.

Nenhuma sugestão é aplicada sem o dono revisar. Não estimamos receita, porque a elasticidade real é desconhecida.

## Melhor horário (motorista)

O preço esperado de cada hora é a tarifa base do horário do dono (`pricing.base_now`) × o multiplicador que `pricing.demand_status` daria com a ocupação prevista. O melhor horário é o menor preço; no empate, a menor ocupação. Com preço igual o dia todo, sugere o horário de menos movimento entre 6h e 23h. A resposta mostra a ocupação só como nível e sempre diz: "Estimativa. O preço é travado quando você reserva ou inicia a recarga."

## Histórico sintético para demonstração

`tools/seed_forecast_history.py --station <uuid>` faz uma prévia. Com `--apply`, grava linhas `synthetic` só nos agregados (não cria sessões, então receita e recargas continuam reais). `--purge --apply` remove só essas linhas. Painel e app mostram "Inclui histórico sintético" sempre que houver esse dado. A conta demo do app usa o histórico fictício de 30 dias, também rotulado como sintético.

## Limites

- O ganho do modelo foi medido em dados sintéticos. Nos dados reais vale o backtest do posto, e a média é usada quando vencer.
- As regras de tarifa atuais também são usadas para o passado (razão de preço histórica aproximada).
- A ocupação vem do tempo de sessão. A permanência depois da bateria cheia (overstay) entra quando existir o registro de desconexão.
