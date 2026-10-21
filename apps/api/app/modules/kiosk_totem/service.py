"""Totem de autoatendimento no painel físico: compra sem celular, do ponto da chave do dispositivo.

Endpoints finos (contrato em ``docs/esp32-protocol.md`` · Totem 0.8.0). Nada de regra própria de
preço, início ou acerto: o orçamento é ``payments.service.quote`` (termos travados, motivo da
demanda, reserva da taxa de permanência), o início é ``payments.service.start_kiosk`` →
``charging.service.start`` com o perfil convidado do ponto (``guest_profile``), o encerramento é
local no painel e o recibo vem de ``receipts.service``.

O método de pagamento é decidido aqui, pelo modo da conta do **dono** do posto
(``profiles.presentation_mode``): Modo apresentação → ``simulated`` (pago na hora, acerto local,
nenhuma chamada à Stripe); conta oficial → ``stripe`` (QR do pedido → Checkout hospedada). O
dispositivo nunca escolhe.

Pedido aberto (``held``/``awaiting_payment``/``paid``) trava o ponto até ``expires_at``: a
disponibilidade (``service.availability``) o vê ocupado e app/reserva recebem
``point_unavailable`` com ``reason: "kiosk_in_use"``. Trava vencida não conta mais; o pedido
vira ``expired`` no próximo contato (``refresh_order``, só banco).
"""

import base64
import hashlib
import hmac
import json
import secrets
import uuid
from datetime import timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select

from chargegrid_core import billing, pricing
from chargegrid_core.receipt import END_REASONS

from ... import overstay
from ...errors import fail
from ...models import (
    KIOSK_ORDER_OPEN,
    ChargingSession,
    Connector,
    KioskOrder,
    Payment,
    Profile,
    Station,
    now,
)
from ...service import SESSION_ACTIVE, availability, fail_unavailable, idempotent, lock_point, remember
from ..charging.service import session_power_limit
from ..payments import gateway as gateways
from ..payments import service as payments
from ..payments.funding import FUNDED, PRE_START, mark_zero_settlement, start_window, status_label
from ..pricing.service import locked_terms

MAX_TOTAL_CENTS = 20000  # teto por pedido: total pré-autorizado (energia + reserva da permanência)
HOLD_MINUTES = 5
QR_HOLD_MINUTES = 10
VISIBLE_AFTER_CLOSE = timedelta(minutes=10)
START_TIMEOUT_SECONDS = 60
SHORTCUTS = {"value": (1000, 2000, 4000, 6000), "time": (15, 30, 60),
             "energy": (Decimal("5.0"), Decimal("10.0"), Decimal("20.0"))}
MIN_VALUE_CENTS = 500
MIN_MINUTES = 5
MIN_ENERGY_KWH = Decimal("1.0")
KWH_STEP = Decimal("0.1")
LABELS = {"simulated": "SIMULADO", "stripe": "TESTE"}
RESERVED_METHODS = ("voucher", "card_terminal")  # voucher do caixa e maquininha física: ocultos
STATUS_LABELS = {
    "held": "Pedido aceito · aguardando pagamento",
    "awaiting_payment": "Aguardando pagamento (QR)",
    "paid": "Pagamento confirmado · iniciando",
    "charging": "Recarga em andamento",
    "finished": "Recarga encerrada",
    "canceled": "Pedido cancelado",
    "expired": "Pedido expirado",
    "failed": "Não foi possível iniciar; valor devolvido",
}
REASON_LABELS = {
    "payments_unavailable": "Pagamento indisponível: Stripe (teste) não configurada",
    "point_disabled": "Ponto desativado",
    "kiosk_in_use": "Ponto em uso no totem",
    "reserved": "Ponto reservado",
    "charging": "Recarga em andamento",
    "occupied": "Ponto ocupado",
    "reconciling": "Ponto sincronizando",
    "offline": "Ponto sem conexão",
    "fault": "Ponto em manutenção",
    "disabled": "Ponto desativado",
}
ERRORS = {
    "failed": ("kiosk_start", "Não foi possível iniciar; valor devolvido"),
    "expired": ("hold_expired", "Tempo esgotado; nada foi cobrado"),
    "method_changed": ("method_changed", "O modo de pagamento do posto mudou; refaça o pedido"),
}


def _iso(value):
    return value.isoformat() if value else None


def _money(cents):
    return str(billing.money(cents))


def _plain(value):
    """Decimal → texto (JSONB sem perder casas); o resto como está."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def public_base(request_base=""):
    return payments.public_base(request_base)


# ---------------------------------------------------------------------------- ponto e método


def point(db, device):
    """Ponto da chave do dispositivo; totem desligado no posto → 404 (firmware: totem desligado)."""
    connector = db.get(Connector, device.connector_id)
    station = db.get(Station, connector.station_id) if connector else None
    if not connector or not station or not station.kiosk_mode:
        fail("kiosk_disabled", "Totem de autoatendimento desligado neste posto", 404)
    return connector, station


def _decide(active, presentation):
    if not active:
        return None, "point_disabled"
    if presentation:
        return "simulated", None
    if gateways.current() is not None:
        return "stripe", None
    return None, "payments_unavailable"


def method_for(db, station, connector):
    """``(método, motivo)`` decididos pelo servidor a partir do modo da conta do dono."""
    if not station.active or not connector.active or station.owner_id is None:
        return None, "point_disabled"
    owner = db.get(Profile, station.owner_id)
    return _decide(True, owner is not None and bool(owner.presentation_mode))


def station_status(station, owner):
    """``kiosk_status`` do posto na visão do dono (``GET/PATCH /stations``): o método que o totem usa
    (ou usaria, com ``kiosk_mode`` desligado) e o motivo de indisponível, pela mesma regra do
    ``connector.kiosk`` do sync, para app e painel web não deduzirem. ``owner``: perfil do dono."""
    method, reason = _decide(bool(station.active) and station.owner_id is not None,
                             bool(getattr(owner, "presentation_mode", False)))
    return {"method": method, "label": LABELS.get(method), "reason": reason,
            "reason_label": REASON_LABELS.get(reason)}


def require_method(db, station, connector):
    method, reason = method_for(db, station, connector)
    if reason == "payments_unavailable":
        fail("payments_unavailable", REASON_LABELS[reason], 503)
    if method is None:
        fail("point_unavailable", REASON_LABELS[reason], 409, reason="disabled")
    return method


def connector_block(db, connector, station):
    """``connector.kiosk`` do sync (só com o totem ligado no posto)."""
    method, reason = method_for(db, station, connector)
    return {"enabled": method is not None, "method": method, "label": LABELS.get(method), "reason": reason}


# ---------------------------------------------------------------------------- oferta e orçamento


def _terms(db, connector):
    base, multiplier, terms = locked_terms(db, connector, None)
    return base, multiplier, terms, pricing.dynamic_price(base, multiplier)


def _demand(terms, multiplier):
    demand = terms.get("demand") or {}
    increase = int(((Decimal(multiplier) - 1) * 100).to_integral_value(rounding=ROUND_HALF_UP))
    return {"reason_label": demand.get("reason_label"), "level_label": demand.get("level_label"),
            "increase_percent": increase}


def _limits(connector, price, power, reserve_cents):
    """Máximos por modo para o total caber no teto de R$ 200 (o orçamento confere de novo)."""
    value_max = max(0, MAX_TOTAL_CENTS - reserve_cents)
    reais = Decimal(value_max) / 100
    if price > 0:
        energy_max = (reais / price).quantize(KWH_STEP, rounding=ROUND_DOWN)
        minutes = int((reais / (price * power) * 60).to_integral_value(rounding=ROUND_DOWN)) if power > 0 else 0
    else:
        energy_max, minutes = Decimal(1000), connector.max_duration_minutes
    return value_max, min(energy_max, Decimal(1000)), max(0, min(connector.max_duration_minutes, minutes))


def offer(db, device):
    connector, station = point(db, device)
    method, reason = method_for(db, station, connector)
    base, multiplier, terms, price = _terms(db, connector)
    power = session_power_limit(db, connector) or Decimal(connector.power_kw)
    reserve = int(overstay.payment_terms(station)["reserve_cents"] or 0)
    value_max, energy_max, time_max = _limits(connector, price, power, reserve)
    state = availability(db, connector)
    busy = None if state["available"] else ("kiosk_in_use" if state["kiosk_in_use"] else state["availability_status"])
    open_order = _open_order(db, connector.id) if busy == "kiosk_in_use" else None
    why = reason or busy
    return {
        "enabled": method is not None,
        "available": state["available"],
        "reason": why,
        "reason_label": REASON_LABELS.get(why) if why else None,
        "open_order_id": str(open_order.id) if open_order else None,
        "method": method,
        "label": LABELS.get(method),
        "currency": billing.CURRENCY,
        "public_code": connector.public_code,
        "power_kw": str(Decimal(power).quantize(Decimal("0.001"))),
        "price": {"price_per_kwh": str(price.quantize(Decimal("0.0001"))),
                  "base_price_per_kwh": str(Decimal(base).quantize(Decimal("0.0001"))),
                  "demand_multiplier": str(Decimal(multiplier).quantize(Decimal("0.01"))),
                  **_demand(terms, multiplier)},
        "limits": {"max_total": _money(MAX_TOTAL_CENTS), "overstay_reserve": _money(reserve)},
        "modes": {
            "value": {"shortcuts": [_money(cents) for cents in SHORTCUTS["value"] if cents <= value_max],
                      "min": _money(MIN_VALUE_CENTS), "max": _money(value_max)},
            "time": {"shortcuts": [minutes for minutes in SHORTCUTS["time"] if minutes <= time_max],
                     "min": MIN_MINUTES, "max": time_max},
            "energy": {"shortcuts": [str(kwh) for kwh in SHORTCUTS["energy"] if kwh <= energy_max],
                       "min": str(MIN_ENERGY_KWH), "max": str(energy_max), "decimals": 1},
        },
        "overstay": overstay.public_terms(station),
        "hold_minutes": HOLD_MINUTES,
        "qr_hold_minutes": QR_HOLD_MINUTES,
        "start_timeout_seconds": START_TIMEOUT_SECONDS,
    }


def _normalized(data, connector):
    """Só o campo do modo escolhido vale; mínimos do totem e duração máxima do ponto."""
    amount = minutes = energy = None
    if data.mode == "value":
        if data.amount is None:
            fail("invalid_quote", "Informe o valor", 422)
        amount = Decimal(data.amount).quantize(billing.CENT)
        if billing.to_cents(amount) < MIN_VALUE_CENTS:
            fail("amount_below_minimum", f"O valor mínimo é {billing.format_money(MIN_VALUE_CENTS)}", 422)
    elif data.mode == "time":
        if data.minutes is None:
            fail("invalid_quote", "Informe o tempo em minutos", 422)
        minutes = int(data.minutes)
        if minutes < MIN_MINUTES:
            fail("amount_below_minimum", f"O tempo mínimo é {MIN_MINUTES} min", 422)
        if minutes > connector.max_duration_minutes:
            fail("amount_above_limit", f"O tempo máximo deste ponto é {connector.max_duration_minutes} min", 422)
    else:
        if data.energy_kwh is None:
            fail("invalid_quote", "Informe a energia em kWh", 422)
        energy = Decimal(data.energy_kwh).quantize(KWH_STEP)
        if energy < MIN_ENERGY_KWH:
            fail("amount_below_minimum", "A energia mínima é 1,0 kWh", 422)
    return amount, minutes, energy


def compute_quote(db, connector, station, guest, data, method):
    """``(campos do pagamento, resposta)``: o mesmo ``payments.service.quote`` do app, com o convidado."""
    amount, minutes, energy = _normalized(data, connector)
    request = SimpleNamespace(mode=data.mode, minutes=minutes, max_cost=amount, energy_kwh=energy,
                              max_power_kw=None, coupon_code=None)
    fields = payments.quote(db, guest, connector, request)
    if fields["amount_cents"] > MAX_TOTAL_CENTS:
        fail("amount_above_limit", f"O total passa do limite do totem ({billing.format_money(MAX_TOTAL_CENTS)})", 422)
    detail = fields["quote"]
    public = overstay.public_terms(station)
    material = {
        "connector": str(connector.id), "method": method, "mode": data.mode, "amount": str(amount),
        "minutes": minutes, "energy_kwh": str(energy), "amount_cents": fields["amount_cents"],
        "energy_cap_cents": fields["energy_cap_cents"], "reserve_cents": fields["overstay_reserve_cents"],
        "price": str(fields["price_per_kwh"]), "base": str(fields["base_price_per_kwh"]),
        "multiplier": str(fields["demand_multiplier"]), "discount": fields["discount_percent"],
        "max_minutes": fields["max_duration_minutes"], "estimate": detail["energy_kwh"],
        "power": detail["power_kw"], "overstay": public.get("version"),
    }
    quote_hash = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()[:32]
    demand = detail["price_terms"].get("demand") or {}
    view = {
        "quote_hash": quote_hash,
        "mode": data.mode,
        "amount": str(amount) if amount is not None else None,
        "minutes": minutes,
        "energy_kwh": str(energy) if energy is not None else None,
        "total": _money(fields["amount_cents"]),
        "energy_cap": _money(fields["energy_cap_cents"]),
        "overstay_reserve": _money(fields["overstay_reserve_cents"]),
        "price_per_kwh": str(Decimal(fields["price_per_kwh"]).quantize(Decimal("0.0001"))),
        "base_price_per_kwh": str(Decimal(fields["base_price_per_kwh"]).quantize(Decimal("0.0001"))),
        "demand_multiplier": str(Decimal(fields["demand_multiplier"]).quantize(Decimal("0.01"))),
        "discount_percent": fields["discount_percent"],
        "demand": {"multiplier": demand.get("multiplier"), "level_label": demand.get("level_label"),
                   "reason_label": demand.get("reason_label")},
        "estimated_energy_kwh": detail["energy_kwh"],
        "max_duration_minutes": fields["max_duration_minutes"],
        "power_kw": detail["power_kw"],
        "overstay": public,
        "method": method,
        "label": LABELS.get(method),
    }
    return fields, view


def quote(db, device, data):
    connector, station = point(db, device)
    method = require_method(db, station, connector)
    guest = payments.guest_profile(db, connector)
    return compute_quote(db, connector, station, guest, data, method)[1]


# ---------------------------------------------------------------------------- pedido e trava


def order_token(db, order):
    """Token do recibo/QR do visitante (24 bytes, base64url sem preenchimento).

    Derivado por HMAC de um segredo do posto que nunca sai do servidor e do sal aleatório do
    pedido; o banco guarda só o sal e o SHA-256. Só os endpoints do dispositivo o devolvem.
    """
    station = db.get(Station, db.get(Connector, order.connector_id).station_id)
    message = b"chargegrid:kiosk-order:" + order.id.bytes + bytes.fromhex(order.token_salt)
    digest = hmac.new(bytes.fromhex(station.presence_secret), message, hashlib.sha256).digest()[:24]
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def order_by_token(db, order_id, token):
    order = db.get(KioskOrder, order_id)
    if order is None or not token or not secrets.compare_digest(order.token_hash, _token_hash(token)):
        fail("not_found", "Pedido não encontrado", 404)
    return order


def _open_order(db, connector_id):
    return db.scalar(
        select(KioskOrder).where(KioskOrder.connector_id == connector_id, KioskOrder.status.in_(KIOSK_ORDER_OPEN))
    )


def order_for_payment(db, payment_id):
    return db.scalar(select(KioskOrder).where(KioskOrder.payment_id == payment_id))


def own_order(db, device, order_id):
    order = db.get(KioskOrder, order_id)
    if order is None or order.connector_id != device.connector_id:
        fail("not_found", "Pedido não encontrado", 404)
    return order


def _locked(db, model, identifier):
    return db.scalar(
        select(model).where(model.id == identifier).with_for_update().execution_options(populate_existing=True)
    )


def _close(order, status, error=None):
    order.status = status
    order.closed_at = now()
    order.expires_at = None
    if error:
        order.last_error = error[:200]


def on_started(order, session):
    """START emitido para o pagamento do pedido: a sessão assume a ocupação do ponto."""
    order.status = "charging"
    order.session_id = session.id
    order.expires_at = None
    order.last_error = None


def may_start(order, payment):
    """O pagamento do pedido ainda pode virar recarga (pedido aberto e pago dentro da trava)."""
    if order.status not in KIOSK_ORDER_OPEN:
        return False
    if order.status == "paid":
        return True
    return bool(order.expires_at and (order.expires_at > now()
                                      or (payment.authorized_at and payment.authorized_at <= order.expires_at)))


def refresh_order(db, order):
    """Leva o pedido ao estado atual a partir do pagamento e da sessão (só banco, sem Stripe)."""
    moment = now()
    payment = db.get(Payment, order.payment_id) if order.payment_id else None
    if order.status in KIOSK_ORDER_OPEN:
        if payment is not None and payment.session_id:
            on_started(order, db.get(ChargingSession, payment.session_id))
        elif payment is not None and payment.status in FUNDED:
            in_time = may_start(order, payment)
            if in_time and order.status != "paid":
                order.status = "paid"
                order.expires_at = payment.start_deadline or moment + start_window(payment)
            if not in_time:
                # Pago depois de a trava vencer: nada inicia e o valor volta inteiro.
                payment = _locked(db, Payment, payment.id)
                if payment.status in FUNDED and payment.session_id is None:
                    payment.status = "canceled"
                    payment.last_error = "kiosk_hold_expired"
                    mark_zero_settlement(payment)
                _close(order, "expired", "kiosk_hold_expired")
            elif order.expires_at <= moment:
                payment = _locked(db, Payment, payment.id)
                payments.expire_if_stale(db, payment)  # prazo de início vencido: devolve (só banco)
                if payment.status not in FUNDED:
                    _close(order, "failed", payment.last_error or "start_deadline")
        elif payment is not None and payment.status not in PRE_START:
            # Cancelado/expirado sem recarga (ex.: START recusado em definitivo): devolvido.
            _close(order, "failed" if payment.authorized_at else "canceled", payment.last_error)
        elif order.expires_at is not None and order.expires_at <= moment:
            if payment is not None:
                payment = _locked(db, Payment, payment.id)
                if payment.status in PRE_START:
                    payment.status = "canceled"  # a Checkout pode seguir aberta: pagamento tardio é devolvido
                    payment.last_error = "kiosk_hold_expired"
            _close(order, "expired", "kiosk_hold_expired")
    if order.status == "charging":
        session = db.get(ChargingSession, order.session_id)
        if session is not None and session.status not in SESSION_ACTIVE:
            order.status = "finished"
            order.closed_at = session.ended_at or moment
    return order


def expire_stale(db, connector_id):
    for order in db.scalars(
        select(KioskOrder)
        .where(KioskOrder.connector_id == connector_id, KioskOrder.status.in_(KIOSK_ORDER_OPEN))
        .with_for_update()
    ).all():
        refresh_order(db, order)


def create_order(db, device, data, key):
    connector, station = point(db, device)
    guest = payments.guest_profile(db, connector)
    # Mesma trava do START (perfil → ponto): pedido e início nunca correm juntos.
    connector = lock_point(db, guest, connector.id)
    old, body_hash = idempotent(db, guest, "kiosk_order", key, data.model_dump(mode="json"), KioskOrder)
    if old is not None:
        return refresh_order(db, old)
    method = require_method(db, station, connector)
    expire_stale(db, connector.id)
    current = _open_order(db, connector.id)
    if current is not None:
        fail("order_open", "Já existe um pedido do totem aberto neste ponto", 409, order_id=str(current.id))
    if data.overstay_terms_version != overstay.public_terms(station).get("version"):
        fail("overstay_terms_changed", "As condições da taxa de permanência mudaram. Revise e confirme de novo.", 409)
    state = availability(db, connector)
    if not state["available"]:
        fail_unavailable(state, db=db, connector=connector)
    fields, view = compute_quote(db, connector, station, guest, data, method)
    if not secrets.compare_digest(view["quote_hash"], data.quote_hash):
        fail("quote_changed", "O orçamento mudou. Revise os novos valores.", 409, quote=view)
    order = KioskOrder(
        id=uuid.uuid4(), connector_id=connector.id, guest_id=guest.id, status="held", method=method,
        mode=data.mode, quote={"fields": _plain(fields), "view": view}, quote_hash=view["quote_hash"],
        expires_at=now() + timedelta(minutes=HOLD_MINUTES), token_salt=secrets.token_hex(16), token_hash="",
    )
    order.token_hash = _token_hash(order_token(db, order))
    db.add(order)
    db.flush()
    remember(db, guest, "kiosk_order", key, body_hash, order)
    return order


def _payment_fields(order):
    """Campos do ``Payment`` com os termos travados ao aceitar o pedido."""
    fields = dict(order.quote["fields"])
    for name in ("price_per_kwh", "base_price_per_kwh", "demand_multiplier"):
        fields[name] = Decimal(fields[name])
    if fields.get("max_power_kw") is not None:
        fields["max_power_kw"] = Decimal(fields["max_power_kw"])
    return fields


def _return_url(db, order, base):
    return f"{base}/pay/r/{order.id}?t={order_token(db, order)}"


def _open_checkout(db, order, payment, base):
    """Checkout hospedada do pedido (idempotente); o retorno é a página do recibo do visitante."""
    url = _return_url(db, order, base)
    payments.ensure_checkout(db, payment, url, url + "&cancel=1")
    order = _locked(db, KioskOrder, order.id)
    if order.status == "held":
        order.status = "awaiting_payment"
    db.commit()
    return order


def pay(db, device, order_id, data, key, request_base=""):
    connector, station = point(db, device)
    order = own_order(db, device, order_id)
    guest = db.get(Profile, order.guest_id)
    lock_point(db, guest, connector.id)
    order = _locked(db, KioskOrder, order.id)
    old, body_hash = idempotent(db, guest, f"kiosk_pay:{order.id}", key, data.model_dump(), KioskOrder)
    base = public_base(request_base)
    if old is not None:
        payment = db.get(Payment, order.payment_id) if order.payment_id else None
        if payment is not None and payment.provider == "stripe" and payment.status in PRE_START \
                and not payment.checkout_url and order.status in ("held", "awaiting_payment"):
            return _open_checkout(db, order, payment, base)  # repetição depois de falha da Stripe
        return refresh_order(db, order)
    if data.method in RESERVED_METHODS:
        fail("method_unavailable", "Método de pagamento indisponível neste totem", 409)
    refresh_order(db, order)
    if order.status == "expired":
        db.commit()
        fail("order_expired", "Tempo esgotado. Comece de novo.", 409)
    if order.status not in ("held", "awaiting_payment"):
        fail("order_not_payable", "Este pedido não aceita pagamento agora", 409)
    method = require_method(db, station, connector)
    if data.method is not None and data.method != method:
        fail("method_mismatch", "O método de pagamento é definido pelo posto", 409)
    if method != order.method:
        payment = db.get(Payment, order.payment_id) if order.payment_id else None
        if payment is None or payment.status in PRE_START:
            if payment is not None:
                payment.status = "canceled"
            _close(order, "canceled", "method_changed")
            db.commit()
            fail("method_changed", ERRORS["method_changed"][1], 409)
    if order.payment_id is not None:  # QR já emitido: devolve o mesmo pedido
        remember(db, guest, f"kiosk_pay:{order.id}", key, body_hash, order)
        return order
    moment = now()
    if method == "simulated":
        payment = Payment(id=uuid.uuid4(), user_id=guest.id, connector_id=connector.id, origin="kiosk",
                          provider=payments.SIMULATED, method=payments.SIMULATED, status="paid",
                          authorized_at=moment, captured_cents=0, expires_at=moment, **_payment_fields(order))
        payment.start_deadline = moment + start_window(payment)
        db.add(payment)
        db.flush()
        order.payment_id = payment.id
        order.status = "paid"
        order.expires_at = payment.start_deadline
        remember(db, guest, f"kiosk_pay:{order.id}", key, body_hash, order)
        db.commit()
        payments.start_kiosk(db, payment.id)  # START uma única vez (idempotente por pagamento)
        order = _locked(db, KioskOrder, order.id)
        refresh_order(db, order)
        db.commit()
        return order
    payments.require_gateway()
    payment = Payment(id=uuid.uuid4(), user_id=guest.id, connector_id=connector.id, origin="kiosk",
                      provider="stripe", status="awaiting_payment",
                      expires_at=moment + timedelta(minutes=payments.CHECKOUT_MINUTES), **_payment_fields(order))
    db.add(payment)
    db.flush()
    order.payment_id = payment.id
    order.expires_at = moment + timedelta(minutes=QR_HOLD_MINUTES)
    remember(db, guest, f"kiosk_pay:{order.id}", key, body_hash, order)
    db.commit()
    return _open_checkout(db, order, payment, base)


def cancel(db, device, order_id):
    connector, _ = point(db, device)
    order = own_order(db, device, order_id)
    guest = db.get(Profile, order.guest_id)
    lock_point(db, guest, connector.id)
    order = _locked(db, KioskOrder, order.id)
    refresh_order(db, order)
    if order.status in ("charging", "finished"):
        fail("order_in_use", "A recarga já começou; use Encerrar", 409)
    payment, checkout_open = None, False
    if order.status in KIOSK_ORDER_OPEN:
        if order.payment_id:
            payment = _locked(db, Payment, order.payment_id)
            if payment.status in PRE_START:
                checkout_open = True
                payment.status = "canceled"
                payment.last_error = "kiosk_canceled"
            elif payment.status in FUNDED and payment.session_id is None:
                payment.status = "canceled"
                payment.last_error = "kiosk_canceled"
                mark_zero_settlement(payment)
        _close(order, "canceled")
    db.commit()
    if payment is not None:
        if checkout_open:
            payments.expire_checkout(payment)  # fora da trava; pagamento tardio é devolvido inteiro
        payments.advance(db, payment.id)  # libera a autorização / devolve (simulado: acerto local)
    return order


def get_order(db, device, order_id):
    order = own_order(db, device, order_id)
    if order.payment_id:
        payments.advance(db, order.payment_id)  # Stripe no máximo a cada 3 s; START e acerto pendentes
    order = _locked(db, KioskOrder, order.id)
    refresh_order(db, order)
    if order.status == "held":
        order.expires_at = max(order.expires_at, now() + timedelta(minutes=HOLD_MINUTES))  # renova a trava
    db.commit()
    return order


# ---------------------------------------------------------------------------- representação


def _payment_view(db, order, payment, base):
    if payment is None:
        return None
    qr = None
    if order.status == "awaiting_payment" and payment.status in PRE_START and payment.checkout_url and base:
        qr = f"{base}/pay/o/{order.id}?t={order_token(db, order)}"
    return {"id": str(payment.id), "status": payment.status, "label": status_label(payment),
            "method": order.method, "amount": _money(payment.amount_cents), "qr_url": qr}


def _receipt_view(session, payment, url):
    if session is None:
        return None
    settled = payment is not None and payment.settlement_status == "done" and payment.charge_cents is not None
    if settled:
        total = _money(payment.charge_cents)
        returned = _money(payment.amount_cents - payment.charge_cents)
        kind = "simulated" if payment.provider == payments.SIMULATED else (
            "refunded" if payment.refunded_cents or payment.method == "pix" else "released")
    else:
        estimate = Decimal(session.cost_estimate or 0) + Decimal(session.overstay_fee or 0)
        total, returned, kind = str(estimate.quantize(billing.CENT, rounding=ROUND_HALF_UP)), None, None
    return {
        "number": str(session.id).replace("-", "")[:8].upper(),
        "energy_kwh": str((Decimal(session.energy_wh or 0) / 1000).quantize(Decimal("0.001"))),
        "total": total,
        "returned": returned,
        "return_kind": kind,
        "final": session.status not in SESSION_ACTIVE and (payment is None or settled),
        "end_reason": session.end_reason,
        "end_reason_label": END_REASONS.get(session.end_reason, session.end_reason),
        "url": url,
    }


def _error_view(order):
    key = order.last_error if order.last_error in ERRORS else order.status
    if order.status in ("failed", "expired") or key == "method_changed":
        code, message = ERRORS[key]
        return {"code": code, "message": message}
    return None


def _expiry(order):
    if order.status not in KIOSK_ORDER_OPEN or order.expires_at is None:
        return None, None
    return _iso(order.expires_at), max(0, int((order.expires_at - now()).total_seconds()))


def sync_view(db, order, base):
    """Bloco ``kiosk_order`` do sync (e base da resposta dos endpoints)."""
    payment = db.get(Payment, order.payment_id) if order.payment_id else None
    session = db.get(ChargingSession, order.session_id) if order.session_id else None
    receipt_url = _return_url(db, order, base) if base else None
    expires_at, remaining = _expiry(order)
    return {
        "id": str(order.id),
        "status": order.status,
        "status_label": STATUS_LABELS[order.status],
        "expires_at": expires_at,
        "expires_in_seconds": remaining,
        "session_id": str(order.session_id) if order.session_id else None,
        "payment": _payment_view(db, order, payment, base),
        "receipt": _receipt_view(session, payment, receipt_url),
        "error": _error_view(order),
    }


def order_view(db, order, request_base=""):
    base = public_base(request_base)
    view = sync_view(db, order, base)
    session = db.get(ChargingSession, order.session_id) if order.session_id else None
    saved = order.quote.get("view") or {}
    return {
        **{key: view[key] for key in ("id", "status", "status_label")},
        "method": order.method,
        "label": LABELS.get(order.method),
        "expires_at": view["expires_at"],
        "expires_in_seconds": view["expires_in_seconds"],
        "quote": {key: saved.get(key) for key in ("mode", "amount", "minutes", "energy_kwh", "total", "energy_cap",
                                                  "overstay_reserve", "price_per_kwh", "estimated_energy_kwh",
                                                  "max_duration_minutes")},
        "payment": view["payment"],
        "session_id": view["session_id"],
        "session": {
            "status": session.status,
            "energy_kwh": str((Decimal(session.energy_wh or 0) / 1000).quantize(Decimal("0.001"))),
            "cost": str(Decimal(session.cost_estimate or 0).quantize(billing.CENT, rounding=ROUND_HALF_UP)),
            "started_at": _iso(session.started_at),
            "ended_at": _iso(session.ended_at),
            "end_reason": session.end_reason,
        } if session else None,
        "receipt": view["receipt"],
        "receipt_url": _return_url(db, order, base) if base else None,
        "error": view["error"],
    }


# ---------------------------------------------------------------------------- sync


def sync_blocks(db, connector, station):
    """``connector.kiosk`` e ``kiosk_order`` do sync (``None`` com o totem desligado no posto).

    Avança só o pedido mais recente deste ponto, sem chamar a Stripe (o sync segura a trava do ponto).
    """
    if not station.kiosk_mode:
        return None
    order = db.scalar(
        select(KioskOrder).where(KioskOrder.connector_id == connector.id)
        .order_by(KioskOrder.created_at.desc()).limit(1)
    )
    if order is not None:
        refresh_order(db, order)
        moment = now()
        if order.status not in (*KIOSK_ORDER_OPEN, "charging") and (
            order.closed_at is None or order.closed_at <= moment - VISIBLE_AFTER_CLOSE
        ):
            order = None
    return {
        "kiosk": connector_block(db, connector, station),
        "order": sync_view(db, order, public_base()) if order is not None else None,
        "open": order is not None and order.status in KIOSK_ORDER_OPEN,
    }


def after_sync(db, connector_id):
    """Depois de gravar o sync (fora da trava do ponto): verificação na Stripe (≤ 1 a cada 3 s),
    START do pagamento confirmado e acerto devido do pedido mais recente. Devolve o bloco novo ou None."""
    connector = db.get(Connector, connector_id)
    station = db.get(Station, connector.station_id) if connector else None
    if station is None or not station.kiosk_mode:
        return None
    order = db.scalar(
        select(KioskOrder).where(KioskOrder.connector_id == connector_id, KioskOrder.payment_id.is_not(None))
        .order_by(KioskOrder.created_at.desc()).limit(1)
    )
    if order is None:
        return None
    payment = db.get(Payment, order.payment_id)
    waiting = order.status in KIOSK_ORDER_OPEN and payment.session_id is None and (
        (payment.status in PRE_START and payment.provider_checkout_id) or payment.status in FUNDED)
    if not waiting and not payments.needs_settle(payment):
        return None
    try:
        payments.advance(db, payment.id)
    except HTTPException:
        db.rollback()
        return None
    order = _locked(db, KioskOrder, order.id)
    refresh_order(db, order)
    db.commit()
    return sync_view(db, order, public_base())


def session_origin(db, session):
    """``authorized.session.origin``: ``app``, ``kiosk_qr`` (QR /pay/k) ou ``kiosk_totem``."""
    row = db.execute(
        select(Payment.origin, KioskOrder.id)
        .outerjoin(KioskOrder, KioskOrder.payment_id == Payment.id)
        .where(Payment.session_id == session.id)
    ).first()
    if row is None or row[0] != "kiosk":
        return "app"
    return "kiosk_totem" if row[1] is not None else "kiosk_qr"
