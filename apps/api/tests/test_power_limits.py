"""Station power limits: per-port limit, station-wide cap, effective power, energy totals,
start payload intersection with the driver's limit and authorization."""

from decimal import Decimal

import pytest
from test_http import clear_overrides, client_for, sync_payload

from app.models import ChargingSession, Connector, Station
from app.presence_code import current_code

DEVICE = {"Authorization": "Device test-key"}


@pytest.fixture
def setup(factory, seed):
    """Seed station: the bench point becomes a 60 kW CCS2 and a 22 kW Tipo 2 point joins it."""
    with factory.begin() as db:
        bench = db.get(Connector, seed["point"])
        bench.power_kw = Decimal(60)
        bench.connector_type = "CCS2"
        ac = Connector(station_id=seed["station"], public_code="CG-02", connector_type="Tipo 2",
                       power_kw=Decimal(22), price_per_kwh=Decimal(2), max_duration_minutes=60)
        db.add(ac)
        db.flush()
        seed = {**seed, "ac": ac.id}
    client, selected = client_for(factory, seed["owner"])
    yield client, selected, seed
    clear_overrides()


def _points(body):
    return {point["public_code"]: point for point in body["connectors"]}


def _code(factory, seed):
    with factory() as db:
        return current_code(db.get(Station, seed["station"]))[0]


def _start(client, factory, seed, key="power-start", **extra):
    return client.post(
        "/v1/charging-sessions",
        headers={"Idempotency-Key": key},
        json={"public_code": "CG-01", "presence_code": _code(factory, seed), **extra},
    )


def test_defaults_serialize_rating_as_effective(setup):
    client, _, seed = setup
    body = client.get(f"/v1/stations/{seed['station']}").json()
    assert body["max_power_kw"] is None
    assert body["power_limit_notify"] is False
    assert body["power_shared"] is False
    assert body["allocated_power_kw"] == "82.000"
    point = _points(body)["CG-01"]
    assert point["power_kw"] == "60.000"
    assert point["power_limit_kw"] is None
    assert point["effective_power_kw"] == "60.000"
    assert point["power_limited"] is False
    assert point["power_limited_by"] is None
    assert point["energy_kwh_total"] == "0.000"


def test_port_limit_validation_and_clearing(setup):
    client, _, seed = setup
    url = f"/v1/connectors/{seed['point']}"
    too_high = client.patch(url, json={"power_limit_kw": 61})
    assert too_high.status_code == 422
    assert too_high.json()["error"]["code"] == "invalid_power_limit"
    assert "potência máxima do carregador (60 kW)" in too_high.json()["error"]["message"]
    assert client.patch(url, json={"power_limit_kw": 0}).json()["error"]["message"] == (
        "Informe um limite de potência maior que zero.")
    assert "mínimo por conector" in client.patch(url, json={"power_limit_kw": 1}).json()["error"]["message"]
    limited = client.patch(url, json={"power_limit_kw": 40})
    assert limited.status_code == 200, limited.text
    assert limited.json()["power_limit_kw"] == "40.000"
    assert limited.json()["effective_power_kw"] == "40.000"
    assert limited.json()["power_limited_by"] == "port"
    assert limited.json()["power_kw"] == "60.000"  # The rating is never overwritten.
    cleared = client.patch(url, json={"power_limit_kw": None})
    assert cleared.status_code == 200
    assert cleared.json()["power_limit_kw"] is None
    assert cleared.json()["effective_power_kw"] == "60.000"


def test_lower_rating_clears_meaningless_limit(setup):
    client, _, seed = setup
    url = f"/v1/connectors/{seed['point']}"
    assert client.patch(url, json={"power_limit_kw": 40}).status_code == 200
    assert client.patch(url, json={"power_kw": 50}).json()["power_limit_kw"] == "40.000"
    body = client.patch(url, json={"power_kw": 30}).json()
    assert body["power_limit_kw"] is None
    assert body["effective_power_kw"] == "30.000"


def test_station_cap_shares_proportionally(setup):
    client, _, seed = setup
    url = f"/v1/stations/{seed['station']}"
    low = client.patch(url, json={"max_power_kw": 2})
    assert low.status_code == 422
    assert "pelo menos 2,8 kW para 2 conectores ativos" in low.json()["error"]["message"]
    assert client.patch(url, json={"max_power_kw": -5}).status_code == 422
    body = client.patch(url, json={"max_power_kw": 50, "power_limit_notify": True}).json()
    assert body["max_power_kw"] == "50.000"
    assert body["power_limit_notify"] is True
    assert body["power_shared"] is True
    points = _points(body)
    # 50 x 60/82 = 36.58 -> 36.5 ; 50 x 22/82 = 13.41 -> 13.4 (rounded down to 0.1 kW).
    assert points["CG-01"]["effective_power_kw"] == "36.500"
    assert points["CG-02"]["effective_power_kw"] == "13.400"
    assert points["CG-01"]["power_limited_by"] == "station"
    assert points["CG-01"]["power_limited"] is True
    assert body["allocated_power_kw"] == "49.900"
    # An inactive point leaves the share: the remaining point takes the whole cap.
    assert client.patch(f"/v1/connectors/{seed['ac']}", json={"active": False}).status_code == 200
    points = _points(client.get(url).json())
    assert points["CG-01"]["effective_power_kw"] == "50.000"
    assert client.patch(url, json={"max_power_kw": None}).json()["max_power_kw"] is None


def test_null_notify_flag_rejected(setup):
    client, _, seed = setup
    response = client.patch(f"/v1/stations/{seed['station']}", json={"power_limit_notify": None})
    assert response.status_code == 422


def test_only_owner_changes_limits_and_sees_energy(setup):
    client, selected, seed = setup
    selected["id"] = seed["a"]  # consumer, not an operator
    assert client.patch(f"/v1/connectors/{seed['point']}", json={"power_limit_kw": 30}).status_code == 403
    assert client.patch(f"/v1/stations/{seed['station']}", json={"max_power_kw": 30}).status_code == 403
    public = _points(client.get(f"/v1/stations/{seed['station']}").json())["CG-01"]
    assert "energy_kwh_total" not in public
    assert public["effective_power_kw"] == "60.000"  # Drivers see the effective power.


def test_start_applies_effective_and_driver_limit(setup, factory):
    client, selected, seed = setup
    assert client.patch(f"/v1/stations/{seed['station']}", json={"max_power_kw": 50}).status_code == 200
    selected["id"] = seed["a"]
    assert _start(client, factory, seed, key="bad", max_power_kw=0).status_code == 422
    response = _start(client, factory, seed, max_power_kw=80)
    assert response.status_code == 202, response.text
    session = response.json()
    # The driver asked for more than the point can give: the effective share wins.
    assert session["power_limit_kw"] == "36.500"
    command = client.post("/v1/devices/sync", headers=DEVICE, json=sync_payload(1)).json()
    start_cmd = command["commands"][0]
    assert start_cmd["parameters"]["max_power_kw"] == 36.5
    assert command["authorized"]["session"]["max_power_kw"] == 36.5


def test_start_driver_limit_below_effective(setup, factory):
    client, selected, seed = setup
    selected["id"] = seed["a"]
    session = _start(client, factory, seed, max_power_kw="22.5").json()
    assert session["power_limit_kw"] == "22.500"
    with factory() as db:
        assert db.get(ChargingSession, session["id"]).power_limit_kw == Decimal("22.5")


def test_start_without_driver_limit_uses_effective(setup, factory):
    client, selected, seed = setup
    selected["id"] = seed["a"]
    assert _start(client, factory, seed).json()["power_limit_kw"] == "60.000"


def test_busy_point_accepts_limit_for_next_start_and_counts_energy(setup, factory):
    client, selected, seed = setup
    selected["id"] = seed["a"]
    session = _start(client, factory, seed).json()
    start_cmd = client.post("/v1/devices/sync", headers=DEVICE, json=sync_payload(1)).json()["commands"][0]
    charging = sync_payload(2, session_id=session["id"], physical_state="charging", connected=True,
                            energy_wh=1500,
                            acks=[{"command_id": start_cmd["id"], "status": "applied", "error": None}])
    assert client.post("/v1/devices/sync", headers=DEVICE, json=charging).status_code == 200
    selected["id"] = seed["owner"]
    # Other edits stay blocked while busy; the power limit applies to the next start.
    assert client.patch(f"/v1/connectors/{seed['point']}", json={"price_per_kwh": 3}).status_code == 409
    limited = client.patch(f"/v1/connectors/{seed['point']}", json={"power_limit_kw": 20})
    assert limited.status_code == 200, limited.text
    assert limited.json()["effective_power_kw"] == "20.000"
    assert limited.json()["energy_kwh_total"] == "1.500"
    selected["id"] = seed["a"]
    assert client.get(f"/v1/charging-sessions/{session['id']}").json()["power_limit_kw"] == "60.000"
    selected["id"] = seed["owner"]
    listing = client.get("/v1/operator/stations").json()["items"][0]
    assert _points(listing)["CG-01"]["energy_kwh_total"] == "1.500"
    assert _points(listing)["CG-02"]["energy_kwh_total"] == "0.000"


def test_operator_listing_energy_is_one_grouped_query(setup, factory):
    from sqlalchemy import event

    client, _, seed = setup
    statements = []
    engine = factory.kw["bind"]

    def record(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        assert client.get("/v1/operator/stations").status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", record)
    grouped = [s for s in statements if "sum(charging_sessions.energy_wh)" in s and "GROUP BY" in s]
    assert len(grouped) == 1
