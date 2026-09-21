import math
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from ...database import db_session
from ...errors import fail
from ...http_helpers import page, point_row, station_row, update
from ...models import ChargingSession, Command, Connector, Device, Reservation, Station
from ...schemas import (
    ConnectorInput,
    ConnectorPatch,
    StationInput,
    StationPatch,
)
from ...security import current_user
from ...service import (
    RES_ACTIVE,
    SESSION_ACTIVE,
    operator,
    owned,
)

router = APIRouter()


@router.get("/stations")
def stations(
    lat: float | None = Query(None, ge=-90, le=90),
    lng: float | None = Query(None, ge=-180, le=180),
    radius_km: float = Query(50, gt=0, le=500),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user=Depends(current_user),
    db=Depends(db_session),
):
    if (lat is None) != (lng is None):
        fail("coordinates_required", "Informe lat e lng juntos", 422)
    query = select(Station).where(Station.active.is_(True)).order_by(Station.id)
    if lat is not None:
        distance = 6371 * func.acos(
            func.least(
                1,
                func.greatest(
                    -1,
                    math.sin(math.radians(lat)) * func.sin(func.radians(Station.latitude))
                    + math.cos(math.radians(lat))
                    * func.cos(func.radians(Station.latitude))
                    * func.cos(func.radians(Station.longitude - lng)),
                ),
            )
        )
        query = query.where(distance <= radius_km)
    return page(db, query, limit, offset, lambda obj: station_row(db, obj))


@router.get("/stations/{station_id}")
def station(station_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    obj = db.get(Station, station_id)
    if not obj:
        fail("not_found", "Posto não encontrado", 404)
    return station_row(db, obj)


@router.post("/stations", status_code=201)
def create_station(data: StationInput, user=Depends(current_user), db=Depends(db_session)):
    operator(user)
    obj = Station(owner_id=user.id, **data.model_dump())
    db.add(obj)
    db.flush()
    return station_row(db, obj)


@router.patch("/stations/{station_id}")
def patch_station(station_id: UUID, data: StationPatch, user=Depends(current_user), db=Depends(db_session)):
    obj = owned(db, user, station_id)
    points = db.scalars(
        select(Connector).where(Connector.station_id == obj.id).order_by(Connector.id).with_for_update()
    ).all()
    if data.active is False and any(
        db.scalar(
            select(ChargingSession.id).where(
                ChargingSession.connector_id == p.id, ChargingSession.status.in_(SESSION_ACTIVE)
            )
        )
        or db.scalar(
            select(Reservation.id).where(Reservation.connector_id == p.id, Reservation.status.in_(RES_ACTIVE))
        )
        for p in points
    ):
        fail("point_busy", "Encerre reservas/recargas antes de desativar")
    update(obj, data)
    return station_row(db, obj)


@router.post("/stations/{station_id}/connectors", status_code=201)
def create_point(station_id: UUID, data: ConnectorInput, user=Depends(current_user), db=Depends(db_session)):
    owned(db, user, station_id)
    fail("claim_required", "Escaneie o QR de propriedade do equipamento para adicionar um ponto", 409)


@router.patch("/connectors/{connector_id}")
def patch_point(connector_id: UUID, data: ConnectorPatch, user=Depends(current_user), db=Depends(db_session)):
    obj = db.scalar(select(Connector).where(Connector.id == connector_id).with_for_update())
    if not obj:
        fail("not_found", "Ponto não encontrado", 404)
    owned(db, user, obj.station_id)
    if data.active is True and db.scalar(
        select(Command.id)
        .join(Device, Device.id == Command.device_id)
        .where(
            Device.connector_id == obj.id,
            Command.type == "FACTORY_RESET",
            Command.status.in_(("pending", "received", "applied")),
        )
        .limit(1)
    ):
        fail("point_retired", "Ponto em restauração de fábrica; vincule a tela novamente pelo QR", 409)
    if db.scalar(
        select(ChargingSession.id).where(
            ChargingSession.connector_id == obj.id, ChargingSession.status.in_(SESSION_ACTIVE)
        )
    ) or db.scalar(
        select(Reservation.id).where(Reservation.connector_id == obj.id, Reservation.status.in_(RES_ACTIVE))
    ):
        fail("point_busy", "Encerre reservas/recargas antes de alterar o ponto")
    update(obj, data)
    db.flush()
    return point_row(db, obj)


@router.get("/operator/stations")
def operator_stations(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user=Depends(current_user),
    db=Depends(db_session),
):
    operator(user)
    return page(
        db,
        select(Station).where(Station.owner_id == user.id).order_by(Station.id),
        limit,
        offset,
        lambda obj: station_row(db, obj),
    )
