from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from ...database import db_session
from ...errors import fail
from ...http_helpers import page, update
from ...models import ChargingSession, Connector, Coupon, Station, now
from ...schemas import (
    CouponCheckInput,
    CouponInput,
    CouponPatch,
)
from ...security import current_user
from ...service import (
    operator,
    owned,
    row,
)
from ..auth.routes import limit
from ..charging.service import find_coupon

router = APIRouter()


def normalize_code(value):
    return value.strip().upper()


def usage(db, owner_id, codes):
    """Uso dos cupons do dono: recargas iniciadas com o código, a última e o desconto aproximado.

    Casa pelo código (único, sem diferenciar maiúsculas) gravado em ``price_terms.coupon``: o
    pré-pago Stripe grava o cupom sem ``id``. Só conta postos do dono e ignora recargas que
    falharam. O desconto é ``kWh × preço × %``, sem o arredondamento do recibo (aproximado).
    """
    if not codes:
        return {}
    code = func.upper(ChargingSession.price_terms["coupon"]["code"].astext)
    discount = func.sum(ChargingSession.energy_wh / 1000 * ChargingSession.price_per_kwh
                        * ChargingSession.discount_percent / 100)
    rows = db.execute(
        select(code, func.count(ChargingSession.id), func.max(ChargingSession.created_at), discount)
        .join(Connector, Connector.id == ChargingSession.connector_id)
        .join(Station, Station.id == Connector.station_id)
        .where(Station.owner_id == owner_id, ChargingSession.status != "failed", code.in_(codes))
        .group_by(code)
    ).all()
    return {key: (uses, last, Decimal(total or 0).quantize(Decimal("0.01"))) for key, uses, last, total in rows}


def with_usage(db, owner_id):
    def render(items):
        found = usage(db, owner_id, [item.code.upper() for item in items])
        result = []
        for item in items:
            uses, last, total = found.get(item.code.upper(), (0, None, Decimal("0.00")))
            result.append({**row(item), "uses": uses, "last_used_at": last.isoformat() if last else None,
                           "discount_total_approx": str(total)})
        return result
    return render


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
        if not station or station.removed_at is not None:
            fail("not_found", "Posto não encontrado", 404)
        query = query.where(
            Coupon.operator_id == station.owner_id,
            (Coupon.station_id == station_id) | Coupon.station_id.is_(None),
        )
    # Gestão (``mine``): cada cupom traz o uso (``uses``, ``last_used_at``, ``discount_total_approx``).
    return page(db, query.order_by(Coupon.id), limit, offset, many=with_usage(db, user.id) if mine else None)


# Tentativas de código por motorista: adivinhar cupons por força bruta fica inviável.
CHECK_LIMIT, CHECK_WINDOW_SECONDS = 10, 300


@router.post("/coupons/check")
def check_coupon(data: CouponCheckInput, user=Depends(current_user), db=Depends(db_session)):
    """Confere o código para o ponto escolhido sem pagar nem iniciar (a mesma regra do início).

    Devolve só o que o motorista precisa ver; 422 ``invalid_coupon`` quando não vale aqui.
    O desconto continua sendo aplicado e travado pela API no pagamento ou no início."""
    limit(db, f"coupon-check:{user.id}", maximum=CHECK_LIMIT, seconds=CHECK_WINDOW_SECONDS)
    connector = db.get(Connector, data.connector_id)
    station = db.get(Station, connector.station_id) if connector else None
    if not connector or connector.removed_at or not connector.active or not station or not station.active:
        fail("not_found", "Ponto não encontrado", 404)
    coupon = find_coupon(db, connector, data.code)
    return {"code": coupon.code, "discount_percent": int(coupon.discount_percent),
            "description": coupon.description, "valid_until": coupon.valid_until.isoformat(),
            "station_id": str(coupon.station_id) if coupon.station_id else None}


@router.post("/coupons", status_code=201)
def create_coupon(data: CouponInput, user=Depends(current_user), db=Depends(db_session)):
    operator(user)
    if data.valid_until.tzinfo is None:
        fail("invalid_time", "Informe fuso horário", 422)
    if data.valid_until <= now():
        fail("invalid_time", "A validade do cupom deve estar no futuro", 422)
    if data.station_id:
        owned(db, user, data.station_id)
    # Drivers type codes by hand: store one canonical case and reject codes that
    # differ only by case, which would otherwise be ambiguous at checkout.
    code = normalize_code(data.code)
    if db.scalar(select(Coupon.id).where(func.upper(Coupon.code) == code).limit(1)):
        fail("coupon_exists", "Já existe um cupom com este código. Escolha outro.", 409)
    obj = Coupon(operator_id=user.id, **{**data.model_dump(), "code": code})
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
    if data.valid_until is not None and data.valid_until <= now():
        fail("invalid_time", "A validade do cupom deve estar no futuro", 422)
    if data.active is True and not obj.active and (data.valid_until or obj.valid_until) <= now():
        fail("invalid_time", "Atualize a validade antes de reativar o cupom", 422)
    update(obj, data)
    return row(obj)
