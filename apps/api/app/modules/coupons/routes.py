from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from ...database import db_session
from ...errors import fail
from ...http_helpers import page, update
from ...models import Coupon, Station, now
from ...schemas import (
    CouponInput,
    CouponPatch,
)
from ...security import current_user
from ...service import (
    operator,
    owned,
    row,
)

router = APIRouter()


@router.get("/coupons")
def coupons(
    station_id: UUID | None = None,
    mine: bool = False,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user=Depends(current_user),
    db=Depends(db_session),
):
    query = select(Coupon)
    if mine:
        operator(user)
        query = query.where(Coupon.operator_id == user.id)
    else:
        query = query.where(Coupon.active.is_(True), Coupon.valid_until > now())
    if station_id:
        station = db.get(Station, station_id)
        if not station:
            fail("not_found", "Posto não encontrado", 404)
        query = query.where(
            Coupon.operator_id == station.owner_id,
            (Coupon.station_id == station_id) | Coupon.station_id.is_(None),
        )
    return page(db, query.order_by(Coupon.id), limit, offset)


@router.post("/coupons", status_code=201)
def create_coupon(data: CouponInput, user=Depends(current_user), db=Depends(db_session)):
    operator(user)
    if data.valid_until.tzinfo is None:
        fail("invalid_time", "Informe fuso horário", 422)
    if data.station_id:
        owned(db, user, data.station_id)
    obj = Coupon(operator_id=user.id, **data.model_dump())
    db.add(obj)
    db.flush()
    return row(obj)


@router.patch("/coupons/{coupon_id}")
def patch_coupon(coupon_id: UUID, data: CouponPatch, user=Depends(current_user), db=Depends(db_session)):
    operator(user)
    obj = db.get(Coupon, coupon_id)
    if not obj or obj.operator_id != user.id:
        fail("not_found", "Cupom não encontrado", 404)
    if data.valid_until and data.valid_until.tzinfo is None:
        fail("invalid_time", "Informe fuso horário", 422)
    update(obj, data)
    return row(obj)
