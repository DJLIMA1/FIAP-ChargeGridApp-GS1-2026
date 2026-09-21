from datetime import datetime, timedelta, timezone

from tools.device_simulator import Device


def response(kind="START", version=1, identifier="command"):
    now = datetime.now(timezone.utc)
    return {
        "server_time": now.isoformat(),
        "control_version": version,
        "sync_interval_seconds": 5,
        "authorized": {
            "reservation": None,
            "session": {
                "id": "session",
                "max_duration_minutes": 60,
                "max_cost": None,
                "price_per_kwh": 2,
                "discount_percent": 0,
            },
        },
        "commands": [
            {
                "id": identifier,
                "type": kind,
                "version": version,
                "expires_at": (now + timedelta(minutes=1)).isoformat(),
                "session_id": "session",
                "reservation_id": None,
                "parameters": {},
            }
        ],
    }


def test_duplicate_start_does_not_reset_energy():
    now = [0]
    device = Device(clock=lambda: now[0])
    device.response(response())
    now[0] = 10
    device.tick()
    energy = device.energy
    device.response(response())
    assert device.energy == energy == 20
    assert device.state == "charging"


def test_offline_stop_caps_energy_and_reconciles(tmp_path):
    now = [0]
    device = Device(tmp_path / "state.json", clock=lambda: now[0])
    device.response(response())
    now[0] = 60
    device.tick()
    assert device.state == "stopped"
    assert device.reason == "communication_lost"
    assert device.energy == 90
    restarted = Device(tmp_path / "state.json", clock=lambda: now[0])
    restarted.response(response())
    assert restarted.session_id == "session"
    assert restarted.state == "stopped"
    assert restarted.energy == 90
    assert restarted.acks[0]["status"] == "failed"


def test_expired_and_older_commands_do_not_start():
    device = Device()
    data = response()
    data["commands"][0]["expires_at"] = "2000-01-01T00:00:00Z"
    device.response(data)
    assert device.state == "idle"
    data = response(version=2)
    data["commands"][0]["version"] = 1
    device.response(data)
    assert device.state == "idle"


def test_stop_wrong_session_fails():
    device = Device()
    device.response(response())
    data = response(kind="STOP", version=2, identifier="stop")
    data["commands"][0]["session_id"] = "other"
    device.response(data)
    assert device.state == "charging"
    assert device.acks[0]["status"] == "failed"


def test_duration_and_cost_limits():
    now = [0]
    device = Device(clock=lambda: now[0])
    data = response()
    data["authorized"]["session"]["max_duration_minutes"] = 0.5
    device.response(data)
    now[0] = 31
    device.tick()
    assert device.reason == "duration_limit"
    assert device.energy == 60
    device = Device(clock=lambda: now[0])
    data = response()
    data["authorized"]["session"]["max_cost"] = 0.01
    device.response(data)
    now[0] += 10
    device.tick()
    assert device.reason == "cost_limit"
    assert device.energy == 5


def test_new_session_after_server_reconciliation():
    device = Device()
    device.response(response())
    device.stop("requested")
    data = response(version=2, identifier="new")
    data["authorized"]["session"]["id"] = "new-session"
    data["commands"][0]["session_id"] = "new-session"
    device.response(data)
    assert device.state == "charging"
    assert device.session_id == "new-session"
    assert device.energy == 0


def test_reservation_ttl_updates_on_every_sync():
    device = Device()
    data = response(kind="RESERVE")
    expiry = datetime.now(timezone.utc) + timedelta(seconds=30)
    data["authorized"] = {
        "session": None,
        "reservation": {"id": "reservation", "expires_at": expiry.isoformat()},
    }
    data["commands"][0]["reservation_id"] = "reservation"
    device.response(data)
    assert device.state == "reserved"
    expiry += timedelta(minutes=10)
    data["authorized"]["reservation"]["expires_at"] = expiry.isoformat()
    data["commands"] = []
    device.response(data)
    assert device.reservation_expires == expiry.timestamp()
