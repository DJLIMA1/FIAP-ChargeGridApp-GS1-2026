"""Aluguel mensal por central: configuração no banco, rateio por dia e desconto no resultado."""

import csv
import io
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from test_http import clear_overrides, client_for

from app.models import CentralRentRate, Connector, Device, DeviceClaim, Profile
from app.reports import pdf
from app.security import digest

SP = ZoneInfo("America/Sao_Paulo")
SEPTEMBER = {"from": datetime(2026, 9, 1, tzinfo=SP).isoformat(), "to": datetime(2026, 10, 1, tzinfo=SP).isoformat()}


@pytest.fixture
def owner(factory, seed):
    client, _ = client_for(factory, seed["owner"])
    yield client
    clear_overrides()


def _claim(factory, seed, claimed_at, created_at=None):
    with factory.begin() as db:
        db.add(DeviceClaim(connector_id=seed["point"], token_hash=digest("claim-rent"), claimed_by=seed["owner"],
                           claimed_at=claimed_at))
        db.get(Device, seed["device"]).created_at = created_at


def _rate(factory, amount, effective, station_id=None):
    with factory.begin() as db:
        db.add(CentralRentRate(station_id=station_id, monthly_amount=amount, effective_from=effective))


def test_without_rate_there_is_no_rent_and_nothing_changes(owner, factory, seed):
    _claim(factory, seed, datetime(2026, 9, 15, 10, tzinfo=SP))
    report = owner.get("/v1/owner/margin", params=SEPTEMBER).json()
    assert report["central_rent"] is None and report["totals"]["central_rent"] is None
    assert report["totals"]["owner_net_after_rent"] == report["totals"]["owner_net"]
    economics = owner.get(f"/v1/stations/{seed['station']}/economics").json()
    assert economics["central_monthly_rent"] is None and economics["centrals"] == 1
    assert economics["rent_editable"] is False


def test_rent_is_prorated_from_the_claim_day_and_deducted_from_the_payout(owner, factory, seed):
    _claim(factory, seed, datetime(2026, 9, 15, 10, tzinfo=SP), created_at=datetime(2026, 8, 1, tzinfo=SP))
    _rate(factory, Decimal("99.00"), date(2026, 1, 1))
    report = owner.get("/v1/owner/margin", params=SEPTEMBER).json()
    totals = report["totals"]
    assert totals["central_rent"] == "52.80"  # 99 × 16/30
    assert totals["centrals"] == 1
    assert Decimal(totals["owner_net_after_rent"]) == Decimal(totals["owner_net"]) - Decimal("52.80")
    assert Decimal(totals["result"]) == Decimal(totals["margin"]) - Decimal("52.80")
    line = report["central_rent"]["lines"][0]
    assert (line["central"], line["month"], line["days"], line["days_in_month"], line["monthly_amount"]) == (
        "CG-01", "2026-09", 16, 30, "99.00")
    station = report["by_station"][0]
    assert station["station_name"] == "Demo" and station["sessions"] == 0 and station["central_rent"] == "52.80"
    economics = owner.get(f"/v1/stations/{seed['station']}/economics").json()
    assert economics["central_monthly_rent"] == "99.00" and economics["centrals"] == 1
    assert any("Aluguel mensal por central" in note for note in economics["notes"])
    assert report["stations"][0]["central_monthly_rent"] == "99.00"
    assert any("Aluguel das centrais" in text for text in report["methodology"])


def test_station_override_revocation_and_child_chargers(owner, factory, seed):
    _claim(factory, seed, datetime(2026, 8, 1, tzinfo=SP))
    _rate(factory, Decimal("99.00"), date(2026, 1, 1))
    _rate(factory, Decimal("60.00"), date(2026, 9, 1), station_id=seed["station"])
    with factory.begin() as db:
        extra = Connector(station_id=seed["station"], public_code="CG-02", connector_type="bench", power_kw=1,
                          price_per_kwh=2, max_duration_minutes=60)
        db.add(extra)
        db.flush()
        db.add(Device(connector_id=extra.id, key_hash=digest("child"), parent_device_id=seed["device"]))
        db.add(DeviceClaim(connector_id=extra.id, token_hash=digest("claim-child"), claimed_by=seed["owner"],
                           claimed_at=datetime(2026, 8, 1, tzinfo=SP)))
        # Revogada no dia 10: conta os dias 1 a 10 (o gatilho mantém o horário informado).
        device = db.get(Device, seed["device"])
        device.revoked, device.revoked_at = True, datetime(2026, 9, 10, 15, tzinfo=SP)
    totals = owner.get("/v1/owner/margin", params=SEPTEMBER).json()["totals"]
    assert totals["central_rent"] == "20.00" and totals["centrals"] == 1  # 60 × 10/30; carregador não conta


def test_revoked_at_trigger_marks_the_first_revocation(factory, seed):
    with factory.begin() as db:
        db.get(Device, seed["device"]).revoked = True
    with factory() as db:
        device = db.get(Device, seed["device"])
        assert device.revoked_at is not None and device.created_at is not None


def test_rent_csv_and_pdf(owner, factory, seed, monkeypatch):
    _claim(factory, seed, datetime(2026, 8, 1, tzinfo=SP))
    _rate(factory, Decimal("99.00"), date(2026, 1, 1))
    response = owner.get("/v1/owner/export/central-rent.csv", params=SEPTEMBER)
    assert response.status_code == 200 and "chargegrid-aluguel-centrais-" in response.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows == [["Posto", "Central (ponto)", "Mês", "Dias cobrados", "Dias do mês", "Aluguel mensal (R$)",
                     "Valor (R$)"], ["Demo", "CG-01", "2026-09", "30", "30", "99.00", "99.00"]]
    monkeypatch.setattr(pdf, "COMPRESS", False)
    body = owner.get("/v1/owner/export/margin.pdf", params=SEPTEMBER).content
    for text in (b"Aluguel das centrais", b"Repasse l\\355quido", b"Resultado estimado"):
        assert text in body, text


def test_other_owner_never_sees_this_rent(factory, seed):
    _claim(factory, seed, datetime(2026, 8, 1, tzinfo=SP))
    _rate(factory, Decimal("99.00"), date(2026, 1, 1))
    with factory.begin() as db:
        db.get(Profile, seed["b"]).operator_enabled = True
    client, _ = client_for(factory, seed["b"])
    try:
        report = client.get("/v1/owner/margin", params=SEPTEMBER)
        assert report.status_code == 200 and report.json()["central_rent"] is None
    finally:
        clear_overrides()
