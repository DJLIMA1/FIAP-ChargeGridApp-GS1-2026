"""Textos do vendedor para o pagamento e a permanência das sessões.

Mesmas regras do painel web (``apps/owner-web/src/lib/overstay.ts``):

* bloco ``overstay`` das sessões (``/operator/charging-sessions``) ou as colunas ``overstay_minutes`` /
  ``overstay_fee`` de ``/owner/sessions``;
* ``payment`` das sessões: rótulo da API (sem as marcas "(teste)") e o acerto (capturado e devolvido/liberado).

Tudo devolve ``None`` quando a API não manda os campos (API antiga): a tela esconde a linha.
"""

from decimal import Decimal, InvalidOperation

from ..ui.wording import visible
from .payments import money

# Fase da permanência: rótulo e tom (``theme``).
OVERSTAY_STATUS = {
    'none': ('Sem permanência', 'SLATE'),
    'no_fee': ('Na vaga · sem taxa', 'SLATE'),
    'grace': ('Em tolerância', 'AMBER'),
    'billing': ('Cobrando permanência', 'RED'),
    'capped': ('Taxa no máximo', 'RED'),
    'closed': ('Permanência encerrada', 'GREEN'),
}
OPEN = ('no_fee', 'grace', 'billing', 'capped')


def _amount(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(0)


def overstay_summary(session):
    """Permanência da sessão: ``14 min na vaga · taxa R$ 4,00`` (ou ``None`` sem permanência).

    Aceita o bloco ``overstay`` (sessões do app) ou ``overstay_minutes``/``overstay_fee`` (``/owner/sessions``)."""
    session = session or {}
    block = session.get('overstay')
    if isinstance(block, dict):
        status = block.get('status')
        if status in (None, 'none'):
            return None
        minutes = int(block.get('billable_seconds') or 0) // 60
        fee = _amount(block.get('fee_due'))
        head = f'{minutes} min na vaga' if status != 'grace' or minutes else 'Na vaga agora'
        if fee > 0:
            tail = f'taxa {money(fee)}' + (' (no máximo)' if status == 'capped' else '')
        elif not block.get('fee_applies'):
            tail = 'sem taxa'
        else:
            tail = 'dentro da tolerância'
        text = f'{head} · {tail}'
        if status in OPEN:
            text += f' · {OVERSTAY_STATUS[status][0].lower()}'
        return text
    if 'overstay_fee' in session or 'overstay_minutes' in session:
        fee = _amount(session.get('overstay_fee'))
        minutes = int(_amount(session.get('overstay_minutes')))
        if fee <= 0:
            return None
        return f'{money(fee)}' + (f' · {minutes} min cobrados' if minutes else '')
    return None


CHANNEL_LABELS = {'app': 'App', 'kiosk_qr': 'QR do painel', 'kiosk_totem': 'Totem', 'kiosk': 'Painel'}


def is_simulated(payment):
    """Pagamento simulado do totem (conta do dono em Modo apresentação): sem Stripe."""
    payment = payment or {}
    return payment.get('provider') == 'simulated' or payment.get('method') == 'simulated'


def payment_source(payment):
    """``'Totem · Simulado'``, ``'QR do painel · Stripe'`` ou ``'Stripe'`` (canal do app fica implícito).

    ``payment.channel`` (``app`` | ``kiosk_qr`` | ``kiosk_totem``) vem de ``/owner/sessions`` e de
    ``/operator/charging-sessions``; sem o campo (API antiga): simulado só existe no totem; outra origem
    ``kiosk`` vira "Painel" (QR ou totem, sem como distinguir)."""
    payment = payment or {}
    channel = payment.get('channel')
    if not channel:
        channel = ('kiosk_totem' if is_simulated(payment) else 'kiosk' if payment.get('origin') == 'kiosk'
                   else 'app')
    method = 'Sem cobrança' if is_simulated(payment) else 'Stripe'
    return method if channel == 'app' else f'{CHANNEL_LABELS.get(channel, channel)} · {method}'


def payment_summary(payment):
    """``(rótulo, detalhe)`` do pagamento da sessão ou ``None`` sem pagamento.

    Rótulo da API sem "(teste)"; detalhe com o acerto: ``Capturado R$ 21,83 · liberado R$ 18,17``."""
    if not isinstance(payment, dict):
        return None
    label = visible(str(payment.get('status_label') or payment.get('status') or 'Pagamento')) or 'Pagamento'
    settlement = payment.get('settlement') or {}
    detail = None
    if settlement.get('status') == 'done':
        captured = settlement.get('captured') if settlement.get('captured') is not None else settlement.get('charged')
        detail = f'Capturado {money(captured or 0)}'
        returned = _amount(settlement.get('returned'))
        if returned > 0:
            verb = 'devolvido' if settlement.get('return_kind') == 'refunded' else 'liberado'
            detail += f' · {verb} {money(returned)}'
        if _amount(settlement.get('overstay_amount')) > 0:
            detail += f" · inclui {money(settlement['overstay_amount'])} de permanência"
    elif settlement.get('status') == 'failed':
        detail = 'Acerto em revisão'
    elif settlement.get('status') in ('due', 'settling'):
        detail = 'Acerto em andamento'
    elif payment.get('amount') is not None:
        detail = f"Teto autorizado {money(payment['amount'])}"
    return label, detail
