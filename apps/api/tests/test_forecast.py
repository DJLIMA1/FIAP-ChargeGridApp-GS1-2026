"""Previsão de ocupação: agregados duráveis, rollup, rotas do dono e melhor horário do motorista."""
import sys
import time
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from test_http import clear_overrides, client_for

from app.models import (
    AggregateWatermark,
    ChargingSession,
    Connector,
    ConnectorHourlyStats,
    Profile,
    Station,
    Telemetry,
    now,
)
from app.modules.forecast import rollup as rollup_module
from app.modules.forecast import service as service_module
from app.modules.forecast.rollup import rollup
from chargegrid_core.forecast import synthetic
from chargegrid_core.forecast.aggregate import floor_hour
from chargegrid_core.forecast.calendar import to_local, to_utc


@pytest.fixture(autouse=True)
def _clear():
    yield
    clear_overrides()


def evening_sessions(db, seed, days=21, connector=None, current=None):
    """Uma recarga por dia das 17h às 19h (horário de São Paulo) nos últimos ``days`` dias.

    Com ``current`` fixo, a de hoje também entra quando já terminou e fechou (``closed_until``): sem ela, as
    células das 17h/18h de hoje, já dentro da janela do histórico, contariam como 0% e derrubariam a média.
    Devolve quantas recargas foram criadas.
    """
    today = floor_hour(to_local(current or now())).replace(hour=0)
    first_day = 0 if current is not None and to_utc(today + timedelta(hours=19)) <= rollup_module.closed_until(
        current) else 1
    for day in range(first_day, days + 1):
        began = to_utc(today - timedelta(days=day) + timedelta(hours=17))
        db.add(ChargingSession(user_id=seed["a"], connector_id=connector or seed["point"], status="completed",
                               created_at=began, started_at=began, ended_at=began + timedelta(hours=2),
                               max_duration_minutes=120, price_per_kwh=Decimal(2), energy_wh=Decimal(2000),
                               source="simulated"))
    return days + 1 - first_day


def test_owner_forecast_requires_ownership(factory, seed):
    with factory.begin() as db:
        rival = Profile(id=uuid.uuid4(), name="Rival", operator_enabled=True)
        db.add(rival)
    client, selected = client_for(factory, rival.id)
    assert client.get("/v1/owner/forecast", params={"station_id": str(seed["station"])}).status_code == 404
    selected["id"] = seed["a"]  # consumidor sem operação habilitada
    assert client.get("/v1/owner/forecast", params={"station_id": str(seed["station"])}).status_code == 403
    assert client.get("/v1/owner/occupancy-history", params={"station_id": str(seed["station"])}).status_code == 403


def test_owner_forecast_without_history(factory, seed):
    client, _ = client_for(factory, seed["owner"])
    body = client.get("/v1/owner/forecast", params={"station_id": str(seed["station"])}).json()
    assert body["status"] == "no_history" and body["hours"] == [] and body["method"] == "baseline"
    assert body["model"]["version"] and body["includes_synthetic"] is False


def test_owner_forecast_finds_the_evening_peak_with_measured_accuracy(factory, seed):
    with factory.begin() as db:
        evening_sessions(db, seed)
    client, _ = client_for(factory, seed["owner"])
    response = client.get("/v1/owner/forecast", params={"station_id": str(seed["station"]), "horizon_hours": 36})
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["status"] == "ok" and len(body["hours"]) == 36 and body["method"] in ("gbm", "baseline")
    assert body["accuracy"]["status"] == "ok" and body["accuracy"]["origins"] >= 7
    assert body["accuracy"]["baseline"]["mae_pp"] is not None
    assert any("17h–19h deve lotar" in peak["label"] for peak in body["peaks"])
    assert body["suggestions"] and body["suggestions"][0]["action"]["type"] == "pricing_rules"
    assert body["model"]["offline_test"]["baseline"]["wape"] is not None
    # A sugestão é aplicável pelo PUT de tarifas existente (PUT parcial).
    patch = next(item for item in body["suggestions"] if item["kind"] == "schedule_peak")["action"]["patch"]
    saved = client.put(f"/v1/stations/{seed['station']}/pricing", json=patch)
    assert saved.status_code == 200 and saved.json()["rules"]["schedule"]["intervals"][0]["start"] == "17:00"


def test_rollup_is_idempotent_keeps_synthetic_rows_and_moves_the_watermark(factory, seed):
    moment = now()
    began = floor_hour(moment) - timedelta(hours=5) + timedelta(minutes=30)
    with factory.begin() as db:
        record = ChargingSession(user_id=seed["a"], connector_id=seed["point"], status="completed",
                                 started_at=began, ended_at=began + timedelta(minutes=90), max_duration_minutes=120,
                                 price_per_kwh=Decimal(2), energy_wh=Decimal(1500), source="simulated")
        db.add(record)
        db.flush()
        db.add(Telemetry(device_id=seed["device"], session_id=record.id, boot_id="b", sequence=1,
                         captured_at=began + timedelta(minutes=30), data={"energy_wh": "500", "power_w": "1000"}))
        db.add(ConnectorHourlyStats(connector_id=seed["point"], hour_start=floor_hour(began), origin="synthetic",
                                    busy_seconds=3600, energy_wh=1, energy_basis="synthetic", sessions_started=1,
                                    generator=synthetic.VERSION))
    with factory.begin() as db:
        first = rollup(db, moment)
    with factory.begin() as db:
        second = rollup(db, moment)
        rows = db.scalars(select(ConnectorHourlyStats).where(ConnectorHourlyStats.origin != "synthetic")
                          .order_by(ConnectorHourlyStats.hour_start)).all()
        assert first["rows"] == second["rows"] == 2
        assert [r.busy_seconds for r in rows] == [1800, 3600]
        assert sum(Decimal(r.energy_wh) for r in rows) == Decimal("1500.000")
        assert {r.energy_basis for r in rows} == {"telemetry"}
        assert db.scalar(select(func.count()).select_from(ConnectorHourlyStats)
                         .where(ConnectorHourlyStats.origin == "synthetic")) == 1
        mark = db.get(AggregateWatermark, rollup_module.WATERMARK)
        assert mark.rolled_until == rollup_module.closed_until(moment)


def test_rollup_counts_overstay_as_occupied_until_unplug_or_last_confirmed_sync(factory, seed):
    """A permanência ocupa a vaga: ``[ended_at, overstay_ended_at)``; aberta, até o último sync com cabo."""
    hour = floor_hour(now()) - timedelta(hours=8)
    with factory.begin() as db:
        db.add(ChargingSession(user_id=seed["a"], connector_id=seed["point"], status="completed",
                               started_at=hour + timedelta(minutes=30), ended_at=hour + timedelta(hours=1),
                               max_duration_minutes=120, price_per_kwh=Decimal(2), energy_wh=Decimal(1000),
                               source="simulated", overstay_started_at=hour + timedelta(hours=1),
                               overstay_last_connected_at=hour + timedelta(hours=1, minutes=39),
                               overstay_ended_at=hour + timedelta(hours=1, minutes=40),
                               overstay_end_reason="disconnected"))
    with factory.begin() as db:
        # Janela que começa depois do fim da recarga: a sessão entra só pela permanência.
        rows = rollup_module.compute_rows(db, hour + timedelta(hours=1), hour + timedelta(hours=3), now())
        assert [(r["hour_start"], r["busy_seconds"], r["energy_wh"]) for r in rows] == [
            (hour + timedelta(hours=1), 2400, Decimal("0.000"))]
    with factory.begin() as db:
        db.add(ChargingSession(user_id=seed["a"], connector_id=seed["point"], status="completed",
                               started_at=hour + timedelta(hours=3), ended_at=hour + timedelta(hours=3, minutes=30),
                               max_duration_minutes=120, price_per_kwh=Decimal(2), energy_wh=Decimal(500),
                               source="simulated", overstay_started_at=hour + timedelta(hours=3, minutes=30),
                               overstay_last_connected_at=hour + timedelta(hours=4, minutes=15)))
    with factory.begin() as db:
        rows = rollup_module.compute_rows(db, hour + timedelta(hours=4), hour + timedelta(hours=7), now())
        # Aberta: conta só até o último sync confirmado (04:15), não até agora.
        assert [(r["hour_start"], r["busy_seconds"]) for r in rows] == [(hour + timedelta(hours=4), 900)]


# Instantes (UTC) fixos: 00:10, 12:00, 17:30 e 23:30 de 14/10/2026 em São Paulo (UTC-3). O relógio real nunca entra:
# antes, rodar a suíte após ~18:15 locais fechava a hora das 17h de hoje (sem recarga) e a média caía para 50%.
CLOCKS = ["2026-10-14T03:10:00+00:00", "2026-10-14T15:00:00+00:00", "2026-10-14T20:30:00+00:00",
          "2026-10-15T02:30:00+00:00"]


@pytest.mark.parametrize("instant", CLOCKS)
def test_history_reads_live_hours_after_the_watermark(factory, seed, monkeypatch, instant):
    moment = datetime.fromisoformat(instant)
    for module in (service_module, rollup_module, sys.modules[__name__]):
        monkeypatch.setattr(module, "now", lambda: moment)
    with factory.begin() as db:
        created = evening_sessions(db, seed, days=10, current=moment)
    with factory.begin() as db:
        rollup(db, moment - timedelta(days=3))  # marca d'água atrasada: os últimos dias vêm calculados na hora
    client, _ = client_for(factory, seed["owner"])
    body = client.get("/v1/owner/occupancy-history", params={"station_id": str(seed["station"]), "weeks": 2}).json()
    cells = [value for row in body["occupancy_percent"] for value in [row[17], row[18]] if value is not None]
    assert cells and all(Decimal(value) > 50 for value in cells)
    # O histórico começa na primeira recarga; os 3 dias depois da marca d'água entram calculados na hora.
    assert sum(body["samples"][d][17] for d in range(7)) == created
    assert body["includes_synthetic"] is False


def test_synthetic_history_is_labeled(factory, seed):
    start = floor_hour(to_local(now())).replace(hour=0) - timedelta(days=21)
    profile = {**synthetic.station_profile(1, 0), "connectors": 1}
    rows = synthetic.station_rows(profile, start, 21, [str(seed["point"])])
    with factory.begin() as db:
        for row in rows:
            db.add(ConnectorHourlyStats(**{**row, "connector_id": seed["point"], "generator": synthetic.VERSION}))
    client, _ = client_for(factory, seed["owner"])
    forecast = client.get("/v1/owner/forecast", params={"station_id": str(seed["station"])}).json()
    history = client.get("/v1/owner/occupancy-history", params={"station_id": str(seed["station"])}).json()
    assert forecast["includes_synthetic"] and history["includes_synthetic"]
    assert any("sintético" in note for note in forecast["notes"])
    assert forecast["coverage"]["days_synthetic"] >= 20


def test_best_times_for_drivers_without_owner_numbers(factory, seed):
    with factory.begin() as db:
        evening_sessions(db, seed)
        station = db.get(Station, seed["station"])
        today = to_local(now()).weekday()
        station.pricing = {"schedule": {"enabled": True, "intervals": [
            {"start": "13:00", "end": "16:00", "days": list(range(7)), "prices": {str(seed["point"]): "1.5"}}]}}
        hidden = Station(owner_id=seed["owner"], name="Inativo", address="X", latitude=0, longitude=0, active=False)
        db.add(hidden)
        assert today in range(7)
    client, _ = client_for(factory, seed["a"])
    response = client.get(f"/v1/stations/{seed['station']}/best-times", params={"hours": 24})
    assert response.status_code == 200
    body = response.json()
    assert len(body["hours"]) == 24 and body["best"]["price_from"] == "1.5000"
    assert "13:00–16:00" in body["best"]["reason"] and "Estimativa" in body["note"]
    assert "occupancy_percent" not in str(body) and body["now"]["price_per_kwh"]
    assert client.get(f"/v1/stations/{hidden.id}/best-times").status_code == 404
    assert client.get(f"/v1/stations/{uuid.uuid4()}/best-times").status_code == 404


def test_forecast_stays_fast_with_eight_points_and_eight_weeks(factory, seed):
    start = floor_hour(to_local(now())).replace(hour=0) - timedelta(days=56)
    with factory.begin() as db:
        ids = [seed["point"]]
        for index in range(7):
            point = Connector(station_id=seed["station"], public_code=f"CG-F{index}", connector_type="CCS2",
                              power_kw=22, price_per_kwh=2)
            db.add(point)
            db.flush()
            ids.append(point.id)
        profile = {**synthetic.station_profile(5, 0), "connectors": 8}
        for row in synthetic.station_rows(profile, start, 56, [str(i) for i in ids]):
            db.add(ConnectorHourlyStats(**{**row, "connector_id": uuid.UUID(row["connector_id"]),
                                           "generator": synthetic.VERSION}))
    client, _ = client_for(factory, seed["owner"])
    began = time.perf_counter()
    body = client.get("/v1/owner/forecast", params={"station_id": str(seed["station"])}).json()
    assert time.perf_counter() - began < 3
    assert body["status"] == "ok" and body["connectors"] == 8
