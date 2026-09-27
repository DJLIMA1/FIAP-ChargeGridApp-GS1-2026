from sqlalchemy import func, select

from .errors import fail
from .models import ChargingSession, Command, Connector, Device, Reservation, Station
from .service import (
    RES_ACTIVE,
    SESSION_ACTIVE,
    availability,
    device_for,
    online,
    owned,
    row,
)


def update(obj, data):
    for key, value in data.model_dump(exclude_unset=True).items():
        if value is None and key not in ("phone", "vehicle_description"):
            fail("null_not_allowed", "Campo não aceita null", 422)
        setattr(obj, key, value)


def point_row(db, connector):
    result = row(connector)
    device = device_for(db, connector)
    result.update(availability(db, connector, device=device))
    result.update(
        online=online(device),
        physical_state=device.physical_state if device else "unknown",
        retired=bool(db.scalar(
            select(Command.id).join(Device, Device.id == Command.device_id).where(
                Device.connector_id == connector.id,
                Command.type == "FACTORY_RESET",
                Command.status == "applied",
            ).limit(1)
        )),
    )
    return result


def station_row(db, station):
    result = row(station)
    result.pop("presence_secret", None)
    result["latitude"] = float(station.latitude)
    result["longitude"] = float(station.longitude)
    result["connectors"] = [
        point_row(db, point)
        for point in db.scalars(select(Connector).where(Connector.station_id == station.id))
    ]
    return result


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


def session_row(db, session):
    result = row(session)
    if result:
        connector = db.get(Connector, session.connector_id)
        result.update(point_context(db, connector))
        result["online"] = online(device_for(db, connector))
    return result


def page(db, query, limit, offset, renderer=row):
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.limit(limit).offset(offset)).all()
    return {"items": [renderer(x) for x in items], "total": total, "limit": limit, "offset": offset}


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
