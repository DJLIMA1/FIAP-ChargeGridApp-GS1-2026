"""Fuso, feriados nacionais e rótulos de horário para a previsão.

São Paulo não tem horário de verão desde 2019: usamos o deslocamento fixo de −3 h,
o que deixa cada hora UTC corresponder a exatamente uma hora local.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

LOCAL_TZ = timezone(timedelta(hours=-3), "America/Sao_Paulo")
TZ_NAME = "America/Sao_Paulo"
WEEKDAYS_LONG = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo")
FIXED_HOLIDAYS = ((1, 1), (4, 21), (5, 1), (9, 7), (10, 12), (11, 2), (11, 15), (11, 20), (12, 25))


def to_local(moment: datetime) -> datetime:
    """Datetime com fuso → hora local *ingênua* (sem fuso)."""
    return moment.astimezone(LOCAL_TZ).replace(tzinfo=None)


def iso(local: datetime) -> str:
    """Hora local ingênua → ISO 8601 com o deslocamento de São Paulo (``-03:00``)."""
    return local.replace(tzinfo=LOCAL_TZ).isoformat()


def to_utc(local: datetime) -> datetime:
    return local.replace(tzinfo=LOCAL_TZ).astimezone(timezone.utc)


def _easter(year: int) -> date:
    """Domingo de Páscoa (algoritmo gregoriano anônimo)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    weekday = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * weekday) // 451
    month = (h + weekday - 7 * m + 114) // 31
    day = ((h + weekday - 7 * m + 114) % 31) + 1
    return date(year, month, day)


@lru_cache(maxsize=64)
def holidays(year: int) -> frozenset[date]:
    """Feriados nacionais (fixos) + Carnaval, Sexta-feira Santa e Corpus Christi."""
    easter = _easter(year)
    movable = {easter - timedelta(days=48), easter - timedelta(days=47), easter - timedelta(days=2),
               easter + timedelta(days=60)}
    return frozenset({date(year, month, day) for month, day in FIXED_HOLIDAYS} | movable)


def is_holiday(day: date) -> bool:
    return day in holidays(day.year)


def day_word(target: date, today: date) -> str:
    """"Hoje", "Amanhã" ou o dia da semana ("Quinta-feira")."""
    delta = (target - today).days
    if delta == 0:
        return "Hoje"
    if delta == 1:
        return "Amanhã"
    return WEEKDAYS_LONG[target.weekday()].capitalize()


def window_text(start: datetime, end: datetime) -> str:
    """``17h–19h`` (``end`` exclusivo; meia-noite vira 24h quando fecha o dia)."""
    last = end.hour if end.date() == start.date() or end.hour else 24
    return f"{start.hour}h–{last}h"
