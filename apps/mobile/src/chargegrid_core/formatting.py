"""Formatação pt-BR comum a app, dashboard e API (mensagens e relatórios).

Valores monetários e medidas são arredondados com Decimal (meio para cima), e
não com o arredondamento binário de ``float`` — ``f"{2.675:.2f}"`` resulta em
``2.67``. Strings decimais da API ("3.6000") são aceitas sem conversão a float.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

Number = float | int | str | Decimal


def _decimal(value: Number) -> Decimal | None:
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _ptbr(value: Decimal, digits: int) -> str:
    rounded = value.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    text = f"{abs(rounded):,.{digits}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def brl(value: Number | None, cents: bool = False) -> str:
    """Formata reais: brl(12.5) -> 'R$ 12,50'; brl(1250, cents=True) -> 'R$ 12,50'."""
    amount = None if value is None else _decimal(value)
    if amount is None:
        return "—"
    if cents:
        amount = amount / 100
    rounded = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if rounded < 0 else ""
    return f"{sign}R$ {_ptbr(rounded, 2)}"


def kwh(value: Number | None, digits: int = 1) -> str:
    amount = None if value is None else _decimal(value)
    if amount is None:
        return "—"
    sign = "-" if amount.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP) < 0 else ""
    return f"{sign}{_ptbr(amount, digits)} kWh"


def duration(minutes: Number | None) -> str:
    """duration(95) -> '1 h 35 min'; duration(40) -> '40 min'."""
    amount = None if minutes is None else _decimal(minutes)
    if amount is None:
        return "—"
    total = max(0, int(amount.quantize(Decimal(1), rounding=ROUND_HALF_UP)))
    hours, mins = divmod(total, 60)
    if not hours:
        return f"{mins} min"
    return f"{hours} h" if not mins else f"{hours} h {mins:02d} min"


def km(value: Number | None) -> str:
    amount = None if value is None else _decimal(value)
    if amount is None:
        return "—"
    # Decide the format after rounding: 9,96 km becomes "10 km", not "10,0 km".
    if amount.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP) < 10:
        return f"{_ptbr(amount, 1)} km"
    return f"{_ptbr(amount, 0)} km"


def percent(value: Number | None, digits: int = 1) -> str:
    """percent(42.25) -> '42,3%'; None -> '—' (sem dados)."""
    amount = None if value is None or value == "" else _decimal(value)
    if amount is None:
        return "—"
    sign = "-" if amount.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP) < 0 else ""
    return f"{sign}{_ptbr(amount, digits)}%"


def integer(value: Number | None) -> str:
    """integer(12345) -> '12.345'."""
    amount = None if value is None or value == "" else _decimal(value)
    if amount is None:
        return "—"
    sign = "-" if amount.quantize(Decimal(1), rounding=ROUND_HALF_UP) < 0 else ""
    return f"{sign}{_ptbr(amount, 0)}"
