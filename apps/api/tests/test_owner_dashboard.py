import csv
import io
import json
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from app.database import db_session
from app.main import app
from app.models import (
    ChargingSession,
    Command,
    Connector,
    Device,
    Profile,
    Reservation,
    Station,
    Telemetry,
    now,
)
from app.modules.owner.service import live_status
from app.security import current_user, digest
from app.service import availability


@pytest.fixture
def client(factory):
    selected = {"id": None}

    def database():
        with factory() as db:
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    def user():
        with factory() as db:
            return db.get(Profile, selected["id"])

    app.dependency_overrides[db_session] = database
    app.dependency_overrides[current_user] = user
    yield TestClient(app), selected
    app.dependency_overrides.clear()


@pytest.fixture
def owner_data(factory, seed):
    """Two owners; the rival's data must never leak into the first owner's dashboard."""
    moment = now().replace(microsecond=0)
    start = moment - timedelta(days=2)
    with factory.begin() as db:
        rival = Profile(id=uuid.uuid4(), name="Rival", operator_enabled=True)
        db.add(rival)
        db.flush()
        rival_station = Station(owner_id=rival.id, name="Rival", address="Outro", latitude=1, longitude=1)
        db.add(rival_station)
        db.flush()
        rival_point = Connector(station_id=rival_station.id, public_code="RIVAL-01", connector_type="CCS2",
                                power_kw=50, price_per_kwh=3)
        db.add(rival_point)
        db.flush()
        offline_point = Connector(station_id=seed["station"], public_code="CG-02", connector_type="Tipo 2",
                                  power_kw=7, price_per_kwh=2)
        db.add(offline_point)
        db.flush()
        offline_device = Device(connector_id=offline_point.id, key_hash=digest("offline-key"),
                                last_seen=moment - timedelta(hours=3), reconciled=True, physical_state="idle")
        db.add(offline_device)
        db.flush()

        def session(point, user, status, began, minutes, energy, cost, **extra):
            ended = began + timedelta(minutes=minutes) if status in ("completed", "interrupted", "failed") else None
            record = ChargingSession(
                user_id=user, connector_id=point, status=status, created_at=began - timedelta(minutes=1),
                started_at=began, ended_at=ended, max_duration_minutes=120, price_per_kwh=Decimal(2),
                energy_wh=Decimal(energy), cost_estimate=Decimal(cost), source="simulated", **extra,
            )
            db.add(record)
            db.flush()
            return record

        session(seed["point"], seed["a"], "completed", start + timedelta(hours=1), 60, 2000, "4.0000")
        session(seed["point"], seed["b"], "interrupted", start + timedelta(hours=5), 30, 1000, "2.0000",
                end_reason="communication_lost")
        session(seed["point"], seed["a"], "failed", start + timedelta(hours=6), 1, 0, "0")
        session(offline_point.id, seed["a"], "completed", start + timedelta(hours=1), 60, 3000, "6.0000",
                end_reason="=HYPERLINK(1)")
        # Fora da janela consultada e de outro proprietário.
        session(seed["point"], seed["a"], "completed", start - timedelta(days=3), 60, 9000, "18.0000")
        session(rival_point.id, seed["a"], "completed", start + timedelta(hours=1), 60, 50000, "150.0000")
        active = session(seed["point"], seed["b"], "charging", moment - timedelta(minutes=10), 0, 500, "1.0000")
        device = db.get(Device, seed["device"])
        device.physical_state, device.connected, device.boot_id = "charging", True, "boot"
        db.add(Telemetry(device_id=device.id, session_id=active.id, boot_id="boot", sequence=1,
                         captured_at=moment - timedelta(seconds=5), data={"power_w": 7100}))
        db.add(Telemetry(device_id=device.id, session_id=active.id, boot_id="boot", sequence=0,
                         captured_at=moment - timedelta(seconds=60), data={"power_w": 10}))
        for status in ("consumed", "expired", "cancelled"):
            db.add(Reservation(user_id=seed["a"], connector_id=seed["point"], status=status,
                               created_at=start + timedelta(hours=2), confirmation_deadline=start))
        db.add(Reservation(user_id=seed["a"], connector_id=rival_point.id, status="expired",
                           created_at=start + timedelta(hours=2), confirmation_deadline=start))
        db.add(Command(device_id=offline_device.id, type="START", version=1, status="failed",
                       expires_at=moment - timedelta(hours=4), error="timeout"))
        return {**seed, "rival": rival.id, "rival_station": rival_station.id, "offline_point": offline_point.id,
                "active": active.id, "start": start, "end": moment}


def window(data, **extra):
    return {"from": data["start"].isoformat(), "to": data["end"].isoformat(), **extra}


def test_overview_kpis_are_scoped_to_the_owner(client, owner_data):
    http, selected = client
    selected["id"] = owner_data["owner"]
    body = http.get("/v1/owner/overview", params=window(owner_data)).json()
    kpis = body["kpis"]
    assert kpis["sessions"] == 3  # completed + interrupted + completed no outro ponto
    assert kpis["revenue"] == "12.00"
    assert kpis["energy_kwh"] == "6.000"
    assert kpis["average_ticket"] == "4.00"
    assert kpis["interrupted_sessions"] == 1 and kpis["failed_sessions"] == 1 and kpis["active_sessions"] == 1
    assert kpis["reservations"] == 3 and kpis["no_shows"] == 1
    assert kpis["points"] == 2 and kpis["points_online"] == 1 and kpis["uptime_percent"] == "50.0"
    assert Decimal(kpis["occupancy_percent"]) > 0
    assert body["stations"]["total"] == 1
    assert [item["public_code"] for item in body["ranking"]] == ["CG-01", "CG-02"]  # empate em receita: mais sessões primeiro
    assert all(item["public_code"] != "RIVAL-01" for item in body["ranking"])

    selected["id"] = owner_data["rival"]
    rival = http.get("/v1/owner/overview", params=window(owner_data)).json()["kpis"]
    assert rival["revenue"] == "150.00" and rival["sessions"] == 1 and rival["no_shows"] == 1


def test_station_filter_requires_ownership_and_operator(client, owner_data):
    http, selected = client
    selected["id"] = owner_data["owner"]
    response = http.get("/v1/owner/overview", params=window(owner_data, station_id=str(owner_data["rival_station"])))
    assert response.status_code == 404
    response = http.get("/v1/owner/sessions", params=window(owner_data, station_id=str(owner_data["station"])))
    assert response.status_code == 200 and response.json()["total"] == 5
    selected["id"] = owner_data["a"]
    for path in ("overview", "timeseries", "heatmap", "sessions", "reservations", "alerts", "live",
                 "export/sessions.csv"):
        assert http.get(f"/v1/owner/{path}").status_code == 403, path


def test_period_validation(client, owner_data):
    http, selected = client
    selected["id"] = owner_data["owner"]
    end = owner_data["end"]
    bad = [
        {"from": end.isoformat(), "to": (end - timedelta(days=1)).isoformat()},
        {"from": (end - timedelta(days=400)).isoformat(), "to": end.isoformat()},
        {"from": "2026-10-01T00:00:00", "to": "2026-10-02T00:00:00"},
    ]
    for params in bad:
        response = http.get("/v1/owner/overview", params=params)
        assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_period"
    response = http.get("/v1/owner/timeseries", params={"from": (end - timedelta(days=40)).isoformat(),
                                                        "to": end.isoformat(), "granularity": "hour"})
    assert response.status_code == 422
    assert http.get("/v1/owner/sessions", params={"status": "bogus"}).status_code == 422
    # Sem parâmetros: últimos 7 dias (inclui a sessão de 5 dias atrás).
    assert http.get("/v1/owner/overview").json()["kpis"]["sessions"] == 4


def test_timeseries_and_heatmap(client, owner_data):
    http, selected = client
    selected["id"] = owner_data["owner"]
    daily = http.get("/v1/owner/timeseries", params=window(owner_data, granularity="day")).json()
    assert daily["timezone"] == "America/Sao_Paulo" and len(daily["buckets"]) in (3, 4)
    assert sum(daily["series"]["sessions"]) == 3
    assert sum(Decimal(value) for value in daily["series"]["revenue"]) == Decimal("12.00")
    hourly = http.get("/v1/owner/timeseries", params=window(owner_data, granularity="hour", metric="energy_kwh"))
    assert list(hourly.json()["series"]) == ["energy_kwh"]
    assert sum(Decimal(v) for v in hourly.json()["series"]["energy_kwh"]) == Decimal("6.000")
    heat = http.get("/v1/owner/heatmap", params=window(owner_data)).json()
    assert len(heat["cells"]) == 7 and all(len(row) == 24 for row in heat["cells"])
    assert sum(map(sum, heat["cells"])) == 5  # quatro do período + a recarga ativa
    assert heat["peak_hours"][0]["sessions"] >= 2


def test_sessions_table_filters_search_and_hides_customer_identity(client, owner_data):
    http, selected = client
    selected["id"] = owner_data["owner"]
    body = http.get("/v1/owner/sessions", params=window(owner_data, limit=2)).json()
    assert body["total"] == 5 and len(body["items"]) == 2 and body["limit"] == 2
    assert body["items"][0]["status"] == "charging"  # mais recente primeiro
    assert "user_id" not in body["items"][0] and "reservation_id" not in body["items"][0]
    second = http.get("/v1/owner/sessions", params=window(owner_data, limit=2, offset=4)).json()
    assert len(second["items"]) == 1
    filtered = http.get("/v1/owner/sessions", params=window(owner_data, status="completed,interrupted")).json()
    assert {item["status"] for item in filtered["items"]} == {"completed", "interrupted"}
    searched = http.get("/v1/owner/sessions", params=window(owner_data, q="cg-02")).json()
    assert searched["total"] == 1 and searched["items"][0]["public_code"] == "CG-02"
    prefix = str(owner_data["active"])[:8]
    assert http.get("/v1/owner/sessions", params=window(owner_data, q=prefix)).json()["total"] == 1


def test_reservations_table_marks_no_shows(client, owner_data):
    http, selected = client
    selected["id"] = owner_data["owner"]
    body = http.get("/v1/owner/reservations", params=window(owner_data)).json()
    assert body["total"] == 3
    assert sum(item["no_show"] for item in body["items"]) == 1
    expired = http.get("/v1/owner/reservations", params=window(owner_data, status="expired")).json()
    assert expired["total"] == 1 and expired["items"][0]["status"] == "expired"


def test_csv_and_json_exports(client, owner_data):
    http, selected = client
    selected["id"] = owner_data["owner"]
    response = http.get("/v1/owner/export/sessions.csv", params=window(owner_data))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["cache-control"] == "no-store"
    assert 'filename="chargegrid-sessoes-' in response.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[0][0] == "ID da sessão" and len(rows) == 6
    assert all("RIVAL" not in cell for row in rows for cell in row)
    assert "'=HYPERLINK(1)" in [row[-1] for row in rows]  # fórmula neutralizada
    data = http.get("/v1/owner/export/sessions.json", params=window(owner_data, status="completed")).json()
    assert data["schema_version"] == 1 and data["dataset"] == "sessions" and data["total"] == 2
    assert data["filters"]["status"] == "completed"
    reservations = http.get("/v1/owner/export/reservations.csv", params=window(owner_data))
    assert reservations.status_code == 200 and "Não comparecimento" in reservations.text
    assert json.loads(http.get("/v1/owner/export/reservations.json",
                               params=window(owner_data)).text)["total"] == 3


def test_alerts_report_offline_and_failed_commands(client, owner_data):
    http, selected = client
    selected["id"] = owner_data["owner"]
    items = http.get("/v1/owner/alerts").json()["items"]
    kinds = {(item["public_code"], item["kind"]) for item in items}
    assert ("CG-02", "device_offline") in kinds
    assert ("CG-02", "command_failed") in kinds
    assert all(item["station_name"] == "Demo" for item in items)
    selected["id"] = owner_data["rival"]
    assert {item["kind"] for item in http.get("/v1/owner/alerts").json()["items"]} == {"no_device"}


def test_live_reports_active_session_with_latest_power(client, owner_data):
    http, selected = client
    selected["id"] = owner_data["owner"]
    items = {item["public_code"]: item for item in http.get("/v1/owner/live").json()["items"]}
    assert set(items) == {"CG-01", "CG-02"}
    charging = items["CG-01"]
    assert charging["online"] is True and charging["session"]["power_w"] == "7100"
    assert charging["session"]["energy_wh"].startswith("500")
    assert items["CG-02"]["availability_status"] == "offline" and items["CG-02"]["session"] is None


def test_live_status_matches_authoritative_availability(factory, owner_data):
    states = [
        {"physical_state": "idle", "connected": False, "reconciled": True},
        {"physical_state": "idle", "connected": True, "reconciled": True},
        {"physical_state": "idle", "connected": False, "reconciled": False},
        {"physical_state": "fault", "connected": False, "reconciled": True},
        {"physical_state": "charging", "connected": True, "reconciled": True},
    ]
    with factory() as db:
        point = db.get(Connector, owner_data["point"])
        station = db.get(Station, point.station_id)
        device = db.get(Device, owner_data["device"])
        session = db.get(ChargingSession, owner_data["active"])
        for state in states:
            for key, value in state.items():
                setattr(device, key, value)
            for active_session in (session, None):
                if active_session is None:
                    session.status = "completed"
                db.flush()
                expected = availability(db, point, device=device)
                actual = live_status(point, station, device, None, active_session, now())
                assert actual["availability_status"] == expected["availability_status"], state
            session.status = "charging"
        db.rollback()


def test_overview_query_count_does_not_grow_with_points(client, factory, owner_data, engine):
    http, selected = client
    selected["id"] = owner_data["owner"]
    counter = {"n": 0}

    def count(*args):
        counter["n"] += 1

    def run(path):
        counter["n"] = 0
        event.listen(engine, "before_cursor_execute", count)
        try:
            assert http.get(f"/v1/owner/{path}", params=window(owner_data)).status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", count)
        return counter["n"]

    baseline = {path: run(path) for path in ("overview", "alerts", "live")}
    with factory.begin() as db:
        for index in range(6):
            point = Connector(station_id=owner_data["station"], public_code=f"EXTRA-{index}",
                              connector_type="Tipo 2", power_kw=7, price_per_kwh=1)
            db.add(point)
            db.flush()
            db.add(Device(connector_id=point.id, key_hash=digest(f"extra-{index}"), last_seen=now(),
                          reconciled=True, physical_state="idle"))
    for path, queries in baseline.items():
        assert run(path) == queries, path
    with factory() as db:
        assert db.scalar(select(Connector.id).where(Connector.public_code == "EXTRA-5"))
