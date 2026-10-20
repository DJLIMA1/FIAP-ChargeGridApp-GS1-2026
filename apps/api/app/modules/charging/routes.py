from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import func, select

from ... import overstay
from ...database import db_session
from ...errors import fail
from ...http_helpers import page, session_row, session_rows
from ...models import ChargingSession, Connector, SessionEvent, Station
from ...schemas import (
    SocInput,
    StartInput,
)
from ...security import current_user
from ...service import (
    SESSION_ACTIVE,
    lock_point,
    operator,
    owned,
)
from ..auth.routes import limit
from .service import report_soc, start, stop

router = APIRouter()


@router.post("/charging-sessions", status_code=202)
def create_session(
    data: StartInput,
    idempotency_key: str = Header(default=""),
    user=Depends(current_user),
    db=Depends(db_session),
):
    limit(db, f"presence:{user.id}", maximum=10, seconds=300)
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
        db.flush()
        db.refresh(obj)
        if obj.status not in SESSION_ACTIVE:
            return None
    return session_row(db, obj)


@router.get("/overstays/current")
def current_overstay(user=Depends(current_user), db=Depends(db_session)):
    """Permanência aberta da pessoa (recarga encerrada e cabo ainda conectado), ou null."""
    obj = overstay.current_for_user(db, user)
    if obj is None:
        return None
    lock_point(db, user, obj.connector_id)  # fecha a permanência sem notícia do equipamento
    db.flush()
    db.refresh(obj)
    if not overstay.is_open(obj):
        return None
    context = session_row(db, obj)
    return {key: context[key] for key in ("station_id", "station_name", "station_address", "connector")} | {
        "session_id": str(obj.id), "ended_at": context["ended_at"], **context["overstay"]}


@router.get("/charging-sessions/{session_id}")
def get_session(session_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    obj = db.get(ChargingSession, session_id)
    if not obj or obj.user_id != user.id:
        fail("not_found", "Sessão não encontrada", 404)
    return session_row(db, obj)


@router.get("/charging-sessions/{session_id}/events")
def session_events(session_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    session = db.get(ChargingSession, session_id)
    if not session or session.user_id != user.id:
        fail("not_found", "Sessão não encontrada", 404)
    events = db.scalars(
        select(SessionEvent).where(SessionEvent.session_id == session_id).order_by(SessionEvent.id)
    ).all()
    return [
        {"kind": event.kind, "source": event.source, "observed_at": event.observed_at}
        for event in events
    ]


@router.post("/charging-sessions/{session_id}/stop", status_code=202)
def stop_session(
    session_id: UUID,
    idempotency_key: str = Header(default=""),
    user=Depends(current_user),
    db=Depends(db_session),
):
    return session_row(db, stop(db, user, session_id, idempotency_key))


@router.post("/charging-sessions/{session_id}/soc")
def session_soc(
    session_id: UUID,
    data: SocInput,
    user=Depends(current_user),
    db=Depends(db_session),
):
    # The app pushes the phone battery every poll (~5 s); 60/min leaves room for retries.
    limit(db, f"soc:{user.id}", maximum=60, seconds=60)
    return session_row(db, report_soc(db, user, session_id, data.soc_percent))


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
        many=lambda items: session_rows(db, items),
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
    return page(db, query, limit, offset, many=lambda items: session_rows(db, items, channel=True))


@router.get("/operator/summary")
def summary(user=Depends(current_user), db=Depends(db_session)):
    operator(user)
    # Aggregate in SQL; loading every historical session grew without bound.
    total_sessions, energy_wh, estimated_cost = db.execute(
        select(
            func.count(ChargingSession.id),
            func.sum(ChargingSession.energy_wh),
            func.sum(ChargingSession.cost_estimate),
        ).join(Connector).join(Station).where(Station.owner_id == user.id)
    ).one()
    return {
        "stations": db.scalar(select(func.count()).select_from(Station).where(Station.owner_id == user.id)),
        "total_sessions": total_sessions,
        "total_energy_wh": str(energy_wh if energy_wh is not None else 0),
        "total_estimated_cost": str(estimated_cost if estimated_cost is not None else 0),
    }


@router.get("/operator/charging-sessions")
def operator_history(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user=Depends(current_user),
    db=Depends(db_session),
):
    operator(user)
    query = (
        select(ChargingSession)
        .join(Connector)
        .join(Station)
        .where(Station.owner_id == user.id)
        .order_by(ChargingSession.created_at.desc(), ChargingSession.id.desc())
    )
    return page(db, query, limit, offset, many=lambda items: session_rows(db, items, channel=True))
