"""Métricas, backtest por posto e a regra que decide entre modelo e baseline.

* **MAE** da ocupação em pontos percentuais.
* **WAPE** = Σ|real − previsto| / Σ real (sem MAPE: horas vazias dariam divisão por zero).
* **Acerto** = 100 % − WAPE (limitado a 0).
* O modelo só é usado quando o seu WAPE é no máximo 95 % do WAPE do baseline nos mesmos
  pontos (``MARGIN``), no teste offline **e** no backtest do próprio posto.
"""

from __future__ import annotations

from .baseline import baseline
from .features import OriginContext, has_history, vector
from .gbm import predict_occupancy

HORIZON = 36
MARGIN = 0.95
BACKTEST_DAYS = 14
MIN_ORIGINS = 7
BUCKETS = ((0, 6), (6, 12), (12, 24), (24, 36))
MIN_BAND_RESIDUALS = 30


def origin_rows(series, origin: int, horizon: int = HORIZON, ratios=None, limit: int | None = None):
    """``(t, x, baseline, real)`` para cada hora prevista a partir de ``origin``.

    ``limit``: só horas ``< limit`` (backtest: até a última hora fechada). ``real`` é
    ``None`` quando a hora ainda não aconteceu ou não tem dado.
    """
    ctx = OriginContext(series, origin)
    stop = origin + horizon if limit is None else min(origin + horizon, limit)
    rows = []
    for t in range(origin, stop):
        base = baseline(series.occ, t, origin)
        base = 0.0 if base is None else base
        ratio = ratios[t] if ratios is not None and t < len(ratios) else 1.0
        actual = series.occ[t] if t < len(series.occ) else None
        rows.append((t, vector(series, t, ctx, base, ratio), base, actual))
    return rows


def metrics(actual, predicted) -> dict:
    """``{mae_pp, wape, accuracy_percent, n}`` (``None`` quando não há base de cálculo)."""
    pairs = [(a, p) for a, p in zip(actual, predicted, strict=True) if a is not None and p is not None]
    if not pairs:
        return {"mae_pp": None, "wape": None, "accuracy_percent": None, "n": 0}
    error = sum(abs(a - p) for a, p in pairs)
    total = sum(a for a, _ in pairs)
    wape = error / total if total > 0 else None
    return {
        "mae_pp": round(100 * error / len(pairs), 2),
        "wape": round(wape, 4) if wape is not None else None,
        "accuracy_percent": round(max(0.0, 100 * (1 - wape)), 1) if wape is not None else None,
        "n": len(pairs),
    }


def model_wins(model_metrics: dict, base_metrics: dict, margin: float = MARGIN) -> bool:
    """O modelo vence quando erra pelo menos ``1 − margin`` a menos (WAPE; sem WAPE, MAE)."""
    key = "wape" if model_metrics.get("wape") is not None and base_metrics.get("wape") is not None else "mae_pp"
    if model_metrics.get(key) is None or base_metrics.get(key) is None:
        return False
    return model_metrics[key] <= base_metrics[key] * margin


def backtest(series, as_of: int, model: dict | None, ratios=None, days: int = BACKTEST_DAYS,
             horizon: int = HORIZON) -> dict:
    """Previsões refeitas em cada meia-noite dos últimos ``days`` dias antes de ``as_of``.

    Cada origem usa só horas anteriores a ela; o modelo nunca viu dados do posto (foi
    treinado no histórico sintético), então o erro é medido fora da amostra.
    """
    first_midnight = as_of - series.at(as_of).hour
    origins = [first_midnight - 24 * k for k in range(1, days + 1)]
    origins = [o for o in origins if o >= 0 and has_history(series, o)]
    actual, base_pred, model_pred, residuals, daily = [], [], [], {}, {}
    for origin in origins:
        rows = origin_rows(series, origin, horizon, ratios, limit=as_of)
        guesses = {"baseline": [], "gbm": []}
        for t, x, base, real in rows:
            guess = predict_occupancy(model, x, base) if model else None
            guesses["baseline"].append(base)
            guesses["gbm"].append(guess)
            if real is None:
                continue
            actual.append(real)
            base_pred.append(base)
            model_pred.append(guess)
            residuals.setdefault(t - origin, []).append((real - base, None if guess is None else real - guess))
        score_day(daily, series, origin, rows, guesses if model else {"baseline": guesses["baseline"]})
    base_metrics = metrics(actual, base_pred)
    model_metrics = metrics(actual, model_pred) if model else None
    return {"origins": len(origins), "baseline": base_metrics, "gbm": model_metrics, "residuals": residuals,
            "daily": {method: score.result() for method, score in daily.items()}}


def choose(result: dict, model: dict | None, offline_selected: str | None) -> tuple[str, str]:
    """``(método, motivo)`` para este posto."""
    if result["origins"] < MIN_ORIGINS:
        return "baseline", "Histórico insuficiente para medir o acerto do modelo neste posto; usando a média."
    if model is None or offline_selected != "gbm":
        return "baseline", "O modelo não venceu a média na validação offline; usando a média."
    if model_wins(result["gbm"], result["baseline"]):
        return "gbm", "O modelo errou menos que a média nos últimos dias deste posto."
    return "baseline", "A média errou menos que o modelo nos últimos dias deste posto."


def band(residuals: dict, method: str, offset: int) -> tuple[float, float] | None:
    """Faixa p10–p90 do erro por horizonte, a partir do backtest (``None`` = não calibrada)."""
    low, high = next(((a, b) for a, b in BUCKETS if a <= offset < b), BUCKETS[-1])
    pick = 1 if method == "gbm" else 0
    values = sorted(item[pick] for h in range(low, high) for item in residuals.get(h, ()) if item[pick] is not None)
    if len(values) < MIN_BAND_RESIDUALS:
        return None
    return values[int(0.1 * (len(values) - 1))], values[int(0.9 * (len(values) - 1))]


def kwh_per_busy_hour(series, origin: int, days: int = 28) -> float | None:
    """kWh entregues por hora de conector ocupada, no histórico antes de ``origin``."""
    busy = energy = 0.0
    for j in range(max(0, origin - 24 * days), origin):
        if series.occ[j] is None:
            continue
        busy += series.occ[j] * series.connectors
        energy += series.kwh[j] or 0.0
    return energy / busy if busy >= 2 else None


PEAK_WIDTH = 3
PEAK_MIN = 0.25


def busiest_window(values, width: int = PEAK_WIDTH) -> int:
    """Início da janela de ``width`` horas com maior ocupação somada (empate: a primeira)."""
    best, best_sum = 0, None
    for start in range(0, max(1, len(values) - width + 1)):
        total = sum(values[start:start + width])
        if best_sum is None or total > best_sum + 1e-12:
            best, best_sum = start, total
    return best


class DailyScore:
    """Acumula, por dia previsto à meia-noite, o acerto do pico e o erro da energia do dia."""

    def __init__(self):
        self.peak_days = self.peak_hits = 0
        self.energy_error = self.energy_total = 0.0

    def add(self, actual_occ, predicted_occ, actual_kwh: float, predicted_kwh: float | None):
        if len(actual_occ) == 24 and max(actual_occ) >= PEAK_MIN:
            self.peak_days += 1
            real, guess = busiest_window(actual_occ), busiest_window(predicted_occ)
            self.peak_hits += abs(real - guess) < PEAK_WIDTH  # janelas de 3 h se sobrepõem
        if predicted_kwh is not None and len(actual_occ) == 24:
            self.energy_error += abs(actual_kwh - predicted_kwh)
            self.energy_total += actual_kwh

    def result(self) -> dict:
        wape = self.energy_error / self.energy_total if self.energy_total > 0 else None
        return {
            "peak_days": self.peak_days,
            "peak_hit_percent": round(100 * self.peak_hits / self.peak_days, 1) if self.peak_days else None,
            "energy_day_wape": round(wape, 4) if wape is not None else None,
            "energy_day_accuracy_percent": round(max(0.0, 100 * (1 - wape)), 1) if wape is not None else None,
        }


def score_day(scores: dict, series, origin: int, rows, guesses: dict):
    """Soma um dia (origem à meia-noite) em ``scores[método]`` (``DailyScore``)."""
    day = [(t, real) for t, _, _, real in rows if t < origin + 24 and real is not None]
    if len(day) < 24:
        return
    factor = kwh_per_busy_hour(series, origin)
    actual_occ = [real for _, real in day]
    actual_kwh = sum(series.kwh[t] or 0.0 for t, _ in day)
    for method, values in guesses.items():
        predicted = values[:24]
        if any(value is None for value in predicted):
            continue
        kwh = sum(predicted) * series.connectors * factor if factor is not None else None
        scores.setdefault(method, DailyScore()).add(actual_occ, predicted, actual_kwh, kwh)
