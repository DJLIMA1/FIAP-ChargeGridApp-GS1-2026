"""Consultas agregadas do dashboard do proprietário.

Cada função executa um número fixo de consultas, independente da quantidade de
postos/pontos (sem N+1). A autorização é aplicada por ``scope``: somente
conectores de postos cujo ``owner_id`` é o usuário (e, opcionalmente, um posto
específico já validado com :func:`app.service.owned`).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import String, and_, case, cast, extract, func, or_, select
from sqlalchemy.orm import aliased

from chargegrid_core import analytics
from chargegrid_core.chargers import link as charger_link

from ... import overstay
from ...models import ChargingSession, Command, Connector, Device, Reservation, Station, Telemetry, now
from ...service import RES_ACTIVE, SESSION_ACTIVE, kiosk_holds, resetting_screens

TZ = analytics.REPORT_TZ_NAME
ONLINE_WINDOW = timedelta(seconds=45)
EXPORT_LIMIT = 10000


@dataclass(frozen=True)
class Scope:
    owner_id: UUID
    station_id: UUID | None = None

    def stations(self, query):
        query = query.where(Station.owner_id == self.owner_id)
        return query.where(Station.id == self.station_id) if self.station_id else query


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime


def _owned_sessions(scope, *columns):
    return scope.stations(
        select(*columns)
        .select_from(ChargingSession)
        .join(Connector, Connector.id == ChargingSession.connector_id)
        .join(Station, Station.id == Connector.station_id)
    )


def _eligible(window):
    return and_(
        ChargingSession.status.in_(analytics.FINISHED_STATUSES),
        ChargingSession.energy_wh > 0,
        ChargingSession.ended_at >= window.start,
        ChargingSession.ended_at < window.end,
    )


def _charged():
    """Valor cobrado de cada sessão: ``cost_estimate`` ao centavo (mesma regra do recibo e da margem,
    ``chargegrid_core.economics.charged_amount``); somas ao centavo por sessão fecham com a margem."""
    return func.round(ChargingSession.cost_estimate, 2)


def _busy_seconds(window, moment):
    finished = func.least(func.coalesce(ChargingSession.ended_at, moment), window.end)
    began = func.greatest(ChargingSession.started_at, window.start)
    overlap = and_(ChargingSession.started_at.is_not(None), ChargingSession.started_at < window.end,
                   func.coalesce(ChargingSession.ended_at, moment) > window.start)
    return func.coalesce(func.sum(extract("epoch", finished - began)).filter(overlap), 0)


def _ended_in(window):
    return and_(ChargingSession.ended_at >= window.start, ChargingSession.ended_at < window.end)


def point_counts(db, scope, moment):
    published = and_(Connector.active.is_(True), Station.active.is_(True))
    online = and_(Device.last_seen.is_not(None), Device.last_seen > moment - ONLINE_WINDOW)
    total, alive, stations, stations_active, all_points = db.execute(
        scope.stations(
            select(
                func.count(Connector.id).filter(published),
                func.count(Connector.id).filter(and_(published, online)),
                func.count(func.distinct(Station.id)),
                func.count(func.distinct(Station.id)).filter(Station.active.is_(True)),
                func.count(Connector.id),
            )
            .select_from(Station)
            .outerjoin(Connector, Connector.station_id == Station.id)
            .outerjoin(Device, and_(Device.connector_id == Connector.id, Device.revoked.is_(False)))
        )
    ).one()
    return {"points": total, "points_online": alive, "stations": stations, "stations_active": stations_active,
            "points_total": all_points}


def overview(db, scope, window, ranking_limit=10):
    moment = now()
    revenue, energy, sessions, busy, interrupted, failed, active = db.execute(
        _owned_sessions(
            scope,
            func.coalesce(func.sum(_charged()).filter(_eligible(window)), 0),
            func.coalesce(func.sum(ChargingSession.energy_wh).filter(_eligible(window)), 0),
            func.count(ChargingSession.id).filter(_eligible(window)),
            _busy_seconds(window, moment),
            func.count(ChargingSession.id).filter(and_(ChargingSession.status == "interrupted", _ended_in(window))),
            func.count(ChargingSession.id).filter(and_(ChargingSession.status == "failed", _ended_in(window))),
            func.count(ChargingSession.id).filter(ChargingSession.status.in_(SESSION_ACTIVE)),
        )
    ).one()
    reservations, no_shows = db.execute(
        scope.stations(
            select(func.count(Reservation.id), func.count(Reservation.id).filter(Reservation.status == "expired"))
            .select_from(Reservation)
            .join(Connector, Connector.id == Reservation.connector_id)
            .join(Station, Station.id == Connector.station_id)
            .where(Reservation.created_at >= window.start, Reservation.created_at < window.end)
        )
    ).one()
    counts = point_counts(db, scope, moment)
    totals = {"revenue": revenue, "energy_wh": energy, "sessions": sessions, "busy_minutes": analytics.to_decimal(busy) / 60,
              "interrupted": interrupted, "failed": failed, "active_sessions": active,
              "reservations": reservations, "no_shows": no_shows}
    return {
        "period": {"from": window.start.isoformat(), "to": window.end.isoformat(), "timezone": TZ},
        "station_id": str(scope.station_id) if scope.station_id else None,
        "kpis": analytics.build_kpis(totals, points=counts["points"], points_online=counts["points_online"],
                                     start=window.start, end=window.end),
        "stations": {"total": counts["stations"], "active": counts["stations_active"],
                     "points": counts["points_total"], "points_published": counts["points"],
                     "points_online": counts["points_online"]},
        "ranking": ranking(db, scope, window, moment, ranking_limit),
        "generated_at": moment.isoformat(),
    }


def ranking(db, scope, window, moment, limit=None):
    join = and_(
        ChargingSession.connector_id == Connector.id,
        ChargingSession.created_at < window.end,
        or_(ChargingSession.ended_at.is_(None), ChargingSession.ended_at >= window.start),
    )
    rows = db.execute(
        scope.stations(
            select(
                Connector.id.label("connector_id"),
                Station.id.label("station_id"),
                Station.name.label("station_name"),
                Connector.public_code,
                func.coalesce(func.sum(_charged()).filter(_eligible(window)), 0).label("revenue"),
                func.coalesce(func.sum(ChargingSession.energy_wh).filter(_eligible(window)), 0).label("energy_wh"),
                func.count(ChargingSession.id).filter(_eligible(window)).label("sessions"),
                _busy_seconds(window, moment).label("busy_seconds"),
            )
            .select_from(Connector)
            .join(Station, Station.id == Connector.station_id)
            .outerjoin(ChargingSession, join)
            .group_by(Connector.id, Station.id, Station.name, Connector.public_code)
        )
    ).mappings()
    records = [{**row, "busy_minutes": analytics.to_decimal(row["busy_seconds"]) / 60} for row in rows]
    return analytics.ranking_payload(records, window.start, window.end, limit)


def timeseries(db, scope, window, granularity):
    local_end = func.timezone(TZ, ChargingSession.ended_at)
    bucket = func.date_trunc(granularity, local_end).label("bucket")
    rows = db.execute(
        _owned_sessions(
            scope,
            bucket,
            func.coalesce(func.sum(_charged()), 0),
            func.coalesce(func.sum(ChargingSession.energy_wh), 0),
            func.count(ChargingSession.id),
        ).where(_eligible(window)).group_by(bucket)
    ).all()
    return analytics.series_payload(rows, window.start, window.end, granularity)


def heatmap(db, scope, window):
    moment = func.coalesce(ChargingSession.started_at, ChargingSession.created_at)
    local_moment = func.timezone(TZ, moment)
    weekday = (extract("isodow", local_moment) - 1).label("weekday")
    hour = extract("hour", local_moment).label("hour")
    rows = db.execute(
        _owned_sessions(scope, weekday, hour, func.count(ChargingSession.id))
        .where(moment >= window.start, moment < window.end)
        .group_by(weekday, hour)
    ).all()
    payload = analytics.heatmap_payload(rows)
    payload["peak_hours"] = analytics.peak_hours(payload)
    return payload


SESSION_COLUMNS = (
    ChargingSession.id, ChargingSession.connector_id, ChargingSession.status, ChargingSession.created_at,
    ChargingSession.started_at, ChargingSession.ended_at, ChargingSession.energy_wh,
    ChargingSession.price_per_kwh, ChargingSession.discount_percent, ChargingSession.cost_estimate,
    ChargingSession.source, ChargingSession.end_reason, ChargingSession.overstay_terms,
    ChargingSession.overstay_billable_seconds, ChargingSession.overstay_fee, Station.id.label("station_id"),
    Station.name.label("station_name"), Connector.public_code,
)


def _literal(q):
    """Texto digitado vira literal no LIKE ("%" e "_" não funcionam como curingas)."""
    return q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _search(q, column):
    text = _literal(q)
    pattern = f"%{text}%"
    return or_(Station.name.ilike(pattern, escape="\\"), Connector.public_code.ilike(pattern, escape="\\"),
               cast(column, String).ilike(f"{text}%", escape="\\"))


def session_query(scope, window, status=None, q=None):
    query = _owned_sessions(scope, *SESSION_COLUMNS).where(
        ChargingSession.created_at >= window.start, ChargingSession.created_at < window.end
    )
    if status:
        query = query.where(ChargingSession.status.in_(status))
    if q and q.strip():
        query = query.where(_search(q, ChargingSession.id))
    return query.order_by(ChargingSession.created_at.desc(), ChargingSession.id.desc())


def reservation_query(scope, window, status=None, q=None):
    query = scope.stations(
        select(Reservation.id, Reservation.connector_id, Reservation.status, Reservation.created_at,
               Reservation.expires_at, Station.id.label("station_id"), Station.name.label("station_name"),
               Connector.public_code)
        .select_from(Reservation)
        .join(Connector, Connector.id == Reservation.connector_id)
        .join(Station, Station.id == Connector.station_id)
        .where(Reservation.created_at >= window.start, Reservation.created_at < window.end)
    )
    if status:
        query = query.where(Reservation.status.in_(status))
    if q and q.strip():
        query = query.where(_search(q, Reservation.id))
    return query.order_by(Reservation.created_at.desc(), Reservation.id.desc())


def paginate(db, query, renderer, limit, offset):
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    rows = db.execute(query.limit(limit).offset(offset)).mappings()
    return {"items": [renderer(row) for row in rows], "total": total, "limit": limit, "offset": offset}


def session_item(row, moment=None):
    return analytics.session_export_row(dict(row), moment or now())


def reservation_item(row):
    return analytics.reservation_export_row(dict(row))


def live(db, scope):
    """Estado atual de cada ponto, com sessão ativa e a última potência recebida.

    Ponto travado por um pedido do totem: ``occupied`` com ``kiosk_in_use`` ("Em uso no totem").
    """
    moment = now()
    points = db.execute(
        scope.stations(
            select(Connector, Station, Device)
            .select_from(Connector)
            .join(Station, Station.id == Connector.station_id)
            .outerjoin(Device, and_(Device.connector_id == Connector.id, Device.revoked.is_(False)))
            .order_by(Station.name, Connector.public_code)
        )
    ).all()
    ids = [point.id for point, _, _ in points]
    reservations, sessions, samples = {}, {}, {}
    if ids:
        for reservation in db.scalars(select(Reservation).where(
                Reservation.connector_id.in_(ids), Reservation.status.in_(RES_ACTIVE))):
            reservations[reservation.connector_id] = reservation
        for session in db.scalars(select(ChargingSession).where(
                ChargingSession.connector_id.in_(ids), ChargingSession.status.in_(SESSION_ACTIVE))):
            sessions[session.connector_id] = session
        if sessions:
            latest = db.execute(
                select(Telemetry.session_id, Telemetry.data, Telemetry.captured_at)
                .where(Telemetry.session_id.in_([s.id for s in sessions.values()]))
                .distinct(Telemetry.session_id)
                .order_by(Telemetry.session_id, Telemetry.captured_at.desc())
            ).all()
            samples = {row.session_id: row for row in latest}
        retired = set(db.scalars(
            select(Device.connector_id).join(Command, Command.device_id == Device.id).where(
                Device.connector_id.in_(ids), Command.type == "FACTORY_RESET", Command.status == "applied")
        ))
    else:
        retired = set()
    holds = kiosk_holds(db, ids)
    # Estação = a tela: carregadores adicionais dependem da tela-mãe (uma consulta).
    parents = {device.parent_device_id for _, _, device in points if device is not None and device.parent_device_id}
    screens = {item.id: item for item in db.scalars(
        select(Device).where(Device.id.in_(parents), Device.revoked.is_(False)))} if parents else {}
    resetting = resetting_screens(db, [device.id for _, _, device in points if device] + list(parents))
    items = []
    for point, station, device in points:
        session = sessions.get(point.id)
        reservation = reservations.get(point.id)
        screen = device if device is None or device.parent_device_id is None else screens.get(device.parent_device_id)
        state = live_status(point, station, device, reservation, session, moment, holds.get(point.id), screen,
                            resetting=screen is not None and screen.id in resetting)
        sample = samples.get(session.id) if session else None
        power = (sample.data or {}).get("power_w") if sample else None
        items.append({
            "connector_id": str(point.id), "station_id": str(station.id), "station_name": station.name,
            "station_active": station.active, "public_code": point.public_code,
            "connector_type": point.connector_type, "power_kw": str(point.power_kw),
            "price_per_kwh": str(point.price_per_kwh), "max_duration_minutes": point.max_duration_minutes,
            "active": point.active, "retired": point.id in retired,
            "has_device": device is not None, "device_id": str(device.id) if device else None,
            # "online" = o carregador responde; a estação (tela) vem em screen_online.
            "online": state.pop("_charger_online"), "last_seen": device.last_seen.isoformat()
            if device and device.last_seen else None,
            "firmware_version": device.firmware_version if device else None,
            "physical_state": device.physical_state if device else "unknown",
            **state,
            "session": {
                "id": str(session.id), "status": session.status,
                "started_at": session.started_at.isoformat() if session.started_at else None,
                "energy_wh": str(session.energy_wh), "cost_estimate": str(session.cost_estimate),
                "soc_percent": str(session.soc_percent) if session.soc_percent is not None else None,
                "soc_source": session.soc_source,
                "power_w": str(power) if power is not None else None,
                # Potência ao vivo: aplicada confirmada pelo equipamento, estado e motivo.
                "applied_power_kw": str(session.applied_power_kw) if session.applied_power_kw is not None else None,
                "power_state": session.power_state, "power_reason": session.power_reason,
                "source": session.source,
                "last_measurement_at": session.last_measurement_at.isoformat()
                if session.last_measurement_at else None,
            } if session else None,
        })
    # Permanência após a recarga: quem ocupa a vaga (primeiro nome + veículo) e a taxa até agora.
    occupancy = overstay.occupancy_by_connector(db, ids)
    for item in items:
        item["occupancy"] = occupancy.get(UUID(item["connector_id"]))
    return {"items": items, "generated_at": moment.isoformat()}


def _online(device, moment):
    return bool(device and device.last_seen and device.last_seen > moment - ONLINE_WINDOW)


def _hardware(connector, device, screen, moment):
    """Mesma regra de :func:`app.service.hardware_state` no instante ``moment``."""
    if not _online(screen, moment):
        return False, False, charger_link.SCREEN_OFFLINE
    if device is not screen and not _online(device, moment):
        return True, False, charger_link.CHARGER_OFFLINE
    reason = charger_link.availability_reason(connector.charger_address, device.charger, True)
    return True, reason is None, reason


def live_status(connector, station, device, reservation, session, moment, hold=None, screen=False, *, resetting=False):
    """Mesmas regras de :func:`app.service.availability`, sem consultas extras (``hold``: pedido do
    totem que trava o ponto, de ``service.kiosk_holds``; ``screen``: a tela que comanda o
    carregador — por padrão o próprio dispositivo)."""
    screen = device if screen is False else screen
    screen_online, charger_online, hardware = _hardware(connector, device, screen, moment)
    reserved_until = (
        reservation.expires_at
        if reservation and reservation.status == "confirmed" and reservation.expires_at
        and reservation.expires_at > moment
        else None
    )
    if not connector.active or not station or not station.active or station.owner_id is None:
        status = "disabled"
    elif not screen_online or not _online(device, moment):
        status = "offline"
    elif device.physical_state == "fault":
        status = "fault"
    elif resetting:
        status = "reconciling"
    elif session:
        status = ("charging" if session.status == "charging" and device.physical_state == "charging"
                  and device.reconciled else "reconciling")
    elif hardware is not None:
        status = "offline"  # só este carregador; a estação segue online
    elif reservation:
        status = ("reserved" if reserved_until and device.physical_state == "reserved" and device.reconciled
                  else "reconciling")
    elif hold is not None:
        status = "occupied"
    elif not device.reconciled:
        status = "reconciling"
    elif device.connected or device.physical_state not in ("idle", "stopped"):
        status = "occupied"
    else:
        status = "available"
    return {"available": status == "available", "availability_status": status,
            "reserved_until": reserved_until.isoformat() if reserved_until else None,
            "kiosk_in_use": hold is not None,
            "unavailable_reason": hardware if status == "offline" else None,
            "screen_online": screen_online, "_charger_online": charger_online}


def _alert_point(row, moment):
    """Ponto para os alertas: ``online`` = a TELA da estação; ``charger_offline`` = tela online e o
    carregador GoodWe deste ponto sem resposta (ou, num carregador adicional, sem sync pela tela)."""
    def alive(seen):
        return bool(seen and seen > moment - ONLINE_WINDOW)

    child = row["parent_device_id"] is not None
    screen_online = alive(row["screen_last_seen"]) if child else alive(row["last_seen"])
    charger_offline = screen_online and (
        (child and not alive(row["last_seen"]))
        or charger_link.availability_reason(row["charger_address"], row["charger"], True) is not None)
    return {**row, "online": screen_online, "charger_offline": charger_offline}


def alerts(db, scope):
    screen_device = aliased(Device)
    moment = now()
    failed_cmd = or_(
        Command.status == "failed",
        and_(Command.status.in_(("pending", "received")), Command.expires_at <= moment),
    )
    failures = (
        select(Device.connector_id.label("connector_id"), func.count(Command.id).label("failed"))
        .join(Command, Command.device_id == Device.id)
        .where(failed_cmd, Command.expires_at >= moment - timedelta(hours=24))
        .group_by(Device.connector_id)
        .subquery()
    )
    last_session = (
        select(ChargingSession.connector_id.label("connector_id"),
               func.max(ChargingSession.created_at).label("last_session_at"))
        .group_by(ChargingSession.connector_id)
        .subquery()
    )
    retired = (
        select(Device.connector_id.label("connector_id"))
        .join(Command, Command.device_id == Device.id)
        .where(Command.type == "FACTORY_RESET", Command.status == "applied")
        .distinct()
        .subquery()
    )
    rows = db.execute(
        scope.stations(
            select(
                Connector.id.label("connector_id"), Station.id.label("station_id"),
                Station.name.label("station_name"), Connector.public_code,
                and_(Connector.active.is_(True), Station.active.is_(True)).label("published"),
                (Device.id.is_not(None)).label("has_device"), Device.last_seen, Device.physical_state,
                Device.charger, Connector.charger_address, Device.parent_device_id,
                screen_device.last_seen.label("screen_last_seen"),
                func.coalesce(failures.c.failed, 0).label("failed_commands"),
                last_session.c.last_session_at,
                case((retired.c.connector_id.is_not(None), True), else_=False).label("retired"),
            )
            .select_from(Connector)
            .join(Station, Station.id == Connector.station_id)
            .outerjoin(Device, and_(Device.connector_id == Connector.id, Device.revoked.is_(False)))
            .outerjoin(screen_device, and_(screen_device.id == Device.parent_device_id, screen_device.revoked.is_(False)))
            .outerjoin(failures, failures.c.connector_id == Connector.id)
            .outerjoin(last_session, last_session.c.connector_id == Connector.id)
            .outerjoin(retired, retired.c.connector_id == Connector.id)
        )
    ).mappings()
    points = [_alert_point(row, moment) for row in rows]
    return {"items": analytics.build_alerts(points, moment), "generated_at": moment.isoformat()}
