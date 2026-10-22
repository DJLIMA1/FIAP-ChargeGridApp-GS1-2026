import math
from decimal import ROUND_CEILING, Decimal

from chargegrid_core import billing
from chargegrid_core.charge_plan import autonomy_energy, charge_maxima


def test_time_bound_maxima_without_car():
    result = charge_maxima('7.2', '2.30', 120)
    assert result['minutes'] == 120 and result['bound'] == 'time'
    assert result['energy_kwh'] == Decimal('14.400')
    assert result['value'] == Decimal('33.12') and result['km'] is None


def test_battery_bound_maxima_use_free_capacity_and_consumption():
    # 60 kW por 120 min = 120 kWh, mas a bateria só comporta (100-40)% de 44,9 = 26,94 kWh.
    result = charge_maxima('60', '2.27', 120, consumption=14, soc=40, usable_kwh=44.9)
    assert result['bound'] == 'battery' and result['energy_kwh'] == Decimal('26.940')
    assert result['value'] == Decimal('61.15')  # 26,94 x 2,27 = 61,1538 -> para baixo
    assert result['km'] == 192  # 26,94 / 14 x 100 = 192,4


def test_value_is_rounded_down_so_the_maximum_fits_in_the_point_limit():
    for power, price, minutes in (('7.4', '1.89', 37), ('22', '3.33', 90), ('11', '0.07', 1), ('150', '2.99', 13)):
        result = charge_maxima(power, price, minutes)
        cap = billing.quote_cap('value', power_kw=power, price_per_kwh=price, max_cost=result['value'],
                                max_minutes=10_000, min_cents=0)
        assert cap['max_duration_minutes'] <= minutes
        needed = math.ceil(result['value'] / Decimal(price) / Decimal(power) * 60)
        assert needed <= minutes


def test_km_maximum_is_never_capped_by_the_battery():
    result = charge_maxima('60', '2', 120, consumption=14.0, soc=33.3, usable_kwh=44.9)
    plan = autonomy_energy(result['km'], 14.0, 33.3, 44.9)
    assert not plan['capped']
    assert (plan['energy_kwh'] * 60 / Decimal(60)).to_integral_value(rounding=ROUND_CEILING) <= 120


def test_free_tariff_discount_full_battery_and_limits():
    assert charge_maxima('22', '0', 60)['value'] is None
    assert charge_maxima('10', '2', 60, discount_percent=50)['value'] == Decimal('10.00')
    full = charge_maxima('22', '2', 60, consumption=14, soc=100, usable_kwh=50)
    assert full['energy_kwh'] == 0 and full['value'] == 0 and full['km'] == 0
    assert charge_maxima('22', '2', 0)['minutes'] == 1440  # sem limite informado: 24 h
    assert charge_maxima('350', '2', 1440, consumption=1)['km'] == 2000  # teto de parse_km
