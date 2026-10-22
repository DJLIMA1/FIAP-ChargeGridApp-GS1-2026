"""Limites do posto: limite contratado, margem ESTIMADA da loja e máximo dos carregadores.

Regra pura, sem banco nem rede, usada pela API, pela conta demo, pelo app e pelos testes.

Sem medidor, o consumo da loja que recebe o eletroposto não é medido nem simulado: o dono
informa uma **estimativa fixa** (consumo mínimo e pico típicos). O pico estimado fica
**reservado o tempo todo** (margem de segurança por cima de tudo) e os carregadores dividem
o que sobra do limite contratado:

``para os carregadores = min(máximo dos carregadores, limite contratado − pico estimado)``

O mínimo estimado é informativo (mostrado na régua da tela Limites); ele não libera potência.

Padrões (posto sem valores gravados)
------------------------------------
* Loja: 14–22 kW, uma loja de conveniência média (o padrão da versão anterior).
* Limite contratado: pela REN ANEEL 1.000/2021 (art. 23), unidade em baixa tensão (Grupo B) tem
  carga instalada de até 75 kW; acima disso o atendimento é em média tensão (Grupo A), com demanda
  contratada. Padrão: ``max(75 kW, pico estimado × 1,3)`` arredondado para cima de 10 em 10 kW.

Defesa em profundidade: a validação exige que o pico deixe ao menos o piso de um carro; um dado
inconsistente (gravado por fora da API) nunca reserva mais que ``contratado − 1,4 kW``, então o
posto nunca fica parado por causa da estimativa. A migração d8b3f6a2c5e7 limitou os valores antigos
a 85 % do contratado, o mesmo teto da antiga loja simulada.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from .power import FLOOR_KW, STATION_MAX_KW, floor_for, kw_text, to_kw

LABEL = 'ESTIMATIVA'
DEFAULT_MIN_KW = Decimal(14)
DEFAULT_PEAK_KW = Decimal(22)
GROUP_B_LIMIT_KW = Decimal(75)
LIMIT_MARGIN = Decimal('1.3')
LIMIT_STEP_KW = Decimal(10)
STEP = Decimal('0.1')
ZERO = Decimal(0)
RESERVE_TEXT = 'Reservamos o pico estimado da loja o tempo todo.'


def quantize(value) -> Decimal | None:
    """kW com 1 casa (como a API grava); ``None`` sem valor."""
    number = to_kw(value)
    return None if number is None else number.quantize(STEP, rounding=ROUND_HALF_UP)


def estimate(min_kw=None, peak_kw=None) -> tuple[Decimal, Decimal, bool]:
    """``(mínimo, pico, é o padrão?)`` da loja. Sem nada gravado vale 14–22 kW."""
    low, peak = to_kw(min_kw), to_kw(peak_kw)
    if low is None and peak is None:
        return DEFAULT_MIN_KW, DEFAULT_PEAK_KW, True
    if peak is None:
        peak = max(DEFAULT_PEAK_KW, low)
    if low is None:
        low = min(DEFAULT_MIN_KW, peak)
    peak = max(ZERO, peak)
    return min(max(ZERO, low), peak), peak, False


def default_site_limit_kw(peak_kw=None) -> Decimal:
    """Limite contratado padrão: ``max(75 kW do Grupo B, pico × 1,3)`` em passos de 10 kW."""
    peak = max(ZERO, to_kw(peak_kw) if to_kw(peak_kw) is not None else DEFAULT_PEAK_KW)
    rounded = (peak * LIMIT_MARGIN / LIMIT_STEP_KW).to_integral_value(rounding=ROUND_CEILING) * LIMIT_STEP_KW
    return max(GROUP_B_LIMIT_KW, rounded).quantize(STEP)


def effective_site_limit(configured, peak_kw=None) -> tuple[Decimal, bool]:
    """``(limite em kW, é o padrão?)``: o informado pelo dono ou o padrão pelo pico estimado."""
    value = to_kw(configured)
    if value is not None:
        return value, False
    return default_site_limit_kw(peak_kw), True


def reserve_kw(peak_kw, site_limit_kw=None) -> Decimal:
    """Margem reservada para a loja: o pico estimado, inteiro (nunca deixa menos de 1,4 kW do contratado)."""
    peak = max(ZERO, to_kw(peak_kw) or ZERO)
    limit = to_kw(site_limit_kw)
    if limit is None:
        return peak
    return min(peak, max(ZERO, limit - FLOOR_KW))


def site_inputs(site_limit_kw=None, store_min_kw=None, store_peak_kw=None) -> dict:
    """Entradas efetivas: ``{site_limit_kw, site_limit_default, store_min_kw, store_peak_kw,
    store_estimate_default, store_reserve_kw}``."""
    low, peak, default = estimate(store_min_kw, store_peak_kw)
    limit, limit_default = effective_site_limit(site_limit_kw, peak)
    return {'site_limit_kw': limit, 'site_limit_default': limit_default, 'store_min_kw': low,
            'store_peak_kw': peak, 'store_estimate_default': default,
            'store_reserve_kw': reserve_kw(peak, limit)}


def chargers_budget(site_limit_kw=None, store_min_kw=None, store_peak_kw=None, cap_kw=None) -> Decimal:
    """Potência dos carregadores do posto: ``min(teto, contratado − pico estimado)``, nunca negativa."""
    inputs = site_inputs(site_limit_kw, store_min_kw, store_peak_kw)
    site = max(ZERO, inputs['site_limit_kw'] - inputs['store_reserve_kw'])
    cap = to_kw(cap_kw)
    return site if cap is None else min(site, cap)


def charger_floor(ratings=()) -> Decimal:
    """Menor potência para carregar UM carro no posto: o maior piso entre os conectores ativos."""
    floors = [floor_for(item) for item in ratings or () if (to_kw(item) or ZERO) > 0]
    return max(floors) if floors else FLOOR_KW


def validate(site_limit_kw=None, store_min_kw=None, store_peak_kw=None, ratings=()) -> None:
    """Confere a estimativa contra o limite efetivo; ``ValueError`` com a frase em pt-BR."""
    for value, name in ((store_min_kw, 'mínimo'), (store_peak_kw, 'pico')):
        number = to_kw(value)
        if value is not None and number is None:
            raise ValueError(f'Informe o {name} estimado da loja em kW.')
        if number is not None and number < 0:
            raise ValueError(f'O {name} estimado da loja não pode ser negativo.')
        if number is not None and number > STATION_MAX_KW:
            raise ValueError(f'O {name} estimado da loja deve ser de até 10.000 kW.')
    low, peak = to_kw(store_min_kw), to_kw(store_peak_kw)
    if low is not None and peak is not None and low > peak:
        raise ValueError('O mínimo estimado da loja não pode passar do pico.')
    inputs = site_inputs(site_limit_kw, store_min_kw, store_peak_kw)
    floor = charger_floor(ratings)
    left = inputs['site_limit_kw'] - inputs['store_peak_kw']
    if left < floor:
        raise ValueError(f"Dos {kw_text(inputs['site_limit_kw'])} kW contratados, o pico estimado da loja "
                         f"({kw_text(inputs['store_peak_kw'])} kW) deixa {kw_text(max(ZERO, left))} kW para os "
                         f'carregadores; o mínimo para carregar um carro é {kw_text(floor)} kW.')
