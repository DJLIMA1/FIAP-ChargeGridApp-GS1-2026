from chargegrid_core.formatting import brl, duration, km, kwh


def test_formatting_ptbr():
    assert brl(1234.5) == "R$ 1.234,50"
    assert brl(1250, cents=True) == "R$ 12,50"
    assert brl(-3) == "-R$ 3,00"
    assert kwh(12.34) == "12,3 kWh"
    assert duration(95) == "1 h 35 min"
    assert duration(40) == "40 min"
    assert km(3.25) == "3,2 km" or km(3.25) == "3,3 km"
    assert km(42.4) == "42 km"
