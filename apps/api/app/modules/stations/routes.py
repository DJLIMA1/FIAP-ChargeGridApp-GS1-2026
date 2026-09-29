import math
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select

from ...database import db_session
from ...errors import fail
from ...http_helpers import page, point_row, station_row, update
from ...models import ChargingSession, Connector, Reservation, Station
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
    reset_blocks_point,
)
from .discovery import discover, normalize_connector

router = APIRouter()


@router.get("/stations")
def stations(
    lat: float | None = Query(None, ge=-90, le=90),
    lng: float | None = Query(None, ge=-180, le=180),
    radius_km: float = Query(50, gt=0, le=500),
    connector_type: str | None = Query(None, min_length=1, max_length=50),
    available_only: bool = False,
    max_price_per_kwh: Decimal | None = Query(None, ge=0, le=10000),
    sort: Literal["default", "price", "distance"] = "default",
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user=Depends(current_user),
    db=Depends(db_session),
):
    if (lat is None) != (lng is None):
        fail("coordinates_required", "Informe lat e lng juntos", 422)
    if sort == "distance" and lat is None:
        fail("coordinates_required", "Informe lat e lng para ordenar por proximidade", 422)
    if connector_type is not None and not connector_type.strip():
        fail("validation_error", "Informe um conector válido", 422)
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
    if not connector_type and not available_only and max_price_per_kwh is None:
        if sort in ("default", "distance"):
            if sort == "distance":
                query = query.order_by(None).order_by(distance, Station.id)
            def render(obj):
                return discover([station_row(db, obj)], lat=lat, lng=lng)[0]
            return page(db, query, limit, offset, render)
    # Narrow by static point attributes before materializing authoritative states.
    # Availability itself also includes reservations, watchdog and reconciliation.
    point_query = select(Connector.id).where(Connector.station_id == Station.id, Connector.active.is_(True))
    if connector_type:
        key = func.regexp_replace(func.lower(Connector.connector_type), "[^a-z0-9]", "", "g")
        normalized = case((key.in_(("tipo2", "typeii")), "type2"),
                          (key.in_(("ccs", "ccstype2")), "ccs2"), else_=key)
        point_query = point_query.where(normalized == normalize_connector(connector_type))
    if max_price_per_kwh is not None:
        point_query = point_query.where(Connector.price_per_kwh <= max_price_per_kwh)
    if connector_type or available_only or max_price_per_kwh is not None:
        query = query.where(point_query.exists())
    # Availability includes device reconciliation and active operations. Use the
    # authoritative serializer before pagination, rather than a weaker SQL guess.
    records = discover(
        [station_row(db, obj) for obj in db.scalars(query)],
        connector_type=connector_type, available_only=available_only,
        max_price_per_kwh=max_price_per_kwh, sort=sort, lat=lat, lng=lng,
    )
    return {"items": records[offset:offset + limit], "total": len(records), "limit": limit, "offset": offset}


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
    if data.active is True and reset_blocks_point(db, obj.id):
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
