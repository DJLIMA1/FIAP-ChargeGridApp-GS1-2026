from datetime import timedelta

from ...errors import fail
from ...models import Reservation, now
from ...service import device_for, ensure_user_free, free, idempotent, issue, lock_point, remember


def reserve(db, user, data, key):
    connector = lock_point(db, user, data.connector_id)
    old, body_hash = idempotent(db, user, "reserve", key, data.model_dump(), Reservation)
    if old:
        return old
    ensure_user_free(db, user)
    if not free(db, connector):
        fail("point_unavailable", "Ponto indisponível")
    reservation = Reservation(
        user_id=user.id, connector_id=connector.id, confirmation_deadline=now() + timedelta(seconds=30)
    )
    db.add(reservation)
    db.flush()
    issue(
        db,
        connector,
        device_for(db, connector),
        "RESERVE",
        reservation=reservation,
        parameters={"expires_at": (now() + timedelta(minutes=10)).isoformat()},
    )
    remember(db, user, "reserve", key, body_hash, reservation)
    return reservation
