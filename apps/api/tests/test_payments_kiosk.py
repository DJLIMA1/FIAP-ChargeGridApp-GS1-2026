"""Pagamento pelo QR do painel físico (quem chega sem o app) — FakeStripe, sem rede."""

import re
from datetime import timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest
from test_http import clear_overrides, client_for, sync_payload
from test_payments import SECRET, _post_event

from app.config import settings
from app.models import ChargingSession, Command, Payment, PowerDecision, Profile, Station, now
from app.modules.payments import gateway
from app.modules.payments.fake import FakeStripe
from app.presence_code import current_code

DEVICE = {"Authorization": "Device test-key"}


@pytest.fixture
def stripe(monkeypatch):
    fake = FakeStripe()
    gateway.use(fake)
    monkeypatch.setattr(settings(), "stripe_webhook_secret", SECRET)
    monkeypatch.setattr(settings(), "public_base_url", "https://api.chargegrid.test")
    yield fake
    gateway.use(None)


@pytest.fixture
def http(factory, seed, stripe):
    with factory.begin() as db:
        db.get(Station, seed["station"]).kiosk_payments = True
    client, selected = client_for(factory, seed["a"])
    yield client
    clear_overrides()


def _digits(factory, seed):
    with factory() as db:
        return current_code(db.get(Station, seed["station"]))[0][2:]


def _sync(http, sequence, **changes):
    response = http.post("/v1/devices/sync", headers=DEVICE, json=sync_payload(sequence, **changes))
    assert response.status_code == 200, response.text
    return response.json()


def _checkout(http, factory, seed, amount=2000):
    response = http.post("/pay/k/CG-01", data={"c": _digits(factory, seed), "amount": str(amount)},
                         follow_redirects=False)
    assert response.status_code == 303, response.text
    with factory() as db:
        payment = db.query(Payment).order_by(Payment.created_at.desc()).first()
    return response.headers["location"], payment


def _status_url(stripe, payment):
    session = stripe.sessions[payment.provider_checkout_id]
    parsed = urlparse(session["params"]["success_url"])
    return parsed.path, parse_qs(parsed.query)["t"][0]


def test_sync_exposes_kiosk_url_only_when_enabled(http, factory, seed, stripe):
    connector = _sync(http, 1)["connector"]
    assert connector["kiosk_url"] == f"https://api.chargegrid.test/pay/k/CG-01?c={_digits(factory, seed)}"
    assert connector["payment"] is None
    with factory.begin() as db:
        db.get(Station, seed["station"]).kiosk_payments = False
    connector = _sync(http, 2)["connector"]
    assert connector["kiosk_url"] is None and "presence_code" in connector
    gateway.use(None)
    with factory.begin() as db:
        db.get(Station, seed["station"]).kiosk_payments = True
    assert _sync(http, 3)["connector"]["kiosk_url"] is None  # sem Stripe configurada, sem QR


def test_kiosk_page_checks_presence_code_and_option(http, factory, seed):
    page = http.get(f"/pay/k/CG-01?c={_digits(factory, seed)}")
    assert page.status_code == 200 and "Pagamento processado com segurança pela Stripe" in page.text
    assert not re.search(r"simulad|demonstra|\bteste\b|modo teste|ambiente de teste|modo apresenta", page.text, re.I)
    assert re.findall(r'name="amount" value="(\d+)"', page.text) == ["1000", "2000", "4000"]
    assert "4242 4242 4242 4242" in page.text
    wrong = http.get("/pay/k/CG-01?c=abc")
    assert wrong.status_code == 422 and "Escaneie o QR de novo" in wrong.text
    assert http.get("/pay/k/CG-XX?c=12345").status_code == 404
    with factory.begin() as db:
        db.get(Station, seed["station"]).kiosk_payments = False
    assert http.get(f"/pay/k/CG-01?c={_digits(factory, seed)}").status_code == 404


def test_kiosk_rejects_other_amounts(http, factory, seed):
    response = http.post("/pay/k/CG-01", data={"c": _digits(factory, seed), "amount": "999"},
                         follow_redirects=False)
    assert response.status_code == 422
    with factory() as db:
        assert db.query(Payment).count() == 0


def test_kiosk_payment_starts_once_and_guest_can_stop(http, factory, seed, stripe):
    location, payment = _checkout(http, factory, seed)
    assert location.startswith("https://checkout.stripe.test/")
    assert (payment.origin, payment.amount_cents, payment.status) == ("kiosk", 2000, "awaiting_payment")
    with factory() as db:
        guest = db.get(Profile, payment.user_id)
        assert guest.name == "Visitante do painel CG-01"
    shown = _sync(http, 1)["connector"]["payment"]
    assert shown == {"status": "awaiting_payment", "status_label": "Aguardando pagamento", "amount": "20.00",
                     "environment": "test"}
    path, token = _status_url(stripe, payment)
    assert http.get(f"{path}?t=wrong").status_code == 404
    waiting = http.get(f"{path}?t={token}")
    assert "Aguardando pagamento" in waiting.text and 'http-equiv="refresh"' in waiting.text
    intent = stripe.pay(payment.provider_checkout_id)
    # O webhook confirma e o servidor emite START uma única vez.
    assert _post_event(http, stripe.event("payment_intent.amount_capturable_updated", intent)).status_code == 200
    http.get(f"{path}?t={token}")
    with factory() as db:
        session = db.query(ChargingSession).one()
        assert session.user_id == payment.user_id and session.max_duration_minutes == 60
        # Visitante do QR do painel: bateria simulada como no app (carro padrão, SoC sorteado).
        assert (session.soc_source, session.battery_kwh) == ("simulated", Decimal("44.90"))
        assert Decimal(15) <= session.start_soc_percent <= Decimal(60)
        assert db.query(Command).filter(Command.type == "START").count() == 1
        assert db.get(Payment, payment.id).status == "in_use"
    synced = _sync(http, 2)
    assert synced["connector"]["kiosk_url"] is None and synced["connector"]["payment"] is None
    start_cmd = next(cmd for cmd in synced["commands"] if cmd["type"] == "START")
    _sync(http, 3, session_id=str(session.id), physical_state="charging", connected=True,
          acks=[{"command_id": start_cmd["id"], "status": "applied", "error": None}])
    _sync(http, 4, session_id=str(session.id), physical_state="charging", connected=True, energy_wh=2500)
    charging = http.get(f"{path}?t={token}")
    assert "Carregando" in charging.text and "2,50 kWh" in charging.text and "Encerrar recarga" in charging.text
    stopped = http.post(f"{path}/stop", data={"t": token}, follow_redirects=False)
    assert stopped.status_code == 303
    stop_cmd = next(cmd for cmd in _sync(http, 5, session_id=str(session.id), physical_state="charging",
                                         connected=True, energy_wh=2500)["commands"] if cmd["type"] == "STOP")
    _sync(http, 6, session_id=str(session.id), physical_state="stopped", energy_wh=2500,
          acks=[{"command_id": stop_cmd["id"], "status": "applied", "error": None}])
    final = http.get(f"{path}?t={token}")
    assert "Cobrado R$ 5,00" in final.text and "(teste)" not in final.text and 'http-equiv="refresh"' not in final.text
    assert stripe.intents[intent["id"]]["amount_received"] == 500


def test_kiosk_waits_while_point_is_busy_then_releases(http, factory, seed, stripe):
    _, payment = _checkout(http, factory, seed)
    with factory.begin() as db:
        db.get(Station, seed["station"]).prepay_required = False
    started = http.post("/v1/charging-sessions", headers={"Idempotency-Key": "busy"},
                        json={"public_code": "CG-01", "presence_code": "#F" + _digits(factory, seed)})
    assert started.status_code == 202  # alguém iniciou pelo app enquanto o visitante pagava
    stripe.pay(payment.provider_checkout_id)
    path, token = _status_url(stripe, payment)
    http.get(f"{path}?t={token}")
    with factory() as db:
        stored = db.get(Payment, payment.id)
        assert stored.status == "authorized" and stored.last_error.startswith("kiosk_start:")
        assert db.query(ChargingSession).count() == 1
    with factory.begin() as db:
        db.get(Payment, payment.id).start_deadline = now() - timedelta(seconds=1)
    page = http.get(f"{path}?t={token}")
    assert "Expirado · valor devolvido" in page.text
    assert stripe.intents[stripe.sessions[payment.provider_checkout_id]["payment_intent"]]["status"] == "canceled"


def test_kiosk_start_from_webhook_gets_live_power(http, factory, seed, stripe):
    """Integração pagamento × potência ao vivo: o START emitido pelo webhook passa pela decisão do posto."""
    with factory.begin() as db:
        station = db.get(Station, seed["station"])
        station.rebalance_enabled, station.site_limit_kw = True, Decimal(30)
    _, payment = _checkout(http, factory, seed)
    intent = stripe.pay(payment.provider_checkout_id)
    assert _post_event(http, stripe.event("payment_intent.amount_capturable_updated", intent)).status_code == 200
    with factory() as db:
        session = db.query(ChargingSession).one()
        start_cmd = db.query(Command).filter(Command.type == "START").one()
        decision = db.query(PowerDecision).one()
        assert start_cmd.parameters["power_decision_id"] == decision.id
        assert session.power_state == "raising" and session.power_decision_id == decision.id
        assert db.get(Payment, payment.id).session_id == session.id


def test_kiosk_page_discloses_the_overstay_reserve_in_the_preauthorization(http, factory, seed):
    page = http.get(f"/pay/k/CG-01?c={_digits(factory, seed)}")
    assert "R$ 10,00</button>" in page.text and "permanência =" not in page.text
    with factory.begin() as db:
        db.get(Station, seed["station"]).pricing = {"rotation": {
            "enabled": True, "start_after_min": 10, "interval_min": 1, "amount": "1.00", "max_amount": "30.00"}}
    page = http.get(f"/pay/k/CG-01?c={_digits(factory, seed)}")
    assert "R$ 10,00 + até R$ 30,00 de permanência = R$ 40,00" in page.text
    assert "10 min de tolerância" in page.text and "reserva de até R$ 30,00" in page.text
    assert re.findall(r'name="amount" value="(\d+)"', page.text) == ["1000", "2000", "4000"]
