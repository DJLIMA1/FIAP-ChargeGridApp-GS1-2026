"""Previsão de um posto: junta série, baseline, modelo, backtest, janelas e sugestões.

Mesmo cálculo na API (``/v1/owner/forecast`` e ``/v1/stations/{id}/best-times``), na
conta demo do app e no mock do painel. Entradas já autorizadas; saída serializável.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from .. import pricing
from . import evaluate, insights
from .best_times import best_times, expected_multiplier
from .calendar import TZ_NAME, iso
from .evaluate import HORIZON, backtest, band, choose, kwh_per_busy_hour, origin_rows
from .gbm import predict_occupancy
from .series import StationSeries

FALLBACK_EFFICIENCY = 0.85
SYNTHETIC_NOTE = "Inclui histórico sintético (rotulado), usado para demonstração."


def default_model():
    try:
        from .model_v1 import MODEL
    except ImportError:  # pragma: no cover - artefato ausente
        return None
    return MODEL


def extend(series: StationSeries, hours: int) -> StationSeries:
    """Série com ``hours`` horas futuras vazias (para indexar as horas previstas)."""
    return StationSeries(start=series.start, occ=series.occ + [None] * hours, kwh=series.kwh + [None] * hours,
                         connectors=series.connectors,
                         synthetic=(series.synthetic or [False] * len(series.occ)) + [False] * hours)


def price_ratios(rules, connectors: list[dict], series: StationSeries) -> list[float]:
    """Razão tarifa do horário / tarifa base (média dos conectores) em cada hora da série.

    Usa as regras atuais também para o passado (aproximação declarada).
    """
    rules = pricing.stored_rules(rules)
    if not connectors or not (rules.get("schedule") or {}).get("intervals"):
        return [1.0] * len(series.occ)
    ratios = []
    for index in range(len(series.occ)):
        interval = pricing.active_interval(rules, series.at(index))
        values = []
        for connector in connectors:
            base = Decimal(str(connector["price_per_kwh"]))
            if base > 0:
                values.append(float(pricing.base_now(interval, connector["id"], base) / base))
        ratios.append(sum(values) / len(values) if values else 1.0)
    return ratios


def _metrics_out(result: dict) -> dict:
    return {key: value for key, value in result.items() if key != "n"} if result else None


def _model_card(model: dict | None) -> dict | None:
    if not model:
        return None
    test = model.get("offline_test") or {}
    return {
        "version": model.get("version"), "trained_on": model.get("trained_on"), "library": model.get("library"),
        "selected": model.get("selected"),
        "offline_test": {
            "period": "dias 175–209 do histórico sintético (nunca usados no ajuste)",
            "baseline": _metrics_out(test.get("baseline")), "gbm": _metrics_out(test.get("gbm")),
            "daily": test.get("daily"),
            "unseen_stations": {k: _metrics_out(v) for k, v in (test.get("unseen_stations") or {}).items()},
        },
    }


def forecast_hours(series: StationSeries, as_of: int, model, method: str, ratios, horizon: int = HORIZON):
    """``[(início local, ocupação usada, baseline, modelo)]`` das próximas ``horizon`` horas."""
    result = []
    for t, x, base, _ in origin_rows(series, as_of, horizon, ratios):
        guess = predict_occupancy(model, x, base) if model else None
        chosen = guess if method == "gbm" and guess is not None else base
        result.append((series.at(t), chosen, base, guess))
    return result


def station_forecast(series: StationSeries, now_local: datetime, *, rules, connectors: list[dict],
                     model=None, horizon: int = HORIZON, use_default_model: bool = True) -> dict:
    """Previsão completa do posto (contrato de ``GET /v1/owner/forecast``).

    ``series`` termina na última hora fechada (``now_local`` truncado); ``connectors``:
    ``[{id, public_code, price_per_kwh, power_kw}]`` publicados.
    """
    if model is None and use_default_model:
        model = default_model()
    as_of = len(series.occ)
    coverage = series.coverage()
    series = extend(series, horizon)
    rules = pricing.stored_rules(rules)
    ratios = price_ratios(rules, connectors, series)
    notes = []
    if coverage["days_synthetic"]:
        notes.append(SYNTHETIC_NOTE)
    payload = {
        "timezone": TZ_NAME,
        "as_of": iso(series.at(as_of)),
        "horizon_hours": horizon,
        "connectors": series.connectors,
        "model": _model_card(model),
        "coverage": coverage,
        "includes_synthetic": bool(coverage["days_synthetic"]),
        "notes": notes,
    }
    if series.first >= as_of:
        notes.append("Ainda não há histórico de recargas neste posto para prever a ocupação.")
        return {**payload, "status": "no_history", "method": "baseline", "method_reason": notes[-1],
                "accuracy": None, "hours": [], "peaks": [], "idle": [], "suggestions": []}
    result = backtest(series, as_of, model, ratios)
    method, reason = choose(result, model, (model or {}).get("selected"))
    rows = forecast_hours(series, as_of, model, method, ratios, horizon)
    factor = kwh_per_busy_hour(series, as_of)
    if factor is None:
        powers = [float(c.get("power_kw") or 0) for c in connectors if c.get("power_kw")]
        factor = (sum(powers) / len(powers) * FALLBACK_EFFICIENCY) if powers else 0.0
    hours = []
    for offset, (when, occ, base, _) in enumerate(rows):
        limits = band(result["residuals"], method, offset)
        multiplier = expected_multiplier(rules, series.connectors, occ, when)
        hours.append({
            "start": iso(when),
            "occupancy_percent": f"{100 * occ:.1f}",
            "baseline_percent": f"{100 * base:.1f}",
            "low_percent": f"{100 * max(0.0, min(1.0, occ + limits[0])):.1f}" if limits else None,
            "high_percent": f"{100 * max(0.0, min(1.0, occ + limits[1])):.1f}" if limits else None,
            # O modelo estima a mediana da hora (ótima para o MAE), que subestima somas;
            # a energia usa a média do mesmo dia e hora, que soma corretamente no dia.
            "energy_kwh": f"{base * series.connectors * factor:.3f}",
            "expected_multiplier": str(multiplier),
            "full": occ >= insights.FULL,
        })
    peaks, idle = insights.peaks_and_idle([(when, occ) for when, occ, _, _ in rows], now_local.date())
    enough = result["origins"] >= evaluate.MIN_ORIGINS
    accuracy = {
        "window_days": evaluate.BACKTEST_DAYS, "origins": result["origins"],
        "status": "ok" if enough else "insufficient_history",
        "baseline": _metrics_out(result["baseline"]), "gbm": _metrics_out(result["gbm"]),
        "daily": result.get("daily") or {},
    }
    if not enough:
        notes.append("Menos de 7 dias medidos: o acerto ainda não é confiável e a faixa não é calibrada.")
    advice = insights.suggestions(rules, connectors, peaks, idle) if enough or coverage["days_synthetic"] else []
    return {
        **payload,
        "status": "ok",
        "method": method,
        "method_reason": reason,
        "accuracy": accuracy,
        "band": "p10–p90 do erro no backtest" if any(h["low_percent"] for h in hours) else "não calibrada",
        "energy_basis": "média do mesmo dia e hora × kWh por hora ocupada no histórico do posto",
        "hours": hours,
        "peaks": insights.public(peaks),
        "idle": insights.public(idle),
        "suggestions": advice,
    }


def station_best_times(series: StationSeries, now_local: datetime, *, rules, connectors: list[dict],
                       now_price: Decimal | None, model=None, hours: int = 12) -> dict:
    """Melhor horário das próximas ``hours`` horas (contrato de ``/v1/stations/{id}/best-times``)."""
    if model is None:
        model = default_model()
    as_of = len(series.occ)
    synthetic = bool(series.coverage()["days_synthetic"])
    series = extend(series, hours)
    rules = pricing.stored_rules(rules)
    ratios = price_ratios(rules, connectors, series)
    if series.first >= as_of:
        rows = [(series.at(as_of + i), 0.0) for i in range(hours)]
        method = "no_history"
    else:
        result = backtest(series, as_of, model, ratios)
        method, _ = choose(result, model, (model or {}).get("selected"))
        rows = [(when, occ) for when, occ, _, _ in forecast_hours(series, as_of, model, method, ratios, hours)]
    payload = best_times(rules, connectors, rows, now_price)
    return {**payload, "method": method, "generated_for": iso(series.at(as_of)), "timezone": TZ_NAME,
            "includes_synthetic": synthetic}


def occupancy_history(series: StationSeries, weeks: int = 4) -> dict:
    """Médias por dia da semana × hora (ocupação % e kWh) nas últimas ``weeks`` semanas."""
    end = len(series.occ)
    start = max(series.first, end - weeks * 168)
    occ = [[0.0] * 24 for _ in range(7)]
    kwh = [[0.0] * 24 for _ in range(7)]
    samples = [[0] * 24 for _ in range(7)]
    for index in range(start, end):
        value = series.occ[index]
        if value is None:
            continue
        when = series.at(index)
        day, hour = when.weekday(), when.hour
        occ[day][hour] += value
        kwh[day][hour] += series.kwh[index] or 0.0
        samples[day][hour] += 1
    cells = [[f"{100 * occ[d][h] / samples[d][h]:.1f}" if samples[d][h] else None for h in range(24)] for d in range(7)]
    energy = [[f"{kwh[d][h] / samples[d][h]:.3f}" if samples[d][h] else None for h in range(24)] for d in range(7)]
    peak = max((float(value) for row in cells for value in row if value is not None), default=0.0)
    coverage = series.coverage()
    return {
        "timezone": TZ_NAME, "weeks": weeks, "days": ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"],
        "hours": list(range(24)), "occupancy_percent": cells, "energy_kwh": energy, "samples": samples,
        "max_occupancy_percent": f"{peak:.1f}", "from": iso(series.at(start)) if start < end else None,
        "to": iso(series.at(end)), "coverage": coverage, "includes_synthetic": bool(coverage["days_synthetic"]),
        "notes": [SYNTHETIC_NOTE] if coverage["days_synthetic"] else [],
    }

