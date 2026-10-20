"""Protocolo offline: dados sintéticos, divisão temporal e avaliação reprodutível.

Usado pelo script de treino (``tools/forecast/train_occupancy.py``) e pelo teste que
recalcula as métricas gravadas no artefato. Tudo em Python puro e determinístico.

Divisão (dias contados a partir de ``START``, hora local):

* dias 0–27: aquecimento (o baseline precisa de 4 semanas);
* origens às 0h, 6h, 12h e 18h;
* origens de **treino**: dias 28–139, só em postos de treino, com alvo antes do dia 140;
* origens de **validação**: dias 140–174 (escolha do número de árvores), alvo antes do 175;
* origens de **teste**: dias 175–209, usadas uma única vez, em todos os postos — inclusive
  os postos **não vistos** no treino (``UNSEEN``).
"""

from __future__ import annotations

from datetime import datetime

from . import synthetic
from .evaluate import HORIZON, metrics, model_wins, origin_rows, score_day
from .gbm import predict_occupancy

SEED = 20261020
START = datetime(2025, 1, 6)  # segunda-feira
DAYS = 210
STATIONS = 36
UNSEEN = tuple(range(28, 36))
TRAIN_DAYS = (28, 140)
VALID_DAYS = (140, 175)
TEST_DAYS = (175, 210)
ORIGIN_HOURS = (0, 6, 12, 18)
VERIFY_STATIONS = (0, 1, 30, 31)
VERIFY_ORIGIN_HOURS = (0,)


def station(index: int):
    profile = synthetic.station_profile(SEED, index)
    series, ratios = synthetic.station_series(profile, START, DAYS)
    return profile, series, ratios


def origins(days: tuple[int, int], hours=ORIGIN_HOURS, horizon: int = HORIZON) -> list[int]:
    """Origens (índices de hora) cujo alvo inteiro cabe antes do fim do trecho."""
    first, last = days
    result = []
    for day in range(first, last):
        for hour in hours:
            origin = day * 24 + hour
            if origin + horizon <= last * 24:
                result.append(origin)
    return result


def split_rows(series, ratios, days: tuple[int, int], hours=ORIGIN_HOURS):
    """Linhas ``(x, baseline, real, horizonte)`` de um trecho."""
    rows = []
    for origin in origins(days, hours):
        for t, x, base, actual in origin_rows(series, origin, HORIZON, ratios):
            if actual is not None:
                rows.append((x, base, actual, t - origin))
    return rows


def split_origins(series, ratios, days: tuple[int, int], hours=ORIGIN_HOURS):
    """``(origem, linhas)`` de um trecho (para métricas diárias)."""
    return [(origin, origin_rows(series, origin, HORIZON, ratios)) for origin in origins(days, hours)]


def evaluate(model: dict | None, stations=range(STATIONS), hours=ORIGIN_HOURS, days=TEST_DAYS) -> dict:
    """Métricas de ocupação (baseline × modelo) no trecho, com os mesmos pontos para os dois."""
    actual, base_pred, model_pred = [], [], []
    seen_actual, seen_base, seen_model = [], [], []
    unseen_actual, unseen_base, unseen_model = [], [], []
    daily = {}
    for index in stations:
        _, series, ratios = station(index)
        target = (unseen_actual, unseen_base, unseen_model) if index in UNSEEN else (seen_actual, seen_base, seen_model)
        for origin, rows in split_origins(series, ratios, days, hours):
            guesses = {"baseline": [], "gbm": []}
            for _, x, base, real in rows:
                guess = predict_occupancy(model, x, base) if model else None
                guesses["baseline"].append(base)
                guesses["gbm"].append(guess)
                if real is None:
                    continue
                for bucket, value in zip((actual, base_pred, model_pred), (real, base, guess), strict=True):
                    bucket.append(value)
                for bucket, value in zip(target, (real, base, guess), strict=True):
                    bucket.append(value)
            if series.at(origin).hour == 0:
                score_day(daily, series, origin, rows, guesses if model else {"baseline": guesses["baseline"]})
    report = {
        "baseline": metrics(actual, base_pred),
        "gbm": metrics(actual, model_pred) if model else None,
        "daily": {method: score.result() for method, score in daily.items()},
        "unseen_stations": {"baseline": metrics(unseen_actual, unseen_base),
                            "gbm": metrics(unseen_actual, unseen_model) if model else None},
        "seen_stations": {"baseline": metrics(seen_actual, seen_base),
                          "gbm": metrics(seen_actual, seen_model) if model else None},
    }
    report["selected"] = "gbm" if model and model_wins(report["gbm"], report["baseline"]) else "baseline"
    return report


def verification(model: dict) -> dict:
    """Subconjunto pequeno e reprodutível em CI (mesma regra, menos postos/origens)."""
    return evaluate(model, VERIFY_STATIONS, VERIFY_ORIGIN_HOURS)
