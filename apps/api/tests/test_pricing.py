"""Tarifa dinâmica: dados base do dono, status da demanda e preço travado na reserva/recarga."""
from datetime import timedelta
from decimal import Decimal

import pytest
from test_http import clear_overrides, client_for

from app.models import ChargingSession, Connector, Device, Reservation, Station, now
from app.presence_code import current_code
from app.security import digest


@pytest.fixture
def busy(factory, seed):
    """Posto com 2 pontos online: CG-02 em recarga por outro usuário e muitas recargas na última hora."""
    with factory.begin() as db:
        second = Connector(station_id=seed["station"], public_code="CG-02", connector_type="CCS2",
                           power_kw=Decimal(60), price_per_kwh=Decimal("2.0000"), max_duration_minutes=60)
        db.add(second)
        db.flush()
        db.add(Device(connector_id=second.id, key_hash=digest("second-key"), last_seen=now(), reconciled=True,
                      physical_state="charging"))
        moment = now()
        for minutes in (55, 45, 35, 25):
            db.add(ChargingSession(user_id=seed["b"], connector_id=second.id, status="completed",
                                   created_at=moment - timedelta(minutes=minutes),
                                   started_at=moment - timedelta(minutes=minutes),
                                   ended_at=moment - timedelta(minutes=minutes - 9),
                                   max_duration_minutes=10, price_per_kwh=Decimal(2)))
        db.add(ChargingSession(user_id=seed["b"], connector_id=second.id, status="charging",
                               created_at=moment - timedelta(minutes=14), started_at=moment - timedelta(minutes=14),
                               max_duration_minutes=60, price_per_kwh=Decimal(2)))
    yield seed
    clear_overrides()


def test_owner_reads_and_saves_base_data_and_the_calculation_stays_ours(factory, seed):
    client, _ = client_for(factory, seed["owner"])
    body = client.get(f"/v1/stations/{seed['station']}/pricing").json()
    assert body["rules"]["demand"] == {"enabled": True, "max_increase_percent": 50, "sensitivity": "medium"}
    assert body["status"]["multiplier"] == "1.00" and body["status"]["level"] == "low"
    assert body["connectors"][0]["current_price_per_kwh"] == "2.0000"
    saved = client.put(f"/v1/stations/{seed['station']}/pricing", json={
        "demand": {"enabled": True, "max_increase_percent": 30, "sensitivity": "high"},
        "peak": {"enabled": True, "start": "17:30", "end": "20:00", "days": [0, 1, 2, 3, 4]}})
    assert saved.status_code == 200, saved.text
    assert saved.json()["rules"]["demand"]["max_increase_percent"] == 30
    assert saved.json()["rules"]["peak"]["start"] == "17:30"
    invalid = client.put(f"/v1/stations/{seed['station']}/pricing", json={"demand": {"max_increase_percent": 300}})
    assert invalid.status_code == 422 and invalid.json()["error"]["code"] == "invalid_pricing"
    # Só o dono vê e altera as regras; o público vê apenas o efeito (demanda e preço atual).
    other, _ = client_for(factory, seed["a"])
    assert other.get(f"/v1/stations/{seed['station']}/pricing").status_code in (403, 404)
    public = other.get(f"/v1/stations/{seed['station']}").json()
    assert "pricing" not in public and public["demand"]["multiplier"] == "1.00"
    assert public["connectors"][0]["dynamic_price_per_kwh"] == "2.0000"


def test_busy_station_raises_the_price_and_the_session_locks_it(factory, busy):
    seed = busy
    client, _ = client_for(factory, seed["a"])
    station = client.get(f"/v1/stations/{seed['station']}").json()
    multiplier = Decimal(station["demand"]["multiplier"])
    assert multiplier > 1 and station["demand"]["level"] in ("normal", "high", "very_high")
    point = next(p for p in station["connectors"] if p["public_code"] == "CG-01")
    assert Decimal(point["dynamic_price_per_kwh"]) == (Decimal(2) * multiplier).quantize(Decimal("0.0001"))
    owner, _ = client_for(factory, seed["owner"])
    factors = {f["key"]: f for f in owner.get(f"/v1/stations/{seed['station']}/pricing").json()["status"]["factors"]}
    assert factors["occupancy"]["value"] == "1 de 2" and factors["trend"]["value"] == "5"
    client, _ = client_for(factory, seed["a"])
    with factory() as db:
        code = current_code(db.get(Station, seed["station"]))[0]
    started = client.post("/v1/charging-sessions", headers={"Idempotency-Key": "surge-start"},
                          json={"public_code": "CG-01", "presence_code": code, "max_duration_minutes": 30})
    assert started.status_code in (200, 201, 202), started.text
    session = started.json()
    assert Decimal(session["demand_multiplier"]) == multiplier
    assert session["base_price_per_kwh"] == "2.0000"
    assert Decimal(session["price_per_kwh"]) == (Decimal(2) * multiplier).quantize(Decimal("0.0001"))


def test_reservation_locks_the_multiplier_of_the_moment(factory, busy):
    seed = busy
    client, _ = client_for(factory, seed["a"])
    expected = client.get(f"/v1/stations/{seed['station']}").json()["demand"]["multiplier"]
    reserved = client.post("/v1/reservations", headers={"Idempotency-Key": "surge-reserve"},
                           json={"connector_id": str(seed["point"])})
    assert reserved.status_code in (200, 201, 202), reserved.text
    with factory() as db:
        reservation = db.get(Reservation, reserved.json()["id"])
        assert str(reservation.demand_multiplier) == expected
