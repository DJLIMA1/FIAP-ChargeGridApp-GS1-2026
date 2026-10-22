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


def test_legacy_peak_is_accepted_but_no_longer_changes_the_price():
    busy = {"in_use": 3, "busy_15m": Decimal("0.7"), "starts_60m": 3, "baseline_60m": 2}
    legacy = {"peak": {"enabled": True, "start": "18:00", "end": "21:00", "days": [1]}}
    at_peak = status(legacy, local_now=TUESDAY_PEAK, **busy)
    assert at_peak["peak_now"] is False and at_peak["multiplier"] == status(**busy)["multiplier"]
    assert all(factor["key"] != "peak" for factor in at_peak["factors"])
    # Regras antigas salvas no banco (sem ``schedule``) continuam válidas.
    stored = pricing.stored_rules({"demand": {"max_increase_percent": 30}, **legacy})
    assert stored["peak"]["days"] == [1] and stored["schedule"] == {"enabled": True, "intervals": []}


NIGHT = {"start": "22:00", "end": "06:00", "days": [0, 1, 2, 3, 4], "prices": {"cg-01": "1.2", "cg-02": 1.6}}
EVENING = {"start": "18:00", "end": "21:00", "days": [5, 6], "prices": {"cg-01": "2.5"}}


def schedule(*intervals, enabled=True):
    return {"schedule": {"enabled": enabled, "intervals": list(intervals)}}


def test_schedule_is_validated_sorted_and_normalized():
    rules = pricing.clean_rules(schedule(EVENING, NIGHT))
    night, evening = rules["schedule"]["intervals"]
    assert night == {"start": "22:00", "end": "06:00", "days": [0, 1, 2, 3, 4],
                     "prices": {"cg-01": "1.2000", "cg-02": "1.6000"}, "enabled": True}
    assert evening["days"] == [5, 6] and evening["prices"] == {"cg-01": "2.5000"}
    for bad, message in ((schedule({**NIGHT, "end": "22:00"}), "diferentes"),
                         (schedule({**NIGHT, "days": []}), "ao menos um dia"),
                         (schedule({**NIGHT, "days": [7]}), "Dias"),
                         (schedule({**NIGHT, "start": "24:00"}), "00:00"),
                         (schedule({**NIGHT, "prices": {}}), "Informe a tarifa"),
                         (schedule({**NIGHT, "prices": {"cg-01": "150"}}), "R\\$ 100,00"),
                         (schedule({**NIGHT, "prices": {"cg-01": "abc"}}), "R\\$ 0,00"),
                         (schedule({**NIGHT, "enabled": "false"}), "Status do horário"),
                         (schedule(*[{**EVENING, "days": [d % 7], "start": f"{h:02d}:00", "end": f"{h:02d}:30"}
                                     for d, h in zip(range(13), range(13))]), "no máximo 12"),
                         ({"schedule": {"intervals": "x"}}, "inválidos")):
        with pytest.raises(ValueError, match=message):
            pricing.clean_rules(bad)


def test_overlapping_intervals_are_rejected_including_overnight_and_week_wrap():
    same_day = {"start": "20:00", "end": "23:00", "days": [5], "prices": {"cg-01": "2"}}
    with pytest.raises(ValueError, match=r"18:00–21:00 e 20:00–23:00 se sobrepõem \(Sáb\)"):
        pricing.clean_rules(schedule(EVENING, same_day))
    # Seg 22:00–06:00 invade a manhã de terça.
    tuesday_morning = {"start": "05:00", "end": "08:00", "days": [1], "prices": {"cg-01": "2"}}
    with pytest.raises(ValueError, match=r"\(Ter\)"):
        pricing.clean_rules(schedule({**NIGHT, "days": [0]}, tuesday_morning))
    # Dom 22:00–02:00 continua na segunda de madrugada.
    monday_dawn = {"start": "01:00", "end": "03:00", "days": [0], "prices": {"cg-01": "2"}}
    with pytest.raises(ValueError, match=r"\(Seg\)"):
        pricing.clean_rules(schedule({**NIGHT, "days": [6], "end": "02:00"}, monday_dawn))
    # Encostados (21:00 termina, 21:00 começa) não se sobrepõem.
    touching = {"start": "21:00", "end": "23:00", "days": [5, 6], "prices": {"cg-01": "2"}}
    assert len(pricing.clean_rules(schedule(EVENING, touching))["schedule"]["intervals"]) == 2


def test_active_interval_belongs_to_the_day_it_starts():
    rules = pricing.clean_rules(schedule({**NIGHT, "days": [0]}))  # só segunda à noite
    monday_night, tuesday_dawn = datetime(2026, 10, 19, 23, 0), datetime(2026, 10, 20, 5, 59)
    assert pricing.active_interval(rules, monday_night)["index"] == 0
    assert pricing.active_interval(rules, tuesday_dawn)["start"] == "22:00"
    assert pricing.active_interval(rules, datetime(2026, 10, 20, 6, 0)) is None  # fim exclusivo
    assert pricing.active_interval(rules, datetime(2026, 10, 19, 2, 0)) is None  # domingo não está nos dias
    assert pricing.active_interval(rules, None) is None
    off = pricing.clean_rules(schedule({**NIGHT, "days": [0]}, enabled=False))
    assert pricing.active_interval(off, monday_night) is None
    wrap = pricing.clean_rules(schedule({**NIGHT, "days": [6], "end": "00:00"}))  # domingo 22:00–00:00
    assert pricing.active_interval(wrap, datetime(2026, 10, 25, 23, 30)) is not None
    assert pricing.active_interval(wrap, datetime(2026, 10, 26, 0, 0)) is None


def test_inactive_intervals_keep_prices_but_do_not_apply_or_conflict():
    disabled = {**NIGHT, "enabled": False}
    rules = pricing.clean_rules(schedule(disabled, EVENING))
    assert rules["schedule"]["intervals"][0]["prices"]["cg-01"] == "1.2000"
    assert pricing.active_interval(rules, datetime(2026, 10, 20, 23, 0)) is None
    assert pricing.active_interval(rules, datetime(2026, 10, 24, 19, 0))["enabled"] is True
    fallback = status(rules, local_now=datetime(2026, 10, 20, 23, 0))
    assert pricing.connector_price(fallback, "cg-01", "1.89") == (Decimal("1.8900"), Decimal("1.8900"))
    overlapping = {**NIGHT, "start": "23:00"}
    pricing.clean_rules(schedule(disabled, overlapping))
    with pytest.raises(ValueError, match="se sobrepõem"):
        pricing.clean_rules(schedule({**disabled, "enabled": True}, overlapping))


def test_schedule_base_times_demand_and_the_reason():
    rules = schedule(NIGHT)
    night = status(rules, local_now=datetime(2026, 10, 20, 23, 0))
    assert night["schedule_now"]["prices"]["cg-01"] == "1.2000"
    assert (night["reason"], night["reason_label"]) == ("schedule", "Horário 22:00–06:00")
    assert pricing.connector_price(night, "cg-01", "1.89") == (Decimal("1.2000"), Decimal("1.2000"))
    # Conector sem preço no horário (ex.: cadastrado depois) usa a própria base.
    assert pricing.connector_price(night, "cg-03", "1.89") == (Decimal("1.8900"), Decimal("1.8900"))
    full = {"in_use": 4, "busy_15m": Decimal("1"), "starts_60m": 9, "baseline_60m": 1}
    surge = status({**rules, "demand": {"max_increase_percent": 30}}, local_now=datetime(2026, 10, 20, 23, 0), **full)
    assert surge["multiplier"] == "1.30" and surge["reason"] == "demand_schedule"
    assert surge["reason_label"] == "Demanda muito alta · Horário 22:00–06:00"
    assert pricing.connector_price(surge, "cg-01", "1.89") == (Decimal("1.2000"), Decimal("1.5600"))
    day = status({**rules, "demand": {"max_increase_percent": 30}}, **full)
    assert (day["reason"], day["schedule_now"]) == ("demand", None)
    assert (status()["reason"], status()["reason_label"]) == ("normal", "Preço normal")
    assert pricing.tariff_reason("1.10", "high", None) == ("demand", "Alta demanda")


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


def test_speed_tariffs_apply_owner_overrides_schedule_and_demand_to_both_choices():
    status = {'multiplier': '1.25', 'speed': pricing.clean_rules({'speed': {'prices': {
        'cg-01': {'max': '3', 'reduced': '1.5'}}}})['speed'],
        'schedule_now': {'prices': {'cg-01': '1'}}}
    prices = pricing.speed_prices(status, 'cg-01', '2')
    assert prices['base_speed_prices'] == {'max': '1.0000', 'reduced': '0.5000'}
    assert prices['speed_prices'] == {'max': '1.2500', 'reduced': '0.6250'}
    assert pricing.connector_price(status, 'cg-01', '2', 'reduced') == (Decimal('.5'), Decimal('.625'))
    fallback = pricing.speed_prices({'multiplier': '1'}, 'unconfigured', '2')
    assert fallback['speed_prices'] == {'max': '2.0000', 'reduced': '1.6000'}


def test_speed_rules_validate_relation_and_reject_invalid_values():
    for speed in ({'reduced_discount_percent': 0}, {'prices': {'cg-01': {'max': '1', 'reduced': '2'}}},
                  {'prices': {'cg-01': {'max': '1', 'reduced': '1'}}},
                  {'prices': {'cg-01': {'max': 'NaN'}}}):
        with pytest.raises(ValueError):
            pricing.clean_rules({'speed': speed})


def test_partial_speed_update_preserves_tariffs_of_other_connectors():
    stored = pricing.clean_rules({'speed': {'prices': {
        'first': {'max': '3', 'reduced': '2'}, 'second': {'max': '4', 'reduced': '3'}}}})
    merged = pricing.clean_rules(pricing.merge_rules(stored, {'speed': {'prices': {
        'first': {'max': '2', 'reduced': '1'}}}}, ['first', 'second']))
    assert merged['speed']['prices']['second'] == {'max': '4.0000', 'reduced': '3.0000'}
    assert merged['speed']['prices']['first'] == {'max': '2.0000', 'reduced': '1.0000'}
