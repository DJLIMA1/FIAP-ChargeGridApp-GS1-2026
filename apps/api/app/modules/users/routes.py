from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header
from sqlalchemy import func, select

from ...database import db_session
from ...http_helpers import update
from ...models import ChargingSession
from ...schemas import (
    ProfilePatch,
)
from ...security import current_user
from ...service import (
    row,
)
from ..driver.routes import get_profile, put_profile
from ..driver.schemas import DriverProfileInput
from ..kiosk_totem import account

router = APIRouter()


@router.get("/me/vehicle")
def my_vehicle(user=Depends(current_user), db=Depends(db_session)):
    # Vehicle registration survives the discontinued driver planner.
    return get_profile(user, db)


@router.put("/me/vehicle")
def save_my_vehicle(data: DriverProfileInput, user=Depends(current_user), db=Depends(db_session)):
    return put_profile(data, user, db)


@router.get("/me/wallet")
def my_wallet(user=Depends(current_user), db=Depends(db_session)):
    return account.wallet_view(account.wallet(db, user))


@router.post("/me/wallet/simulate")
def simulated_wallet(data: account.WalletMove, idempotency_key: str = Header(default=""),
                     user=Depends(current_user), db=Depends(db_session)):
    return account.simulate_move(db, user, data, idempotency_key)

REPORTING_TIMEZONE = ZoneInfo("America/Sao_Paulo")


def monthly_bounds(reference: datetime | None = None):
    local = (reference or datetime.now(timezone.utc)).astimezone(REPORTING_TIMEZONE)
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start.strftime("%Y-%m"), start.astimezone(timezone.utc), end.astimezone(timezone.utc)


@router.get("/me")
def me(user=Depends(current_user)):
    return row(user)


@router.get("/me/summary")
def me_summary(user=Depends(current_user), db=Depends(db_session)):
    month, start, end = monthly_bounds()
    sessions_count, energy_wh, estimated_cost = db.execute(
        select(
            func.count(ChargingSession.id),
            func.coalesce(func.sum(ChargingSession.energy_wh), 0),
            # Ao centavo por sessão (mesma regra do histórico e do recibo), depois somado.
            func.coalesce(func.sum(func.round(ChargingSession.cost_estimate, 2)), 0),
        ).where(
            ChargingSession.user_id == user.id,
            ChargingSession.status.in_(("completed", "interrupted")),
            ChargingSession.energy_wh > 0,
            ChargingSession.ended_at >= start,
            ChargingSession.ended_at < end,
        )
    ).one()
    return {
        "month": month,
        "currency": "BRL",
        "estimated_cost": format(Decimal(estimated_cost), ".4f"),
        "energy_wh": format(Decimal(energy_wh), ".3f"),
        "sessions_count": sessions_count,
    }


@router.patch("/me")
def patch_me(data: ProfilePatch, user=Depends(current_user), db=Depends(db_session)):
    update(user, data)
    db.flush()
    return row(user)
