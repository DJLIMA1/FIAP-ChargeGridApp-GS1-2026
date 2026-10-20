"""Pagamento pré-pago da conta demo: as rotas ``/payments`` da API sem rede e sem Stripe.

Mesmas regras de centavos da API (``chargegrid_core.billing``): o teto vem do orçamento
(tarifa de agora × potência efetiva), o START usa os termos travados e, no fim, cobra só a
energia simulada e devolve o resto. "Abrir pagamento seguro" na demo chama a rota local
``POST payments/{id}/demo-checkout``, que confirma o pagamento como se o motorista tivesse usado o
cartão de teste na página da Stripe (2 s de relógio da demo). Nenhum dado de cartão existe aqui.
"""

from decimal import ROUND_DOWN, Decimal

from chargegrid_core import billing, pricing
from chargegrid_core import overstay as overstay_rules
from chargegrid_core import power as power_rules

CHECKOUT_MINUTES = 31
START_WINDOW_MINUTES = 15
CONFIRM_SECONDS = 2
_ENDED = ('completed', 'failed', 'interrupted')


def _fail(message, code, status):
    from .demo import _fail as fail
    fail(message, code, status)


def _store(api):
    store = getattr(api, '_payments', None)
    if not isinstance(store, dict):
        store = api._payments = {}
    return store


def config():
    return {'enabled': True, 'provider': 'stripe', 'environment': 'test', 'currency': billing.CURRENCY,
            'methods': ['card'], 'min_amount': str(billing.money(billing.MIN_CHARGE_CENTS)),
            'kiosk_amounts': ['10.00', '20.00', '40.00'], 'test_card': '4242 4242 4242 4242'}


def _label(payment):
    if payment['status'] == 'completed':
        settlement = payment['settlement'] or {}
        charged, returned = (billing.to_cents(settlement.get(key) or 0) for key in ('charged', 'returned'))
        label = billing.status_label('completed', charge_cents=charged, return_cents=returned)
    else:
        label = billing.status_label(payment['status'])
    # Como a API: o simulado do totem (dono em Modo apresentação) diz "(simulado)", nunca "(teste)".
    return label.replace('(teste)', '(simulado)') if payment.get('provider') == 'simulated' else label


def row(api, payment):
    if payment is None:
        return None
    return {**{key: value for key, value in payment.items() if key != 'confirm_at' and not key.startswith('_')},
            'status_label': _label(payment),
            'checkout_url': payment['checkout_url'] if payment['status'] in ('awaiting_payment', 'declined') else None}


def _quote(api, point, body):
    station = api._stations[point['station_id']]
    status = api._demand(station)
    base, price = pricing.connector_price(status, point['id'], point['price_per_kwh'])
    effective = api._power(station)['connectors'][point['id']]['effective_kw']
    driver = Decimal(str(body['max_power_kw'])) if body.get('max_power_kw') is not None else None
    power = power_rules.applied_limit(effective, driver).quantize(Decimal('0.001'), rounding=ROUND_DOWN)
    power = power if power > 0 else Decimal(point['power_kw'])
    try:
        cap = billing.quote_cap(body.get('mode'), power_kw=power, price_per_kwh=price, minutes=body.get('minutes'),
                                max_cost=body.get('max_cost'), energy_kwh=body.get('energy_kwh'),
                                max_minutes=point['max_duration_minutes'])
    except (ValueError, ArithmeticError) as exc:
        _fail(str(exc), 'invalid_quote', 422)
    return {'amount_cents': cap['energy_cap_cents'], 'price': price, 'base': base,
            'multiplier': status['multiplier'], 'power': power, 'minutes': cap['max_duration_minutes'],
            'energy_kwh': cap['energy_kwh'], 'driver': driver, 'overstay': overstay_terms(api, station)}


def overstay_terms(api, station):
    """Termos da permanência no orçamento (``app.overstay.payment_terms``): o teto da taxa é reservado
    junto com a energia (``reserve_cents``) e os termos ficam travados no pagamento."""
    terms = api._overstay_terms(station)
    if not terms:
        return {'reserve_cents': 0, 'fee_per_minute': None, 'tolerance_minutes': None, 'max_billable_minutes': None}
    return {'reserve_cents': overstay_rules.cents(terms['max_amount']),
            'fee_per_minute': str(overstay_rules.fee_per_minute(terms)), 'tolerance_minutes': terms['grace_minutes'],
            'max_billable_minutes': overstay_rules.max_billable_minutes(terms), **terms}


def create(api, body):
    allowed = ('connector_id', 'mode', 'minutes', 'max_cost', 'energy_kwh', 'max_power_kw', 'coupon_code')
    if set(body) - set(allowed):
        _fail('Campo não aceito pelo pagamento de demonstração.', 'validation_error', 422)
    point = api._get(api._points, body.get('connector_id'), 'Ponto não encontrado')
    for payment in _mine(api):
        _advance(api, payment)
        if payment['status'] in ('authorized', 'paid') and payment['session_id'] is None:
            _fail('Você já tem um pagamento confirmado sem uso. Use-o ou cancele antes de pagar outro.',
                  'payment_open_exists', 409)
        if payment['status'] in ('awaiting_payment', 'declined'):
            payment['status'] = 'canceled'
    quote = _quote(api, point, body)
    pid = api._id('payment')
    energy = quote['amount_cents']
    reserve = int(quote['overstay']['reserve_cents'] or 0)
    amount = energy + reserve  # como a API: teto da energia + reserva do teto da permanência
    payment = {
        'id': pid, 'status': 'awaiting_payment', 'environment': 'test', 'provider': 'stripe', 'origin': 'app',
        'method': None, 'currency': billing.CURRENCY, 'amount': str(billing.money(amount)),
        'energy_cap': str(billing.money(energy)), 'fixed_fee': '0.00', 'overstay_reserve': str(billing.money(reserve)),
        'price_per_kwh': str(quote['price']), 'base_price_per_kwh': str(quote['base']),
        'demand_multiplier': str(quote['multiplier']), 'discount_percent': 0, 'coupon_code': None,
        'max_duration_minutes': quote['minutes'],
        'max_power_kw': str(quote['power']) if quote['driver'] is not None else None,
        'connector_id': point['id'], 'session_id': None,
        'checkout_url': f'chargegrid-demo://checkout/{pid}',
        'expires_at': api._iso(api._elapsed + CHECKOUT_MINUTES * 60), 'start_deadline': None,
        'authorized_at': None, 'created_at': api._iso(), 'provider_ref': None, 'settlement': None,
        'quote': {'mode': body.get('mode'), 'minutes': body.get('minutes'), 'max_cost': body.get('max_cost'),
                  'energy_kwh': str(quote['energy_kwh']), 'power_kw': str(quote['power']),
                  'reservation_terms': False, 'overstay': quote['overstay']},
        'confirm_at': None,
    }
    _store(api)[pid] = payment
    return row(api, payment)


def _mine(api):
    """Pagamentos do motorista da demo (sem os dos motoristas fictícios do movimento simulado)."""
    return [payment for payment in _store(api).values() if not payment.get('_visitor')]


def _owned(api, payment_id):
    payment = _store(api).get(payment_id)
    if payment is None or payment.get('_visitor'):
        _fail('Pagamento não encontrado', 'not_found', 404)
    return payment


def _claimable(api, payment_id):
    payment = _store(api).get(payment_id)
    if payment is None or payment.get('_visitor'):
        _fail('Pagamento não encontrado', 'payment_not_found', 404)  # código do START na API
    return payment


def _advance(api, payment):
    """Como o ``advance`` da API: confirmação simulada, prazos e acerto no fim da recarga."""
    elapsed = api._elapsed
    if payment['status'] == 'awaiting_payment':
        if payment['confirm_at'] is not None and elapsed >= payment['confirm_at']:
            payment.update(status='authorized', method='card', authorized_at=api._iso(),
                           start_deadline=api._iso(elapsed + START_WINDOW_MINUTES * 60),
                           provider_ref=f"pi_demo_{payment['id'].rsplit('-', 1)[-1]}")
        elif api._now() >= _date(payment['expires_at']):
            payment['status'] = 'expired'
    if (payment['status'] in ('authorized', 'paid') and payment['session_id'] is None
            and api._now() >= _date(payment['start_deadline'])):
        payment['status'] = 'expired'
        _settle(payment, 0)
    if payment['status'] == 'in_use' and payment['session_id']:
        from . import demo_site
        session = api._sessions.get(payment['session_id'])
        # O acerto espera a permanência ficar final (carro desconectado ou taxa no teto), como a API.
        if session and session['status'] in _ENDED and demo_site.overstay_final(api, session):
            # Mesma conta do acerto da API: energia confirmada × tarifa travada (meio para cima).
            energy = billing.energy_cents(session['energy_wh'], session['price_per_kwh'], session['discount_percent'])
            _settle(payment, energy, demo_site.overstay_cents(api, session))
            payment['status'] = 'completed'
    return payment


def _date(value):
    from .demo import _date as parse
    return parse(value)


def _settle(payment, energy_cents, overstay_cents=0):
    amount = billing.to_cents(payment['amount'])
    plan = billing.settle_amounts(amount_cents=amount, energy_cents=energy_cents, overstay_cents=overstay_cents)
    money = billing.money
    kept_overstay = max(0, plan['charge_cents'] - min(energy_cents, amount)) if plan['charge_cents'] else 0
    payment['settlement'] = {
        'status': 'done', 'energy_amount': str(money(energy_cents)),
        'overstay_amount': str(money(kept_overstay)), 'fixed_fee': '0.00',
        'charged': str(money(plan['charge_cents'])), 'returned': str(money(plan['return_cents'])),
        'return_kind': 'released', 'captured': str(money(plan['charge_cents'])), 'refunded': '0.00',
        'waived': str(money(plan['waived_cents'])), 'uncollected': str(money(plan['uncollected_cents'])),
        'below_minimum': plan['below_minimum'],
        'provider_fee': None, 'settled_at': None,
    }


def claim_for_start(api, point, payment_id):
    """START com ``payment_id``: as mesmas recusas da API (``claim_for_start``)."""
    payment = _claimable(api, payment_id)
    _advance(api, payment)
    if payment['connector_id'] != point['id']:
        _fail('Este pagamento é de outro ponto', 'payment_mismatch', 409)
    if payment['session_id'] is not None or payment['status'] in ('in_use', 'completed'):
        _fail('Este pagamento já foi usado em uma recarga', 'payment_used', 409)
    if payment['status'] in ('awaiting_payment', 'declined'):
        _fail('Pagamento ainda não confirmado pela Stripe (teste)', 'payment_not_ready', 409)
    if payment['status'] not in ('authorized', 'paid'):
        _fail('Pagamento expirado ou cancelado; faça um novo pagamento', 'payment_expired', 409)
    return payment


def attach(payment, session):
    """Liga o pagamento à sessão e aplica os limites do orçamento pago (como ``funded_input``)."""
    payment.update(session_id=session['id'], status='in_use')
    session.update(max_cost=str(Decimal(payment['energy_cap']).quantize(Decimal('0.0001'))),
                   max_duration_minutes=payment['max_duration_minutes'],
                   price_per_kwh=str(Decimal(payment['price_per_kwh'])), discount_percent=0)


def for_session(api, session_id):
    payment = next((p for p in _store(api).values() if p['session_id'] == session_id), None)
    return row(api, payment)


def route(api, method, parts, body):
    """``payments/...`` da demo; ``None`` quando a rota não é de pagamento."""
    if parts[0] != 'payments':
        return None
    if (method, len(parts)) == ('GET', 2) and parts[1] == 'config':
        return config()
    if (method, len(parts)) == ('POST', 1):
        return create(api, body)
    if (method, len(parts)) == ('GET', 2) and parts[1] == 'current':
        payments = [p for p in _mine(api)
                    if p['status'] in ('awaiting_payment', 'declined', 'authorized', 'paid', 'in_use')]
        payment = max(payments, key=lambda p: p['created_at'], default=None)
        return row(api, _advance(api, payment)) if payment else None
    if (method, len(parts)) == ('GET', 2):
        return row(api, _advance(api, _owned(api, parts[1])))
    if (method, len(parts)) == ('POST', 3) and parts[2] == 'cancel':
        payment = _advance(api, _owned(api, parts[1]))
        if payment['status'] in ('awaiting_payment', 'declined'):
            payment['status'] = 'canceled'
        elif payment['status'] in ('authorized', 'paid') and payment['session_id'] is None:
            payment['status'] = 'canceled'
            _settle(payment, 0)
        elif payment['status'] not in ('canceled', 'expired'):
            _fail('O pagamento já está em uma recarga', 'payment_in_use', 409)
        return row(api, payment)
    if (method, len(parts)) == ('POST', 3) and parts[2] == 'demo-checkout':
        # Só na demo: "abrir a Checkout" = pagar com o cartão de teste; confirma em 2 s.
        payment = _owned(api, parts[1])
        if payment['status'] == 'awaiting_payment' and payment['confirm_at'] is None:
            payment['confirm_at'] = api._elapsed + CONFIRM_SECONDS
        return row(api, payment)
    _fail('Operação de pagamento não disponível na demonstração.', 'demo_route_not_supported', 404)


def visitor_payment(api, point, session, totem=False):
    """Pré-pagamento (teste) de um motorista fictício do movimento simulado (``demo_site``): teto de R$ 40,00
    na energia + a reserva do teto da permanência, em uso na sessão; o acerto segue as regras da API.

    ``totem``: pedido do totem de autoatendimento (``origin`` kiosk); simulado quando a conta demo está em
    Modo apresentação (como ``kiosk_totem.method_for`` na API), senão Stripe (teste)."""
    terms = overstay_rules.clean_terms(session.get('overstay_terms'))
    energy = 4000
    reserve = overstay_rules.cents(terms['max_amount']) if terms else 0
    pid = api._id('payment')
    payment = {
        'id': pid, 'status': 'in_use', 'environment': 'test', 'provider': 'stripe', 'origin': 'app',
        'method': 'card', 'currency': billing.CURRENCY, 'amount': str(billing.money(energy + reserve)),
        'energy_cap': str(billing.money(energy)), 'fixed_fee': '0.00', 'overstay_reserve': str(billing.money(reserve)),
        'price_per_kwh': session['price_per_kwh'], 'base_price_per_kwh': session.get('base_price_per_kwh'),
        'demand_multiplier': '1.00', 'discount_percent': 0, 'coupon_code': None,
        'max_duration_minutes': session['max_duration_minutes'], 'max_power_kw': None, 'connector_id': point['id'],
        'session_id': session['id'], 'checkout_url': None, 'expires_at': None, 'start_deadline': None,
        'authorized_at': session['created_at'], 'created_at': session['created_at'],
        'provider_ref': f"pi_demo_{pid.rsplit('-', 1)[-1]}", 'settlement': None,
        'quote': {'mode': 'value', 'max_cost': '40.00', 'reservation_terms': False}, 'confirm_at': None,
        '_visitor': True,
    }
    if totem:
        simulated = api._profile.get('presentation_mode') is True
        payment.update(origin='kiosk', _totem=True, provider='simulated' if simulated else 'stripe',
                       method='simulated' if simulated else 'card',
                       provider_ref=None if simulated else payment['provider_ref'])
    _store(api)[pid] = payment
    return _advance(api, payment)


def advance_visitors(api):
    """Acerto dos pagamentos dos motoristas fictícios (eles não abrem o app; na API é o cron/webhook)."""
    for payment in _store(api).values():
        if payment.get('_visitor'):
            _advance(api, payment)


def reset(api):
    api._payments = {}
