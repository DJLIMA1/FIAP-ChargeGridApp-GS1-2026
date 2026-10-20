import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import db_session
from app.main import app
from app.models import Profile, Station
from app.presence_code import current_code
from app.security import current_user

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tools.device_simulator import Device  # noqa: E402


def test_real_simulator_contract_reserve_start_stop(factory, seed, tmp_path):
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
            return db.get(Profile, seed["a"])

    app.dependency_overrides[db_session] = database
    app.dependency_overrides[current_user] = user
    client = TestClient(app)
    device = Device(tmp_path / "device-state.json")
    headers = {"Authorization": "Device test-key"}

    def exchange():
        response = client.post("/v1/devices/sync", headers=headers, json=device.payload())
        assert response.status_code == 200, response.text
        device.response(response.json())
        return response.json()

    try:
        reservation = client.post(
            "/v1/reservations",
            headers={"Idempotency-Key": "sim-reserve"},
            json={"connector_id": str(seed["point"])},
        )
        assert reservation.status_code == 202
        exchange()
        confirmed = exchange()
        assert confirmed["authorized"]["reservation"]["status"] == "confirmed"

        started = client.post(
            "/v1/charging-sessions",
            headers={"Idempotency-Key": "sim-start"},
            json={
                "public_code": "CG-01",
                "presence_code": current_code(_station_for_code(factory, seed))[0],
                "reservation_id": reservation.json()["id"],
                "max_duration_minutes": 20,
            },
        )
        assert started.status_code == 202
        exchange()
        charging = exchange()
        assert device.state == "charging"
        assert charging["authorized"]["session"]["status"] == "charging"

        stopped = client.post(
            f"/v1/charging-sessions/{started.json()['id']}/stop",
            headers={"Idempotency-Key": "sim-stop"},
        )
        assert stopped.status_code == 202
        exchange()
        finished = exchange()
        assert finished["authorized"]["session"] is None
        exchange()
        assert device.session_id is None
        assert device.state == "idle"
    finally:
        app.dependency_overrides.clear()


def _station_for_code(factory, seed):
    with factory() as db:
        return db.get(Station, seed["station"])


def test_real_simulator_holds_the_cable_for_overstay_until_unplug(factory, seed, tmp_path):
    with factory.begin() as db:
        db.get(Station, seed["station"]).pricing = {"rotation": {
            "enabled": True, "start_after_min": 10, "interval_min": 1, "amount": "1.00", "max_amount": "30.00"}}

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
            return db.get(Profile, seed["a"])

    app.dependency_overrides[db_session] = database
    app.dependency_overrides[current_user] = user
    client = TestClient(app)
    device = Device(tmp_path / "device-state.json", unplug_after=None)
    headers = {"Authorization": "Device test-key"}

    def exchange():
        response = client.post("/v1/devices/sync", headers=headers, json=device.payload())
        assert response.status_code == 200, response.text
        device.response(response.json())
        return response.json()

    try:
        version = client.get(f"/v1/stations/{seed['station']}").json()["overstay"]["version"]
        started = client.post(
            "/v1/charging-sessions", headers={"Idempotency-Key": "sim-overstay"},
            json={"public_code": "CG-01", "presence_code": current_code(_station_for_code(factory, seed))[0],
                  "overstay_terms_version": version},
        )
        assert started.status_code == 202, started.text
        exchange()
        exchange()
        assert device.state == "charging"
        client.post(f"/v1/charging-sessions/{started.json()['id']}/stop", headers={"Idempotency-Key": "sim-stop"})
        exchange()
        held = exchange()
        assert device.connected is True and held["overstay"]["status"] == "grace"
        exchange()
        assert device.state == "idle" and device.connected is True
        assert client.get("/v1/overstays/current").json()["session_id"] == started.json()["id"]
        assert device.unplug()
        released = exchange()
        assert released["overstay"] is None
        assert client.get("/v1/overstays/current").json() is None
        session = client.get(f"/v1/charging-sessions/{started.json()['id']}").json()
        assert session["overstay"]["end_reason"] == "disconnected" and session["settlement_ready"] is True
    finally:
        app.dependency_overrides.clear()
