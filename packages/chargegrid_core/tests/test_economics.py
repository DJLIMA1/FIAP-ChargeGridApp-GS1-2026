import csv
import io
from decimal import Decimal

import pytest

from chargegrid_core import economics as e

TERMS = {"version": 1, "connector_base_per_kwh": "1.0000", "base_per_kwh": "1.2000", "base_source": "schedule",
         "schedule_window": "18:00–21:00", "demand": {"multiplier": "1.30"},
         "coupon": {"id": "c1", "code": "LOJA10", "discount_percent": 10}}


def session(**overrides):
    base = {"id": "s1", "station_id": "st1", "station_name": "Posto A", "public_code": "CG-7KQ2",
            "ended_at": "2026-10-20T17:40:00Z", "source": "simulated", "energy_wh": "10000.000",
            "price_per_kwh": "1.5600", "base_price_per_kwh": "1.2000", "demand_multiplier": "1.30",
            "discount_percent": 10, "cost_estimate": "14.0400", "price_terms": TERMS,
            "energy_cost_per_kwh": "0.8000", "platform_fee_percent": "25.00"}
    base.update(overrides)
    return base


def test_reference_session_breaks_revenue_into_fee_cost_and_margin():
    row = e.session_economics(session())
    assert row["gross"] == Decimal("15.60")
    assert row["list_value"] == Decimal("10.00")
    assert row["schedule_effect"] == Decimal("2.00")
    assert row["demand_effect"] == Decimal("3.60")
    assert row["list_value"] + row["schedule_effect"] + row["demand_effect"] == row["gross"]
    assert row["discount"] == Decimal("1.56")
    assert row["revenue"] == row["revenue_total"] == Decimal("14.04")
    assert row["platform_fee"] == Decimal("3.51")
    assert row["owner_net"] == Decimal("10.53")
    assert row["energy_cost"] == Decimal("8.00")
    assert row["margin"] == Decimal("2.53")
    assert row["margin_percent"] == Decimal("18.0")
    assert row["cost_basis"] == "snapshot" and row["revenue_basis"] == "estimated"
    assert row["coupon_code"] == "LOJA10"


def test_revenue_is_cost_estimate_rounded_to_the_cent():
    row = e.session_economics(session(cost_estimate="1.2350", energy_wh="1000", price_per_kwh="1.2350",
                                      base_price_per_kwh="1.2350", demand_multiplier="1", discount_percent=0,
                                      price_terms=None))
    assert row["revenue"] == Decimal("1.24") == e.charged_amount("1.2350")
    assert row["discount"] == Decimal("0.00") and row["gross"] == row["revenue"]


def test_without_multiplier_there_is_no_demand_effect_and_legacy_has_no_schedule_split():
    row = e.session_economics(session(price_per_kwh="1.2000", demand_multiplier="1.00", discount_percent=0,
                                      cost_estimate="12.0000", price_terms=None))
    assert row["demand_effect"] == Decimal("0.00")
    assert row["schedule_effect"] is None and row["list_value"] == Decimal("12.00")


def test_legacy_session_without_base_price_uses_charged_price():
    row = e.session_economics(session(base_price_per_kwh=None, demand_multiplier=None, price_terms=None,
                                      price_per_kwh="2.0000", discount_percent=0, cost_estimate="20.0000"))
    assert row["base_per_kwh"] == Decimal("2.0000") and row["demand_effect"] == Decimal("0.00")


def test_missing_energy_cost_never_becomes_zero():
    row = e.session_economics(session(energy_cost_per_kwh=None))
    assert row["energy_cost"] is None and row["margin"] is None and row["cost_basis"] == "missing"
    assert row["owner_net"] == Decimal("10.53")


def test_current_station_cost_and_fee_fill_sessions_without_snapshot():
    row = e.session_economics(session(energy_cost_per_kwh=None, platform_fee_percent=None),
                              station_energy_cost="0.5000", station_fee_percent="20")
    assert row["cost_basis"] == "current" and row["energy_cost"] == Decimal("5.00")
    assert row["platform_fee"] == Decimal("2.81") and row["platform_fee_percent"] == Decimal("20.00")


def test_default_fee_is_25_percent():
    row = e.session_economics(session(platform_fee_percent=None))
    assert row["platform_fee_percent"] == e.DEFAULT_PLATFORM_FEE_PERCENT


def test_negative_margin_is_kept():
    row = e.session_economics(session(energy_cost_per_kwh="2.0000"))
    assert row["margin"] == Decimal("-9.47")


def test_zero_energy_session():
    row = e.session_economics(session(energy_wh="0", cost_estimate="0"))
    assert row["revenue"] == row["platform_fee"] == row["margin"] == Decimal("0.00")
    assert row["margin_percent"] is None


def test_payment_and_overstay_from_other_fronts():
    row = e.session_economics(session(), extras={"overstay": {"amount": "2.00"}})
    assert row["overstay_revenue"] == Decimal("2.00") and row["revenue_total"] == Decimal("16.04")
    assert row["platform_fee"] == Decimal("4.01")
    waived = e.session_economics(session(), extras={"overstay": {"amount": "2.00", "waived": True}})
    assert waived["overstay_revenue"] is None
    paid = e.session_economics(session(), extras={"payment": {"net_amount": "14.04", "provider_fee": "0.20",
                                                              "environment": "sandbox"}})
    assert paid["revenue_basis"] == "captured" and paid["provider_fee"] == Decimal("0.20")
    assert paid["owner_net"] == Decimal("10.33") and paid["payment_environment"] == "sandbox"


def test_aggregate_totals_are_sums_of_rounded_rows():
    rows = [e.session_economics(session(id=str(i), cost_estimate=f"{i}.0049", energy_wh="1000", price_per_kwh="1",
                                        base_price_per_kwh="1", demand_multiplier="1", discount_percent=0,
                                        price_terms=None))
            for i in range(1, 8)]
    report = e.aggregate(rows)
    totals = report["totals"]
    for key in ("revenue", "platform_fee", "owner_net", "energy_cost", "margin"):
        assert totals[key] == sum(row[key] for row in rows)
    assert totals["sessions"] == 7 and totals["coverage"]["missing_energy_cost"] == 0


def test_aggregate_margin_is_none_with_partial_cost_coverage():
    rows = [e.session_economics(session()), e.session_economics(session(id="s2", energy_cost_per_kwh=None))]
    report = e.aggregate(rows)
    assert report["totals"]["margin"] is None
    assert report["totals"]["margin_covered"] == Decimal("2.53")
    assert report["totals"]["coverage"] == {"sessions": 2, "with_energy_cost": 1, "missing_energy_cost": 1}
    assert any("sem custo" in warning for warning in report["warnings"])


def test_aggregate_dynamic_pricing_coupons_and_stations():
    rows = [e.session_economics(session()),
            e.session_economics(session(id="s2", station_id="st2", station_name="Posto B", demand_multiplier="1",
                                        price_per_kwh="1.2000", discount_percent=0, cost_estimate="12.0000",
                                        price_terms=None))]
    report = e.aggregate(rows)
    assert report["dynamic_pricing"]["sessions_with_increase"] == 1
    assert report["dynamic_pricing"]["demand_effect"] == Decimal("3.60")
    assert report["dynamic_pricing"]["average_multiplier"] == Decimal("1.30")
    assert report["coupons"] == {"sessions": 1, "discount": Decimal("1.56")}
    assert [item["station_name"] for item in report["by_station"]] == ["Posto A", "Posto B"]
    assert sum(item["revenue_total"] for item in report["by_station"]) == report["totals"]["revenue_total"]


def test_empty_aggregate():
    report = e.aggregate([])
    assert report["totals"]["sessions"] == 0 and report["totals"]["margin"] == Decimal("0.00")


def test_serialize_uses_decimal_strings():
    data = e.serialize(e.aggregate([e.session_economics(session())]))
    assert data["totals"]["margin"] == "2.53" and data["totals"]["energy_kwh"] == "10.000"
    assert data["dynamic_pricing"]["average_multiplier"] == "1.30"


def test_margin_csv_has_header_rows_and_no_totals():
    hostile = session(station_name="=HYPERLINK(\"x\")")
    text = e.margin_csv([e.session_economics(hostile), e.session_economics(session(id="s2"))])
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0][0] == "ID da sessão" and len(rows) == 3
    assert rows[1][2].startswith("'=")
    header = rows[0]
    assert rows[1][header.index("Margem estimada (R$)")] == "2.53"
    assert rows[1][header.index("Base do custo")] == "custo travado no início da recarga"


@pytest.mark.parametrize("value, expected", [("0,85", Decimal("0.8500")), (Decimal("1.23456"), Decimal("1.2346")),
                                             (None, None), ("", None), ("0", Decimal("0.0000"))])
def test_clean_energy_cost(value, expected):
    assert e.clean_energy_cost(value) == expected


@pytest.mark.parametrize("value", ["-1", "101", "abc", True, "NaN"])
def test_clean_energy_cost_rejects(value):
    with pytest.raises(ValueError):
        e.clean_energy_cost(value)


def test_clean_fee_percent():
    assert e.clean_fee_percent("12.5") == Decimal("12.50")
    with pytest.raises(ValueError):
        e.clean_fee_percent("120")


def test_margin_csv_appends_channel_and_method_at_the_end():
    rows = [{**e.session_economics(session()), "payment_channel": "Totem", "payment_method": "Simulado"},
            e.session_economics(session(id="s2"))]
    parsed = list(csv.reader(io.StringIO(e.margin_csv(rows))))
    assert parsed[0][-3:] == ["Base da receita", "Canal", "Pagamento"]
    assert parsed[1][-2:] == ["Totem", "Simulado"] and parsed[2][-2:] == ["", ""]
