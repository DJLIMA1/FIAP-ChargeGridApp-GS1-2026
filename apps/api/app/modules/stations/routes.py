import math
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select

from chargegrid_core import power as power_rules

from ...database import db_session
from ...errors import fail
from ...http_helpers import page, point_row, retired_ids, station_row, station_rows, update
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
            def render(items):
                return [discover([item], lat=lat, lng=lng)[0] for item in station_rows(db, items, user)]
            return page(db, query, limit, offset, many=render)
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
        station_rows(db, db.scalars(query).all(), user),
        connector_type=connector_type, available_only=available_only,
        max_price_per_kwh=max_price_per_kwh, sort=sort, lat=lat, lng=lng,
    )
    return {"items": records[offset:offset + limit], "total": len(records), "limit": limit, "offset": offset}


@router.get("/stations/{station_id}")
def station(station_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    obj = db.get(Station, station_id)
    if not obj:
        fail("not_found", "Posto não encontrado", 404)
    return station_row(db, obj, user)


@router.post("/stations", status_code=201)
def create_station(data: StationInput, user=Depends(current_user), db=Depends(db_session)):
    operator(user)
    obj = Station(owner_id=user.id, **data.model_dump())
    db.add(obj)
    db.flush()
    return station_row(db, obj, user)


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
    if "max_power_kw" in data.model_fields_set:
        # Without live rebalancing the cap is a next-start setting (running charges keep their
        # power); with rebalance_enabled, the next device syncs redivide it (modules/power).
        retired = retired_ids(db, [point.id for point in points])
        ratings = [point.power_kw for point in points if point.active and point.id not in retired]
        try:
            data.max_power_kw = power_rules.validate_station_max(data.max_power_kw, ratings)
        except ValueError as exc:
            fail("invalid_power_limit", str(exc), 422)
    update(obj, data)
    db.flush()
    db.refresh(obj)
    return station_row(db, obj, user)


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
    if "charger_address" in data.model_fields_set and data.charger_address == obj.charger_address:
        data.model_fields_set.discard("charger_address")  # mesmo carregador: nada muda (nem com recarga)
    limit_only = data.model_fields_set <= {"power_limit_kw"}
    # A power limit only affects the next start (a running charge keeps the power it
    # started with), so it may change while the point is busy; other edits may not.
    if not limit_only and (db.scalar(
        select(ChargingSession.id).where(
            ChargingSession.connector_id == obj.id, ChargingSession.status.in_(SESSION_ACTIVE)
        )
    ) or db.scalar(
        select(Reservation.id).where(Reservation.connector_id == obj.id, Reservation.status.in_(RES_ACTIVE))
    )):
        fail("point_busy", "Encerre reservas/recargas antes de alterar o ponto")
    rating = data.power_kw if data.power_kw is not None else obj.power_kw
    if "power_limit_kw" in data.model_fields_set:
        try:
            data.power_limit_kw = power_rules.validate_port_limit(rating, data.power_limit_kw)
        except ValueError as exc:
            fail("invalid_power_limit", str(exc), 422)
    elif data.power_kw is not None and obj.power_limit_kw is not None and obj.power_limit_kw >= data.power_kw:
        # A new rating at or below the old limit makes that limit meaningless: clear it.
        obj.power_limit_kw = None
    if data.public_code is not None and db.scalar(
        select(Connector.id).where(Connector.public_code == data.public_code, Connector.id != obj.id)
    ):
        # Was a generic IntegrityError 409 ("Operação conflita com registro existente").
        fail("public_code_taken", "Já existe um ponto com este código público. Escolha outro.", 409)
    if "charger_address" in data.model_fields_set and data.charger_address is not None:
        # Endereço único por posto: dois pontos no mesmo carregador disputariam o mesmo relé.
        taken = db.scalar(select(Connector).where(
            Connector.station_id == obj.station_id, Connector.charger_address == data.charger_address,
            Connector.id != obj.id))
        if taken:
            fail("charger_address_taken",
                 f"O carregador {data.charger_address} já está ligado ao ponto {taken.public_code} deste posto. "
                 "Escolha outro endereço.", 409)
    update(obj, data)
    db.flush()
    db.refresh(obj)
    return point_row(db, obj, user)


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
        many=lambda items: station_rows(db, items, user),
    )
