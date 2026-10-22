"""Acompanhamento e previsão de ocupação (dono) e melhor horário para carregar (motorista).

Somente leitura: nenhuma rota grava. Sugestões são aplicadas pelo dono com o
``PUT /stations/{id}/pricing`` existente, depois de confirmar.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ...database import db_session
from ...errors import fail
from ...models import Station
from ...security import current_user
from ...service import owned
from ..auth.routes import limit
from . import service

router = APIRouter(tags=["forecast"])
NO_STORE = {"Cache-Control": "no-store"}
# Backtest + previsão custam algumas centenas de ms de CPU: limite por usuário.
OWNER_LIMIT = (30, 60)
DRIVER_LIMIT = (60, 60)


@router.get("/owner/forecast")
def owner_forecast(
    station_id: UUID,
    horizon_hours: int = Query(36, ge=1, le=36),
    user=Depends(current_user),
    db=Depends(db_session),
):
    station = owned(db, user, station_id)
    limit(db, f"owner-forecast:{user.id}", maximum=OWNER_LIMIT[0], seconds=OWNER_LIMIT[1])
    return JSONResponse(service.owner_forecast(db, station, horizon_hours), headers=NO_STORE)


@router.get("/owner/occupancy-history")
def occupancy_history(
    station_id: UUID,
    weeks: int = Query(4, ge=1, le=8),
    user=Depends(current_user),
    db=Depends(db_session),
):
    station = owned(db, user, station_id)
    return JSONResponse(service.owner_history(db, station, weeks), headers=NO_STORE)


@router.get("/stations/{station_id}/best-times")
def best_times(
    station_id: UUID,
    hours: int = Query(12, ge=3, le=24),
    user=Depends(current_user),
    db=Depends(db_session),
):
    station = db.get(Station, station_id)
    if not station or not station.active or station.removed_at is not None or station.owner_id is None:
        fail("not_found", "Posto não encontrado", 404)
    limit(db, f"best-times:{user.id}", maximum=DRIVER_LIMIT[0], seconds=DRIVER_LIMIT[1])
    return JSONResponse(service.best_times(db, station, hours), headers=NO_STORE)
