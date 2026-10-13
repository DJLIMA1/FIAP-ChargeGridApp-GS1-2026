from sqlalchemy import func, select

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
        if value is None and key not in ("phone", "vehicle_description"):
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


def _render_point(db, connector, station, devices, reservations, sessions, retired):
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
    return result


def point_row(db, connector):
    station = db.get(Station, connector.station_id)
    return _render_point(db, connector, station, *_point_state(db, [connector]))


def station_rows(db, stations):
    """Serialize stations with a constant number of queries, not per point (N+1)."""
    stations = list(stations)
    if not stations:
        return []
    connectors = db.scalars(
        select(Connector).where(Connector.station_id.in_([station.id for station in stations]))
    ).all()
    state = _point_state(db, connectors)
    by_station = {}
    for point in connectors:
        by_station.setdefault(point.station_id, []).append(point)
    results = []
    for station in stations:
        result = row(station)
        result.pop("presence_secret", None)
        result["latitude"] = float(station.latitude)
        result["longitude"] = float(station.longitude)
        result["connectors"] = [
            _render_point(db, point, station, *state) for point in by_station.get(station.id, [])
        ]
        results.append(result)
    return results


def station_row(db, station):
    return station_rows(db, [station])[0]


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
