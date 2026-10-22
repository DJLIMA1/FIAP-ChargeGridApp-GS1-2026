from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from chargegrid_core import rent
from chargegrid_core.analytics import REPORT_TZ

UTC = timezone.utc


def local(year, month, day, hour=0):
    return datetime(year, month, day, hour, tzinfo=REPORT_TZ)


DEFAULT = [{"station_id": None, "monthly_amount": "99.00", "effective_from": "2026-01-01"}]
CENTRAL = {"device_id": "d1", "station_id": "st1", "station_name": "Posto A", "central": "CG-1",
           "linked_at": local(2026, 9, 1), "unlinked_at": None}


def test_full_closed_month_is_exactly_the_monthly_amount():
    result = rent.accrual([CENTRAL], DEFAULT, local(2026, 10, 1), local(2026, 11, 1), local(2026, 11, 5))
    assert result["total"] == Decimal("99.00") and result["centrals"] == 1
    line = result["lines"][0]
    assert (line["month"], line["days"], line["days_in_month"], line["amount"]) == ("2026-10", 31, 31,
                                                                                    Decimal("99.00"))


def test_linked_mid_month_is_prorated_by_local_day():
    central = {**CENTRAL, "linked_at": local(2026, 10, 15, 18)}  # conta o dia 15 inteiro
    result = rent.accrual([central], DEFAULT, local(2026, 10, 1), local(2026, 11, 1), local(2026, 11, 5))
    assert result["lines"][0]["days"] == 17
    assert result["total"] == Decimal("54.29")  # 99 × 17/31


def test_unlinked_central_stops_counting_after_the_unlink_day():
    central = {**CENTRAL, "unlinked_at": local(2026, 10, 10, 9)}
    result = rent.accrual([central], DEFAULT, local(2026, 10, 1), local(2026, 11, 1), local(2026, 11, 5))
    assert result["lines"][0]["days"] == 10


def test_current_month_accrues_only_started_days():
    result = rent.accrual([CENTRAL], DEFAULT, local(2026, 10, 1), local(2026, 11, 1), local(2026, 10, 22, 10))
    assert result["lines"][0]["days"] == 22


def test_contiguous_windows_add_up_and_cross_months_split_lines():
    start, middle, end = local(2026, 9, 20), local(2026, 10, 5, 12), local(2026, 10, 20)
    now = local(2026, 12, 1)
    whole = rent.accrual([CENTRAL], DEFAULT, start, end, now)
    first, second = rent.accrual([CENTRAL], DEFAULT, start, middle, now), rent.accrual([CENTRAL], DEFAULT, middle, end, now)
    days = sum(line["days"] for line in whole["lines"])
    assert days == sum(line["days"] for line in first["lines"] + second["lines"]) == 30
    assert [line["month"] for line in whole["lines"]] == ["2026-09", "2026-10"]


def test_station_override_and_back_to_default_and_rate_change():
    rates = DEFAULT + [
        {"station_id": "st1", "monthly_amount": "50.00", "effective_from": "2026-10-11"},
        {"station_id": "st1", "monthly_amount": None, "effective_from": "2026-10-21"},
    ]
    assert rent.rate_on(rates, "st1", datetime(2026, 10, 10).date()) == Decimal("99.00")
    assert rent.rate_on(rates, "st1", datetime(2026, 10, 15).date()) == Decimal("50.00")
    assert rent.rate_on(rates, "st1", datetime(2026, 10, 25).date()) == Decimal("99.00")
    assert rent.rate_on(rates, "st2", datetime(2026, 10, 15).date()) == Decimal("99.00")
    result = rent.accrual([CENTRAL], rates, local(2026, 10, 1), local(2026, 11, 1), local(2026, 11, 5))
    assert [(line["monthly_amount"], line["days"]) for line in result["lines"]] == [
        (Decimal("99.00"), 21), (Decimal("50.00"), 10)]  # dias 1–10 e 21–31 no padrão
    assert result["total"] == Decimal("16.13") + Decimal("67.06")


def test_no_rate_configured_means_no_rent():
    result = rent.accrual([CENTRAL], [], local(2026, 10, 1), local(2026, 11, 1), local(2026, 11, 5))
    assert result["total"] is None and result["lines"] == []
    future = [{"station_id": None, "monthly_amount": "99.00", "effective_from": "2026-11-01"}]
    assert rent.accrual([CENTRAL], future, local(2026, 10, 1), local(2026, 11, 1), local(2026, 11, 5))["total"] is None


def test_clean_monthly_rent_and_csv():
    assert rent.clean_monthly_rent("99,9") == Decimal("99.90")
    for bad in ("-1", "10000.01", "abc", True):
        with pytest.raises(ValueError):
            rent.clean_monthly_rent(bad)
    result = rent.accrual([CENTRAL], DEFAULT, local(2026, 10, 1), local(2026, 11, 1), local(2026, 11, 5))
    text = rent.rent_csv(result["lines"])
    assert text.splitlines()[0] == "Posto,Central (ponto),Mês,Dias cobrados,Dias do mês,Aluguel mensal (R$),Valor (R$)"
    assert text.splitlines()[1] == "Posto A,CG-1,2026-10,31,31,99.00,99.00"


def test_utc_window_boundaries_follow_sao_paulo_days():
    start = datetime(2026, 10, 1, 3, tzinfo=UTC)  # 00:00 em São Paulo
    result = rent.accrual([CENTRAL], DEFAULT, start, start + timedelta(days=7), start + timedelta(days=30))
    assert result["lines"][0]["days"] == 7
