"""Recibo explicável da recarga (contrato ``chargegrid.receipt`` versionado e aditivo).

Funções puras (stdlib + ``Decimal``): a API monta os fatos (sessão, termos do preço
travado, eventos, amostras de potência e seções das outras frentes) e este módulo
devolve o recibo serializável em JSON. O app (inclusive a conta demo) e o PDF leem o
mesmo dicionário.

Contrato
--------
``schema = "chargegrid.receipt"`` e ``schema_version = 1``. Seções novas entram como
chaves novas; clientes ignoram o que não conhecem. Cada seção traz ``status``:
``available`` | ``pending`` | ``not_applicable`` | ``unavailable``. Pagamento (frente A),
permanência (frente D) e mudanças de potência com motivo (frente B) chegam por
``facts["sections"]`` e só aparecem quando confirmados pela fonte deles.

Dinheiro e energia vão como strings decimais (``"12.34"``, ``"7.250"``); horários em ISO
8601 (UTC). Textos em pt-BR, com rótulo honesto de simulado/sem cobrança.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from . import economics
from .analytics import (
    FINISHED_STATUSES,
    decimal_text,
    duration_minutes,
    local,
    parse_time,
    to_decimal,
)
from .formatting import brl
from .pricing import multiplier_label

SCHEMA = "chargegrid.receipt"
SCHEMA_VERSION = 1
TERMS_VERSION = 1
MAX_POWER_POINTS = 120
FINAL_STATUSES = (*FINISHED_STATUSES, "failed")
KNOWN_SECTIONS = ("payment", "overstay", "power_changes")

STATUS_LABELS = {
    "starting": "Aguardando o equipamento iniciar", "charging": "Recarga em andamento",
    "stopping": "Parada pendente no equipamento", "completed": "Recarga concluída",
    "interrupted": "Recarga interrompida", "failed": "Falha na recarga",
}
END_REASONS = {
    "requested_stop": "Parada solicitada", "user_stop": "Parada solicitada", "stop_requested": "Parada solicitada",
    "requested": "Parada solicitada", "device_stopped": "Encerrada pelo equipamento",
    "duration_limit": "Limite de duração atingido", "max_duration": "Limite de duração atingido",
    "cost_limit": "Limite de valor atingido", "max_cost": "Limite de valor atingido",
    "disconnected": "Cabo desconectado", "device_fault": "Falha no equipamento",
    "communication_lost": "Conexão perdida com o servidor", "device_reboot": "Equipamento reiniciado",
    "reboot": "Equipamento reiniciado", "command_timeout": "Equipamento não confirmou a operação",
    "start_timeout": "Equipamento não confirmou o início", "start_failed": "Falha ao iniciar",
    "battery_full": "Bateria cheia (100%)",
}
EVENT_LABELS = {
    "start_requested": "Início solicitado", "stop_requested": "Parada solicitada",
    "command_received": "Comando recebido pelo ponto", "command_failed": "Falha informada pelo ponto",
    "start_applied": "Início confirmado pelo ponto", "stop_applied": "Parada confirmada pelo ponto",
    "offline_reconciled": "Estado conciliado após período offline", "ended": "Fim da sessão observado",
}
EVENT_SOURCES = {"api": "servidor", "device_sync": "sincronização do ponto", "simulator": "simulador local"}
SOURCE_LABELS = {
    "simulated": "Energia simulada pelo equipamento (não é medição de medidor)",
    "measured": "Energia medida pelo equipamento",
    "estimated": "Energia estimada pelo equipamento",
}
PAYMENT_ENVIRONMENTS = {"none": "Sem pagamento", "mock": "Pagamento simulado", "sandbox": "Pagamento de teste (sandbox)",
                        "production": "Pagamento real"}
FISCAL_NOTE = "Documento sem valor fiscal."


# ----------------------------------------------------------------- utilidades

def _dec(value) -> Decimal | None:
    return economics._dec(value)


def _text(value, places="0.01") -> str | None:
    return decimal_text(value, places) if value is not None else None


def _iso(value) -> str | None:
    moment = parse_time(value)
    return moment.astimezone(timezone.utc).isoformat() if moment else None


def _local(value, fmt="%d/%m %H:%M") -> str:
    moment = parse_time(value)
    return local(moment).strftime(fmt) if moment else "—"


def _per_kwh(value) -> str:
    return brl(value) + "/kWh"


# ------------------------------------------------- termos do preço travado

def demand_snapshot(status: Mapping | None, multiplier=None) -> dict:
    """Parte de demanda dos termos: multiplicador e o motivo exibido no momento da trava."""
    status = status or {}
    value = _dec(multiplier if multiplier is not None else status.get("multiplier")) or Decimal(1)
    snapshot = {"multiplier": _text(value), "recorded": bool(status)}
    if status:
        snapshot.update(level=status.get("level"), level_label=status.get("level_label"),
                        reason=status.get("reason"), reason_label=status.get("reason_label"),
                        factors=[{key: factor.get(key) for key in ("key", "label", "value", "detail")}
                                 for factor in status.get("factors") or []])
    return snapshot


def price_terms(*, locked_at, locked_by: str, connector_base, base, multiplier, status: Mapping | None = None,
                demand: Mapping | None = None, coupon: Mapping | None = None, interval: Mapping | None = None,
                connector_id=None) -> dict:
    """Explicação do preço travado (gravada em ``price_terms`` na reserva e no início).

    ``status``: ``pricing.demand_status`` usado na trava (dele saem motivo e fatores);
    ``demand``: snapshot já gravado (reserva), que tem prioridade sobre ``status``;
    ``interval``: horário da tarifação vigente no momento da trava (``pricing.active_interval``).
    A base vem do horário quando o horário tem preço para ``connector_id``.
    """
    connector_base = _dec(connector_base)
    base = _dec(base)
    if demand is None:
        demand = demand_snapshot(status, multiplier)
    else:
        demand = {**demand, "multiplier": _text(_dec(multiplier) or Decimal(1))}
    prices = (interval or {}).get("prices") or {}
    schedule = bool(interval) and (str(connector_id) in prices if connector_id is not None else bool(prices))
    window = f"{interval['start']}–{interval['end']}" if interval else None
    terms = {
        "version": TERMS_VERSION,
        "locked_at": _iso(locked_at),
        "locked_by": locked_by,
        "connector_base_per_kwh": _text(connector_base, "0.0001"),
        "base_per_kwh": _text(base, "0.0001"),
        "base_source": "schedule" if schedule else "connector",
        "schedule_window": window if schedule else None,
        "demand": demand,
        "coupon": None,
    }
    if coupon:
        terms["coupon"] = {"id": str(coupon.get("id")) if coupon.get("id") else None, "code": coupon.get("code"),
                           "discount_percent": int(coupon.get("discount_percent") or 0)}
    return terms


# ------------------------------------------------------------------ seções

def price_section(session: Mapping) -> dict:
    terms = session.get("price_terms") if isinstance(session.get("price_terms"), Mapping) else None
    price = to_decimal(session.get("price_per_kwh"))
    base = _dec(session.get("base_price_per_kwh"))
    base = price if base is None else base
    multiplier = _dec(session.get("demand_multiplier")) or Decimal(1)
    discount = int(session.get("discount_percent") or 0)
    demand = (terms or {}).get("demand") or {}
    coupon = (terms or {}).get("coupon") or None
    connector_base = _dec((terms or {}).get("connector_base_per_kwh"))
    schedule = (terms or {}).get("base_source") == "schedule"
    window = (terms or {}).get("schedule_window")
    locked_by = (terms or {}).get("locked_by") or ("reservation" if session.get("reservation_id") else "start")
    locked_at = (terms or {}).get("locked_at") or _iso(session.get("created_at"))

    lines, explanation = [], []
    if schedule and connector_base is not None:
        lines.append({"key": "connector_base", "label": "Tarifa base do conector",
                      "value": _text(connector_base, "0.0001"), "unit": "R$/kWh"})
        label = f"Tarifa do horário {window}" if window else "Tarifa do horário"
        lines.append({"key": "schedule", "label": label, "value": _text(base, "0.0001"), "unit": "R$/kWh"})
        explanation.append(f"{label}: {_per_kwh(base)} (base do conector {_per_kwh(connector_base)}).")
    else:
        lines.append({"key": "base", "label": "Tarifa base", "value": _text(base, "0.0001"), "unit": "R$/kWh"})
        explanation.append(f"Tarifa base: {_per_kwh(base)}.")
    reason = demand.get("reason_label")
    occupancy = next((f"{factor.get('label')}: {factor.get('value')}" for factor in demand.get("factors") or []
                      if factor.get("key") == "occupancy"), None)
    if multiplier > 1:
        detail = " · ".join(part for part in ((demand.get("level_label") and f"Demanda {demand['level_label'].lower()}"),
                                               occupancy) if part) or None
        increase = (base * (multiplier - 1)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        lines.append({"key": "demand", "label": "Ajuste por demanda", "value": _text(multiplier), "unit": "×",
                      "detail": detail, "increase_per_kwh": _text(increase, "0.0001")})
        why = detail or ("motivo não registrado (recarga anterior ao registro do motivo)" if not terms else None)
        explanation.append(f"Ajuste por demanda {multiplier_label(multiplier)} (+{_per_kwh(increase)})"
                           + (f": {why}." if why else "."))
    else:
        lines.append({"key": "demand", "label": "Sem ajuste por demanda", "value": "1.00", "unit": "×",
                      "detail": None})
    moment = "na reserva" if locked_by == "reservation" else "no início da recarga"
    lines.append({"key": "locked_price", "label": "Preço travado", "value": _text(price, "0.0001"), "unit": "R$/kWh"})
    explanation.append(f"Preço travado em {_per_kwh(price)} {moment} ({_local(locked_at)}); mudanças posteriores "
                       "de demanda ou tarifa não alteram esta recarga.")
    if discount:
        code = (coupon or {}).get("code")
        label = f"Cupom {code}" if code else "Cupom (código não registrado)"
        lines.append({"key": "coupon", "label": label, "value": str(discount), "unit": "%"})
        explanation.append(f"{label}: −{discount}% sobre a energia.")
    return {
        "status": "available",
        "recorded": bool(terms),
        "locked_at": locked_at,
        "locked_by": locked_by,
        "connector_base_per_kwh": _text(connector_base, "0.0001"),
        "base_per_kwh": _text(base, "0.0001"),
        "base_source": "schedule" if schedule else "connector",
        "schedule_window": window if schedule else None,
        "demand": {"multiplier": _text(multiplier), "label": multiplier_label(multiplier),
                   "level_label": demand.get("level_label"), "reason_label": reason,
                   "factors": demand.get("factors") or []},
        "coupon": {"code": (coupon or {}).get("code"), "discount_percent": discount},
        "price_per_kwh": _text(price, "0.0001"),
        "lines": lines,
        "explanation": explanation,
    }


def _ended_by_device(events) -> Mapping | None:
    return next((event for event in events if event.get("kind") == "ended" and event.get("source") == "device_sync"),
                None)


def energy_section(session: Mapping, events: list[Mapping]) -> dict:
    final = session.get("status") in FINAL_STATUSES
    ended = _ended_by_device(events)
    confirmed = bool(final and ended and session.get("last_measurement_at"))
    source = session.get("source")
    if confirmed:
        note = "Energia confirmada pelo equipamento ao encerrar a recarga."
    elif final:
        note = (f"Última leitura do equipamento às {_local(session.get('last_measurement_at'), '%H:%M')}; "
                "o encerramento não foi confirmado pelo equipamento.") if session.get("last_measurement_at") \
            else "O equipamento não enviou leitura de energia."
    else:
        note = "Recarga em andamento: energia parcial, ainda não confirmada."
    return {
        "status": "available" if final else "pending",
        "kwh": _text(to_decimal(session.get("energy_wh")) / 1000, "0.001"),
        "wh": _text(to_decimal(session.get("energy_wh")), "0.001"),
        "source": source,
        "source_label": SOURCE_LABELS.get(source, "Origem da medição não informada"),
        "confirmed_by_device": confirmed,
        "confirmed_at": _iso(ended.get("observed_at")) if confirmed else None,
        "last_measurement_at": _iso(session.get("last_measurement_at")),
        "soc_start": _text(_dec(session.get("start_soc_percent")), "0.1"),
        "soc_end": _text(_dec(session.get("soc_percent")), "0.1"),
        "power_limit_kw": _text(_dec(session.get("power_limit_kw")), "0.001"),
        "note": note,
    }


def downsample(points: list, limit: int = MAX_POWER_POINTS) -> list:
    """No máximo ``limit`` pontos, espaçados igualmente, sempre com o primeiro e o último."""
    if len(points) <= limit:
        return list(points)
    if limit < 2:
        return points[-limit:] if limit else []
    step = (len(points) - 1) / (limit - 1)
    return [points[round(index * step)] for index in range(limit)]


def power_section(session: Mapping, samples: Iterable[Mapping], changes: list | None, events: list[Mapping]) -> dict:
    curve = []
    for sample in samples:
        moment = parse_time(sample.get("captured_at"))
        watts = _dec(sample.get("power_w"))
        if moment is None or watts is None:
            continue
        curve.append((moment, watts))
    curve.sort(key=lambda item: item[0])
    points = [{"t": moment.astimezone(timezone.utc).isoformat(), "kw": _text(watts / 1000)}
              for moment, watts in downsample(curve)]
    if changes is None:
        changes = []
        limit = _dec(session.get("power_limit_kw"))
        applied = next((event for event in events if event.get("kind") == "start_applied"), None)
        if limit is not None:
            changes.append({"at": _iso((applied or {}).get("observed_at") or session.get("started_at")),
                            "requested_kw": None, "applied_kw": _text(limit, "0.001"),
                            "status": "applied" if applied else "requested", "reason_code": "start_limit",
                            "reason_label": "Limite de potência no início (ponto, posto e carro)",
                            "confirmed_at": _iso((applied or {}).get("observed_at"))})
    peak = max((watts for _, watts in curve), default=None)
    result = {
        "status": "available" if points else "unavailable",
        "samples": points,
        "sample_count": len(curve),
        "peak_kw": _text(peak / 1000) if peak is not None else None,
        "changes": changes,
    }
    if not points:
        result["note"] = "Amostras de potência indisponíveis (não enviadas pelo equipamento ou já expiradas)."
    return result


def timeline_section(events: Iterable[Mapping]) -> list[dict]:
    result = []
    for event in events:
        label = EVENT_LABELS.get(event.get("kind"), "Evento registrado")
        if event.get("source") == "simulator":
            label = label.replace("pelo ponto", "na simulação")
        result.append({"kind": event.get("kind"), "label": label, "source": event.get("source"),
                       "source_label": EVENT_SOURCES.get(event.get("source"), "origem indisponível"),
                       "observed_at": _iso(event.get("observed_at"))})
    return result


def charges_section(session: Mapping, payment: Mapping | None, overstay: Mapping | None) -> dict:
    row = economics.session_economics(session, extras={"payment": payment, "overstay": overstay})
    final = session.get("status") in FINAL_STATUSES
    overstay_amount = row["overstay_revenue"]
    total = row["revenue"] + (overstay_amount or 0)
    result = {
        "status": "final" if final else "provisional",
        "currency": "BRL",
        "energy_gross": _text(row["gross"]),
        "discount": _text(row["discount"]),
        "energy_total": _text(row["revenue"]),
        "overstay": _text(overstay_amount),
        "total": _text(total),
        "revenue_basis": "estimated",
        "note": "Valor estimado pela energia registrada; sem pagamento confirmado." if not payment else None,
    }
    if payment and payment.get("net_amount") is not None:
        result.update(revenue_basis="paid", paid_total=_text(economics.cents(payment["net_amount"])))
        result["note"] = None
    return result


def labels_section(session: Mapping, payment: Mapping | None, demo: bool) -> dict:
    source = session.get("source")
    environment = (payment or {}).get("environment") or "none"
    notes = []
    if demo:
        notes.append("Conta demo: dados de exemplo, sem cobrança nem medição reais.")
    if source == "simulated":
        notes.append("SIMULADO: energia calculada pelo simulador do equipamento, não por medidor.")
    elif source is None:
        notes.append("Origem da medição não informada.")
    if environment == "none":
        notes.append("Sem pagamento registrado: nenhum valor foi cobrado.")
    elif environment in ("mock", "sandbox"):
        notes.append(f"{PAYMENT_ENVIRONMENTS[environment]}: nenhum dinheiro real foi movimentado.")
    notes.append(FISCAL_NOTE)
    return {"measurement": source or "unknown", "measurement_label": SOURCE_LABELS.get(source, "Não informada"),
            "simulated": source == "simulated" or demo, "payment_environment": environment,
            "payment_environment_label": PAYMENT_ENVIRONMENTS.get(environment, environment), "demo": demo,
            "notes": notes}


# ----------------------------------------------------------------- recibo

def build_receipt(facts: Mapping) -> dict:
    """Recibo v1 a partir dos fatos montados pela API (ou pela conta demo do app).

    ``facts``: ``session`` (campos da sessão), ``station`` (``name``, ``address``),
    ``point`` (``public_code``, ``connector_type``, ``power_kw``), ``events``,
    ``samples`` (``captured_at``, ``power_w``), ``sections`` (``payment``, ``overstay``,
    ``power_changes`` e extensões) e ``now``/``demo``.
    """
    session = facts["session"]
    events = list(facts.get("events") or [])
    sections = dict(facts.get("sections") or {})
    payment = sections.get("payment") if isinstance(sections.get("payment"), Mapping) else None
    overstay = sections.get("overstay") if isinstance(sections.get("overstay"), Mapping) else None
    now = facts.get("now") or datetime.now(timezone.utc)
    station, point = facts.get("station") or {}, facts.get("point") or {}
    status = session.get("status")
    minutes = duration_minutes(session, now)
    identifier = str(session.get("id") or "")
    receipt = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "final": status in FINAL_STATUSES,
        "session_id": identifier,
        "number": identifier.replace("-", "")[:8].upper(),
        "labels": labels_section(session, payment, bool(facts.get("demo"))),
        "station": {"name": station.get("name") or "Posto não identificado", "address": station.get("address")},
        "point": {"public_code": point.get("public_code"), "connector_type": point.get("connector_type"),
                  "power_kw": _text(_dec(point.get("power_kw")), "0.001")},
        "times": {"created_at": _iso(session.get("created_at")), "started_at": _iso(session.get("started_at")),
                  "ended_at": _iso(session.get("ended_at")),
                  "duration_minutes": _text(minutes, "0.1") if minutes is not None else None,
                  "status": status, "status_label": STATUS_LABELS.get(status, status),
                  "end_reason": session.get("end_reason"),
                  "end_reason_label": END_REASONS.get(session.get("end_reason"), session.get("end_reason"))},
        "price": price_section(session),
        "energy": energy_section(session, events),
        "charges": charges_section(session, payment, overstay),
        "power": power_section(session, facts.get("samples") or [], sections.get("power_changes"), events),
        "timeline": timeline_section(events),
        "payment": {"status": "available", **payment} if payment else {
            "status": "not_applicable", "note": "Sem pagamento registrado: valor estimado, sem cobrança real."},
        "overstay": {"status": "available", **overstay} if overstay else {"status": "not_applicable"},
    }
    extensions = {key: value for key, value in sections.items() if key not in KNOWN_SECTIONS and value is not None}
    if extensions:
        receipt["extensions"] = extensions
    return receipt


# ----------------------------------------------- histórico do motorista

HISTORY_EXPORT_COLUMNS = (
    ("id", "ID da sessão"),
    ("station_name", "Posto"),
    ("public_code", "Ponto"),
    ("status", "Status"),
    ("started_at", "Início"),
    ("ended_at", "Fim"),
    ("duration_minutes", "Duração (min)"),
    ("energy_kwh", "Energia (kWh)"),
    ("price_per_kwh", "Preço travado (R$/kWh)"),
    ("demand_multiplier", "Multiplicador de demanda"),
    ("discount_percent", "Desconto (%)"),
    ("total", "Valor (R$)"),
    ("source", "Origem da medição"),
    ("end_reason", "Motivo de término"),
)


def history_row(session: Mapping, now: datetime | None = None) -> dict:
    """Linha do histórico do motorista (somente os dados dele; strings decimais)."""
    minutes = duration_minutes(session, now)
    return {
        "id": str(session.get("id") or ""),
        "station_name": session.get("station_name") or "",
        "public_code": session.get("public_code") or "",
        "status": session.get("status"),
        "status_label": STATUS_LABELS.get(session.get("status"), session.get("status")),
        "started_at": _iso(session.get("started_at")),
        "ended_at": _iso(session.get("ended_at")),
        "duration_minutes": _text(minutes, "0.1") if minutes is not None else None,
        "energy_kwh": _text(to_decimal(session.get("energy_wh")) / 1000, "0.001"),
        "price_per_kwh": _text(to_decimal(session.get("price_per_kwh")), "0.0001"),
        "demand_multiplier": _text(_dec(session.get("demand_multiplier")) or Decimal(1)),
        "discount_percent": int(session.get("discount_percent") or 0),
        "total": _text(economics.charged_amount(session.get("cost_estimate"))),
        "source": session.get("source"),
        "end_reason": session.get("end_reason"),
        "end_reason_label": END_REASONS.get(session.get("end_reason"), session.get("end_reason")),
    }


def history_totals(rows: Iterable[Mapping]) -> dict:
    """Totais das sessões encerradas com energia (mesma regra do ``/me/summary``)."""
    eligible = [row for row in rows if row.get("status") in FINISHED_STATUSES and to_decimal(row.get("energy_kwh")) > 0]
    sources: dict[str, int] = {}
    for row in eligible:
        sources[row.get("source") or "unknown"] = sources.get(row.get("source") or "unknown", 0) + 1
    return {
        "sessions": len(eligible),
        "energy_kwh": _text(sum((to_decimal(row.get("energy_kwh")) for row in eligible), Decimal(0)), "0.001"),
        "total": _text(sum((to_decimal(row.get("total")) for row in eligible), Decimal("0.00"))),
        "sources": sources,
    }
