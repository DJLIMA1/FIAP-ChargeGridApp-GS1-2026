from decimal import Decimal

from sqlalchemy import func, select

from chargegrid_core import power as power_rules
from chargegrid_core import pricing

from .errors import fail
from .models import ChargingSession, Command, Connector, Device, Reservation, Station
from .service import (
    RES_ACTIVE,
    SESSION_ACTIVE,
    availability,
    online,
    owned,
    row,
)


def update(obj, data):
    for key, value in data.model_dump(exclude_unset=True).items():
        if value is None and key not in ("phone", "vehicle_description", "max_power_kw", "power_limit_kw"):
            fail("null_not_allowed", "Campo não aceita null", 422)
        setattr(obj, key, value)


def _retired_ids(db, connector_ids):
    if not connector_ids:
        return set()
    return set(db.scalars(
        select(Device.connector_id).select_from(Command).join(Device, Device.id == Command.device_id).where(
            Device.connector_id.in_(connector_ids),
            Command.type == "FACTORY_RESET",
            Command.status == "applied",
        ).distinct()
    ))


retired_ids = _retired_ids


def _point_state(db, connectors):
    """Load every row that availability needs for many points in four queries."""
    ids = [point.id for point in connectors]
    if not ids:
        return {}, {}, {}, set()
    devices = {
        device.connector_id: device
        for device in db.scalars(select(Device).where(Device.connector_id.in_(ids), Device.revoked.is_(False)))
    }
    reservations = {
        item.connector_id: item
        for item in db.scalars(
            select(Reservation).where(Reservation.connector_id.in_(ids), Reservation.status.in_(RES_ACTIVE))
        )
    }
    sessions = {
        item.connector_id: item
        for item in db.scalars(
            select(ChargingSession).where(
                ChargingSession.connector_id.in_(ids), ChargingSession.status.in_(SESSION_ACTIVE)
            )
        )
    }
    return devices, reservations, sessions, _retired_ids(db, ids)


KW = Decimal("0.001")


def _kw(value):
    return None if value is None else str(Decimal(value).quantize(KW))


def allocation(station, connectors, retired):
    """Effective power of every point of one station (``chargegrid_core.power``)."""
    return power_rules.allocate(
        [
            {
                "id": point.id,
                "power_kw": point.power_kw,
                "power_limit_kw": point.power_limit_kw,
                "participates": bool(point.active) and point.id not in retired,
            }
            for point in connectors
        ],
        station.max_power_kw if station is not None else None,
    )


def energy_totals(db, connector_ids):
    """kWh delivered per point (all its sessions) in one grouped query."""
    if not connector_ids:
        return {}
    rows = db.execute(
        select(ChargingSession.connector_id, func.coalesce(func.sum(ChargingSession.energy_wh), 0))
        .where(ChargingSession.connector_id.in_(connector_ids))
        .group_by(ChargingSession.connector_id)
    ).all()
    return {connector_id: Decimal(total) / 1000 for connector_id, total in rows}


def _render_point(db, connector, station, devices, reservations, sessions, retired, power=None, energy=None):
    result = row(connector)
    device = devices.get(connector.id)
    result.update(availability(
        db, connector, device=device, station=station,
        reservation=reservations.get(connector.id), session=sessions.get(connector.id),
    ))
    result.update(
        online=online(device),
        physical_state=device.physical_state if device else "unknown",
        retired=connector.id in retired,
    )
    allocated = (power or {}).get(connector.id)
    if allocated:
        result.update(
            effective_power_kw=_kw(allocated["effective_kw"]),
            power_limited=allocated["power_limited"],
            power_limited_by=allocated["limited_by"],
        )
    if energy is not None:
        # Owner-only: total energy delivered by this point.
        result["energy_kwh_total"] = _kw(energy.get(connector.id, Decimal(0)))
    return result


def _owner_view(station, viewer):
    return viewer is not None and station is not None and station.owner_id == getattr(viewer, "id", None)


def point_row(db, connector, viewer=None):
    station = db.get(Station, connector.station_id)
    siblings = db.scalars(select(Connector).where(Connector.station_id == connector.station_id)).all()
    retired = _retired_ids(db, [point.id for point in siblings])
    power = allocation(station, siblings, retired)["connectors"]
    energy = energy_totals(db, [connector.id]) if _owner_view(station, viewer) else None
    devices, reservations, sessions, _ = _point_state(db, [connector])
    return _render_point(db, connector, station, devices, reservations, sessions, retired, power, energy)


def station_rows(db, stations, viewer=None):
    """Serialize stations with a constant number of queries, not per point (N+1).

    ``viewer``: the owner also gets ``energy_kwh_total`` per point.
    """
    stations = list(stations)
    if not stations:
        return []
    connectors = db.scalars(
        select(Connector).where(Connector.station_id.in_([station.id for station in stations]))
    ).all()
    state = _point_state(db, connectors)
    retired = state[3]
    owned_stations = {station.id for station in stations if _owner_view(station, viewer)}
    energy = energy_totals(db, [point.id for point in connectors if point.station_id in owned_stations])
    by_station = {}
    for point in connectors:
        by_station.setdefault(point.station_id, []).append(point)
    from .modules.pricing.service import demand_by_station  # evita import circular

    demand = demand_by_station(db, stations, by_station, state)
    results = []
    for station in stations:
        result = row(station)
        result.pop("presence_secret", None)
        result.pop("pricing", None)  # dados base do dono: GET /stations/{id}/pricing
        status = demand[station.id]
        result["demand"] = {key: status[key] for key in ("multiplier", "level", "level_label", "increase_percent")}
        result["latitude"] = float(station.latitude)
        result["longitude"] = float(station.longitude)
        points = by_station.get(station.id, [])
        power = allocation(station, points, retired)
        result["allocated_power_kw"] = _kw(power["allocated_kw"])
        result["requested_power_kw"] = _kw(power["requested_kw"])
        result["power_shared"] = power["shared"]
        station_energy = energy if _owner_view(station, viewer) else None
        result["connectors"] = [
            _render_point(db, point, station, *state, power["connectors"], station_energy) for point in points
        ]
        for point in result["connectors"]:
            # Preço que o motorista paga agora (base × demanda); travado ao reservar ou iniciar.
            point["dynamic_price_per_kwh"] = str(pricing.dynamic_price(point["price_per_kwh"], status["multiplier"]))
        results.append(result)
    return results


def station_row(db, station, viewer=None):
    return station_rows(db, [station], viewer)[0]


def point_context(db, connector):
    station = db.get(Station, connector.station_id)
    public_fields = ("id", "public_code", "connector_type", "power_kw", "price_per_kwh", "max_duration_minutes")
    serialized = row(connector)
    return {
        "station_id": str(station.id),
        "station_name": station.name,
        "station_address": station.address,
        "connector": {key: serialized[key] for key in public_fields},
    }


def reservation_row(db, reservation):
    result = row(reservation)
    if result:
        result.update(point_context(db, db.get(Connector, reservation.connector_id)))
        multiplier = reservation.demand_multiplier
        if multiplier is not None and Decimal(multiplier) != 1:
            # O ponto da reserva mostra o preço travado ao reservar (base × multiplicador).
            connector = result["connector"]
            connector["base_price_per_kwh"] = connector["price_per_kwh"]
            connector["price_per_kwh"] = str(pricing.dynamic_price(connector["price_per_kwh"], multiplier))
    return result


def session_rows(db, sessions):
    """History pages: preload points, stations and devices instead of N+1 lookups."""
    sessions = list(sessions)
    connector_ids = {session.connector_id for session in sessions}
    devices = {}
    # Strong references keep these rows in the (weak) identity map, so the
    # db.get() calls in point_context below are served from memory.
    loaded = []
    if connector_ids:
        connectors = db.scalars(select(Connector).where(Connector.id.in_(connector_ids))).all()
        station_ids = {point.station_id for point in connectors}
        loaded = [*connectors, *db.scalars(select(Station).where(Station.id.in_(station_ids))).all()]
        devices = {
            device.connector_id: device
            for device in db.scalars(
                select(Device).where(Device.connector_id.in_(connector_ids), Device.revoked.is_(False))
            )
        }
    results = []
    for session in sessions:
        result = row(session)
        connector = db.get(Connector, session.connector_id)
        result.update(point_context(db, connector))
        result["online"] = online(devices.get(connector.id))
        results.append(result)
    del loaded
    return results


def session_row(db, session):
    if session is None:
        return None
    return session_rows(db, [session])[0]


def page(db, query, limit, offset, renderer=row, *, many=None):
    """Paginate; ``many`` renders the whole page at once to avoid N+1 queries."""
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.limit(limit).offset(offset)).all()
    rendered = many(items) if many else [renderer(x) for x in items]
    return {"items": rendered, "total": total, "limit": limit, "offset": offset}


def own_device(db, user, device_id, *, require_idle=True):
    obj = db.get(Device, device_id)
    if not obj:
        fail("not_found", "Dispositivo não encontrado", 404)
    query = select(Connector).where(Connector.id == obj.connector_id)
    point = db.scalar(query.with_for_update() if require_idle else query)
    owned(db, user, point.station_id)
    if not require_idle:
        return obj
    db.refresh(obj)
    if db.scalar(
        select(ChargingSession.id).where(
            ChargingSession.connector_id == point.id, ChargingSession.status.in_(SESSION_ACTIVE)
        )
    ) or db.scalar(
        select(Reservation.id).where(Reservation.connector_id == point.id, Reservation.status.in_(RES_ACTIVE))
    ):
        fail("point_busy", "Encerre reservas/recargas antes de mudar credencial")
    return obj
