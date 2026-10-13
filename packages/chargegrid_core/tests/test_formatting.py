from decimal import Decimal

from chargegrid_core.formatting import brl, duration, km, kwh


def test_formatting_ptbr():
    assert brl(1234.5) == "R$ 1.234,50"
    assert brl(1250, cents=True) == "R$ 12,50"
    assert brl(-3) == "-R$ 3,00"
    assert kwh(12.34) == "12,3 kWh"
    assert duration(95) == "1 h 35 min"
    assert duration(40) == "40 min"
    assert km(3.25) == "3,3 km"
    assert km(42.4) == "42 km"


def test_money_rounds_half_up_not_binary_float():
    # f"{2.675:.2f}" == "2.67" and f"{0.125:.2f}" == "0.12" (binary/banker's rounding).
    assert brl(2.675) == "R$ 2,68"
    assert brl(0.125) == "R$ 0,13"
    assert brl(1.005) == "R$ 1,01"
    assert brl(-0.001) == "R$ 0,00"


def test_accepts_api_decimal_strings_and_rejects_garbage():
    assert brl("3.6000") == "R$ 3,60"
    assert brl(Decimal("1234567.891")) == "R$ 1.234.567,89"
    assert brl("abc") == "—"
    assert brl(float("nan")) == "—"
    assert brl(None) == "—"
    assert kwh("2400.000") == "2.400,0 kWh"
    assert kwh(None) == "—"


def test_km_and_duration_edges():
    assert km(9.96) == "10 km"
    assert km(9.94) == "9,9 km"
    assert km(1234) == "1.234 km"
    assert duration(0.5) == "1 min"
    assert duration(-4) == "0 min"
    assert duration(120) == "2 h"
