"""Tarifa dinâmica: dados base do dono, status da demanda e preço travado na reserva/recarga."""
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from test_http import clear_overrides, client_for

from app.models import ChargingSession, Connector, Device, Reservation, Station, now
from app.modules.pricing.service import LOCAL_TIMEZONE
from app.presence_code import current_code
from app.security import digest


@pytest.fixture
def busy(factory, seed):
    """Posto com 2 pontos online: CG-02 em recarga por outro usuário e muitas recargas na última hora."""
    with factory.begin() as db:
        # Rebalanceamento ligado por padrão: CG-02 (60 kW, equipamento sem ajuste ao vivo) + a loja simulada
        # passariam do limite padrão de 75 kW; um limite contratado maior deixa espaço para o CG-01.
        db.get(Station, seed["station"]).site_limit_kw = Decimal(150)
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


ALL_WEEK = [0, 1, 2, 3, 4, 5, 6]


def _whole_week(point_id, price="1.5000"):
    """Dois horários que cobrem a semana inteira: o teste não depende do relógio."""
    return {"enabled": True, "intervals": [
        {"start": "00:00", "end": "12:00", "days": ALL_WEEK, "prices": {str(point_id): price}},
        {"start": "12:00", "end": "00:00", "days": ALL_WEEK, "prices": {str(point_id): price}}]}


def test_schedule_put_merges_with_stored_rules_and_strips_foreign_connectors(factory, seed):
    client, _ = client_for(factory, seed["owner"])
    url = f"/v1/stations/{seed['station']}/pricing"
    schedule = _whole_week(seed["point"])
    schedule["intervals"][0]["prices"][str(uuid4())] = "9.0000"  # conector de outro posto
    saved = client.put(url, json={"schedule": schedule})
    assert saved.status_code == 200, saved.text
    intervals = saved.json()["rules"]["schedule"]["intervals"]
    assert [i["prices"] for i in intervals] == [{str(seed["point"]): "1.5000"}] * 2
    # Um PUT parcial (como o do app 0.6.8, que não conhece ``schedule``) não apaga os horários.
    partial = client.put(url, json={"demand": {"max_increase_percent": 30}})
    assert partial.json()["rules"]["schedule"]["intervals"] == intervals
    assert partial.json()["rules"]["demand"] == {"enabled": True, "max_increase_percent": 30, "sensitivity": "medium"}
    status = partial.json()["status"]
    assert status["peak_now"] is False and status["reason"] == "schedule"
    assert partial.json()["connectors"][0]["current_base_price_per_kwh"] == "1.5000"
    assert partial.json()["connectors"][0]["base_price_per_kwh"] == "2.0000"
    overlap = client.put(url, json={"schedule": {"intervals": [
        {"start": "08:00", "end": "10:00", "days": [0], "prices": {str(seed["point"]): "1"}},
        {"start": "09:00", "end": "11:00", "days": [0], "prices": {str(seed["point"]): "1"}}]}})
    assert overlap.status_code == 422 and "se sobrepõem" in overlap.json()["error"]["message"]
    foreign = client.put(url, json={"schedule": {"intervals": [
        {"start": "08:00", "end": "10:00", "days": [0], "prices": {str(uuid4()): "1"}}]}})
    assert foreign.status_code == 422 and foreign.json()["error"]["code"] == "invalid_pricing"


def test_legacy_stored_rules_with_peak_still_load(factory, seed):
    with factory.begin() as db:
        db.get(Station, seed["station"]).pricing = {
            "demand": {"enabled": True, "max_increase_percent": 40, "sensitivity": "high"},
            "peak": {"enabled": True, "start": "18:00", "end": "21:00", "days": ALL_WEEK}}
    client, _ = client_for(factory, seed["owner"])
    body = client.get(f"/v1/stations/{seed['station']}/pricing").json()
    assert body["rules"]["peak"]["start"] == "18:00" and body["rules"]["schedule"] == {"enabled": True, "intervals": []}
    assert body["status"]["peak_now"] is False and body["status"]["reason_label"] == "Preço normal"


def test_schedule_sets_the_public_price_and_the_session_locks_it(factory, seed):
    owner, _ = client_for(factory, seed["owner"])
    assert owner.put(f"/v1/stations/{seed['station']}/pricing",
                     json={"schedule": _whole_week(seed["point"])}).status_code == 200
    client, _ = client_for(factory, seed["a"])
    public = client.get(f"/v1/stations/{seed['station']}").json()
    point = public["connectors"][0]
    assert (point["price_per_kwh"], point["current_base_price_per_kwh"], point["dynamic_price_per_kwh"]) == \
        ("2.0000", "1.5000", "1.5000")
    assert public["demand"]["reason"] == "schedule" and public["demand"]["reason_label"].startswith("Horário ")
    assert "pricing" not in public
    with factory() as db:
        code = current_code(db.get(Station, seed["station"]))[0]
    started = client.post("/v1/charging-sessions", headers={"Idempotency-Key": "schedule-start"},
                          json={"public_code": "CG-01", "presence_code": code, "max_duration_minutes": 30})
    assert started.status_code in (200, 201, 202), started.text
    session = started.json()
    assert (session["base_price_per_kwh"], session["demand_multiplier"], session["price_per_kwh"]) == \
        ("1.5000", "1.00", "1.5000")


def test_reservation_keeps_the_schedule_base_of_the_moment_it_was_made(factory, seed):
    local = now().astimezone(LOCAL_TIMEZONE)
    hour = (local.hour + 12) % 24  # um horário que não é o de agora
    window = {"start": f"{hour:02d}:00", "end": f"{(hour + 1) % 24:02d}:00", "days": ALL_WEEK,
              "prices": {str(seed["point"]): "1.2000"}}
    owner, _ = client_for(factory, seed["owner"])
    assert owner.put(f"/v1/stations/{seed['station']}/pricing",
                     json={"schedule": {"intervals": [window]}}).status_code == 200
    client, _ = client_for(factory, seed["a"])
    assert client.get(f"/v1/stations/{seed['station']}").json()["connectors"][0]["dynamic_price_per_kwh"] == "2.0000"
    reserved = client.post("/v1/reservations", headers={"Idempotency-Key": "schedule-reserve"},
                           json={"connector_id": str(seed["point"])})
    assert reserved.status_code in (200, 201, 202), reserved.text
    assert reserved.json()["connector"]["price_per_kwh"] == "2.0000"
    made_at = (local - timedelta(days=1)).replace(hour=hour, minute=30, second=0, microsecond=0)
    with factory.begin() as db:
        reservation = db.get(Reservation, reserved.json()["id"])
        # Reserva feita dentro do horário de R$ 1,20 e já confirmada pelo ponto.
        reservation.created_at = made_at
        reservation.status, reservation.expires_at = "confirmed", now() + timedelta(minutes=15)
        device = db.get(Device, seed["device"])
        device.physical_state, device.reconciled, device.last_seen = "reserved", True, now()
        code = current_code(db.get(Station, seed["station"]))[0]
    mine = client.get("/v1/reservations/current")
    assert mine.status_code == 200, mine.text
    assert mine.json()["connector"]["price_per_kwh"] == "1.2000"
    assert mine.json()["connector"]["base_price_per_kwh"] == "2.0000"
    started = client.post("/v1/charging-sessions", headers={"Idempotency-Key": "schedule-reserved-start"},
                          json={"presence_code": code, "reservation_id": reserved.json()["id"],
                                "max_duration_minutes": 30})
    assert started.status_code in (200, 201, 202), started.text
    assert (started.json()["base_price_per_kwh"], started.json()["price_per_kwh"]) == ("1.2000", "1.2000")
