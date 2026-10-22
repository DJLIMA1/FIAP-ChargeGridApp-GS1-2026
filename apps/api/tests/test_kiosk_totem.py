"""Totem de autoatendimento (pedido sem celular): endpoints do dispositivo, trava do ponto, sync e recibo.

Modo apresentação do dono → pagamento simulado (sem Stripe); conta oficial → Stripe (FakeStripe, sem rede).
"""

import uuid
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlparse

import pytest
from fastapi import Depends
from test_http import clear_overrides, client_for, sync_payload
from test_payments import SECRET, _post_event

from app.config import settings
from app.database import db_session
from app.main import app
from app.models import (
    ChargingSession,
    Command,
    Connector,
    Device,
    KioskOrder,
    Payment,
    Profile,
    Reservation,
    Station,
    now,
)
from app.modules.payments import gateway
from app.modules.payments.fake import FakeStripe
from app.presence_code import current_code
from app.security import current_user, digest

DEVICE = {"Authorization": "Device test-key"}
BASE = "https://api.chargegrid.test"
ROTATION = {"enabled": True, "start_after_min": 10, "interval_min": 1, "amount": "1.00", "max_amount": "30.00"}
ALL_WEEK = [0, 1, 2, 3, 4, 5, 6]


@pytest.fixture
def base_url(monkeypatch):
    monkeypatch.setattr(settings(), "public_base_url", BASE)
    monkeypatch.setattr(settings(), "stripe_webhook_secret", SECRET)
    gateway.use(None)
    yield
    gateway.use(None)


@pytest.fixture
def stripe(base_url):
    fake = FakeStripe()
    gateway.use(fake)
    yield fake
    gateway.use(None)


@pytest.fixture
def http(factory, seed, base_url):
    with factory.begin() as db:
        db.get(Station, seed["station"]).kiosk_mode = True
    client, selected = client_for(factory, seed["a"])
    client.selected = selected
    yield client
    clear_overrides()


@pytest.fixture
def presentation(factory, seed):
    with factory.begin() as db:
        db.get(Profile, seed["owner"]).presentation_mode = True


class Bench:
    """Painel simulado pelos endpoints do dispositivo (o mesmo caminho do firmware 0.8.0)."""

    def __init__(self, http, headers=DEVICE):
        self.http, self.headers, self.sequence, self.keys = http, headers, 0, 0

    def key(self):
        self.keys += 1
        return {"Idempotency-Key": f"k-{self.keys}-{uuid.uuid4().hex[:6]}"}

    def sync(self, **changes):
        self.sequence += 1
        response = self.http.post("/v1/devices/sync", headers=self.headers, json=sync_payload(self.sequence, **changes))
        assert response.status_code == 200, response.text
        return response.json()

    def offer(self):
        return self.http.get("/v1/devices/kiosk/offer", headers=self.headers)

    def quote(self, **body):
        return self.http.post("/v1/devices/kiosk/quote", headers=self.headers, json=body or {"mode": "value",
                                                                                          "amount": "20.00"})

    def order(self, quote=None, key=None, **body):
        quote = quote or self.quote(**body).json()
        payload = {"quote_hash": quote["quote_hash"], "mode": quote["mode"],
                   "overstay_terms_version": quote["overstay"]["version"]}
        for name in ("amount", "minutes", "energy_kwh"):
            if quote.get(name) is not None:
                payload[name] = quote[name]
        return self.http.post("/v1/devices/kiosk/orders", headers={**self.headers, **(key or self.key())},
                              json=payload)

    def pay(self, order_id, key=None, **body):
        return self.http.post(f"/v1/devices/kiosk/orders/{order_id}/pay", headers={**self.headers, **(key or self.key())},
                              json=body)

    def get(self, order_id):
        return self.http.get(f"/v1/devices/kiosk/orders/{order_id}", headers=self.headers)

    def cancel(self, order_id):
        return self.http.post(f"/v1/devices/kiosk/orders/{order_id}/cancel", headers=self.headers)

    def apply_start(self):
        synced = self.sync()
        start = next(cmd for cmd in synced["commands"] if cmd["type"] == "START")
        session_id = start["session_id"]
        self.sync(session_id=session_id, physical_state="charging", connected=True,
                  acks=[{"command_id": start["id"], "status": "applied", "error": None}])
        return session_id, synced

    def charge_and_stop_locally(self, session_id, energy_wh=2500):
        self.sync(session_id=session_id, physical_state="charging", connected=True, energy_wh=energy_wh)
        # Encerrar local (requestLocalSafeStop): sem endpoint, o painel relata a parada no sync.
        return self.sync(session_id=session_id, physical_state="stopped", energy_wh=energy_wh,
                         end_reason="requested_stop")


def _digits(factory, seed):
    with factory() as db:
        return current_code(db.get(Station, seed["station"]))[0]


def _start_from_app(http, factory, seed, key="app-start"):
    return http.post("/v1/charging-sessions", headers={"Idempotency-Key": key},
                     json={"public_code": "CG-01", "presence_code": _digits(factory, seed)})


def _reserve_from_app(http, seed, key="app-reserve"):
    return http.post("/v1/reservations", headers={"Idempotency-Key": key}, json={"connector_id": str(seed["point"])})


def _second_point(factory, seed):
    with factory.begin() as db:
        point = Connector(station_id=seed["station"], public_code="CG-02", connector_type="bench", power_kw=1,
                          price_per_kwh=2, max_duration_minutes=60)
        db.add(point)
        db.flush()
        db.add(Device(connector_id=point.id, key_hash=digest("other-key"), last_seen=now(), reconciled=True,
                      physical_state="idle"))
        return point.id


# ---------------------------------------------------------------------------- autenticação e liga/desliga


def test_device_key_required_user_bearer_is_401(http):
    assert http.get("/v1/devices/kiosk/offer").status_code == 401
    bearer = http.get("/v1/devices/kiosk/offer", headers={"Authorization": "Bearer user-token"})
    assert bearer.status_code == 401 and bearer.json()["error"]["code"] == "unauthorized"
    assert http.post("/v1/devices/kiosk/quote", headers={"Authorization": "Device wrong"},
                     json={"mode": "value", "amount": "20.00"}).status_code == 401


def test_flag_off_hides_sync_blocks_and_endpoints(factory, seed, base_url, presentation):
    client, _ = client_for(factory, seed["a"])
    try:
        bench = Bench(client)
        synced = bench.sync()
        assert "kiosk" not in synced["connector"] and "kiosk_order" not in synced
        assert synced["sync_interval_seconds"] == 5
        offer = bench.offer()
        assert offer.status_code == 404 and offer.json()["error"]["code"] == "kiosk_disabled"
        assert bench.quote().status_code == 404
        with factory.begin() as db:
            db.get(Station, seed["station"]).kiosk_mode = True
        synced = bench.sync()
        assert synced["connector"]["kiosk"] == {"enabled": True, "method": "simulated", "label": "SIMULADO",
                                                "reason": None}
        assert synced["kiosk_order"] is None
    finally:
        clear_overrides()


def test_owner_toggles_station_flag_and_account_presentation_mode(factory, seed, base_url):
    owner, _ = client_for(factory, seed["owner"])
    try:
        station = owner.get(f"/v1/stations/{seed['station']}").json()
        assert station["kiosk_mode"] is False
        assert station["connectors"][0]["kiosk_in_use"] is False
        saved = owner.patch(f"/v1/stations/{seed['station']}", json={"kiosk_mode": True})
        assert saved.status_code == 200 and saved.json()["kiosk_mode"] is True
        assert owner.patch(f"/v1/stations/{seed['station']}", json={"kiosk_mode": None}).status_code == 422
        # Como em produção, o perfil vem da mesma sessão do pedido (o PATCH grava).
        app.dependency_overrides[current_user] = lambda db=Depends(db_session): db.get(Profile, seed["owner"])
        me = owner.get("/v1/me").json()
        assert me["presentation_mode"] is False
        assert owner.patch("/v1/me", json={"presentation_mode": True}).json()["presentation_mode"] is True
        assert owner.get("/v1/me").json()["presentation_mode"] is True
        assert owner.patch("/v1/me", json={"presentation_mode": None}).status_code == 422
        with factory() as db:
            assert db.get(Profile, seed["owner"]).presentation_mode is True
    finally:
        clear_overrides()


def test_official_owner_without_stripe_keeps_totem_unavailable(http):
    bench = Bench(http)
    assert bench.sync()["connector"]["kiosk"] == {"enabled": False, "method": None, "label": None,
                                                  "reason": "payments_unavailable"}
    offer = bench.offer().json()
    assert offer["enabled"] is False and offer["reason"] == "payments_unavailable"
    assert "Stripe" in offer["reason_label"]
    quote = bench.quote()
    assert quote.status_code == 503 and quote.json()["error"]["code"] == "payments_unavailable"


# ---------------------------------------------------------------------------- oferta e orçamento


def test_offer_lists_shortcuts_limits_and_current_tariff(http, presentation, factory, seed):
    with factory.begin() as db:
        station = db.get(Station, seed["station"])
        station.pricing = {"rotation": ROTATION}
        db.get(Connector, seed["point"]).max_duration_minutes = 45
    offer = Bench(http).offer().json()
    assert offer["enabled"] is True and offer["available"] is True and offer["reason"] is None
    assert (offer["method"], offer["label"], offer["public_code"]) == ("simulated", "SIMULADO", "CG-01")
    assert offer["limits"] == {"max_total": "200.00", "overstay_reserve": "30.00"}
    assert offer["modes"]["value"] == {"shortcuts": ["10.00", "20.00", "40.00", "60.00"], "min": "5.00",
                                       "max": "170.00"}
    assert offer["modes"]["time"] == {"shortcuts": [15, 30], "min": 5, "max": 45}  # 60 min > máximo do ponto
    assert offer["modes"]["energy"]["shortcuts"] == ["5.0", "10.0", "20.0"]
    assert offer["modes"]["energy"]["max"] == "85.0"  # (200 − 30) / R$ 2,00
    assert offer["price"]["price_per_kwh"] == "2.0000" and offer["price"]["reason_label"]
    assert offer["overstay"]["enabled"] is True and offer["overstay"]["summary"]
    assert (offer["hold_minutes"], offer["qr_hold_minutes"]) == (5, 10)


def test_totem_quote_equals_app_quote(http, stripe, factory, seed):
    """Mesmo orçamento do app: tarifa do horário, motivo, teto, reserva da permanência e termos."""
    with factory.begin() as db:
        db.get(Station, seed["station"]).pricing = {"rotation": ROTATION, "schedule": {"enabled": True, "intervals": [
            {"start": "00:00", "end": "12:00", "days": ALL_WEEK, "prices": {str(seed["point"]): "1.5000"}},
            {"start": "12:00", "end": "00:00", "days": ALL_WEEK, "prices": {str(seed["point"]): "1.5000"}}]}}
    bench = Bench(http)
    for mode, field, value in (("value", "amount", "20.00"), ("time", "minutes", 30), ("energy", "energy_kwh", "5.0")):
        totem = bench.quote(mode=mode, **{field: value}).json()
        app_body = {"connector_id": str(seed["point"]), "mode": mode,
                    {"amount": "max_cost"}.get(field, field): value}
        app = http.post("/v1/payments", headers={"Idempotency-Key": f"app-{mode}"}, json=app_body).json()
        assert totem["total"] == app["amount"] and totem["energy_cap"] == app["energy_cap"]
        assert totem["overstay_reserve"] == app["overstay_reserve"] == "30.00"
        assert totem["price_per_kwh"] == app["price_per_kwh"] == "1.5000"
        assert totem["base_price_per_kwh"] == app["base_price_per_kwh"]
        assert Decimal(totem["demand_multiplier"]) == Decimal(app["demand_multiplier"])
        assert totem["max_duration_minutes"] == app["max_duration_minutes"]
        assert totem["estimated_energy_kwh"] == app["quote"]["energy_kwh"]
        assert totem["demand"]["reason_label"] == app["quote"]["price_terms"]["demand"]["reason_label"]
        assert totem["overstay"]["version"] == app["quote"]["overstay"]["version"]
        http.post(f"/v1/payments/{app['id']}/cancel")
    assert totem["method"] == "stripe" and totem["label"] == "TESTE"


def test_quote_validation_minimums_and_ceiling(http, presentation, factory, seed):
    bench = Bench(http)
    missing = bench.quote(mode="value")
    assert missing.status_code == 422 and missing.json()["error"]["code"] == "invalid_quote"
    assert bench.quote(mode="value", amount="4.99").json()["error"]["code"] == "amount_below_minimum"
    assert bench.quote(mode="time", minutes=4).json()["error"]["code"] == "amount_below_minimum"
    assert bench.quote(mode="energy", energy_kwh="0.5").json()["error"]["code"] == "amount_below_minimum"
    assert bench.quote(mode="time", minutes=61).json()["error"]["code"] == "amount_above_limit"
    assert bench.quote(mode="value", amount="200.01").json()["error"]["code"] == "amount_above_limit"
    assert bench.quote(mode="energy", energy_kwh="10.25").status_code == 422  # 1 casa decimal
    assert bench.quote(mode="value", amount="200.00").status_code == 200
    with factory.begin() as db:
        db.get(Station, seed["station"]).pricing = {"rotation": ROTATION}
    assert bench.quote(mode="value", amount="180.00").json()["error"]["code"] == "amount_above_limit"


# ---------------------------------------------------------------------------- modo apresentação → simulado


def test_presentation_owner_simulated_flow_without_any_stripe(http, presentation, factory, seed):
    """Sem STRIPE_SECRET_KEY: oferta → orçamento → pedido → pagar → START único → recarga → Encerrar → recibo."""
    bench = Bench(http)
    bench.sync()
    quote = bench.quote().json()
    assert (quote["method"], quote["label"], quote["total"]) == ("simulated", "SIMULADO", "20.00")
    created = bench.order(quote)
    assert created.status_code == 201, created.text
    order = created.json()
    assert order["status"] == "held" and order["payment"] is None and 290 <= order["expires_in_seconds"] <= 300
    assert order["receipt_url"].startswith(f"{BASE}/pay/r/{order['id']}?t=") and len(order["receipt_url"]) <= 160
    key = bench.key()
    paid = bench.pay(order["id"], key=key)
    assert paid.status_code == 200, paid.text
    body = paid.json()
    assert body["status"] == "charging" and body["session_id"]
    assert body["payment"]["method"] == "simulated" and body["payment"]["label"] == "Pago (simulado) · em uso"
    assert body["payment"]["qr_url"] is None
    # Repetir (mesma chave ou outra) não cria outro pagamento nem outro START.
    assert bench.pay(order["id"], key=key).json()["session_id"] == body["session_id"]
    assert bench.pay(order["id"]).status_code == 409
    with factory() as db:
        assert db.query(Command).filter(Command.type == "START").count() == 1
        payment = db.query(Payment).one()
        assert (payment.provider, payment.origin, payment.status, payment.amount_cents) == (
            "simulated", "kiosk", "in_use", 2000)
    session_id, synced = bench.apply_start()
    assert synced["authorized"]["session"]["origin"] == "kiosk_totem"
    assert synced["kiosk_order"]["status"] == "charging" and synced["sync_interval_seconds"] == 1
    stopped = bench.charge_and_stop_locally(session_id)
    receipt = stopped["kiosk_order"]["receipt"]
    assert stopped["kiosk_order"]["status"] == "finished"
    assert receipt["final"] is True and receipt["energy_kwh"] == "2.500"
    assert (receipt["total"], receipt["returned"], receipt["return_kind"]) == ("5.00", "15.00", "simulated")
    assert receipt["end_reason"] == "requested_stop" and receipt["url"] == order["receipt_url"]
    assert stopped["kiosk_order"]["payment"]["label"] == "Cobrado R$ 5,00 (simulado) · Devolvido R$ 15,00"
    with factory() as db:
        payment = db.query(Payment).one()
        assert (payment.settlement_status, payment.status, payment.charge_cents, payment.captured_cents,
                payment.refunded_cents) == ("done", "completed", 500, 500, 0)
        assert db.get(ChargingSession, uuid.UUID(session_id)).user_id == payment.user_id
    page = http.get(urlparse(order["receipt_url"]).path + "?" + urlparse(order["receipt_url"]).query)
    assert page.status_code == 200 and "SIMULADO" in page.text and "Pagamento simulado" in page.text
    assert "Recibo" in page.text and "2.500 kWh" in page.text and 'http-equiv="refresh"' not in page.text
    token = order["receipt_url"].split("t=")[1]
    pdf = http.get(f"/pay/r/{order['id']}.pdf?t={token}")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert http.get(f"/pay/r/{order['id']}?t=wrong").status_code == 404
    assert http.get(f"/pay/r/{order['id']}.pdf?t=wrong").status_code == 404
    # Some do sync 10 min depois de fechar.
    with factory.begin() as db:
        db.get(KioskOrder, uuid.UUID(order["id"])).closed_at = now() - timedelta(minutes=11)
    assert bench.sync()["kiosk_order"] is None


def test_presentation_mode_never_calls_stripe_even_when_configured(http, presentation, stripe):
    bench = Bench(http)
    bench.sync()
    order = bench.order().json()
    paid = bench.pay(order["id"]).json()
    session_id, _ = bench.apply_start()
    bench.charge_and_stop_locally(session_id, energy_wh=1000)
    assert bench.get(order["id"]).json()["receipt"]["return_kind"] == "simulated"
    canceled = bench.order(key=None)
    assert canceled.status_code == 201
    bench.cancel(canceled.json()["id"])
    assert paid["payment"]["method"] == "simulated"
    assert stripe.calls == []  # acerto local: nenhuma chamada à Stripe


def test_simulated_start_waits_for_point_and_sync_resumes_it(http, presentation, factory, seed):
    """Ponto momentaneamente sem confirmação: o pedido fica pago e o sync emite o START depois."""
    bench = Bench(http)
    bench.sync()
    order = bench.order().json()
    with factory.begin() as db:
        db.get(Device, seed["device"]).reconciled = False
    paid = bench.pay(order["id"]).json()
    assert paid["status"] == "paid" and paid["session_id"] is None
    assert paid["payment"]["label"] == "Pago (simulado)"
    synced = bench.sync()  # reconcilia; o START sai depois de gravar o sync
    assert synced["kiosk_order"]["status"] == "charging"
    session_id, _ = bench.apply_start()
    assert session_id == bench.get(order["id"]).json()["session_id"]


def test_simulated_order_fails_and_returns_when_start_deadline_passes(http, presentation, factory, seed):
    bench = Bench(http)
    bench.sync()
    order = bench.order().json()
    with factory.begin() as db:
        db.get(Device, seed["device"]).last_seen = now() - timedelta(minutes=5)  # sem rede
    assert bench.pay(order["id"]).json()["status"] == "paid"
    with factory.begin() as db:
        db.get(KioskOrder, uuid.UUID(order["id"])).expires_at = now() - timedelta(seconds=1)
        db.query(Payment).one().start_deadline = now() - timedelta(seconds=1)
    failed = bench.get(order["id"]).json()
    assert failed["status"] == "failed" and failed["error"]["code"] == "kiosk_start"
    with factory() as db:
        payment = db.query(Payment).one()
        assert (payment.status, payment.settlement_status, payment.charge_cents) == ("expired", "done", 0)
        assert db.query(ChargingSession).count() == 0


# ---------------------------------------------------------------------------- conta oficial → Stripe


def _qr_checkout(http, qr_url):
    parsed = urlparse(qr_url)
    return http.get(f"{parsed.path}?{parsed.query}", follow_redirects=False)


def test_official_owner_stripe_qr_confirmation_start_partial_capture(http, stripe, factory, seed):
    bench = Bench(http)
    bench.sync()
    assert bench.offer().json()["method"] == "stripe"
    order = bench.order().json()
    assert order["method"] == "stripe" and order["label"] == "TESTE"
    paid = bench.pay(order["id"]).json()
    assert paid["status"] == "awaiting_payment" and 590 <= paid["expires_in_seconds"] <= 600
    qr = paid["payment"]["qr_url"]
    assert qr.startswith(f"{BASE}/pay/o/{order['id']}?t=") and len(qr) <= 160
    synced = bench.sync()
    assert synced["kiosk_order"]["payment"]["qr_url"] == qr and synced["sync_interval_seconds"] == 1
    assert synced["connector"]["payment"] is None  # o QR /pay/k não mostra pagamento do totem
    redirect = _qr_checkout(http, qr)
    assert redirect.status_code == 303 and redirect.headers["location"].startswith("https://checkout.stripe.test/")
    with factory() as db:
        payment = db.query(Payment).one()
        assert (payment.provider, payment.status, payment.amount_cents) == ("stripe", "awaiting_payment", 2000)
        params = stripe.sessions[payment.provider_checkout_id]["params"]
        assert params["success_url"] == order["receipt_url"]
        assert params["payment_method_options"]["card"]["capture_method"] == "manual"
    intent = stripe.pay(payment.provider_checkout_id)
    assert _post_event(http, stripe.event("payment_intent.amount_capturable_updated", intent)).status_code == 200
    with factory() as db:
        assert db.query(Command).filter(Command.type == "START").count() == 1
    session_id, synced = bench.apply_start()
    assert synced["kiosk_order"]["status"] == "charging"
    assert synced["kiosk_order"]["payment"]["label"] == "Pago (teste) · em uso"
    assert _qr_checkout(http, qr).headers["location"].startswith("/pay/r/")
    stopped = bench.charge_and_stop_locally(session_id)
    receipt = stopped["kiosk_order"]["receipt"]
    assert (receipt["total"], receipt["returned"], receipt["return_kind"], receipt["final"]) == (
        "5.00", "15.00", "released", True)
    assert stripe.intents[intent["id"]]["amount_received"] == 500  # captura parcial
    page = http.get(f"/pay/r/{order['id']}?t={order['receipt_url'].split('t=')[1]}")
    assert "AMBIENTE DE TESTE" in page.text and "Pagamento simulado" not in page.text


def test_stripe_pix_returns_the_difference(http, stripe, factory, seed):
    bench = Bench(http)
    bench.sync()
    order = bench.order().json()
    bench.pay(order["id"])
    with factory() as db:
        checkout = db.query(Payment).one().provider_checkout_id
    stripe.pay(checkout, method="pix")
    assert bench.get(order["id"]).json()["status"] == "charging"  # verificação no servidor (sem webhook)
    session_id, _ = bench.apply_start()
    bench.charge_and_stop_locally(session_id, energy_wh=1000)
    receipt = bench.get(order["id"]).json()["receipt"]
    assert (receipt["total"], receipt["returned"], receipt["return_kind"]) == ("2.00", "18.00", "refunded")
    assert "refund" in stripe.calls


def test_sync_confirms_stripe_without_webhook(http, stripe, factory, seed):
    bench = Bench(http)
    bench.sync()
    order = bench.order().json()
    bench.pay(order["id"])
    with factory() as db:
        checkout = db.query(Payment).one().provider_checkout_id
    stripe.pay(checkout)
    with factory.begin() as db:
        db.query(Payment).one().last_provider_check_at = None
    assert bench.sync()["kiosk_order"]["status"] == "charging"  # verificação depois de gravar o sync
    assert any(cmd["type"] == "START" for cmd in bench.sync()["commands"])


def test_device_cannot_force_simulated_with_official_owner(http, stripe, factory, seed):
    bench = Bench(http)
    order = bench.order().json()
    forced = bench.pay(order["id"], method="simulated")
    assert forced.status_code == 409 and forced.json()["error"]["code"] == "method_mismatch"
    reserved = bench.pay(order["id"], method="voucher")
    assert reserved.status_code == 409 and reserved.json()["error"]["code"] == "method_unavailable"
    with factory() as db:
        assert db.query(Payment).count() == 0 and db.query(Command).filter(Command.type == "START").count() == 0
    assert bench.pay(order["id"], method="stripe").json()["status"] == "awaiting_payment"


def test_owner_switching_mode_after_quote_changes_the_order(http, stripe, factory, seed):
    bench = Bench(http)
    quote = bench.quote().json()
    assert quote["method"] == "stripe"
    with factory.begin() as db:
        db.get(Profile, seed["owner"]).presentation_mode = True
    changed = bench.order(quote)
    assert changed.status_code == 409 and changed.json()["error"]["code"] == "quote_changed"
    order = bench.order().json()
    with factory.begin() as db:
        db.get(Profile, seed["owner"]).presentation_mode = False
    switched = bench.pay(order["id"])
    assert switched.status_code == 409 and switched.json()["error"]["code"] == "method_changed"
    assert bench.get(order["id"]).json()["status"] == "canceled"
    assert stripe.calls == []


def test_late_stripe_payment_after_hold_expired_is_returned(http, stripe, factory, seed):
    bench = Bench(http)
    bench.sync()
    order = bench.order().json()
    bench.pay(order["id"])
    with factory.begin() as db:
        db.get(KioskOrder, uuid.UUID(order["id"])).expires_at = now() - timedelta(seconds=1)
    assert bench.sync()["kiosk_order"]["status"] == "expired"
    with factory() as db:
        payment = db.query(Payment).one()
        assert payment.status == "canceled"
    intent = stripe.pay(payment.provider_checkout_id)
    _post_event(http, stripe.event("payment_intent.amount_capturable_updated", intent))
    with factory() as db:
        assert db.query(ChargingSession).count() == 0
        assert db.query(Payment).one().settlement_status == "done"
    assert stripe.intents[intent["id"]]["status"] == "canceled"  # autorização liberada inteira


# ---------------------------------------------------------------------------- trava do ponto


def test_hold_blocks_app_start_and_reservation_then_expired_hold_frees_at_once(http, presentation, factory, seed):
    bench = Bench(http)
    bench.sync()
    order = bench.order().json()
    started = _start_from_app(http, factory, seed)
    assert started.status_code == 409
    assert started.json()["error"] == {"code": "point_unavailable", "message": "Ponto em uso no totem",
                                       "reason": "kiosk_in_use"}
    reserved = _reserve_from_app(http, seed)
    assert reserved.status_code == 409 and reserved.json()["error"]["reason"] == "kiosk_in_use"
    point = http.get(f"/v1/stations/{seed['station']}").json()["connectors"][0]
    assert point["availability_status"] == "occupied" and point["kiosk_in_use"] is True
    offer = bench.offer().json()
    assert offer["available"] is False and offer["reason"] == "kiosk_in_use" and offer["open_order_id"] == order["id"]
    # GET renova a trava (5 min) enquanto o pedido está aceito.
    with factory.begin() as db:
        db.get(KioskOrder, uuid.UUID(order["id"])).expires_at = now() + timedelta(seconds=30)
    assert bench.get(order["id"]).json()["expires_in_seconds"] >= 290
    with factory.begin() as db:
        db.get(KioskOrder, uuid.UUID(order["id"])).expires_at = now() - timedelta(seconds=1)
    # Trava vencida libera na hora, antes de o pedido virar "expired".
    assert http.get(f"/v1/stations/{seed['station']}").json()["connectors"][0]["kiosk_in_use"] is False
    assert _reserve_from_app(http, seed, key="after-expiry").status_code == 202
    expired = bench.get(order["id"]).json()
    assert expired["status"] == "expired" and expired["error"]["code"] == "hold_expired"
    assert bench.pay(order["id"]).json()["error"]["code"] == "order_expired"


def test_cancel_releases_hold_and_point_is_free(http, presentation, factory, seed):
    bench = Bench(http)
    bench.sync()
    order = bench.order().json()
    canceled = bench.cancel(order["id"])
    assert canceled.status_code == 200 and canceled.json()["status"] == "canceled"
    assert bench.cancel(order["id"]).json()["status"] == "canceled"  # idempotente
    assert _start_from_app(http, factory, seed).status_code == 202
    assert bench.pay(order["id"]).json()["error"]["code"] == "order_not_payable"


def test_cancel_after_simulated_payment_returns_everything(http, presentation, factory, seed):
    bench = Bench(http)
    bench.sync()
    order = bench.order().json()
    with factory.begin() as db:
        db.get(Device, seed["device"]).reconciled = False
    assert bench.pay(order["id"]).json()["status"] == "paid"
    assert bench.cancel(order["id"]).json()["status"] == "canceled"
    with factory() as db:
        payment = db.query(Payment).one()
        assert (payment.status, payment.settlement_status, payment.charge_cents, payment.captured_cents) == (
            "canceled", "done", 0, 0)


def test_cancel_after_start_is_refused(http, presentation, factory, seed):
    bench = Bench(http)
    bench.sync()
    order = bench.order().json()
    bench.pay(order["id"])
    refused = bench.cancel(order["id"])
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "order_in_use"


def test_order_needs_free_point_and_is_idempotent(http, presentation, factory, seed):
    bench = Bench(http)
    bench.sync()
    quote = bench.quote().json()
    key = bench.key()
    first = bench.order(quote, key=key)
    again = bench.order(quote, key=key)
    assert first.status_code == again.status_code == 201 and first.json()["id"] == again.json()["id"]
    other = bench.order(quote)
    assert other.status_code == 409 and other.json()["error"] == {
        "code": "order_open", "message": "Já existe um pedido do totem aberto neste ponto",
        "order_id": first.json()["id"]}
    bench.cancel(first.json()["id"])
    assert _reserve_from_app(http, seed).status_code == 202
    busy = bench.order(quote)
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "point_unavailable"
    assert busy.json()["error"]["reason"] in ("reserved", "reconciling")
    assert bench.order(quote, key={"Idempotency-Key": ""}).status_code == 422


def test_order_rechecks_quote_and_overstay_terms(http, presentation, factory, seed):
    bench = Bench(http)
    bench.sync()
    quote = bench.quote().json()
    with factory.begin() as db:
        db.get(Connector, seed["point"]).price_per_kwh = 3
    changed = bench.order(quote)
    assert changed.status_code == 409 and changed.json()["error"]["code"] == "quote_changed"
    fresh = changed.json()["error"]["quote"]
    assert fresh["price_per_kwh"] == "3.0000" and fresh["quote_hash"] != quote["quote_hash"]
    with factory.begin() as db:
        db.get(Station, seed["station"]).pricing = {"rotation": ROTATION}
    stale_terms = bench.order(fresh)
    assert stale_terms.status_code == 409 and stale_terms.json()["error"]["code"] == "overstay_terms_changed"
    order = bench.order().json()
    with factory() as db:
        assert db.get(KioskOrder, uuid.UUID(order["id"])).quote["fields"]["overstay_reserve_cents"] == 3000
    bench.pay(order["id"])
    with factory() as db:
        session = db.query(ChargingSession).one()
        assert session.overstay_terms["max_amount"] == "30.00"  # termos travados no pedido
        assert db.query(Payment).one().amount_cents == 5000


def test_order_of_another_point_is_404(http, presentation, factory, seed):
    _second_point(factory, seed)
    bench = Bench(http)
    order = bench.order().json()
    other = Bench(http, {"Authorization": "Device other-key"})
    assert other.get(order["id"]).status_code == 404
    assert other.pay(order["id"]).status_code == 404
    assert other.cancel(order["id"]).status_code == 404
    assert bench.get(str(uuid.uuid4())).status_code == 404


# ---------------------------------------------------------------------------- canal e app


def test_session_origin_and_owner_channel(http, presentation, factory, seed):
    bench = Bench(http)
    bench.sync()
    started = _start_from_app(http, factory, seed)
    assert started.status_code == 202
    synced = bench.sync()
    assert synced["authorized"]["session"]["origin"] == "app"
    start = next(cmd for cmd in synced["commands"] if cmd["type"] == "START")
    session_id = start["session_id"]
    bench.sync(session_id=session_id, physical_state="charging", connected=True,
               acks=[{"command_id": start["id"], "status": "applied", "error": None}])
    bench.sync(session_id=session_id, physical_state="stopped", end_reason="requested_stop")
    bench.sync()
    order = bench.order().json()
    bench.pay(order["id"])
    totem_session, _ = bench.apply_start()
    owner, _ = client_for(factory, seed["owner"])
    items = owner.get("/v1/owner/sessions").json()["items"]
    channels = {item["id"]: (item["payment"] or {}).get("channel") for item in items}
    assert channels[totem_session] == "kiosk_totem" and channels[session_id] is None
    with factory() as db:
        assert db.query(Reservation).count() == 0


# ---------------------------------------------------------------------------- telas do vendedor (integração)


def _app_and_totem_sessions(http, bench, factory, seed):
    """Uma recarga do app (sem pré-pagamento, com energia) e uma do totem (simulado), ambas encerradas."""
    bench.sync()
    assert _start_from_app(http, factory, seed).status_code == 202
    app_session, _ = bench.apply_start()
    bench.charge_and_stop_locally(app_session, energy_wh=1500)
    bench.sync()
    order = bench.order().json()
    assert bench.pay(order["id"]).json()["payment"]["method"] == "simulated"
    totem_session, _ = bench.apply_start()
    bench.charge_and_stop_locally(totem_session, energy_wh=2500)
    bench.sync()
    return app_session, totem_session


def test_seller_history_and_exports_carry_channel_and_method(http, presentation, factory, seed, monkeypatch):
    import csv
    import io

    from app.reports import pdf

    bench = Bench(http)
    app_session, totem_session = _app_and_totem_sessions(http, bench, factory, seed)
    owner, _ = client_for(factory, seed["owner"])
    # App do vendedor: /operator/charging-sessions e o histórico do posto com payment.channel.
    for path in ("/v1/operator/charging-sessions", f"/v1/stations/{seed['station']}/charging-sessions"):
        items = {item["id"]: item for item in owner.get(path).json()["items"]}
        assert items[totem_session]["payment"]["channel"] == "kiosk_totem", path
        assert items[totem_session]["payment"]["provider"] == "simulated"
        assert items[app_session]["payment"] is None
    owner_sessions = {item["id"]: item for item in owner.get("/v1/owner/sessions").json()["items"]}
    assert owner_sessions[totem_session]["payment"]["channel"] == "kiosk_totem"
    # CSV/JSON de sessões: Canal e Pagamento no fim, formato anterior intacto.
    exported = owner.get("/v1/owner/export/sessions.csv")
    rows = list(csv.reader(io.StringIO(exported.text)))
    header = rows[0]
    assert len(header) == 18 and header[15] == "Taxa de permanência (R$)" and header[-2:] == ["Canal", "Pagamento"]
    by_id = {row[0]: row for row in rows[1:]}
    assert by_id[totem_session][-2:] == ["Totem", "Simulado"] and by_id[app_session][-2:] == ["App", ""]
    envelope = owner.get("/v1/owner/export/sessions.json").json()
    json_items = {item["id"]: item for item in envelope["items"]}
    assert (json_items[totem_session]["payment_channel"], json_items[totem_session]["payment_method"]) == (
        "Totem", "Simulado")
    # Resultado do dono: CSV com as colunas no fim e PDF com a coluna Canal.
    margin = list(csv.DictReader(io.StringIO(owner.get("/v1/owner/export/margin.csv").text)))
    margin_rows = {row["ID da sessão"]: row for row in margin}
    assert list(margin[0])[-3:] == ["Base da receita", "Canal", "Pagamento"]
    assert (margin_rows[totem_session]["Canal"], margin_rows[totem_session]["Pagamento"]) == ("Totem", "Simulado")
    assert (margin_rows[app_session]["Canal"], margin_rows[app_session]["Pagamento"]) == ("App", "")
    screen = {item["session_id"]: item for item in owner.get("/v1/owner/margin").json()["items"]}
    assert screen[totem_session]["payment_channel"] == "Totem"
    monkeypatch.setattr(pdf, "COMPRESS", False)
    document = owner.get("/v1/owner/export/margin.pdf")
    assert document.status_code == 200 and b"Canal" in document.content
    assert b"Totem \\267 Simulado" in document.content


def test_owner_live_shows_point_held_by_totem(http, presentation, factory, seed):
    bench = Bench(http)
    bench.sync()
    order = bench.order().json()
    owner, _ = client_for(factory, seed["owner"])
    item = owner.get("/v1/owner/live").json()["items"][0]
    point = owner.get(f"/v1/stations/{seed['station']}").json()["connectors"][0]
    assert item["availability_status"] == point["availability_status"] == "occupied"
    assert item["kiosk_in_use"] is True and item["available"] is False and item["session"] is None
    assert bench.cancel(order["id"]).json()["status"] == "canceled"
    item = owner.get("/v1/owner/live").json()["items"][0]
    assert item["kiosk_in_use"] is False and item["availability_status"] == "available"


def test_owner_station_carries_effective_totem_status(factory, seed, base_url):
    owner, _ = client_for(factory, seed["owner"])
    try:
        bench = Bench(owner)
        url = f"/v1/stations/{seed['station']}"
        status = owner.get(url).json()["kiosk_status"]
        assert status["method"] is None and status["reason"] == "payments_unavailable" and status["label"] is None
        assert "Stripe" in status["reason_label"]
        saved = owner.patch(url, json={"kiosk_mode": True}).json()
        assert saved["kiosk_status"] == status  # o PATCH devolve o mesmo bloco
        kiosk = bench.sync()["connector"]["kiosk"]
        assert (kiosk["method"], kiosk["label"], kiosk["reason"]) == (None, None, "payments_unavailable")
        gateway.use(FakeStripe())
        assert owner.get(url).json()["kiosk_status"] == {"method": "stripe", "label": "TESTE", "reason": None,
                                                         "reason_label": None}
        assert bench.sync()["connector"]["kiosk"]["method"] == "stripe"
        with factory.begin() as db:
            db.get(Profile, seed["owner"]).presentation_mode = True
        assert owner.get(url).json()["kiosk_status"]["method"] == "simulated"
        assert owner.get(url).json()["kiosk_status"]["label"] == "SIMULADO"
        assert bench.sync()["connector"]["kiosk"]["method"] == "simulated"
        listed = owner.get("/v1/operator/stations").json()
        listed = listed["items"] if isinstance(listed, dict) else listed
        assert any(item.get("kiosk_status", {}).get("method") == "simulated" for item in listed)
        with factory.begin() as db:
            db.get(Station, seed["station"]).active = False
        assert owner.get(url).json()["kiosk_status"]["reason"] == "point_disabled"
        driver, _ = client_for(factory, seed["a"])
        with factory.begin() as db:
            db.get(Station, seed["station"]).active = True
        assert "kiosk_status" not in driver.get(url).json()  # só o dono
    finally:
        clear_overrides()


# ---------------------------------------------------------------------------- bateria simulada (SoC)


def test_kiosk_battery_default_is_deterministic_and_in_app_range():
    from types import SimpleNamespace

    from app.modules.payments.service import kiosk_battery

    values = set()
    for _ in range(300):
        payment = SimpleNamespace(id=uuid.uuid4(), quote={})
        first = kiosk_battery(payment)
        assert first == kiosk_battery(payment)  # repetição do START: mesmo corpo idempotente
        assert first["soc_source"] == "simulated" and first["battery_kwh"] == Decimal("44.9")
        assert Decimal(15) <= first["soc_percent"] <= Decimal(60)
        assert first["soc_percent"] == first["soc_percent"].quantize(Decimal("0.1"))
        values.add(first["soc_percent"])
    assert len(values) > 50  # cada visitante é um carro diferente


def test_kiosk_battery_keeps_account_car_and_redraws_full_inherited_soc():
    from types import SimpleNamespace

    from app.modules.payments.service import kiosk_battery

    payment_id = uuid.uuid4()
    drawn = kiosk_battery(SimpleNamespace(id=payment_id, quote=None))["soc_percent"]
    inherited = kiosk_battery(SimpleNamespace(id=payment_id, quote={"vehicle": {"battery_kwh": 82.5,
                                                                               "soc_percent": "94.99"}}))
    assert inherited == {"battery_kwh": Decimal("82.5"), "soc_percent": Decimal("94.99"), "soc_source": "simulated"}
    for full in ("95", "95.00", "100", "100.00"):
        result = kiosk_battery(SimpleNamespace(id=payment_id, quote={"vehicle": {"battery_kwh": 82.5,
                                                                                "soc_percent": full}}))
        assert result == {"battery_kwh": Decimal("82.5"), "soc_percent": drawn, "soc_source": "simulated"}
    unknown = kiosk_battery(SimpleNamespace(id=payment_id, quote={"vehicle": {"battery_kwh": 82.5,
                                                                             "soc_percent": None}}))
    assert unknown["soc_percent"] == drawn and unknown["battery_kwh"] == Decimal("82.5")


def test_guest_totem_charge_simulates_the_car_battery_like_the_app(http, presentation, factory, seed):
    """Visitante sem celular: START leva a bateria (padrão do app) e o SoC sobe com a energia."""
    bench = Bench(http)
    bench.sync()
    order = bench.order().json()
    paid = bench.pay(order["id"])
    assert paid.status_code == 200, paid.text
    session_id, synced = bench.apply_start()
    start = next(cmd for cmd in synced["commands"] if cmd["type"] == "START")["parameters"]
    assert start["soc_source"] == "simulated" and start["battery_kwh"] == 44.9
    assert 15 <= start["soc_percent"] <= 60
    authorized = synced["authorized"]["session"]
    assert authorized["soc_source"] == "simulated" and authorized["start_soc_percent"] == start["soc_percent"]
    bench.sync(session_id=session_id, physical_state="charging", connected=True, energy_wh=2500)
    with factory() as db:
        session = db.get(ChargingSession, uuid.UUID(session_id))
        begin = Decimal(str(start["soc_percent"]))
        assert (session.soc_source, session.start_soc_percent, session.battery_kwh) == (
            "simulated", begin, Decimal("44.90"))
        expected = (begin + Decimal("2.5") / Decimal("44.9") * 100).quantize(Decimal("0.01"))
        assert session.soc_percent == expected
