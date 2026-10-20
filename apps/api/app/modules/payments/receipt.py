"""Pagamento (frente A) no recibo e na margem (frente C): adaptador ``register_extras("payment")``.

Só entra pagamento confirmado pelo provedor (``authorized_at`` gravado pelo webhook ou pela
verificação no servidor). ``net_amount`` (capturado − devolvido) só existe depois do acerto
(``settlement_status = done``): é ele que substitui a receita estimada na margem e manda no
total do recibo. Antes do acerto o recibo mostra o pagamento confirmado e o valor estimado.

O valor gravado em ``payments.environment`` continua ``"test"`` (restrição do banco); o
contrato do recibo usa ``mock | sandbox | production`` e aqui ``test`` vira ``sandbox``.
"""

from sqlalchemy import select

from chargegrid_core import billing

from ...models import Payment

ENVIRONMENTS = {"test": "sandbox", "sandbox": "sandbox", "mock": "mock", "live": "production",
                "production": "production"}


def _money(cents):
    return str(billing.money(cents)) if cents is not None else None


def _iso(value):
    return value.isoformat() if value else None


def _refund_status(payment, settled):
    if not settled:
        return "pending" if payment.settlement_status in ("due", "settling") else "none"
    if payment.refunded_cents:
        return "refunded"
    if payment.captured_cents < payment.amount_cents:
        return "released"  # cartão: a parte não capturada da pré-autorização é liberada
    return "none"


def receipt_payment(payment) -> dict:
    """Fatos do pagamento no formato do recibo (strings decimais em R$)."""
    settled = payment.settlement_status == "done"
    # Simulado (totem com o dono em Modo apresentação): "mock" = "Pagamento simulado" no recibo.
    environment = "mock" if payment.provider == "simulated" else ENVIRONMENTS.get(payment.environment, "sandbox")
    return {
        "environment": environment,
        "provider": payment.provider,
        "provider_reference": payment.provider_payment_intent_id,
        "method": payment.method,
        "status": payment.status,
        "settlement_status": payment.settlement_status,
        "authorized_amount": _money(payment.amount_cents),
        "captured_amount": _money(payment.captured_cents) if settled else None,
        "refunded_amount": _money(payment.refunded_cents) if settled else None,
        "net_amount": _money(payment.captured_cents - payment.refunded_cents) if settled else None,
        "charged_amount": _money(payment.charge_cents) if settled else None,
        "energy_amount": _money(payment.energy_cents),
        "overstay_amount": _money(payment.overstay_cents),
        "waived_amount": _money(payment.waived_cents) if settled else None,
        "uncollected_amount": _money(payment.uncollected_cents) if settled else None,
        "below_minimum": bool(settled and payment.charge_cents == 0 and payment.waived_cents
                              and payment.energy_cents),
        "provider_fee": _money(payment.provider_fee_cents) if settled else None,
        "refund_status": _refund_status(payment, settled),
        "confirmed_at": _iso(payment.authorized_at),
        "settled_at": _iso(payment.settled_at) if settled else None,
    }


def payment_extras(db, sessions) -> dict:
    """``{session_id: {...}}`` numa consulta só (sem N+1), só pagamentos confirmados."""
    ids = [session.id for session in sessions]
    if not ids:
        return {}
    payments = db.scalars(
        select(Payment).where(Payment.session_id.in_(ids), Payment.authorized_at.is_not(None))
    ).all()
    return {payment.session_id: receipt_payment(payment) for payment in payments}


def install():
    from ..receipts.registry import register_extras

    register_extras("payment", payment_extras)
