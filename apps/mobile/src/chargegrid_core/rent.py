"""Aluguel mensal das centrais (a tela do posto), descontado do repasse do dono ("folha").

Funções puras e determinísticas (stdlib + ``Decimal``), usadas pela API (tela, CSV e PDF do
resultado) e pela conta demo do app. Uma única regra para todos.

Configuração (banco, nunca ambiente)
------------------------------------
``rates``: linhas ``{station_id, monthly_amount, effective_from}`` com vigência por data local
(São Paulo). ``station_id`` ``None`` = padrão da plataforma; uma linha de posto vale para todas
as centrais daquele posto e ``monthly_amount`` ``None`` numa linha de posto = "volta ao padrão".
Mudar o valor nunca reescreve dias anteriores à vigência.

Rateio
------
* Uma central conta num dia local se esteve vinculada em algum momento dele
  (``linked_at < fim do dia`` e ``unlinked_at`` vazio ou depois do início do dia).
* Valor do dia = valor mensal vigente naquele dia ÷ dias do mês.
* Cada dia pertence à janela que contém o início dele (janelas contíguas somam sem sobrar
  nem faltar); só conta dia já começado (o mês em curso acumula até hoje).
* Arredondamento ao centavo (meio para cima) uma vez por central, mês e valor mensal; os
  totais somam as linhas arredondadas. Mês fechado inteiro = exatamente o valor mensal.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable, Mapping
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .analytics import REPORT_TZ, csv_cell, decimal_text, parse_time

CENT = Decimal("0.01")
MAX_MONTHLY_RENT = Decimal("10000")
RENT_EXPORT_COLUMNS = (
    ("station_name", "Posto"),
    ("central", "Central (ponto)"),
    ("month", "Mês"),
    ("days", "Dias cobrados"),
    ("days_in_month", "Dias do mês"),
    ("monthly_amount", "Aluguel mensal (R$)"),
    ("amount", "Valor (R$)"),
)
METHODOLOGY = (
    "Aluguel das centrais: valor mensal por central (definido em contrato) rateado por dia de "
    "vínculo no horário de São Paulo — valor mensal ÷ dias do mês por dia em que a central esteve "
    "vinculada. É descontado do repasse (folha) e do resultado; a margem de contribuição por "
    "recarga não muda."
)


def clean_monthly_rent(value) -> Decimal:
    """Valor mensal por central (R$ 0 a R$ 10.000, 2 casas); ``ValueError`` em pt-BR."""
    try:
        number = None if isinstance(value, bool) else Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError, TypeError):
        number = None
    if number is None or not number.is_finite():
        raise ValueError("Informe o aluguel mensal com números, por exemplo 99,00.")
    if not Decimal(0) <= number <= MAX_MONTHLY_RENT:
        raise ValueError("O aluguel mensal vai de R$ 0,00 a R$ 10.000,00 por central.")
    return number.quantize(CENT, rounding=ROUND_HALF_UP)


def _day(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _day_start(day: date, tz) -> datetime:
    return datetime.combine(day, time(0), tzinfo=tz)


def days_in_month(day: date) -> int:
    return calendar.monthrange(day.year, day.month)[1]


def _amount(value) -> Decimal | None:
    return None if value is None else Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def rate_on(rates: Iterable[Mapping], station_id, day: date) -> Decimal | None:
    """Valor mensal vigente em ``day`` para as centrais do posto (``None`` = sem aluguel)."""
    station = str(station_id) if station_id is not None else None
    own, default = None, None
    for rate in rates:
        effective = _day(rate["effective_from"])
        if effective > day:
            continue
        target = str(rate["station_id"]) if rate.get("station_id") is not None else None
        if target is None:
            if default is None or effective >= default[0]:
                default = (effective, rate.get("monthly_amount"))
        elif target == station and (own is None or effective >= own[0]):
            own = (effective, rate.get("monthly_amount"))
    if own is not None and own[1] is not None:
        return _amount(own[1])
    return _amount(default[1]) if default is not None else None


def current_rate(rates: Iterable[Mapping], station_id, now: datetime, tz=REPORT_TZ) -> Decimal | None:
    return rate_on(list(rates), station_id, now.astimezone(tz).date())


def _days(start: datetime, end: datetime, tz) -> list[date]:
    """Dias locais cujo início está em ``[start, end)``."""
    if end <= start:
        return []
    day = start.astimezone(tz).date()
    if _day_start(day, tz) < start:
        day += timedelta(days=1)
    result = []
    while _day_start(day, tz) < end:
        result.append(day)
        day += timedelta(days=1)
    return result


def accrual(centrals: Iterable[Mapping], rates: Iterable[Mapping], start: datetime, end: datetime,
            now: datetime, tz=REPORT_TZ) -> dict:
    """Aluguel das centrais na janela ``[start, end)`` até ``now``.

    ``centrals``: ``{device_id, station_id, station_name, central, linked_at, unlinked_at}``.
    Devolve ``{total, centrals, lines, by_station}`` (``total`` ``None`` sem nenhuma linha:
    aluguel não configurado ou nenhuma central vinculada no período).
    """
    rates = list(rates)
    days = _days(start, min(end, now), tz)
    groups: dict[tuple, dict] = {}
    order: list[tuple] = []
    for central in centrals:
        linked = parse_time(central.get("linked_at"))
        unlinked = parse_time(central.get("unlinked_at"))
        if linked is None:
            continue
        for day in days:
            begin = _day_start(day, tz)
            finish = _day_start(day + timedelta(days=1), tz)
            if not (linked < finish and (unlinked is None or unlinked > begin)):
                continue
            monthly = rate_on(rates, central.get("station_id"), day)
            if monthly is None:
                continue
            key = (str(central.get("device_id")), f"{day.year:04d}-{day.month:02d}", monthly)
            group = groups.get(key)
            if group is None:
                group = groups[key] = {
                    "station_id": str(central.get("station_id")) if central.get("station_id") else None,
                    "station_name": central.get("station_name") or "",
                    "device_id": str(central.get("device_id")),
                    "central": central.get("central") or "",
                    "month": key[1],
                    "days": 0,
                    "days_in_month": days_in_month(day),
                    "monthly_amount": monthly,
                    "_exact": Decimal(0),
                }
                order.append(key)
            group["days"] += 1
            group["_exact"] += monthly / group["days_in_month"]
    lines = []
    for key in order:
        group = groups[key]
        exact = group.pop("_exact")
        group["amount"] = exact.quantize(CENT, rounding=ROUND_HALF_UP)
        lines.append(group)
    lines.sort(key=lambda line: (line["station_name"], line["central"], line["month"], line["device_id"]))
    by_station: dict[str | None, Decimal] = {}
    for line in lines:
        by_station[line["station_id"]] = by_station.get(line["station_id"], Decimal("0.00")) + line["amount"]
    return {
        "total": sum((line["amount"] for line in lines), Decimal("0.00")) if lines else None,
        "centrals": len({line["device_id"] for line in lines}),
        "lines": lines,
        "by_station": by_station,
    }


def rent_csv(lines: Iterable[Mapping]) -> str:
    """CSV das linhas do aluguel (uma por central, mês e valor), protegido contra fórmulas."""
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([label for _, label in RENT_EXPORT_COLUMNS])
    for line in lines:
        data = {**line, "monthly_amount": decimal_text(line["monthly_amount"]),
                "amount": decimal_text(line["amount"])}
        writer.writerow([csv_cell(data.get(key)) for key, _ in RENT_EXPORT_COLUMNS])
    return buffer.getvalue()
