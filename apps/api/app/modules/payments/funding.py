"""Partes do pagamento que só tocam o banco (usadas no START e no sync do equipamento).

Nada aqui chama a Stripe: o sync do equipamento e o START nunca esperam o provedor.

* START: ``claim_for_start`` exige/valida o pagamento sob trava (perfil → ponto → pagamento),
  ``funded_input``/``locked_terms``/``payment_price_terms`` aplicam o teto, os termos travados e a
  explicação do preço do recibo, ``attach_payment`` liga a sessão.
* Fim da recarga: ``prepare_settlement_for_session`` calcula o acerto (energia confirmada,
  permanência, mínimo do provedor) e marca ``settlement_status = due``; a chamada à Stripe é feita
  depois, fora da trava do ponto (``service.settle``).
* Sync: ``prepare_recent_settlements`` e ``device_fields`` (QR de pagamento do painel).
"""

from datetime import timedelta
from decimal import Decimal
from urllib.parse import quote

from sqlalchemy import select

from chargegrid_core import billing

from ...config import settings
from ...errors import fail
from ...models import PAYMENT_OPEN, ChargingSession, KioskOrder, Payment, Station, now
from ...presence_code import current_code
from ...service import SESSION_ACTIVE, active_hold, active_res, active_session
from . import gateway as gateways
from .overstay import overstay_charge

PRE_START = ("awaiting_payment", "declined")
FUNDED = ("authorized", "paid")
KIOSK_PAYMENT_VISIBLE_MINUTES = 35


def claim_for_start(db, user, connector, payment_id, power_tier="max", reservation=None):
    """Pagamento que financia este START (ou ``None`` quando o posto não exige)."""
    if payment_id is None:
        station = db.get(Station, connector.station_id)
        if station.prepay_required:
            from ..pricing.service import locked_terms as current_price_terms

            base, _, _ = current_price_terms(db, connector, reservation, power_tier)
            if base > 0:
                fail("payment_required", "Este posto exige pagamento antes de iniciar. Pague pelo app (teste) "
                     "e tente de novo.", 402)
        return None
    payment = db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
    if not payment or payment.user_id != user.id:
        fail("payment_not_found", "Pagamento não encontrado", 404)
    if payment.connector_id != connector.id:
        fail("payment_mismatch", "Este pagamento é de outro ponto", 409)
    if payment.session_id is not None or payment.status in ("in_use", "completed"):
        fail("payment_used", "Este pagamento já foi usado em uma recarga", 409)
    if payment.status in PRE_START:
        fail("payment_not_ready", "Pagamento ainda não confirmado pela Stripe (teste)", 409)
    if payment.status not in FUNDED or (payment.start_deadline and payment.start_deadline <= now()):
        fail("payment_expired", "Pagamento expirado ou cancelado; faça um novo pagamento", 409)
    return payment


def funded_input(data, payment):
    """Limites do START vindos do orçamento pago: teto de energia, duração e potência."""
    return data.model_copy(update={
        "max_cost": billing.money(payment.energy_cap_cents),
        "max_duration_minutes": payment.max_duration_minutes,
        "max_power_kw": Decimal(payment.max_power_kw) if payment.max_power_kw is not None else data.max_power_kw,
        "coupon_code": None,
        "power_tier": (payment.quote or {}).get("power_tier", "max"),
    })


def locked_terms(payment):
    """``(base, multiplicador, desconto)`` travados no orçamento pago."""
    return Decimal(payment.base_price_per_kwh), Decimal(payment.demand_multiplier), payment.discount_percent


def payment_price_terms(payment, connector):
    """Explicação do preço do recibo travada no orçamento pago (``quote.price_terms``).

    Pagamentos orçados antes do recibo não a têm: reconstrói pelos termos gravados no pagamento.
    """
    quote = payment.quote if isinstance(payment.quote, dict) else {}
    if isinstance(quote.get("price_terms"), dict):
        return dict(quote["price_terms"])
    from chargegrid_core import receipt  # evita custo de import nas rotas de consulta

    coupon = {"code": payment.coupon_code, "discount_percent": payment.discount_percent} \
        if payment.coupon_code else None
    return receipt.price_terms(
        locked_at=payment.created_at, locked_by="reservation" if quote.get("reservation_terms") else "start",
        connector_base=connector.price_per_kwh, base=payment.base_price_per_kwh,
        multiplier=payment.demand_multiplier, coupon=coupon, connector_id=connector.id,
    )


def attach_payment(payment, session):
    payment.session_id = session.id
    payment.status = "in_use"


def start_window(payment):
    minutes = settings().payments_kiosk_start_minutes if payment.origin == "kiosk" \
        else settings().payments_start_window_minutes
    return timedelta(minutes=minutes)


def mark_zero_settlement(payment):
    """Nada fica: autorização liberada (cartão) ou devolução integral (Pix)."""
    plan = billing.settle_amounts(amount_cents=payment.amount_cents, energy_cents=0,
                                  captured_upfront=payment.captured_cents > 0)
    payment.energy_cents = 0
    payment.overstay_cents = 0
    payment.charge_cents = plan["charge_cents"]
    payment.waived_cents = 0
    payment.uncollected_cents = 0
    payment.settlement_status = "due"


def prepare_settlement_for_session(db, session):
    """Recarga encerrada: calcula o acerto pela energia confirmada (uma única vez)."""
    payment = db.scalar(select(Payment).where(Payment.session_id == session.id).with_for_update())
    if not payment or payment.settlement_status != "none" or session.status in SESSION_ACTIVE:
        return payment
    overstay, final = overstay_charge(db, session)
    if not final:
        return payment
    energy = billing.energy_cents(session.energy_wh, session.price_per_kwh, session.discount_percent)
    plan = billing.settle_amounts(
        amount_cents=payment.amount_cents, energy_cents=energy, fixed_fee_cents=payment.fixed_fee_cents,
        overstay_cents=overstay, captured_upfront=payment.captured_cents > 0,
        energy_cap_cents=payment.energy_cap_cents,
    )
    payment.energy_cents = energy
    payment.overstay_cents = overstay
    payment.charge_cents = plan["charge_cents"]
    payment.waived_cents = plan["waived_cents"]
    payment.uncollected_cents = plan["uncollected_cents"]
    payment.settlement_status = "due"
    return payment


def prepare_recent_settlements(db, connector):
    """Chamado no sync (com a trava do ponto): pagamentos cuja recarga acabou de encerrar."""
    sessions = db.scalars(
        select(ChargingSession)
        .join(Payment, Payment.session_id == ChargingSession.id)
        .where(
            Payment.connector_id == connector.id,
            Payment.status == "in_use",
            Payment.settlement_status == "none",
            ChargingSession.status.not_in(SESSION_ACTIVE),
        )
    ).all()
    for session in sessions:
        prepare_settlement_for_session(db, session)


def device_fields(db, connector, station):
    """Campos aditivos do bloco ``connector`` do sync: QR de pagamento e pagamento em andamento."""
    base = settings().public_base_url.strip().rstrip("/")
    url = None
    if (
        station.kiosk_payments and base and connector.active and station.active and station.owner_id
        and gateways.current() is not None
        and not active_session(db, connector.id) and not active_res(db, connector.id)
        and not active_hold(db, connector.id)
    ):
        code = current_code(station)[0]
        url = f"{base}/pay/k/{quote(connector.public_code, safe='')}?c={code[2:]}"
    payment = db.scalar(
        select(Payment)
        .where(
            Payment.connector_id == connector.id,
            Payment.origin == "kiosk",
            Payment.status.in_(PAYMENT_OPEN),
            Payment.created_at > now() - timedelta(minutes=KIOSK_PAYMENT_VISIBLE_MINUTES),
            # Pagamento de pedido do totem aparece no bloco ``kiosk_order``, não aqui.
            ~select(KioskOrder.id).where(KioskOrder.payment_id == Payment.id).exists(),
        )
        .order_by(Payment.created_at.desc())
        .limit(1)
    )
    return {
        "kiosk_url": url,
        "payment": {
            "status": payment.status,
            "status_label": billing.status_label(payment.status),
            "amount": str(billing.money(payment.amount_cents)),
            "environment": "test",
        } if payment else None,
    }


def _iso(value):
    return value.isoformat() if value else None


def status_label(payment):
    """Rótulo do pagamento; o simulado do totem (Modo apresentação) diz "(simulado)", nunca "(teste)"."""
    label = _status_label(payment)
    return label.replace("(teste)", "(simulado)") if payment.provider == "simulated" else label


def _status_label(payment):
    if payment.settlement_status == "failed":
        return "Em revisão (teste)"
    if payment.status == "in_use" and payment.settlement_status in ("due", "settling"):
        return "Pago (teste) · acertando o valor"
    returned = payment.amount_cents - payment.charge_cents if payment.charge_cents is not None else None
    if payment.status in ("expired", "canceled") and payment.settlement_status in ("due", "settling"):
        return billing.STATUS_LABELS[payment.status] + " · devolvendo"
    return billing.status_label(
        payment.status, charge_cents=payment.charge_cents, return_cents=returned,
        method=payment.method if payment.provider_payment_intent_id and payment.settlement_status == "done" else None,
    )


def payment_row(payment, *, owner=False):
    """Representação pública do pagamento (sem identidade do motorista)."""
    money = billing.money
    settlement = None
    if payment.charge_cents is not None:
        returned = payment.amount_cents - payment.charge_cents
        settlement = {
            "status": payment.settlement_status,
            "energy_amount": str(money(payment.energy_cents)),
            "overstay_amount": str(money(payment.overstay_cents)),
            "fixed_fee": str(money(payment.fixed_fee_cents)),
            "charged": str(money(payment.charge_cents)),
            "returned": str(money(returned)),
            # Cartão: a pré-autorização não usada é liberada; Pix: a diferença é devolvida (refund).
            "return_kind": "refunded" if payment.refunded_cents or payment.method == "pix" else "released",
            "captured": str(money(payment.captured_cents)),
            "refunded": str(money(payment.refunded_cents)),
            "waived": str(money(payment.waived_cents)),
            "uncollected": str(money(payment.uncollected_cents)),
            "below_minimum": bool(payment.charge_cents == 0 and payment.waived_cents and payment.energy_cents),
            "provider_fee": str(money(payment.provider_fee_cents)) if payment.provider_fee_cents is not None else None,
            "settled_at": _iso(payment.settled_at),
        }
    result = {
        "id": str(payment.id),
        "status": payment.status,
        "status_label": status_label(payment),
        "environment": payment.environment,
        "provider": payment.provider,
        "origin": payment.origin,
        "method": payment.method,
        "currency": billing.CURRENCY,
        "amount": str(money(payment.amount_cents)),
        "energy_cap": str(money(payment.energy_cap_cents)),
        "fixed_fee": str(money(payment.fixed_fee_cents)),
        "overstay_reserve": str(money(payment.overstay_reserve_cents)),
        "price_per_kwh": str(payment.price_per_kwh),
        "base_price_per_kwh": str(payment.base_price_per_kwh),
        "demand_multiplier": str(payment.demand_multiplier),
        "discount_percent": payment.discount_percent,
        "max_duration_minutes": payment.max_duration_minutes,
        "max_power_kw": str(payment.max_power_kw) if payment.max_power_kw is not None else None,
        "connector_id": str(payment.connector_id),
        "session_id": str(payment.session_id) if payment.session_id else None,
        "expires_at": _iso(payment.expires_at),
        "start_deadline": _iso(payment.start_deadline),
        "authorized_at": _iso(payment.authorized_at),
        "created_at": _iso(payment.created_at),
        "settlement": settlement,
        "provider_ref": payment.provider_payment_intent_id,
    }
    if not owner:
        result["coupon_code"] = payment.coupon_code
        result["checkout_url"] = payment.checkout_url if payment.status in PRE_START else None
        result["quote"] = payment.quote
    result["power_tier"] = (payment.quote or {}).get("power_tier", "max")
    return result


def payments_by_session(db, session_ids):
    ids = [value for value in session_ids if value]
    if not ids:
        return {}
    return {payment.session_id: payment for payment in db.scalars(select(Payment).where(Payment.session_id.in_(ids)))}


def payment_channel(payment, totem_payment_ids=()):
    """Canal da recarga paga: ``app``, ``kiosk_qr`` (QR /pay/k da tela Pronto) ou ``kiosk_totem``."""
    if payment.origin != "kiosk":
        return "app"
    return "kiosk_totem" if payment.id in totem_payment_ids else "kiosk_qr"


def totem_payment_ids(db, payments):
    """Ids dos pagamentos (entre ``payments``) que vieram de um pedido do totem (uma consulta, só se houver
    pagamento de origem ``kiosk``)."""
    kiosk_ids = [payment.id for payment in payments if payment.origin == "kiosk"]
    if not kiosk_ids:
        return set()
    return set(db.scalars(select(KioskOrder.payment_id).where(KioskOrder.payment_id.in_(kiosk_ids))))


def channel_by_session(db, payments):
    """``{session_id: {"channel", "provider", "method"}}`` de ``payments_by_session`` (exportações do dono)."""
    totem = totem_payment_ids(db, payments.values())
    return {session_id: {"channel": payment_channel(payment, totem), "provider": payment.provider,
                         "method": payment.method} for session_id, payment in payments.items()}


def attach_owner_payments(db, result):
    """``/owner/sessions``: acrescenta o pagamento de cada sessão (sem dados do motorista) e o canal."""
    payments = payments_by_session(db, [item.get("id") for item in result["items"]])
    by_text = {str(key): value for key, value in payments.items()}
    totem = totem_payment_ids(db, payments.values())
    for item in result["items"]:
        payment = by_text.get(str(item.get("id")))
        item["payment"] = payment_row(payment, owner=True) | {"channel": payment_channel(payment, totem)} \
            if payment else None
    return result
