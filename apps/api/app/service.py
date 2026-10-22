import hashlib
import json
import secrets
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from fastapi.encoders import jsonable_encoder
from sqlalchemy import or_, select, text
from sqlalchemy.orm import aliased

from .errors import fail
from .models import (
    KIOSK_ORDER_OPEN,
    ChargingSession,
    Command,
    Connector,
    Device,
    Idempotency,
    KioskOrder,
    Profile,
    Reservation,
    Station,
    now,
)
from .session_events import record as record_session_event

# Tempo que o ponto fica guardado depois que o posto confirma a reserva (o app mostra o mesmo prazo).
RESERVATION_MINUTES = 15
# Código público curto do ponto: "CG-" + 4 caracteres sem 0/O e 1/I (fáceis de ler e ditar).
PUBLIC_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_public_code(db, length=4):
    """Código público curto e único (``CG-7KQ2``)."""
    while True:
        code = "CG-" + "".join(secrets.choice(PUBLIC_CODE_ALPHABET) for _ in range(length))
        if not db.scalar(select(Connector.id).where(Connector.public_code == code)):
            return code

RES_ACTIVE = ("pending_device", "confirmed", "cancelling")
# Capacidade declarada pela tela que comanda vários carregadores (sync endereçado).
MULTI_CHARGER_CAPABILITY = "multi_charger_v1"
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
    if not station or station.owner_id != user.id or station.removed_at is not None:
        fail("not_found", "Posto não encontrado", 404)
    return station


def device_for(db, connector):
    return db.scalar(select(Device).where(Device.connector_id == connector.id, Device.revoked.is_(False)))


def screen_for(db, device):
    """A TELA (estação) que comanda o carregador deste dispositivo: ela mesma, ou a tela-mãe de
    um carregador adicional (``parent_device_id``). ``None`` sem dispositivo ou tela revogada."""
    if device is None:
        return None
    if device.parent_device_id is None:
        return device
    screen = db.get(Device, device.parent_device_id)
    return screen if screen is not None and not screen.revoked else None


def lock_screen_group(db, connector_id):
    """Serialize a screen lifecycle with all its chargers, before locking any Connector.

    Order: existing Profile lock -> screen-group advisory lock -> Connector -> Device ->
    power advisory lock. Lifecycle checks read siblings without FOR UPDATE: taking sibling
    connector locks after the screen connector would invert that order. The key is the
    screen's connector, so reprovisioning its Device cannot change the lock identity.
    Resolve with scalar columns (not a possibly stale authenticated ORM object); callers
    reload device/revocation state after acquiring the lock. No external I/O under this lock.
    """
    root = screen_group_key(db, connector_id)
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
               {"key": f"screen-group:{root}"})


def screen_group_key(db, connector_id):
    parent = aliased(Device)
    return db.scalar(
        select(parent.connector_id).select_from(Device).join(parent, parent.id == Device.parent_device_id)
        .where(Device.connector_id == connector_id, Device.revoked.is_(False))
    ) or connector_id


def screen_group_busy(db, screen):
    """Called with the screen-group lock held; preserve the existing session/reservation rule."""
    ids = select(Device.connector_id).where(or_(Device.id == screen.id, Device.parent_device_id == screen.id))
    return bool(db.scalar(select(ChargingSession.id).where(
        ChargingSession.connector_id.in_(ids), ChargingSession.status.in_(SESSION_ACTIVE)).limit(1))
        or db.scalar(select(Reservation.id).where(
            Reservation.connector_id.in_(ids), Reservation.status.in_(RES_ACTIVE)).limit(1)))


def retire_screen_chargers(db, screen):
    """Retire idle dependents with their screen; keep connectors and history for the owner."""
    for child in db.scalars(select(Device).where(Device.parent_device_id == screen.id, Device.revoked.is_(False))):
        child.revoked = True
        child.reconciled = False
        db.get(Connector, child.connector_id).active = False


def hardware_state(connector, device, screen):
    """``(screen_online, charger_online, reason)`` do ponto.

    A estação só fica offline sem contato da TELA (``screen_offline``). Com a tela online, o
    carregador do ponto pode estar offline (``charger_offline``): a tela não o leu no último
    sync (``devices.charger``) ou, num carregador adicional, a tela parou de sincronizar por ele.
    Firmware antigo (sem ``charger.address``) continua como antes: carregador = tela."""
    from chargegrid_core.chargers import link as charger_link  # módulo puro; evita ciclo no import

    screen_online = online(screen)
    if not screen_online:
        return False, False, charger_link.SCREEN_OFFLINE
    if device is not screen and not online(device):
        return True, False, charger_link.CHARGER_OFFLINE
    reason = charger_link.availability_reason(connector.charger_address, device.charger, True)
    return True, reason is None, reason


def reset_blocks_point(db, connector_id):
    # Includes the screen's reset for an additional charger (also after retirement).
    parent_ids = select(Device.parent_device_id).where(Device.connector_id == connector_id)
    return bool(db.scalar(
        select(Command.id).join(Device, Device.id == Command.device_id).where(
            or_(Device.connector_id == connector_id, Device.id.in_(parent_ids)),
            Command.type == "FACTORY_RESET",
            (Command.status == "applied")
            | (Command.status.in_(("pending", "received")) & (Command.expires_at > now())),
        ).limit(1)
    ))


def resetting_screens(db, screen_ids):
    """Batch the pending screen-reset state used by public and owner availability."""
    if not screen_ids:
        return set()
    return set(db.scalars(select(Command.device_id).where(
        Command.device_id.in_(screen_ids), Command.type == "FACTORY_RESET",
        Command.status.in_(("pending", "received")), Command.expires_at > now())))


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


def kiosk_holds(db, connector_ids):
    """Pedidos do totem que travam os pontos agora (abertos e dentro do prazo): ``{connector_id: pedido}``.

    Trava vencida não conta: o ponto fica livre na hora, mesmo antes de o pedido virar ``expired``.
    """
    ids = list(connector_ids)
    if not ids:
        return {}
    return {
        order.connector_id: order
        for order in db.scalars(
            select(KioskOrder).where(
                KioskOrder.connector_id.in_(ids),
                KioskOrder.status.in_(KIOSK_ORDER_OPEN),
                KioskOrder.expires_at > now(),
            )
        )
    }


def active_hold(db, connector_id):
    return kiosk_holds(db, [connector_id]).get(connector_id)


def issue(db, connector, device, kind, reservation=None, session=None, parameters=None, *, reconcile=True):
    # ``reconcile=False``: power adjustments (SET_POWER) do not change the point's lifecycle,
    # so they must not flip it to "reconciling" while the device confirms.
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
    if reconcile:
        device.reconciled = False
    db.flush()
    if session and kind in ("START", "STOP"):
        record_session_event(db, session, f"{kind.lower()}_requested", "api", f"command:{cmd.id}")
    return cmd


BATTERY_FULL = "battery_full"
SOC_STEP = Decimal("0.01")


def derived_soc(session, energy_wh):
    """SoC of a ``simulated`` session from delivered energy, or None if unknown."""
    if session.soc_source != "simulated" or session.start_soc_percent is None or not session.battery_kwh:
        return None
    gained = Decimal(energy_wh) / Decimal(1000) / Decimal(session.battery_kwh) * Decimal(100)
    return min(Decimal(100), Decimal(session.start_soc_percent) + gained).quantize(SOC_STEP, rounding=ROUND_HALF_UP)


def stop_if_battery_full(db, connector, device, session):
    """Battery at 100 %: same path as a user stop, once (a stopping session is left alone).

    ``end_reason`` is recorded now so the final reconciliation keeps
    ``battery_full`` whatever reason the device reports with its STOP ACK.
    """
    if (
        session.status not in ("starting", "charging")
        or session.soc_percent is None
        or Decimal(session.soc_percent) < 100
    ):
        return False
    session.status = "stopping"
    session.end_reason = BATTERY_FULL
    if device:
        issue(db, connector, device, "STOP", session=session, parameters={"reason": BATTERY_FULL})
    return True


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
    from .overstay import reconcile as reconcile_overstay  # evita import circular

    reconcile_overstay(db, connector, device)
    return reservation, session


def lock_point(db, user, connector_id):
    db.execute(select(Profile).where(Profile.id == user.id).with_for_update()).scalar_one()
    lock_screen_group(db, connector_id)
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


def availability(db, connector, allow_reservation=None, *, device=_DEVICE_NOT_LOADED,
                 station=_DEVICE_NOT_LOADED, reservation=_DEVICE_NOT_LOADED, session=_DEVICE_NOT_LOADED,
                 hold=_DEVICE_NOT_LOADED, allow_kiosk_payment=None, screen=_DEVICE_NOT_LOADED,
                 resetting=_DEVICE_NOT_LOADED):
    """Public state without identity data: available/offline/reserved/charging/
    reconciling/disabled/fault/occupied. A deadline never implies availability.

    Batch serializers may pass rows they already loaded for this connector; any
    omitted dependency is read here, so single-point callers keep one code path.
    A totem order holding the point (``hold``) makes it ``occupied`` with
    ``kiosk_in_use``; ``allow_kiosk_payment`` ignores the hold paid by that payment
    (the totem's own START).

    Hardware: the station (screen) offline makes the point ``offline`` with
    ``unavailable_reason`` ``screen_offline``; the screen online but this point's GoodWe charger
    not answering makes only this point ``offline`` with ``charger_offline`` (an active session
    keeps its charging/reconciling state). ``screen_online`` reports the station itself.
    """
    if device is _DEVICE_NOT_LOADED:
        device = device_for(db, connector)
    if screen is _DEVICE_NOT_LOADED:
        screen = screen_for(db, device)
    if resetting is _DEVICE_NOT_LOADED:
        resetting = bool(screen and screen.id in resetting_screens(db, [screen.id]))
    screen_online, _, hardware = hardware_state(connector, device, screen)
    if station is _DEVICE_NOT_LOADED:
        station = db.get(Station, connector.station_id)
    if reservation is _DEVICE_NOT_LOADED:
        reservation = active_res(db, connector.id)
    if session is _DEVICE_NOT_LOADED:
        session = active_session(db, connector.id)
    if hold is _DEVICE_NOT_LOADED:
        hold = active_hold(db, connector.id)
    if hold is not None and allow_kiosk_payment is not None and hold.payment_id == allow_kiosk_payment:
        hold = None
    reserved_until = (
        reservation.expires_at
        if reservation
        and reservation.status == "confirmed"
        and reservation.expires_at
        and reservation.expires_at > now()
        else None
    )
    if not connector.active or not station or not station.active or station.owner_id is None:
        status = "disabled"
    elif not screen_online or not online(device):
        status = "offline"
    elif device.physical_state == "fault":
        status = "fault"
    elif resetting:
        status = "reconciling"
    elif session:
        status = (
            "charging"
            if session.status == "charging" and device.physical_state == "charging" and device.reconciled
            else "reconciling"
        )
    elif hardware is not None:
        status = "offline"  # carregador sem resposta: só este ponto (a estação segue online)
    elif reservation and reservation.id != allow_reservation:
        status = (
            "reserved"
            if reserved_until and device.physical_state == "reserved" and device.reconciled
            else "reconciling"
        )
    elif hold is not None:
        status = "occupied"
    elif not device.reconciled:
        status = "reconciling"
    elif device.connected or device.physical_state not in ("idle", "stopped"):
        status = "occupied"
    else:
        status = "available"
    return {
        "available": status == "available",
        "availability_status": status,
        "reserved_until": reserved_until,
        # Ponto travado por um pedido do totem ("Ponto em uso no totem").
        "kiosk_in_use": hold is not None,
        # Por que está offline: "screen_offline" (a estação/tela) ou "charger_offline" (só este carregador).
        "unavailable_reason": hardware if status == "offline" else None,
        "screen_online": screen_online,
    }


def free(db, connector, allow_reservation=None, *, device=_DEVICE_NOT_LOADED):
    return availability(db, connector, allow_reservation, device=device)["available"]


def fail_unavailable(state, message="Ponto indisponível", *, db=None, connector=None):
    """409 ``point_unavailable`` com ``reason`` (estado do ponto, ``kiosk_in_use`` ou
    ``charger_offline``). Carregador offline: ``alternatives`` = pontos livres da mesma estação."""
    if state.get("kiosk_in_use"):
        fail("point_unavailable", "Ponto em uso no totem", 409, reason="kiosk_in_use")
    if state.get("unavailable_reason") == "charger_offline":
        from chargegrid_core.chargers import link as charger_link

        fail("point_unavailable", charger_link.CHARGER_OFFLINE_MESSAGE, 409, reason="charger_offline",
             alternatives=station_alternatives(db, connector) if db is not None and connector is not None else [])
    fail("point_unavailable", message, 409, reason=state.get("availability_status"))


def station_alternatives(db, connector):
    """Outros pontos livres da mesma estação (``[{id, public_code}]``), para o motorista trocar."""
    siblings = db.scalars(
        select(Connector).where(Connector.station_id == connector.station_id, Connector.id != connector.id,
                                Connector.active.is_(True)).order_by(Connector.charger_address)
    ).all()
    return [{"id": str(point.id), "public_code": point.public_code}
            for point in siblings if availability(db, point)["available"]]


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
