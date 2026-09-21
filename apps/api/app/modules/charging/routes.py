from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import func, select

from ...database import db_session
from ...errors import fail
from ...http_helpers import page, session_row
from ...models import ChargingSession, Connector, Station
from ...schemas import (
    StartInput,
)
from ...security import current_user
from ...service import (
    SESSION_ACTIVE,
    lock_point,
    operator,
    owned,
)
from .service import start, stop

router = APIRouter()


@router.post("/charging-sessions", status_code=202)
def create_session(
    data: StartInput,
    idempotency_key: str = Header(default=""),
    user=Depends(current_user),
    db=Depends(db_session),
):
    return session_row(db, start(db, user, data, idempotency_key))


@router.get("/charging-sessions/current")
def current_session(user=Depends(current_user), db=Depends(db_session)):
    obj = db.scalar(
        select(ChargingSession).where(
            ChargingSession.user_id == user.id, ChargingSession.status.in_(SESSION_ACTIVE)
        )
    )
    if obj:
        lock_point(db, user, obj.connector_id)
    return session_row(db, obj)


@router.get("/charging-sessions/{session_id}")
def get_session(session_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    obj = db.get(ChargingSession, session_id)
    if not obj or obj.user_id != user.id:
        fail("not_found", "Sessão não encontrada", 404)
    return session_row(db, obj)


@router.post("/charging-sessions/{session_id}/stop", status_code=202)
def stop_session(
    session_id: UUID,
    idempotency_key: str = Header(default=""),
    user=Depends(current_user),
    db=Depends(db_session),
):
    return session_row(db, stop(db, user, session_id, idempotency_key))


@router.get("/me/charging-sessions")
def history(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user=Depends(current_user),
    db=Depends(db_session),
):
    return page(
        db,
        select(ChargingSession)
        .where(ChargingSession.user_id == user.id)
        .order_by(ChargingSession.created_at.desc(), ChargingSession.id.desc()),
        limit,
        offset,
        lambda obj: session_row(db, obj),
    )


@router.get("/stations/{station_id}/charging-sessions")
def station_history(
    station_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user=Depends(current_user),
    db=Depends(db_session),
):
    owned(db, user, station_id)
    query = (
        select(ChargingSession)
        .join(Connector)
        .where(Connector.station_id == station_id)
        .order_by(ChargingSession.created_at.desc(), ChargingSession.id.desc())
    )
    return page(db, query, limit, offset, lambda obj: session_row(db, obj))


@router.get("/operator/summary")
def summary(user=Depends(current_user), db=Depends(db_session)):
    operator(user)
    sessions = db.scalars(
        select(ChargingSession).join(Connector).join(Station).where(Station.owner_id == user.id)
    ).all()
    return {
        "stations": db.scalar(select(func.count()).select_from(Station).where(Station.owner_id == user.id)),
        "total_sessions": len(sessions),
        "total_energy_wh": str(sum(x.energy_wh for x in sessions)),
        "total_estimated_cost": str(sum(x.cost_estimate for x in sessions)),
    }
