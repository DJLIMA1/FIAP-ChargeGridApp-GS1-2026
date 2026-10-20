from uuid import UUID

from fastapi import APIRouter, Depends

from ...database import db_session
from ...errors import fail
from ...models import ChargingSession
from ...schemas import BuildingLoadInput, PowerSiteInput
from ...security import current_user
from ...service import owned
from ..auth.routes import limit
from .service import session_view, set_building_load, set_site, station_view

router = APIRouter()


@router.get("/stations/{station_id}/power")
def station_power(station_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    return station_view(db, owned(db, user, station_id))


@router.put("/stations/{station_id}/power-site")
def station_power_site(station_id: UUID, data: PowerSiteInput, user=Depends(current_user), db=Depends(db_session)):
    station = owned(db, user, station_id)
    set_site(db, station, data)
    return station_view(db, station)


@router.put("/stations/{station_id}/building-load")
def station_building_load(station_id: UUID, data: BuildingLoadInput, user=Depends(current_user),
                          db=Depends(db_session)):
    # Controle deslizante do painel do vendedor: 120/min deixa arrastar sem travar.
    limit(db, f"building-load:{user.id}", maximum=120)
    station = owned(db, user, station_id)
    set_building_load(db, station, data.building_load_kw)
    return station_view(db, station)


@router.get("/charging-sessions/{session_id}/power")
def charging_session_power(session_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    session = db.get(ChargingSession, session_id)
    if not session or session.user_id != user.id:
        fail("not_found", "Sessão não encontrada", 404)
    return session_view(db, session)
