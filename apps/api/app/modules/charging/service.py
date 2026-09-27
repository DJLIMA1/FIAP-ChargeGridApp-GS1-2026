from sqlalchemy import select

from ...errors import fail
from ...models import ChargingSession, Connector, Coupon, Profile, Reservation, Station, now
from ...presence_code import valid_code
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


def _point_for_code(db, user, data):
    if data.public_code:
        point = db.scalar(select(Connector).where(Connector.public_code == data.public_code))
        if not point:
            fail("not_found", "Ponto não encontrado", 404)
        return point
    if data.reservation_id:
        reservation = db.get(Reservation, data.reservation_id)
        if not reservation or reservation.user_id != user.id:
            fail("invalid_reservation", "Reserva inválida")
        return db.get(Connector, reservation.connector_id)
    points = db.execute(
        select(Connector, Station).join(Station).where(
            Connector.active.is_(True), Station.active.is_(True), Station.owner_id.is_not(None)
        )
    ).all()
    checked_at = now()
    matching = [point for point, station in points if valid_code(station, data.presence_code, checked_at)]
    if not matching:
        fail("invalid_presence_code", "Código do posto inválido ou expirado", 422)
    # Availability cannot disambiguate locations: that could start a different
    # station from the one whose physical display the user is reading.
    if len({point.station_id for point in matching}) > 1:
        fail("ambiguous_presence_code", "Há mais de um posto com este código. Escolha o ponto na lista antes de iniciar.", 422)
    if len(matching) == 1:
        return matching[0]
    available = [point for point in matching if free(db, point)]
    if len(available) == 1:
        return available[0]
    fail("ambiguous_presence_code", "Há mais de um ponto com este código. Escolha o ponto na lista antes de iniciar.", 422)


def start(db, user, data, key):
    # Serialize this user's requests before looking up a rotating code. A retry
    # must recover the accepted session even after expiry or availability changes.
    db.execute(select(Profile).where(Profile.id == user.id).with_for_update()).scalar_one()
    old, body_hash = idempotent(db, user, "start", key, data.model_dump(), ChargingSession)
    if old:
        lock_point(db, user, old.connector_id)
        db.refresh(old)
        return old
    point = _point_for_code(db, user, data)
    connector = lock_point(db, user, point.id)
    if not valid_code(db.get(Station, connector.station_id), data.presence_code):
        fail("invalid_presence_code", "Código do posto inválido ou expirado", 422)
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
