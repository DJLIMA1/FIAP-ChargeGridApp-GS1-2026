import secrets
from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select, text

from ...database import db_session
from ...errors import fail
from ...http_helpers import own_device
from ...models import Command, Connector, Device, now
from ...schemas import (
    SyncInput,
)
from ...security import current_user, digest, syncing_device
from ...service import (
    active_res,
    active_session,
    device_for,
    issue,
    lock_screen_group,
    online,
    operator,
    owned,
    reset_blocks_point,
    retire_screen_chargers,
    screen_group_busy,
)
from ..auth.routes import limit
from ..devices.service import charger_device, sync
from ..kiosk_totem import service as totem

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
        # Carregador declarado pela tela no último sync (model, transport, limites; address/link
        # quando há um GoodWe HCA G2 externo) e o endereço configurado pelo dono.
        "charger": device.charger,
        "charger_address": point.charger_address,
        # Carregador adicional: a tela (dispositivo) da estação que o comanda; null = é a própria tela.
        "screen_device_id": str(device.parent_device_id) if device.parent_device_id else None,
    }


@router.post("/connectors/{connector_id}/device", status_code=201)
def provision(connector_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    lock_screen_group(db, connector_id)
    point = db.scalar(select(Connector).where(Connector.id == connector_id).with_for_update())
    if not point or point.removed_at is not None:
        fail("not_found", "Ponto não encontrado", 404)
    owned(db, user, point.station_id)
    if reset_blocks_point(db, point.id):
        fail("point_retired", "Escaneie o novo QR da central do ponto para criar outro ponto", 409)
    if device_for(db, point):
        fail("device_exists", "Ponto já tem dispositivo; revogue ou rotacione")
    key = secrets.token_urlsafe(32)
    obj = Device(connector_id=point.id, key_hash=digest(key))
    db.add(obj)
    db.flush()
    return {"device_id": str(obj.id), "device_key": key}


def _screen_only(obj):
    """Carregador adicional não tem chave nem firmware próprio: credencial e restauração são da tela."""
    if obj.parent_device_id is not None:
        fail("charger_device", "Este carregador é comandado pela central da estação; gerencie a central", 409)


def _idle_screen_group(db, obj):
    if screen_group_busy(db, obj):
        fail("point_busy", "Encerre reservas/recargas dos carregadores antes de mudar a central", 409)


@router.post("/devices/{device_id}/rotate-key")
def rotate(device_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    obj = own_device(db, user, device_id)
    _screen_only(obj)
    _idle_screen_group(db, obj)
    reset = _reset_command(db, obj.id)
    if reset and reset.status in ("pending", "received") and reset.expires_at > now():
        fail("reset_pending", "Aguarde o equipamento confirmar a restauração", 409)
    if obj.revoked:
        fail("device_revoked", "Provisione um novo dispositivo")
    key = secrets.token_urlsafe(32)
    obj.key_hash = digest(key)
    obj.reconciled = False
    return {"device_id": str(obj.id), "device_key": key}


@router.post("/devices/{device_id}/revoke")
def revoke(device_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    obj = own_device(db, user, device_id)
    _screen_only(obj)
    _idle_screen_group(db, obj)
    reset = _reset_command(db, obj.id)
    if reset and reset.status in ("pending", "received") and reset.expires_at > now():
        fail("reset_pending", "Aguarde o equipamento confirmar a restauração", 409)
    obj.revoked = True
    obj.reconciled = False
    retire_screen_chargers(db, obj)
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
    obj = own_device(db, user, device_id, require_idle=False)
    return _reset_status(_reset_command(db, obj.id))


@router.post("/devices/{device_id}/factory-reset", status_code=202)
def factory_reset(device_id: UUID, user=Depends(current_user), db=Depends(db_session)):
    obj = own_device(db, user, device_id)
    point = db.scalar(select(Connector).where(Connector.id == obj.connector_id).with_for_update())
    obj = db.scalar(select(Device).where(Device.id == obj.id).with_for_update())
    _screen_only(obj)
    _idle_screen_group(db, obj)
    if obj.revoked:
        fail("device_revoked", "Este equipamento já foi desvinculado", 409)
    existing = _reset_command(db, obj.id)
    if existing and existing.status in ("pending", "received") and existing.expires_at > now():
        return _reset_status(existing)
    if not online(obj) or obj.physical_state != "idle" or obj.connected:
        fail("device_not_idle", "O equipamento deve estar online e sem recarga para restaurar", 409)
    if not _supports_factory_reset(obj.firmware_version):
        fail("firmware_update_required", "Atualize o software do equipamento antes de restaurar", 409)
    if active_res(db, point.id) or active_session(db, point.id):
        fail("point_busy", "Encerre reservas e recargas antes de restaurar", 409)
    if not db.scalar(text("SELECT has_table_privilege(current_user, 'device_claims', 'INSERT')")):
        fail("factory_reset_unavailable", "A restauração do equipamento está indisponível; contate o suporte", 503)
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
def device_sync(data: SyncInput, device=Depends(syncing_device), db=Depends(db_session)):
    # Sync de 1 s em recarga + sync imediato após aplicar comando: 120/min (antes 40/min
    # derrubava cerca de 1/3 dos syncs com 429 e atrasava os ACKs).
    # Tela com vários carregadores: ``charger_address`` endereça o sync a um carregador adicional
    # dela (mesma chave); cada carregador tem o seu limite.
    target = charger_device(db, device, data.charger_address) if data.charger_address is not None else device
    limit(db, "device:" + str(target.id), maximum=120)
    result = sync(db, target, data, screen=device if target is not device else None)
    if "kiosk_order" in result:
        # Totem: verificação na Stripe, START pago e acerto do pedido depois de gravar o sync
        # (fora da trava do ponto); o START sai em ``commands`` no sync seguinte.
        db.commit()
        block = totem.after_sync(db, target.connector_id)
        if block is not None:
            result["kiosk_order"] = block
    return result
