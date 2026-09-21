from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select

from ...errors import fail
from ...models import ChargingSession, Command, Connector, Device, DeviceBoot, Station, Telemetry, now
from ...service import active_res, active_session, issue, reconcile_expiry, row


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
                or data.soc_percent != reported.soc_percent
                or data.source != reported.source
                or data.physical_state not in ("idle", "stopped", "fault")
            ):
                fail("session_finished", "Resultado final da sessão é imutável")
    elif data.physical_state == "charging" or data.energy_wh or data.soc_percent is not None:
        fail("session_required", "Medição de recarga exige session_id", 422)
    expired = db.scalar(
        select(Command)
        .where(
            Command.device_id == device.id,
            Command.status.in_(("pending", "received")),
            Command.expires_at <= now(),
        )
        .order_by(Command.version.desc())
        .limit(1)
    )
    if expired and expired.type in ("STOP", "RELEASE"):
        issue(
            db,
            connector,
            device,
            expired.type,
            reservation=reservation if expired.type == "RELEASE" else None,
            session=session if expired.type == "STOP" else None,
            parameters=expired.parameters,
        )
    reboot = device.boot_id is not None and not same_boot
    old_state = device.physical_state
    device.boot_id = data.boot_id
    device.sequence = data.sequence
    device.last_seen = now()
    device.firmware_version = data.firmware_version
    device.physical_state = data.physical_state
    device.connected = data.connected
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
            cmd.status = "received"
            continue
        if ack.status == "failed":
            cmd.status = "failed"
            cmd.error = ack.error
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
                reservation.expires_at = now() + timedelta(minutes=10)
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
    if data.session_id and not terminal_replay:
        reported = db.get(ChargingSession, data.session_id)
        reported.energy_wh = energy_wh
        reported.soc_percent = data.soc_percent
        reported.source = data.source
        reported.last_measurement_at = now()
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
            for cmd in db.scalars(
                select(Command).where(
                    Command.session_id == reported.id, Command.status.in_(("pending", "received"))
                )
            ):
                cmd.status = "superseded"
            device.reconciled = True
    restore_reservation(db, connector, device, reservation, session, reboot)
    pending = db.scalar(
        select(Command.id).where(Command.device_id == device.id, Command.status.in_(("pending", "received")))
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
    db.flush()
    return response(db, connector, device)


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
        parameters={"expires_at": (reservation.expires_at or now() + timedelta(minutes=10)).isoformat()},
    )


def finish(session, data, fallback):
    reason = data.end_reason or fallback
    session.status = (
        "failed"
        if data.physical_state == "fault" or session.started_at is None
        else ("interrupted" if reason in ("communication_lost", "device_reboot") else "completed")
    )
    session.ended_at = now()
    session.end_reason = reason


def response(db, connector, device):
    station = db.get(Station, connector.station_id)
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
    return {
        "server_time": now().isoformat(),
        "sync_interval_seconds": 5 if session else 10,
        "control_version": connector.control_version,
        "connector": {
            "id": str(connector.id),
            "public_code": connector.public_code,
            "max_duration_minutes": connector.max_duration_minutes,
            "owned": station.owner_id is not None,
            "active": bool(connector.active and station.active),
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
