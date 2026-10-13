"""Formatação pt-BR comum a app, dashboard e API (mensagens e relatórios)."""

from __future__ import annotations


def brl(value: float | int | None, cents: bool = False) -> str:
    """Formata reais: brl(12.5) -> 'R$ 12,50'; brl(1250, cents=True) -> 'R$ 12,50'."""
    if value is None:
        return "—"
    amount = float(value) / 100 if cents else float(value)
    sign = "-" if amount < 0 else ""
    text = f"{abs(amount):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{sign}R$ {text}"


def kwh(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{float(value):.{digits}f} kWh".replace(".", ",")


def duration(minutes: float | int | None) -> str:
    """duration(95) -> '1 h 35 min'; duration(40) -> '40 min'."""
    if minutes is None:
        return "—"
    total = max(0, round(float(minutes)))
    hours, mins = divmod(total, 60)
    if not hours:
        return f"{mins} min"
    return f"{hours} h" if not mins else f"{hours} h {mins:02d} min"


def km(value: float | None) -> str:
    if value is None:
        return "—"
    return (f"{float(value):.1f} km" if value < 10 else f"{round(float(value))} km").replace(".", ",")


def percent(value: float | str | None, digits: int = 1) -> str:
    """percent(42.25) -> '42,3%'; None -> '—' (sem dados)."""
    if value is None or value == "":
        return "—"
    return f"{float(value):.{digits}f}%".replace(".", ",")


def integer(value: float | int | str | None) -> str:
    """integer(12345) -> '12.345'."""
    if value is None or value == "":
        return "—"
    return f"{round(float(value)):,}".replace(",", ".")
