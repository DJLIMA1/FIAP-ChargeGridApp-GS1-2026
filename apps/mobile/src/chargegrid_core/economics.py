"""Resultado do dono do posto: receita, comissão, custo da energia e margem por sessão.

Funções puras e determinísticas (stdlib + ``Decimal``), usadas pela API (tela, CSV e
PDF do painel), pela conta demo do app e pelo recibo. Uma única regra para todos.

Receita bruta não é lucro
-------------------------
Por sessão, em centavos (``ROUND_HALF_UP``):

* ``gross`` = kWh × preço travado (antes do cupom);
* ``revenue`` (valor cobrado pela energia) = ``cost_estimate`` ao centavo — o mesmo valor
  que o motorista vê no recibo; ``discount`` = ``gross`` − ``revenue``;
* ``gross`` se decompõe em ``list_value`` (kWh × tarifa base do conector) +
  ``schedule_effect`` (tarifa do horário) + ``demand_effect`` (preço dinâmico);
* ``overstay_revenue``: taxa de permanência (frente D), quando houver;
* ``revenue_total`` = ``revenue`` + ``overstay_revenue``; com pagamento confirmado
  (frente A), o valor líquido recebido do provedor (``net_amount``) substitui a estimativa;
* ``platform_fee`` = ``revenue_total`` × comissão da plataforma (padrão 25 %, sobre o valor
  cobrado depois do cupom, incluindo permanência). O cupom é do dono;
* ``provider_fee``: tarifa do provedor de pagamento (frente A); ``None`` sem pagamento;
* ``owner_net`` (repasse) = ``revenue_total`` − ``platform_fee`` − ``provider_fee``;
* ``energy_cost`` = kWh × custo do kWh informado pelo dono; ``None`` se não informado;
* ``margin`` (margem de contribuição estimada) = ``owner_net`` − ``energy_cost``.

Custo ausente nunca vira zero: a margem fica ``None`` e a cobertura é declarada. A margem
não inclui custos fixos (equipamento, aluguel, manutenção, tarifa de demanda em R$/kW).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .analytics import (
    PAYMENT_EXPORT_COLUMNS,
    csv_cell,
    decimal_text,
    parse_time,
    to_decimal,
)

SCHEMA_VERSION = 1
CENT = Decimal("0.01")
DEFAULT_PLATFORM_FEE_PERCENT = Decimal("25")
MAX_ENERGY_COST = Decimal(100)

MONEY_FIELDS = (
    "list_value", "schedule_effect", "demand_effect", "gross", "discount", "revenue", "overstay_revenue",
    "revenue_total", "platform_fee", "provider_fee", "owner_net", "energy_cost", "margin",
)
COST_BASIS_LABELS = {
    "snapshot": "custo travado no início da recarga",
    "current": "custo atual do posto (recarga anterior ao cadastro do custo)",
    "missing": "custo da energia não informado",
}
METHODOLOGY = (
    "Receita bruta não é lucro. Margem = receita cobrada − comissão da plataforma − tarifa do "
    "provedor de pagamento − custo estimado da energia.",
    "Comissão sobre o valor cobrado depois do cupom, incluindo a taxa de permanência. O cupom é "
    "um desconto do dono do posto.",
    "Custo da energia = kWh × custo do kWh informado pelo dono, travado no início de cada recarga. "
    "Não inclui custos fixos (equipamento, aluguel, manutenção) nem tarifa de demanda (R$/kW).",
    "Sessões encerradas (concluídas ou interrompidas) com energia positiva, atribuídas à data de "
    "término (horário de São Paulo). Valores estimados até a confirmação do pagamento.",
)
MARGIN_EXPORT_COLUMNS = (
    ("session_id", "ID da sessão"),
    ("ended_at", "Fim"),
    ("station_name", "Posto"),
    ("public_code", "Ponto"),
    ("energy_kwh", "Energia (kWh)"),
    ("source", "Origem da medição"),
    ("connector_base_per_kwh", "Tarifa base do conector (R$/kWh)"),
    ("base_per_kwh", "Tarifa base aplicada (R$/kWh)"),
    ("demand_multiplier", "Multiplicador de demanda"),
    ("price_per_kwh", "Preço travado (R$/kWh)"),
    ("coupon_code", "Cupom"),
    ("discount_percent", "Desconto (%)"),
    ("list_value", "Valor na tarifa base (R$)"),
    ("schedule_effect", "Efeito do horário (R$)"),
    ("demand_effect", "Efeito da demanda (R$)"),
    ("gross", "Receita bruta antes do cupom (R$)"),
    ("discount", "Desconto do cupom (R$)"),
    ("revenue", "Receita da energia (R$)"),
    ("overstay_revenue", "Taxa de permanência (R$)"),
    ("revenue_total", "Receita cobrada (R$)"),
    ("platform_fee_percent", "Comissão (%)"),
    ("platform_fee", "Comissão da plataforma (R$)"),
    ("provider_fee", "Tarifa do provedor (R$)"),
    ("owner_net", "Repasse ao dono (R$)"),
    ("energy_cost_per_kwh", "Custo do kWh (R$)"),
    ("cost_basis", "Base do custo"),
    ("energy_cost", "Custo estimado da energia (R$)"),
    ("margin", "Margem estimada (R$)"),
    ("margin_percent", "Margem (%)"),
    ("revenue_basis", "Base da receita"),
    *PAYMENT_EXPORT_COLUMNS,  # totem 0.8.0: canal e método (no fim; vazios em linhas sem a informação)
)


# ---------------------------------------------------------------- conversões

def _dec(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return number if number.is_finite() else None


def _value(amount: Decimal) -> Decimal:
    """Mesmo caminho do ``cost_estimate`` (4 casas) e depois o centavo: sem dupla divergência."""
    return amount.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP).quantize(CENT, rounding=ROUND_HALF_UP)


def cents(value) -> Decimal | None:
    """Valor ao centavo (meio para cima); ``None`` é preservado."""
    number = _dec(value)
    return None if number is None else number.quantize(CENT, rounding=ROUND_HALF_UP)


def charged_amount(cost_estimate) -> Decimal:
    """Valor cobrado pela energia de uma sessão: ``cost_estimate`` arredondado ao centavo.

    É a regra única para recibo, painel, exportações e captura do pagamento.
    """
    return cents(cost_estimate) or Decimal("0.00")


def clean_energy_cost(value) -> Decimal | None:
    """Custo do kWh informado pelo dono (R$ 0 a R$ 100, 4 casas) ou ``None`` (não informado)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    number = None if isinstance(value, bool) else _dec(value.replace(",", ".") if isinstance(value, str) else value)
    if number is None:
        raise ValueError("Informe o custo do kWh com números, por exemplo 0,85.")
    if not Decimal(0) <= number <= MAX_ENERGY_COST:
        raise ValueError("O custo do kWh vai de R$ 0,00 a R$ 100,00.")
    return number.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def clean_fee_percent(value) -> Decimal:
    number = None if isinstance(value, bool) else _dec(value)
    if number is None or not Decimal(0) <= number <= Decimal(100):
        raise ValueError("A comissão vai de 0% a 100%.")
    return number.quantize(CENT, rounding=ROUND_HALF_UP)


# ------------------------------------------------------------------ sessão

def session_economics(session: Mapping, *, station_energy_cost=None, station_fee_percent=None,
                      extras: Mapping | None = None) -> dict:
    """Resultado de uma sessão (valores ``Decimal`` ou ``None``).

    ``session``: campos da sessão (``energy_wh``, ``price_per_kwh``, ``base_price_per_kwh``,
    ``demand_multiplier``, ``discount_percent``, ``cost_estimate``, ``price_terms``,
    ``energy_cost_per_kwh`` e ``platform_fee_percent`` travados no início) e contexto
    (``id``, ``ended_at``, ``station_id``, ``station_name``, ``public_code``, ``source``).
    ``station_*``: configuração atual do posto, usada só quando a sessão não tem o valor
    travado (recargas anteriores ao cadastro). ``extras``: ``{"payment": {...},
    "overstay": {...}}`` das frentes de pagamento e permanência.
    """
    extras = extras or {}
    terms = session.get("price_terms") if isinstance(session.get("price_terms"), Mapping) else {}
    kwh = to_decimal(session.get("energy_wh")) / 1000
    price = to_decimal(session.get("price_per_kwh"))
    base = _dec(session.get("base_price_per_kwh"))
    base = price if base is None else base
    multiplier = _dec(session.get("demand_multiplier")) or Decimal(1)
    connector_base = _dec(terms.get("connector_base_per_kwh"))

    gross = _value(kwh * price)
    revenue = charged_amount(session.get("cost_estimate"))
    discount = gross - revenue
    at_base = _value(kwh * base)
    demand_effect = gross - at_base
    if connector_base is not None:
        list_value = _value(kwh * connector_base)
        schedule_effect = at_base - list_value
    else:
        list_value, schedule_effect = at_base, None

    overstay = extras.get("overstay") if isinstance(extras.get("overstay"), Mapping) else None
    overstay_revenue = None
    if overstay and not overstay.get("waived") and overstay.get("amount") is not None:
        overstay_revenue = cents(overstay.get("amount"))
    payment = extras.get("payment") if isinstance(extras.get("payment"), Mapping) else None
    revenue_total = revenue + (overstay_revenue or 0)
    revenue_basis = "estimated"
    provider_fee = None
    if payment:
        if payment.get("net_amount") is not None:
            revenue_total = cents(payment["net_amount"])
            revenue_basis = "captured"
        provider_fee = cents(payment.get("provider_fee"))

    fee_snapshot = _dec(session.get("platform_fee_percent"))
    fee_percent = fee_snapshot if fee_snapshot is not None else (
        _dec(station_fee_percent) if _dec(station_fee_percent) is not None else DEFAULT_PLATFORM_FEE_PERCENT)
    platform_fee = cents(revenue_total * fee_percent / 100)
    owner_net = revenue_total - platform_fee - (provider_fee or 0)

    cost_snapshot = _dec(session.get("energy_cost_per_kwh"))
    if cost_snapshot is not None:
        cost_per_kwh, cost_basis = cost_snapshot, "snapshot"
    elif _dec(station_energy_cost) is not None:
        cost_per_kwh, cost_basis = _dec(station_energy_cost), "current"
    else:
        cost_per_kwh, cost_basis = None, "missing"
    energy_cost = _value(kwh * cost_per_kwh) if cost_per_kwh is not None else None
    margin = owner_net - energy_cost if energy_cost is not None else None
    margin_percent = (margin / revenue_total * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP) \
        if margin is not None and revenue_total else None

    coupon = terms.get("coupon") if isinstance(terms.get("coupon"), Mapping) else {}
    ended = parse_time(session.get("ended_at"))
    return {
        "session_id": str(session.get("id") or ""),
        "ended_at": ended.isoformat() if ended else None,
        "station_id": str(session.get("station_id") or "") or None,
        "station_name": session.get("station_name") or "",
        "public_code": session.get("public_code") or "",
        "source": session.get("source"),
        "energy_kwh": kwh,
        "connector_base_per_kwh": connector_base,
        "base_per_kwh": base,
        "demand_multiplier": multiplier,
        "price_per_kwh": price,
        "coupon_code": coupon.get("code"),
        "discount_percent": int(session.get("discount_percent") or 0),
        "list_value": list_value,
        "schedule_effect": schedule_effect,
        "demand_effect": demand_effect,
        "gross": gross,
        "discount": discount,
        "revenue": revenue,
        "overstay_revenue": overstay_revenue,
        "revenue_total": revenue_total,
        "revenue_basis": revenue_basis,
        "payment_environment": (payment or {}).get("environment"),
        "platform_fee_percent": fee_percent.quantize(CENT, rounding=ROUND_HALF_UP),
        "platform_fee": platform_fee,
        "provider_fee": provider_fee,
        "owner_net": owner_net,
        "energy_cost_per_kwh": cost_per_kwh,
        "cost_basis": cost_basis,
        "energy_cost": energy_cost,
        "margin": margin,
        "margin_percent": margin_percent,
    }


# --------------------------------------------------------------- agregação

def _sum(rows, key) -> Decimal:
    return sum((row[key] for row in rows if row[key] is not None), Decimal("0.00"))


def _totals(rows: list[dict]) -> dict:
    covered = [row for row in rows if row["energy_cost"] is not None]
    complete = len(covered) == len(rows)
    revenue_total = _sum(rows, "revenue_total")
    margin_covered = _sum(covered, "margin")
    margin = margin_covered if complete else None
    totals = {key: _sum(rows, key) for key in MONEY_FIELDS if key not in ("margin", "energy_cost")}
    totals.update(
        sessions=len(rows),
        energy_kwh=sum((row["energy_kwh"] for row in rows), Decimal(0)),
        energy_cost=_sum(covered, "energy_cost") if covered else (None if rows else Decimal("0.00")),
        margin=margin if rows else Decimal("0.00"),
        margin_covered=margin_covered,
        margin_percent=(margin / revenue_total * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        if margin is not None and revenue_total else None,
        schedule_effect=_sum(rows, "schedule_effect") if any(r["schedule_effect"] is not None for r in rows) else None,
        provider_fee=_sum(rows, "provider_fee") if any(r["provider_fee"] is not None for r in rows) else None,
        overstay_revenue=_sum(rows, "overstay_revenue") if any(r["overstay_revenue"] is not None for r in rows)
        else None,
    )
    totals["coverage"] = {"sessions": len(rows), "with_energy_cost": len(covered),
                          "missing_energy_cost": len(rows) - len(covered)}
    return totals


def aggregate(rows: Iterable[dict]) -> dict:
    """Totais, efeito do preço dinâmico/cupons e quebra por posto (``Decimal``).

    Os totais somam as linhas já arredondadas ao centavo: tela, CSV e PDF fecham.
    A margem total só existe quando todas as sessões têm custo da energia; senão vem
    ``None`` e ``margin_covered`` traz a margem das sessões cobertas.
    """
    rows = list(rows)
    surge = [row for row in rows if row["demand_multiplier"] > 1]
    coupons = [row for row in rows if row["discount_percent"]]
    stations: dict[str, list[dict]] = {}
    for row in rows:
        stations.setdefault(row["station_id"] or "", []).append(row)
    by_station = []
    for station_id, items in stations.items():
        entry = _totals(items)
        entry.update(station_id=station_id or None, station_name=items[0]["station_name"])
        by_station.append(entry)
    by_station.sort(key=lambda item: (-item["revenue_total"], item["station_name"]))
    sources: dict[str, int] = {}
    for row in rows:
        key = row["source"] or "unknown"
        sources[key] = sources.get(key, 0) + 1
    totals = _totals(rows)
    return {
        "totals": totals,
        "dynamic_pricing": {
            "demand_effect": totals["demand_effect"],
            "schedule_effect": totals["schedule_effect"],
            "sessions_with_increase": len(surge),
            "average_multiplier": (sum((row["demand_multiplier"] for row in surge), Decimal(0)) / len(surge))
            .quantize(CENT, rounding=ROUND_HALF_UP) if surge else None,
        },
        "coupons": {"sessions": len(coupons), "discount": _sum(coupons, "discount")},
        "sources": sources,
        "by_station": by_station,
        "warnings": warnings(totals, sources),
    }


def warnings(totals: Mapping, sources: Mapping) -> list[str]:
    result = []
    missing = totals["coverage"]["missing_energy_cost"]
    if missing:
        result.append(f"{missing} de {totals['sessions']} sessões sem custo da energia informado: a margem "
                      "total não é calculada. Informe o custo do kWh do posto.")
    if totals.get("margin") is not None and totals["margin"] < 0:
        result.append("Margem negativa no período: o repasse não cobre o custo estimado da energia.")
    if sources.get("simulated"):
        result.append(f"{sources['simulated']} sessão(ões) com energia simulada pelo equipamento: não é medição "
                      "de medidor.")
    if totals["sessions"] and totals.get("provider_fee") is None:
        result.append("Sem pagamento confirmado: receitas estimadas pela energia registrada.")
    return result


# ------------------------------------------------------------ serialização

def _out(value, places="0.01"):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return decimal_text(value, places)
    return value


PLACES = {"energy_kwh": "0.001", "connector_base_per_kwh": "0.0001", "base_per_kwh": "0.0001",
          "price_per_kwh": "0.0001", "energy_cost_per_kwh": "0.0001", "margin_percent": "0.1",
          "demand_multiplier": "0.01", "platform_fee_percent": "0.01", "average_multiplier": "0.01"}


def serialize(value):
    """Converte linhas/totais (``Decimal``) para JSON: strings decimais com casas fixas."""
    if isinstance(value, Mapping):
        return {key: (serialize(item) if isinstance(item, (Mapping, list)) else
                      _out(item, PLACES.get(key, "0.01"))) for key, item in value.items()}
    if isinstance(value, list):
        return [serialize(item) for item in value]
    return _out(value)


def export_row(row: Mapping) -> dict:
    """Linha do CSV da margem (textos legíveis; números com ponto decimal)."""
    data = serialize(dict(row))
    data["cost_basis"] = COST_BASIS_LABELS.get(row["cost_basis"], row["cost_basis"])
    data["revenue_basis"] = "pagamento confirmado" if row["revenue_basis"] == "captured" else "estimada"
    return data


def margin_csv(rows: Iterable[Mapping]) -> str:
    """CSV das sessões (sem linhas de total misturadas), protegido contra fórmulas."""
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([label for _, label in MARGIN_EXPORT_COLUMNS])
    for row in rows:
        data = export_row(row)
        writer.writerow([csv_cell(data.get(key)) for key, _ in MARGIN_EXPORT_COLUMNS])
    return buffer.getvalue()
