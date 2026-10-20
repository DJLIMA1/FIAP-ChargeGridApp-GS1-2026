"""Tarifas do posto: dados base do dono e o status atual da demanda (cálculo do ChargeGrid)."""
from uuid import UUID

from fastapi import APIRouter, Body, Depends
from sqlalchemy import select

from chargegrid_core import pricing

from ...database import db_session
from ...errors import fail
from ...models import Connector
from ...security import current_user
from ...service import owned
from .service import station_demand

router = APIRouter()


def _payload(db, station):
    status = station_demand(db, station)
    points = db.scalars(select(Connector).where(Connector.station_id == station.id)).all()
    connectors = [
        {"id": str(point.id), "public_code": point.public_code, "active": point.active,
         "base_price_per_kwh": str(point.price_per_kwh),
         "current_price_per_kwh": str(pricing.dynamic_price(point.price_per_kwh, status["multiplier"]))}
        for point in points
    ]
    return {"rules": pricing.stored_rules(station.pricing), "status": status, "connectors": connectors}


@router.get("/stations/{station_id}/pricing")
def get_pricing(station_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    return _payload(db, owned(db, user, station_id))


@router.put("/stations/{station_id}/pricing")
def put_pricing(station_id: UUID, rules: dict = Body(...), user=Depends(current_user), db=Depends(db_session)):
    station = owned(db, user, station_id)
    try:
        station.pricing = pricing.clean_rules(rules)
    except ValueError as error:
        fail("invalid_pricing", str(error), 422)
    db.flush()
    return _payload(db, station)
