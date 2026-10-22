"""Tela Potência do vendedor, sem Flet: textos e contas sobre ``GET /stations/{id}/power``.

Mesmas regras da API (``chargegrid_core.site_load`` e ``chargegrid_core.power``):

* **Limites** num só lugar: limite contratado (o do dono ou o padrão), margem ESTIMADA da loja
  (mínimo e pico; sem medidor, o pico fica reservado o tempo todo) e máximo dos carregadores.
  ``para os carregadores = min(máximo dos carregadores, contratado − pico estimado)``.
* A régua da tela Limites: escala, passos, segmentos e as travas de cada faixa de arrastar
  (``move_store``/``move_limit``/``move_cap``), além do corpo do ``PUT power-site``.
* Potência configurada × efetiva de cada carregador.
"""

from decimal import Decimal, InvalidOperation

from chargegrid_core import power as power_rules
from chargegrid_core import site_load

POLL_SECONDS = 3             # atualização do cartão enquanto a tela está aberta
SITE_MAX_KW = Decimal(10000)
REBALANCE_HELP = 'Divide a potência entre os carros sem passar dos limites do posto.'
ESTIMATE_HELP = ('Não medimos a loja: é uma estimativa sua. Reservamos o pico estimado o tempo todo, '
                 'por cima de tudo, e os carregadores dividem o que sobra.')
ZERO = Decimal(0)
NICE_STEPS = ('1', '1.2', '1.5', '2', '2.5', '3', '4', '5', '6', '8', '10')


def number(value):
    """``'28.5'`` -> ``Decimal('28.5')``; vazio/inválido -> ``None``."""
    if value is None or value == '':
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() else None


def kw(value, empty='—'):
    """``6 kW``, ``28,5 kW`` (até 1 casa, como a API arredonda) ou ``empty``."""
    amount = number(value)
    if amount is None:
        return empty
    return f'{power_rules.kw_text(amount.quantize(Decimal("0.1")))} kW'


def has_rebalance(station):
    """A API manda as colunas do rebalanceamento no posto (``rebalance_enabled``)."""
    return isinstance((station or {}).get('rebalance_enabled'), bool)


def station_limits(station):
    """Entradas efetivas e potência dos carregadores pelo posto (``GET stations/{id}``), como a API."""
    station = station or {}
    inputs = site_load.site_inputs(number(station.get('site_limit_kw')), number(station.get('store_min_kw')),
                                   number(station.get('store_peak_kw')))
    inputs['budget_kw'] = site_load.chargers_budget(inputs['site_limit_kw'], inputs['store_min_kw'],
                                                    inputs['store_peak_kw'], number(station.get('max_power_kw')))
    return inputs


def menu_subtitle(station):
    """Subtítulo do menu do posto: ``Até 53 kW para os carregadores · rebalanceamento ligado``."""
    head = f"Até {kw(station_limits(station)['budget_kw'])} para os carregadores"
    return f"{head} · rebalanceamento {'ligado' if station.get('rebalance_enabled') else 'desligado'}"


def summary(view):
    """Cartão do topo: disponível, limite contratado, margem ESTIMADA da loja e carros agora."""
    used = number(view.get('envelope_kw'))
    if used is None:
        used = number(view.get('allocated_kw')) or ZERO
    exceeded = max(ZERO, number(view.get('exceeded_kw')) or ZERO)
    count = int(view.get('cars') or 0)
    reserve = number(view.get('store_reserve_kw'))
    if reserve is None:
        reserve = number(view.get('store_peak_kw'))
    store_detail = 'Pico estimado, reservado o tempo todo'
    if view.get('store_estimate_default'):
        store_detail += ' (padrão)'
    return {
        'available': kw(view.get('available_kw'), 'Sem limite'),
        'limit': kw(view.get('site_limit_kw'), 'Sem limite'),
        'limit_detail': 'Padrão (75 kW ou pico × 1,3)' if view.get('site_limit_default') else 'Informado por você',
        'store': f'−{kw(reserve, "0 kW")}',
        'store_detail': store_detail,
        'cars': kw(used, '0 kW'),
        'cars_detail': 'Nenhum carro carregando' if not count else f"{count} carro{'s' if count != 1 else ''} carregando",
        'over': (f'Excesso transitório de {kw(exceeded)}: reduções enviadas, aguardando os equipamentos.'
                 if exceeded > 0 else None),
    }


def limits_subtitle(view):
    """``Contratado 75 kW · loja até 22 kW · carregadores até 53 kW``."""
    peak = view.get('store_reserve_kw') or view.get('store_peak_kw')
    return (f"Contratado {kw(view.get('site_limit_kw'))} · loja até {kw(peak)} · "
            f"carregadores até {kw(view.get('available_kw'))}")


def cap_subtitle(station):
    """``Sem teto · aviso desligado`` ou ``80 kW · aviso ligado`` (API antiga, sem Limites)."""
    cap = power_rules.to_kw((station or {}).get('max_power_kw'))
    head = 'Sem teto' if cap is None else kw(cap)
    return f"{head} · aviso {'ligado' if station.get('power_limit_notify') else 'desligado'}"


def points(station):
    return [point for point in (station or {}).get('connectors') or [] if not point.get('retired')]


def point_name(point, index):
    """``CCS2 · Carregador 1``: o número é o endereço do carregador (dono) ou a posição no posto."""
    address = point.get('charger_address') or index
    return f"{point.get('connector_type') or 'Carregador'} · Carregador {address}"


def connector_line(point, station, view=None):
    """``60 kW configurados · 47 kW efetivos`` (carregando) ou ``... · até 55 kW efetivos`` (livre)."""
    if point.get('active') is False:
        return 'Inativo: fica fora da divisão do posto'
    configured = power_rules.requested_kw(point.get('power_kw'), point.get('power_limit_kw'))
    head = f'{kw(configured)} configurados'
    session = next(((item.get('session') or {}) for item in (view or {}).get('points') or []
                    if item.get('connector_id') == point.get('id')), {})
    if session:
        effective = number(session.get('applied_kw'))
        effective = number(session.get('target_kw')) if effective is None else effective
        if effective is not None:
            return f'{head} · {kw(effective)} efetivos'
    shared = power_rules.allocate(points(station), station.get('max_power_kw'))['connectors'].get(point.get('id'))
    effective = shared['effective_kw'] if shared else configured
    available = number((view or {}).get('available_kw'))
    if available is not None and available < effective:
        effective = available
    return f"{head} · até {kw(effective)} efetivos"


def limit_input(value):
    """Valor da API -> texto do campo (``75,5``; vazio sem valor)."""
    amount = number(value)
    if amount is None:
        return ''
    return power_rules.kw_text(amount.quantize(Decimal('0.1')))


def parse_kw(text, *, allow_zero=False):
    """kW digitado (``75,5``) -> ``(Decimal | None, erro | None)``; vazio = ``(None, None)``."""
    raw = str(text or '').strip()
    if not raw:
        return None, None
    cleaned = raw.replace(',', '.')
    parts = cleaned.split('.')
    if len(parts) > 2 or not parts[0].isdigit() or len(parts[0]) > 5 or \
            (len(parts) == 2 and (not parts[1].isdigit() or len(parts[1]) != 1)):
        return None, 'Use kW com até 1 casa, por exemplo 75,5.'
    amount = Decimal(cleaned)
    if amount < 0 or (amount == 0 and not allow_zero):
        return None, 'Informe um valor maior que zero.'
    if amount > SITE_MAX_KW:
        return None, 'Os valores vão até 10.000 kW.'
    return amount, None


# ---------------------------------------------------------------- régua da tela Limites
def scale_max(limit, peak=ZERO, total=ZERO):
    """Fim da régua: ``max(contratado, 20) × 1,25`` arredondado para cima (1/1,2/1,5/2/2,5/3/4/5/6/8 × 10ⁿ).

    ``peak``/``total`` ficam na assinatura por compatibilidade: a régua acompanha só o contratado (o pico
    nunca passa dele), para a parte útil ocupar ~80 % da largura."""
    top = max(Decimal(limit or 0), Decimal(20)) * Decimal('1.25')
    magnitude = Decimal(10) ** (len(str(int(top))) - 1)
    for factor in NICE_STEPS:
        candidate = Decimal(factor) * magnitude
        if candidate >= top:
            return candidate.quantize(Decimal(1))
    return (Decimal(10) * magnitude).quantize(Decimal(1))


def step_for(scale):
    """Passo do arraste: 1 kW até 200 kW de escala, 5 kW até 1.000, 10 kW acima."""
    scale = Decimal(scale)
    return Decimal(1) if scale <= 200 else Decimal(5) if scale <= 1000 else Decimal(10)


def snap(value, step):
    """Valor do controle no passo da régua (kW, nunca negativo)."""
    step = Decimal(step)
    amount = Decimal(str(round(float(value) / float(step)))) * step
    return max(ZERO, amount.quantize(Decimal('0.1')))


def limits_state(view, station=None):
    """Rascunho da tela Limites a partir de ``GET power`` (valores efetivos e padrões)."""
    station = station or {}
    total = number(view.get('connectors_total_kw'))
    if total is None:
        total = sum((power_rules.to_kw(point.get('power_kw')) or ZERO for point in points(station)
                     if point.get('active') is not False), ZERO)
    floor = number(view.get('charger_floor_kw')) or power_rules.FLOOR_KW
    floor_total = number(view.get('chargers_floor_total_kw')) or floor
    cap = number(view.get('station_cap_kw'))
    if cap is None and 'station_cap_kw' not in view:
        cap = power_rules.to_kw(station.get('max_power_kw'))
    notify = view.get('power_limit_notify')
    if notify is None:
        notify = bool(station.get('power_limit_notify'))
    low, peak, default = number(view.get('store_min_kw')), number(view.get('store_peak_kw')), \
        bool(view.get('store_estimate_default'))
    if peak is None:
        low, peak, default = site_load.estimate()
    state = {
        'limit': number(view.get('site_limit_kw')) or site_load.default_site_limit_kw(peak),
        'limit_default': bool(view.get('site_limit_default')),
        'min': min(site_load.DEFAULT_MIN_KW, peak) if low is None else low, 'peak': peak,
        'store_default': default, 'cap': cap, 'notify': bool(notify),
        'total': total, 'floor': floor, 'floor_total': floor_total,
    }
    rescale(state)
    return state


def rescale(state):
    """Recalcula a escala e o passo da régua (ao abrir e depois de digitar valores)."""
    state['scale'] = scale_max(state['limit'], state['peak'], state['total'])
    state['step'] = step_for(state['scale'])


def remainder(state):
    """Contratado − pico estimado (o que a loja deixa para os carregadores)."""
    return max(ZERO, state['limit'] - state['peak'])


def budget(state):
    """Potência dos carregadores: ``min(teto, contratado − pico)``."""
    left = remainder(state)
    return left if state['cap'] is None else min(left, state['cap'])


def cap_top(state):
    """Valor a partir do qual o teto não muda nada (vira "sem teto próprio")."""
    left = remainder(state)
    return min(left, state['total']) if state['total'] > 0 else left


def move_store(state, low, high):
    """Arraste da faixa da loja (mínimo e pico): o pico deixa ao menos o piso de um carro."""
    hint = None
    high = snap(high, state['step'])
    top = max(ZERO, state['limit'] - state['floor'])
    if high > top:
        high, hint = top, 'Para reservar mais para a loja, aumente o limite contratado.'
    low = min(snap(low, state['step']), high)
    state.update(min=low, peak=high, store_default=False)
    return hint


def move_limit(state, value):
    """Arraste do limite contratado: nunca abaixo do pico da loja + o piso de um carro."""
    hint = None
    value = snap(value, state['step'])
    bottom = state['peak'] + state['floor']
    if value < bottom:
        value, hint = bottom, 'Para baixar mais o contratado, reduza o pico estimado da loja.'
    state.update(limit=value, limit_default=False)
    return hint


def move_cap(state, value):
    """Arraste do máximo dos carregadores: no fim da faixa = sem teto próprio (``None``)."""
    value = snap(value, state['step'])
    hint = None
    if value < state['floor_total']:
        value, hint = state['floor_total'], f"O mínimo é {kw(state['floor_total'])} (piso de cada carregador)."
    state['cap'] = None if value >= cap_top(state) else value
    return hint


def set_values(state, limit, low, peak, cap):
    """Valores digitados (diálogo "Digitar valores"): ``None`` em ``cap`` = sem teto. Devolve o erro ou ``None``."""
    if low > peak:
        return 'O mínimo estimado da loja não pode passar do pico.'
    if limit - peak < state['floor']:
        return (f"O pico da loja precisa deixar ao menos {kw(state['floor'])} do contratado para os carregadores.")
    if cap is not None and cap < state['floor_total']:
        return f"O máximo dos carregadores precisa ser de pelo menos {kw(state['floor_total'])}."
    state.update(limit=limit, limit_default=False, min=low, peak=peak, store_default=False)
    state['cap'] = None if cap is None or cap >= cap_top(state) else cap
    rescale(state)
    return None


def cap_text(state):
    """``53 kW · sem teto`` (sem teto próprio: tudo que sobra, ou todos no máximo) ou ``40 kW``."""
    if state['cap'] is None or state['cap'] >= cap_top(state):
        return f'{kw(cap_top(state))} · sem teto'
    return kw(state['cap'])


def store_text(state):
    """``14 – 22 kW``."""
    return f"{power_rules.kw_text(state['min'])} – {kw(state['peak'])}"


def equation(state):
    """``75 kW contratados − 22 kW de margem da loja`` (+ teto quando ele manda)."""
    text = f"{kw(state['limit'])} contratados − {kw(state['peak'])} de margem da loja"
    if state['cap'] is not None and state['cap'] < remainder(state):
        text += " · limitado pelo máximo dos carregadores"
    return text


def segments(state, used=None):
    """Faixas da régua em kW, da esquerda para a direita: ``[(chave, kW)]`` (as de 0 kW somem).

    ``store_base`` (0→mínimo), ``store_peak`` (mínimo→pico), ``cars`` (em uso agora, só na visão
    geral), ``chargers``, ``unused`` (bloqueado pelo teto) e ``above`` (acima do contratado)."""
    left = remainder(state)
    chargers = budget(state)
    in_use = min(max(ZERO, Decimal(used or 0)), chargers)
    items = [('store_base', state['min']), ('store_peak', state['peak'] - state['min']),
             ('cars', in_use), ('chargers', chargers - in_use), ('unused', left - chargers),
             ('above', max(ZERO, state['scale'] - state['limit']))]
    return [(key, value) for key, value in items if value > 0]


def body(state, original):
    """Corpo do ``PUT power-site`` com o que mudou em relação a ``original`` (``limits_state``)."""
    result = {}
    if not state['limit_default'] and (original['limit_default'] or state['limit'] != original['limit']):
        result['site_limit_kw'] = f"{state['limit']:.1f}"
    elif state['limit_default'] and not original['limit_default']:
        result['site_limit_kw'] = None
    store_changed = (state['min'], state['peak']) != (original['min'], original['peak'])
    if state['store_default'] and not original['store_default']:
        result.update(store_min_kw=None, store_peak_kw=None)
    elif not state['store_default'] and (store_changed or original['store_default']):
        result.update(store_min_kw=f"{state['min']:.1f}", store_peak_kw=f"{state['peak']:.1f}")
    if state['cap'] != original['cap']:
        result['max_power_kw'] = None if state['cap'] is None else f"{state['cap']:.1f}"
    if state['notify'] != original['notify']:
        result['power_limit_notify'] = state['notify']
    return result


def restore_defaults(state):
    """Botão "Restaurar padrão": loja 14–22 kW, contratado padrão e sem teto próprio."""
    low, peak, _ = site_load.estimate()
    state.update(min=low, peak=peak, store_default=True, limit=site_load.default_site_limit_kw(peak),
                 limit_default=True, cap=None)
    rescale(state)
