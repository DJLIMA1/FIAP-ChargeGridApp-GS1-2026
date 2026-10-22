from decimal import Decimal

import pytest

from chargegrid_core import billing


def test_cents_round_half_up_and_back():
    assert billing.to_cents(Decimal('12.345')) == 1235
    assert billing.to_cents('0.004') == 0
    assert billing.money(1235) == Decimal('12.35')
    assert billing.format_money(123456) == 'R$ 1.234,56'


def test_energy_cents_matches_api_cost_estimate():
    # 1234,5 Wh × R$ 2,00 × (100 − 10) % = R$ 2,2221 → 222 centavos.
    assert billing.energy_cost(Decimal('1234.5'), Decimal('2'), 10) == Decimal('2.2221')
    assert billing.energy_cents(Decimal('1234.5'), Decimal('2'), 10) == 222


def test_quote_by_time_rounds_up_so_the_time_fits():
    quote = billing.quote_cap('time', power_kw=7, price_per_kwh=Decimal('1.99'), minutes=30)
    # 3,5 kWh × 1,99 = 6,965 → 697 centavos (para cima).
    assert quote == {'energy_cap_cents': 697, 'max_duration_minutes': 30, 'energy_kwh': Decimal('3.500')}


def test_quote_by_value_with_coupon_derives_duration():
    quote = billing.quote_cap('value', power_kw=10, price_per_kwh=2, discount_percent=50, max_cost='20',
                              max_minutes=600)
    # Tarifa efetiva R$ 1,00 → 20 kWh → 120 min a 10 kW.
    assert quote['energy_cap_cents'] == 2000
    assert quote['max_duration_minutes'] == 120
    assert quote['energy_kwh'] == Decimal('20.000')


def test_quote_by_energy_is_capped_by_point_duration():
    quote = billing.quote_cap('energy', power_kw=1, price_per_kwh=2, energy_kwh='5', max_minutes=60)
    assert quote['energy_cap_cents'] == 1000
    assert quote['max_duration_minutes'] == 60


def test_quote_free_energy_uses_point_limit():
    quote = billing.quote_cap('value', power_kw=1, price_per_kwh=0, max_cost='10', max_minutes=45)
    assert quote['max_duration_minutes'] == 45


@pytest.mark.parametrize('kwargs', [
    {'mode': 'time'}, {'mode': 'value', 'max_cost': '0'}, {'mode': 'energy'}, {'mode': 'other', 'minutes': 5},
    {'mode': 'value', 'max_cost': '0.49'},
])
def test_quote_rejects_missing_or_too_small(kwargs):
    mode = kwargs.pop('mode')
    with pytest.raises(ValueError):
        billing.quote_cap(mode, power_kw=7, price_per_kwh=2, **kwargs)


def test_settle_card_partial_capture():
    result = billing.settle_amounts(amount_cents=2000, energy_cents=1240)
    assert result == {'charge_cents': 1240, 'return_cents': 760, 'waived_cents': 0, 'uncollected_cents': 0,
                      'below_minimum': False, 'action': 'capture'}


def test_settle_pix_refunds_difference_or_nothing():
    assert billing.settle_amounts(amount_cents=2000, energy_cents=1240, captured_upfront=True)['action'] == 'refund'
    full = billing.settle_amounts(amount_cents=2000, energy_cents=2000, captured_upfront=True)
    assert (full['action'], full['return_cents']) == ('none', 0)


def test_settle_zero_energy_cancels():
    result = billing.settle_amounts(amount_cents=2000, energy_cents=0)
    assert (result['charge_cents'], result['return_cents'], result['action']) == (0, 2000, 'cancel')


def test_settle_below_minimum_is_waived():
    result = billing.settle_amounts(amount_cents=2000, energy_cents=23)
    assert result['below_minimum'] is True
    assert (result['charge_cents'], result['waived_cents'], result['action']) == (0, 23, 'cancel')


def test_settle_never_exceeds_authorized_amount():
    result = billing.settle_amounts(amount_cents=2000, energy_cents=2013)
    assert (result['charge_cents'], result['waived_cents'], result['return_cents']) == (2000, 13, 0)


def test_settle_overstay_inside_and_beyond_reserve():
    inside = billing.settle_amounts(amount_cents=2500, energy_cents=1800, overstay_cents=300)
    assert (inside['charge_cents'], inside['uncollected_cents'], inside['return_cents']) == (2100, 0, 400)
    beyond = billing.settle_amounts(amount_cents=2500, energy_cents=1800, overstay_cents=900)
    assert (beyond['charge_cents'], beyond['uncollected_cents']) == (2500, 200)


def test_settle_energy_above_cap_is_waived_even_with_overstay_reserve():
    # Teto da energia R$ 10,00 + reserva da permanência R$ 30,00: a energia acima do teto aceito é
    # perdoada (antes saía da reserva da permanência e o motorista pagava R$ 10,40).
    plan = billing.settle_amounts(amount_cents=4000, energy_cents=1040, overstay_cents=0, energy_cap_cents=1000)
    assert (plan['charge_cents'], plan['waived_cents'], plan['return_cents']) == (1000, 40, 3000)
    full = billing.settle_amounts(amount_cents=4000, energy_cents=1040, overstay_cents=3000, energy_cap_cents=1000)
    assert (full['charge_cents'], full['waived_cents'], full['uncollected_cents']) == (4000, 40, 0)
    inside = billing.settle_amounts(amount_cents=4000, energy_cents=800, overstay_cents=500, energy_cap_cents=1000)
    assert (inside['charge_cents'], inside['waived_cents'], inside['return_cents']) == (1300, 0, 2700)
    fee = billing.settle_amounts(amount_cents=4490, energy_cents=1100, fixed_fee_cents=490, energy_cap_cents=1000)
    assert (fee['charge_cents'], fee['waived_cents']) == (1490, 100)


def test_settle_fixed_fee_is_kept():
    result = billing.settle_amounts(amount_cents=2490, energy_cents=0, fixed_fee_cents=490)
    assert (result['charge_cents'], result['return_cents']) == (490, 2000)


def test_status_labels_reach_the_driver_without_test_marks():
    assert billing.status_label('authorized') == 'Pago'
    assert billing.status_label('completed', charge_cents=140, return_cents=1860) == \
        'Cobrado R$ 1,40 · Devolvido R$ 18,60'
    assert billing.status_label('completed', charge_cents=0, return_cents=2000) == 'Devolvido'
    assert billing.status_label('expired', method='card') == 'Expirado · valor devolvido'
