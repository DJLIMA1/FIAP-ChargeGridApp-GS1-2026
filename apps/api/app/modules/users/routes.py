from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
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

router = APIRouter()

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
            func.coalesce(func.sum(ChargingSession.cost_estimate), 0),
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
