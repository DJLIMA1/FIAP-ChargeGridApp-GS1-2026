import hashlib
import json
from datetime import timedelta
from decimal import Decimal

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select

from .errors import fail
from .models import (
    ChargingSession,
    Command,
    Connector,
    Device,
    Idempotency,
    Profile,
    Reservation,
    Station,
    now,
)

RES_ACTIVE = ("pending_device", "confirmed", "cancelling")
SESSION_ACTIVE = ("starting", "charging", "stopping")
_DEVICE_NOT_LOADED = object()


def row(obj):
    if obj is None:
        return None
    return {
        col.name: (
            str(getattr(obj, col.name))
            if isinstance(getattr(obj, col.name), Decimal)
            else jsonable_encoder(getattr(obj, col.name))
        )
        for col in obj.__table__.columns
    }


def operator(user):
    if not user.operator_enabled:
        fail("forbidden", "Operador não habilitado", 403)


def owned(db, user, station_id):
    operator(user)
    station = db.get(Station, station_id)
    if not station or station.owner_id != user.id:
        fail("not_found", "Posto não encontrado", 404)
    return station


def device_for(db, connector):
    return db.scalar(select(Device).where(Device.connector_id == connector.id, Device.revoked.is_(False)))


def online(device):
    return bool(device and device.last_seen and device.last_seen > now() - timedelta(seconds=45))


def active_res(db, connector_id):
    return db.scalar(
        select(Reservation).where(
            Reservation.connector_id == connector_id, Reservation.status.in_(RES_ACTIVE)
        )
    )


def active_session(db, connector_id):
    return db.scalar(
        select(ChargingSession).where(
            ChargingSession.connector_id == connector_id, ChargingSession.status.in_(SESSION_ACTIVE)
        )
    )


def issue(db, connector, device, kind, reservation=None, session=None, parameters=None):
    for cmd in db.scalars(
        select(Command).where(Command.device_id == device.id, Command.status.in_(("pending", "received")))
    ):
        cmd.status = "superseded"
    connector.control_version += 1
    cmd = Command(
        device_id=device.id,
        type=kind,
        version=connector.control_version,
        reservation_id=reservation.id if reservation else None,
        session_id=session.id if session else None,
        parameters=parameters or {},
        expires_at=now() + timedelta(seconds=30),
    )
    db.add(cmd)
    device.reconciled = False
    db.flush()
    return cmd


def reconcile_expiry(db, connector):
    reservation = active_res(db, connector.id)
    session = active_session(db, connector.id)
    device = device_for(db, connector)
    if reservation and reservation.status in ("pending_device", "confirmed"):
        deadline = (
            reservation.expires_at if reservation.status == "confirmed" else reservation.confirmation_deadline
        )
        if deadline and deadline <= now():
            reservation.status = "cancelling"
            if device:
                issue(
                    db,
                    connector,
                    device,
                    "RELEASE",
                    reservation=reservation,
                    parameters={"reason": "expired"},
                )
    if session and session.status == "starting":
        cmd = db.scalar(
            select(Command)
            .where(Command.session_id == session.id, Command.type == "START")
            .order_by(Command.version.desc())
        )
        if cmd and cmd.expires_at <= now() and cmd.status not in ("applied", "superseded"):
            session.status = "stopping"
            issue(db, connector, device, "STOP", session=session, parameters={"reason": "start_timeout"})
    return reservation, session


def lock_point(db, user, connector_id):
    db.execute(select(Profile).where(Profile.id == user.id).with_for_update()).scalar_one()
    connector = db.scalar(
        select(Connector)
        .where(Connector.id == connector_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not connector:
        fail("not_found", "Ponto não encontrado", 404)
    reconcile_expiry(db, connector)
    return connector


def free(db, connector, allow_reservation=None, *, device=_DEVICE_NOT_LOADED):
    if device is _DEVICE_NOT_LOADED:
        device = device_for(db, connector)
    station = db.get(Station, connector.station_id)
    reservation = active_res(db, connector.id)
    session = active_session(db, connector.id)
    return bool(
        connector.active
        and station.active
        and online(device)
        and device.reconciled
        and not device.connected
        and device.physical_state in ("idle", "stopped")
        and not session
        and (not reservation or reservation.id == allow_reservation)
    )


def ensure_user_free(db, user, reservation=None):
    res = db.scalar(
        select(Reservation).where(Reservation.user_id == user.id, Reservation.status.in_(RES_ACTIVE))
    )
    ses = db.scalar(
        select(ChargingSession).where(
            ChargingSession.user_id == user.id, ChargingSession.status.in_(SESSION_ACTIVE)
        )
    )
    if ses or (res and res.id != reservation):
        fail("user_busy", "Usuário já possui reserva ou recarga ativa")


def idempotent(db, user, operation, key, body, cls):
    if not key or len(key) > 100:
        fail("idempotency_key_required", "Informe Idempotency-Key com até 100 caracteres", 422)
    body_hash = hashlib.sha256(json.dumps(jsonable_encoder(body), sort_keys=True).encode()).hexdigest()
    old = db.get(Idempotency, (user.id, operation, key))
    if old:
        if old.body_hash != body_hash:
            fail("idempotency_conflict", "Chave já usada com outro corpo")
        return db.get(cls, old.resource_id), body_hash
    return None, body_hash


def remember(db, user, operation, key, body_hash, obj):
    db.flush()
    db.add(
        Idempotency(user_id=user.id, operation=operation, key=key, body_hash=body_hash, resource_id=obj.id)
    )
