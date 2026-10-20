"""Pagamento Stripe em MODO TESTE: orçamento, Checkout, confirmação, expiração e acerto.

Sem worker de fundo (Vercel serverless): o estado avança quando alguém olha o pagamento —
webhook assinado, ``GET`` do app (verificação no servidor como alternativa ao webhook), página
de status do painel e a varredura do cron diário (``sweep``). Toda chamada à Stripe acontece
sem trava do ponto; as que movem dinheiro levam ``Idempotency-Key`` derivada do pagamento.

Confirmação = PaymentIntent em ``requires_capture`` (cartão, pré-autorizado) ou ``succeeded``
(Pix). O retorno do navegador sozinho nunca confirma nada.
"""

import hashlib
import json
import secrets
import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert

from chargegrid_core import billing, pricing

from ...config import settings
from ...errors import fail
from ...models import PAYMENT_OPEN, ChargingSession, Connector, Payment, PaymentEvent, Profile, Station, now
from ...presence_code import current_code, valid_code
from ...schemas import StartInput
from ...service import SESSION_ACTIVE, active_res, free, idempotent, remember
from ..auth.routes import limit
from ..charging.service import find_coupon, session_power_limit, start, stop
from ..pricing.service import locked_terms
from . import gateway as gateways
from .funding import (
    FUNDED,
    PRE_START,
    mark_zero_settlement,
    prepare_settlement_for_session,
    start_window,
)
from .gateway import GatewayError
from .overstay import overstay_terms

CHECKOUT_MINUTES = 31  # a Stripe exige ao menos 30 min de validade para a Checkout
PROVIDER_CHECK_SECONDS = 3
SETTLING_STALE_SECONDS = 120
MAX_SETTLE_ATTEMPTS = 5
KIOSK_AMOUNTS_CENTS = (1000, 2000, 4000)
# Erros de início que podem passar sozinhos (ponto reconciliando): o pagamento do painel espera
# até o prazo de início em vez de ser devolvido na hora.
TRANSIENT_START_ERRORS = ("point_unavailable", "user_busy", "invalid_presence_code")


def enabled():
    return gateways.current() is not None


def require_gateway():
    gateway = gateways.current()
    if gateway is None:
        fail("payments_unavailable", "Pagamento indisponível no momento (Stripe em modo teste não configurada)", 503)
    return gateway


def public_base(request_base=""):
    return (settings().public_base_url.strip() or request_base or "").rstrip("/")


def config():
    methods = [item.strip() for item in settings().stripe_methods.split(",") if item.strip()]
    return {
        "enabled": enabled(),
        "provider": "stripe",
        "environment": "test",
        "currency": billing.CURRENCY,
        "methods": methods or ["card"],
        "min_amount": str(billing.money(billing.MIN_CHARGE_CENTS)),
        "kiosk_amounts": [str(billing.money(value)) for value in KIOSK_AMOUNTS_CENTS],
        "test_card": "4242 4242 4242 4242",
    }


# ---------------------------------------------------------------------------- orçamento


def quote(db, user, connector, data):
    """Teto e termos travados, calculados pela API (o valor do cliente nunca é aceito como teto)."""
    station = db.get(Station, connector.station_id)
    if not connector.active or not station or not station.active or station.owner_id is None:
        fail("point_unavailable", "Ponto indisponível", 409)
    reservation = active_res(db, connector.id)
    if reservation and (reservation.user_id != user.id or reservation.status != "confirmed"):
        reservation = None
    # Um único cálculo: os termos travados aqui (e a explicação do recibo) valem no START pago.
    base, multiplier, price_terms = locked_terms(db, connector, reservation)
    price = pricing.dynamic_price(base, multiplier)
    coupon = find_coupon(db, connector, data.coupon_code)
    discount = coupon.discount_percent if coupon else 0
    if coupon is not None:
        price_terms["coupon"] = {"id": str(coupon.id), "code": coupon.code,
                                 "discount_percent": int(coupon.discount_percent)}
    power = session_power_limit(db, connector, data.max_power_kw) or Decimal(connector.power_kw)
    try:
        cap = billing.quote_cap(
            data.mode, power_kw=power, price_per_kwh=price, discount_percent=discount, minutes=data.minutes,
            max_cost=data.max_cost, energy_kwh=data.energy_kwh, max_minutes=connector.max_duration_minutes,
        )
    except ValueError as exc:
        fail("invalid_quote", str(exc), 422)
    terms = overstay_terms(db, station)
    reserve = int(terms.get("reserve_cents") or 0)
    return {
        "energy_cap_cents": cap["energy_cap_cents"],
        "fixed_fee_cents": 0,
        "overstay_reserve_cents": reserve,
        "amount_cents": cap["energy_cap_cents"] + reserve,
        "price_per_kwh": price,
        "base_price_per_kwh": base,
        "demand_multiplier": multiplier,
        "discount_percent": discount,
        "coupon_code": data.coupon_code.strip().upper() if data.coupon_code else None,
        "max_duration_minutes": cap["max_duration_minutes"],
        "max_power_kw": power if data.max_power_kw is not None else None,
        "quote": {
            "mode": data.mode,
            "minutes": data.minutes,
            "max_cost": str(data.max_cost) if data.max_cost is not None else None,
            "energy_kwh": str(cap["energy_kwh"]),
            "power_kw": str(power),
            "reservation_terms": reservation is not None,
            "overstay": {key: (str(value) if isinstance(value, Decimal) else value) for key, value in terms.items()},
            "price_terms": price_terms,
        },
    }


# ---------------------------------------------------------------------------- Checkout


def _checkout_params(payment, connector, success_url, cancel_url):
    name = f"Recarga ChargeGrid {connector.public_code} (teste)"
    return {
        "mode": "payment",
        "locale": "pt-BR",
        "client_reference_id": str(payment.id),
        "line_items": [{
            "quantity": 1,
            "price_data": {
                "currency": "brl",
                "unit_amount": payment.amount_cents,
                "product_data": {
                    "name": name,
                    "description": "Pré-autorização do teto. Cobramos só a energia confirmada pelo equipamento; "
                                   "o restante é liberado ou devolvido. Ambiente de teste: nenhum valor real.",
                },
            },
        }],
        # Cartão: autorização retida e captura só do consumido; outros métodos (Pix) cobram na hora.
        "payment_method_options": {"card": {"capture_method": "manual"}},
        "payment_intent_data": {
            "description": name,
            "metadata": {"payment_id": str(payment.id), "origin": payment.origin},
        },
        "metadata": {"payment_id": str(payment.id), "connector": connector.public_code, "origin": payment.origin},
        "success_url": success_url,
        "cancel_url": cancel_url,
        "expires_at": int((now() + timedelta(minutes=CHECKOUT_MINUTES)).timestamp()),
    }


def ensure_checkout(db, payment, success_url, cancel_url):
    """Abre a Checkout hospedada (idempotente por pagamento). Faz commit antes e depois."""
    if payment.checkout_url or payment.status not in PRE_START:
        return payment
    gateway = require_gateway()
    connector = db.get(Connector, payment.connector_id)
    params = _checkout_params(payment, connector, success_url, cancel_url)
    db.commit()
    try:
        session = gateway.create_checkout_session(params, f"checkout-{payment.id}")
    except GatewayError as exc:
        payment = db.scalar(select(Payment).where(Payment.id == payment.id).with_for_update())
        payment.last_error = f"checkout: {exc.code}"[:200]
        if not exc.retryable:
            payment.status = "canceled"
        db.commit()
        fail("payment_provider_error", "Não foi possível abrir o pagamento na Stripe (teste). Tente de novo.", 502)
    payment = db.scalar(select(Payment).where(Payment.id == payment.id).with_for_update())
    payment.provider_checkout_id = session["id"]
    payment.checkout_url = session.get("url")
    payment.expires_at = now() + timedelta(minutes=CHECKOUT_MINUTES - 1)
    payment.last_error = None
    db.commit()
    return payment


def _expire_checkout(payment):
    gateway = gateways.current()
    if gateway is None or not payment.provider_checkout_id:
        return
    try:
        gateway.expire_checkout_session(payment.provider_checkout_id, f"expire-{payment.id}")
    except GatewayError:
        pass  # já concluída/expirada: o estado real chega pela verificação/webhook


def create_payment(db, user, data, key, request_base=""):
    db.execute(select(Profile).where(Profile.id == user.id).with_for_update()).scalar_one()
    old, body_hash = idempotent(db, user, "payment", key, data.model_dump(), Payment)
    base = public_base(request_base)
    if old:
        payment = old
    else:
        connector = db.get(Connector, data.connector_id)
        if not connector:
            fail("not_found", "Ponto não encontrado", 404)
        require_gateway()
        replaced = None
        previous = db.scalar(
            select(Payment)
            .where(Payment.user_id == user.id, Payment.origin == "app", Payment.status.in_(PAYMENT_OPEN))
            .with_for_update()
        )
        if previous:
            refresh(db, previous, force=True)
            if previous.status in FUNDED:
                fail("payment_open_exists", "Você já tem um pagamento confirmado sem uso. Use-o ou cancele antes "
                     "de pagar outro.", 409)
            previous.status = "canceled"
            previous.last_error = "replaced"
            replaced = previous
            db.flush()  # libera o índice de um pagamento em aberto antes de inserir o novo
        fields = quote(db, user, connector, data)
        payment = Payment(user_id=user.id, connector_id=connector.id, origin="app", status="awaiting_payment",
                          expires_at=now() + timedelta(minutes=CHECKOUT_MINUTES), **fields)
        db.add(payment)
        db.flush()
        remember(db, user, "payment", key, body_hash, payment)
        db.commit()
        if replaced is not None:
            _expire_checkout(replaced)
    return ensure_checkout(
        db, payment, f"{base}/pay/return?p={payment.id}", f"{base}/pay/return?p={payment.id}&cancel=1"
    )


# ---------------------------------------------------------------------------- estado do provedor


def _charge(intent):
    charge = intent.get("latest_charge")
    return charge if isinstance(charge, dict) else {}


def _method(intent):
    details = _charge(intent).get("payment_method_details") or {}
    if details.get("type"):
        return details["type"]
    types = intent.get("payment_method_types") or []
    return types[0] if len(types) == 1 else None


def apply_intent(payment, intent):
    """Aplica o estado do PaymentIntent. Só avança: eventos fora de ordem não regridem o pagamento."""
    payment.provider_payment_intent_id = intent["id"]
    payment.provider_status = str(intent.get("status"))[:40]
    payment.method = _method(intent) or payment.method
    status = intent.get("status")
    if status in ("requires_capture", "succeeded"):
        received = int(intent.get("amount_received") or 0) if status == "succeeded" else 0
        if payment.status in PRE_START:
            payment.status = "authorized" if status == "requires_capture" else "paid"
            payment.authorized_at = now()
            payment.start_deadline = now() + start_window(payment)
            payment.captured_cents = received
        elif payment.status in ("expired", "canceled") and payment.settlement_status == "none":
            # Pagamento tardio (depois de expirar/cancelar): nada inicia e o valor volta inteiro.
            payment.captured_cents = received
            mark_zero_settlement(payment)
    elif status == "requires_payment_method" and intent.get("last_payment_error"):
        if payment.status == "awaiting_payment":
            payment.status = "declined"
    elif status == "canceled" and payment.status in FUNDED + PRE_START:
        # Autorização cancelada fora daqui (ex.: prazo da Stripe): nada foi cobrado.
        was_funded = payment.status in FUNDED
        payment.status = "expired"
        if was_funded and payment.settlement_status == "none":
            payment.charge_cents = 0
            payment.energy_cents = 0
            payment.settlement_status = "done"
            payment.settled_at = now()


def apply_checkout(payment, session, gateway):
    intent = session.get("payment_intent")
    if isinstance(intent, str):
        intent = gateway.retrieve_payment_intent(intent)
    if isinstance(intent, dict):
        apply_intent(payment, intent)
    elif session.get("status") == "expired" and payment.status in PRE_START:
        payment.status = "expired"


def refresh(db, payment, force=False, raise_errors=False):
    """Verificação no servidor (alternativa ao webhook), no máximo a cada 3 s por pagamento."""
    gateway = gateways.current()
    if gateway is None or not payment.provider_checkout_id:
        return payment
    recent = payment.last_provider_check_at and payment.last_provider_check_at > now() - timedelta(
        seconds=PROVIDER_CHECK_SECONDS)
    if recent and not force:
        return payment
    try:
        session = gateway.retrieve_checkout_session(payment.provider_checkout_id)
        apply_checkout(payment, session, gateway)
    except GatewayError:
        if raise_errors:
            raise
        return payment
    payment.last_provider_check_at = now()
    return payment


def expire_if_stale(db, payment):
    moment = now()
    if payment.status in PRE_START and payment.expires_at <= moment:
        refresh(db, payment, force=True)
        if payment.status in PRE_START:
            _expire_checkout(payment)
            payment.status = "expired"
    if (
        payment.status in FUNDED and payment.session_id is None
        and payment.start_deadline and payment.start_deadline <= moment
    ):
        payment.status = "expired"
        payment.last_error = payment.last_error or "start_deadline"
        mark_zero_settlement(payment)


# ---------------------------------------------------------------------------- acerto


def _fee(intent):
    transaction = _charge(intent).get("balance_transaction")
    return int(transaction["fee"]) if isinstance(transaction, dict) and transaction.get("fee") is not None else None


def settle(db, payment_id):
    """Executa o acerto marcado como devido: capture/cancel (cartão) ou refund (Pix).

    Reivindica o pagamento (``settling``) e faz commit antes de chamar a Stripe; repetir é seguro
    (chaves de idempotência e leitura do estado real do PaymentIntent antes de agir).
    """
    gateway = gateways.current()
    payment = db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update(skip_locked=True))
    if gateway is None or payment is None:
        return payment
    stale = payment.settlement_status == "settling" and payment.updated_at < now() - timedelta(
        seconds=SETTLING_STALE_SECONDS)
    if payment.settlement_status != "due" and not stale:
        return payment
    charge = payment.charge_cents or 0
    intent_id = payment.provider_payment_intent_id
    if not intent_id:
        _finish(payment, captured=0, refunded=0, fee=None)
        db.commit()
        return payment
    payment.settlement_status = "settling"
    payment.settle_attempts += 1
    attempts = payment.settle_attempts
    db.commit()
    try:
        intent = gateway.retrieve_payment_intent(intent_id)
        status = intent.get("status")
        if status == "requires_capture":
            if charge > 0:
                intent = gateway.capture(intent_id, charge, f"capture-{payment_id}")
                captured, refunded = charge, 0
            else:
                gateway.cancel(intent_id, f"cancel-{payment_id}")
                captured, refunded = 0, 0
        elif status == "succeeded":
            received = int(intent.get("amount_received") or 0)
            already = int(_charge(intent).get("amount_refunded") or 0)
            target = max(0, received - charge)
            if target > already:
                gateway.refund(intent_id, target - already, f"refund-{payment_id}-{target}")
            captured, refunded = received, target
        else:
            # Cancelada/não paga: nada foi cobrado; uma cobrança devida aqui não pode mais acontecer.
            captured, refunded = 0, 0
    except GatewayError as exc:
        payment = db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
        payment.last_error = f"settle: {exc.code}"[:200]
        payment.settlement_status = "failed" if attempts >= MAX_SETTLE_ATTEMPTS else "due"
        db.commit()
        return payment
    payment = db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
    if captured == 0 and charge > 0:
        payment.uncollected_cents += charge
        payment.charge_cents = 0
        payment.last_error = "authorization_unavailable"
    _finish(payment, captured=captured, refunded=refunded, fee=_fee(intent))
    db.commit()
    return payment


def _finish(payment, *, captured, refunded, fee):
    payment.captured_cents = captured
    payment.refunded_cents = refunded
    if fee is not None:
        payment.provider_fee_cents = fee
    payment.settlement_status = "done"
    payment.settled_at = now()
    if payment.status == "in_use":
        payment.status = "completed"
    if payment.charge_cents is None:
        payment.charge_cents = 0
    if payment.last_error and payment.last_error.startswith("settle:"):
        payment.last_error = None


def _needs_settle(payment):
    return payment.settlement_status == "due" or (
        payment.settlement_status == "settling"
        and payment.updated_at < now() - timedelta(seconds=SETTLING_STALE_SECONDS)
    )


# ---------------------------------------------------------------------------- painel físico


def guest_profile(db, connector):
    """Visitante do painel: um perfil por ponto (quem paga pelo QR sem o app)."""
    guest_id = uuid.uuid5(uuid.NAMESPACE_URL, f"chargegrid:kiosk:{connector.id}")
    db.execute(
        insert(Profile)
        .values(id=guest_id, name=f"Visitante do painel {connector.public_code}"[:100], account_type="consumer")
        .on_conflict_do_nothing()
    )
    return db.get(Profile, guest_id)


def start_kiosk(db, payment_id):
    """Pagamento do painel confirmado: emite START uma vez (presença provada ao pagar no QR)."""
    payment = db.get(Payment, payment_id)
    if payment is None or payment.origin != "kiosk" or payment.status not in FUNDED or payment.session_id:
        return payment
    guest = db.get(Profile, payment.user_id)
    connector = db.get(Connector, payment.connector_id)
    station = db.get(Station, connector.station_id)
    error = None
    for _ in range(2):  # o código #F pode virar entre gerar e conferir: tenta mais uma vez
        data = StartInput(public_code=connector.public_code, presence_code=current_code(station)[0],
                          max_duration_minutes=payment.max_duration_minutes, payment_id=payment.id)
        try:
            start(db, guest, data, f"kiosk:{payment.id}")
            db.commit()
            return db.get(Payment, payment_id)
        except HTTPException as exc:
            db.rollback()
            error = exc.detail.get("code") if isinstance(exc.detail, dict) else "start_failed"
            if error != "invalid_presence_code":
                break
    payment = db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
    if payment.status in FUNDED and payment.session_id is None:
        payment.last_error = f"kiosk_start: {error}"[:200]
        if error not in TRANSIENT_START_ERRORS:
            payment.status = "canceled"
            mark_zero_settlement(payment)
    db.commit()
    return payment


def kiosk_context(db, public_code, code_digits):
    """Ponto do QR, conferindo o código do painel (presença), a opção do vendedor e a Stripe."""
    connector = db.scalar(select(Connector).where(Connector.public_code == public_code))
    station = db.get(Station, connector.station_id) if connector else None
    if not connector or not station or not station.active or not connector.active or station.owner_id is None:
        fail("not_found", "Ponto não encontrado ou indisponível", 404)
    if not station.kiosk_payments:
        fail("kiosk_disabled", "Pagamento pelo painel desativado neste posto", 404)
    if not (code_digits or "").isdigit() or not valid_code(station, f"#F{code_digits}"):
        fail("invalid_presence_code", "Código do painel expirado. Escaneie o QR de novo.", 422)
    return connector, station


def create_kiosk_payment(db, public_code, code_digits, amount_cents, request_base=""):
    connector, station = kiosk_context(db, public_code, code_digits)
    require_gateway()
    if amount_cents not in KIOSK_AMOUNTS_CENTS:
        fail("invalid_amount", "Escolha um dos valores", 422)
    limit(db, f"kiosk:{connector.id}", maximum=10, seconds=300)
    connector = db.scalar(select(Connector).where(Connector.id == connector.id).with_for_update())
    if not free(db, connector):
        fail("point_unavailable", "Ponto em uso ou indisponível agora", 409)
    guest = guest_profile(db, connector)
    request = SimpleNamespace(mode="value", minutes=None, max_cost=billing.money(amount_cents), energy_kwh=None,
                              max_power_kw=None, coupon_code=None)
    fields = quote(db, guest, connector, request)
    token = secrets.token_urlsafe(24)
    payment = Payment(user_id=guest.id, connector_id=connector.id, origin="kiosk", status="awaiting_payment",
                      kiosk_token_hash=hashlib.sha256(token.encode()).hexdigest(),
                      expires_at=now() + timedelta(minutes=CHECKOUT_MINUTES), **fields)
    db.add(payment)
    db.flush()
    db.commit()
    base = public_base(request_base)
    status_url = f"{base}/pay/s/{payment.id}?t={token}"
    return ensure_checkout(db, payment, status_url, status_url + "&cancel=1"), token


def kiosk_payment(db, payment_id, token):
    payment = db.get(Payment, payment_id)
    expected = payment.kiosk_token_hash if payment else None
    if not expected or not token or not secrets.compare_digest(
        expected, hashlib.sha256(token.encode()).hexdigest()
    ):
        fail("not_found", "Pagamento não encontrado", 404)
    return payment


def kiosk_stop(db, payment):
    if not payment.session_id:
        return None
    guest = db.get(Profile, payment.user_id)
    return stop(db, guest, payment.session_id, f"kiosk-stop:{payment.session_id}")


# ---------------------------------------------------------------------------- avanço preguiçoso


def advance(db, payment_id):
    """Leva o pagamento ao estado atual: verifica o provedor, expira, inicia (painel) e acerta."""
    payment = db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
    if payment is None:
        return None
    if payment.status in PRE_START:
        refresh(db, payment)
    expire_if_stale(db, payment)
    if payment.session_id and payment.settlement_status == "none":
        session = db.get(ChargingSession, payment.session_id)
        if session.status not in SESSION_ACTIVE:
            prepare_settlement_for_session(db, session)
    db.commit()
    if payment.origin == "kiosk" and payment.status in FUNDED and payment.session_id is None:
        payment = start_kiosk(db, payment_id)
    if _needs_settle(payment):
        payment = settle(db, payment_id) or payment
    return db.get(Payment, payment_id)


def owned_payment(db, user, payment_id):
    payment = db.get(Payment, payment_id)
    if not payment or payment.user_id != user.id:
        fail("not_found", "Pagamento não encontrado", 404)
    return payment


def current_payment(db, user):
    payment = db.scalar(
        select(Payment)
        .where(Payment.user_id == user.id, Payment.origin == "app",
               Payment.status.in_((*PAYMENT_OPEN, "in_use")))
        .order_by(Payment.created_at.desc())
        .limit(1)
    )
    return advance(db, payment.id) if payment else None


def cancel_payment(db, user, payment_id):
    owned_payment(db, user, payment_id)
    payment = db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
    refresh(db, payment, force=True)
    if payment.status in PRE_START:
        _expire_checkout(payment)
        payment.status = "canceled"
    elif payment.status in FUNDED and payment.session_id is None:
        payment.status = "canceled"
        mark_zero_settlement(payment)
    elif payment.status not in ("canceled", "expired"):
        fail("payment_in_use", "O pagamento já está em uma recarga", 409)
    db.commit()
    return advance(db, payment_id)


def sweep(db, max_items=20):
    """Varredura de segurança (cron): expira, acerta e devolve o que ficou pendente."""
    moment = now()
    ended = select(ChargingSession.id).where(ChargingSession.status.not_in(SESSION_ACTIVE))
    ids = db.scalars(
        select(Payment.id)
        .where(or_(
            Payment.status.in_(PRE_START) & (Payment.expires_at <= moment),
            Payment.status.in_(FUNDED) & (Payment.start_deadline <= moment),
            Payment.settlement_status.in_(("due", "settling")),
            (Payment.status == "in_use") & (Payment.settlement_status == "none") & Payment.session_id.in_(ended),
        ))
        .order_by(Payment.created_at)
        .limit(max_items)
    ).all()
    db.commit()
    done = 0
    for payment_id in ids:
        try:
            advance(db, payment_id)
            done += 1
        except Exception:  # um pagamento com problema não impede os demais
            db.rollback()
    return done


# ---------------------------------------------------------------------------- webhook

HANDLED_EVENTS = (
    "checkout.session.completed", "checkout.session.async_payment_succeeded",
    "checkout.session.async_payment_failed", "checkout.session.expired",
    "payment_intent.amount_capturable_updated", "payment_intent.succeeded", "payment_intent.payment_failed",
    "payment_intent.canceled", "charge.refunded",
)


def _locate(db, obj):
    candidates = []
    payment_id = (obj.get("metadata") or {}).get("payment_id")
    try:
        if payment_id:
            candidates.append(Payment.id == uuid.UUID(str(payment_id)))
    except ValueError:
        pass
    kind = obj.get("object")
    if kind == "checkout.session" and obj.get("id"):
        candidates.append(Payment.provider_checkout_id == obj["id"])
    if kind == "payment_intent" and obj.get("id"):
        candidates.append(Payment.provider_payment_intent_id == obj["id"])
    if kind == "charge" and isinstance(obj.get("payment_intent"), str):
        candidates.append(Payment.provider_payment_intent_id == obj["payment_intent"])
    for condition in candidates:
        payment = db.scalar(select(Payment).where(condition).with_for_update())
        if payment:
            return payment
    return None


def handle_webhook(db, payload: bytes, signature: str):
    secret = settings().stripe_webhook_secret.strip()
    if not secret:
        fail("webhook_unconfigured", "Webhook da Stripe não configurado", 503)
    if not gateways.verify_signature(payload, signature or "", secret):
        fail("invalid_signature", "Assinatura do webhook inválida", 400)
    try:
        event = json.loads(payload)
        event_id, event_type = str(event["id"]), str(event.get("type") or "")
        obj = (event.get("data") or {}).get("object") or {}
    except (ValueError, KeyError, TypeError, AttributeError):
        fail("invalid_payload", "Evento inválido", 400)
    payment = _locate(db, obj) if isinstance(obj, dict) else None
    inserted = db.execute(
        insert(PaymentEvent)
        .values(provider="stripe", event_id=event_id[:100], type=event_type[:80],
                payment_id=payment.id if payment else None,
                payload_sha256=hashlib.sha256(payload).hexdigest())
        .on_conflict_do_nothing(index_elements=["provider", "event_id"])
        .returning(PaymentEvent.id)
    ).scalar()
    if inserted is None:
        return {"received": True, "duplicate": True}
    if payment and event_type in HANDLED_EVENTS:
        gateway = gateways.current()
        kind = obj.get("object")
        try:
            if kind == "payment_intent":
                apply_intent(payment, obj)
            elif kind == "checkout.session":
                if event_type == "checkout.session.expired":
                    if payment.status in PRE_START:
                        payment.status = "expired"
                elif gateway is not None:
                    apply_checkout(payment, obj, gateway)
        except GatewayError:
            # Sem o estado real não dá para confirmar: a Stripe repete o evento (não grava nada).
            db.rollback()
            fail("provider_unavailable", "Stripe indisponível; tente novamente", 503)
    db.commit()
    if payment:
        try:
            advance(db, payment.id)
        except Exception:
            db.rollback()  # o evento já foi aplicado; a varredura/leitura seguinte conclui
    return {"received": True}
