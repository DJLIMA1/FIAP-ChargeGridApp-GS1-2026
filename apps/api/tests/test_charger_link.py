"""Carregador GoodWe HCA G2 externo ligado à tela de um ponto (``connectors.charger_address``):
validação, unicidade por posto, só o dono, payloads do dono/motorista e o sync com/sem link."""

import sys
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from test_http import clear_overrides, client_for, sync_payload

from app.models import ChargingSession, Connector, Device, Profile, Station
from app.presence_code import current_code
from app.security import digest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tools.device_simulator import Device as Simulator  # noqa: E402

DEVICE = {"Authorization": "Device test-key"}
HCA = {"model": "goodwe_hca_g2", "transport": "modbus_tcp", "min_power_w": 1400, "max_power_w": 7000,
       "step_w": 100}


@pytest.fixture
def setup(factory, seed):
    with factory.begin() as db:
        other = Connector(station_id=seed["station"], public_code="CG-02", connector_type="Tipo 2",
                          power_kw=Decimal(7), price_per_kwh=Decimal(2), max_duration_minutes=60)
        db.add(other)
        db.flush()
        seed = {**seed, "other": other.id}
    client, selected = client_for(factory, seed["owner"])
    yield client, selected, seed
    clear_overrides()


def _patch(client, point, value):
    return client.patch(f"/v1/connectors/{point}", json={"charger_address": value})


def _point(body, code="CG-01"):
    return next(item for item in body["connectors"] if item["public_code"] == code)


def test_owner_sets_and_removes_the_charger_address(setup):
    client, _, seed = setup
    body = client.get(f"/v1/stations/{seed['station']}").json()
    assert _point(body)["charger_address"] is None and _point(body)["charger_link"] is None
    saved = _patch(client, seed["point"], 1)
    assert saved.status_code == 200, saved.text
    assert saved.json()["charger_address"] == 1
    link = saved.json()["charger_link"]
    assert link["host"] == "cg-hca-1.local" and link["model"] == "goodwe_hca_g2"
    assert link["transport"] == "modbus_tcp" and link["simulated"] is True
    assert link["link"] == "pending"  # a tela (online) ainda não confirmou o endereço
    assert _point(client.get(f"/v1/stations/{seed['station']}").json())["charger_address"] == 1
    listed = client.get("/v1/operator/stations").json()["items"][0]
    assert _point(listed)["charger_link"]["address"] == 1
    removed = _patch(client, seed["point"], None)
    assert removed.status_code == 200 and removed.json()["charger_address"] is None
    assert removed.json()["charger_link"] is None


@pytest.mark.parametrize("value", [0, 248, -1, 1.5, "1", True, "abc"])
def test_invalid_addresses_are_rejected(setup, value):
    client, _, seed = setup
    response = _patch(client, seed["point"], value)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "invalid_charger_address"
    assert "1 a 247" in response.json()["error"]["message"]


def test_address_is_unique_per_station_with_clear_409(setup, factory):
    client, _, seed = setup
    assert _patch(client, seed["point"], 1).status_code == 200
    taken = _patch(client, seed["other"], 1)
    assert taken.status_code == 409
    error = taken.json()["error"]
    assert error["code"] == "charger_address_taken"
    assert "carregador 1" in error["message"] and "CG-01" in error["message"]
    assert _patch(client, seed["other"], 2).status_code == 200
    # Mesmo endereço de novo no próprio ponto: sem conflito.
    assert _patch(client, seed["point"], 1).status_code == 200
    # Outro posto pode usar o mesmo endereço (outra rede local).
    with factory.begin() as db:
        station = Station(owner_id=seed["owner"], name="Outro", address="Rua", latitude=0, longitude=0)
        db.add(station)
        db.flush()
        far = Connector(station_id=station.id, public_code="CG-09", connector_type="Tipo 2",
                        power_kw=Decimal(7), price_per_kwh=Decimal(2), max_duration_minutes=60)
        db.add(far)
        db.flush()
        far_id = far.id
    assert _patch(client, far_id, 1).status_code == 200


def test_only_the_owner_can_link_a_charger(setup, factory):
    client, selected, seed = setup
    selected["id"] = seed["a"]  # motorista, sem operador
    assert _patch(client, seed["point"], 1).status_code == 403
    with factory.begin() as db:
        intruder = Profile(id=uuid.uuid4(), name="Outro vendedor", operator_enabled=True)
        db.add(intruder)
        db.flush()
        selected["id"] = intruder.id
    assert _patch(client, seed["point"], 1).status_code == 404
    with factory() as db:
        assert db.get(Connector, seed["point"]).charger_address is None


def test_drivers_never_see_the_charger_fields(setup):
    client, selected, seed = setup
    assert _patch(client, seed["point"], 1).status_code == 200
    selected["id"] = seed["a"]
    point = _point(client.get(f"/v1/stations/{seed['station']}").json())
    assert "charger_address" not in point and "charger_link" not in point
    listed = client.get("/v1/stations").json()["items"][0]
    assert all("charger_address" not in item and "charger_link" not in item for item in listed["connectors"])


def test_charger_cannot_change_while_the_point_is_busy(setup, factory):
    client, _, seed = setup
    assert _patch(client, seed["point"], 1).status_code == 200
    with factory.begin() as db:
        db.add(ChargingSession(user_id=seed["a"], connector_id=seed["point"], status="charging",
                               price_per_kwh=Decimal(2), max_duration_minutes=30))
    busy = _patch(client, seed["point"], 2)
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "point_busy"
    assert _patch(client, seed["point"], 1).status_code == 200  # mesmo endereço: nada muda


def test_sync_sends_charger_link_only_when_configured(setup):
    client, _, seed = setup
    plain = client.post("/v1/devices/sync", headers=DEVICE, json=sync_payload(1)).json()
    assert plain["connector"]["charger_link"] is None
    assert _patch(client, seed["point"], 1).status_code == 200
    linked = client.post("/v1/devices/sync", headers=DEVICE, json=sync_payload(2)).json()
    assert linked["connector"]["charger_link"] == {"model": "goodwe_hca_g2", "transport": "modbus_tcp",
                                                   "address": 1, "host": "cg-hca-1.local"}


def test_screen_reports_link_state_and_owner_sees_it(setup, factory):
    client, _, seed = setup
    assert _patch(client, seed["point"], 1).status_code == 200
    online = sync_payload(1, charger={**HCA, "address": 1, "link": "online"})
    assert client.post("/v1/devices/sync", headers=DEVICE, json=online).status_code == 200
    point = _point(client.get(f"/v1/stations/{seed['station']}").json())
    assert point["charger_link"]["link"] == "online"
    assert point["charger_link"]["reported"] == {"model": "goodwe_hca_g2", "transport": "modbus_tcp",
                                                 "address": 1, "link": "online"}
    device = client.get(f"/v1/connectors/{seed['point']}/device").json()
    assert device["charger"]["address"] == 1 and device["charger"]["link"] == "online"
    assert device["charger_address"] == 1
    offline = sync_payload(2, charger={**HCA, "address": 1, "link": "offline"})
    assert client.post("/v1/devices/sync", headers=DEVICE, json=offline).status_code == 200
    assert _point(client.get(f"/v1/stations/{seed['station']}").json())["charger_link"]["link"] == "offline"
    # Tela sem contato há mais de 45 s: o link aparece offline.
    with factory.begin() as db:
        db.get(Device, seed["device"]).last_seen = None
    point = _point(client.get(f"/v1/stations/{seed['station']}").json())
    assert point["online"] is False and point["charger_link"]["link"] == "offline"


@pytest.mark.parametrize("charger", [
    {"address": 0, "link": "online"}, {"address": 248}, {"address": 1, "link": "unknown"},
])
def test_invalid_reported_charger_fields_are_rejected(setup, charger):
    client, _, _ = setup
    response = client.post("/v1/devices/sync", headers=DEVICE, json=sync_payload(1, charger={**HCA, **charger}))
    assert response.status_code == 422


def test_old_firmware_keeps_working_with_a_configured_charger(setup, factory):
    client, _, seed = setup
    assert _patch(client, seed["point"], 1).status_code == 200
    # Firmware sem `charger` (0.4.0) e firmware com o carregador de bancada, sem address/link.
    assert client.post("/v1/devices/sync", headers=DEVICE, json=sync_payload(1)).status_code == 200
    point = _point(client.get(f"/v1/stations/{seed['station']}").json())
    assert point["charger_link"]["link"] == "pending"
    bench = {"model": "esp32_bench", "transport": "simulated", "min_power_w": 1400, "max_power_w": 7200}
    assert client.post("/v1/devices/sync", headers=DEVICE, json=sync_payload(2, charger=bench)).status_code == 200
    with factory() as db:
        stored = db.get(Device, seed["device"]).charger
    assert "address" not in stored and "link" not in stored  # mesmo formato de antes
    assert _point(client.get(f"/v1/stations/{seed['station']}").json())["charger_link"]["link"] == "pending"


def _code(factory, seed):
    with factory() as db:
        return current_code(db.get(Station, seed["station"]))[0]


def test_simulator_follows_the_link_and_charges_through_the_external_charger(setup, factory, tmp_path):
    client, selected, seed = setup
    with factory.begin() as db:
        db.get(Connector, seed["point"]).power_kw = Decimal(7)
    simulator = Simulator(tmp_path / "hca.json", hca_link=True)

    def exchange():
        response = client.post("/v1/devices/sync", headers=DEVICE, json=simulator.payload())
        assert response.status_code == 200, response.text
        simulator.response(response.json())
        return response.json()

    exchange()
    assert simulator.link_address is None and simulator.payload()["charger"]["model"] == "simulated_bench"
    assert _patch(client, seed["point"], 1).status_code == 200
    exchange()
    assert simulator.link_address == 1
    exchange()  # agora a tela reporta o carregador externo
    point = _point(client.get(f"/v1/stations/{seed['station']}").json())
    assert point["charger_link"]["link"] == "online"
    selected["id"] = seed["a"]
    started = client.post("/v1/charging-sessions", headers={"Idempotency-Key": "hca-start"},
                          json={"public_code": "CG-01", "presence_code": _code(factory, seed)})
    assert started.status_code in (200, 201, 202), started.text
    exchange()
    exchange()
    assert simulator.state == "charging" and simulator.transport.read(10060) == [2]
    assert simulator.power_w <= 7000  # GW7K: no máximo 7 kW no 10029
    # Carregador some da rede: a tela para a sessão e reporta o link offline.
    simulator.link_online = False
    sent = simulator.payload()
    assert sent["physical_state"] == "stopped" and sent["end_reason"] == "charger_unreachable"
    assert sent["charger"]["link"] == "offline"
    simulator.sequence -= 1  # reenvia o mesmo sync pelo exchange
    exchange()
    exchange()
    assert simulator.state != "charging"
    with factory() as db:
        session = db.get(ChargingSession, uuid.UUID(started.json()["id"]))
        assert session.status in ("completed", "failed") and session.end_reason == "charger_unreachable"
    selected["id"] = seed["owner"]
    point = _point(client.get(f"/v1/stations/{seed['station']}").json())
    assert point["charger_link"]["link"] == "offline"


def test_simulator_with_a_new_device_key_reports_the_link(factory, seed, tmp_path):
    """Contrato do corpo: o simulador com --hca-link passa na validação da API."""
    with factory.begin() as db:
        db.get(Connector, seed["point"]).charger_address = 3
        db.get(Device, seed["device"]).key_hash = digest("hca-key")
    client, _ = client_for(factory, seed["owner"])
    try:
        simulator = Simulator(tmp_path / "s.json", hca_link=True, hca_address=3)
        body = simulator.payload()
        assert body["charger"]["address"] == 3 and body["charger"]["link"] == "online"
        assert body["charger"]["transport"] == "modbus_tcp" and body["charger"]["model"] == "goodwe_hca_g2"
        response = client.post("/v1/devices/sync", headers={"Authorization": "Device hca-key"}, json=body)
        assert response.status_code == 200, response.text
        assert response.json()["connector"]["charger_link"]["address"] == 3
    finally:
        clear_overrides()
