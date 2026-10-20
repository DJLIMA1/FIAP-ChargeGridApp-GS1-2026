"""Acompanhamento e previsão de ocupação/energia por posto (ver docs/previsao-ocupacao.md).

* :mod:`aggregate` — agregados horários duráveis (sessões + telemetria);
* :mod:`series` / :mod:`baseline` / :mod:`features` — série local, média suavizada e variáveis;
* :mod:`gbm` + ``model_v1`` — gradient boosting exportado, avaliado em Python puro;
* :mod:`evaluate` — MAE/WAPE, backtest e a regra "o modelo só entra se vencer a média";
* :mod:`synthetic` / :mod:`offline` — histórico sintético rotulado e protocolo de teste;
* :mod:`engine` / :mod:`insights` / :mod:`best_times` — respostas para dono e motorista.
"""
