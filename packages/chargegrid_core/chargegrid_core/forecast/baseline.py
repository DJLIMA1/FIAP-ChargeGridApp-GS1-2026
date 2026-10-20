"""Baseline: média do mesmo dia da semana e hora, suavizada.

``b(t) = (n·m_dh + K·m_h) / (n + K)``

* ``m_dh``: média ponderada da mesma hora nas últimas 4 semanas (pesos 0,4 / 0,3 /
  0,2 / 0,1, a mais recente pesa mais), só com semanas que têm histórico;
* ``m_h``: média da mesma hora nos 7 dias mais recentes disponíveis;
* ``n``: semanas encontradas; ``K = 2`` puxa para ``m_h`` quando há poucas semanas.

Só usa horas anteriores à origem da previsão (``origin``), sem olhar o futuro.
"""

from __future__ import annotations

WEEK = 168
DAY = 24
WEIGHTS = (0.4, 0.3, 0.2, 0.1)
SHRINK = 2.0
HOUR_DAYS = 7


def week_values(occ, t: int, origin: int) -> list[tuple[float, float]]:
    values = []
    for k, weight in enumerate(WEIGHTS, start=1):
        j = t - WEEK * k
        if 0 <= j < origin and occ[j] is not None:
            values.append((weight, occ[j]))
    return values


def hour_mean(occ, t: int, origin: int, days: int = HOUR_DAYS) -> float | None:
    """Média da mesma hora nos ``days`` dias mais recentes antes de ``origin``."""
    first = t - DAY * ((t - origin) // DAY + 1)  # mesma hora, primeiro dia antes da origem
    total = count = 0
    j = first
    while j >= 0 and count < days and first - j < DAY * days * 2:
        if occ[j] is not None:
            total += occ[j]
            count += 1
        j -= DAY
    return total / count if count else None


def baseline(occ, t: int, origin: int) -> float | None:
    """Ocupação esperada na hora ``t`` com dados até ``origin`` (exclusivo); ``None`` sem histórico."""
    weeks = week_values(occ, t, origin)
    mean_h = hour_mean(occ, t, origin)
    if weeks:
        mean_dh = sum(w * v for w, v in weeks) / sum(w for w, _ in weeks)
        if mean_h is None:
            return mean_dh
        n = len(weeks)
        return (n * mean_dh + SHRINK * mean_h) / (n + SHRINK)
    return mean_h
