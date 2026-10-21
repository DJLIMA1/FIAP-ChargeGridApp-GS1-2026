"""An audit trail records accepted facts once and exposes only the owner's session."""

from datetime import timedelta

from sqlalchemy import select
from test_http import clear_overrides, client_for

from app.models import Command, Device, Profile, SessionEvent, Station, now
from app.modules.charging.service import start, stop
from app.modules.devices.service import sync
from app.presence_code import current_code
from app.schemas import StartInput, SyncInput


def sync_data(sequence, **changes):
    values = dict(
        boot_id="events-boot", sequence=sequence, firmware_version="test",
        physical_state="idle", connected=False, source="simulated", captured_at=now(),
    )
    values.update(changes)
    return SyncInput(**values)


def device_sync(factory, seed, data):
    with factory.begin() as db:
        return sync(db, db.get(Device, seed["device"]), data)


def events(factory):
    with factory() as db:
        return [(item.kind, item.source) for item in db.scalars(select(SessionEvent).order_by(SessionEvent.id))]


def test_request_ack_retry_reconcile_end_and_owner_isolation(factory, seed):
    device_sync(factory, seed, sync_data(1))
    with factory.begin() as db:
        user = db.get(Profile, seed["a"])
        payload = StartInput(public_code="CG-01", presence_code=current_code(db.get(Station, seed["station"]))[0])
        session = start(db, user, payload, "start-key")
        assert start(db, user, payload, "start-key").id == session.id
        session_id = session.id
        command_id = db.scalar(select(Command).where(Command.session_id == session_id)).id
    assert events(factory) == [("start_requested", "api")]

    received = sync_data(2, acks=[{"command_id": command_id, "status": "received"}])
    device_sync(factory, seed, received)
    device_sync(factory, seed, received)
    device_sync(factory, seed, sync_data(3, acks=[{"command_id": command_id, "status": "received"}]))
    applied = sync_data(4, physical_state="charging", connected=True, session_id=session_id,
                        acks=[{"command_id": command_id, "status": "applied"}])
    device_sync(factory, seed, applied)
    device_sync(factory, seed, applied)
    # Rebalanceamento ligado por padrão: o START confirmado também registra a potência aplicada.
    assert events(factory) == [
        ("start_requested", "api"), ("command_received", "device_sync"),
        ("power_applied", "device_sync"), ("start_applied", "device_sync"),
    ]

    with factory.begin() as db:
        db.get(Device, seed["device"]).last_seen = now() - timedelta(minutes=2)
    device_sync(factory, seed, sync_data(5, physical_state="charging", connected=True,
                                     session_id=session_id))
    with factory.begin() as db:
        user = db.get(Profile, seed["a"])
        stop(db, user, session_id, "stop-key")
        stop(db, user, session_id, "stop-key")
        stop_id = db.scalar(select(Command).where(Command.session_id == session_id,
                                                   Command.type == "STOP")).id
    ended = sync_data(6, physical_state="stopped", session_id=session_id,
                      acks=[{"command_id": stop_id, "status": "applied"}])
    device_sync(factory, seed, ended)
    device_sync(factory, seed, ended)
    assert [kind for kind, _ in events(factory)] == [
        "start_requested", "command_received", "power_applied", "start_applied", "offline_reconciled",
        "stop_requested", "stop_applied", "ended",
        # Cable reported disconnected at the end: no overstay, the final amount is known.
        "vehicle_disconnected", "settlement_ready",
    ]

    client, selected = client_for(factory, seed["a"])
    try:
        response = client.get(f"/v1/charging-sessions/{session_id}/events")
        assert response.status_code == 200
        assert [item["kind"] for item in response.json()] == [kind for kind, _ in events(factory)]
        assert all(item["observed_at"] and item["source"] for item in response.json())
        assert all(set(item) == {"kind", "source", "observed_at"} for item in response.json())
        selected["id"] = seed["b"]
        assert client.get(f"/v1/charging-sessions/{session_id}/events").status_code == 404
    finally:
        clear_overrides()


def test_unacknowledged_activity_does_not_claim_start(factory, seed):
    device_sync(factory, seed, sync_data(1))
    with factory.begin() as db:
        user = db.get(Profile, seed["a"])
        session = start(db, user, StartInput(public_code="CG-01", presence_code=current_code(
            db.get(Station, seed["station"]))[0]), "s")
        session_id = session.id
    device_sync(factory, seed, sync_data(2, physical_state="charging", connected=True,
                                     session_id=session_id))
    assert events(factory) == [("start_requested", "api")]


def test_failed_ack_is_recorded_once_without_start_confirmation(factory, seed):
    device_sync(factory, seed, sync_data(1))
    with factory.begin() as db:
        user = db.get(Profile, seed["a"])
        session = start(db, user, StartInput(public_code="CG-01", presence_code=current_code(
            db.get(Station, seed["station"]))[0]), "s")
        command_id = db.scalar(select(Command).where(Command.session_id == session.id)).id
    failed = sync_data(2, acks=[{"command_id": command_id, "status": "failed", "error": "hardware_fault"}])
    device_sync(factory, seed, failed)
    device_sync(factory, seed, failed)
    device_sync(factory, seed, sync_data(3, acks=[{"command_id": command_id, "status": "failed"}]))
    assert [kind for kind, _ in events(factory)] == [
        "start_requested", "command_failed", "stop_requested",
    ]
