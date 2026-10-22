"""Períodos das ferramentas do assistente (fuso de São Paulo, mesmos limites do dashboard)."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from .. import analytics
from .schema import ToolArgumentError

PRESETS = ("today", "yesterday", "7d", "30d", "month", "last_month", "90d", "custom")
MAX_DAYS = 92

PERIOD_SCHEMA = {"type": "string", "enum": list(PRESETS),
                 "description": "Período: today, yesterday, 7d, 30d, month (este mês), last_month, 90d ou custom "
                                "(com from_date/to_date)."}
DATE_SCHEMA = {"type": "string", "minLength": 10, "maxLength": 10, "description": "Data AAAA-MM-DD (custom)."}


def _midnight(day):
    return datetime.combine(day, time(), analytics.REPORT_TZ)


def _fmt(moment: datetime) -> str:
    return moment.astimezone(analytics.REPORT_TZ).strftime("%d/%m/%Y")


def resolve_period(preset: str | None, now: datetime, *, from_date: str | None = None, to_date: str | None = None,
                   default: str = "30d", max_days: int = MAX_DAYS) -> dict:
    """``{start, end, label, preset}`` com ``start``/``end`` em UTC; ``end`` nunca passa de ``now``."""
    preset = preset or ("custom" if from_date and to_date else default)
    today = now.astimezone(analytics.REPORT_TZ).date()
    try:
        if preset in ("today", "7d", "30d"):
            start, end = analytics.period_bounds(preset, now)
        elif preset == "90d":
            start, end = _midnight(today - timedelta(days=89)), now
        elif preset == "yesterday":
            start, end = _midnight(today - timedelta(days=1)), _midnight(today)
        elif preset == "month":
            start, end = _midnight(today.replace(day=1)), now
        elif preset == "last_month":
            first = today.replace(day=1)
            start, end = _midnight((first - timedelta(days=1)).replace(day=1)), _midnight(first)
        elif preset == "custom":
            start, end = analytics.period_bounds("custom", now, start=from_date, end=to_date)
        else:
            raise ToolArgumentError("período desconhecido")
    except ValueError as exc:
        raise ToolArgumentError(str(exc)) from exc
    end = min(end, now)
    if end <= start:
        raise ToolArgumentError("o período ainda não começou")
    if end - start > timedelta(days=max_days, hours=1):
        raise ToolArgumentError(f"escolha um período de até {max_days} dias")
    labels = {"today": "hoje", "yesterday": "ontem", "7d": "últimos 7 dias", "30d": "últimos 30 dias",
              "90d": "últimos 90 dias", "month": f"este mês (desde {_fmt(start)})",
              "last_month": f"mês passado ({start.astimezone(analytics.REPORT_TZ):%m/%Y})"}
    label = labels.get(preset) or f"de {_fmt(start)} a {_fmt(end - timedelta(microseconds=1))}"
    return {"start": start, "end": end, "label": label, "preset": preset}


def previous_period(period: dict) -> dict:
    """Janela de mesma duração imediatamente anterior (para comparação)."""
    length = period["end"] - period["start"]
    start = period["start"] - length
    return {"start": start, "end": period["start"], "preset": "previous",
            "label": f"de {_fmt(start)} a {_fmt(period['start'] - timedelta(microseconds=1))}"}
