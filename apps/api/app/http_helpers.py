from sqlalchemy import func, select

from .errors import fail
from .models import ChargingSession, Connector, Device, Reservation
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
    )
    return result


def station_row(db, station):
    result = row(station)
    result["latitude"] = float(station.latitude)
    result["longitude"] = float(station.longitude)
    result["connectors"] = [
        point_row(db, point)
        for point in db.scalars(select(Connector).where(Connector.station_id == station.id))
    ]
    return result


def session_row(db, session):
    result = row(session)
    if result:
        result["online"] = online(device_for(db, db.get(Connector, session.connector_id)))
    return result


def page(db, query, limit, offset, renderer=row):
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.limit(limit).offset(offset)).all()
    return {"items": [renderer(x) for x in items], "total": total, "limit": limit, "offset": offset}


def own_device(db, user, device_id):
    obj = db.get(Device, device_id)
    if not obj:
        fail("not_found", "Dispositivo não encontrado", 404)
    point = db.scalar(select(Connector).where(Connector.id == obj.connector_id).with_for_update())
    owned(db, user, point.station_id)
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
