import csv
import io
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from chargegrid_core import analytics as a
from chargegrid_core.formatting import integer, percent

UTC = timezone.utc
NOW = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)  # 12:00 em São Paulo
START = datetime(2026, 10, 12, 3, 0, tzinfo=UTC)  # 12/10 00:00 local
END = datetime(2026, 10, 13, 3, 0, tzinfo=UTC)  # 13/10 00:00 local


def session(**overrides):
    base = {"id": "s1", "connector_id": "p1", "status": "completed", "energy_wh": "2000.000",
            "cost_estimate": "3.0000", "started_at": "2026-10-12T13:00:00Z", "ended_at": "2026-10-12T14:00:00Z",
            "created_at": "2026-10-12T12:59:00Z", "price_per_kwh": "1.5", "discount_percent": 0}
    base.update(overrides)
    return base


def test_period_bounds_use_local_midnight():
    start, end = a.period_bounds("today", NOW)
    assert start == datetime(2026, 10, 13, 3, tzinfo=UTC) and end == NOW
    start, _ = a.period_bounds("7d", NOW)
    assert start == datetime(2026, 10, 7, 3, tzinfo=UTC)
    start, _ = a.period_bounds("30d", NOW)
    assert start == datetime(2026, 9, 14, 3, tzinfo=UTC)
    start, end = a.period_bounds("custom", NOW, start=date(2026, 10, 1), end="2026-10-01")
    assert (start, end) == (datetime(2026, 10, 1, 3, tzinfo=UTC), datetime(2026, 10, 2, 3, tzinfo=UTC))
    with pytest.raises(ValueError):
        a.period_bounds("custom", NOW, start="2026-10-02", end="2026-10-01")
    with pytest.raises(ValueError):
        a.period_bounds("custom", NOW, start="2024-01-01", end="2026-10-01")
    with pytest.raises(ValueError):
        a.period_bounds("year", NOW)


def test_validate_window_limits_hourly_series():
    a.validate_window(START, END, "hour")
    with pytest.raises(ValueError):
        a.validate_window(END, START)
    with pytest.raises(ValueError):
        a.validate_window(START, START + timedelta(days=40), "hour")
    with pytest.raises(ValueError):
        a.validate_window(START, END, "week")
    assert a.suggested_granularity(START, END) == "hour"
    assert a.suggested_granularity(START, START + timedelta(days=7)) == "day"


def test_summary_counts_only_finished_sessions_by_end_time():
    records = [
        session(),
        session(id="s2", status="interrupted", energy_wh="1000", cost_estimate="1.5"),
        session(id="s3", status="failed", energy_wh="0", cost_estimate="0", started_at=None),
        session(id="s4", started_at="2026-10-13T02:00:00Z", ended_at="2026-10-13T03:00:00Z"),  # fim exatamente no limite aberto
        session(id="s5", status="charging", ended_at=None, started_at="2026-10-13T02:00:00Z"),
        session(id="s6", energy_wh="0"),
    ]
    totals = a.summarize_sessions(records, START, END, NOW)
    assert totals["revenue"] == Decimal("4.5")
    assert totals["energy_wh"] == Decimal("3000")
    assert totals["sessions"] == 2
    assert totals["interrupted"] == 1 and totals["failed"] == 1 and totals["active_sessions"] == 1
    # 60 min (s1) + 60 (s2) + 60 (s4 recortada até o fim) + 60 (s5 até END) + 60 (s6)
    assert totals["busy_minutes"] == Decimal(300)
    totals.update(a.summarize_reservations([
        {"created_at": "2026-10-12T10:00:00Z", "status": "consumed"},
        {"created_at": "2026-10-12T11:00:00Z", "status": "expired"},
        {"created_at": "2026-10-11T11:00:00Z", "status": "expired"},
    ], START, END))
    kpis = a.build_kpis(totals, points=2, points_online=1, start=START, end=END)
    assert kpis["revenue"] == "4.50" and kpis["average_ticket"] == "2.25"
    assert kpis["energy_kwh"] == "3.000"
    assert kpis["occupancy_percent"] == "10.4"  # 300 / (2 × 1440)
    assert kpis["uptime_percent"] == "50.0"
    assert kpis["reservations"] == 2 and kpis["no_shows"] == 1 and kpis["no_show_percent"] == "50.0"


def test_empty_kpis_report_missing_data_instead_of_zero_division():
    kpis = a.build_kpis({}, points=0, points_online=0, start=START, end=END)
    assert kpis["average_ticket"] is None and kpis["occupancy_percent"] is None and kpis["uptime_percent"] is None
    assert kpis["revenue"] == "0.00" and kpis["sessions"] == 0


def test_series_fill_empty_buckets_in_local_time():
    rows = a.series_rows([session(), session(id="x", ended_at="2026-10-12T14:30:00Z")], START, END, "hour")
    payload = a.series_payload(rows, START, END, "hour")
    assert len(payload["buckets"]) == 24
    assert payload["buckets"][0].startswith("2026-10-12T00:00:00-03:00")
    assert payload["series"]["revenue"][11] == "6.00"
    assert payload["series"]["sessions"][11] == 2
    assert payload["series"]["energy_kwh"][11] == "4.000"
    assert sum(payload["series"]["sessions"]) == 2
    daily = a.series_payload([(datetime(2026, 10, 12), "1", "500", 1)], START, END + timedelta(days=1), "day")
    assert daily["series"]["revenue"] == ["1.00", "0.00"]


def test_heatmap_and_peak_hours():
    cells = a.heatmap_cells([session(), session(id="b"), session(id="c", started_at="2026-10-12T21:10:00Z")],
                            START, END)
    payload = a.heatmap_payload(cells + [(9, 1, 5)])  # célula inválida é ignorada
    assert payload["cells"][0][10] == 2  # segunda-feira, 10h local
    assert payload["cells"][0][18] == 1
    assert payload["max"] == 2
    assert a.peak_hours(payload) == [{"hour": 10, "sessions": 2}, {"hour": 18, "sessions": 1}]


def test_ranking_orders_by_revenue_and_includes_idle_points():
    points = [{"connector_id": "p1", "station_id": "st", "station_name": "Centro", "public_code": "A"},
              {"connector_id": "p2", "station_id": "st", "station_name": "Centro", "public_code": "B"}]
    rows = a.ranking_rows([session(), session(id="z", connector_id="p2", cost_estimate="9")], points,
                          START, END, NOW)
    ranking = a.ranking_payload(rows + [{"connector_id": "p3", "station_id": "st", "public_code": "C"}], START, END)
    assert [item["public_code"] for item in ranking] == ["B", "A", "C"]
    assert ranking[0]["revenue"] == "9.00" and ranking[1]["occupancy_percent"] == "4.2"
    assert a.ranking_payload(rows, START, END, limit=1)[0]["public_code"] == "B"


def test_alerts_cover_offline_failures_idle_and_missing_device():
    base = {"station_id": "st", "station_name": "Centro", "published": True, "has_device": True}
    alerts = a.build_alerts([
        {**base, "connector_id": "p1", "public_code": "A", "online": False, "last_seen": "2026-10-13T10:00:00Z"},
        {**base, "connector_id": "p2", "public_code": "B", "online": True, "failed_commands": 2,
         "last_session_at": "2026-10-13T12:00:00Z"},
        {**base, "connector_id": "p3", "public_code": "C", "online": True, "last_session_at": "2026-10-01T12:00:00Z"},
        {**base, "connector_id": "p4", "public_code": "D", "has_device": False},
        {**base, "connector_id": "p5", "public_code": "E", "online": True, "physical_state": "fault",
         "last_session_at": "2026-10-13T12:00:00Z"},
        {**base, "connector_id": "p6", "public_code": "F", "retired": True, "online": False},
        {**base, "connector_id": "p7", "public_code": "G", "published": False, "online": False},
    ], NOW)
    kinds = [(alert["public_code"], alert["kind"], alert["severity"]) for alert in alerts]
    assert kinds == [("A", "device_offline", "critical"), ("E", "device_fault", "critical"),
                     ("B", "command_failed", "warning"), ("D", "no_device", "warning"),
                     ("C", "point_idle", "info")]
    assert "07:00" in alerts[0]["detail"]  # horário local de São Paulo


def test_charger_offline_alert_keeps_the_station_online():
    base = {"station_id": "st", "station_name": "Centro", "published": True, "has_device": True,
            "last_session_at": "2026-10-13T12:00:00Z"}
    alerts = a.build_alerts([
        {**base, "connector_id": "p1", "public_code": "A", "online": True, "charger_offline": True,
         "charger_address": 2},
        {**base, "connector_id": "p2", "public_code": "B", "online": True},
        {**base, "connector_id": "p3", "public_code": "C", "online": False, "charger_offline": True},
    ], NOW)
    kinds = [(alert["public_code"], alert["kind"]) for alert in alerts]
    assert kinds == [("A", "charger_offline"), ("C", "device_offline")]  # tela offline prevalece
    assert alerts[0]["title"] == "Carregador offline" and "carregador 2 não responde" in alerts[0]["detail"]
    assert "a central da estação está online" in alerts[0]["detail"]


def test_csv_export_neutralizes_formulas_and_keeps_numbers():
    rows = [a.session_export_row({**session(), "station_name": "=HYPERLINK(\"x\")", "public_code": "-10",
                                  "end_reason": "@cmd", "connector": {"public_code": "ignored"}})]
    assert rows[0]["duration_minutes"] == "60.0" and rows[0]["energy_kwh"] == "2.000"
    text = a.to_csv(rows)
    parsed = list(csv.reader(io.StringIO(text)))
    assert parsed[0][0] == "ID da sessão" and len(parsed) == 2
    record = dict(zip([key for key, _ in a.SESSION_EXPORT_COLUMNS], parsed[1], strict=True))
    assert record["station_name"] == "'=HYPERLINK(\"x\")"
    assert record["public_code"] == "-10"
    assert record["end_reason"] == "'@cmd"
    assert a.csv_cell(True) == "sim" and a.csv_cell(None) == "" and a.csv_cell(Decimal("-1.5")) == "-1.5"
    reservation = a.reservation_export_row({"id": "r", "status": "expired", "connector": {"public_code": "A"},
                                            "created_at": "2026-10-12T10:00:00Z"})
    assert reservation["no_show"] is True and reservation["public_code"] == "A"
    assert "não comparecimento" in a.to_csv([reservation], a.RESERVATION_EXPORT_COLUMNS).lower()
    envelope = a.export_envelope(rows, dataset="sessions", filters={"station_id": None, "status": "completed"},
                                 generated_at=NOW)
    assert envelope["filters"] == {"status": "completed"} and envelope["total"] == 1


def test_parsing_and_decimal_helpers_are_defensive():
    assert a.parse_time("invalid") is None and a.parse_time(None) is None
    assert a.parse_time("2026-10-12T10:00:00").tzinfo is not None
    assert a.to_decimal("abc") == 0 and a.to_decimal("NaN") == 0
    assert a.decimal_text(None) is None and a.decimal_text("1.005") == "1.01"
    assert a.duration_minutes({"started_at": None}) is None
    assert a.average_ticket(10, 0) is None


def test_new_formatting_helpers():
    assert percent(42.25) == "42,2%" or percent(42.25) == "42,3%"
    assert percent(None) == "—"
    assert integer(12345) == "12.345"
    assert integer(None) == "—"


def test_payment_channel_and_method_columns_are_appended_at_the_end():
    # Totem 0.8.0: o formato anterior continua igual; Canal e Pagamento entram no fim.
    keys = [key for key, _ in a.SESSION_EXPORT_COLUMNS]
    assert keys[:16][-1] == "overstay_fee" and keys[-2:] == ["payment_channel", "payment_method"]
    assert [label for _, label in a.SESSION_EXPORT_COLUMNS][-2:] == ["Canal", "Pagamento"]
    assert a.payment_export_fields(None) == {"payment_channel": "App", "payment_method": ""}
    assert a.payment_export_fields({"channel": "kiosk_totem", "provider": "simulated", "method": "simulated"}) == {
        "payment_channel": "Totem", "payment_method": "Simulado"}
    assert a.payment_export_fields({"channel": "kiosk_qr", "provider": "stripe", "method": "card"}) == {
        "payment_channel": "QR do painel", "payment_method": "Stripe (teste)"}
    assert a.payment_export_fields({"channel": "app", "provider": "stripe"})["payment_channel"] == "App"
    row = {**a.session_export_row(session()), **a.payment_export_fields({"channel": "kiosk_totem",
                                                                          "provider": "simulated"})}
    parsed = list(csv.reader(io.StringIO(a.to_csv([row, a.session_export_row(session())]))))
    assert parsed[0][-2:] == ["Canal", "Pagamento"]
    assert parsed[1][-2:] == ["Totem", "Simulado"] and parsed[2][-2:] == ["", ""]
