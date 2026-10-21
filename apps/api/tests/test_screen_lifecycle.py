"""A screen's credentials/reset must remain safe for every charger it commands."""

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import text
from test_http import clear_overrides, client_for, sync_payload
from test_station_chargers import DEVICE, _add, _code, _sync

from app.models import ChargingSession, Connector, Device, Reservation, now
from app.modules.devices import routes as device_routes
from app.security import digest


@pytest.fixture
def screen(factory, seed):
    client, selected = client_for(factory, seed["owner"])
    child = _add(client, seed["point"])
    assert client.patch(f"/v1/connectors/{child['id']}", json={"active": True}).status_code == 200
    assert _sync(client, 1, firmware_version="0.8.0").status_code == 200
    assert _sync(client, 1, address=2, firmware_version="0.8.0").status_code == 200
    yield client, selected, child
    clear_overrides()


def start_child(client, factory, seed, child, key="child-start", **extra):
    return client.post("/v1/charging-sessions", headers={"Idempotency-Key": key}, json={
        "public_code": child["public_code"], "presence_code": _code(factory, seed), **extra})


def reset_ack(client, reset, sequence=2):
    return client.post("/v1/devices/sync", headers=DEVICE, json=sync_payload(
        sequence, firmware_version="0.8.0", acks=[{
            "command_id": reset.json()["command_id"], "status": "applied",
            "new_device_key_hash": digest("replacement-key"),
            "new_claim_token_hash": digest("replacement-claim"),
        }]))


@pytest.mark.parametrize("action", ["rotate-key", "revoke", "factory-reset"])
@pytest.mark.parametrize("busy", ["session", "reservation"])
def test_screen_credentials_require_all_chargers_free(screen, factory, seed, action, busy):
    client, selected, child = screen
    selected["id"] = seed["a"]
    if busy == "session":
        started = start_child(client, factory, seed, child)
        assert started.status_code == 202, started.text
        command = _sync(client, 2, address=2).json()["commands"][0]
        applied = _sync(client, 3, address=2, physical_state="charging", connected=True,
                        session_id=started.json()["id"],
                        acks=[{"command_id": command["id"], "status": "applied"}])
        assert applied.status_code == 200, applied.text
    else:
        reserved = client.post("/v1/reservations", headers={"Idempotency-Key": "child-reserve"},
                               json={"connector_id": child["id"]})
        assert reserved.status_code == 202, reserved.text
    selected["id"] = seed["owner"]
    refused = client.post(f"/v1/devices/{seed['device']}/{action}")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "point_busy"
    # Refusing the lifecycle operation must leave the key and reconciliation channel usable.
    assert _sync(client, 4, address=2).status_code == 200
    with factory() as db:
        assert not db.get(Device, seed["device"]).revoked


def test_pending_reset_blocks_child_start_reserve_publish_and_add(screen, factory, seed):
    client, selected, child = screen
    reset = client.post(f"/v1/devices/{seed['device']}/factory-reset")
    assert reset.status_code == 202, reset.text
    selected["id"] = seed["a"]
    assert start_child(client, factory, seed, child).status_code == 409
    assert client.post("/v1/reservations", headers={"Idempotency-Key": "pending-reserve"},
                       json={"connector_id": child["id"]}).status_code == 409
    selected["id"] = seed["owner"]
    assert client.post(f"/v1/connectors/{child['id']}/chargers").status_code == 409
    assert client.patch(f"/v1/connectors/{child['id']}", json={"active": True}).status_code == 409
    live = client.get("/v1/owner/live").json()["items"]
    assert next(item for item in live if item["connector_id"] == child["id"])["available"] is False
    assert reset_ack(client, reset).status_code == 200
    with factory() as db:
        child_device = db.query(Device).filter(Device.connector_id == uuid.UUID(child["id"])).one()
        assert child_device.revoked and not child_device.reconciled
        assert not db.get(Connector, child_device.connector_id).active
        assert db.get(Device, seed["device"]).revoked


def test_reset_ack_rechecks_dependents_before_revoking(screen, factory, seed):
    client, _, child = screen
    reset = client.post(f"/v1/devices/{seed['device']}/factory-reset")
    assert reset.status_code == 202, reset.text
    # Simulate legacy state or an already-in-flight write from an older API instance.
    with factory.begin() as db:
        db.add(ChargingSession(user_id=seed["a"], connector_id=uuid.UUID(child["id"]), status="charging",
                               started_at=now(), max_duration_minutes=60, price_per_kwh=2, discount_percent=0))
    acknowledged = reset_ack(client, reset)
    assert acknowledged.status_code == 200, acknowledged.text
    with factory() as db:
        from app.models import Command

        command = db.get(Command, uuid.UUID(reset.json()["command_id"]))
        assert command.status == "failed" and command.error == "unsafe_or_missing_factory_credentials"
        assert not db.get(Device, seed["device"]).revoked
    assert _sync(client, 2, address=2).status_code == 200


def test_idle_revoke_retires_children_without_resurrecting_on_provision(screen, factory, seed):
    client, _, child = screen
    revoked = client.post(f"/v1/devices/{seed['device']}/revoke")
    assert revoked.status_code == 200, revoked.text
    replacement = client.post(f"/v1/connectors/{seed['point']}/device")
    assert replacement.status_code == 201, replacement.text
    with factory() as db:
        child_device = db.query(Device).filter(Device.connector_id == uuid.UUID(child["id"])).one()
        assert child_device.revoked and not child_device.reconciled
        assert not db.get(Connector, child_device.connector_id).active
        assert child_device.parent_device_id == seed["device"]  # historical relationship retained
    response = client.post("/v1/devices/sync", headers={
        "Authorization": "Device " + replacement.json()["device_key"]}, json=sync_payload(1))
    assert response.status_code == 200 and response.json()["chargers"] == []


def test_idle_rotation_preserves_children_without_new_physical_state_restrictions(screen, factory, seed):
    client, _, child = screen
    with factory.begin() as db:
        device = db.query(Device).filter(Device.connector_id == uuid.UUID(child["id"])).one()
        device.physical_state = "fault"
        device.connected = True
        device.reconciled = False
    rotated = client.post(f"/v1/devices/{seed['device']}/rotate-key")
    assert rotated.status_code == 200, rotated.text
    response = client.post("/v1/devices/sync", headers={
        "Authorization": "Device " + rotated.json()["device_key"]}, json=sync_payload(2, charger_address=2))
    assert response.status_code == 200, response.text
    with factory() as db:
        assert not db.query(Device).filter(Device.connector_id == uuid.UUID(child["id"])).one().revoked


def test_reserved_child_start_rejects_offline_screen(screen, factory, seed):
    client, selected, child = screen
    with factory.begin() as db:
        db.get(Device, seed["device"]).last_seen = now() - timedelta(seconds=60)
        child_device = db.query(Device).filter(Device.connector_id == uuid.UUID(child["id"])).one()
        child_device.physical_state = "reserved"
        child_device.reconciled = True
        reservation = Reservation(user_id=seed["a"], connector_id=uuid.UUID(child["id"]), status="confirmed",
                                  confirmation_deadline=now() + timedelta(minutes=1),
                                  expires_at=now() + timedelta(minutes=5))
        db.add(reservation)
        db.flush()
        reservation_id = reservation.id
    selected["id"] = seed["a"]
    refused = start_child(client, factory, seed, child, reservation_id=str(reservation_id))
    assert refused.status_code == 409, refused.text
    with factory() as db:
        assert db.get(Reservation, reservation_id).status == "confirmed"
        assert not db.query(ChargingSession).count()


def test_reserved_child_still_starts_after_normal_confirmation(screen, factory, seed):
    client, selected, child = screen
    selected["id"] = seed["a"]
    reserved = client.post("/v1/reservations", headers={"Idempotency-Key": "normal-reserve"},
                           json={"connector_id": child["id"]})
    assert reserved.status_code == 202, reserved.text
    command = _sync(client, 2, address=2).json()["commands"][0]
    confirmed = _sync(client, 3, address=2, physical_state="reserved",
                      acks=[{"command_id": command["id"], "status": "applied"}])
    assert confirmed.status_code == 200, confirmed.text
    started = start_child(client, factory, seed, child, reservation_id=reserved.json()["id"])
    assert started.status_code == 202, started.text
    with factory() as db:
        assert db.get(Reservation, uuid.UUID(reserved.json()["id"])).status == "consumed"


@pytest.mark.parametrize("operation", ["start", "reserve", "add"])
def test_reset_serializes_with_child_operations(screen, factory, seed, monkeypatch, operation):
    client, _, child = screen
    reset_inside = threading.Event()
    release_reset = threading.Event()
    original_issue = device_routes.issue

    def paused_reset_issue(*args, **kwargs):
        if args[3] == "FACTORY_RESET":
            reset_inside.set()
            assert release_reset.wait(10), "test failed to release reset transaction"
        return original_issue(*args, **kwargs)

    monkeypatch.setattr(device_routes, "issue", paused_reset_issue)

    def operation_request():
        if operation == "start":
            return start_child(client, factory, seed, child)
        if operation == "reserve":
            return client.post("/v1/reservations", headers={"Idempotency-Key": "race-reserve"},
                               json={"connector_id": child["id"]})
        return client.post(f"/v1/connectors/{child['id']}/chargers")

    with ThreadPoolExecutor(max_workers=2) as pool:
        reset_job = pool.submit(client.post, f"/v1/devices/{seed['device']}/factory-reset")
        assert reset_inside.wait(10)
        operation_job = pool.submit(operation_request)
        waiting = False
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                with factory() as db:
                    waiting = db.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_locks "
                                             "WHERE locktype = 'advisory' AND NOT granted)"))
                if waiting or operation_job.done():
                    break
                time.sleep(0.01)
        finally:
            release_reset.set()
        reset = reset_job.result(timeout=10)
        result = operation_job.result(timeout=10)
    assert waiting, "child operation did not wait for the screen-group transaction"
    assert reset.status_code == 202, reset.text
    assert result.status_code == 409, result.text
    assert reset_ack(client, reset).status_code == 200
