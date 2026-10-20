"""Sinais de demanda medidos no banco + regra de ``chargegrid_core.pricing``.

Para uma lista de postos: duas consultas agrupadas (recargas recentes e histórico do
mesmo horário nas 4 semanas anteriores), além do estado já carregado por ``_point_state``.
A tarifa base vigente vem da tarifação por horário do dono (``rules.schedule``), no
horário local do posto.
"""
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select

from chargegrid_core import pricing

from ...models import ChargingSession, Connector, Station, now
from ...service import online

LOCAL_TIMEZONE = ZoneInfo("America/Sao_Paulo")
BASELINE_WEEKS = 4


def local_time(moment):
    """Horário local do posto (sem fuso), usado pela tarifação por horário."""
    return moment.astimezone(LOCAL_TIMEZONE).replace(tzinfo=None)


def _participants(points, state):
    devices, _, _, retired = state
    return [
        point for point in points
        if point.active and point.id not in retired and online(devices.get(point.id))
    ]


def demand_by_station(db, stations, points_by_station, state, current=None):
    """``{station_id: demand_status}`` (``chargegrid_core.pricing.demand_status``) para vários postos."""
    current = current or now()
    _, reservations, sessions, _ = state
    participants = {station.id: _participants(points_by_station.get(station.id, []), state) for station in stations}
    station_of = {point.id: station_id for station_id, points in participants.items() for point in points}
    ids = list(station_of)
    window_start = current - timedelta(minutes=pricing.WINDOW_MINUTES)
    hour_ago = current - timedelta(hours=1)
    intervals, starts, baseline = {}, {}, {}
    if ids:
        recent = db.execute(
            select(ChargingSession.connector_id, ChargingSession.created_at, ChargingSession.started_at,
                   ChargingSession.ended_at)
            .where(ChargingSession.connector_id.in_(ids),
                   or_(ChargingSession.created_at >= hour_ago, ChargingSession.ended_at.is_(None),
                       ChargingSession.ended_at >= window_start))
        ).all()
        for connector_id, created_at, started_at, ended_at in recent:
            station_id = station_of[connector_id]
            intervals.setdefault(station_id, []).append((started_at or created_at, ended_at))
            if created_at >= hour_ago:
                starts[station_id] = starts.get(station_id, 0) + 1
        ranges = [(hour_ago - timedelta(weeks=week), current - timedelta(weeks=week))
                  for week in range(1, BASELINE_WEEKS + 1)]
        history = db.execute(
            select(ChargingSession.connector_id).where(
                ChargingSession.connector_id.in_(ids),
                or_(*(ChargingSession.created_at.between(begin, end) for begin, end in ranges)),
            )
        ).scalars()
        for connector_id in history:
            baseline[station_of[connector_id]] = baseline.get(station_of[connector_id], 0) + 1
    local_now = local_time(current)
    result = {}
    for station in stations:
        points = participants[station.id]
        in_use = sum(1 for point in points if point.id in sessions)
        reserved = sum(1 for point in points if point.id in reservations and point.id not in sessions)
        result[station.id] = pricing.demand_status(station.pricing, {
            "connectors": len(points), "in_use": in_use, "reserved": reserved,
            "busy_15m": pricing.busy_fraction(intervals.get(station.id, []), current, len(points)),
            "starts_60m": starts.get(station.id, 0),
            "baseline_60m": Decimal(baseline.get(station.id, 0)) / BASELINE_WEEKS,
            "local_now": local_now,
        })
    return result


def station_demand(db, station):
    """Status de demanda de um posto (consulta o estado dos pontos)."""
    from ...http_helpers import _point_state  # evita import circular

    points = db.scalars(select(Connector).where(Connector.station_id == station.id)).all()
    return demand_by_station(db, [station], {station.id: points}, _point_state(db, points))[station.id]


def current_multiplier(db, connector) -> Decimal:
    """Multiplicador vigente para iniciar uma reserva/recarga neste ponto."""
    station = db.get(Station, connector.station_id)
    return Decimal(station_demand(db, station)["multiplier"])


def scheduled_base(station, connector, moment) -> Decimal:
    """Tarifa base do ponto em ``moment``: a do horário do dono ou a base do conector."""
    interval = pricing.active_interval(pricing.stored_rules(station.pricing), local_time(moment))
    return pricing.base_now(interval, connector.id, connector.price_per_kwh)


def current_terms(db, connector, reservation=None) -> tuple[Decimal, Decimal]:
    """``(base, multiplicador)`` travados ao iniciar uma recarga neste ponto.

    Com reserva, valem os termos do momento da reserva: o multiplicador gravado nela e a
    base do horário em ``reservation.created_at``. Sem reserva, os de agora.
    """
    station = db.get(Station, connector.station_id)
    if reservation is not None:
        multiplier = (Decimal(reservation.demand_multiplier) if reservation.demand_multiplier is not None
                      else Decimal(station_demand(db, station)["multiplier"]))
        return scheduled_base(station, connector, reservation.created_at), multiplier
    status = station_demand(db, station)
    return pricing.connector_price(status, connector.id, connector.price_per_kwh)[0], Decimal(status["multiplier"])
