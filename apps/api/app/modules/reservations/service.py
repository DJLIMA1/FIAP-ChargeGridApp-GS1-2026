from datetime import timedelta

from ...errors import fail
from ...models import Reservation, now
from ...service import (
    RESERVATION_MINUTES,
    device_for,
    ensure_user_free,
    free,
    idempotent,
    issue,
    lock_point,
    remember,
)
from ..pricing.service import current_multiplier


def reserve(db, user, data, key):
    connector = lock_point(db, user, data.connector_id)
    old, body_hash = idempotent(db, user, "reserve", key, data.model_dump(), Reservation)
    if old:
        return old
    ensure_user_free(db, user)
    if not free(db, connector):
        fail("point_unavailable", "Ponto indisponível")
    reservation = Reservation(
        user_id=user.id, connector_id=connector.id, confirmation_deadline=now() + timedelta(seconds=30),
        # Tarifa dinâmica travada ao reservar: a recarga desta reserva paga este multiplicador.
        demand_multiplier=current_multiplier(db, connector),
    )
    db.add(reservation)
    db.flush()
    issue(
        db,
        connector,
        device_for(db, connector),
        "RESERVE",
        reservation=reservation,
        parameters={"expires_at": (now() + timedelta(minutes=RESERVATION_MINUTES)).isoformat()},
    )
    remember(db, user, "reserve", key, body_hash, reservation)
    return reservation
