"""Simulador real (``tools/device_simulator.py --kiosk``) percorrendo o totem 0.8.0 contra a API, nos dois modos."""

import sys
from pathlib import Path

import pytest
from test_http import clear_overrides, client_for

from app.config import settings
from app.models import Command, Payment, Profile, Station
from app.modules.payments import gateway
from app.modules.payments.fake import FakeStripe

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tools.device_simulator import Device, KioskRunner  # noqa: E402

HEADERS = {"Authorization": "Device test-key"}


@pytest.fixture
def bench(factory, seed, monkeypatch, tmp_path):
    monkeypatch.setattr(settings(), "public_base_url", "https://api.chargegrid.test")
    with factory.begin() as db:
        db.get(Station, seed["station"]).kiosk_mode = True
    client, _ = client_for(factory, seed["a"])
    clock = [0.0]
    device = Device(tmp_path / "state.json", clock=lambda: clock[0])
    screens = []

    def request(method, path, json=None, headers=None):
        return client.request(method, path, json=json, headers={**HEADERS, **(headers or {})})

    def exchange():
        response = client.post("/v1/devices/sync", headers=HEADERS, json=device.payload())
        assert response.status_code == 200, response.text
        device.response(response.json())
        return response.json()

    hooks = []

    def wait(seconds):
        clock[0] += seconds
        for hook in list(hooks):
            hook()

    runner = KioskRunner(device, request, exchange, echo=screens.append, wait=wait, timeout=30, pay_timeout=30)
    yield runner, device, screens, hooks
    clear_overrides()
    gateway.use(None)


def test_simulator_kiosk_presentation_mode_simulated(bench, factory, seed):
    runner, device, screens, _ = bench
    gateway.use(None)  # sem Stripe nenhuma
    with factory.begin() as db:
        db.get(Profile, seed["owner"]).presentation_mode = True
    outcome = runner.run("value", "20.00", charge_seconds=5)
    assert outcome["status"] == "finished" and outcome["method"] == "simulated"
    assert outcome["receipt"]["final"] is True and outcome["receipt"]["return_kind"] == "simulated"
    names = [line.split("]")[0][1:] for line in screens]
    assert names[:6] == ["T0", "T1", "T2", "T3", "T4", "T5"] and "T6" in names and names[-2:] == ["T7", "T8"]
    assert any("Simular pagamento de R$ 20,00 (sem cobrança)" in line for line in screens)
    assert any("Ao vivo (kiosk_totem)" in line for line in screens)
    assert device.state in ("idle", "stopped") and device.kiosk_order["status"] == "finished"
    with factory() as db:
        assert db.query(Command).filter(Command.type == "START").count() == 1
        assert db.query(Payment).one().provider == "simulated"


def test_simulator_kiosk_official_mode_stripe_qr(bench, factory, seed):
    runner, device, screens, hooks = bench
    fake = FakeStripe()
    gateway.use(fake)

    def pay_once():
        with factory() as db:
            payment = db.query(Payment).first()
        if payment is not None and payment.provider_checkout_id and not fake.sessions[payment.provider_checkout_id][
                "payment_intent"]:
            fake.pay(payment.provider_checkout_id)  # o visitante paga pelo celular
            hooks.clear()

    hooks.append(pay_once)
    outcome = runner.run("time", "15", charge_seconds=3)
    assert outcome["status"] == "finished" and outcome["method"] == "stripe"
    assert outcome["receipt"]["return_kind"] == "released" and outcome["receipt"]["final"] is True
    assert any("Pague pelo QR (Stripe · TESTE): https://api.chargegrid.test/pay/o/" in line for line in screens)
    assert "capture" in fake.calls or "cancel" in fake.calls


def test_simulator_kiosk_reports_disabled_totem(bench, factory, seed):
    runner, _, screens, _ = bench
    with factory.begin() as db:
        db.get(Station, seed["station"]).kiosk_mode = False
    assert runner.run()["status"] == "disabled"
    assert screens == ["[T0] Totem desligado neste posto (sem connector.kiosk): telas atuais"]
