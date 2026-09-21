from sqlalchemy import select

from ...errors import fail
from ...models import ChargingSession, Connector, Coupon, Station, now
from ...service import (
    SESSION_ACTIVE,
    active_res,
    device_for,
    ensure_user_free,
    free,
    idempotent,
    issue,
    lock_point,
    online,
    remember,
)


def start(db, user, data, key):
    point = db.scalar(select(Connector).where(Connector.public_code == data.public_code))
    if not point:
        fail("not_found", "Código não encontrado", 404)
    connector = lock_point(db, user, point.id)
    old, body_hash = idempotent(db, user, "start", key, data.model_dump(), ChargingSession)
    if old:
        return old
    ensure_user_free(db, user, data.reservation_id)
    device = device_for(db, connector)
    reservation = active_res(db, connector.id)
    if data.reservation_id:
        if (
            not reservation
            or reservation.id != data.reservation_id
            or reservation.user_id != user.id
            or reservation.status != "confirmed"
        ):
            fail("invalid_reservation", "Reserva inválida")
        if (
            not connector.active
            or not db.get(Station, connector.station_id).active
            or not online(device)
            or not device.reconciled
            or device.physical_state != "reserved"
        ):
            fail("point_unavailable", "Ponto sem confirmação recente")
    elif not free(db, connector):
        fail("point_unavailable", "Ponto indisponível")
    if data.max_duration_minutes > connector.max_duration_minutes:
        fail("duration_limit", "Duração acima do limite do ponto", 422)
    discount = 0
    if data.coupon_code:
        coupon = db.scalar(
            select(Coupon).where(
                Coupon.code == data.coupon_code, Coupon.active.is_(True), Coupon.valid_until > now()
            )
        )
        station = db.get(Station, connector.station_id)
        if (
            not coupon
            or coupon.operator_id != station.owner_id
            or (coupon.station_id and coupon.station_id != station.id)
        ):
            fail("invalid_coupon", "Cupom inválido", 422)
        discount = coupon.discount_percent
    if reservation:
        reservation.status = "consumed"
    session = ChargingSession(
        user_id=user.id,
        connector_id=connector.id,
        reservation_id=reservation.id if reservation else None,
        max_duration_minutes=data.max_duration_minutes,
        max_cost=data.max_cost,
        price_per_kwh=connector.price_per_kwh,
        discount_percent=discount,
    )
    db.add(session)
    db.flush()
    limits = {
        "session_id": str(session.id),
        "max_duration_minutes": session.max_duration_minutes,
        "max_cost": str(session.max_cost) if session.max_cost else None,
        "price_per_kwh": str(session.price_per_kwh),
        "discount_percent": discount,
    }
    issue(db, connector, device, "START", session=session, parameters=limits)
    remember(db, user, "start", key, body_hash, session)
    return session


def stop(db, user, session_id, key):
    session = db.get(ChargingSession, session_id)
    if not session or session.user_id != user.id:
        fail("not_found", "Sessão não encontrada", 404)
    connector = lock_point(db, user, session.connector_id)
    db.refresh(session)
    old, body_hash = idempotent(db, user, "stop:" + str(session_id), key, {}, ChargingSession)
    if old:
        return old
    if session.status in SESSION_ACTIVE and session.status != "stopping":
        session.status = "stopping"
        issue(db, connector, device_for(db, connector), "STOP", session=session)
    remember(db, user, "stop:" + str(session_id), key, body_hash, session)
    return session
