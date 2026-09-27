from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import TextClause

from app.database import db_session
from app.http_helpers import point_row
from app.main import app
from app.models import (
    ChargingSession,
    Command,
    Connector,
    Coupon,
    Device,
    DeviceClaim,
    Profile,
    Reservation,
    Station,
    now,
)
from app.modules.users.routes import monthly_bounds
from app.presence_code import current_code
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


def test_http_start_with_only_temporary_code(factory, seed):
    client, _ = client_for(factory, seed["a"])
    try:
        code = current_code(_station_for_code(factory, seed))[0]
        response = client.post(
            "/v1/charging-sessions",
            headers={"Idempotency-Key": "temporary-code-only"},
            json={"presence_code": code},
        )
        assert response.status_code == 202
        assert response.json()["connector_id"] == str(seed["point"])
    finally:
        clear_overrides()


def test_http_reserve_charge_stop_history(factory, seed):
    client, _ = client_for(factory, seed["a"])
    try:
        station_response = client.get(f"/v1/stations/{seed['station']}")
        assert station_response.status_code == 200
        assert "presence_secret" not in station_response.json()
        assert "presence_code" not in station_response.json()
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
        current = confirmed.json()["connector"]["presence_code"]
        assert current.startswith("#F")
        outdated = client.post(
            "/v1/charging-sessions",
            headers={"Idempotency-Key": "old-app-http"},
            json={"public_code": "CG-01", "reservation_id": reservation_id},
        )
        assert outdated.status_code == 422
        assert "Atualize o app" in outdated.json()["error"]["message"]
        wrong = "#F00000" if current != "#F00000" else "#F00001"
        rejected = client.post(
            "/v1/charging-sessions",
            headers={"Idempotency-Key": "wrong-presence-http"},
            json={"public_code": "CG-01", "presence_code": wrong, "reservation_id": reservation_id},
        )
        assert rejected.status_code == 422

        started = client.post(
            "/v1/charging-sessions",
            headers={"Idempotency-Key": "start-http"},
            json={
                "presence_code": current_code(_station_for_code(factory, seed))[0],
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
        assert client.post(f"/v1/devices/{seed['device']}/rotate-key").status_code == 409
        assert client.post(f"/v1/devices/{seed['device']}/revoke").status_code == 409
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


def test_factory_reset_refuses_before_deactivation_when_runtime_cannot_insert_claim(
    factory, seed, monkeypatch
):
    with factory.begin() as db:
        db.get(Device, seed["device"]).firmware_version = "0.3.5"
    original_scalar = Session.scalar

    def without_claim_insert(self, statement, *args, **kwargs):
        if isinstance(statement, TextClause) and "has_table_privilege" in statement.text:
            return False
        return original_scalar(self, statement, *args, **kwargs)

    monkeypatch.setattr(Session, "scalar", without_claim_insert)
    client, _ = client_for(factory, seed["owner"])
    try:
        response = client.post(f"/v1/devices/{seed['device']}/factory-reset")
        assert response.status_code == 503
        with factory() as db:
            assert db.get(Connector, seed["point"]).active
            assert db.query(Command).filter_by(type="FACTORY_RESET").count() == 0
    finally:
        clear_overrides()


def _station_for_code(factory, seed):
    with factory() as db:
        return db.get(Station, seed["station"])


def assert_public_context(body, seed):
    assert body["station_id"] == str(seed["station"])
    assert body["station_name"] == "Demo"
    assert body["station_address"] == "Bancada"
    assert body["connector"] == {
        "id": str(seed["point"]), "public_code": "CG-01", "connector_type": "bench",
        "power_kw": "1.000", "price_per_kwh": "2.0000", "max_duration_minutes": 60,
    }
    assert not {"owner_id", "presence_secret", "device", "key_hash", "token_hash"}.intersection(body)


def test_reservation_and_session_endpoints_include_safe_point_context(factory, seed):
    client, selected = client_for(factory, seed["a"])
    device_headers = {"Authorization": "Device test-key"}
    try:
        reserved = client.post("/v1/reservations", headers={"Idempotency-Key": "context-reserve"},
                               json={"connector_id": str(seed["point"])})
        assert reserved.status_code == 202
        assert_public_context(reserved.json(), seed)
        assert_public_context(client.get("/v1/reservations/current").json(), seed)
        cancel = client.post(f"/v1/reservations/{reserved.json()['id']}/cancel")
        assert cancel.status_code == 202
        assert_public_context(cancel.json(), seed)
        command = client.post("/v1/devices/sync", headers=device_headers, json=sync_payload(1)).json()["commands"][0]
        assert command["type"] == "RELEASE"
        client.post("/v1/devices/sync", headers=device_headers, json=sync_payload(2,
                    acks=[{"command_id": command["id"], "status": "applied"}]))
        assert client.get("/v1/reservations/current").json() is None

        started = client.post("/v1/charging-sessions", headers={"Idempotency-Key": "context-start"},
                              json={"public_code": "CG-01", "presence_code": current_code(_station_for_code(factory, seed))[0]})
        assert started.status_code == 202
        sid = started.json()["id"]
        assert_public_context(started.json(), seed)
        for path in ("/v1/charging-sessions/current", f"/v1/charging-sessions/{sid}"):
            response = client.get(path)
            assert response.status_code == 200
            assert_public_context(response.json(), seed)
        stopped = client.post(f"/v1/charging-sessions/{sid}/stop", headers={"Idempotency-Key": "context-stop"})
        assert stopped.status_code == 202
        assert_public_context(stopped.json(), seed)
        assert_public_context(client.get("/v1/me/charging-sessions").json()["items"][0], seed)
        selected["id"] = seed["owner"]
        for path in (f"/v1/stations/{seed['station']}/charging-sessions", "/v1/operator/charging-sessions"):
            response = client.get(path)
            assert response.status_code == 200
            assert_public_context(response.json()["items"][0], seed)
    finally:
        clear_overrides()


@pytest.mark.parametrize("resource_kind", ["reservation", "session"])
def test_current_resource_context_preserves_expiry_reconciliation(factory, seed, resource_kind):
    client, _ = client_for(factory, seed["a"])
    try:
        if resource_kind == "reservation":
            created = client.post("/v1/reservations", headers={"Idempotency-Key": "expire-context"},
                                  json={"connector_id": str(seed["point"])})
            with factory.begin() as db:
                db.get(Reservation, UUID(created.json()["id"])).confirmation_deadline = now() - timedelta(seconds=1)
            path, expected_status, expected_command = "/v1/reservations/current", "cancelling", "RELEASE"
        else:
            created = client.post("/v1/charging-sessions", headers={"Idempotency-Key": "expire-context"},
                json={"presence_code": current_code(_station_for_code(factory, seed))[0]})
            with factory.begin() as db:
                db.query(Command).filter_by(session_id=UUID(created.json()["id"]), type="START").one().expires_at = (
                    now() - timedelta(seconds=1)
                )
            path, expected_status, expected_command = "/v1/charging-sessions/current", "stopping", "STOP"
        response = client.get(path)
        assert response.status_code == 200
        assert response.json()["status"] == expected_status
        assert_public_context(response.json(), seed)
        with factory() as db:
            assert db.query(Command).filter_by(type=expected_command, status="pending").count() == 1
    finally:
        clear_overrides()


@pytest.mark.parametrize("status", ["pending", "received"])
def test_expired_factory_reset_allows_reactivation_and_ignores_late_ack(factory, seed, status):
    with factory.begin() as db:
        db.get(Device, seed["device"]).firmware_version = "0.3.6"
    client, _ = client_for(factory, seed["owner"])
    endpoint = f"/v1/devices/{seed['device']}/factory-reset"
    try:
        requested = client.post(endpoint)
        assert requested.status_code == 202
        command_id = requested.json()["command_id"]
        with factory.begin() as db:
            command = db.get(Command, UUID(command_id))
            command.status = status
            command.expires_at = now() - timedelta(seconds=1)
        assert client.get(endpoint).json()["status"] == "expired"
        activated = client.patch(f"/v1/connectors/{seed['point']}", json={"active": True})
        assert activated.status_code == 200 and activated.json()["active"] is True
        late = client.post("/v1/devices/sync", headers={"Authorization": "Device test-key"},
                          json=sync_payload(1, acks=[{
                              "command_id": command_id, "status": "applied",
                              "new_device_key_hash": digest("never-applied-key"),
                              "new_claim_token_hash": digest("never-applied-claim"),
                          }]))
        assert late.status_code == 200 and "factory_reset_confirmed" not in late.json()
        available = client.get(f"/v1/stations/{seed['station']}").json()["connectors"][0]
        assert available["available"] is True and available["availability_status"] == "available"
        with factory() as db:
            assert not db.get(Device, seed["device"]).revoked
            assert db.query(DeviceClaim).count() == 0
        # Recovery may also replace an explicitly revoked device; the expired
        # reset must not permanently mark this point retired.
        assert client.post(f"/v1/devices/{seed['device']}/revoke").status_code == 200
        assert client.post(f"/v1/connectors/{seed['point']}/device").status_code == 201
    finally:
        clear_overrides()


@pytest.mark.parametrize("resource_kind", ["reservation", "session"])
def test_factory_reset_status_is_read_only_during_active_operation(factory, seed, resource_kind):
    with factory.begin() as db:
        db.get(Profile, seed["b"]).operator_enabled = True
    client, selected = client_for(factory, seed["a"])
    endpoint = f"/v1/devices/{seed['device']}/factory-reset"
    try:
        if resource_kind == "reservation":
            response = client.post("/v1/reservations", headers={"Idempotency-Key": "busy-status"},
                                   json={"connector_id": str(seed["point"])})
        else:
            response = client.post("/v1/charging-sessions", headers={"Idempotency-Key": "busy-status"},
                json={"presence_code": current_code(_station_for_code(factory, seed))[0]})
        assert response.status_code == 202
        assert client.get(endpoint).status_code == 403
        selected["id"] = seed["b"]
        assert client.get(endpoint).status_code == 404
        selected["id"] = seed["owner"]
        status = client.get(endpoint)
        assert status.status_code == 200 and status.json() == {"status": "not_requested"}
        for mutation in (endpoint, f"/v1/devices/{seed['device']}/rotate-key", f"/v1/devices/{seed['device']}/revoke"):
            denied = client.post(mutation)
            assert denied.status_code == 409 and denied.json()["error"]["code"] == "point_busy"
        with factory() as db:
            assert db.query(Command).count() == 1
            assert not db.get(Device, seed["device"]).revoked
    finally:
        clear_overrides()


def test_operator_history_is_paginated_and_isolated_to_owned_stations(factory, seed):
    with factory.begin() as db:
        other_owner = db.get(Profile, seed["b"])
        other_owner.operator_enabled = True
        other_station = Station(owner_id=other_owner.id, name="Other", address="Other road", latitude=1, longitude=1)
        db.add(other_station)
        db.flush()
        other_point = Connector(station_id=other_station.id, public_code="OTHER", connector_type="bench",
                                power_kw=1, price_per_kwh=2)
        db.add(other_point)
        db.flush()
        expected = []
        for index, point_id in enumerate((seed["point"], seed["point"], other_point.id)):
            record = ChargingSession(user_id=seed["a"], connector_id=point_id, status="completed",
                                     max_duration_minutes=30, price_per_kwh=2,
                                     created_at=now() + timedelta(seconds=index))
            db.add(record)
            db.flush()
            if point_id == seed["point"]:
                expected.insert(0, str(record.id))
    client, selected = client_for(factory, seed["a"])
    try:
        assert client.get("/v1/operator/charging-sessions").status_code == 403
        selected["id"] = seed["owner"]
        first = client.get("/v1/operator/charging-sessions", params={"limit": 1, "offset": 0})
        second = client.get("/v1/operator/charging-sessions", params={"limit": 1, "offset": 1})
        assert first.status_code == second.status_code == 200
        assert first.json()["total"] == second.json()["total"] == 2
        assert [first.json()["items"][0]["id"], second.json()["items"][0]["id"]] == expected
        assert_public_context(first.json()["items"][0], seed)
        selected["id"] = seed["b"]
        other = client.get("/v1/operator/charging-sessions").json()
        assert other["total"] == 1 and other["items"][0]["station_name"] == "Other"
        assert other["items"][0]["id"] not in expected
    finally:
        clear_overrides()


def test_expired_coupon_can_be_edited_or_disabled_but_needs_future_date_to_reactivate(factory, seed):
    expires = now() - timedelta(days=1)
    with factory.begin() as db:
        coupon = Coupon(operator_id=seed["owner"], code="EDIT-EXPIRED", description="Old", discount_percent=10,
                        valid_until=expires, active=True)
        db.add(coupon)
        db.flush()
        coupon_id = coupon.id
    client, _ = client_for(factory, seed["owner"])
    endpoint = f"/v1/coupons/{coupon_id}"
    try:
        edited = client.patch(endpoint, json={"description": "Updated", "discount_percent": 15})
        assert edited.status_code == 200
        assert datetime.fromisoformat(edited.json()["valid_until"]) == expires
        assert client.patch(endpoint, json={"active": False}).status_code == 200
        assert client.patch(endpoint, json={"active": True}).status_code == 422
        assert client.patch(endpoint, json={"valid_until": expires.isoformat()}).status_code == 422
        future = now() + timedelta(days=1)
        enabled = client.patch(endpoint, json={"valid_until": future.isoformat(), "active": True})
        assert enabled.status_code == 200 and enabled.json()["active"] is True
        assert datetime.fromisoformat(enabled.json()["valid_until"]) == future
        rejected = client.post("/v1/coupons", json={"code": "ALREADY-EXPIRED", "description": "Expired",
            "discount_percent": 10, "valid_until": expires.isoformat()})
        assert rejected.status_code == 422
    finally:
        clear_overrides()
