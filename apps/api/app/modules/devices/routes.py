import secrets
from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select

from ...database import db_session
from ...errors import fail
from ...http_helpers import own_device
from ...models import Command, Connector, Device, now
from ...schemas import (
    SyncInput,
)
from ...security import current_device, current_user, digest
from ...service import (
    active_res,
    active_session,
    device_for,
    issue,
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
        device = db.scalar(
            select(Device).join(Command, Command.device_id == Device.id).where(
                Device.connector_id == point.id,
                Command.type == "FACTORY_RESET",
                Command.status == "applied",
            ).limit(1)
        )
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
        "retired": device.revoked,
    }


@router.post("/connectors/{connector_id}/device", status_code=201)
def provision(connector_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    point = db.scalar(select(Connector).where(Connector.id == connector_id).with_for_update())
    if not point:
        fail("not_found", "Ponto não encontrado", 404)
    owned(db, user, point.station_id)
    if db.scalar(
        select(Command.id).join(Device, Device.id == Command.device_id).where(
            Device.connector_id == point.id,
            Command.type == "FACTORY_RESET",
            Command.status.in_(("pending", "received", "applied")),
        ).limit(1)
    ):
        fail("point_retired", "Escaneie o novo QR do ESP32 para criar outro ponto", 409)
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
    reset = _reset_command(db, obj.id)
    if reset and reset.status in ("pending", "received") and reset.expires_at > now():
        fail("reset_pending", "Aguarde o ESP32 confirmar a restauração", 409)
    if obj.revoked:
        fail("device_revoked", "Provisione um novo dispositivo")
    key = secrets.token_urlsafe(32)
    obj.key_hash = digest(key)
    obj.reconciled = False
    return {"device_id": str(obj.id), "device_key": key}


@router.post("/devices/{device_id}/revoke")
def revoke(device_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    obj = own_device(db, user, device_id)
    reset = _reset_command(db, obj.id)
    if reset and reset.status in ("pending", "received") and reset.expires_at > now():
        fail("reset_pending", "Aguarde o ESP32 confirmar a restauração", 409)
    obj.revoked = True
    obj.reconciled = False
    return {"revoked": True}


def _reset_command(db, device_id):
    return db.scalar(
        select(Command)
        .where(Command.device_id == device_id, Command.type == "FACTORY_RESET")
        .order_by(Command.version.desc())
        .limit(1)
    )


def _reset_status(command):
    if not command:
        return {"status": "not_requested"}
    status = "expired" if command.status in ("pending", "received") and command.expires_at <= now() else command.status
    return {"status": status, "command_id": str(command.id)}


def _supports_factory_reset(version):
    try:
        parts = [int(part) for part in version.split(".")]
        return len(parts) == 3 and tuple(parts) >= (0, 3, 5)
    except (AttributeError, TypeError, ValueError):
        return False


@router.get("/devices/{device_id}/factory-reset")
def factory_reset_status(device_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    obj = own_device(db, user, device_id)
    return _reset_status(_reset_command(db, obj.id))


@router.post("/devices/{device_id}/factory-reset", status_code=202)
def factory_reset(device_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    obj = own_device(db, user, device_id)
    point = db.scalar(select(Connector).where(Connector.id == obj.connector_id).with_for_update())
    obj = db.scalar(select(Device).where(Device.id == obj.id).with_for_update())
    if obj.revoked:
        fail("device_revoked", "Este ESP32 já foi desvinculado", 409)
    existing = _reset_command(db, obj.id)
    if existing and existing.status in ("pending", "received") and existing.expires_at > now():
        return _reset_status(existing)
    if not online(obj) or obj.physical_state != "idle" or obj.connected:
        fail("device_not_idle", "O ESP32 deve estar online e sem recarga para restaurar", 409)
    if not _supports_factory_reset(obj.firmware_version):
        fail("firmware_update_required", "Atualize o firmware do ESP32 antes de restaurar", 409)
    if active_res(db, point.id) or active_session(db, point.id):
        fail("point_busy", "Encerre reservas e recargas antes de restaurar", 409)
    other = db.scalar(select(Command.id).where(
        Command.device_id == obj.id,
        Command.status.in_(("pending", "received")),
        Command.expires_at > now(),
    ))
    if other:
        fail("point_busy", "Aguarde o comando anterior terminar", 409)
    point.active = False
    command = issue(db, point, obj, "FACTORY_RESET")
    command.expires_at = now() + timedelta(minutes=2)
    return _reset_status(command)


@router.post("/devices/sync")
def device_sync(data: SyncInput, device=Depends(current_device), db=Depends(db_session)):
    limit(db, "device:" + str(device.id), maximum=40)
    return sync(db, device, data)
