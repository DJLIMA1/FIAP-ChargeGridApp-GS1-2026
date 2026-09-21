import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import db_session
from app.main import app
from app.models import Profile
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
