from decimal import Decimal

import pytest

from chargegrid_core import power


def _points(*items):
    return [{'id': f'p{index}', 'power_kw': rating, 'power_limit_kw': limit, **extra}
            for index, (rating, limit, extra) in enumerate(items, 1)]


def test_no_station_cap_uses_port_limits():
    result = power.allocate(_points(('60.000', None, {}), ('22.000', '11', {})))
    assert result['connectors']['p1']['effective_kw'] == Decimal('60.000')
    assert result['connectors']['p1']['power_limited'] is False
    assert result['connectors']['p1']['limited_by'] is None
    assert result['connectors']['p2']['effective_kw'] == Decimal('11')
    assert result['connectors']['p2']['limited_by'] == power.LIMITED_BY_PORT
    assert result['allocated_kw'] == Decimal('71.000')
    assert result['shared'] is False


def test_cap_above_sum_keeps_requests():
    result = power.allocate(_points(('60', None, {}), ('22', None, {})), '100')
    assert [c['effective_kw'] for c in result['connectors'].values()] == [Decimal(60), Decimal(22)]
    assert result['shared'] is False


def test_proportional_share_rounded_down_and_sum_within_cap():
    result = power.allocate(_points(('60', None, {}), ('22', None, {})), '80')
    first, second = (result['connectors'][key] for key in ('p1', 'p2'))
    # 80 x 60/82 = 58.53 -> 58.5 ; 80 x 22/82 = 21.46 -> 21.4
    assert first['effective_kw'] == Decimal('58.5')
    assert second['effective_kw'] == Decimal('21.4')
    assert first['limited_by'] == second['limited_by'] == power.LIMITED_BY_STATION
    assert first['power_limited'] and second['power_limited']
    assert result['allocated_kw'] <= Decimal(80)
    assert result['shared'] is True


def test_share_never_below_floor():
    result = power.allocate(_points(('150', None, {}), ('3', None, {})), '20')
    small = result['connectors']['p2']['effective_kw']
    big = result['connectors']['p1']['effective_kw']
    # Proportional would give 0.39 kW; the floor holds 1.4 kW and the rest goes to the big one.
    assert small == power.FLOOR_KW
    assert big == Decimal('18.6')
    assert small + big <= Decimal(20)


def test_cap_below_all_floors_splits_equally():
    assert power.share({'a': Decimal(22), 'b': Decimal(22), 'c': Decimal(22)}, '3') == {
        'a': Decimal('1.0'), 'b': Decimal('1.0'), 'c': Decimal('1.0')}


def test_inactive_and_retired_ports_are_excluded():
    points = _points(('60', None, {}), ('60', None, {'active': False}), ('60', None, {'retired': True}))
    result = power.allocate(points, '60')
    assert result['connectors']['p1']['effective_kw'] == Decimal(60)
    assert result['connectors']['p2']['effective_kw'] == Decimal(60)  # shows its own request
    assert result['allocated_kw'] == Decimal(60)
    assert result['shared'] is False


def test_clearing_limits_restores_rating():
    points = _points(('60', '30', {}))
    assert power.allocate(points)['connectors']['p1']['effective_kw'] == Decimal(30)
    points[0]['power_limit_kw'] = None
    assert power.allocate(points)['connectors']['p1']['effective_kw'] == Decimal(60)


def test_port_limit_combined_with_station_share():
    result = power.allocate(_points(('60', '40', {}), ('22', None, {})), '50')
    # requests 40 + 22 = 62 > 50 -> 50 x 40/62 = 32.25 ; 50 x 22/62 = 17.74
    assert result['connectors']['p1']['effective_kw'] == Decimal('32.2')
    assert result['connectors']['p2']['effective_kw'] == Decimal('17.7')
    assert result['requested_kw'] == Decimal(62)


def test_validate_port_limit_messages():
    assert power.validate_port_limit('60', None) is None
    assert power.validate_port_limit('60', '40,04') == Decimal('40.0')
    with pytest.raises(ValueError, match='maior que zero'):
        power.validate_port_limit('60', 0)
    with pytest.raises(ValueError, match='potência máxima do carregador \\(60 kW\\)'):
        power.validate_port_limit('60.000', 61)
    with pytest.raises(ValueError, match='mínimo por conector é 1,4 kW'):
        power.validate_port_limit('60', '1')
    # A bench charger smaller than the floor accepts its own rating as minimum.
    assert power.validate_port_limit('1', '1') == Decimal('1.0')


def test_validate_station_max_messages():
    assert power.validate_station_max(None, ['60']) is None
    assert power.validate_station_max('80', ['60', '22']) == Decimal('80.0')
    with pytest.raises(ValueError, match='maior que zero'):
        power.validate_station_max('-1', [])
    with pytest.raises(ValueError, match='pelo menos 2,8 kW para 2 conectores ativos'):
        power.validate_station_max('2', ['60', '22'])
    with pytest.raises(ValueError, match='até 10.000|até 10000'):
        power.validate_station_max('20000', [])


def test_driver_limit_picks_the_bottleneck():
    station_bound = power.driver_limit('40', 'CCS2', max_ac_kw=6.6, max_dc_kw=60)
    assert station_bound == {'kw': Decimal('40'), 'limited_by': 'station'}
    car_bound = power.driver_limit('22', 'Tipo 2', max_ac_kw=6.6, max_dc_kw=60)
    assert car_bound == {'kw': Decimal('6.6'), 'limited_by': 'car'}
    chosen = power.driver_limit('22', 'Tipo 2', max_ac_kw=11, chosen_kw='5')
    assert chosen == {'kw': Decimal('5'), 'limited_by': 'choice'}
    assert power.car_limit('CCS2', max_dc_kw=0) is None


def test_applied_limit_never_exceeds_effective():
    assert power.applied_limit('40', '60') == Decimal('40')
    assert power.applied_limit('40', '11') == Decimal('11')
    assert power.applied_limit('40', None) == Decimal('40')


def test_kw_text():
    assert power.kw_text('60.000') == '60'
    assert power.kw_text('7.40') == '7,4'
    assert power.kw_text(None) == '—'
