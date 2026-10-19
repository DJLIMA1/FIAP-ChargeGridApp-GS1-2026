"""Limites de potência: posto inteiro, cada conector e o motorista.

Mesma regra na API, na conta demo e no app (o app recalcula ao vivo enquanto o
vendedor move os controles). Tudo em ``Decimal``; aceita números ou textos da API.

Regra de alocação
-----------------
1. Cada conector tem a potência nominal ``power_kw`` (o máximo que o carregador
   consegue enviar; nunca é alterada por limites) e, opcionalmente, um limite do
   vendedor ``power_limit_kw``. Pedido = ``min(power_kw, power_limit_kw)``.
2. O posto pode ter um teto ``max_power_kw`` compartilhado pelos conectores que
   participam (ativos/publicados e não aposentados):
   * Σ pedidos ≤ teto → cada conector recebe o próprio pedido;
   * senão, divisão proporcional ao pedido (a soma fica ≤ teto), arredondada
     para baixo em passos de 0,1 kW e nunca abaixo do piso de 1,4 kW (6 A em
     230 V, a menor corrente de recarga AC da IEC 61851) — ou do próprio pedido,
     se for menor. Quem ficaria abaixo do piso recebe o piso e o restante do teto
     é redividido proporcionalmente entre os demais ("enchimento");
   * se o teto não comporta o piso de todos (ex.: conector ativado depois do
     teto salvo), o teto é dividido igualmente (arredondado para baixo).
3. Conectores fora da divisão (inativos/aposentados) exibem o próprio pedido.
4. Efetivo do conector = ``min(power_kw, power_limit_kw, parcela do posto)``.
5. Motorista: ``min(efetivo do conector, carro (DC: max_dc_kw / AC: max_ac_kw),
   escolha do assistente)``. A API aplica esse valor no início da recarga.

O limite vale para o próximo início de recarga: uma recarga em andamento mantém
a potência com que começou.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation

from .driver.vehicles import is_dc

FLOOR_KW = Decimal('1.4')
STEP = Decimal('0.1')
CONNECTOR_MAX_KW = Decimal('1000')
STATION_MAX_KW = Decimal('10000')

LIMITED_BY_STATION = 'station'
LIMITED_BY_PORT = 'port'


def to_kw(value) -> Decimal | None:
    """``"60.000"``/``60``/``7,4`` → ``Decimal``; vazio ou inválido → ``None``."""
    if value is None or value == '':
        return None
    try:
        number = Decimal(str(value).strip().replace(',', '.'))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _down(value: Decimal) -> Decimal:
    return value.quantize(STEP, rounding=ROUND_DOWN)


def floor_for(rating) -> Decimal:
    """Piso por conector: 1,4 kW (ou a própria nominal, se o carregador for menor)."""
    rating = to_kw(rating) or Decimal(0)
    return min(FLOOR_KW, rating) if rating > 0 else FLOOR_KW


def requested_kw(rating, limit=None) -> Decimal:
    """Pedido do conector: nominal, reduzida pelo limite do vendedor quando houver."""
    rating = to_kw(rating) or Decimal(0)
    limit = to_kw(limit)
    return min(rating, limit) if limit is not None and limit > 0 else rating


def share(requests: dict, cap) -> dict:
    """Parcela de cada participante sob o teto ``cap`` (ver regra 2 do módulo)."""
    cap = to_kw(cap)
    requests = {key: max(Decimal(0), to_kw(value) or Decimal(0)) for key, value in requests.items()}
    if cap is None or not requests or sum(requests.values()) <= cap:
        return dict(requests)
    floors = {key: min(floor_for(value), value) for key, value in requests.items()}
    if sum(floors.values()) > cap:
        each = _down(cap / len(requests))
        return {key: min(value, each) for key, value in requests.items()}
    fixed, free = {}, dict(requests)
    shares = {}
    while free:
        budget = cap - sum(fixed.values())
        total = sum(free.values())
        shares = {key: (budget * value / total if total > 0 else Decimal(0)) for key, value in free.items()}
        low = [key for key, value in shares.items() if value < floors[key]]
        if not low:
            break
        for key in low:
            fixed[key] = floors[key]
            free.pop(key)
            shares.pop(key)
    result = dict(fixed)
    result.update({key: _down(min(requests[key], value)) for key, value in shares.items()})
    return result


def allocate(points, station_max=None) -> dict:
    """Potência efetiva de cada conector de um posto.

    ``points``: mapeamentos com ``id``, ``power_kw``, ``power_limit_kw`` e, opcional,
    ``participates`` (padrão: ``active`` não falso e não ``retired``).
    Devolve ``{'connectors': {id: {requested_kw, effective_kw, power_limited, limited_by}},
    'allocated_kw', 'requested_kw', 'shared'}`` (valores ``Decimal``).
    """
    points = list(points or [])
    requested, participants = {}, {}
    for point in points:
        key = point['id']
        requested[key] = requested_kw(point.get('power_kw'), point.get('power_limit_kw'))
        joins = point.get('participates')
        if joins is None:
            joins = point.get('active') is not False and not point.get('retired')
        if joins:
            participants[key] = requested[key]
    cap = to_kw(station_max)
    shares = share(participants, cap) if cap is not None else dict(participants)
    total_requested = sum(participants.values(), Decimal(0))
    connectors = {}
    for point in points:
        key = point['id']
        rating = to_kw(point.get('power_kw')) or Decimal(0)
        effective = shares.get(key, requested[key])
        limited_by = (LIMITED_BY_STATION if effective < requested[key]
                      else LIMITED_BY_PORT if requested[key] < rating else None)
        connectors[key] = {'requested_kw': requested[key], 'effective_kw': effective,
                           'power_limited': effective < rating, 'limited_by': limited_by}
    return {'connectors': connectors, 'allocated_kw': sum(shares.values(), Decimal(0)),
            'requested_kw': total_requested,
            'shared': cap is not None and total_requested > cap}


def kw_text(value) -> str:
    """``Decimal('40.0')`` → ``'40'``; ``7.4`` → ``'7,4'`` (sem a unidade)."""
    number = to_kw(value)
    if number is None:
        return '—'
    number = number.quantize(STEP, rounding=ROUND_HALF_UP)
    text = f'{number:f}'
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    return text.replace('.', ',')


def validate_port_limit(rating, limit) -> Decimal | None:
    """Limite de um conector (``None`` limpa). Levanta ``ValueError`` com mensagem pt-BR."""
    if limit is None:
        return None
    value = to_kw(limit)
    if value is None:
        raise ValueError('Informe o limite de potência em kW (ex.: 40).')
    if value <= 0:
        raise ValueError('Informe um limite de potência maior que zero.')
    rating = to_kw(rating) or Decimal(0)
    value = value.quantize(STEP, rounding=ROUND_HALF_UP)
    if value > rating:
        raise ValueError(f'O limite não pode passar da potência máxima do carregador ({kw_text(rating)} kW).')
    minimum = floor_for(rating)
    if value < minimum:
        raise ValueError(f'O limite mínimo por conector é {kw_text(minimum)} kW.')
    return value


def validate_station_max(value, ratings=()) -> Decimal | None:
    """Teto do posto (``None`` limpa). ``ratings``: nominais dos conectores ativos."""
    if value is None:
        return None
    number = to_kw(value)
    if number is None:
        raise ValueError('Informe o limite do posto em kW (ex.: 80).')
    if number <= 0:
        raise ValueError('Informe um limite do posto maior que zero.')
    number = number.quantize(STEP, rounding=ROUND_HALF_UP)
    if number > STATION_MAX_KW:
        raise ValueError(f'O limite do posto deve ser de até {kw_text(STATION_MAX_KW)} kW.')
    ratings = [to_kw(item) or Decimal(0) for item in ratings]
    minimum = sum((floor_for(item) for item in ratings), Decimal(0))
    if number < minimum:
        count = len(ratings)
        plural = 'conectores ativos' if count != 1 else 'conector ativo'
        raise ValueError(f'O limite do posto precisa ser de pelo menos {kw_text(minimum)} kW para '
                         f'{count} {plural} (mínimo de {kw_text(FLOOR_KW)} kW por conector).')
    return number


def car_limit(connector_type, *, max_ac_kw=None, max_dc_kw=None) -> Decimal | None:
    """Potência máxima que o carro aceita neste tipo de conector (DC ou AC)."""
    value = to_kw(max_dc_kw if is_dc(connector_type or '') else max_ac_kw)
    return value if value is not None and value > 0 else None


def driver_limit(effective_kw, connector_type=None, *, max_ac_kw=None, max_dc_kw=None, chosen_kw=None) -> dict:
    """Limite geral do motorista: ``min(efetivo do conector, carro, escolha)``.

    Devolve ``{'kw', 'limited_by'}`` com ``limited_by`` = ``'choice'``, ``'car'``,
    ``'station'`` (o conector/posto é o gargalo) ou ``None``.
    """
    effective = to_kw(effective_kw) or Decimal(0)
    candidates = [('station', effective)]
    car = car_limit(connector_type, max_ac_kw=max_ac_kw, max_dc_kw=max_dc_kw)
    if car is not None:
        candidates.append(('car', car))
    chosen = to_kw(chosen_kw)
    if chosen is not None and chosen > 0:
        candidates.append(('choice', chosen))
    kind, value = min(candidates, key=lambda item: (item[1], {'choice': 0, 'car': 1, 'station': 2}[item[0]]))
    return {'kw': value, 'limited_by': kind}


def applied_limit(effective_kw, requested_kw=None) -> Decimal:
    """Limite aplicado no início: o pedido do motorista nunca passa do efetivo do conector."""
    effective = to_kw(effective_kw) or Decimal(0)
    requested = to_kw(requested_kw)
    if requested is None or requested <= 0:
        return effective
    return min(effective, requested)
