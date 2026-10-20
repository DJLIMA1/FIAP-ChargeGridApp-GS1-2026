"""Permanência após a recarga (overstay): fim da carga ≠ veículo desconectado, taxa sobre tempo confirmado."""

from datetime import timedelta
from decimal import Decimal

import pytest
from test_http import clear_overrides, client_for, sync_payload
from test_payments import Flow, _checkout

from app import overstay as overstay_service
from app.models import ChargingSession, Device, Payment, Profile, SessionEvent, Station, now
from app.modules.payments import gateway
from app.modules.payments.fake import FakeStripe
from app.modules.payments.overstay import overstay_charge, overstay_terms
from app.presence_code import current_code

DEVICE = {"Authorization": "Device test-key"}
RULE = {"enabled": True, "start_after_min": 1, "interval_min": 1, "amount": "1.00", "max_amount": "3.00"}


class Clock:
    def __init__(self):
        self.value = now()

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


@pytest.fixture
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(overstay_service, "now", fake)
    return fake


@pytest.fixture
def http(factory, seed):
    client, _ = client_for(factory, seed["a"])
    yield client
    clear_overrides()


class Bench:
    def __init__(self, http, factory, seed):
        self.http, self.factory, self.seed, self.sequence, self.boot = http, factory, seed, 0, "boot-a"

    def rules(self, **rotation):
        with self.factory.begin() as db:
            station = db.get(Station, self.seed["station"])
            station.pricing = {"rotation": {**RULE, **rotation}}

    def version(self):
        return self.http.get(f"/v1/stations/{self.seed['station']}").json()["overstay"]["version"]

    def sync(self, **changes):
        self.sequence += 1
        response = self.http.post("/v1/devices/sync", headers=DEVICE,
                                  json=sync_payload(self.sequence, boot_id=self.boot, **changes))
        assert response.status_code == 200, response.text
        return response.json()

    def start(self, key="start", expect=202, **body):
        with self.factory() as db:
            code = current_code(db.get(Station, self.seed["station"]))[0]
        response = self.http.post("/v1/charging-sessions", headers={"Idempotency-Key": key},
                                  json={"public_code": "CG-01", "presence_code": code, **body})
        assert response.status_code == expect, response.text
        return response.json()

    def charge(self, session_id):
        start_cmd = next(cmd for cmd in self.sync()["commands"] if cmd["type"] == "START")
        self.sync(session_id=session_id, physical_state="charging", connected=True,
                  acks=[{"command_id": start_cmd["id"], "status": "applied", "error": None}])
        self.sync(session_id=session_id, physical_state="charging", connected=True, energy_wh=500)
        return start_cmd

    def end(self, session_id, connected=True, reason="cost_limit"):
        """Spontaneous device stop (cost limit) with the cable still connected or not."""
        return self.sync(session_id=session_id, physical_state="stopped", connected=connected, energy_wh=500,
                         end_reason=reason)

    def idle(self, connected=True):
        return self.sync(physical_state="idle", connected=connected)

    def session(self, session_id):
        return self.http.get(f"/v1/charging-sessions/{session_id}").json()

    def events(self, session_id):
        with self.factory() as db:
            return [event.kind for event in db.query(SessionEvent).filter(SessionEvent.session_id == session_id)
                    .order_by(SessionEvent.id)]

    def point(self):
        return self.http.get(f"/v1/stations/{self.seed['station']}").json()["connectors"][0]


@pytest.fixture
def bench(http, factory, seed):
    return Bench(http, factory, seed)


def test_station_shows_public_terms_and_pricing_validates_the_cap(bench, factory, seed):
    owner, _ = client_for(factory, seed["owner"])
    station = bench.http.get(f"/v1/stations/{seed['station']}").json()
    assert station["overstay"]["enabled"] is False and "pricing" not in station
    rules = owner.get(f"/v1/stations/{seed['station']}/pricing").json()["rules"]
    assert rules["rotation"] == {"enabled": False, "start_after_min": 10, "interval_min": 1, "amount": "1.00",
                                 "max_amount": "30.00"}
    rules["rotation"].update(enabled=True, start_after_min=0, max_amount="1000.01")
    response = owner.put(f"/v1/stations/{seed['station']}/pricing", json=rules)
    assert response.status_code == 422 and "1.000,00" in response.json()["error"]["message"]
    rules["rotation"]["max_amount"] = "20"
    assert owner.put(f"/v1/stations/{seed['station']}/pricing", json=rules).status_code == 200
    shown = bench.http.get(f"/v1/stations/{seed['station']}").json()["overstay"]
    assert shown["enabled"] is True and shown["max_amount"] == "20.00" and shown["grace_minutes"] == 0
    assert shown["summary"] == "Após a recarga: 0 min de tolerância; depois R$ 1,00 por minuto, até R$ 20,00."
    assert bench.http.get("/v1/stations").json()["items"][0]["overstay"]["version"] == shown["version"]
    clear_overrides()


def test_connected_after_charging_runs_grace_fee_cap_then_disconnect(bench, clock, factory, seed):
    bench.rules()
    session = bench.start(overstay_terms_version=bench.version())
    assert session["overstay"]["status"] == "none" and session["overstay"]["fee_applies"] is True
    start_cmd = bench.charge(session["id"])
    assert start_cmd["parameters"]["overstay"] == {"grace_minutes": 1, "interval_minutes": 1, "amount": "1.00",
                                                   "max_amount": "3.00"}
    synced = bench.end(session["id"])
    assert synced["overstay"]["status"] == "grace" and synced["overstay"]["grace_remaining_seconds"] == 60
    current = bench.session(session["id"])
    assert current["status"] == "completed" and current["end_reason"] == "cost_limit"
    assert current["overstay"]["status"] == "grace" and current["settlement_ready"] is False
    assert not any(key.startswith("overstay_") for key in current)
    # Still connected: the point is occupied and nobody else can start there.
    assert bench.point()["availability_status"] == "occupied"
    other, _ = client_for(factory, seed["b"])
    with factory() as db:
        code = current_code(db.get(Station, seed["station"]))[0]
    blocked = other.post("/v1/charging-sessions", headers={"Idempotency-Key": "b"},
                         json={"public_code": "CG-01", "presence_code": code})
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "point_unavailable"
    clear_overrides()
    bench.http, _ = client_for(factory, seed["a"])
    # Grace: 40 s + 30 s = 70 s confirmed -> past the minute of tolerance, no full minute billed yet.
    for seconds in (40, 30):
        clock.advance(seconds)
        block = bench.idle()["overstay"]
    assert block["status"] == "billing" and block["fee_due"] == "0.00"
    for _ in range(4):
        clock.advance(30)
        bench.idle()
    shown = bench.http.get("/v1/overstays/current").json()
    assert shown["session_id"] == session["id"] and shown["station_name"] == "Demo"
    assert shown["billable_seconds"] == 190 and shown["fee_due"] == "2.00" and shown["billable_minutes"] == 2
    for _ in range(4):
        clock.advance(30)
        bench.idle()
    capped = bench.session(session["id"])["overstay"]
    assert capped["status"] == "capped" and capped["fee_due"] == "3.00"
    assert bench.session(session["id"])["settlement_ready"] is True  # the amount cannot grow anymore
    clock.advance(30)
    released = bench.idle(connected=False)
    assert released["overstay"] is None
    final = bench.session(session["id"])["overstay"]
    assert final["status"] == "closed" and final["end_reason"] == "disconnected" and final["fee_due"] == "3.00"
    assert bench.http.get("/v1/overstays/current").json() is None
    assert bench.point()["availability_status"] == "available"
    events = bench.events(session["id"])
    assert events.count("settlement_ready") == 1 and events.count("overstay_billing_started") == 1
    for kind in ("ended", "overstay_started", "overstay_capped", "overstay_ended", "vehicle_disconnected"):
        assert kind in events
    assert events.index("ended") < events.index("overstay_started") < events.index("vehicle_disconnected")


def test_old_firmware_disconnects_at_stop_so_no_overstay_and_point_frees(bench, clock):
    bench.rules()
    session = bench.start(overstay_terms_version=bench.version())
    bench.charge(session["id"])
    synced = bench.end(session["id"], connected=False)
    assert synced["overstay"] is None
    body = bench.session(session["id"])
    assert body["overstay"]["status"] == "none" and body["settlement_ready"] is True
    assert bench.events(session["id"])[-2:] == ["vehicle_disconnected", "settlement_ready"]
    bench.idle(connected=False)
    assert bench.point()["availability_status"] == "available"


def test_start_without_accepted_terms_records_the_interval_with_no_fee(bench, clock):
    bench.rules()
    session = bench.start()  # old app / start by #F only
    start_cmd = bench.charge(session["id"])
    assert "overstay" not in start_cmd["parameters"]
    bench.end(session["id"])
    for _ in range(10):
        clock.advance(30)
        bench.idle()
    shown = bench.session(session["id"])["overstay"]
    assert shown["status"] == "no_fee" and shown["fee_due"] == "0.00" and shown["fee_applies"] is False
    assert shown["billable_seconds"] == 300
    # Zero fee cannot grow: the payment may settle while the cable is still connected.
    assert bench.session(session["id"])["settlement_ready"] is True
    bench.idle(connected=False)
    assert bench.events(session["id"]).count("settlement_ready") == 1


def test_stale_terms_are_refused_and_accepted_terms_are_frozen(bench, factory, seed, clock):
    bench.rules()
    old = bench.version()
    bench.rules(amount="2.00")
    response = bench.start(overstay_terms_version=old, expect=409)
    assert response["error"]["code"] == "overstay_terms_changed"
    session = bench.start(key="again", overstay_terms_version=bench.version())
    assert session["overstay"]["status"] == "none"
    retry = bench.start(key="again", overstay_terms_version=bench.version())
    assert retry["id"] == session["id"]
    bench.rules(amount="9.00", max_amount="90.00")  # a later owner change does not touch this session
    bench.charge(session["id"])
    bench.end(session["id"])
    clock.advance(30)
    bench.idle()
    terms = bench.session(session["id"])["overstay"]["terms"]
    assert terms["amount"] == "2.00" and terms["max_amount"] == "3.00"


def test_offline_gap_and_replays_are_not_billed(bench, clock):
    bench.rules(start_after_min=0)
    session = bench.start(overstay_terms_version=bench.version())
    bench.charge(session["id"])
    bench.end(session["id"])
    clock.advance(30)
    bench.idle()
    clock.advance(120)  # device silent for two minutes: unknown, never billed
    bench.idle()
    shown = bench.session(session["id"])["overstay"]
    assert shown["billable_seconds"] == 30 and shown["fee_due"] == "0.00"
    assert "overstay_gap" in bench.events(session["id"])
    clock.advance(30)
    replay = sync_payload(bench.sequence, boot_id=bench.boot, physical_state="idle", connected=True)
    assert bench.http.post("/v1/devices/sync", headers=DEVICE, json=replay).status_code == 200
    assert bench.session(session["id"])["overstay"]["billable_seconds"] == 30


def test_reboot_closes_at_the_last_confirmed_connection(bench, clock):
    bench.rules(start_after_min=0)
    session = bench.start(overstay_terms_version=bench.version())
    bench.charge(session["id"])
    bench.end(session["id"])
    for _ in range(4):
        clock.advance(30)
        bench.idle()
    bench.boot, bench.sequence = "boot-b", 0
    clock.advance(30)
    bench.idle(connected=True)
    shown = bench.session(session["id"])["overstay"]
    assert shown["status"] == "closed" and shown["end_reason"] == "device_reboot"
    assert shown["billable_seconds"] == 120 and shown["fee_due"] == "2.00"


def test_silent_device_closes_after_fifteen_minutes(bench, factory, seed, clock):
    bench.rules()
    session = bench.start(overstay_terms_version=bench.version())
    bench.charge(session["id"])
    bench.end(session["id"])
    with factory.begin() as db:
        db.get(Device, seed["device"]).last_seen = now() - timedelta(minutes=16)
    assert bench.http.get("/v1/overstays/current").json() is None
    shown = bench.session(session["id"])["overstay"]
    assert shown["status"] == "closed" and shown["end_reason"] == "observation_lost"


def test_interrupted_charge_never_opens_an_overstay(bench, clock):
    bench.rules()
    session = bench.start(overstay_terms_version=bench.version())
    bench.charge(session["id"])
    bench.end(session["id"], reason="communication_lost")
    body = bench.session(session["id"])
    assert body["status"] == "interrupted" and body["overstay"]["status"] == "none"


def test_owner_sees_who_occupies_and_exports_the_fee(bench, factory, seed, clock):
    with factory.begin() as db:
        profile = db.get(Profile, seed["a"])
        profile.name, profile.vehicle_description, profile.phone = "Ana Souza", "BYD Dolphin", "11999990000"
    bench.rules(start_after_min=0)
    session = bench.start(overstay_terms_version=bench.version())
    bench.charge(session["id"])
    bench.end(session["id"])
    for _ in range(4):
        clock.advance(30)
        bench.idle()
    owner, _ = client_for(factory, seed["owner"])
    item = owner.get("/v1/owner/live").json()["items"][0]
    occupancy = item["occupancy"]
    assert occupancy["driver_label"] == "Ana · BYD Dolphin" and occupancy["fee_due"] == "2.00"
    assert occupancy["status"] == "billing" and "11999990000" not in str(occupancy)
    bench.idle(connected=False)
    rows = owner.get("/v1/owner/sessions").json()["items"]
    assert rows[0]["overstay_fee"] == "2.00" and rows[0]["overstay_minutes"] == 2
    csv = owner.get("/v1/owner/export/sessions.csv").text
    assert "Taxa de permanência (R$)" in csv.splitlines()[0]
    clear_overrides()
    driver, _ = client_for(factory, seed["a"])
    body = driver.get(f"/v1/charging-sessions/{session['id']}/receipt").json()
    assert body["overstay"]["status"] == "available" and body["overstay"]["amount"] == "2.00"
    assert body["overstay"]["phase"] == "closed" and body["overstay"]["end_reason"] == "disconnected"
    assert body["overstay"]["billable_minutes"] == 2 and body["charges"]["overstay"] == "2.00"
    clear_overrides()


def test_payment_contract_reserves_the_cap_and_waits_for_disconnect(http, factory, seed, clock, monkeypatch):
    from app.config import settings

    fake = FakeStripe()
    gateway.use(fake)
    monkeypatch.setattr(settings(), "stripe_webhook_secret", "whsec_test_secret")
    monkeypatch.setattr(settings(), "public_base_url", "https://api.chargegrid.test")
    try:
        bench = Bench(http, factory, seed)
        bench.rules(start_after_min=0)
        with factory() as db:
            terms = overstay_terms(db, db.get(Station, seed["station"]))
        assert terms["reserve_cents"] == 300 and terms["fee_per_minute"] == Decimal("1.0000")
        assert terms["tolerance_minutes"] == 0 and terms["max_billable_minutes"] == 3
        flow = Flow(http, factory, seed)
        payment = flow.pay()
        assert payment["amount"] == "23.00"  # R$ 20 of energy + R$ 3 overstay cap held on the card
        fake.pay(_checkout(fake, payment)["id"], method="card")
        assert flow.get(payment["id"])["status"] == "authorized"
        response = flow.start(payment_id=payment["id"])
        assert response.status_code == 202, response.text
        session_id = response.json()["id"]
        assert response.json()["overstay"]["fee_applies"] is True  # accepted when paying
        bench.sequence = flow.sequence
        bench.boot = "http-boot"
        bench.charge(session_id)
        bench.end(session_id)
        for _ in range(4):
            clock.advance(30)
            bench.idle()
        with factory() as db:
            stored = db.get(Payment, payment["id"])
            assert stored.settlement_status == "none"  # still connected: fee may grow
            assert overstay_charge(db, db.get(ChargingSession, session_id)) == (200, False)
        bench.idle(connected=False)
        with factory() as db:
            stored = db.get(Payment, payment["id"])
            assert stored.settlement_status in ("due", "done") and stored.overstay_cents == 200
            assert overstay_charge(db, db.get(ChargingSession, session_id)) == (200, True)
    finally:
        gateway.use(None)
