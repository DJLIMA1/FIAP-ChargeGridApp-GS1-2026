"""Car battery (SoC): start fields, /soc endpoint, battery_full stop, device payloads."""

from decimal import Decimal

import pytest
from test_http import clear_overrides, client_for, sync_payload

from app.models import ChargingSession, Command, Station
from app.presence_code import current_code

DEVICE = {"Authorization": "Device test-key"}


@pytest.fixture
def client(factory, seed):
    client, selected = client_for(factory, seed["a"])
    yield client, selected
    clear_overrides()


def _code(factory, seed):
    with factory() as db:
        return current_code(db.get(Station, seed["station"]))[0]


def _start(client, factory, seed, key="soc-start", **battery):
    response = client.post(
        "/v1/charging-sessions",
        headers={"Idempotency-Key": key},
        json={"public_code": "CG-01", "presence_code": _code(factory, seed), **battery},
    )
    assert response.status_code == 202, response.text
    return response.json()


def _charging(client, session_id, sequence=1):
    """Device acknowledges START and reports charging."""
    start_cmd = client.post("/v1/devices/sync", headers=DEVICE, json=sync_payload(sequence)).json()["commands"][0]
    assert start_cmd["type"] == "START"
    response = client.post(
        "/v1/devices/sync",
        headers=DEVICE,
        json=sync_payload(
            sequence + 1, session_id=session_id, physical_state="charging", connected=True,
            acks=[{"command_id": start_cmd["id"], "status": "applied", "error": None}],
        ),
    )
    assert response.status_code == 200, response.text
    return start_cmd, response.json()


def _measure(client, session_id, sequence, energy_wh, **extra):
    response = client.post(
        "/v1/devices/sync",
        headers=DEVICE,
        json=sync_payload(sequence, session_id=session_id, physical_state="charging", connected=True,
                          energy_wh=energy_wh, **extra),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _stop_commands(factory, session_id):
    with factory() as db:
        return db.query(Command).filter(Command.session_id == session_id, Command.type == "STOP").all()


def test_start_stores_battery_and_device_payload(client, factory, seed):
    http, _ = client
    session = _start(http, factory, seed, soc_percent=42.5, battery_kwh=60, soc_source="simulated")
    assert session["soc_percent"] == "42.50"
    assert session["start_soc_percent"] == "42.50"
    assert session["battery_kwh"] == "60.00"
    assert session["soc_source"] == "simulated"
    assert session["end_reason"] is None
    start_cmd, synced = _charging(http, session["id"])
    assert start_cmd["parameters"]["soc_percent"] == 42.5
    assert start_cmd["parameters"]["battery_kwh"] == 60.0
    assert start_cmd["parameters"]["soc_source"] == "simulated"
    authorized = synced["authorized"]["session"]
    assert authorized["soc_percent"] == 42.5
    assert authorized["start_soc_percent"] == 42.5
    assert authorized["battery_kwh"] == 60.0
    assert authorized["soc_source"] == "simulated"
    # Serialised the same way in current, by id and in history.
    for body in (
        http.get("/v1/charging-sessions/current").json(),
        http.get(f"/v1/charging-sessions/{session['id']}").json(),
        http.get("/v1/me/charging-sessions").json()["items"][0],
    ):
        assert body["start_soc_percent"] == "42.50"
        assert body["battery_kwh"] == "60.00"
        assert body["soc_source"] == "simulated"


def test_start_without_battery_is_backward_compatible(client, factory, seed):
    http, _ = client
    session = _start(http, factory, seed)
    assert session["soc_percent"] is None
    assert session["start_soc_percent"] is None
    assert session["battery_kwh"] is None
    assert session["soc_source"] is None
    start_cmd, synced = _charging(http, session["id"])
    assert start_cmd["parameters"]["soc_percent"] is None
    assert synced["authorized"]["session"]["soc_source"] is None
    # Legacy sessions keep the device-reported SoC verbatim (null stays null).
    _measure(http, session["id"], 3, 500)
    assert http.get(f"/v1/charging-sessions/{session['id']}").json()["soc_percent"] is None


def test_soc_without_source_defaults_to_simulated(client, factory, seed):
    http, _ = client
    session = _start(http, factory, seed, soc_percent=30)
    assert session["soc_source"] == "simulated"


@pytest.mark.parametrize(
    "battery",
    [
        {"soc_percent": -1},
        {"soc_percent": 100.5},
        {"battery_kwh": 4},
        {"battery_kwh": 251},
        {"soc_source": "car"},
    ],
)
def test_start_validates_battery_fields(client, factory, seed, battery):
    http, _ = client
    response = http.post(
        "/v1/charging-sessions",
        headers={"Idempotency-Key": "bad-battery"},
        json={"public_code": "CG-01", "presence_code": _code(factory, seed), **battery},
    )
    assert response.status_code == 422


def test_simulated_soc_derived_from_energy_and_battery_full_stop(client, factory, seed):
    http, _ = client
    session = _start(http, factory, seed, soc_percent=90, battery_kwh=10, soc_source="simulated")
    _charging(http, session["id"])
    synced = _measure(http, session["id"], 3, 500)  # +5 % of 10 kWh
    assert synced["authorized"]["session"]["soc_percent"] == 95.0
    current = http.get("/v1/charging-sessions/current").json()
    assert current["soc_percent"] == "95.00"
    assert current["status"] == "charging"

    synced = _measure(http, session["id"], 4, 1200)  # would be 102 % -> capped at 100
    assert synced["authorized"]["session"]["status"] == "stopping"
    assert synced["authorized"]["session"]["soc_percent"] == 100.0
    stop = [cmd for cmd in synced["commands"] if cmd["type"] == "STOP"]
    assert len(stop) == 1 and stop[0]["parameters"] == {"reason": "battery_full"}

    # More energy while stopping does not issue a second STOP.
    synced = _measure(http, session["id"], 5, 1300)
    assert len(_stop_commands(factory, session["id"])) == 1

    # The device's own reason does not overwrite battery_full.
    final = http.post(
        "/v1/devices/sync",
        headers=DEVICE,
        json=sync_payload(6, session_id=session["id"], physical_state="stopped", energy_wh=1300,
                          end_reason="requested_stop",
                          acks=[{"command_id": stop[0]["id"], "status": "applied", "error": None}]),
    )
    assert final.status_code == 200
    ended = http.get(f"/v1/charging-sessions/{session['id']}").json()
    assert ended["status"] == "completed"
    assert ended["end_reason"] == "battery_full"
    assert ended["soc_percent"] == "100.00"
    assert ended["start_soc_percent"] == "90.00"
    # Replaying the final measurement (device SoC null) stays accepted.
    replay = http.post(
        "/v1/devices/sync",
        headers=DEVICE,
        json=sync_payload(7, session_id=session["id"], physical_state="stopped", energy_wh=1300),
    )
    assert replay.status_code == 200


def test_device_reported_soc_wins_for_simulated(client, factory, seed):
    http, _ = client
    session = _start(http, factory, seed, soc_percent=20, battery_kwh=50, soc_source="simulated")
    _charging(http, session["id"])
    synced = _measure(http, session["id"], 3, 1000, soc_percent=33)
    assert synced["authorized"]["session"]["soc_percent"] == 33.0
    synced = _measure(http, session["id"], 4, 1100, soc_percent=100)
    assert synced["authorized"]["session"]["status"] == "stopping"
    assert len(_stop_commands(factory, session["id"])) == 1


def test_soc_endpoint_phone_flow_and_battery_full(client, factory, seed):
    http, _ = client
    session = _start(http, factory, seed, soc_percent=80, battery_kwh=60, soc_source="phone")
    _charging(http, session["id"])
    # Device SoC and energy do not move a phone session's SoC.
    synced = _measure(http, session["id"], 3, 900, soc_percent=10)
    assert synced["authorized"]["session"]["soc_percent"] == 80.0

    response = http.post(f"/v1/charging-sessions/{session['id']}/soc", json={"soc_percent": 76})
    assert response.status_code == 200
    body = response.json()
    assert body["soc_percent"] == "76.00"  # lower than before: allowed
    assert body["soc_source"] == "phone"
    assert body["status"] == "charging"
    assert body["station_name"] == "Demo"  # full session representation

    synced = _measure(http, session["id"], 4, 950)
    assert synced["authorized"]["session"]["soc_percent"] == 76.0

    full = http.post(f"/v1/charging-sessions/{session['id']}/soc", json={"soc_percent": 100})
    assert full.status_code == 200
    assert full.json()["status"] == "stopping"
    assert full.json()["end_reason"] == "battery_full"
    assert len(_stop_commands(factory, session["id"])) == 1
    # Stopping is no longer active for /soc, and no extra STOP is issued.
    again = http.post(f"/v1/charging-sessions/{session['id']}/soc", json={"soc_percent": 100})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "session_not_active"
    assert len(_stop_commands(factory, session["id"])) == 1

    stop = _stop_commands(factory, session["id"])[0]
    http.post(
        "/v1/devices/sync",
        headers=DEVICE,
        json=sync_payload(5, session_id=session["id"], physical_state="stopped", energy_wh=950,
                          acks=[{"command_id": str(stop.id), "status": "applied", "error": None}]),
    )
    ended = http.get(f"/v1/charging-sessions/{session['id']}").json()
    assert ended["status"] == "completed"
    assert ended["end_reason"] == "battery_full"


def test_soc_endpoint_switches_simulated_session_to_phone(client, factory, seed):
    http, _ = client
    session = _start(http, factory, seed, soc_percent=50, battery_kwh=10, soc_source="simulated")
    _charging(http, session["id"])
    assert http.post(f"/v1/charging-sessions/{session['id']}/soc", json={"soc_percent": 61}).status_code == 200
    synced = _measure(http, session["id"], 3, 2000)  # would derive 70 %; phone owns it now
    assert synced["authorized"]["session"]["soc_percent"] == 61.0


def test_soc_endpoint_auth_and_validation(client, factory, seed):
    http, selected = client
    session = _start(http, factory, seed, soc_percent=40, battery_kwh=40)
    url = f"/v1/charging-sessions/{session['id']}/soc"
    for bad in ({"soc_percent": -0.1}, {"soc_percent": 100.01}, {}, {"soc_percent": 50, "extra": 1}):
        assert http.post(url, json=bad).status_code == 422
    selected["id"] = seed["b"]
    other = http.post(url, json={"soc_percent": 50})
    assert other.status_code == 404
    selected["id"] = seed["a"]
    # Starting (not yet acknowledged) is active: accepted.
    assert http.post(url, json={"soc_percent": 45}).json()["status"] == "starting"
    assert http.post(f"/v1/charging-sessions/{session['id']}/stop",
                     headers={"Idempotency-Key": "stop-soc"}).status_code == 202
    assert http.post(url, json={"soc_percent": 50}).status_code == 409
    with factory() as db:
        assert db.get(ChargingSession, session["id"]).soc_percent == Decimal("45.00")


def test_soc_endpoint_starting_at_full_stops_once(client, factory, seed):
    http, _ = client
    session = _start(http, factory, seed, soc_percent=99, battery_kwh=40, soc_source="phone")
    response = http.post(f"/v1/charging-sessions/{session['id']}/soc", json={"soc_percent": 100})
    assert response.status_code == 200
    assert response.json()["status"] == "stopping"
    assert len(_stop_commands(factory, session["id"])) == 1


def test_start_idempotency_with_battery_fields(client, factory, seed):
    http, _ = client
    first = _start(http, factory, seed, key="same", soc_percent=40, battery_kwh=40)
    again = _start(http, factory, seed, key="same", soc_percent=40, battery_kwh=40)
    assert again["id"] == first["id"]
    conflict = http.post(
        "/v1/charging-sessions",
        headers={"Idempotency-Key": "same"},
        json={"public_code": "CG-01", "presence_code": _code(factory, seed), "soc_percent": 41,
              "battery_kwh": 40},
    )
    assert conflict.status_code == 409
