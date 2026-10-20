"""Recibo explicável e exportação do histórico do motorista na conta demo (somente memória).

Monta os mesmos "fatos" que a API lê do banco e chama ``chargegrid_core.receipt.build_receipt``:
o app mostra o recibo demo com o mesmo contrato e as mesmas regras do recibo real.

* Termos do preço: travados ao reservar/iniciar (``lock_reservation``/``lock_session``, chamados
  por ``demo.py``), com o motivo da demanda e o cupom, como ``charging_sessions.price_terms``.
* Energia e potência: do simulador local (curva constante na potência simulada do ponto, com
  rampa no primeiro minuto). Sempre rotulada SIMULADO.
* Pagamento: o pagamento Stripe (teste) simulado da sessão (``demo_payments``, no formato da API) ou o
  pré-pagamento simulado do saldo (``services.prepaid`` grava em ``api.chargegrid_prepaid``); ambiente
  ``mock``: nenhum dinheiro real.
"""

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from chargegrid_core import analytics, economics, pricing
from chargegrid_core import receipt as receipts

from .api_client import ApiError

SAMPLE_SECONDS = 60
DEMO_PROVIDER = 'Conta demo (simulado)'
PDF_ONLY_REAL = 'O PDF só é gerado na conta real. Na demo, use o CSV ou veja o recibo na tela.'


def _fail(message, code='not_found', status=404):
    raise ApiError(message, status, code)


def _store(api):
    return api.__dict__.setdefault('_receipt_terms', {})


def _terms_now(api, point, *, locked_by, multiplier=None):
    """Termos com o mesmo cálculo que travou o preço agora (demanda do posto e horário vigente)."""
    station = api._stations[point['station_id']]
    status = api._demand(station)
    rules = pricing.stored_rules(api._pricing.get(station['id']))
    moment = api._now()
    interval = pricing.active_interval(rules, moment.astimezone(analytics.REPORT_TZ))
    base = pricing.base_now(interval, point['id'], point['price_per_kwh'])
    return receipts.price_terms(
        locked_at=moment, locked_by=locked_by, connector_base=point['price_per_kwh'], base=base,
        multiplier=multiplier if multiplier is not None else status['multiplier'], status=status,
        interval=interval, connector_id=point['id'])


def lock_reservation(api, reservation, point):
    """Explicação do preço travado ao reservar (como ``pricing.service.current_terms``)."""
    terms = _terms_now(api, point, locked_by='reservation', multiplier=reservation.get('demand_multiplier'))
    _store(api)[('reservation', reservation['id'])] = (reservation['created_at'], terms)


def lock_session(api, session, point, reservation=None, coupon_code=None):
    """Grava os termos da sessão que está sendo criada (chamar antes de guardá-la em ``_sessions``,
    para a demanda ser a mesma que travou o preço): os da reserva ou os de agora."""
    stored = _store(api).get(('reservation', reservation['id'])) if reservation else None
    if stored and stored[0] == reservation['created_at']:
        terms = dict(stored[1])
    else:
        terms = _terms_now(api, point, locked_by='start', multiplier=session.get('demand_multiplier'))
    if session.get('discount_percent'):
        terms['coupon'] = {'id': None, 'code': str(coupon_code or '').strip().upper() or None,
                           'discount_percent': int(session['discount_percent'])}
    _store(api)[('session', session['id'])] = (session['created_at'], terms)


def session_terms(api, session):
    stored = _store(api).get(('session', session['id']))
    return stored[1] if stored and stored[0] == session['created_at'] else None


def _events(api, session):
    events = list(api._session_events.get(session['id']) or [])
    if events or session['status'] not in receipts.FINAL_STATUSES:
        return events
    # Sessões de exemplo criadas com a conta: o simulador registrou início e fim.
    synthetic = []
    if session.get('started_at'):
        synthetic.append({'kind': 'start_applied', 'source': 'simulator', 'observed_at': session['started_at']})
    if session.get('ended_at'):
        synthetic.append({'kind': 'ended', 'source': 'simulator', 'observed_at': session['ended_at']})
    return synthetic


def _samples(api, session):
    started = analytics.parse_time(session.get('started_at'))
    if started is None:
        return []
    ended = analytics.parse_time(session.get('ended_at')) or api._now()
    seconds = (ended - started).total_seconds()
    if seconds <= 0:
        return []
    runtime = api._session_runtime.get(session['id']) or {}
    kw = Decimal(str(runtime.get('power_kw') or 0))
    if not kw:
        kw = Decimal(str(session.get('energy_wh') or 0)) / 1000 / (Decimal(str(seconds)) / 3600)
    step = max(SAMPLE_SECONDS, int(seconds // 240))
    watts = (kw * 1000).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    samples, offset = [], 0
    while offset <= seconds:
        ramp = Decimal('0.5') if offset == 0 else Decimal(1)
        samples.append({'captured_at': (started + timedelta(seconds=offset)).isoformat(), 'power_w': watts * ramp})
        offset += step
    return samples


def _stripe_payment(api, session):
    """Pagamento Stripe (teste) simulado da sessão no formato do recibo da API
    (``payments.receipt.receipt_payment``); só depois de confirmado, como lá. Ambiente ``mock``."""
    payment = next((item for item in (getattr(api, '_payments', None) or {}).values()
                    if item.get('session_id') == session['id']), None)
    if payment is None or not payment.get('authorized_at'):
        return None
    settlement = payment.get('settlement') or {}
    settled = settlement.get('status') == 'done'

    def money(key):
        return str(economics.cents(settlement.get(key) or 0)) if settled else None
    captured = economics.cents(settlement.get('captured') or 0) if settled else None
    refunded = economics.cents(settlement.get('refunded') or 0) if settled else None
    return {
        'environment': 'mock', 'provider': payment.get('provider'), 'provider_reference': payment.get('provider_ref'),
        'method': payment.get('method'), 'status': payment['status'],
        'settlement_status': settlement.get('status') or 'none',
        'authorized_amount': str(economics.cents(payment['amount'])),
        'captured_amount': money('captured'), 'refunded_amount': money('refunded'),
        'net_amount': str(captured - refunded) if settled else None, 'charged_amount': money('charged'),
        'energy_amount': str(economics.cents(settlement.get('energy_amount') or 0)),
        'overstay_amount': str(economics.cents(settlement.get('overstay_amount') or 0)),
        'waived_amount': money('waived'), 'uncollected_amount': money('uncollected'),
        'below_minimum': bool(settled and settlement.get('below_minimum')), 'provider_fee': None,
        'refund_status': (('refunded' if refunded else 'released' if captured < economics.cents(payment['amount'])
                           else 'none') if settled else 'none'),
        'confirmed_at': payment.get('authorized_at'), 'settled_at': settlement.get('settled_at') if settled else None,
    }


def _payment(api, session):
    stripe = _stripe_payment(api, session)
    if stripe is not None:
        return stripe
    rows = getattr(api, 'chargegrid_prepaid', None)
    row = next((item for item in rows if isinstance(item, dict) and item.get('session_id') == session['id']), None) \
        if isinstance(rows, list) else None
    if row is None or row.get('status') == 'cancelled':
        return None
    amount = economics.cents(row.get('amount')) or Decimal('0.00')
    settled = row.get('status') == 'settled'
    credited = economics.cents(row.get('credited')) or Decimal('0.00')
    return {
        'environment': 'mock', 'provider': DEMO_PROVIDER, 'provider_reference': 'DEMO-' + str(row.get('id', ''))[:8].upper(),
        'method': row.get('method'), 'status': 'settled' if settled else 'paid',
        'authorized_amount': str(amount), 'captured_amount': str(amount),
        'refunded_amount': str(credited) if settled else None,
        'net_amount': str(amount - credited) if settled else None,
        'provider_fee': None, 'refund_status': ('refunded' if credited else 'none') if settled else 'pending',
        'confirmed_at': row.get('created_at'),
    }


def receipt(api, session_id):
    session = api._get(api._sessions, session_id, 'Sessão não encontrada')
    if session.get('user_id') != api._profile.get('id'):
        _fail('Sessão não encontrada')
    point = api._points[session['connector_id']]
    station = api._stations[point['station_id']]
    sections = {}
    payment = _payment(api, session)
    if payment:
        sections['payment'] = payment
    events = _events(api, session)
    result = receipts.build_receipt({
        'session': {**session, 'price_terms': session_terms(api, session)},
        'station': {'name': station['name'], 'address': station['address']},
        'point': {key: point.get(key) for key in ('public_code', 'connector_type', 'power_kw')},
        'events': events, 'samples': _samples(api, session), 'sections': sections,
        'now': api._now(), 'demo': True,
    })
    # Número legível na demo (o real usa os 8 primeiros caracteres do UUID da sessão).
    result['number'] = 'DEMO' + str(session_id).rsplit('-', 1)[-1].zfill(4)[-4:]
    ended = next((event for event in events if event.get('kind') == 'ended'), None)
    energy = result['energy']
    if result['final'] and ended and session.get('last_measurement_at'):
        # O "equipamento" da demo é o simulador: confirma o encerramento, sem fingir medidor.
        energy.update(confirmed_by_device=True, confirmed_at=receipts._iso(ended['observed_at']),
                      note='Energia confirmada pelo equipamento simulado ao encerrar a recarga (conta demo).')
    return result


# ------------------------------------------------------- exportação do histórico

def _window(api, params):
    end = analytics.parse_time((params or {}).get('to')) or api._now()
    start = analytics.parse_time((params or {}).get('from')) or end - timedelta(days=30)
    try:
        analytics.validate_window(start, end)
    except ValueError as exc:
        _fail(str(exc), 'invalid_period', 422)
    return start, end


def history_rows(api, params=None):
    start, end = _window(api, params)
    now = api._now()
    rows = []
    for session in api._sessions.values():
        ended = analytics.parse_time(session.get('ended_at'))
        if session.get('user_id') != api._profile.get('id') or ended is None or not start <= ended < end:
            continue
        point = api._points[session['connector_id']]
        rows.append(receipts.history_row({**session, 'station_name': api._stations[point['station_id']]['name'],
                                          'public_code': point['public_code']}, now))
    rows.sort(key=lambda row: (row['ended_at'] or '', row['id']), reverse=True)
    return rows


def download(api, path, params=None):
    """``me/charging-sessions/export.csv`` local; PDFs (recibo e histórico) só na conta real."""
    if not api.session.access_token:
        _fail('Entre na conta de demonstração para continuar.', 'unauthorized', 401)
    name = path.strip('/').removeprefix('v1/')
    if name.endswith('.pdf'):
        _fail(PDF_ONLY_REAL, 'demo_pdf_unavailable', 404)
    if name != 'me/charging-sessions/export.csv':
        _fail('Exportação não disponível na demonstração.', 'demo_route_not_supported', 404)
    rows = history_rows(api, params)
    return analytics.to_csv(rows, receipts.HISTORY_EXPORT_COLUMNS).encode('utf-8')
