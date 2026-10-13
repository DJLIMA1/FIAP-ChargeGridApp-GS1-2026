"""Regression tests for the QA audit of 2026-10 (docs/qa-auditoria-2026-10.md)."""
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import event, select
from test_auth_http import FakeAuthClient, configured_client
from test_http import clear_overrides, client_for

from app.database import Base
from app.main import app
from app.models import ChargingSession, Connector, Coupon, Device, Profile, RequestLimit, Station, now
from app.modules.auth import routes as auth_routes
from app.presence_code import current_code
from app.security import digest


class QueryCounter:
    def __init__(self, engine):
        self.engine, self.count = engine, 0

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self.tick)
        return self

    def __exit__(self, *args):
        event.remove(self.engine, "before_cursor_execute", self.tick)

    def tick(self, *args):
        self.count += 1


def add_stations(factory, owner, count, prefix):
    with factory.begin() as db:
        for index in range(count):
            station = Station(owner_id=owner, name=f"{prefix}{index}", address="Rua", latitude=0, longitude=0)
            db.add(station)
            db.flush()
            for point in range(2):
                connector = Connector(station_id=station.id, public_code=f"{prefix}-{index}-{point}",
                                      connector_type="type2", power_kw=7, price_per_kwh=Decimal("1.5"))
                db.add(connector)
                db.flush()
                db.add(Device(connector_id=connector.id, key_hash=digest(f"{prefix}{index}{point}"),
                              last_seen=now(), reconciled=True, physical_state="idle"))


def count_queries(engine, client, path, **params):
    with QueryCounter(engine) as counter:
        response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    return counter.count, response.json()


@pytest.mark.parametrize("params", [{}, {"available_only": "true"}, {"sort": "price", "connector_type": "type2"}])
def test_station_list_query_count_does_not_grow_with_stations(engine, factory, seed, params):
    client, _ = client_for(factory, seed["a"])
    try:
        add_stations(factory, seed["owner"], 2, "S")
        few, first = count_queries(engine, client, "/v1/stations", **params)
        add_stations(factory, seed["owner"], 10, "M")
        many, second = count_queries(engine, client, "/v1/stations", **params)
        assert second["total"] == first["total"] + 10
        # Was ~5 queries per point (device, station, reservation, session, retired).
        assert many == few
    finally:
        clear_overrides()


def test_station_list_keeps_point_availability_contract(factory, seed):
    client, _ = client_for(factory, seed["a"])
    try:
        add_stations(factory, seed["owner"], 1, "C")
        with factory.begin() as db:
            offline = db.scalar(select(Device).join(Connector).where(Connector.public_code == "C-0-1"))
            offline.last_seen = now() - timedelta(minutes=5)
        items = client.get("/v1/stations").json()["items"]
        points = {p["public_code"]: p for s in items for p in s["connectors"]}
        assert points["C-0-0"]["availability_status"] == "available" and points["C-0-0"]["online"] is True
        assert points["C-0-1"]["availability_status"] == "offline" and points["C-0-1"]["available"] is False
        assert points["CG-01"]["retired"] is False and "presence_secret" not in items[0]
    finally:
        clear_overrides()


def test_history_query_count_does_not_grow_with_sessions(engine, factory, seed):
    client, _ = client_for(factory, seed["a"])
    try:
        def add_sessions(count):
            with factory.begin() as db:
                for index in range(count):
                    db.add(ChargingSession(user_id=seed["a"], connector_id=seed["point"], status="completed",
                                           max_duration_minutes=30, price_per_kwh=2,
                                           created_at=now() + timedelta(seconds=index)))
        add_sessions(2)
        few, first = count_queries(engine, client, "/v1/me/charging-sessions")
        add_sessions(15)
        many, second = count_queries(engine, client, "/v1/me/charging-sessions")
        assert second["total"] == 17 and len(second["items"]) == 17
        assert many == few
        assert second["items"][0]["station_name"] == "Demo" and second["items"][0]["online"] is True
    finally:
        clear_overrides()


def test_operator_summary_aggregates_in_sql(factory, seed):
    client, _ = client_for(factory, seed["owner"])
    try:
        empty = client.get("/v1/operator/summary").json()
        assert empty == {"stations": 1, "total_sessions": 0, "total_energy_wh": "0", "total_estimated_cost": "0"}
        with factory.begin() as db:
            for energy, cost in (("1000.500", "2.0010"), ("250.000", "0.5000")):
                db.add(ChargingSession(user_id=seed["a"], connector_id=seed["point"], status="completed",
                                       max_duration_minutes=30, price_per_kwh=2, energy_wh=Decimal(energy),
                                       cost_estimate=Decimal(cost)))
        summary = client.get("/v1/operator/summary").json()
        assert summary == {"stations": 1, "total_sessions": 2, "total_energy_wh": "1250.500",
                           "total_estimated_cost": "2.5010"}
    finally:
        clear_overrides()


def test_coupon_codes_are_case_insensitive_and_unique_ignoring_case(factory, seed):
    client, selected = client_for(factory, seed["owner"])
    valid = (now() + timedelta(days=1)).isoformat()
    try:
        created = client.post("/v1/coupons", json={"code": " promo10 ", "description": "", "discount_percent": 10,
                                                   "valid_until": valid})
        assert created.status_code == 201 and created.json()["code"] == "PROMO10"
        duplicate = client.post("/v1/coupons", json={"code": "Promo10", "description": "", "discount_percent": 5,
                                                     "valid_until": valid})
        assert duplicate.status_code == 409 and duplicate.json()["error"]["code"] == "coupon_exists"
        selected["id"] = seed["a"]
        with factory() as db:
            station = db.get(Station, seed["station"])
        started = client.post("/v1/charging-sessions", headers={"Idempotency-Key": "coupon-case"},
                              json={"public_code": "CG-01", "presence_code": current_code(station)[0],
                                    "coupon_code": "promo10"})
        assert started.status_code == 202, started.text
        assert started.json()["discount_percent"] == 10
    finally:
        clear_overrides()


def test_legacy_mixed_case_coupon_still_matches(factory, seed):
    with factory.begin() as db:
        db.add(Coupon(operator_id=seed["owner"], code="Legacy", description="", discount_percent=20,
                      valid_until=now() + timedelta(days=1)))
    client, _ = client_for(factory, seed["a"])
    try:
        with factory() as db:
            station = db.get(Station, seed["station"])
        started = client.post("/v1/charging-sessions", headers={"Idempotency-Key": "legacy"},
                              json={"public_code": "CG-01", "presence_code": current_code(station)[0],
                                    "coupon_code": "LEGACY"})
        assert started.status_code == 202 and started.json()["discount_percent"] == 20
    finally:
        clear_overrides()


def test_rate_limit_counts_previous_window_so_boundary_bursts_are_limited(factory, seed):
    with factory() as db:
        base = 1_800_000_000 - 1_800_000_000 % 60
        # 20 requests at the end of one window...
        for _ in range(20):
            auth_routes.limit(db, "burst", maximum=20, clock=lambda: base + 59.0)
        # ...then one right after the boundary: a fixed window would allow 20 more.
        with pytest.raises(Exception) as rejected:
            auth_routes.limit(db, "burst", maximum=20, clock=lambda: base + 60.5)
        assert rejected.value.status_code == 429
        # Late in the next window the previous burst weighs little again.
        auth_routes.limit(db, "other", maximum=20, clock=lambda: base + 1.0)
        assert db.scalar(select(RequestLimit.count).where(RequestLimit.key == digest("other"))) == 1


def test_auth_limit_uses_forwarded_client_only_on_vercel(monkeypatch):
    from starlette.requests import Request

    def request(headers):
        return Request({"type": "http", "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
                        "client": ("10.0.0.1", 1234)})
    forged = {"x-forwarded-for": "1.2.3.4, 10.0.0.1"}
    monkeypatch.delenv("VERCEL", raising=False)
    assert auth_routes.client_ip(request(forged)) == "10.0.0.1"
    monkeypatch.setenv("VERCEL", "1")
    assert auth_routes.client_ip(request(forged)) == "1.2.3.4"
    assert auth_routes.client_ip(request({"x-real-ip": "5.6.7.8"})) == "5.6.7.8"
    assert auth_routes.client_ip(request({})) == "10.0.0.1"


def test_password_reset_without_provider_session_is_401_not_500(factory, seed, monkeypatch):
    FakeAuthClient.calls = []
    FakeAuthClient.response_status = 200
    FakeAuthClient.response_json = {"user": {"id": str(uuid.uuid4())}}
    monkeypatch.setattr(auth_routes.httpx, "AsyncClient", lambda **kwargs: FakeAuthClient())
    client = configured_client(factory)
    try:
        response = client.post("/v1/auth/password/reset",
                               json={"email": "person@example.com", "code": "123456", "password": "new-password"})
        assert response.status_code == 401
        assert len(FakeAuthClient.calls) == 1
    finally:
        FakeAuthClient.response_status = 400
        FakeAuthClient.response_json = {"error": "invalid"}
        app.dependency_overrides.clear()


def test_hot_path_indexes_exist_in_model_and_migration():
    from pathlib import Path
    names = {index.name for table in Base.metadata.tables.values() for index in table.indexes}
    expected = {"ix_telemetry_device_received", "ix_device_commands_session_id",
                "ix_charging_sessions_user_created", "ix_coupons_operator_id"}
    assert expected <= names
    migration = (Path(__file__).resolve().parents[1] / "migrations/versions/4d7e1a9c2b60_hot_path_indexes.py").read_text()
    assert all(name in migration for name in expected)


def test_profile_fixture_cleanup_isolated_between_tests(factory):
    # The schema is created once per run; TRUNCATE must still isolate every test.
    with factory() as db:
        assert db.scalar(select(Profile.id).limit(1)) is None
        assert db.scalar(select(Coupon.id).limit(1)) is None


def test_duplicate_public_code_has_specific_message(factory, seed):
    add_stations(factory, seed["owner"], 1, "D")
    client, _ = client_for(factory, seed["owner"])
    try:
        response = client.patch(f"/v1/connectors/{seed['point']}", json={"public_code": "D-0-0"})
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "public_code_taken"
        assert client.patch(f"/v1/connectors/{seed['point']}", json={"public_code": "CG-01"}).status_code == 200
    finally:
        clear_overrides()

