"""Variáveis do modelo, todas calculáveis na origem da previsão (sem olhar o futuro)."""

from __future__ import annotations

from .baseline import WEEK, baseline, hour_mean, week_values
from .calendar import is_holiday

FEATURES = (
    "hour", "weekday", "weekend", "holiday", "baseline", "hour_mean_7d", "recent_3h", "recent_delta",
    "trend_24h", "horizon", "connectors", "weeks", "price_ratio", "last_day_same_hour", "level_7d",
)


class OriginContext:
    """Estatísticas da origem compartilhadas pelas 36 horas previstas."""

    __slots__ = ("origin", "recent_3h", "recent_delta", "trend_24h", "level_7d")

    def __init__(self, series, origin: int):
        occ = series.occ
        self.origin = origin
        recent = [(occ[j], baseline(occ, j, j)) for j in range(max(0, origin - 3), origin) if occ[j] is not None]
        self.recent_3h = sum(v for v, _ in recent) / len(recent) if recent else 0.0
        expected = [b for _, b in recent if b is not None]
        self.recent_delta = (self.recent_3h - sum(expected) / len(expected)) if expected else 0.0
        day = [(occ[j], baseline(occ, j, j)) for j in range(max(0, origin - 24), origin) if occ[j] is not None]
        actual = sum(v for v, _ in day)
        usual = sum(b for _, b in day if b is not None)
        self.trend_24h = (actual + 0.5) / (usual + 0.5) if day else 1.0
        week = [occ[j] for j in range(max(0, origin - 168), origin) if occ[j] is not None]
        self.level_7d = sum(week) / len(week) if week else 0.0


def vector(series, t: int, ctx: OriginContext, base: float, price_ratio: float = 1.0) -> list[float]:
    """Vetor na ordem de ``FEATURES`` para a hora ``t`` prevista na origem ``ctx.origin``."""
    when = series.at(t)
    origin = ctx.origin
    mean_h = hour_mean(series.occ, t, origin)
    return [
        float(when.hour), float(when.weekday()), 1.0 if when.weekday() >= 5 else 0.0,
        1.0 if is_holiday(when.date()) else 0.0,
        base, mean_h if mean_h is not None else base,
        ctx.recent_3h, ctx.recent_delta, ctx.trend_24h,
        float(t - origin + 1), float(series.connectors), float(len(week_values(series.occ, t, origin))),
        float(price_ratio), _last_day(series.occ, t, origin), ctx.level_7d,
    ]


def _last_day(occ, t: int, origin: int) -> float:
    """Mesma hora no dia mais recente antes da origem (``-1`` sem dado)."""
    j = t - 24 * ((t - origin) // 24 + 1)
    return occ[j] if j >= 0 and occ[j] is not None else -1.0


def has_history(series, origin: int, days: int = 7) -> bool:
    """A origem tem ao menos ``days`` dias de histórico antes dela?"""
    return series.first <= origin - 24 * days


__all__ = ["FEATURES", "OriginContext", "WEEK", "has_history", "vector"]
