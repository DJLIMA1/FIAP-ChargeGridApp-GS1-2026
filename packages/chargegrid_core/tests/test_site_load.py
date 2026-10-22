"""Limites do posto: margem ESTIMADA da loja (fixa, sem medidor nem simulação) e limite contratado."""

from decimal import Decimal as D

import pytest

from chargegrid_core import balancing, power, site_load


def test_store_estimate_defaults_to_a_medium_convenience_store():
    assert site_load.estimate() == (D(14), D(22), True)
    assert site_load.estimate('5', '30') == (D(5), D(30), False)
    assert site_load.estimate(None, '10') == (D(10), D(10), False)  # mínimo nunca passa do pico
    assert site_load.estimate('30', None) == (D(30), D(30), False)
    assert site_load.LABEL == 'ESTIMATIVA' and 'o tempo todo' in site_load.RESERVE_TEXT


def test_default_contracted_limit_follows_group_b_and_margin_over_the_peak():
    assert site_load.default_site_limit_kw() == D(75)
    assert site_load.default_site_limit_kw(22) == D(75)
    assert site_load.default_site_limit_kw(100) == D(130)   # 100 × 1,3
    assert site_load.default_site_limit_kw(160) == D(210)   # 208 → 210
    assert site_load.effective_site_limit(None) == (D(75), True)
    assert site_load.effective_site_limit('40.5', 22) == (D('40.5'), False)


def test_reserve_is_the_whole_peak_all_the_time():
    assert site_load.reserve_kw(22, 75) == D(22)
    assert site_load.reserve_kw(22) == D(22)
    assert site_load.reserve_kw('28.6', 30) == D('28.6')   # o que a validação aceita vale inteiro
    assert site_load.reserve_kw(750, 75) == D('73.6')      # dado inconsistente: sobra o piso de um carro


def test_chargers_budget_is_contract_minus_peak_capped_by_the_chargers_max():
    assert site_load.chargers_budget() == D(53)                       # padrões: 75 − 22
    assert site_load.chargers_budget(75, 14, 22, 40) == D(40)         # o teto manda
    assert site_load.chargers_budget(30, 0, 12) == D(18)
    assert site_load.chargers_budget(None, 89.6, 160) == D(50)        # 210 − 160
    inputs = site_load.site_inputs()
    assert inputs == {'site_limit_kw': D(75), 'site_limit_default': True, 'store_min_kw': D(14),
                      'store_peak_kw': D(22), 'store_estimate_default': True, 'store_reserve_kw': D(22)}


def test_validation_messages():
    site_load.validate(75, 14, 22, ['7.4'])
    site_load.validate(None, None, None, ['7.4'])
    with pytest.raises(ValueError, match='não pode passar do pico'):
        site_load.validate(75, 30, 22)
    with pytest.raises(ValueError, match='negativo'):
        site_load.validate(75, -1, 22)
    with pytest.raises(ValueError, match='deixa 0,5 kW para os carregadores; o mínimo para carregar um carro é 1,4'):
        site_load.validate(30, 10, '29.5', ['22'])
    with pytest.raises(ValueError, match='deixa 0 kW'):
        site_load.validate(30, 10, 40)
    with pytest.raises(ValueError, match='10.000'):
        site_load.validate(None, 0, 20000)
    assert site_load.charger_floor(['0.7']) == D('0.7') and site_load.charger_floor([]) == power.FLOOR_KW


def test_lab_station_with_defaults_and_a_7kw_charger_keeps_full_power():
    """Central real (posto sem valores gravados + HCA 7 kW): 53 kW disponíveis, o carro recebe 7 kW cheios."""
    inputs = site_load.site_inputs()
    car = balancing.Participant(id='hca', rating_kw=D(7), order=(1,))
    decision = balancing.decide([car], site_limit_kw=inputs['site_limit_kw'],
                                store_reserve_kw=inputs['store_reserve_kw'])
    assert decision['available_kw'] == D(53)
    assert decision['sessions']['hca']['target_kw'] == D(7)
    static = power.allocate([{'id': 'hca', 'power_kw': '7'}], site_load.chargers_budget())
    assert static['connectors']['hca']['effective_kw'] == D(7)
