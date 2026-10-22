from uuid import UUID

from fastapi import APIRouter, Depends

from ...database import db_session
from ...errors import fail
from ...models import ChargingSession
from ...schemas import PowerSiteInput
from ...security import current_user
from ...service import owned
from .service import session_view, set_site, station_view

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
def station_building_load(station_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    # Consumo da loja ao vivo/simulado removido: a loja é uma margem ESTIMADA fixa (PUT power-site).
    owned(db, user, station_id)
    fail("store_load_removed", "A loja agora é uma margem estimada: informe o mínimo e o pico estimados "
                               "em Limites (PUT power-site, store_min_kw e store_peak_kw).", 410)


@router.get("/charging-sessions/{session_id}/power")
def charging_session_power(session_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    session = db.get(ChargingSession, session_id)
    if not session or session.user_id != user.id:
        fail("not_found", "Sessão não encontrada", 404)
    return session_view(db, session)
