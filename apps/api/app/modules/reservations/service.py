from datetime import timedelta

from ...models import Reservation, now
from ...service import (
    RESERVATION_MINUTES,
    availability,
    device_for,
    ensure_user_free,
    fail_unavailable,
    idempotent,
    issue,
    lock_point,
    remember,
)
from ..pricing.service import reservation_terms


def reserve(db, user, data, key):
    connector = lock_point(db, user, data.connector_id)
    old, body_hash = idempotent(db, user, "reserve", key, data.model_dump(), Reservation)
    if old:
        return old
    ensure_user_free(db, user)
    state = availability(db, connector)
    if not state["available"]:
        fail_unavailable(state)
    # Tarifa dinâmica travada ao reservar: a recarga desta reserva paga este multiplicador;
    # ``price_terms`` guarda o motivo (demanda e horário) para o recibo.
    multiplier, terms = reservation_terms(db, connector)
    reservation = Reservation(
        user_id=user.id, connector_id=connector.id, confirmation_deadline=now() + timedelta(seconds=30),
        demand_multiplier=multiplier, price_terms=terms,
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
