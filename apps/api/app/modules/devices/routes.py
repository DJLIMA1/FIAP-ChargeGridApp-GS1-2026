import secrets
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select

from ...database import db_session
from ...errors import fail
from ...http_helpers import own_device
from ...models import Connector, Device
from ...schemas import (
    SyncInput,
)
from ...security import current_device, current_user, digest
from ...service import (
    device_for,
    online,
    operator,
    owned,
)
from ..auth.routes import limit
from ..devices.service import sync

router = APIRouter()


@router.get("/connectors/{connector_id}/device")
def connector_device(connector_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    operator(user)
    point = db.get(Connector, connector_id)
    if not point:
        fail("not_found", "Ponto não encontrado", 404)
    owned(db, user, point.station_id)
    device = device_for(db, point)
    if not device:
        fail("not_found", "Ponto sem dispositivo ativo", 404)
    # Explicit allowlist: credentials, hashes and replay internals are never returned.
    return {
        "device_id": str(device.id),
        "connector_id": str(point.id),
        "firmware_version": device.firmware_version,
        "last_seen": device.last_seen,
        "online": online(device),
        "physical_state": device.physical_state,
        "connected": device.connected,
        "reconciled": device.reconciled,
    }


@router.post("/connectors/{connector_id}/device", status_code=201)
def provision(connector_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    point = db.scalar(select(Connector).where(Connector.id == connector_id).with_for_update())
    if not point:
        fail("not_found", "Ponto não encontrado", 404)
    owned(db, user, point.station_id)
    if device_for(db, point):
        fail("device_exists", "Ponto já tem dispositivo; revogue ou rotacione")
    key = secrets.token_urlsafe(32)
    obj = Device(connector_id=point.id, key_hash=digest(key))
    db.add(obj)
    db.flush()
    return {"device_id": str(obj.id), "device_key": key}


@router.post("/devices/{device_id}/rotate-key")
def rotate(device_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    obj = own_device(db, user, device_id)
    if obj.revoked:
        fail("device_revoked", "Provisione um novo dispositivo")
    key = secrets.token_urlsafe(32)
    obj.key_hash = digest(key)
    obj.reconciled = False
    return {"device_id": str(obj.id), "device_key": key}


@router.post("/devices/{device_id}/revoke")
def revoke(device_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    obj = own_device(db, user, device_id)
    obj.revoked = True
    obj.reconciled = False
    return {"revoked": True}


@router.post("/devices/sync")
def device_sync(data: SyncInput, device=Depends(current_device), db=Depends(db_session)):
    limit(db, "device:" + str(device.id), maximum=40)
    return sync(db, device, data)
