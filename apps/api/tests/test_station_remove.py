"""Remover estação (``DELETE /v1/stations/{id}``): o posto some de todas as listas, o histórico fica."""

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from test_http import clear_overrides, client_for

from app.models import ChargingSession, Connector, Device, Profile, Reservation, Station, now
from app.security import digest


@pytest.fixture
def owner(factory, seed):
    client, selected = client_for(factory, seed["owner"])
    yield client, selected, seed
    clear_overrides()


def _offline(factory, seed):
    with factory.begin() as db:
        db.get(Device, seed["device"]).last_seen = now() - timedelta(minutes=5)


def _finished_session(factory, seed):
    with factory.begin() as db:
        ended = now() - timedelta(hours=1)
        session = ChargingSession(
            user_id=seed["a"], connector_id=seed["point"], status="completed", created_at=ended - timedelta(hours=1),
            started_at=ended - timedelta(hours=1), ended_at=ended, max_duration_minutes=60,
            price_per_kwh=Decimal(2), energy_wh=Decimal(3000), cost_estimate=Decimal(6),
        )
        db.add(session)
        db.flush()
        return session.id


def test_remove_hides_the_station_everywhere_and_keeps_history(owner, factory):
    client, selected, seed = owner
    station = str(seed["station"])
    with factory.begin() as db:
        db.get(Station, seed["station"]).active = True
        db.get(Connector, seed["point"]).active = True
    session_id = _finished_session(factory, seed)
    _offline(factory, seed)
    assert any(item["id"] == station for item in client.get("/v1/stations").json()["items"])

    response = client.delete(f"/v1/stations/{station}")
    assert response.status_code == 204, response.text

    assert client.get(f"/v1/stations/{station}").status_code == 404
    assert all(item["id"] != station for item in client.get("/v1/stations").json()["items"])
    assert client.get("/v1/operator/stations").json()["items"] == []
    assert client.get("/v1/operator/summary").json()["stations"] == 0
    assert client.get("/v1/owner/live").json()["items"] == []
    assert client.get("/v1/owner/alerts").json()["items"] == []
    overview = client.get("/v1/owner/overview").json()
    assert overview["stations"]["total"] == 0 and overview["stations"]["points"] == 0
    # A receita do período continua contando a recarga da estação removida (histórico).
    assert overview["kpis"]["sessions"] == 1
    assert [str(row["station_id"]) for row in overview["ranking"]] == [station]
    assert client.get(f"/v1/owner/overview?station_id={station}").status_code == 404
    assert client.get(f"/v1/stations/{station}/charging-sessions").status_code == 404
    with factory() as db:
        removed = db.get(Station, seed["station"])
        assert removed.removed_at is not None and removed.active is False
        point = db.get(Connector, seed["point"])
        assert point.removed_at is not None and point.active is False and point.charger_address is None
        assert db.get(Device, seed["device"]).revoked is True
    # Histórico do dono: a sessão continua nos relatórios.
    sessions = client.get("/v1/owner/sessions").json()["items"]
    assert [item["id"] for item in sessions] == [str(session_id)]

    # Histórico do motorista: recibo e lista continuam.
    selected["id"] = seed["a"]
    assert client.get(f"/v1/charging-sessions/{session_id}/receipt").status_code == 200
    mine = client.get("/v1/me/charging-sessions").json()["items"]
    assert [item["id"] for item in mine] == [str(session_id)]
    assert all(item["id"] != station for item in client.get("/v1/stations").json()["items"])


def test_removed_station_cannot_be_patched_reactivated_or_removed_again(owner, factory):
    client, _, seed = owner
    _offline(factory, seed)
    station = seed["station"]
    assert client.delete(f"/v1/stations/{station}").status_code == 204
    assert client.patch(f"/v1/stations/{station}", json={"active": True}).status_code == 404
    assert client.patch(f"/v1/stations/{station}", json={"name": "De volta"}).status_code == 404
    assert client.patch(f"/v1/connectors/{seed['point']}", json={"active": True}).status_code == 404
    assert client.delete(f"/v1/stations/{station}").status_code == 404
    with factory() as db:
        assert db.get(Station, station).active is False


def test_busy_station_is_refused(owner, factory):
    client, _, seed = owner
    _offline(factory, seed)
    with factory.begin() as db:
        db.add(Reservation(user_id=seed["a"], connector_id=seed["point"], status="confirmed",
                           confirmation_deadline=now() + timedelta(minutes=5)))
    response = client.delete(f"/v1/stations/{seed['station']}")
    assert response.status_code == 409 and response.json()["error"]["code"] == "station_busy"
    with factory.begin() as db:
        db.query(Reservation).delete()
        db.add(ChargingSession(user_id=seed["a"], connector_id=seed["point"], status="charging",
                               max_duration_minutes=60, price_per_kwh=Decimal(2)))
    response = client.delete(f"/v1/stations/{seed['station']}")
    assert response.status_code == 409 and response.json()["error"]["code"] == "station_busy"
    with factory() as db:
        assert db.get(Station, seed["station"]).removed_at is None


def test_online_central_is_refused(owner, factory):
    client, _, seed = owner
    response = client.delete(f"/v1/stations/{seed['station']}")
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "central_online" and "Restaurar" in error["message"]
    with factory() as db:
        assert db.get(Station, seed["station"]).removed_at is None
        assert db.get(Device, seed["device"]).revoked is False


def test_offline_central_and_its_chargers_are_revoked(owner, factory):
    client, _, seed = owner
    with factory.begin() as db:
        charger = Connector(station_id=seed["station"], public_code="CG-02", connector_type="bench", power_kw=1,
                            price_per_kwh=2, max_duration_minutes=60, charger_address=2)
        db.add(charger)
        db.flush()
        child = Device(connector_id=charger.id, key_hash=digest("child"), parent_device_id=seed["device"])
        db.add(child)
        db.flush()
        charger_id, child_id = charger.id, child.id
    _offline(factory, seed)
    assert client.delete(f"/v1/stations/{seed['station']}").status_code == 204
    with factory() as db:
        assert db.get(Device, seed["device"]).revoked is True
        assert db.get(Device, child_id).revoked is True
        for point_id in (seed["point"], charger_id):
            point = db.get(Connector, point_id)
            assert point.removed_at is not None and point.charger_address is None and point.active is False


def test_only_the_owner_operator_can_remove(owner, factory):
    client, selected, seed = owner
    _offline(factory, seed)
    with factory.begin() as db:
        intruder = Profile(id=uuid.uuid4(), name="Outro", operator_enabled=True)
        db.add(intruder)
        db.flush()
        selected["id"] = intruder.id
    assert client.delete(f"/v1/stations/{seed['station']}").status_code == 404
    selected["id"] = seed["a"]
    assert client.delete(f"/v1/stations/{seed['station']}").status_code == 403
    assert client.delete(f"/v1/stations/{uuid.uuid4()}").status_code == 403
    selected["id"] = seed["owner"]
    assert client.delete(f"/v1/stations/{uuid.uuid4()}").status_code == 404
    with factory() as db:
        assert db.get(Station, seed["station"]).removed_at is None


def test_central_of_a_removed_station_gets_back_to_the_claim_qr(owner, factory):
    """Posto removido com a central offline: a central ainda usa a chave antiga. Em vez de ficar
    presa em "Chave inválida", ela recebe só a restauração de fábrica e volta ao QR de vínculo."""
    from test_http import sync_payload

    from app.models import DeviceClaim

    client, _, seed = owner
    _offline(factory, seed)
    assert client.delete(f"/v1/stations/{seed['station']}").status_code == 204
    device = {"Authorization": "Device test-key"}
    first = client.post("/v1/devices/sync", headers=device, json=sync_payload(1))
    assert first.status_code == 200
    commands = first.json()["commands"]
    assert [command["type"] for command in commands] == ["FACTORY_RESET"]
    assert first.json()["connector"]["active"] is False
    ack = {"command_id": commands[0]["id"], "status": "applied",
           "new_device_key_hash": digest("new-key"), "new_claim_token_hash": digest("new-claim")}
    applied = client.post("/v1/devices/sync", headers=device, json=sync_payload(2, acks=[ack]))
    assert applied.status_code == 200 and applied.json()["commands"] == []
    with factory() as db:
        fresh = db.query(Device).filter(Device.key_hash == digest("new-key")).one()
        point = db.get(Connector, fresh.connector_id)
        assert point.station_id != seed["station"] and point.active is False
        assert db.get(Station, point.station_id).owner_id is None
        assert db.get(DeviceClaim, point.id).token_hash == digest("new-claim")
    # Restaurada: a chave antiga não serve mais; a nova sincroniza o ponto de fábrica.
    assert client.post("/v1/devices/sync", headers=device, json=sync_payload(3)).status_code == 401
    renewed = client.post("/v1/devices/sync", headers={"Authorization": "Device new-key"}, json=sync_payload(1))
    assert renewed.status_code == 200 and renewed.json()["connector"]["owned"] is False


def test_other_revoked_keys_stay_rejected(owner, factory):
    client, _, seed = owner
    with factory.begin() as db:
        db.get(Device, seed["device"]).revoked = True  # revogada com o posto ainda ativo
    from test_http import sync_payload
    assert client.post("/v1/devices/sync", headers={"Authorization": "Device test-key"},
                       json=sync_payload(1)).status_code == 401
