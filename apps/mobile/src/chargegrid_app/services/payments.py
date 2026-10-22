"""Pagamento pré-pago pela Stripe em MODO TESTE (``/v1/payments``), visto pelo motorista.

O app nunca lê, guarda ou envia número de cartão, validade ou CVV: o motorista paga na página
hospedada da Stripe (``checkout_url``, aberta no navegador com ``ft.UrlLauncher``) e quem confirma
é o servidor (webhook ou verificação no ``GET /payments/{id}``). O app só consulta o estado.

* ``config``: ``GET payments/config`` (``enabled`` falso quando a rota não existe ou falha).
* ``create``: ``POST payments`` com ``Idempotency-Key`` (repetir com a mesma chave reaproveita).
* ``fetch`` / ``cancel``: ``GET payments/{id}`` (também dispara o acerto no servidor) e ``POST cancel``.
* Textos: selo do pagamento, acerto "Cobrado R$ X · Devolvido R$ Y (teste)" e prazo ``mm:ss``.

Conta demo: ``demo_payments`` responde as mesmas rotas sem rede.

Modo apresentação (``vehicle_state.presentation_mode``): a Stripe fica de fora por completo — o app não
consulta ``payments/config``, não cria pagamento nem abre o navegador, e volta ao pagamento simulado da
0.6.x (Saldo / Pix / Cartão). ``enabled(app)`` é a chave usada pelas telas.
"""

from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import flet as ft

from ..api_client import ApiError
from ..ui.wording import visible
from . import vehicle_state

AWAITING = ('awaiting_payment',)
DECLINED = ('declined',)
FUNDED = ('authorized', 'paid')
CLOSED = ('expired', 'canceled')
SETTLING = ('due', 'settling')
METHOD_LABEL = 'Cartão ou Pix · Stripe'
TEST_CARD = '4242 4242 4242 4242'
_CENT = Decimal('0.01')
PRESENTATION_PREPAY = ('Este posto exige pagamento pela Stripe. Ajuste a forma de pagamento em Conta ou '
                       'desative a exigência no painel.')


def enabled(app):
    """``False`` no modo apresentação: a Stripe não é usada (pagamento simulado da 0.6.x)."""
    return not vehicle_state.presentation_mode(app)


async def config(app, refresh=False):
    """``{enabled, test_card, ...}`` da API; sem a rota (API antiga) ou com erro, ``enabled`` falso.

    Fica guardado em ``app.payments_config`` durante a sessão do app (``refresh`` consulta de novo).
    """
    cached = getattr(app, 'payments_config', None)
    if isinstance(cached, dict) and not refresh:
        return cached
    try:
        result = await app.api.request('GET', 'payments/config')
    except ApiError:
        result = None
    result = result if isinstance(result, dict) else {}
    result = {**result, 'enabled': result.get('enabled') is True}
    try:
        app.payments_config = result
    except AttributeError:
        pass
    return result


def request_body(connector_id, intent, energy_kwh=None):
    """Corpo do ``POST payments`` a partir da escolha do assistente (o teto é calculado pela API).

    ``intent``: ``{'mode': 'time', 'minutes'}`` | ``{'mode': 'value', 'max_cost'}`` |
    ``{'mode': 'autonomy', 'km'}`` (vira ``energy`` com ``energy_kwh``) e ``max_power_kw`` opcional.
    """
    body = {'connector_id': connector_id}
    mode = intent.get('mode')
    if mode == 'value':
        body.update(mode='value', max_cost=str(intent['max_cost']))
    elif mode == 'autonomy':
        body.update(mode='energy', energy_kwh=str(energy_kwh))
    else:
        body.update(mode='time', minutes=int(intent.get('minutes') or 30))
    if intent.get('power_tier') in ('max', 'reduced'):
        body['power_tier'] = intent['power_tier']
    if intent.get('max_power_kw') is not None:
        body['max_power_kw'] = str(intent['max_power_kw'])
    if intent.get('coupon_code'):
        body['coupon_code'] = intent['coupon_code']  # a API aplica o desconto no teto e trava o cupom
    return body


async def create(app, body, key):
    return await app.api.request('POST', 'payments', body, key=key)


async def fetch(app, payment_id):
    return await app.api.request('GET', f'payments/{payment_id}')


async def cancel(app, payment_id):
    return await app.api.request('POST', f'payments/{payment_id}/cancel')


async def open_checkout(app, payment):
    """Abre a Checkout hospedada da Stripe no navegador do aparelho. ``False`` sem URL.

    Conta demo: não há Stripe; a rota local ``demo-checkout`` confirma como o cartão de teste faria.
    """
    payment = payment or {}
    url = payment.get('checkout_url')
    if not url:
        return False
    if getattr(app.api, 'is_demo', False) is True:
        await app.api.request('POST', f"payments/{payment['id']}/demo-checkout")
        return True
    await ft.UrlLauncher().launch_url(url)
    return True


def money(value):
    """``'12.5'`` -> ``'R$ 12,50'`` (milhar com ponto)."""
    try:
        amount = Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        amount = Decimal('0.00')
    whole, cents = f'{amount:,.2f}'.split('.')
    return f"R$ {whole.replace(',', '.')},{cents}"


def _when(value):
    try:
        moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def seconds_left(payment, now=None):
    """Segundos até o prazo do passo atual: a Checkout (aguardando) ou o início (pago); ``None`` sem prazo."""
    payment = payment or {}
    deadline = _when(payment.get('start_deadline') if payment.get('status') in FUNDED else payment.get('expires_at'))
    if deadline is None:
        return None
    now = now or datetime.now(timezone.utc)
    return max(0, int((deadline - now).total_seconds()))


def clock(seconds):
    """``75`` -> ``'01:15'``."""
    seconds = max(0, int(seconds or 0))
    return f'{seconds // 60:02d}:{seconds % 60:02d}'


def settlement_text(payment):
    """``Cobrado R$ X · Devolvido R$ Y`` quando o acerto terminou; senão ``None``."""
    settlement = (payment or {}).get('settlement') or {}
    if settlement.get('status') != 'done':
        return None
    charged, returned = Decimal(str(settlement.get('charged') or 0)), Decimal(str(settlement.get('returned') or 0))
    if charged <= 0:
        return f'Nada cobrado · Devolvido {money(returned)}'
    if returned <= 0:
        return f'Cobrado {money(charged)}'
    return f'Cobrado {money(charged)} · Devolvido {money(returned)}'


def settlement_note(payment):
    """Linha secundária do acerto: como volta a diferença e o que não foi cobrado."""
    settlement = (payment or {}).get('settlement') or {}
    if settlement.get('status') == 'failed':
        return 'Acerto em revisão. Nenhum valor acima do autorizado é cobrado.'
    if settlement.get('status') != 'done':
        return None
    parts = []
    if Decimal(str(settlement.get('returned') or 0)) > 0:
        parts.append('Pré-autorização não usada liberada no cartão.' if settlement.get('return_kind') == 'released'
                     else 'Diferença devolvida pela Stripe.')
    if settlement.get('below_minimum'):
        parts.append('Valor abaixo do mínimo da Stripe perdoado.')
    if Decimal(str(settlement.get('overstay_amount') or 0)) > 0:
        parts.append(f"Inclui {money(settlement['overstay_amount'])} de taxa de permanência.")
    return ' '.join(parts) or None


def pending_settlement(payment):
    """``True`` enquanto a recarga paga terminou mas o acerto ainda não foi concluído."""
    if not payment:
        return False
    settlement = payment.get('settlement')
    if settlement is None:
        return payment.get('status') in ('in_use',) + FUNDED
    return settlement.get('status') in SETTLING


def badge_text(payment):
    """Selo curto do pagamento (rótulo da API, sem as marcas "(teste)")."""
    if not payment:
        return None
    label = visible(str(payment.get('status_label') or 'Pagamento')) or 'Pagamento'
    return f"Stripe · {label}"
