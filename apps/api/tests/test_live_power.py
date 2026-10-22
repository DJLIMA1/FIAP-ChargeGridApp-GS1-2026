"""Live power rebalancing: decisions on every event, SET_POWER confirmed by the device,
reduce-before-raise, unconfirmed reductions, legacy firmware and the owner/driver views."""

import sys
import threading
import uuid
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest
from sqlalchemy import select, update
from test_http import clear_overrides, client_for

from app.database import Base  # noqa: F401
from app.models import (
    ChargingSession,
    Command,
    Connector,
    Device,
    PowerDecision,
    Profile,
    SessionEvent,
    Station,
    now,
)
from app.modules.power import service as live
from app.presence_code import current_code
from app.security import digest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tools.device_simulator import Device as Simulator  # noqa: E402
from tools.device_simulator import load_charger  # noqa: E402


class Bench:
    """Station with three 7,2 kW points, one simulator and one driver per point."""

    def __init__(self, factory, tmp_path, *, live_enabled=True, legacy=(), chargers=None):
        self.factory = factory
        chargers = chargers or {}
        with factory.begin() as db:
            owner = Profile(id=uuid.uuid4(), name="Owner", operator_enabled=True)
            db.add(owner)
            self.drivers = {}
            for name in "abc":
                profile = Profile(id=uuid.uuid4(), name=f"Driver {name}")
                db.add(profile)
                self.drivers[name] = profile.id
            db.flush()
            station = Station(owner_id=owner.id, name="Loja", address="Rua", latitude=0, longitude=0,
                              site_limit_kw=D(30), store_min_kw=D(0), store_peak_kw=D(12),  # margem ESTIMADA
                              rebalance_enabled=live_enabled)
            db.add(station)
            db.flush()
            self.points = {}
            for name in "abc":
                point = Connector(station_id=station.id, public_code=f"CG-{name.upper()}", connector_type="Tipo 2",
                                  power_kw=D("7.2"), price_per_kwh=D(2), max_duration_minutes=60)
                db.add(point)
                db.flush()
                db.add(Device(connector_id=point.id, key_hash=digest(f"key-{name}"), last_seen=now(),
                              reconciled=True, physical_state="idle"))
                self.points[name] = point.id
            self.owner, self.station = owner.id, station.id
        self.client, self.selected = client_for(factory, self.owner)
        self.sims = {}
        for name in "abc":
            charger, transport = chargers.get(name, (None, None))
            self.sims[name] = Simulator(tmp_path / f"{name}.json", legacy=name in legacy,
                                        charger=charger, transport=transport)
        self.sessions = {}
        for name in "abc":
            self.sync(name)

    def sync(self, name, times=1):
        body = None
        for _ in range(times):
            response = self.client.post("/v1/devices/sync", headers={"Authorization": f"Device key-{name}"},
                                        json=self.sims[name].payload())
            assert response.status_code == 200, response.text
            body = response.json()
            self.sims[name].response(body)
        return body

    def as_user(self, user_id):
        self.selected["id"] = user_id

    def code(self):
        with self.factory() as db:
            return current_code(db.get(Station, self.station))[0]

    def start(self, name, expect=202, **extra):
        self.as_user(self.drivers[name])
        response = self.client.post("/v1/charging-sessions", headers={"Idempotency-Key": f"start-{name}-{uuid.uuid4()}"},
                                    json={"public_code": f"CG-{name.upper()}", "presence_code": self.code(),
                                          "max_duration_minutes": 30, **extra})
        assert response.status_code == expect, response.text
        if expect == 202:
            self.sessions[name] = uuid.UUID(response.json()["id"])
        return response

    def stop(self, name):
        self.as_user(self.drivers[name])
        response = self.client.post(f"/v1/charging-sessions/{self.sessions[name]}/stop",
                                    headers={"Idempotency-Key": f"stop-{name}-{uuid.uuid4()}"})
        assert response.status_code == 202, response.text

    def store(self, kw):
        """O dono muda o pico ESTIMADO da loja (Limites): a margem reservada passa a ser ``kw``."""
        self.as_user(self.owner)
        response = self.client.put(f"/v1/stations/{self.station}/power-site",
                                   json={"store_min_kw": 0, "store_peak_kw": kw})
        assert response.status_code == 200, response.text
        return response.json()

    def session(self, name):
        with self.factory() as db:
            return db.get(ChargingSession, self.sessions[name])

    def applied(self, name):
        value = self.session(name).applied_power_kw
        return None if value is None else D(value)

    def envelope_total(self):
        with self.factory() as db:
            points = live._state(db, db.get(Station, self.station))
            return sum((point.envelope() for point in points), D(0))

    def commands(self, name, kind=None):
        with self.factory() as db:
            device = db.scalar(select(Device).where(Device.connector_id == self.points[name]))
            query = select(Command).where(Command.device_id == device.id).order_by(Command.version)
            if kind:
                query = query.where(Command.type == kind)
            return db.scalars(query).all()


@pytest.fixture
def bench(factory, tmp_path):
    yield Bench(factory, tmp_path)
    clear_overrides()


def _charge(bench, name, **extra):
    bench.start(name, **extra)
    bench.sync(name, 2)  # START aplicado, depois ACK
    assert bench.session(name).status == "charging"


def test_lone_car_gets_full_power_not_one_third(bench):
    _charge(bench, "a")
    assert bench.applied("a") == D("7.2")
    start = bench.commands("a", "START")[-1]
    assert start.parameters["power_limit_w"] == 7200
    session = bench.session("a")
    assert session.power_reason == ("7,2 kW, o máximo deste carregador (12 kW dos 30 kW contratados ficam reservados "
                                    "para a loja; 1 carro carregando).")


def test_third_car_reduces_others_first_then_raises_after_acks(bench):
    _charge(bench, "a")
    _charge(bench, "b")
    assert (bench.applied("a"), bench.applied("b")) == (D("7.2"), D("7.2"))
    bench.start("c")
    start = bench.commands("c", "START")[-1]
    assert start.parameters["power_limit_w"] == 3600  # só a folga confirmada: 18 − 7,2 − 7,2
    assert bench.envelope_total() <= D(18)
    bench.sync("c", 2)
    assert bench.applied("c") == D("3.6")
    assert bench.session("c").power_state == "waiting"
    # A recebe a redução no próximo sync e confirma no seguinte.
    body = bench.sync("a")
    assert [cmd["type"] for cmd in body["commands"]] == ["SET_POWER"]
    assert body["commands"][0]["parameters"]["power_limit_w"] == 6000
    assert bench.session("a").power_state == "reducing"
    assert bench.envelope_total() <= D(18)
    bench.sync("a")
    assert bench.applied("a") == D("6.0")
    # C sobe só o que A liberou (B ainda não reduziu): 18 − 6 − 7,2 = 4,8.
    assert bench.sync("c")["commands"][0]["parameters"]["power_limit_w"] == 4800
    bench.sync("c")
    assert bench.applied("c") == D("4.8") and bench.envelope_total() <= D(18)
    bench.sync("b", 2)
    assert bench.applied("b") == D("6.0")
    body = bench.sync("c")
    assert body["commands"][0]["parameters"]["power_limit_w"] == 6000
    bench.sync("c")
    assert [bench.applied(name) for name in "abc"] == [D("6.0")] * 3
    assert bench.envelope_total() == D(18)
    assert bench.session("c").power_reason == ("6 kW porque 12 kW dos 30 kW contratados ficam reservados para a loja "
                                               "(estimativa) e há 3 carros carregando.")


def test_store_load_change_reduces_all_on_next_syncs_and_panel_shows_reason(bench):
    for name in "abc":
        _charge(bench, name)
    for name in "abc":
        bench.sync(name, 2)
    bench.sync("c", 2)
    view = bench.store(24)
    assert view["available_kw"] == "6.000" and view["store_reserve_kw"] == "24.000"
    assert view["decisions"][0]["trigger"] == "store_estimate_changed"
    for name in "abc":
        bench.sync(name, 2)
    assert [bench.applied(name) for name in "abc"] == [D("2.0")] * 3
    panel = bench.sync("a")["authorized"]["session"]
    assert panel["applied_power_kw"] == 2.0
    assert panel["power_reason_short"] == "Contrat. 30 - loja 24 kW · 3 carros"
    assert panel["power_state"] == "applied"
    bench.as_user(bench.owner)
    view = bench.client.get(f"/v1/stations/{bench.station}/power").json()
    assert view["envelope_kw"] == "6.000" and view["exceeded_kw"] == "0.000"
    assert any(D(item["exceeded_kw"]) > 0 for item in view["decisions"])  # excesso transitório registrado
    assert {point["public_code"]: point["session"]["applied_kw"] for point in view["points"]} == \
        {"CG-A": "2.000", "CG-B": "2.000", "CG-C": "2.000"}


def test_driver_power_timeline_for_receipt(bench):
    _charge(bench, "a")
    bench.store(26)
    bench.sync("a", 2)
    bench.as_user(bench.drivers["a"])
    body = bench.client.get(f"/v1/charging-sessions/{bench.sessions['a']}/power").json()
    assert [segment["applied_kw"] for segment in body["segments"]] == ["7.200", "4.000"]
    assert body["segments"][1]["reason_text"] == ("4 kW porque 26 kW dos 30 kW contratados ficam reservados para a "
                                                  "loja (estimativa) e só o seu carro está carregando.")
    assert body["current"]["applied_kw"] == "4.000"
    assert body["requests"][0]["kind"] == "power_requested"
    bench.as_user(bench.drivers["b"])
    assert bench.client.get(f"/v1/charging-sessions/{bench.sessions['a']}/power").status_code == 404
    # O motivo também está em texto na sessão (histórico/recibo) e no /owner/live.
    bench.as_user(bench.drivers["a"])
    current = bench.client.get("/v1/charging-sessions/current").json()
    assert current["power_reason"].startswith("4 kW porque") and current["applied_power_kw"] == "4.000"


def test_stop_supersedes_pending_set_power_and_frees_capacity(bench):
    for name in "ab":
        _charge(bench, name)
    bench.store(24)  # 6 kW para 2 carros
    body = bench.sync("a")  # recebe SET_POWER 3000, ainda sem ACK
    assert body["commands"][0]["type"] == "SET_POWER"
    bench.stop("a")
    body = bench.sync("a")
    assert [cmd["type"] for cmd in body["commands"]] == ["STOP"]
    assert bench.commands("a", "SET_POWER")[-1].status == "superseded"
    bench.sync("a", 2)
    assert bench.session("a").status == "completed"
    bench.sync("b", 2)
    assert bench.applied("b") == D("6.0")


def test_pending_stop_blocks_set_power(bench):
    _charge(bench, "a")
    bench.stop("a")
    bench.store(25)
    body = bench.sync("a")
    assert [cmd["type"] for cmd in body["commands"]] == ["STOP"]
    assert bench.commands("a", "SET_POWER") == []


def test_set_power_does_not_mark_point_reconciling(bench):
    _charge(bench, "a")
    bench.store(25)
    bench.sync("a")
    bench.as_user(bench.drivers["b"])
    stations = bench.client.get(f"/v1/stations/{bench.station}").json()
    point = next(item for item in stations["connectors"] if item["public_code"] == "CG-A")
    assert point["availability_status"] == "charging"


def test_ack_with_power_above_request_is_rejected(bench):
    _charge(bench, "a")
    bench.store(25)
    bench.sync("a")
    command = bench.commands("a", "SET_POWER")[-1]
    payload = bench.sims["a"].payload()
    payload["acks"] = [{"command_id": str(command.id), "status": "applied", "error": None, "applied_power_w": 7200}]
    payload["applied_power_w"] = 7200
    response = bench.client.post("/v1/devices/sync", headers={"Authorization": "Device key-a"}, json=payload)
    assert response.status_code == 200
    assert bench.commands("a", "SET_POWER")[0].status == "failed"
    assert bench.commands("a", "SET_POWER")[0].error == "applied_power_mismatch"
    with bench.factory() as db:
        kinds = [event.kind for event in db.scalars(select(SessionEvent).order_by(SessionEvent.id))]
    assert "power_failed" in kinds


def test_lost_increase_ack_is_resolved_by_reported_applied_power(bench):
    _charge(bench, "a")
    bench.store(26)
    bench.sync("a", 2)
    assert bench.applied("a") == D("4.0")
    bench.store(12)
    bench.sync("a")  # recebe e aplica o aumento
    bench.sims["a"].acks = []  # o ACK se perde
    with bench.factory.begin() as db:
        db.execute(update(Command).where(Command.type == "SET_POWER").values(expires_at=now() - timedelta(seconds=1)))
    bench.sync("a")
    assert bench.applied("a") == D("7.2")
    assert len(bench.commands("a", "SET_POWER")) == 2  # nenhum reenvio


def test_unconfirmed_reduction_is_retried_once_then_point_is_stopped(factory, tmp_path):
    charger, transport = load_charger("goodwe-hca-g2", fail_writes=0)
    bench = Bench(factory, tmp_path, chargers={"a": (charger, transport)})
    try:
        _charge(bench, "a")
        assert bench.applied("a") == D("7.0")  # GW7K: máximo de 7 kW
        transport.fail_writes = 100
        bench.store(26)
        bench.sync("a", 2)  # 1ª redução: escrita perdida, ACK failed (readback) → 2ª tentativa
        assert bench.commands("a", "SET_POWER")[0].error == "readback_mismatch"
        assert bench.applied("a") == D("7.0")  # a potência antiga continua valendo
        attempts = [cmd.parameters["attempt"] for cmd in bench.commands("a", "SET_POWER")]
        assert attempts == [1, 2]
        bench.sync("a")
        assert bench.commands("a")[-1].type == "STOP"
        assert bench.commands("a")[-1].parameters == {"reason": "power_limit_unconfirmed"}
        assert bench.session("a").status == "stopping"
    finally:
        clear_overrides()


def test_hca_adapter_point_follows_decision_through_registers(factory, tmp_path):
    charger, transport = load_charger("goodwe-hca-g2")
    bench = Bench(factory, tmp_path, chargers={"a": (charger, transport)})
    try:
        _charge(bench, "a")
        bench.store(26)
        bench.sync("a", 2)
        assert bench.applied("a") == D("4.0") and transport.read(10029) == [40]
        with factory() as db:
            device = db.scalar(select(Device).where(Device.connector_id == bench.points["a"]))
            assert device.charger["model"] == "goodwe_hca_g2" and device.charger["transport"] == "simulated"
        bench.as_user(bench.owner)
        view = bench.client.get(f"/v1/stations/{bench.station}/power").json()
        assert view["points"][0]["charger"]["variant"] == "GW7K-HCA-20"
    finally:
        clear_overrides()


def test_legacy_firmware_never_gets_set_power_or_zero_start(factory, tmp_path):
    bench = Bench(factory, tmp_path, legacy=("a",))
    try:
        _charge(bench, "a")
        start = bench.commands("a", "START")[-1]
        assert "power_limit_w" not in start.parameters and start.parameters["max_power_kw"] == 7.2
        bench.store(26)
        assert bench.sync("a", 3)["commands"] == []
        assert bench.session("a").power_state == "fixed"
        # O carro novo conta com os 7,2 kW fixos do ponto antigo.
        bench.store(12)
        bench.start("b")
        assert bench.commands("b", "START")[-1].parameters["power_limit_w"] == 7200
    finally:
        clear_overrides()


def test_new_car_refused_when_site_is_full(bench):
    _charge(bench, "a")
    bench.store("28.5")
    bench.sync("a", 2)
    response = bench.start("b", expect=409)
    error = response.json()["error"]
    assert error["code"] == "site_power_full"
    assert error["message"].startswith("Sem potência disponível agora: dos 30 kW contratados, 28,5 kW ficam "
                                       "reservados para a loja")
    with bench.factory() as db:
        assert db.scalar(select(ChargingSession).where(ChargingSession.user_id == bench.drivers["b"])) is None


def test_new_car_may_start_paused_while_others_reduce(bench):
    _charge(bench, "a")
    bench.store(22)  # 8 kW: o carro A fica com 7,2
    bench.sync("a", 2)
    bench.start("b", max_power_kw="7.2")
    start = bench.commands("b", "START")[-1]
    assert start.parameters["power_limit_w"] == 0  # 8 − 7,2 = 0,8 < 1,4: começa pausado
    bench.sync("b", 2)
    assert bench.session("b").power_state == "waiting"
    bench.sync("a", 2)  # A reduz para 4
    bench.sync("b", 2)
    assert (bench.applied("a"), bench.applied("b")) == (D("4.0"), D("4.0"))


def test_driver_cap_is_kept_live(bench):
    _charge(bench, "a", max_power_kw="3.5")
    assert bench.applied("a") == D("3.5")
    assert bench.session("a").requested_power_kw == D("3.5")
    bench.store(0)
    bench.sync("a", 2)
    assert bench.applied("a") == D("3.5")
    assert bench.session("a").power_reason == "3,5 kW, o limite escolhido para o seu carro."


def test_disabled_station_splits_the_limits_at_start_and_never_sends_set_power(factory, tmp_path):
    """Rebalanceamento desligado: a margem vale por cima de tudo, dividida no START entre os pontos
    ativos (30 contratados − 12 da loja = 18 kW ÷ 3 = 6 kW); depois nada muda durante a recarga."""
    bench = Bench(factory, tmp_path, live_enabled=False)
    try:
        _charge(bench, "a")
        start = bench.commands("a", "START")[-1]
        assert "power_limit_w" not in start.parameters and start.parameters["max_power_kw"] == 6.0
        bench.store(28)
        assert bench.sync("a", 2)["commands"] == []
        assert bench.commands("a", "SET_POWER") == []
        session = bench.session("a")
        assert session.power_state is None and session.power_limit_kw == D("6.0")
    finally:
        clear_overrides()


def test_owner_routes_validate_and_are_owner_only(bench):
    bench.as_user(bench.owner)
    url = f"/v1/stations/{bench.station}"
    removed = bench.client.put(url + "/building-load", json={"building_load_kw": 1})
    assert removed.status_code == 410 and removed.json()["error"]["code"] == "store_load_removed"
    assert bench.client.put(url + "/power-site", json={"site_limit_kw": 0}).status_code == 422
    assert bench.client.put(url + "/power-site", json={"rebalance_enabled": None}).status_code == 422
    view = bench.client.put(url + "/power-site", json={"site_limit_kw": "45.04", "rebalance_enabled": False}).json()
    assert view["site_limit_kw"] == "45.000" and view["rebalance_enabled"] is False
    bench.as_user(bench.drivers["a"])
    for method, path, body in (("get", "/power", None), ("put", "/building-load", {"building_load_kw": 1}),
                               ("put", "/power-site", {"site_limit_kw": 10})):
        response = getattr(bench.client, method)(url + path, **({"json": body} if body else {}))
        assert response.status_code in (403, 404)


def test_decision_log_dedupes_identical_inputs(bench):
    _charge(bench, "a")
    bench.sync("a", 5)
    with bench.factory() as db:
        count = len(db.scalars(select(PowerDecision)).all())
    bench.sync("a", 5)
    with bench.factory() as db:
        assert len(db.scalars(select(PowerDecision)).all()) == count


def test_concurrent_raises_never_share_the_same_headroom(bench):
    for name in "abc":
        _charge(bench, name)
    for name in "abc":
        bench.sync(name, 2)
    bench.sync("c", 2)
    assert [bench.applied(name) for name in "abc"] == [D("6.0")] * 3
    bench.stop("c")  # STOP pendente: os 6 kW de C continuam reservados
    bench.store(24)
    for name in "ab":
        bench.sync(name, 2)
    assert (bench.applied("a"), bench.applied("b")) == (D("3.0"), D("3.0"))
    bench.store(12)  # A e B querem 7,2; a folga real é 18 − 6 (C) − 3 − 3 = 6
    barrier = threading.Barrier(2)
    errors = []

    def raise_point(name):
        try:
            payload = bench.sims[name].payload()
            barrier.wait()
            response = bench.client.post("/v1/devices/sync", headers={"Authorization": f"Device key-{name}"},
                                         json=payload)
            assert response.status_code == 200, response.text
            bench.sims[name].response(response.json())
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=raise_point, args=(name,)) for name in "ab"]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    assert bench.envelope_total() <= D(18)
    requested = sorted(cmd.parameters["power_limit_w"] for name in "ab" for cmd in bench.commands(name, "SET_POWER")
                       if cmd.parameters["direction"] == "raise")
    assert requested == [4800, 7200]


def test_device_capabilities_follow_each_sync(bench):
    with bench.factory() as db:
        device = db.scalar(select(Device).where(Device.connector_id == bench.points["a"]))
        assert device.capabilities == ["set_power_v1", "multi_charger_v1"]  # tela que comanda vários carregadores
    bench.sims["a"].legacy = True
    bench.sync("a")
    with bench.factory() as db:
        device = db.scalar(select(Device).where(Device.connector_id == bench.points["a"]))
        assert device.capabilities == [] and device.charger is None


def test_sync_rate_limit_allows_one_second_syncs(bench):
    for _ in range(70):
        bench.sync("a")


# ---- Margem ESTIMADA da loja, limites e rebalanceamento ligado por padrão ----------------------------------


def _plain_station(factory, **fields):
    """Posto sem limite nem consumo informados (como um posto novo), com um ponto e um dono."""
    with factory.begin() as db:
        owner = Profile(id=uuid.uuid4(), name="Owner", operator_enabled=True)
        db.add(owner)
        db.flush()
        station = Station(owner_id=owner.id, name="Loja", address="Rua", latitude=0, longitude=0, **fields)
        db.add(station)
        db.flush()
        return owner.id, station.id


def test_new_stations_have_rebalancing_on_and_payment_switches_off(factory):
    owner, _ = _plain_station(factory)
    client, _ = client_for(factory, owner)
    try:
        created = client.post("/v1/stations", json={"name": "Nova", "address": "Rua 2", "latitude": "-23.5",
                                                    "longitude": "-46.6"})
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["rebalance_enabled"] is True
        assert body["prepay_required"] is False and body["kiosk_payments"] is False and body["kiosk_mode"] is False
        assert body["site_limit_kw"] is None  # o dono não informou: vale o padrão (75 kW)
    finally:
        clear_overrides()


def test_power_view_uses_default_limit_and_estimated_store_margin(factory):
    owner, station_id = _plain_station(factory)
    client, _ = client_for(factory, owner)
    url = f"/v1/stations/{station_id}/power-site"
    try:
        view = client.get(f"/v1/stations/{station_id}/power").json()
        assert view["rebalance_enabled"] is True
        assert view["site_limit_kw"] == "75.000" and view["site_limit_default"] is True
        assert view["site_limit_configured_kw"] is None and view["site_limit_default_kw"] == "75.000"
        # Sem medidor: margem ESTIMADA fixa (14–22 kW), o pico reservado o tempo todo; nada simulado.
        assert (view["store_min_kw"], view["store_peak_kw"], view["store_reserve_kw"]) == ("14.000", "22.000", "22.000")
        assert view["store_estimate_default"] is True and view["store_estimate_label"] == "ESTIMATIVA"
        assert view["available_kw"] == "53.000" and view["building_load_kw"] == "22.000"  # alias descontinuado
        for gone in ("building_load_simulated", "building_load_mode", "building_profile", "building_size",
                     "building_profile_label", "building_peak_kw", "building_load_manual_until"):
            assert gone not in view
        assert client.get(f"/v1/stations/{station_id}/power").json()["available_kw"] == "53.000"  # estável
        # Tipo/porte de apps antigos: aceitos e ignorados.
        view = client.put(url, json={"building_profile": "supermercado", "building_size": "grande"}).json()
        assert view["available_kw"] == "53.000"
        # Pico maior: o limite padrão acompanha (160 × 1,3 → 210) e sobram 50 kW.
        view = client.put(url, json={"store_min_kw": "89.6", "store_peak_kw": "160"}).json()
        assert (view["site_limit_kw"], view["available_kw"], view["store_estimate_default"]) == \
            ("210.000", "50.000", False)
        refused = client.put(url, json={"site_limit_kw": "120"})
        assert refused.status_code == 422 and refused.json()["error"]["code"] == "invalid_store_estimate"
        assert "deixa 0 kW para os carregadores" in refused.json()["error"]["message"]
        assert client.get(f"/v1/stations/{station_id}/power").json()["site_limit_kw"] == "210.000"  # nada gravado
        view = client.put(url, json={"site_limit_kw": "200.04"}).json()
        assert (view["site_limit_kw"], view["available_kw"]) == ("200.000", "40.000")
        assert client.put(url, json={"store_min_kw": "170"}).status_code == 422  # mínimo acima do pico
        assert client.put(url, json={"store_peak_kw": "-1"}).status_code == 422
        view = client.put(url, json={"site_limit_kw": None, "store_min_kw": None, "store_peak_kw": None}).json()
        assert (view["site_limit_kw"], view["store_peak_kw"], view["available_kw"]) == ("75.000", "22.000", "53.000")
    finally:
        clear_overrides()


def test_power_site_saves_all_limits_in_one_atomic_put(bench):
    bench.as_user(bench.owner)
    url = f"/v1/stations/{bench.station}/power-site"
    view = bench.client.put(url, json={"site_limit_kw": "30", "store_min_kw": "2", "store_peak_kw": "10",
                                       "max_power_kw": "12", "power_limit_notify": True}).json()
    assert (view["station_cap_kw"], view["available_kw"], view["power_limit_notify"]) == ("12.000", "12.000", True)
    assert (view["connectors_total_kw"], view["charger_floor_kw"], view["chargers_floor_total_kw"]) == \
        ("21.600", "1.400", "4.200")
    # Teto abaixo do piso dos 3 conectores: 422 e nada muda (nem o pico enviado junto).
    refused = bench.client.put(url, json={"store_peak_kw": "5", "max_power_kw": "3"})
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "invalid_power_limit"
    view = bench.client.get(f"/v1/stations/{bench.station}/power").json()
    assert (view["station_cap_kw"], view["store_peak_kw"]) == ("12.000", "10.000")
    view = bench.client.put(url, json={"max_power_kw": None, "power_limit_notify": False}).json()
    assert (view["station_cap_kw"], view["available_kw"], view["power_limit_notify"]) == (None, "20.000", False)
    assert bench.client.put(url, json={"power_limit_notify": None}).status_code == 422
    station = bench.client.get(f"/v1/stations/{bench.station}").json()
    assert station["store_peak_kw"] == "10.000" and station["max_power_kw"] is None


@pytest.mark.parametrize("live_enabled", [True, False])
def test_lab_station_with_defaults_keeps_a_7kw_hca_at_full_power(factory, tmp_path, live_enabled):
    """A central real (sem valores gravados, HCA de 7 kW) não pode pausar: 75 − 22 = 53 kW sobram."""
    charger, transport = load_charger("goodwe-hca-g2")
    bench = Bench(factory, tmp_path, live_enabled=live_enabled, chargers={"a": (charger, transport)})
    try:
        with factory.begin() as db:  # posto "de fábrica"
            station = db.get(Station, bench.station)
            station.site_limit_kw = station.store_min_kw = station.store_peak_kw = None
        _charge(bench, "a")
        bench.sync("a", 3)
        session = bench.session("a")
        assert session.status == "charging" and session.power_limit_kw == D("7.0")
        if live_enabled:
            assert bench.applied("a") == D("7.0") and session.power_state == "applied"
        bench.as_user(bench.owner)
        view = bench.client.get(f"/v1/stations/{bench.station}/power").json()
        assert view["available_kw"] == "53.000" and view["store_estimate_default"] is True
    finally:
        clear_overrides()


def test_disabled_rebalancing_splits_contract_minus_store_peak_between_two_60kw_points(factory):
    """2 × 60 kW DC, padrões (75 − 22 = 53 kW), rebalanceamento desligado: 26,5 kW cada no START.
    Ligado, a divisão fica com a decisão ao vivo (um carro sozinho recebe até 53 kW)."""
    from app.http_helpers import allocation, station_budget

    owner, station_id = _plain_station(factory, rebalance_enabled=False)
    with factory.begin() as db:
        for code in ("DC-1", "DC-2"):
            db.add(Connector(station_id=station_id, public_code=code, connector_type="CCS2", power_kw=D(60),
                             price_per_kwh=D(2), max_duration_minutes=60))
    with factory() as db:
        station = db.get(Station, station_id)
        points = db.scalars(select(Connector).where(Connector.station_id == station_id)).all()
        assert station_budget(station) == D(53)
        shares = allocation(station, points, set())["connectors"]
        assert sorted(item["effective_kw"] for item in shares.values()) == [D("26.5"), D("26.5")]
        station.rebalance_enabled = True
        assert station_budget(station) is None
        assert all(item["effective_kw"] == D(60) for item in allocation(station, points, set())["connectors"].values())
    client, _ = client_for(factory, owner)
    try:
        body = client.get(f"/v1/stations/{station_id}").json()
        assert [point["effective_power_kw"] for point in body["connectors"]] == ["26.500", "26.500"]
    finally:
        clear_overrides()


def test_store_estimate_migration_backfills_from_the_old_type_and_size(factory):
    import importlib.util

    from sqlalchemy import text

    root = Path(__file__).resolve().parents[1]
    path = root / "migrations/versions/d8b3f6a2c5e7_store_estimate_limits.py"
    spec = importlib.util.spec_from_file_location("store_estimate_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "c4f1a8e6d2b9"
    rows = {
        "super": dict(building_profile="supermercado", building_size="grande"),
        "conv": dict(building_profile="conveniencia"),
        "mall": dict(building_profile="shopping", site_limit_kw=D(75)),
        "small": dict(site_limit_kw=D(20)),
        "plain": dict(),
        "big": dict(site_limit_kw=D(100)),
        "odd": dict(building_profile="fabrica", building_size="pequeno"),
    }
    ids = {name: _plain_station(factory, **fields)[1] for name, fields in rows.items()}
    with factory.begin() as db:
        db.execute(text(migration.backfill_sql()))
    with factory() as db:
        got = {name: (db.get(Station, ident).store_min_kw, db.get(Station, ident).store_peak_kw)
               for name, ident in ids.items()}
    assert got["super"] == (D("89.6"), D("160"))       # 100 × 1,6; 0,56 do pico
    assert got["conv"] == (D("13.6"), D("22"))
    assert got["mall"] == (D("63.7"), D("63.7"))       # nunca acima de 85 % do contratado
    assert got["small"] == (D("14"), D("17"))          # padrão, limitado a 85 % de 20
    assert got["plain"] == (None, None) and got["big"] == (None, None)  # seguem o padrão 14–22
    assert got["odd"] == (D("8.2"), D("13.2"))         # tipo desconhecido = conveniência, porte pequeno
    offline = (root / "sql/migracao_d8b3f6a2c5e7.sql").read_text()
    assert "ADD COLUMN store_min_kw" in offline and "ADD COLUMN store_peak_kw" in offline
    assert "Running upgrade c4f1a8e6d2b9 -> d8b3f6a2c5e7" in offline


def test_migration_turns_rebalancing_on_for_new_and_existing_stations():
    column = Station.__table__.c.rebalance_enabled
    assert column.default.arg is True and "true" in str(column.server_default.arg)
    root = Path(__file__).resolve().parents[1]
    migration = (root / "migrations/versions/a3e8c5d1f7b9_rebalance_on_simulated_load.py").read_text()
    assert 'down_revision = "f4b9d2c7e1a3"' in migration
    offline = (root / "sql/migracao_a3e8c5d1f7b9.sql").read_text()
    assert "ALTER COLUMN rebalance_enabled SET DEFAULT true" in offline
    assert "UPDATE stations SET rebalance_enabled = true" in offline
    assert "SET prepay_required = false, kiosk_payments = false" in offline
    assert "ADD COLUMN building_profile" in offline and "ADD COLUMN building_size" in offline
