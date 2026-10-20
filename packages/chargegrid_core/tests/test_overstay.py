from decimal import Decimal

import pytest

from chargegrid_core import overstay, pricing

RULE = {"enabled": True, "start_after_min": 10, "interval_min": 1, "amount": "1.00", "max_amount": "30.00"}


def terms(**changes):
    return overstay.terms_from_rotation({**RULE, **changes})


def test_default_rule_is_off_with_the_agreed_values():
    rules = pricing.clean_rules({})
    assert rules["rotation"] == {"enabled": False, "start_after_min": 10, "interval_min": 1,
                                 "amount": "1.00", "max_amount": "30.00"}
    assert overstay.terms_from_rotation(rules["rotation"]) is None


def test_legacy_rule_without_cap_gets_the_default_cap_and_zero_tolerance_is_allowed():
    rules = pricing.clean_rules({"rotation": {"enabled": True, "start_after_min": 0, "interval_min": 10,
                                              "amount": "0.2"}})
    assert rules["rotation"] == {"enabled": True, "start_after_min": 0, "interval_min": 10,
                                 "amount": "0.20", "max_amount": "30.00"}


@pytest.mark.parametrize(("bad", "message"), [
    ({"start_after_min": -1}, "0 a 1440"),
    ({"start_after_min": 1441}, "0 a 1440"),
    ({"interval_min": 0}, "1 a 1440"),
    ({"amount": "100.01"}, "R\\$ 100,00"),
    ({"max_amount": "1000.01"}, "1.000,00"),
    ({"max_amount": "abc"}, "números"),
])
def test_rule_validation_in_portuguese(bad, message):
    with pytest.raises(ValueError, match=message):
        pricing.clean_rules({"rotation": {**RULE, **bad}})


def test_fee_is_zero_inside_tolerance_and_counts_only_full_minutes():
    accepted = terms()
    assert overstay.fee_due(accepted, 0) == Decimal("0.00")
    assert overstay.fee_due(accepted, 600) == Decimal("0.00")
    assert overstay.fee_due(accepted, 659) == Decimal("0.00")  # minuto incompleto não é cobrado
    assert overstay.fee_due(accepted, 660) == Decimal("1.00")
    assert overstay.fee_due(accepted, 600 + 3 * 60 + 59) == Decimal("3.00")
    assert overstay.billable_minutes(accepted, 600 + 3 * 60 + 59) == 3
    assert overstay.grace_remaining_seconds(accepted, 120) == 480
    assert overstay.phase(accepted, 600) == "grace" and overstay.phase(accepted, 601) == "billing"


def test_fee_stops_at_the_cap():
    accepted = terms(max_amount="5.00")
    assert overstay.fee_due(accepted, 600 + 60 * 60) == Decimal("5.00")
    assert overstay.capped(accepted, 600 + 5 * 60) and not overstay.capped(accepted, 600 + 4 * 60)
    assert overstay.phase(accepted, 600 + 5 * 60) == "capped"
    assert overstay.billable_minutes(accepted, 600 + 60 * 60) == 5
    assert overstay.max_billable_minutes(accepted) == 5


def test_interval_rule_and_no_terms():
    accepted = terms(start_after_min=0, interval_min=10, amount="0.20")
    assert overstay.fee_due(accepted, 25 * 60) == Decimal("0.40")
    assert overstay.fee_per_minute(accepted) == Decimal("0.0200")
    assert overstay.fee_due(None, 99999) == Decimal("0.00")
    assert overstay.phase(None, 99999) == "no_fee" and overstay.phase(accepted, 1, closed=True) == "closed"
    assert overstay.max_billable_minutes(terms(amount="0")) is None


def test_version_is_stable_and_changes_with_any_value():
    assert terms()["version"] == terms()["version"]
    versions = {terms()["version"], terms(start_after_min=11)["version"], terms(amount="1.10")["version"],
                terms(max_amount="31")["version"], terms(interval_min=2)["version"]}
    assert len(versions) == 5
    assert overstay.clean_terms(terms()) == terms()
    assert overstay.clean_terms({"enabled": True, "grace_minutes": "x"}) is None
    assert overstay.clean_terms(None) is None


def test_public_summary_and_cents():
    shown = overstay.public(terms())
    assert shown["summary"] == "Após a recarga: 10 min de tolerância; depois R$ 1,00 por minuto, até R$ 30,00."
    assert shown["fee_per_minute"] == "1.0000" and shown["version"].startswith("ovs-")
    assert overstay.public(None)["enabled"] is False
    assert overstay.summary(terms(interval_min=5)).endswith("R$ 1,00 a cada 5 min, até R$ 30,00.")
    assert overstay.cents("30.00") == 3000 and overstay.cents(Decimal("1.005")) == 101
