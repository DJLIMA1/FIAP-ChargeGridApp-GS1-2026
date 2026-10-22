"""Potência do posto (rebalanceamento) e movimento simulado na conta demo (sem rede).

Responde às rotas do vendedor da API com o mesmo núcleo (``chargegrid_core.balancing`` e
``chargegrid_core.site_load``):

* ``GET stations/{id}/power`` e ``PUT stations/{id}/power-site`` (Limites: limite contratado, margem
  ESTIMADA da loja, máximo dos carregadores, aviso e rebalanceamento), com o registro das últimas
  decisões. Como na API, a loja é uma estimativa fixa (padrão 14–22 kW) e o pico estimado fica
  reservado o tempo todo; ``PUT building-load`` responde 410 (consumo simulado removido);
* rebalanceamento ao vivo: a cada avanço do relógio da demo, com o posto ligado, as sessões em
  recarga recebem o alvo da decisão; o equipamento simulado confirma na hora (aplicada = alvo) e a
  energia passa a ser contada na potência nova;
* ``POST stations/{id}/demo-traffic`` (só na demo): coloca carros de motoristas fictícios no posto,
  um carregando e um que terminou a recarga e continua na vaga (permanência), mais uma recarga paga
  já encerrada no histórico. Com o limite padrão (75 kW) e a margem da loja (22 kW), os carros dividem
  os 53 kW que sobram.

A permanência simulada segue ``chargegrid_core.overstay`` com os termos que valiam no posto quando o
carro começou (taxa desligada = ``no_fee``) e termina quando o motorista fictício "desconecta".
"""

from decimal import ROUND_HALF_UP, Decimal

from chargegrid_core import balancing, billing, pricing, site_load
from chargegrid_core import overstay as overstay_rules
from chargegrid_core import power as power_rules

ALLOCATED = ('starting', 'charging')
ENVELOPED = ('starting', 'charging', 'stopping')
TENTH = Decimal('0.1')
SITE_MAX_KW = Decimal(10000)
DECISIONS_KEPT = 20
# Motoristas fictícios do movimento simulado (primeiro nome + veículo, como ``driver_label`` da API).
VISITORS = ('Ana · BYD Dolphin', 'Carlos · Renault Kwid E-Tech', 'Marina · Volvo EX30', 'Rafael · GWM Ora 03')
CHARGING_MINUTES = 45          # duração pedida pelo carro simulado que está carregando
CHARGED_AGO_MINUTES = 7        # o carro carregando começou há 7 min
OVERSTAY_AGO_MINUTES = 4       # o carro na vaga terminou a recarga há 4 min
OVERSTAY_UNPLUG_MINUTES = 26   # ...e desconecta 26 min depois de terminar
PAST_ENDED_HOURS = 2           # recarga paga já encerrada no histórico


def _fail(message, code, status):
    from .demo import _fail as fail
    fail(message, code, status)


def _kw(value):
    return power_rules.to_kw(value)


def _text(value):
    return None if value is None else str(value)


def _round_kw(value):
    return Decimal(value).quantize(TENTH, rounding=ROUND_HALF_UP)


def site(station):
    """Colunas do posto (``stations``) dos limites, com o padrão da API (ligado, limite e loja padrão)."""
    station.setdefault('rebalance_enabled', True)
    station.setdefault('site_limit_kw', None)
    station.setdefault('store_min_kw', None)
    station.setdefault('store_peak_kw', None)
    station.setdefault('max_power_kw', None)
    station.setdefault('power_limit_notify', False)
    return station


def inputs(api, station):
    """Limite efetivo e margem ESTIMADA da loja, como ``power.service.site_inputs`` da API."""
    site(station)
    return site_load.site_inputs(_kw(station['site_limit_kw']), _kw(station['store_min_kw']),
                                 _kw(station['store_peak_kw']))


def _ratings(api, station):
    return [p['power_kw'] for p in api._points.values()
            if p['station_id'] == station['id'] and p.get('active', True) and not p.get('retired')]


# ------------------------------------------------------------------ sessões do posto
def _station_points(api, station_id):
    return sorted((p for p in api._points.values() if p['station_id'] == station_id), key=lambda p: p['public_code'])


def _sessions(api, station_id, statuses=ALLOCATED):
    ids = {p['id'] for p in _station_points(api, station_id)}
    return sorted((s for s in api._sessions.values() if s['connector_id'] in ids and s['status'] in statuses),
                  key=lambda s: (s['created_at'], s['id']))


def _runtime_power(api, session):
    runtime = api._session_runtime.get(session['id']) or {}
    value = runtime.get('power_kw')
    return Decimal(value) if value is not None else None


def _envelope(api, session):
    """Maior potência que ainda pode estar no ponto: a aplicada confirmada ou a do início."""
    applied = session.get('applied_power_kw')
    if applied is not None:
        return Decimal(applied)
    return _runtime_power(api, session) or Decimal(0)


def _decide(api, station):
    participants = []
    for session in _sessions(api, station['id']):
        point = api._points[session['connector_id']]
        participants.append(balancing.Participant(
            id=session['id'], rating_kw=Decimal(point['power_kw']), port_limit_kw=_kw(point.get('power_limit_kw')),
            driver_kw=_kw(session.get('requested_power_kw')), floor_kw=power_rules.floor_for(point['power_kw']),
            order=(session['created_at'], session['id'])))
    now = inputs(api, station)
    return balancing.decide(participants, site_limit_kw=now['site_limit_kw'],
                            store_reserve_kw=now['store_reserve_kw'], station_cap_kw=station.get('max_power_kw'))


def _labels(api, station_id):
    return {s['id']: api._points[s['connector_id']]['public_code'] for s in _sessions(api, station_id, ENVELOPED)}


def _record(api, station, decision):
    """Registro de decisões (como ``power_decisions``): grava só quando entradas ou alvos mudam."""
    envelopes = {s['id']: _envelope(api, s) for s in _sessions(api, station['id'], ENVELOPED)}
    snap = balancing.snapshot(decision, envelopes)
    digest = balancing.fingerprint(snap)
    log = api._power_decisions.setdefault(station['id'], [])
    if log and log[0]['input_hash'] == digest:
        return log[0]
    api._counter += 1
    row = {'id': api._counter, 'created_at': api._iso(), 'trigger': balancing.trigger(log[0]['inputs'] if log else None,
                                                                                      snap),
           'available_kw': _text(decision['available_kw']),
           'exceeded_kw': _text(balancing.exceeded(envelopes.values(), decision['available_kw'])),
           'summary': balancing.summary(decision, _labels(api, station['id'])), 'inputs': snap, 'input_hash': digest}
    log.insert(0, row)
    del log[DECISIONS_KEPT:]
    return row


def _apply(api, session, kw):
    """O equipamento simulado confirma a potência nova; a energia segue contada na potência anterior até agora."""
    runtime = api._session_runtime.get(session['id'])
    if runtime is None or runtime.get('power_kw') == kw:
        return
    if api._elapsed > runtime['start_at']:
        runtime['energy_base_wh'] = Decimal(session['energy_wh'])
        runtime['power_since'] = api._elapsed
    runtime['power_kw'] = kw


def _refresh(api, station):
    """Recalcula o posto: com o rebalanceamento ligado, aplica os alvos; sempre registra a decisão."""
    decision = _decide(api, station)
    targets = {}
    if station.get('rebalance_enabled'):
        for session in _sessions(api, station['id']):
            target = Decimal(decision['sessions'][session['id']]['target_kw']).quantize(Decimal('0.001'))
            reason = balancing.explain(decision, session['id'])
            session.update(target_power_kw=str(target), applied_power_kw=str(target),
                           power_state='paused' if target == 0 else 'applied', power_reason=reason['text'][:300],
                           power_reason_short=reason['short'][:60], power_reason_code=reason['code'])
            _apply(api, session, target)
            targets[session['id']] = session
    row = _record(api, station, decision)
    for session in targets.values():
        session['power_decision_id'] = row['id']


def tick(api):
    """Rebalanceamento ao vivo dos postos com a chave ligada (chamado a cada avanço do relógio da demo)."""
    if getattr(api, '_payments', None):
        from . import demo_payments
        demo_payments.advance_visitors(api)
    for station in list(api._stations.values()):
        if station.get('rebalance_enabled'):
            _refresh(api, station)


def start_check(api, station, point):
    """Início com o rebalanceamento ligado: sem potência para o carro novo, 409 ``site_power_full`` (como a API)."""
    if not station.get('rebalance_enabled'):
        return
    probe = '~probe'
    participants = [balancing.Participant(
        id=s['id'], rating_kw=Decimal(api._points[s['connector_id']]['power_kw']),
        port_limit_kw=_kw(api._points[s['connector_id']].get('power_limit_kw')),
        driver_kw=_kw(s.get('requested_power_kw')),
        floor_kw=power_rules.floor_for(api._points[s['connector_id']]['power_kw']),
        order=(s['created_at'], s['id'])) for s in _sessions(api, station['id'])]
    participants.append(balancing.Participant(id=probe, rating_kw=Decimal(point['power_kw']),
                                              port_limit_kw=_kw(point.get('power_limit_kw')),
                                              floor_kw=power_rules.floor_for(point['power_kw']),
                                              order=('~', probe)))
    now = inputs(api, station)
    decision = balancing.decide(participants, site_limit_kw=now['site_limit_kw'],
                                store_reserve_kw=now['store_reserve_kw'], station_cap_kw=station.get('max_power_kw'))
    if decision['sessions'][probe]['target_kw'] <= 0:
        reason = balancing.explain(decision, probe)['text'].removeprefix('Pausado: ')
        _fail('Sem potência disponível agora: ' + reason + ' Tente novamente em alguns minutos.',
              'site_power_full', 409)


# ------------------------------------------------------------------ visão do vendedor
def view(api, station):
    """``GET /stations/{id}/power``: entradas, divisão atual, estado por ponto e últimas decisões."""
    now = inputs(api, station)
    decision = _decide(api, station)
    active = {s['connector_id']: s for s in _sessions(api, station['id'], ENVELOPED)}
    envelopes = {s['id']: _envelope(api, s) for s in active.values()}
    points = []
    for point in _station_points(api, station['id']):
        device = api._device_for(point['id'])
        entry = {'connector_id': point['id'], 'public_code': point['public_code'], 'power_kw': point['power_kw'],
                 'online': bool(device and device['online']), 'adjustable': True, 'charger': None, 'session': None}
        session = active.get(point['id'])
        if session:
            item = decision['sessions'].get(session['id'])
            reason = balancing.explain(decision, session['id']) if item else None
            entry['session'] = {
                'id': session['id'], 'status': session['status'],
                'target_kw': _text(item['target_kw']) if item else None,
                'applied_kw': session.get('applied_power_kw'), 'envelope_kw': _text(envelopes[session['id']]),
                'power_state': session.get('power_state'),
                'reason': reason['text'] if reason else session.get('power_reason'),
                'reason_short': reason['short'] if reason else session.get('power_reason_short'),
                'reason_code': reason['code'] if reason else session.get('power_reason_code'),
            }
        points.append(entry)
    total = sum(envelopes.values(), Decimal(0))
    log = api._power_decisions.get(station['id'], [])
    ratings = _ratings(api, station)
    return {
        'station_id': station['id'], 'rebalance_enabled': station['rebalance_enabled'],
        'site_limit_kw': _text(now['site_limit_kw']), 'site_limit_default': now['site_limit_default'],
        'site_limit_configured_kw': station['site_limit_kw'],
        'site_limit_default_kw': _text(site_load.default_site_limit_kw(now['store_peak_kw'])),
        'store_min_kw': _text(now['store_min_kw']), 'store_peak_kw': _text(now['store_peak_kw']),
        'store_reserve_kw': _text(now['store_reserve_kw']), 'store_estimate_default': now['store_estimate_default'],
        'store_estimate_label': site_load.LABEL, 'building_load_kw': _text(now['store_reserve_kw']),
        'station_cap_kw': _text(_kw(station.get('max_power_kw'))),
        'power_limit_notify': bool(station.get('power_limit_notify')),
        'connectors_total_kw': _text(sum((Decimal(str(value)) for value in ratings), Decimal(0))),
        'charger_floor_kw': _text(site_load.charger_floor(ratings)),
        'chargers_floor_total_kw': _text(sum((power_rules.floor_for(value) for value in ratings), Decimal(0))),
        'available_kw': _text(decision['available_kw']), 'allocated_kw': _text(decision['allocated_kw']),
        'envelope_kw': _text(total),
        'exceeded_kw': _text(balancing.exceeded(envelopes.values(), decision['available_kw'])),
        'cars': decision['cars'], 'points': points,
        'decisions': [{key: item[key] for key in ('id', 'created_at', 'trigger', 'available_kw', 'exceeded_kw',
                                                  'summary')} for item in log],
    }


def _decimal_input(value, message):
    try:
        number = Decimal(str(value))
    except (ArithmeticError, ValueError, TypeError):
        _fail(message, 'validation_error', 422)
    if not number.is_finite():
        _fail(message, 'validation_error', 422)
    return number


SITE_FIELDS = {'site_limit_kw', 'rebalance_enabled', 'store_min_kw', 'store_peak_kw', 'max_power_kw',
               'power_limit_notify', 'building_profile', 'building_size'}


def set_site(api, station, body):
    """``PUT power-site``: Limites num só salvamento, validados no estado final (como a API)."""
    if not isinstance(body, dict) or set(body) - SITE_FIELDS:
        _fail('Envie site_limit_kw, store_min_kw, store_peak_kw, max_power_kw, power_limit_notify e/ou '
              'rebalance_enabled.', 'validation_error', 422)
    site(station)
    changes = {}
    if 'site_limit_kw' in body:
        value = body['site_limit_kw']
        if value is not None:
            value = _decimal_input(value, 'Informe o limite contratado em kW.')
            if value <= 0:
                _fail('Informe um limite contratado maior que zero.', 'invalid_power_limit', 422)
            value = _round_kw(value)
            if value > SITE_MAX_KW:
                _fail('O limite contratado deve ser de até 10.000 kW.', 'invalid_power_limit', 422)
            value = str(value)
        changes['site_limit_kw'] = value
    for key in ('store_min_kw', 'store_peak_kw'):
        if key in body:
            value = body[key]
            if value is not None:
                value = str(_round_kw(_decimal_input(value, 'Informe a estimativa da loja em kW.')))
            changes[key] = value
    for key in ('rebalance_enabled', 'power_limit_notify'):
        if key in body:
            if not isinstance(body[key], bool):
                _fail('Campo não aceita null', 'null_not_allowed', 422)
            changes[key] = body[key]
    ratings = _ratings(api, station)
    if 'max_power_kw' in body:
        try:
            cap = power_rules.validate_station_max(body['max_power_kw'], ratings)
        except ValueError as exc:
            _fail(str(exc), 'invalid_power_limit', 422)
        changes['max_power_kw'] = None if cap is None else format(cap.quantize(Decimal('0.001')), 'f')
    final = {**station, **changes}
    if {'site_limit_kw', 'store_min_kw', 'store_peak_kw'} & set(changes):
        try:
            site_load.validate(_kw(final['site_limit_kw']), _kw(final['store_min_kw']), _kw(final['store_peak_kw']),
                               ratings)
        except ValueError as exc:
            _fail(str(exc), 'invalid_store_estimate', 422)
    station.update(changes)  # building_profile/building_size: descontinuados, ignorados
    _refresh(api, station)


def route(api, method, parts, body):
    """``stations/{id}/power|power-site|demo-traffic`` da demo (``building-load``: 410, como a API)."""
    station = api._owned(parts[1])
    action = parts[2]
    if (method, action) == ('GET', 'power'):
        return view(api, station)
    if (method, action) == ('PUT', 'power-site'):
        set_site(api, station, body)
        return view(api, station)
    if (method, action) == ('PUT', 'building-load'):
        _fail('A loja agora é uma margem estimada: informe o mínimo e o pico estimados em Limites.',
              'store_load_removed', 410)
    if (method, action) == ('POST', 'demo-traffic'):
        traffic(api, station)
        return view(api, station)
    _fail('Operação não disponível na demonstração.', 'demo_route_not_supported', 404)


# ------------------------------------------------------------------ permanência simulada
def _open(api, session):
    info = session.get('_overstay')
    return bool(info) and api._elapsed < info['unplug']


def open_overstay(api, point_id):
    """Sessão com o carro ainda na vaga depois da recarga neste ponto (ou ``None``)."""
    return next((s for s in api._sessions.values() if s['connector_id'] == point_id and _open(api, s)), None)


def overstay_view(api, session):
    """Bloco ``overstay`` da sessão (``app.overstay.view``) com a contagem simulada do cabo conectado."""
    terms = overstay_rules.clean_terms(session.get('overstay_terms'))
    info = session.get('_overstay')
    if not info:
        return {'status': 'none', 'fee_applies': terms is not None, 'started_at': None, 'ended_at': None,
                'end_reason': None, 'billable_seconds': 0, 'billable_minutes': 0, 'grace_remaining_seconds': 0,
                'fee_due': '0.00', 'max_fee': terms['max_amount'] if terms else None, 'as_of': None,
                'terms': overstay_rules.public(terms) if terms else None}
    closed = api._elapsed >= info['unplug']
    last = min(api._elapsed, info['unplug'])
    seconds = int(max(0, last - info['start']))
    status = overstay_rules.phase(terms, seconds, closed=closed)
    return {'status': status, 'fee_applies': terms is not None, 'started_at': api._iso(info['start']),
            'ended_at': api._iso(info['unplug']) if closed else None, 'end_reason': 'disconnected' if closed else None,
            'billable_seconds': seconds, 'billable_minutes': overstay_rules.billable_minutes(terms, seconds),
            'grace_remaining_seconds': overstay_rules.grace_remaining_seconds(terms, seconds)
            if status in ('grace', 'billing', 'capped') else 0,
            'fee_due': str(overstay_rules.fee_due(terms, seconds)),
            'max_fee': terms['max_amount'] if terms else None, 'as_of': api._iso(last),
            'terms': overstay_rules.public(terms) if terms else None}


def overstay_final(api, session):
    """O valor da permanência não muda mais (sem permanência, desconectado ou no teto)."""
    info = session.get('_overstay')
    if not info or api._elapsed >= info['unplug']:
        return True
    shown = overstay_view(api, session)
    return shown['status'] == 'capped'


def overstay_cents(api, session):
    return billing.to_cents(overstay_view(api, session)['fee_due'])


def occupancy(api, point_id):
    """``occupancy`` do ponto em ``/owner/live`` (``app.overstay.occupancy_by_connector``) ou ``None``."""
    session = open_overstay(api, point_id)
    if session is None:
        return None
    shown = overstay_view(api, session)
    return {'session_id': session['id'], 'status': shown['status'], 'started_at': shown['started_at'],
            'grace_remaining_seconds': shown['grace_remaining_seconds'],
            'billable_minutes': shown['billable_minutes'], 'fee_due': shown['fee_due'], 'max_fee': shown['max_fee'],
            'fee_applies': shown['fee_applies'], 'driver_label': session.get('_driver_label') or 'Motorista',
            'as_of': shown['as_of']}


# ------------------------------------------------------------------ movimento simulado
def _free(api, station):
    result = []
    for point in _station_points(api, station['id']):
        row = api._point_row(point)
        if row['available'] and point['active'] and not point['retired']:
            result.append(point)
    return sorted(result, key=lambda p: (-Decimal(p['power_kw']), p['public_code']))


def _visitor_session(api, point, *, label, status, started, ended=None, energy_wh='0.000', soc=None):
    station = api._stations[point['station_id']]
    base = str(api._scheduled_base(point, api._now()))
    price = str(pricing.dynamic_price(base, api._demand(station)['multiplier']))
    effective = Decimal(price)
    sid = api._id('session')
    cost = (Decimal(energy_wh) / 1000 * effective).quantize(Decimal('0.0001'))
    session = {
        'id': sid, 'user_id': f"demo-visitor-{sid.rsplit('-', 1)[-1]}", 'connector_id': point['id'],
        'reservation_id': None, 'status': status, 'created_at': api._iso(started - 1),
        'started_at': api._iso(started), 'ended_at': api._iso(ended) if ended is not None else None,
        'max_duration_minutes': CHARGING_MINUTES, 'max_cost': None, 'price_per_kwh': price,
        'base_price_per_kwh': base, 'demand_multiplier': '1.00', 'discount_percent': 0, 'energy_wh': energy_wh,
        'soc_percent': soc, 'start_soc_percent': None, 'battery_kwh': None, 'soc_source': None,
        'source': 'simulated', 'last_measurement_at': api._iso(ended if ended is not None else started),
        'cost_estimate': str(cost), 'end_reason': 'requested' if ended is not None else None,
        'power_limit_kw': None, 'requested_power_kw': None,
        'overstay_terms': api._overstay_terms(station), '_driver_label': label,
    }
    api._sessions[sid] = session
    api._event(sid, 'start_requested', at=session['created_at'])
    return session


def _finished(api, point, *, label, ended, minutes, unplug, paid, totem=False):
    """Recarga encerrada por um motorista fictício, com permanência até ``unplug`` (s do relógio da demo)."""
    started = ended - minutes * 60
    power = min(Decimal(point['power_kw']), Decimal('22'))
    energy = (power * 1000 * minutes / 60 * Decimal('0.9')).quantize(Decimal('0.001'))
    session = _visitor_session(api, point, label=label, status='completed', started=started, ended=ended,
                               energy_wh=str(energy), soc='80.00')
    session['_overstay'] = {'start': ended, 'unplug': unplug}
    api._event(session['id'], 'start_applied', at=session['started_at'])
    api._event(session['id'], 'ended', at=session['ended_at'])
    if paid:
        from . import demo_payments
        demo_payments.visitor_payment(api, point, session, totem=totem)
    return session


def traffic(api, station):
    """Movimento simulado (só na demo): um carro carregando, um na vaga depois da recarga e uma recarga
    paga já encerrada no histórico. Idempotente enquanto o movimento anterior continua no posto."""
    site(station)
    ids = {p['id'] for p in _station_points(api, station['id'])}
    if any(s.get('_driver_label') and s['connector_id'] in ids and (s['status'] in ENVELOPED or _open(api, s))
           for s in api._sessions.values()):
        return
    free = _free(api, station)
    if not free:
        _fail('Nenhum ponto livre e online para simular carros neste posto.', 'point_unavailable', 409)
    now = api._elapsed
    first_visit = not any(s.get('_driver_label') and s['connector_id'] in ids for s in api._sessions.values())
    if first_visit:
        # Recarga paga de 1 h atrás (histórico do vendedor: pagamento acertado e permanência encerrada).
        _finished(api, free[-1], label=VISITORS[3], ended=now - PAST_ENDED_HOURS * 3600, minutes=35,
                  unplug=now - PAST_ENDED_HOURS * 3600 + 14 * 60, paid=True,
                  totem=station.get('kiosk_mode') is True)  # totem ligado: a recarga paga veio do totem
    charging, parked = (free[:-1], free[-1]) if len(free) > 1 else (free, None)
    for index, point in enumerate(charging[:2]):
        start = now - CHARGED_AGO_MINUTES * 60
        session = _visitor_session(api, point, label=VISITORS[index], status='starting',
                                   started=start)
        session['started_at'] = None
        api._session_runtime[session['id']] = {'start_at': start, 'power_kw': Decimal(point['power_kw'])}
    if parked is not None:
        ended = now - OVERSTAY_AGO_MINUTES * 60
        _finished(api, parked, label=VISITORS[2], ended=ended, minutes=32,
                  unplug=ended + OVERSTAY_UNPLUG_MINUTES * 60, paid=True)
    api._advance()
    _refresh(api, station)
