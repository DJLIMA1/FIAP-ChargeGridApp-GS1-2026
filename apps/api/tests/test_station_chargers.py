"""Estação = a TELA; carregadores = os pontos dela. "Adicionar carregador" cria o próximo
endereço ligado à mesma tela; a tela sincroniza por cada carregador (``charger_address``);
disponibilidade POR carregador: um carregador offline não derruba a estação."""

import sys
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from test_http import clear_overrides, client_for, sync_payload

from app.models import ChargingSession, Connector, Device, Profile, Station, now
from app.presence_code import current_code

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tools.device_simulator import Device as Simulator  # noqa: E402
from tools.device_simulator import Station as SimulatedStation  # noqa: E402

DEVICE = {"Authorization": "Device test-key"}
HCA = {"model": "goodwe_hca_g2", "transport": "modbus_tcp", "min_power_w": 1400, "max_power_w": 7000,
       "step_w": 100}


@pytest.fixture
def owner(factory, seed):
    client, selected = client_for(factory, seed["owner"])
    yield client, selected, seed
    clear_overrides()


def _point(body, point_id):
    return next(item for item in body["connectors"] if item["id"] == str(point_id))


def _station(client, seed):
    return client.get(f"/v1/stations/{seed['station']}").json()


def _sync(client, sequence, address=None, link="online", **changes):
    body = sync_payload(sequence, charger={**HCA, "address": address or 1, "link": link}, **changes)
    if address is not None:
        body["charger_address"] = address
    return client.post("/v1/devices/sync", headers=DEVICE, json=body)


def _add(client, point):
    response = client.post(f"/v1/connectors/{point}/chargers")
    assert response.status_code == 201, response.text
    return response.json()


def _code(factory, seed):
    with factory() as db:
        return current_code(db.get(Station, seed["station"]))[0]


def test_add_charger_creates_the_next_address_linked_to_the_same_screen(owner, factory):
    client, _, seed = owner
    assert _sync(client, 1).status_code == 200
    added = _add(client, seed["point"])
    assert added["charger_address"] == 2 and added["active"] is False
    assert added["connector_type"] == "bench" and Decimal(added["power_kw"]) == 1
    assert added["charger_link"]["host"] == "cg-hca-2.local"
    assert added["screen"]["role"] == "charger" and added["screen"]["public_code"] == "CG-01"
    assert added["screen"]["device_id"] == str(seed["device"]) and added["screen"]["online"] is True
    # Adicionar a partir do carregador adicional usa a tela dele.
    third = _add(client, added["id"])
    assert third["charger_address"] == 3 and third["screen"]["device_id"] == str(seed["device"])
    with factory() as db:
        child = db.query(Device).filter(Device.connector_id == uuid.UUID(added["id"])).one()
        assert child.parent_device_id == seed["device"] and not child.revoked
    body = _station(client, seed)
    screen = _point(body, seed["point"])["screen"]
    assert screen["role"] == "screen" and screen["multi_charger"] is False
    assert body["screen_online"] is True
    assert body["screens"] == [{
        "device_id": str(seed["device"]), "connector_id": str(seed["point"]), "public_code": "CG-01",
        "online": True, "last_seen": screen["last_seen"], "firmware_version": "test", "multi_charger": False,
        "charger_ids": [str(seed["point"]), added["id"], third["id"]],
    }]


def test_add_charger_requires_a_screen_and_the_owner(owner, factory):
    client, selected, seed = owner
    with factory.begin() as db:
        bare = Connector(station_id=seed["station"], public_code="CG-NOSCREEN", connector_type="Tipo 2",
                         power_kw=Decimal(7), price_per_kwh=Decimal(2), max_duration_minutes=60)
        db.add(bare)
        db.flush()
        bare_id = bare.id
    refused = client.post(f"/v1/connectors/{bare_id}/chargers")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "screen_required"
    assert client.post(f"/v1/connectors/{uuid.uuid4()}/chargers").status_code == 404
    with factory.begin() as db:
        intruder = Profile(id=uuid.uuid4(), name="Outro", operator_enabled=True)
        db.add(intruder)
        db.flush()
        selected["id"] = intruder.id
    assert client.post(f"/v1/connectors/{seed['point']}/chargers").status_code == 404
    selected["id"] = seed["a"]
    assert client.post(f"/v1/connectors/{seed['point']}/chargers").status_code == 403


def test_screen_syncs_for_each_charger_and_availability_is_per_charger(owner, factory):
    client, selected, seed = owner
    added = _add(client, seed["point"])
    assert client.patch(f"/v1/connectors/{added['id']}", json={"active": True}).status_code == 200
    # Tela online, carregador 2 nunca sincronizado: só ele offline (charger_offline).
    response = _sync(client, 1, capabilities=["set_power_v1", "multi_charger_v1"])
    assert response.status_code == 200
    assert response.json()["chargers"] == [{
        "address": 2, "connector_id": added["id"], "public_code": added["public_code"],
        "charger_link": {"model": "goodwe_hca_g2", "transport": "modbus_tcp", "address": 2, "host": "cg-hca-2.local"},
    }]
    body = _station(client, seed)
    child = _point(body, added["id"])
    assert child["unavailable_reason"] == "charger_offline" and child["online"] is False
    assert child["screen_online"] is True and child["charger_link"]["link"] == "offline"
    assert _point(body, seed["point"])["available"] is True and body["screen_online"] is True
    assert _point(body, seed["point"])["screen"]["multi_charger"] is True
    # Sync endereçado do carregador 2 (mesma chave da tela): online e disponível.
    addressed = _sync(client, 2, address=2)
    assert addressed.status_code == 200, addressed.text
    reply = addressed.json()
    assert reply["connector"]["id"] == added["id"] and reply["connector"]["charger_link"]["address"] == 2
    assert "chargers" not in reply
    child = _point(_station(client, seed), added["id"])
    assert child["available"] is True and child["online"] is True and child["charger_link"]["link"] == "online"
    # Só o carregador 1 cai: a estação (tela) continua online e o 2 segue disponível.
    assert _sync(client, 3, link="offline").status_code == 200
    body = _station(client, seed)
    assert _point(body, seed["point"])["unavailable_reason"] == "charger_offline"
    assert _point(body, added["id"])["available"] is True and body["screen_online"] is True
    selected["id"] = seed["a"]
    refused = client.post("/v1/charging-sessions", headers={"Idempotency-Key": "c1"},
                          json={"public_code": "CG-01", "presence_code": _code(factory, seed)})
    assert refused.status_code == 409
    assert refused.json()["error"]["alternatives"] == [{"id": added["id"], "public_code": added["public_code"]}]
    # A tela parou de sincronizar pelo carregador 2 (> 45 s): só ele offline.
    selected["id"] = seed["owner"]
    with factory.begin() as db:
        db.query(Device).filter(Device.connector_id == uuid.UUID(added["id"])).one().last_seen = (
            now() - timedelta(seconds=60))
    assert _sync(client, 4).status_code == 200
    body = _station(client, seed)
    assert _point(body, added["id"])["unavailable_reason"] == "charger_offline"
    assert _point(body, seed["point"])["available"] is True
    # Tela sem contato: tudo offline com screen_offline.
    with factory.begin() as db:
        db.get(Device, seed["device"]).last_seen = now() - timedelta(seconds=60)
    body = _station(client, seed)
    assert body["screen_online"] is False
    assert {item["unavailable_reason"] for item in body["connectors"]} == {"screen_offline"}
    live = {item["connector_id"]: item for item in client.get("/v1/owner/live").json()["items"]}
    assert live[added["id"]]["unavailable_reason"] == "screen_offline" and live[added["id"]]["online"] is False


def test_owner_live_shows_the_charger_offline_but_the_screen_online(owner):
    client, _, seed = owner
    assert _sync(client, 1, link="offline").status_code == 200
    item = next(row for row in client.get("/v1/owner/live").json()["items"] if row["connector_id"] == str(seed["point"]))
    assert item["availability_status"] == "offline" and item["unavailable_reason"] == "charger_offline"
    assert item["online"] is False and item["screen_online"] is True
    assert _sync(client, 2).status_code == 200
    item = next(row for row in client.get("/v1/owner/live").json()["items"] if row["connector_id"] == str(seed["point"]))
    assert item["available"] is True and item["online"] is True and item["unavailable_reason"] is None


def test_owner_alerts_name_the_offline_charger(owner):
    client, _, seed = owner
    added = _add(client, seed["point"])
    assert client.patch(f"/v1/connectors/{added['id']}", json={"active": True}).status_code == 200
    assert _sync(client, 1, link="offline").status_code == 200
    alerts = {(item["public_code"], item["kind"]) for item in client.get("/v1/owner/alerts").json()["items"]}
    assert ("CG-01", "charger_offline") in alerts and (added["public_code"], "charger_offline") in alerts
    assert not any(kind == "device_offline" for _, kind in alerts)
    assert _sync(client, 2).status_code == 200 and _sync(client, 3, address=2).status_code == 200
    alerts = {item["kind"] for item in client.get("/v1/owner/alerts").json()["items"]}
    assert "charger_offline" not in alerts and "device_offline" not in alerts


def test_addressed_sync_only_reaches_this_screens_chargers(owner, factory):
    client, _, seed = owner
    unknown = _sync(client, 1, address=9)
    assert unknown.status_code == 409 and unknown.json()["error"]["code"] == "charger_not_linked"
    # Endereço da própria tela = o sync de sempre.
    own = _sync(client, 2, address=1)
    assert own.status_code == 200 and own.json()["connector"]["id"] == str(seed["point"])
    added = _add(client, seed["point"])
    with factory.begin() as db:
        # Outra tela no mesmo posto não sincroniza pelo carregador desta.
        other_point = Connector(station_id=seed["station"], public_code="CG-OTHER", connector_type="bench",
                                power_kw=1, price_per_kwh=2, max_duration_minutes=60)
        db.add(other_point)
        db.flush()
        from app.security import digest
        db.add(Device(connector_id=other_point.id, key_hash=digest("other-key"), last_seen=now()))
    body = sync_payload(1, charger_address=2)
    foreign = client.post("/v1/devices/sync", headers={"Authorization": "Device other-key"}, json=body)
    assert foreign.status_code == 409 and foreign.json()["error"]["code"] == "charger_not_linked"
    # O carregador adicional não tem chave própria nem credenciais gerenciáveis.
    with factory() as db:
        child = db.query(Device).filter(Device.connector_id == uuid.UUID(added["id"])).one()
    assert client.post(f"/v1/devices/{child.id}/rotate-key").json()["error"]["code"] == "charger_device"
    assert client.post(f"/v1/devices/{child.id}/revoke").json()["error"]["code"] == "charger_device"
    device = client.get(f"/v1/connectors/{added['id']}/device").json()
    assert device["screen_device_id"] == str(seed["device"])
    assert client.post("/v1/devices/sync", headers=DEVICE, json=sync_payload(3, charger_address=0)).status_code == 422


def test_simulated_station_charges_on_an_added_charger(owner, factory, tmp_path):
    """Bancada: a tela segue ``chargers`` e carrega pelo carregador 2 (sync endereçado)."""
    client, selected, seed = owner
    added = _add(client, seed["point"])
    assert client.patch(f"/v1/connectors/{added['id']}", json={"active": True}).status_code == 200

    def post(body):
        response = client.post("/v1/devices/sync", headers=DEVICE, json=body)
        assert response.status_code == 200, response.text
        return response.json()

    station = SimulatedStation(Simulator(tmp_path / "screen.json"),
                               lambda address: Simulator(tmp_path / f"c{address}.json", hca_address=address,
                                                         charger_address=address))
    station.exchange_all(post)
    station.exchange_all(post)
    assert set(station.children) == {2}
    assert _point(_station(client, seed), added["id"])["available"] is True
    selected["id"] = seed["a"]
    started = client.post("/v1/charging-sessions", headers={"Idempotency-Key": "c2"},
                          json={"public_code": added["public_code"], "presence_code": _code(factory, seed)})
    assert started.status_code in (200, 201, 202), started.text
    for _ in range(3):
        station.exchange_all(post)
    child = station.children[2]
    assert child.state == "charging" and child.session_on_charger and station.screen.state == "idle"
    with factory() as db:
        session = db.get(ChargingSession, uuid.UUID(started.json()["id"]))
        assert session.status == "charging" and str(session.connector_id) == added["id"]
