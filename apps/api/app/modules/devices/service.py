import hashlib
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select

from chargegrid_core.chargers import link as charger_link

from ... import overstay
from ...errors import fail
from ...models import (
    ChargingSession,
    Command,
    Connector,
    Device,
    DeviceBoot,
    DeviceClaim,
    Station,
    Telemetry,
    now,
)
from ...presence_code import current_code
from ...service import (
    BATTERY_FULL,
    RESERVATION_MINUTES,
    active_res,
    active_session,
    derived_soc,
    issue,
    new_public_code,
    online,
    reconcile_expiry,
    row,
    stop_if_battery_full,
)
from ...session_events import record as record_session_event
from ..payments.funding import device_fields as payment_device_fields
from ..payments.funding import prepare_recent_settlements
from ..power import service as live_power


def sync(db, authenticated_device, data):
    authenticated_key_hash = authenticated_device.key_hash
    connector = db.scalar(
        select(Connector)
        .where(Connector.id == authenticated_device.connector_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    # Authentication loaded this object before acquiring the connector lock.
    # Re-read it after waiting: another sync or revocation may have committed.
    device = db.scalar(
        select(Device)
        .where(Device.id == authenticated_device.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if device.revoked or device.key_hash != authenticated_key_hash:
        fail("unauthorized", "Chave revogada ou alterada", 401)
    was_offline = not online(device)
    completed_reset_id = None
    for ack in data.acks:
        command = db.get(Command, ack.command_id)
        if not command or command.device_id != device.id:
            fail("invalid_command", "Comando não pertence ao dispositivo")
    if data.captured_at.tzinfo is None or data.captured_at > now() + timedelta(minutes=5):
        fail("invalid_time", "Horário inválido", 422)
    same_boot = device.boot_id == data.boot_id
    boot = db.get(DeviceBoot, (device.id, data.boot_id))
    # Server-time expiry also runs for duplicate telemetry, without accepting its
    # sequence or refreshing last_seen. A replay must not keep authorization alive.
    reservation, session = reconcile_expiry(db, connector)
    if (same_boot and data.sequence <= device.sequence) or (not same_boot and boot):
        return response(db, connector, device)
    if not boot:
        boot = DeviceBoot(device_id=device.id, boot_id=data.boot_id, last_sequence=data.sequence)
        db.add(boot)
    else:
        boot.last_sequence = data.sequence
    energy_wh = data.energy_wh.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    soc_percent = (
        data.soc_percent.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if data.soc_percent is not None else None
    )
    terminal_replay = False
    if data.session_id:
        reported = db.get(ChargingSession, data.session_id)
        if not reported or reported.connector_id != connector.id:
            fail("invalid_session", "Sessão não pertence ao dispositivo")
        if session and session.id != data.session_id:
            fail("invalid_session", "Sessão anterior não pode substituir sessão atual")
        if energy_wh < reported.energy_wh:
            fail("energy_regression", "Energia acumulada diminuiu", 422)
        if reported.status in ("completed", "failed", "interrupted"):
            terminal_replay = True
            if (
                energy_wh != reported.energy_wh
                or _soc_changed(reported, soc_percent)
                or data.source != reported.source
                or data.physical_state not in ("idle", "stopped", "fault")
            ):
                fail("session_finished", "Resultado final da sessão é imutável")
    elif data.physical_state == "charging" or data.energy_wh or data.soc_percent is not None:
        fail("session_required", "Medição de recarga exige session_id", 422)
    reboot = device.boot_id is not None and not same_boot
    old_state = device.physical_state
    device.boot_id = data.boot_id
    device.sequence = data.sequence
    device.last_seen = now()
    device.firmware_version = data.firmware_version
    device.physical_state = data.physical_state
    device.connected = data.connected
    # Capacidade declarada a cada sync: firmware rebaixado deixa de receber SET_POWER.
    device.capabilities = list(data.capabilities)
    # Firmware sem carregador externo guarda o mesmo formato de antes (sem address/link nulos).
    device.charger = data.charger.model_dump(
        exclude={key for key in ("address", "link") if getattr(data.charger, key) is None}
    ) if data.charger else None
    if reboot and session:
        session.status = "stopping"
        issue(db, connector, device, "STOP", session=session, parameters={"reason": "device_reboot"})
    for ack in data.acks:
        cmd = db.get(Command, ack.command_id)
        if cmd.status in ("applied", "superseded", "failed") or cmd.version != connector.control_version:
            continue
        if cmd.expires_at <= now():
            continue
        if ack.status == "received":
            if cmd.status == "received":
                continue
            cmd.status = "received"
            if cmd.session_id:
                record_session_event(db, db.get(ChargingSession, cmd.session_id),
                                     "command_received", "device_sync", f"received:{cmd.id}")
            continue
        if ack.status == "failed":
            cmd.status = "failed"
            cmd.error = ack.error
            if cmd.session_id:
                record_session_event(db, db.get(ChargingSession, cmd.session_id),
                                     "command_failed", "device_sync", f"failed:{cmd.id}")
            if cmd.type == "START" and session:
                session.status = "stopping"
                issue(db, connector, device, "STOP", session=session, parameters={"reason": "start_failed"})
            elif cmd.type == "RESERVE" and reservation:
                if reservation.status == "pending_device":
                    reservation.status = "cancelling"
                    issue(db, connector, device, "RELEASE", reservation=reservation)
                else:
                    # Restoration failing after reboot does not cancel an already
                    # confirmed booking. Its original deadline remains authoritative.
                    device.reconciled = False
            continue
        if cmd.type == "FACTORY_RESET":
            if (
                data.physical_state != "idle"
                or data.connected
                or data.session_id
                or active_res(db, connector.id)
                or active_session(db, connector.id)
                or not ack.new_device_key_hash
                or not ack.new_claim_token_hash
                or ack.new_device_key_hash == device.key_hash
            ):
                cmd.status = "failed"
                cmd.error = "unsafe_or_missing_factory_credentials"
                continue
            factory_station = Station(
                owner_id=None, name="Novo ponto ChargeGrid", address="Configure o endereço",
                latitude=0, longitude=0, active=False,
            )
            db.add(factory_station)
            db.flush()
            factory_point = Connector(
                station_id=factory_station.id,
                public_code=new_public_code(db),
                connector_type=connector.connector_type,
                power_kw=connector.power_kw,
                price_per_kwh=0,
                max_duration_minutes=connector.max_duration_minutes,
                active=False,
            )
            db.add(factory_point)
            db.flush()
            db.add(Device(connector_id=factory_point.id, key_hash=ack.new_device_key_hash))
            db.add(DeviceClaim(connector_id=factory_point.id, token_hash=ack.new_claim_token_hash))
            cmd.status = "applied"
            device.revoked = True
            device.reconciled = False
            completed_reset_id = str(cmd.id)
            continue
        if cmd.type == "SET_POWER":
            live_power.acknowledge(db, session, cmd, ack, data)
            continue
        compatible = False
        if (
            cmd.type == "RESERVE"
            and reservation
            and reservation.status in ("pending_device", "confirmed")
            and cmd.reservation_id == reservation.id
            and not reboot
            and data.physical_state == "reserved"
        ):
            if reservation.status == "pending_device":
                reservation.status = "confirmed"
                reservation.expires_at = now() + timedelta(minutes=RESERVATION_MINUTES)
            compatible = True
        elif (
            cmd.type == "START"
            and session
            and session.status == "starting"
            and not reboot
            and data.session_id == session.id
            and data.physical_state == "charging"
            and data.connected
        ):
            session.status = "charging"
            session.started_at = now()
            live_power.on_start_applied(db, session, cmd, data)
            compatible = True
        elif (
            cmd.type == "STOP"
            and session
            and (data.session_id == session.id or (data.session_id is None and data.energy_wh == 0))
            and data.physical_state in ("idle", "stopped", "fault")
        ):
            finish(session, data, cmd.parameters.get("reason") or "requested_stop")
            compatible = True
        elif cmd.type == "RELEASE" and data.physical_state in ("idle", "stopped") and not data.connected:
            if reservation and reservation.status == "cancelling":
                reservation.status = "expired" if cmd.parameters.get("reason") == "expired" else "cancelled"
            compatible = True
        if compatible:
            cmd.status = "applied"
            device.reconciled = True
            if cmd.session_id:
                record_session_event(db, db.get(ChargingSession, cmd.session_id),
                                     f"{cmd.type.lower()}_applied", "device_sync", f"applied:{cmd.id}")
                if cmd.type == "STOP":
                    record_session_event(db, db.get(ChargingSession, cmd.session_id),
                                         "ended", "device_sync", f"ended:{cmd.session_id}")
    if data.session_id and not terminal_replay:
        reported = db.get(ChargingSession, data.session_id)
        reported.energy_wh = energy_wh
        reported.soc_percent = _current_soc(reported, soc_percent, energy_wh)
        reported.source = data.source
        reported.last_measurement_at = now()
        live_power.observe(reported, device, data)
        reported.cost_estimate = (
            energy_wh
            / Decimal(1000)
            * reported.price_per_kwh
            * Decimal(100 - reported.discount_percent)
            / Decimal(100)
        ).quantize(Decimal("0.0001"))
        if reported.status in ("charging", "stopping") and data.physical_state in (
            "stopped",
            "idle",
            "fault",
        ):
            finish(reported, data, "device_stopped")
            record_session_event(db, reported, "ended", "device_sync", f"ended:{reported.id}")
            for cmd in db.scalars(
                select(Command).where(
                    Command.session_id == reported.id, Command.status.in_(("pending", "received"))
                )
            ):
                cmd.status = "superseded"
            device.reconciled = True
        elif reported.status == "charging" and session and session.id == reported.id:
            stop_if_battery_full(db, connector, device, reported)
    recover_safety_command(db, connector, device, reservation, session)
    restore_reservation(db, connector, device, reservation, session, reboot)
    # Permanência após a recarga: abre/acumula/fecha antes do acerto do pagamento deste sync.
    overstay.on_sync(db, connector, data, reboot=reboot,
                     finished=[session] if session is not None and session.status in overstay.TERMINAL else [])
    prepare_recent_settlements(db, connector)
    pending = db.scalar(
        select(Command.id).where(
            Command.device_id == device.id,
            Command.status.in_(("pending", "received")),
            Command.expires_at > now(),
        )
    )
    if (
        not active_res(db, connector.id)
        and not active_session(db, connector.id)
        and not pending
        and data.physical_state in ("idle", "stopped")
        and not data.connected
    ):
        device.reconciled = True
    if (
        session
        and session.status == "starting"
        and data.physical_state == "charging"
        and data.session_id == session.id
    ):
        # Physical activity without a valid START acknowledgement remains blocked.
        device.reconciled = False
    if was_offline and session and data.session_id == session.id and device.reconciled:
        sync_key = hashlib.sha256(f"{data.boot_id}:{data.sequence}".encode()).hexdigest()
        record_session_event(db, session, "offline_reconciled", "device_sync",
                             f"reconciled:{sync_key}")
    last_sample = db.scalar(
        select(Telemetry)
        .where(Telemetry.device_id == device.id)
        .order_by(Telemetry.received_at.desc())
        .limit(1)
    )
    if (
        not last_sample
        or last_sample.received_at < now() - timedelta(seconds=30)
        or old_state != data.physical_state
        or data.acks
        or data.end_reason
    ):
        db.add(
            Telemetry(
                device_id=device.id,
                session_id=data.session_id,
                boot_id=data.boot_id,
                sequence=data.sequence,
                captured_at=data.captured_at,
                data=data.model_dump(mode="json"),
            )
        )
    live_power.after_sync(db, connector, device, active_session(db, connector.id))
    db.flush()
    result = response(db, connector, device)
    if completed_reset_id:
        result["factory_reset_confirmed"] = completed_reset_id
    return result


def _current_soc(session, reported_soc, energy_wh):
    """Device SoC wins for simulated/legacy sessions; the phone owns ``phone`` sessions."""
    if session.soc_source == "phone":
        return session.soc_percent
    if reported_soc is not None:
        return reported_soc
    if session.soc_source == "simulated":
        derived = derived_soc(session, energy_wh)
        return derived if derived is not None else session.soc_percent
    return None


def _soc_changed(session, reported_soc):
    """Final-result immutability for replays. With battery data the stored SoC may be
    API-derived or phone-reported, so only an explicit, different device value conflicts."""
    if session.soc_source is None:
        return reported_soc != session.soc_percent
    if session.soc_source == "phone" or reported_soc is None:
        return False
    return reported_soc != session.soc_percent


def recover_safety_command(db, connector, device, reservation, session):
    """A failed/expired safety command is not proof that its operation ended.

    Retry only the current version and its still-active resource. An old failed
    STOP/RELEASE must never supersede a newer START or a different reservation.
    """
    command = db.scalar(
        select(Command).where(
            Command.device_id == device.id,
            Command.version == connector.control_version,
            Command.type.in_(("STOP", "RELEASE")),
            Command.status.in_(("pending", "received", "failed")),
        )
    )
    if not command or (command.status != "failed" and command.expires_at > now()):
        return
    if command.type == "STOP":
        if not session or session.status != "stopping" or command.session_id != session.id:
            return
        reservation = None
    else:
        if not reservation or reservation.status != "cancelling" or command.reservation_id != reservation.id:
            return
        session = None
    issue(db, connector, device, command.type, reservation=reservation, session=session,
          parameters=command.parameters)


def restore_reservation(db, connector, device, reservation, session, reboot):
    if session or not reservation or reservation.status not in ("pending_device", "confirmed"):
        return
    deadline = (
        reservation.expires_at if reservation.status == "confirmed" else reservation.confirmation_deadline
    )
    if not deadline or deadline <= now():
        return
    if not reboot and device.physical_state == "reserved" and device.reconciled:
        return
    command = db.scalar(
        select(Command).where(
            Command.device_id == device.id,
            Command.reservation_id == reservation.id,
            Command.type == "RESERVE",
            Command.version == connector.control_version,
            Command.status.in_(("pending", "received")),
            Command.expires_at > now(),
        )
    )
    device.reconciled = False
    if command and not reboot:
        return
    issue(
        db,
        connector,
        device,
        "RESERVE",
        reservation=reservation,
        parameters={"expires_at": (reservation.expires_at or now() + timedelta(minutes=RESERVATION_MINUTES)).isoformat()},
    )


def finish(session, data, fallback):
    # A battery-full stop was decided by the API; the device's own reason
    # (often a generic "requested_stop") must not overwrite it.
    reason = BATTERY_FULL if session.end_reason == BATTERY_FULL else (data.end_reason or fallback)
    session.status = (
        "failed"
        if data.physical_state == "fault" or session.started_at is None
        else ("interrupted" if reason in ("communication_lost", "device_reboot") else "completed")
    )
    session.ended_at = now()
    session.end_reason = reason


def _number(value):
    return float(value) if value is not None else None


def battery_parameters(session):
    """Car battery fields as plain JSON numbers for the firmware (``as<float>()``)."""
    return {
        "soc_percent": _number(session.soc_percent),
        "battery_kwh": _number(session.battery_kwh),
        "soc_source": session.soc_source,
    }


def _battery(session):
    return battery_parameters(session) | {
        "start_soc_percent": _number(session.start_soc_percent),
        "max_power_kw": _number(session.power_limit_kw),
    }


def response(db, connector, device):
    from ..kiosk_totem import service as totem  # evita import circular (totem → pagamentos → início)

    station = db.get(Station, connector.station_id)
    # Totem (só com kiosk_mode no posto): avança o pedido aberto deste ponto, sem chamar a Stripe.
    kiosk = totem.sync_blocks(db, connector, station)
    response_time = now()
    presence_code, presence_expires_at = current_code(station, response_time)
    reservation = active_res(db, connector.id)
    session = active_session(db, connector.id)
    commands = db.scalars(
        select(Command)
        .where(
            Command.device_id == device.id,
            Command.status.in_(("pending", "received")),
            Command.expires_at > now(),
        )
        .order_by(Command.version)
    ).all()
    result = {
        "server_time": response_time.isoformat(),
        # Sessão, reserva, comando pendente ou pedido do totem aberto: 1 s para app e totem
        # mostrarem os mesmos números e o START/STOP chegar logo; ocioso: 5 s.
        "sync_interval_seconds": 1 if session or reservation or commands or (kiosk and kiosk["open"]) else 5,
        "control_version": connector.control_version,
        # Permanência aberta neste ponto (painel: "desconecte em mm:ss" / taxa), ou null.
        "overstay": overstay.sync_block(db, connector),
        "connector": {
            "id": str(connector.id),
            "public_code": connector.public_code,
            "max_duration_minutes": connector.max_duration_minutes,
            "owned": station.owner_id is not None,
            "active": bool(connector.active and station.active),
            "presence_code": presence_code if connector.active and station.active and station.owner_id else None,
            "presence_expires_at": presence_expires_at.isoformat(),
            # Carregador externo que a tela deve controlar (Modbus TCP, unit id = endereço), ou null.
            "charger_link": charger_link.sync_link(connector.charger_address),
            **payment_device_fields(db, connector, station),
            **({"kiosk": kiosk["kiosk"]} if kiosk else {}),
        },
        "authorized": {
            "reservation": (
                {
                    "id": str(reservation.id),
                    "status": reservation.status,
                    "expires_at": (reservation.expires_at or reservation.confirmation_deadline).isoformat(),
                }
                if reservation and reservation.status in ("confirmed", "pending_device")
                else None
            ),
            "session": (
                {
                    key: row(session)[key]
                    for key in (
                        "id",
                        "status",
                        "max_duration_minutes",
                        "max_cost",
                        "price_per_kwh",
                        "discount_percent",
                    )
                }
                | _battery(session)
                | live_power.sync_fields(session)
                # Quem iniciou: app, QR de pagamento do painel ou pedido do totem.
                | {"origin": totem.session_origin(db, session)}
                if session
                else None
            ),
        },
        "commands": [
            {
                key: row(cmd)[key]
                for key in (
                    "id",
                    "type",
                    "version",
                    "expires_at",
                    "reservation_id",
                    "session_id",
                    "parameters",
                )
            }
            for cmd in commands
        ],
    }
    if kiosk:
        # Pedido do totem deste ponto (aberto, em recarga ou fechado há até 10 min), ou null.
        result["kiosk_order"] = kiosk["order"]
    return result
