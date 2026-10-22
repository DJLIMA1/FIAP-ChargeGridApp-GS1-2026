"""Tarifa do posto: dados base do dono e o status atual (cálculo do ChargeGrid)."""
from decimal import Decimal
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
    points = db.scalars(select(Connector).where(Connector.station_id == station.id,
                                                Connector.removed_at.is_(None))).all()
    connectors = []
    for point in points:
        current, price = pricing.connector_price(status, point.id, point.price_per_kwh)
        connectors.append({
            "id": str(point.id), "public_code": point.public_code, "active": point.active,
            "connector_type": point.connector_type, "base_price_per_kwh": str(point.price_per_kwh),
            "current_base_price_per_kwh": str(current), "current_price_per_kwh": str(price),
            **pricing.speed_prices(status, point.id, point.price_per_kwh)})
    return {"rules": pricing.stored_rules(station.pricing), "status": status, "connectors": connectors}


@router.get("/stations/{station_id}/pricing")
def get_pricing(station_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    return _payload(db, owned(db, user, station_id))


@router.put("/stations/{station_id}/pricing")
def put_pricing(station_id: UUID, rules: dict = Body(...), user=Depends(current_user), db=Depends(db_session)):
    station = owned(db, user, station_id)
    connector_ids = db.scalars(select(Connector.id).where(Connector.station_id == station.id)).all()
    try:
        # PUT parcial: o que não veio continua como está (o app 0.6.8 não conhece ``schedule``).
        validated = pricing.clean_rules(pricing.merge_rules(pricing.stored_rules(station.pricing), rules,
                                                                  connector_ids))
        for point in db.scalars(select(Connector).where(Connector.station_id == station.id)):
            configured = validated["speed"]["prices"].get(str(point.id), {})
            if "reduced" in configured:
                maximum = Decimal(configured.get("max", point.price_per_kwh))
                reduced = Decimal(configured["reduced"])
                if reduced > maximum or (maximum > 0 and reduced == maximum):
                    raise ValueError("A velocidade reduzida deve custar menos que a máxima.")
        station.pricing = validated
    except ValueError as error:
        fail("invalid_pricing", str(error), 422)
    db.flush()
    return _payload(db, station)
