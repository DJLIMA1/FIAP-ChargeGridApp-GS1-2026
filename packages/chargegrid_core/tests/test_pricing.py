from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from chargegrid_core import pricing

TUESDAY_NOON = datetime(2026, 10, 20, 12, 0)
TUESDAY_PEAK = datetime(2026, 10, 20, 19, 0)


def status(rules=None, **signals):
    base = {"connectors": 4, "in_use": 0, "reserved": 0, "busy_15m": 0, "starts_60m": 0, "baseline_60m": 0,
            "local_now": TUESDAY_NOON}
    return pricing.demand_status(rules or {}, {**base, **signals})


def test_idle_or_half_busy_station_keeps_the_base_price():
    assert status()["multiplier"] == "1.00" and status()["level"] == "low"
    # Metade ocupada e um pouco de movimento: ruído, sem acréscimo.
    assert status(in_use=2, busy_15m=Decimal("0.5"), starts_60m=1, baseline_60m=1)["multiplier"] == "1.00"


def test_price_rises_smoothly_with_occupancy_trend_and_queue():
    mild = status(in_use=3, busy_15m=Decimal("0.6"), starts_60m=2, baseline_60m=2)
    busy = status(in_use=4, busy_15m=Decimal("0.9"), starts_60m=6, baseline_60m=2)
    queue = status(in_use=3, reserved=1, busy_15m=Decimal("0.9"), starts_60m=6, baseline_60m=2)
    values = [Decimal(item["multiplier"]) for item in (mild, busy, queue)]
    assert Decimal(1) < values[0] < values[1] <= values[2] <= Decimal("1.50")
    assert all((value * 100) % 5 == 0 for value in values)  # passos de 0,05×
    assert queue["level"] == "very_high" and queue["pressure"] > busy["pressure"] - 1


def test_owner_cap_sensitivity_and_switch():
    signals = {"in_use": 4, "busy_15m": Decimal("1"), "starts_60m": 9, "baseline_60m": 1, "reserved": 0}
    assert status({"demand": {"max_increase_percent": 30}}, **signals)["multiplier"] == "1.30"
    assert status({"demand": {"enabled": False}}, **signals)["multiplier"] == "1.00"
    moderate = {"in_use": 3, "busy_15m": Decimal("0.7"), "starts_60m": 3, "baseline_60m": 2}
    low = Decimal(status({"demand": {"sensitivity": "low"}}, **moderate)["multiplier"])
    high = Decimal(status({"demand": {"sensitivity": "high"}}, **moderate)["multiplier"])
    assert low < high


def test_peak_window_is_a_signal_not_a_fixed_extra():
    quiet_peak = status(local_now=TUESDAY_PEAK)
    assert quiet_peak["peak_now"] is True and quiet_peak["multiplier"] == "1.00"  # pico sozinho, posto vazio
    busy = {"in_use": 3, "busy_15m": Decimal("0.7"), "starts_60m": 3, "baseline_60m": 2}
    assert Decimal(status(local_now=TUESDAY_PEAK, **busy)["multiplier"]) > Decimal(status(**busy)["multiplier"])
    overnight = {"peak": {"start": "22:00", "end": "02:00", "days": [1]}}
    assert pricing.in_peak(pricing.clean_rules(overnight)["peak"], datetime(2026, 10, 20, 23, 30))
    assert not pricing.in_peak(pricing.clean_rules(overnight)["peak"], datetime(2026, 10, 21, 12, 0))


def test_busy_fraction_is_time_weighted_over_the_window():
    now = datetime(2026, 10, 20, 12, 0)
    intervals = [(now - timedelta(minutes=30), None), (now - timedelta(minutes=5), None),
                 (now - timedelta(minutes=40), now - timedelta(minutes=20))]
    # 15 min + 5 min ocupados em 2 conectores × 15 min.
    assert pricing.busy_fraction(intervals, now, 2) == Decimal(20) / Decimal(30)
    assert pricing.busy_fraction([], now, 0) == 0


def test_clean_rules_validates_owner_input_in_portuguese():
    rules = pricing.clean_rules({"demand": {"max_increase_percent": "40"}, "rotation": {"amount": "0.2"}})
    assert rules["demand"]["max_increase_percent"] == 40 and rules["rotation"]["amount"] == "0.20"
    for bad, message in (({"demand": {"max_increase_percent": 150}}, "100%"),
                         ({"demand": {"sensitivity": "turbo"}}, "sensibilidade"),
                         ({"peak": {"start": "25:00"}}, "00:00"),
                         ({"peak": {"start": "18:00", "end": "18:00"}}, "diferentes"),
                         ({"peak": {"days": []}}, "dia"),
                         ({"rotation": {"interval_min": 0}}, "1440")):
        with pytest.raises(ValueError, match=message):
            pricing.clean_rules(bad)
    assert pricing.stored_rules({"demand": {"max_increase_percent": 999}}) == pricing.DEFAULT_RULES


def test_price_and_labels():
    assert pricing.dynamic_price("1.89", "1.30") == Decimal("2.4570")
    assert pricing.multiplier_label("1.30") == "1,3×" and pricing.multiplier_label("1.00") == "1×"
    assert pricing.days_label([0, 1, 2, 3, 4, 5, 6]) == "Todos os dias"
    assert pricing.days_label([4, 5]) == "Sex e Sáb"
