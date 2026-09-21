from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy import select

from ...database import db_session
from ...errors import fail
from ...models import Reservation
from ...schemas import (
    ReserveInput,
)
from ...security import current_user
from ...service import (
    RES_ACTIVE,
    device_for,
    issue,
    lock_point,
    row,
)
from .service import reserve

router = APIRouter()


@router.post("/reservations", status_code=202)
def create_reservation(
    data: ReserveInput,
    idempotency_key: str = Header(default=""),
    user=Depends(current_user),
    db=Depends(db_session),
):
    return row(reserve(db, user, data, idempotency_key))


@router.get("/reservations/current")
def current_reservation(user=Depends(current_user), db=Depends(db_session)):
    obj = db.scalar(
        select(Reservation).where(Reservation.user_id == user.id, Reservation.status.in_(RES_ACTIVE))
    )
    if obj:
        lock_point(db, user, obj.connector_id)
    return row(obj)


@router.post("/reservations/{reservation_id}/cancel", status_code=202)
def cancel(reservation_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    obj = db.get(Reservation, reservation_id)
    if not obj or obj.user_id != user.id:
        fail("not_found", "Reserva não encontrada", 404)
    connector = lock_point(db, user, obj.connector_id)
    db.refresh(obj)
    if obj.status in ("pending_device", "confirmed"):
        obj.status = "cancelling"
        issue(db, connector, device_for(db, connector), "RELEASE", reservation=obj)
    return row(obj)
