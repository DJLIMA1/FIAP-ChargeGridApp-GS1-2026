from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.database import db_session
from app.http_helpers import point_row
from app.main import app
from app.models import ChargingSession, Command, Connector, Device, DeviceClaim, Profile, Station, now
from app.modules.users.routes import monthly_bounds
from app.security import current_user, digest


def client_for(factory, user_id):
    selected = {"id": user_id}

    def database():
        with factory() as db:
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    def user():
        with factory() as db:
            return db.get(Profile, selected["id"])

    app.dependency_overrides[db_session] = database
    app.dependency_overrides[current_user] = user
    return TestClient(app), selected


def clear_overrides():
    app.dependency_overrides.clear()


def test_monthly_bounds_use_sao_paulo_calendar():
    month, start, end = monthly_bounds(datetime(2026, 3, 15, 12, tzinfo=timezone.utc))
    assert month == "2026-03"
    assert start == datetime(2026, 3, 1, 3, tzinfo=timezone.utc)
    assert end == datetime(2026, 4, 1, 3, tzinfo=timezone.utc)


def test_me_summary_month_boundaries_and_user_isolation(factory, seed):
    month, start, end = monthly_bounds()
    with factory.begin() as db:
        rows = [
            (seed["a"], "completed", start, Decimal("1000.000"), Decimal("2.5000")),
            (
                seed["a"],
                "interrupted",
                end - timedelta(microseconds=1),
                Decimal("250.000"),
                Decimal("0.6250"),
            ),
            (
                seed["a"],
                "completed",
                start - timedelta(microseconds=1),
                Decimal("9000.000"),
                Decimal("90.0000"),
            ),
            (seed["a"], "completed", end, Decimal("8000.000"), Decimal("80.0000")),
            (seed["a"], "failed", start, Decimal("0.000"), Decimal("0.0000")),
            (seed["b"], "completed", start, Decimal("7000.000"), Decimal("70.0000")),
        ]
        for user_id, status, ended_at, energy_wh, cost in rows:
            db.add(
                ChargingSession(
                    user_id=user_id,
                    connector_id=seed["point"],
                    status=status,
                    started_at=ended_at - timedelta(minutes=10),
                    ended_at=ended_at,
                    max_duration_minutes=30,
                    price_per_kwh=Decimal("2.5000"),
                    energy_wh=energy_wh,
                    discount_percent=0,
                    cost_estimate=cost,
                )
            )
    client, _ = client_for(factory, seed["a"])
    try:
        response = client.get("/v1/me/summary")
        assert response.status_code == 200
        assert response.json() == {
            "month": month,
            "currency": "BRL",
            "estimated_cost": "3.1250",
            "energy_wh": "1250.000",
            "sessions_count": 2,
        }
    finally:
        clear_overrides()


def sync_payload(sequence, **changes):
    data = {
        "boot_id": "http-boot",
        "sequence": sequence,
        "firmware_version": "test",
        "session_id": None,
        "physical_state": "idle",
        "connected": False,
        "soc_percent": None,
        "energy_wh": 0,
        "power_w": 0,
        "source": "simulated",
        "captured_at": now().isoformat(),
        "end_reason": None,
        "acks": [],
    }
    data.update(changes)
    return data


def test_http_reserve_charge_stop_history(factory, seed):
    client, _ = client_for(factory, seed["a"])
    try:
        response = client.post(
            "/v1/reservations",
            headers={"Idempotency-Key": "reserve-http"},
            json={"connector_id": str(seed["point"])},
        )
        assert response.status_code == 202
        reservation_id = response.json()["id"]

        first = client.post(
            "/v1/devices/sync", headers={"Authorization": "Device test-key"}, json=sync_payload(1)
        )
        reserve_command = first.json()["commands"][0]
        confirmed = client.post(
            "/v1/devices/sync",
            headers={"Authorization": "Device test-key"},
            json=sync_payload(
                2,
                physical_state="reserved",
                acks=[{"command_id": reserve_command["id"], "status": "applied", "error": None}],
            ),
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["authorized"]["reservation"]["status"] == "confirmed"

        started = client.post(
            "/v1/charging-sessions",
            headers={"Idempotency-Key": "start-http"},
            json={
                "public_code": "CG-01",
                "reservation_id": reservation_id,
                "max_duration_minutes": 20,
            },
        )
        assert started.status_code == 202
        session_id = started.json()["id"]
        command = client.post(
            "/v1/devices/sync",
            headers={"Authorization": "Device test-key"},
            json=sync_payload(3, physical_state="reserved"),
        ).json()["commands"][0]
        charging = client.post(
            "/v1/devices/sync",
            headers={"Authorization": "Device test-key"},
            json=sync_payload(
                4,
                physical_state="charging",
                connected=True,
                session_id=session_id,
                energy_wh=25,
                soc_percent=40,
                acks=[{"command_id": command["id"], "status": "applied", "error": None}],
            ),
        )
        assert charging.status_code == 200
        assert charging.json()["authorized"]["session"]["status"] == "charging"

        stopped = client.post(
            f"/v1/charging-sessions/{session_id}/stop",
            headers={"Idempotency-Key": "stop-http"},
        )
        assert stopped.status_code == 202
        stop_command = client.post(
            "/v1/devices/sync",
            headers={"Authorization": "Device test-key"},
            json=sync_payload(
                5,
                physical_state="charging",
                connected=True,
                session_id=session_id,
                energy_wh=25,
                soc_percent=40,
            ),
        ).json()["commands"][0]
        final = client.post(
            "/v1/devices/sync",
            headers={"Authorization": "Device test-key"},
            json=sync_payload(
                6,
                physical_state="stopped",
                session_id=session_id,
                energy_wh=30,
                soc_percent=41,
                end_reason="requested",
                acks=[{"command_id": stop_command["id"], "status": "applied", "error": None}],
            ),
        )
        assert final.status_code == 200
        assert final.json()["authorized"]["session"] is None
        history = client.get("/v1/me/charging-sessions")
        assert history.status_code == 200
        assert history.json()["items"][0]["status"] == "completed"
        assert history.json()["items"][0]["energy_wh"] == "30.000"
    finally:
        clear_overrides()


def test_http_authorization_isolation(factory, seed):
    with factory.begin() as db:
        operator_b = db.get(Profile, seed["b"])
        operator_b.operator_enabled = True
        other_station = Station(
            owner_id=operator_b.id,
            name="Other",
            address="Private",
            latitude=1,
            longitude=1,
        )
        db.add(other_station)
        session = ChargingSession(
            user_id=seed["b"],
            connector_id=seed["point"],
            status="completed",
            max_duration_minutes=10,
            price_per_kwh=1,
            energy_wh=0,
            discount_percent=0,
            cost_estimate=0,
        )
        db.add(session)
        db.flush()
        station_id = other_station.id
        session_id = session.id
    client, selected = client_for(factory, seed["a"])
    try:
        assert client.get(f"/v1/charging-sessions/{session_id}").status_code == 404
        selected["id"] = seed["owner"]
        assert client.patch(f"/v1/stations/{station_id}", json={"name": "Taken"}).status_code == 404
    finally:
        clear_overrides()


def test_revoked_device_and_safe_validation(factory, seed):
    client, _ = client_for(factory, seed["a"])
    try:
        with factory.begin() as db:
            db.get(Device, seed["device"]).revoked = True
        assert (
            client.post(
                "/v1/devices/sync",
                headers={"Authorization": "Device test-key"},
                json=sync_payload(1),
            ).status_code
            == 401
        )
        secret = "short"
        invalid = client.post(
            "/v1/auth/register", json={"email": "person@example.com", "password": secret, "name": "A"}
        )
        assert invalid.status_code == 422
        assert secret not in invalid.text
        assert "input" not in invalid.text
    finally:
        clear_overrides()


def test_invalid_jwt_is_rejected_without_bypass(factory, seed):
    def database():
        with factory() as db:
            yield db

    app.dependency_overrides[db_session] = database
    try:
        response = TestClient(app).get("/v1/me", headers={"Authorization": "Bearer invalid"})
        assert response.status_code == 401
    finally:
        clear_overrides()


def test_history_is_chronological_not_uuid_order(factory, seed):
    older_id = UUID("ffffffff-ffff-4fff-bfff-ffffffffffff")
    newer_id = UUID("00000000-0000-4000-8000-000000000001")
    with factory.begin() as db:
        for session_id, age in ((older_id, 2), (newer_id, 1)):
            db.add(
                ChargingSession(
                    id=session_id,
                    user_id=seed["a"],
                    connector_id=seed["point"],
                    status="completed",
                    created_at=now() - timedelta(days=age),
                    started_at=now() - timedelta(days=age),
                    ended_at=now() - timedelta(days=age),
                    max_duration_minutes=10,
                    price_per_kwh=1,
                )
            )
    client, selected = client_for(factory, seed["a"])
    try:
        history = client.get("/v1/me/charging-sessions", params={"limit": 1})
        assert history.json()["total"] == 2
        assert history.json()["items"][0]["id"] == str(newer_id)
        second = client.get("/v1/me/charging-sessions", params={"limit": 1, "offset": 1})
        assert second.json()["items"][0]["id"] == str(older_id)
        selected["id"] = seed["owner"]
        station_history = client.get(f"/v1/stations/{seed['station']}/charging-sessions")
        assert [item["id"] for item in station_history.json()["items"]] == [str(newer_id), str(older_id)]
    finally:
        clear_overrides()


@pytest.mark.parametrize("device_present", [True, False])
def test_point_serialization_fetches_device_once(factory, seed, device_present):
    with factory.begin() as db:
        if not device_present:
            db.get(Device, seed["device"]).revoked = True
            db.flush()
        connector = db.get(Connector, seed["point"])
        connection = db.connection()
        queries = []

        def record(_connection, _cursor, statement, _parameters, _context, _executemany):
            queries.append(statement)

        event.listen(connection, "before_cursor_execute", record)
        try:
            result = point_row(db, connector)
        finally:
            event.remove(connection, "before_cursor_execute", record)
        assert sum("FROM devices" in statement for statement in queries) == 1
        assert result["available"] is device_present
        assert result["online"] is device_present


def test_owner_can_rediscover_device_without_secrets_after_provisioning(factory, seed):
    client, _ = client_for(factory, seed["owner"])
    endpoint = f"/v1/connectors/{seed['point']}/device"
    try:
        first = client.get(endpoint)
        assert first.status_code == 200
        assert first.json()["device_id"] == str(seed["device"])
        assert set(first.json()) == {
            "device_id",
            "connector_id",
            "firmware_version",
            "last_seen",
            "online",
            "physical_state",
            "connected",
            "reconciled",
            "retired",
        }
        assert "test-key" not in first.text and "key_hash" not in first.text
        assert first.json()["online"] is True
        assert client.post(f"/v1/devices/{seed['device']}/revoke").status_code == 200
        assert client.get(endpoint).status_code == 404
        provisioned = client.post(endpoint)
        assert provisioned.status_code == 201
        again = client.get(endpoint)
        assert again.status_code == 200
        assert again.json()["device_id"] == provisioned.json()["device_id"]
        assert again.json()["device_id"] != str(seed["device"])
        assert provisioned.json()["device_key"] not in again.text
        assert again.json()["online"] is False
    finally:
        clear_overrides()


def test_device_discovery_requires_approved_owner(factory, seed):
    with factory.begin() as db:
        db.get(Profile, seed["b"]).operator_enabled = True
    client, selected = client_for(factory, seed["a"])
    endpoint = f"/v1/connectors/{seed['point']}/device"
    try:
        assert client.get(endpoint).status_code == 403
        selected["id"] = seed["b"]
        assert client.get(endpoint).status_code == 404
        selected["id"] = seed["owner"]
        assert client.get("/v1/connectors/00000000-0000-4000-8000-000000000000/device").status_code == 404
    finally:
        clear_overrides()


@pytest.mark.parametrize("revoked", [False, True])
def test_device_discovery_missing_or_revoked_is_not_found(factory, seed, revoked):
    with factory.begin() as db:
        device = db.get(Device, seed["device"])
        if revoked:
            device.revoked = True
        else:
            db.delete(device)
    client, _ = client_for(factory, seed["owner"])
    try:
        response = client.get(f"/v1/connectors/{seed['point']}/device")
        assert response.status_code == 404
        assert "device_id" not in response.text and "key_hash" not in response.text
    finally:
        clear_overrides()


def test_factory_reset_requires_owner_idle_recent_firmware_and_confirmed_ack(factory, seed):
    with factory.begin() as db:
        db.get(Device, seed["device"]).firmware_version = "0.3.5"
    client, selected = client_for(factory, seed["a"])
    endpoint = f"/v1/devices/{seed['device']}/factory-reset"
    try:
        assert client.post(endpoint).status_code == 403
        selected["id"] = seed["owner"]
        started = client.post(endpoint)
        assert started.status_code == 202
        assert started.json()["status"] == "pending"
        command_id = started.json()["command_id"]
        assert client.post(endpoint).json()["command_id"] == command_id
        assert client.get(endpoint).json()["status"] == "pending"
        assert client.patch(f"/v1/connectors/{seed['point']}", json={"active": True}).status_code == 409
        assert client.post(f"/v1/connectors/{seed['point']}/device").status_code == 409
        with factory() as db:
            assert not db.get(Connector, seed["point"]).active
            assert db.get(Command, UUID(command_id)).parameters == {}

        delivered = client.post(
            "/v1/devices/sync", headers={"Authorization": "Device test-key"},
            json=sync_payload(1, firmware_version="0.3.5"),
        )
        assert delivered.status_code == 200
        assert [item["type"] for item in delivered.json()["commands"]] == ["FACTORY_RESET"]
        new_key, new_claim = "new-private-device-key", "new-private-claim-token"
        confirmed = client.post(
            "/v1/devices/sync", headers={"Authorization": "Device test-key"},
            json=sync_payload(2, firmware_version="0.3.5", acks=[{
                "command_id": command_id, "status": "applied", "error": None,
                "new_device_key_hash": digest(new_key), "new_claim_token_hash": digest(new_claim),
            }]),
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["factory_reset_confirmed"] == command_id
        assert new_key not in confirmed.text and new_claim not in confirmed.text
        assert client.get(endpoint).json()["status"] == "applied"
        assert client.post(endpoint).status_code == 409
        retired = client.get(f"/v1/connectors/{seed['point']}/device")
        assert retired.status_code == 200 and retired.json()["retired"] is True
        assert client.post(f"/v1/connectors/{seed['point']}/device").status_code == 409
        with factory() as db:
            old = db.get(Device, seed["device"])
            assert old.revoked
            assert db.get(Station, seed["station"]).owner_id == seed["owner"]
            assert not db.get(Connector, seed["point"]).active
            fresh = db.query(Device).filter_by(key_hash=digest(new_key)).one()
            claim = db.get(DeviceClaim, fresh.connector_id)
            new_point = db.get(Connector, fresh.connector_id)
            assert claim.token_hash == digest(new_claim) and claim.claimed_by is None
            assert db.get(Station, new_point.station_id).owner_id is None
            assert not new_point.active
    finally:
        clear_overrides()


def test_factory_reset_rejects_old_firmware_and_active_reservation(factory, seed):
    client, _ = client_for(factory, seed["owner"])
    endpoint = f"/v1/devices/{seed['device']}/factory-reset"
    try:
        assert client.post(endpoint).status_code == 409
        with factory.begin() as db:
            db.get(Device, seed["device"]).firmware_version = "0.3.5"
        reservation = client_for(factory, seed["a"])
        selected = reservation[1]
        selected["id"] = seed["a"]
        created = reservation[0].post(
            "/v1/reservations", headers={"Idempotency-Key": "factory-reset-busy"},
            json={"connector_id": str(seed["point"])},
        )
        assert created.status_code == 202
        selected["id"] = seed["owner"]
        assert reservation[0].post(endpoint).status_code == 409
    finally:
        clear_overrides()
