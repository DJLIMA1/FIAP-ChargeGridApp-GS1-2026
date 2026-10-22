"""Pagamento Stripe em modo teste (teto pré-pago) — sempre com FakeStripe, sem rede."""

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from test_http import clear_overrides, client_for, sync_payload

from app.config import settings
from app.models import (
    ChargingSession,
    Command,
    Connector,
    Coupon,
    Device,
    Payment,
    PaymentEvent,
    Station,
    now,
)
from app.modules.payments import gateway
from app.modules.payments.fake import FakeStripe
from app.modules.payments.gateway import GatewayError, StripeGateway, sign
from app.presence_code import current_code
from app.security import digest

DEVICE = {"Authorization": "Device test-key"}
SECRET = "whsec_test_secret"


@pytest.fixture
def stripe(monkeypatch):
    fake = FakeStripe()
    gateway.use(fake)
    monkeypatch.setattr(settings(), "stripe_webhook_secret", SECRET)
    monkeypatch.setattr(settings(), "public_base_url", "https://api.chargegrid.test")
    yield fake
    gateway.use(None)


@pytest.fixture
def client(factory, seed, stripe):
    http, selected = client_for(factory, seed["a"])
    yield http, selected
    clear_overrides()


class Flow:
    """Device + driver helpers sharing one boot sequence."""

    def __init__(self, http, factory, seed):
        self.http, self.factory, self.seed, self.sequence = http, factory, seed, 0

    def sync(self, **changes):
        self.sequence += 1
        response = self.http.post("/v1/devices/sync", headers=DEVICE, json=sync_payload(self.sequence, **changes))
        assert response.status_code == 200, response.text
        return response.json()

    def code(self):
        with self.factory() as db:
            return current_code(db.get(Station, self.seed["station"]))[0]

    def pay(self, key="pay-1", **body):
        response = self.http.post("/v1/payments", headers={"Idempotency-Key": key},
                                  json={"connector_id": str(self.seed["point"]), "mode": "value", "max_cost": "20",
                                        **body})
        assert response.status_code == 201, response.text
        return response.json()

    def get(self, payment_id):
        response = self.http.get(f"/v1/payments/{payment_id}")
        assert response.status_code == 200, response.text
        return response.json()

    def start(self, key="start-1", **body):
        return self.http.post("/v1/charging-sessions", headers={"Idempotency-Key": key},
                              json={"public_code": "CG-01", "presence_code": self.code(), **body})

    def charge(self, session_id, energy_wh):
        start_cmd = next(cmd for cmd in self.sync()["commands"] if cmd["type"] == "START")
        self.sync(session_id=session_id, physical_state="charging", connected=True,
                  acks=[{"command_id": start_cmd["id"], "status": "applied", "error": None}])
        return self.sync(session_id=session_id, physical_state="charging", connected=True, energy_wh=energy_wh)

    def stop(self, session_id, energy_wh):
        self.http.post(f"/v1/charging-sessions/{session_id}/stop", headers={"Idempotency-Key": f"stop-{session_id}"})
        stop_cmd = next(cmd for cmd in self.sync(session_id=session_id, physical_state="charging", connected=True,
                                                  energy_wh=energy_wh)["commands"] if cmd["type"] == "STOP")
        return self.sync(session_id=session_id, physical_state="stopped", energy_wh=energy_wh,
                         acks=[{"command_id": stop_cmd["id"], "status": "applied", "error": None}])


@pytest.fixture
def flow(client, factory, seed):
    return Flow(client[0], factory, seed)


def _checkout(stripe, payment):
    return next(session for session in stripe.sessions.values()
                if session["metadata"]["payment_id"] == payment["id"])


def _paid(flow, stripe, method="card", **body):
    payment = flow.pay(**body)
    stripe.pay(_checkout(stripe, payment)["id"], method=method)
    payment = flow.get(payment["id"])
    assert payment["status"] == ("authorized" if method == "card" else "paid")
    return payment


def _start_paid(flow, payment):
    response = flow.start(payment_id=payment["id"])
    assert response.status_code == 202, response.text
    return response.json()


def _set(factory, payment_id, **values):
    with factory.begin() as db:
        payment = db.get(Payment, payment_id)
        for key, value in values.items():
            setattr(payment, key, value)


def _require_prepay(factory, seed, value=True):
    with factory.begin() as db:
        db.get(Station, seed["station"]).prepay_required = value


# ---------------------------------------------------------------------------- configuração


def test_gateway_only_with_test_keys(monkeypatch):
    gateway.use(None)
    for key, expected in (("", None), ("sk_live_abc", None), ("pk_test_abc", None), ("sk_test_abc", StripeGateway)):
        monkeypatch.setattr(settings(), "stripe_secret_key", key)
        current = gateway.current()
        assert (current is None) if expected is None else isinstance(current, expected)


def test_config_and_unavailable_without_gateway(factory, seed):
    gateway.use(None)
    http, _ = client_for(factory, seed["a"])
    try:
        assert http.get("/v1/payments/config").json()["enabled"] is False
        response = http.post("/v1/payments", headers={"Idempotency-Key": "k"},
                             json={"connector_id": str(seed["point"]), "mode": "value", "max_cost": "20"})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "payments_unavailable"
    finally:
        clear_overrides()


def test_config_with_gateway(client):
    body = client[0].get("/v1/payments/config").json()
    assert body["enabled"] is True and body["environment"] == "test" and body["currency"] == "BRL"
    assert body["kiosk_amounts"] == ["10.00", "20.00", "40.00"]


# ---------------------------------------------------------------------------- orçamento e Checkout


def test_create_payment_quote_is_server_side_and_idempotent(flow, stripe, client):
    payment = flow.pay()
    assert payment["status"] == "awaiting_payment" and payment["status_label"] == "Aguardando pagamento"
    assert payment["environment"] == "test" and payment["amount"] == "20.00" and payment["energy_cap"] == "20.00"
    # Ponto de 1 kW a R$ 2/kWh: R$ 20 = 10 kWh, mas o ponto limita a 60 min.
    assert payment["max_duration_minutes"] == 60 and payment["price_per_kwh"] == "2.0000"
    assert payment["checkout_url"].startswith("https://checkout.stripe.test/")
    params = _checkout(stripe, payment)["params"]
    assert params["payment_method_options"] == {"card": {"capture_method": "manual"}}
    assert params["line_items"][0]["price_data"] == {**params["line_items"][0]["price_data"], "currency": "brl",
                                                     "unit_amount": 2000}
    assert params["success_url"] == f"https://api.chargegrid.test/pay/return?p={payment['id']}"
    assert params["payment_intent_data"]["metadata"]["payment_id"] == payment["id"]
    assert "(teste)" in params["line_items"][0]["price_data"]["product_data"]["name"]
    # Repetição com a mesma chave: mesmo pagamento, uma única Checkout.
    assert flow.pay()["id"] == payment["id"]
    assert stripe.calls.count("create_checkout_session") == 1
    conflict = client[0].post("/v1/payments", headers={"Idempotency-Key": "pay-1"},
                              json={"connector_id": str(flow.seed["point"]), "mode": "value", "max_cost": "30"})
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "idempotency_conflict"


def test_quote_by_time_with_coupon(flow, factory, seed):
    with factory.begin() as db:
        db.add(Coupon(operator_id=seed["owner"], code="METADE", description="50%", discount_percent=50,
                      valid_until=now() + timedelta(days=1)))
    payment = flow.pay(mode="time", minutes=30, max_cost=None, coupon_code="metade")
    # 0,5 kWh × R$ 2 × 50 % = R$ 0,50.
    assert (payment["amount"], payment["discount_percent"], payment["max_duration_minutes"]) == ("0.50", 50, 30)
    too_small = flow.http.post("/v1/payments", headers={"Idempotency-Key": "small"},
                               json={"connector_id": str(seed["point"]), "mode": "time", "minutes": 5})
    assert too_small.status_code == 422 and too_small.json()["error"]["code"] == "invalid_quote"


def test_checkout_failure_is_reported_and_retry_reuses_payment(flow, stripe, client):
    stripe.fail_next["create_checkout_session"] = GatewayError("timeout", retryable=True)
    response = client[0].post("/v1/payments", headers={"Idempotency-Key": "retry"},
                              json={"connector_id": str(flow.seed["point"]), "mode": "value", "max_cost": "20"})
    assert response.status_code == 502
    payment = flow.pay(key="retry")
    assert payment["checkout_url"] and payment["status"] == "awaiting_payment"
    with flow.factory() as db:
        assert db.query(Payment).count() == 1


# ---------------------------------------------------------------------------- confirmação


def test_server_side_verification_without_webhook(flow, stripe):
    payment = flow.pay()
    assert flow.get(payment["id"])["status"] == "awaiting_payment"
    stripe.pay(_checkout(stripe, payment)["id"])
    throttled = flow.get(payment["id"])  # no máximo uma consulta à Stripe a cada 3 s
    assert throttled["status"] == "awaiting_payment"
    _set(flow.factory, payment["id"], last_provider_check_at=now() - timedelta(seconds=4))
    confirmed = flow.get(payment["id"])
    assert confirmed["status"] == "authorized" and confirmed["status_label"] == "Pago (teste)"
    assert confirmed["method"] == "card" and confirmed["provider_ref"].startswith("pi_")
    assert confirmed["start_deadline"] and confirmed["checkout_url"] is None


def test_declined_then_retry_authorizes(flow, stripe):
    payment = flow.pay()
    session_id = _checkout(stripe, payment)["id"]
    stripe.pay(session_id, decline=True)
    assert flow.get(payment["id"])["status"] == "declined"
    _set(flow.factory, payment["id"], last_provider_check_at=None)
    stripe.pay(session_id)
    assert flow.get(payment["id"])["status"] == "authorized"


def test_return_page_never_confirms_by_itself(flow, stripe):
    payment = flow.pay()
    page = flow.http.get(f"/pay/return?p={payment['id']}")
    assert page.status_code == 200 and "Confirmando com a Stripe" in page.text
    assert "AMBIENTE DE TESTE" in page.text and "default-src 'none'" in page.headers["content-security-policy"]
    assert flow.get(payment["id"])["status"] == "awaiting_payment"
    stripe.pay(_checkout(stripe, payment)["id"])
    _set(flow.factory, payment["id"], last_provider_check_at=None)
    assert "Pagamento confirmado (teste)" in flow.http.get(f"/pay/return?p={payment['id']}").text


# ---------------------------------------------------------------------------- START


def test_prepay_required_blocks_start_without_payment(flow, factory, seed):
    _require_prepay(factory, seed)
    response = flow.start()
    assert response.status_code == 402 and response.json()["error"]["code"] == "payment_required"
    with factory() as db:
        assert db.query(Command).count() == 0


def test_start_without_flag_is_unchanged(flow):
    assert flow.start().status_code == 202


def test_start_rejects_unconfirmed_foreign_or_expired_payment(flow, stripe, factory, seed, client):
    payment = flow.pay()
    not_ready = flow.start(payment_id=payment["id"])
    assert not_ready.status_code == 409 and not_ready.json()["error"]["code"] == "payment_not_ready"
    stripe.pay(_checkout(stripe, payment)["id"])
    flow.get(payment["id"])
    _set(factory, payment["id"], start_deadline=now() - timedelta(seconds=1))
    expired = flow.start(key="s2", payment_id=payment["id"])
    assert expired.status_code == 409 and expired.json()["error"]["code"] == "payment_expired"
    client[1]["id"] = seed["b"]
    foreign = flow.http.post("/v1/charging-sessions", headers={"Idempotency-Key": "s3"},
                                 json={"public_code": "CG-01", "presence_code": flow.code(),
                                       "payment_id": payment["id"]})
    assert foreign.status_code == 404 and foreign.json()["error"]["code"] == "payment_not_found"
    with factory() as db:
        assert db.query(Command).count() == 0


def test_payment_for_another_point_is_rejected(flow, stripe, factory, seed):
    with factory.begin() as db:
        other = Connector(station_id=seed["station"], public_code="CG-02", connector_type="bench", power_kw=1,
                          price_per_kwh=2)
        db.add(other)
        db.flush()
        db.add(Device(connector_id=other.id, key_hash=digest("other-key"), last_seen=now(), reconciled=True,
                      physical_state="idle"))
        other_id = other.id
    payment = flow.pay(connector_id=str(other_id))
    stripe.pay(_checkout(stripe, payment)["id"])
    flow.get(payment["id"])
    response = flow.start(payment_id=payment["id"])
    assert response.status_code == 409 and response.json()["error"]["code"] == "payment_mismatch"


def test_full_card_flow_captures_only_consumed(flow, stripe, factory, seed, client):
    _require_prepay(factory, seed)
    payment = _paid(flow, stripe)
    session = _start_paid(flow, payment)
    assert Decimal(session["max_cost"]) == Decimal("20") and session["max_duration_minutes"] == 60
    assert session["payment"]["status"] == "in_use"
    start_cmd = flow.charge(session["id"], 3000)
    assert start_cmd["authorized"]["session"]["max_cost"] == "20.0000"
    calls = len(stripe.calls)
    flow.stop(session["id"], 6200)
    assert len(stripe.calls) == calls  # o sync nunca espera a Stripe
    with factory() as db:
        assert db.get(Payment, payment["id"]).settlement_status == "due"
    done = flow.get(payment["id"])
    assert done["status"] == "completed"
    assert done["status_label"] == "Cobrado R$ 12,40 (teste) · Devolvido R$ 7,60"
    settlement = done["settlement"]
    assert (settlement["energy_amount"], settlement["charged"], settlement["returned"]) == ("12.40", "12.40", "7.60")
    assert settlement["return_kind"] == "released" and settlement["captured"] == "12.40"
    assert settlement["provider_fee"] is not None and settlement["status"] == "done"
    intent = stripe.intents[done["provider_ref"]]
    assert (intent["status"], intent["amount_received"]) == ("succeeded", 1240)
    assert flow.http.get(f"/v1/charging-sessions/{session['id']}").json()["payment"]["status"] == "completed"
    # Repetir a leitura não captura de novo.
    flow.get(payment["id"])
    assert stripe.calls.count("capture") == 1
    used = flow.start(key="again", payment_id=payment["id"])
    assert used.status_code == 409 and used.json()["error"]["code"] == "payment_used"


def test_start_uses_locked_quote_terms(flow, stripe, factory, seed):
    payment = _paid(flow, stripe)
    with factory.begin() as db:
        db.get(Connector, seed["point"]).price_per_kwh = Decimal("5")  # tarifa muda depois do pagamento
    session = _start_paid(flow, payment)
    assert session["price_per_kwh"] == "2.0000"



def test_paid_start_snapshots_receipt_terms_from_quote(flow, stripe, factory, seed):
    """Integração recibo × pagamento: a explicação do preço (com cupom) vem do orçamento pago."""
    with factory.begin() as db:
        db.add(Coupon(operator_id=seed["owner"], code="METADE", description="50%", discount_percent=50,
                      valid_until=now() + timedelta(days=1)))
        db.get(Station, seed["station"]).energy_cost_per_kwh = Decimal("0.80")
    payment = _paid(flow, stripe, mode="time", minutes=30, max_cost=None, coupon_code="metade")
    locked = payment["quote"]["price_terms"]
    assert locked["locked_by"] == "start" and locked["coupon"]["code"] == "METADE"
    with factory.begin() as db:
        db.get(Connector, seed["point"]).price_per_kwh = Decimal("5")
    session = _start_paid(flow, payment)
    with factory() as db:
        row = db.get(ChargingSession, session["id"])
        assert row.price_terms == locked
        assert (row.discount_percent, str(row.base_price_per_kwh)) == (50, "2.0000")
        assert (str(row.energy_cost_per_kwh), str(row.platform_fee_percent)) == ("0.8000", "25.00")

def test_battery_full_releases_surplus(flow, stripe):
    payment = _paid(flow, stripe)
    session = flow.start(payment_id=payment["id"], soc_percent=90, battery_kwh=10, soc_source="simulated").json()
    flow.charge(session["id"], 500)
    synced = flow.sync(session_id=session["id"], physical_state="charging", connected=True, energy_wh=1300)
    stop_cmd = next(cmd for cmd in synced["commands"] if cmd["type"] == "STOP")
    assert stop_cmd["parameters"] == {"reason": "battery_full"}
    flow.sync(session_id=session["id"], physical_state="stopped", energy_wh=1300,
              acks=[{"command_id": stop_cmd["id"], "status": "applied", "error": None}])
    done = flow.get(payment["id"])
    assert (done["settlement"]["charged"], done["settlement"]["returned"]) == ("2.60", "17.40")
    assert flow.http.get(f"/v1/charging-sessions/{session['id']}").json()["end_reason"] == "battery_full"


def test_pix_refunds_the_difference(flow, stripe):
    payment = _paid(flow, stripe, method="pix")
    assert payment["status_label"] == "Pago (teste)"
    session = _start_paid(flow, payment)
    flow.charge(session["id"], 3000)
    flow.stop(session["id"], 6200)
    done = flow.get(payment["id"])
    assert done["settlement"]["return_kind"] == "refunded"
    assert (done["settlement"]["captured"], done["settlement"]["refunded"]) == ("20.00", "7.60")
    charge = stripe.intents[done["provider_ref"]]["latest_charge"]
    assert charge["amount_refunded"] == 760
    assert stripe.calls.count("refund") == 1


def test_start_that_never_began_returns_everything(flow, stripe):
    payment = _paid(flow, stripe)
    session = _start_paid(flow, payment)
    start_cmd = next(cmd for cmd in flow.sync()["commands"] if cmd["type"] == "START")
    synced = flow.sync(acks=[{"command_id": start_cmd["id"], "status": "failed", "error": "relay"}])
    stop_cmd = next(cmd for cmd in synced["commands"] if cmd["type"] == "STOP")
    flow.sync(session_id=session["id"], physical_state="stopped",
              acks=[{"command_id": stop_cmd["id"], "status": "applied", "error": None}])
    done = flow.get(payment["id"])
    assert done["settlement"]["charged"] == "0.00" and done["status_label"] == "Devolvido (teste)"
    assert stripe.intents[done["provider_ref"]]["status"] == "canceled"


def test_consumption_below_provider_minimum_is_waived(flow, stripe):
    payment = _paid(flow, stripe)
    session = _start_paid(flow, payment)
    flow.charge(session["id"], 100)
    flow.stop(session["id"], 100)
    settlement = flow.get(payment["id"])["settlement"]
    assert (settlement["charged"], settlement["waived"], settlement["below_minimum"]) == ("0.00", "0.20", True)
    assert stripe.calls.count("capture") == 0 and stripe.calls.count("cancel") == 1


def test_cost_above_cap_captures_only_the_cap(flow, stripe):
    payment = _paid(flow, stripe)
    session = _start_paid(flow, payment)
    flow.charge(session["id"], 5000)
    flow.stop(session["id"], 10500)
    settlement = flow.get(payment["id"])["settlement"]
    assert (settlement["charged"], settlement["waived"], settlement["returned"]) == ("20.00", "1.00", "0.00")


def test_cost_above_cap_is_waived_even_with_overstay_reserve(flow, stripe, factory, seed):
    # Taxa de permanência ligada: a autorização reserva o teto dela (R$ 30), mas a energia acima do
    # teto aceito (R$ 20) continua perdoada — antes saía da reserva e o motorista pagava R$ 21,00.
    with factory.begin() as db:
        db.get(Station, seed["station"]).pricing = {"rotation": {
            "enabled": True, "start_after_min": 0, "interval_min": 1, "amount": "1.00", "max_amount": "30.00"}}
    payment = _paid(flow, stripe)
    assert payment["amount"] == "50.00"
    session = _start_paid(flow, payment)
    flow.charge(session["id"], 5000)
    flow.stop(session["id"], 10500)
    settlement = flow.get(payment["id"])["settlement"]
    assert (settlement["charged"], settlement["waived"], settlement["returned"]) == ("20.00", "1.00", "30.00")


def test_settlement_retry_after_provider_timeout(flow, stripe, factory):
    payment = _paid(flow, stripe)
    session = _start_paid(flow, payment)
    flow.charge(session["id"], 3000)
    flow.stop(session["id"], 6200)
    stripe.fail_next["capture"] = GatewayError("timeout", retryable=True)
    pending = flow.get(payment["id"])
    assert pending["status"] == "in_use" and pending["settlement"]["status"] == "due"
    with factory() as db:
        assert db.get(Payment, payment["id"]).last_error == "settle: timeout"
    done = flow.get(payment["id"])
    assert done["status"] == "completed" and stripe.intents[done["provider_ref"]]["amount_received"] == 1240


def test_unused_authorization_expires_and_is_released(flow, stripe, factory):
    payment = _paid(flow, stripe)
    _set(factory, payment["id"], start_deadline=now() - timedelta(seconds=1))
    expired = flow.get(payment["id"])
    assert expired["status"] == "expired" and expired["settlement"]["status"] == "done"
    assert expired["status_label"] == "Expirado · valor devolvido"
    assert stripe.intents[expired["provider_ref"]]["status"] == "canceled"


def test_unpaid_checkout_expires(flow, stripe, factory):
    payment = flow.pay()
    _set(factory, payment["id"], expires_at=now() - timedelta(seconds=1))
    assert flow.get(payment["id"])["status"] == "expired"
    assert _checkout(stripe, payment)["status"] == "expired"


def test_late_payment_after_expiry_is_released(flow, stripe, factory):
    payment = flow.pay()
    _set(factory, payment["id"], expires_at=now() - timedelta(seconds=1))
    stripe.fail_next["expire_checkout_session"] = GatewayError("checkout_session_not_open", status=400)
    flow.get(payment["id"])
    stripe.pay(_checkout(stripe, payment)["id"])  # chegou depois de expirar
    intent = next(iter(stripe.intents.values()))
    _post_event(flow.http, stripe.event("payment_intent.amount_capturable_updated", intent))
    late = flow.get(payment["id"])
    assert late["status"] == "expired" and late["settlement"]["charged"] == "0.00"
    assert stripe.intents[intent["id"]]["status"] == "canceled"


def test_cancel_before_start(flow, stripe):
    awaiting = flow.pay()
    canceled = flow.http.post(f"/v1/payments/{awaiting['id']}/cancel").json()
    assert canceled["status"] == "canceled" and _checkout(stripe, awaiting)["status"] == "expired"
    payment = flow.pay(key="pay-2")
    stripe.pay(_checkout(stripe, payment)["id"])
    flow.get(payment["id"])
    released = flow.http.post(f"/v1/payments/{payment['id']}/cancel").json()
    assert released["status"] == "canceled" and stripe.intents[released["provider_ref"]]["status"] == "canceled"
    third = _paid(flow, stripe, key="pay-3")
    _start_paid(flow, third)
    in_use = flow.http.post(f"/v1/payments/{third['id']}/cancel")
    assert in_use.status_code == 409 and in_use.json()["error"]["code"] == "payment_in_use"


def test_new_payment_replaces_unpaid_and_blocks_when_funded(flow, stripe):
    first = flow.pay()
    second = flow.pay(key="pay-2")
    assert flow.get(first["id"])["status"] == "canceled"
    stripe.pay(_checkout(stripe, second)["id"])
    blocked = flow.http.post("/v1/payments", headers={"Idempotency-Key": "pay-3"},
                             json={"connector_id": str(flow.seed["point"]), "mode": "value", "max_cost": "20"})
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "payment_open_exists"
    assert flow.http.get("/v1/payments/current").json()["id"] == second["id"]


# ---------------------------------------------------------------------------- webhook


def _post_event(http, event, secret=SECRET, timestamp=None):
    payload = json.dumps(event).encode()
    return http.post("/v1/webhooks/stripe", content=payload,
                     headers={"Stripe-Signature": sign(payload, secret, timestamp), "Content-Type": "application/json"})


def test_webhook_rejects_bad_missing_or_stale_signature(flow, stripe, factory):
    payment = flow.pay()
    intent = stripe.pay(_checkout(stripe, payment)["id"])
    event = stripe.event("payment_intent.amount_capturable_updated", intent)
    assert _post_event(flow.http, event, secret="whsec_other").status_code == 400
    assert _post_event(flow.http, event, timestamp=int(now().timestamp()) - 600).status_code == 400
    assert flow.http.post("/v1/webhooks/stripe", content=json.dumps(event).encode()).status_code == 400
    with factory() as db:
        assert db.get(Payment, payment["id"]).status == "awaiting_payment"
        assert db.query(PaymentEvent).count() == 0


def test_webhook_unconfigured_is_503(flow, stripe, monkeypatch):
    monkeypatch.setattr(settings(), "stripe_webhook_secret", "")
    assert _post_event(flow.http, {"id": "evt_1", "type": "x", "data": {"object": {}}}).status_code == 503


def test_webhook_confirms_once_and_ignores_duplicates_and_stale_events(flow, stripe, factory):
    payment = flow.pay()
    session = _checkout(stripe, payment)
    intent = stripe.pay(session["id"])
    event = stripe.event("payment_intent.amount_capturable_updated", intent)
    calls = len(stripe.calls)
    response = _post_event(flow.http, event)
    assert response.status_code == 200 and response.json() == {"received": True}
    assert len(stripe.calls) == calls  # evento de PaymentIntent aplicado sem consultar a Stripe
    with factory() as db:
        assert db.get(Payment, payment["id"]).status == "authorized"
    assert _post_event(flow.http, event).json()["duplicate"] is True
    # Evento antigo de falha chegando depois não regride o pagamento.
    stale = stripe.event("payment_intent.payment_failed", {**intent, "status": "requires_payment_method",
                                                           "last_payment_error": {"code": "card_declined"}})
    assert _post_event(flow.http, stale).status_code == 200
    with factory() as db:
        assert db.get(Payment, payment["id"]).status == "authorized"
        assert db.query(PaymentEvent).count() == 2


def test_webhook_checkout_completed_fetches_intent(flow, stripe, factory):
    payment = flow.pay()
    session = _checkout(stripe, payment)
    intent = stripe.pay(session["id"], method="pix")
    obj = {"id": session["id"], "object": "checkout.session", "status": "complete", "payment_intent": intent["id"],
           "metadata": session["metadata"]}
    stripe.fail_next["retrieve_payment_intent"] = GatewayError("timeout", retryable=True)
    assert _post_event(flow.http, stripe.event("checkout.session.completed", obj, "evt_done")).status_code == 503
    assert _post_event(flow.http, stripe.event("checkout.session.completed", obj, "evt_done")).status_code == 200
    with factory() as db:
        stored = db.get(Payment, payment["id"])
        assert (stored.status, stored.method, stored.captured_cents) == ("paid", "pix", 2000)


def test_webhook_unknown_payment_is_acknowledged(flow, stripe):
    event = {"id": "evt_unknown", "type": "payment_intent.succeeded",
             "data": {"object": {"id": "pi_other", "object": "payment_intent", "status": "succeeded"}}}
    assert _post_event(flow.http, event).status_code == 200


# ---------------------------------------------------------------------------- vendedor, cron


def test_station_flags_and_owner_projection(flow, stripe, factory, seed, client):
    selected = client[1]
    selected["id"] = seed["owner"]
    patched = flow.http.patch(f"/v1/stations/{seed['station']}", json={"prepay_required": True,
                                                                        "kiosk_payments": True})
    assert patched.status_code == 200 and patched.json()["prepay_required"] is True
    selected["id"] = seed["a"]
    payment = _paid(flow, stripe)
    session = _start_paid(flow, payment)
    selected["id"] = seed["owner"]
    items = flow.http.get("/v1/owner/sessions", params={"from": (now() - timedelta(hours=1)).isoformat(),
                                                         "to": (now() + timedelta(hours=1)).isoformat()}).json()
    row = next(item for item in items["items"] if item["id"] == session["id"])
    assert row["payment"]["status"] == "in_use" and row["payment"]["amount"] == "20.00"
    assert "checkout_url" not in row["payment"] and "coupon_code" not in row["payment"]


def test_keepalive_sweep_releases_stale_authorizations(flow, stripe, factory, monkeypatch):
    payment = _paid(flow, stripe)
    _set(factory, payment["id"], start_deadline=now() - timedelta(seconds=1))
    monkeypatch.setenv("CRON_SECRET", "cron")
    assert flow.http.get("/internal/keepalive", headers={"Authorization": "Bearer cron"}).status_code == 200
    with factory() as db:
        stored = db.get(Payment, payment["id"])
        assert (stored.status, stored.settlement_status) == ("expired", "done")


def test_session_rows_without_payment_are_null(flow):
    session = flow.start().json()
    assert session["payment"] is None
    with flow.factory() as db:
        assert db.get(ChargingSession, session["id"]) is not None
