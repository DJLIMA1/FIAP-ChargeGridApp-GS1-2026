import importlib.util
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest


def load(name):
    path = Path(__file__).parents[1] / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def require_test_database_url(database):
    database_name = urlsplit(database).path.removeprefix("/")
    if not database_name.endswith("_test"):
        raise ValueError(
            "CHARGEGRID_IMPORT_TEST_DATABASE_URL must name a *_test database"
        )


def test_preview_counts_only():
    module = load("import_legacy")
    report = module.preview(
        {
            "users": [{"email": "fake@example.test", "password": "secret"}],
            "history": [{"status": "charging", "token": "hidden"}],
        }
    )
    assert report["users"] == 1
    assert "secret" not in str(report) and "example.test" not in str(report)


def test_auth_mapping_fails_closed():
    module = load("import_legacy")
    uid = "00000000-0000-0000-0000-000000000001"
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"id": uid, "email": "fake@example.test", "email_confirmed_at": None},
        )
    )
    with (
        httpx.Client(
            base_url="https://auth.example.test", transport=transport
        ) as client,
        pytest.raises(ValueError),
    ):
        module.verify_accounts({"fake@example.test": uid}, client)


def test_seed_reuses_station_without_changing_existing_connectors():
    uid = "00000000-0000-0000-0000-000000000001"
    station = {
        "id": uid,
        "owner_id": "operator",
        "name": "ChargeGrid Demo FIAP",
        "connectors": [{"public_code": "DEMO-00000000-1"}],
    }
    writes = []

    def respond(request):
        if request.method != "GET":
            writes.append(request)
        if request.url.path == "/v1/me":
            body = {"id": "operator", "operator_enabled": True}
        elif request.url.path == "/v1/operator/stations":
            body = {"items": [station], "total": 1}
        else:
            body = station
        return httpx.Response(200, json=body)

    with httpx.Client(
        base_url="https://api.example.test/v1", transport=httpx.MockTransport(respond)
    ) as client:
        assert load("seed_demo").seed(client) == uid
    assert writes == []


class Connection:
    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def __init__(self, aggregates=False, rolled_until=None):
        self.queries = []
        self.rowcount = 2
        self.aggregates = aggregates
        self.rolled_until = rolled_until
        self.last = None

    def execute(self, query, params):
        self.queries.append((query, params))
        self.last = query

    def fetchone(self):
        if "to_regclass" in self.last:
            return (self.aggregates,)
        if "aggregate_watermarks" in self.last:
            return (self.rolled_until,) if self.rolled_until else None
        return (2,)


def counted(connection):
    return [(q, p) for q, p in connection.queries if q.startswith("SELECT count")]


def test_maintenance_preview_and_apply_preserve_replay():
    module = load("maintenance")
    now = datetime(2026, 9, 18, tzinfo=timezone.utc)
    connection = Connection()
    module.maintain(connection, now=now)
    assert all(q.startswith("SELECT") for q, _ in connection.queries)
    assert (now - counted(connection)[0][1][0]).days == 7
    connection = Connection()
    module.maintain(connection, True, now)
    assert len([q for q, _ in connection.queries if q.startswith("DELETE")]) == 2
    assert not any(
        "device_boots" in q or "idempotency" in q for q, _ in connection.queries
    )


def test_maintenance_keeps_telemetry_not_yet_aggregated():
    module = load("maintenance")
    now = datetime(2026, 9, 18, tzinfo=timezone.utc)
    # Agregados existem, mas o rollup nunca rodou: nenhuma telemetria sai.
    connection = Connection(aggregates=True)
    counts = module.maintain(connection, True, now)
    assert "retida" in counts["telemetry_samples"]
    assert not any("telemetry_samples" in q for q, _ in connection.queries if q.startswith("DELETE"))
    # Rollup atrasado (marca há 10 dias): apaga só o que já foi agregado, menos a folga de 72 h.
    rolled = now - timedelta(days=10)
    connection = Connection(aggregates=True, rolled_until=rolled)
    module.maintain(connection, True, now)
    deletes = [(q, p) for q, p in connection.queries if q.startswith("DELETE FROM telemetry_samples")]
    assert deletes and deletes[0][1][0] == rolled - timedelta(hours=72)
    # Rollup em dia: vale o limite normal de 7 dias.
    connection = Connection(aggregates=True, rolled_until=now)
    module.maintain(connection, True, now)
    deletes = [(q, p) for q, p in connection.queries if q.startswith("DELETE FROM telemetry_samples")]
    assert (now - deletes[0][1][0]).days == 7


def test_auth_mapping_accepts_confirmed_exact_identity():
    module = load("import_legacy")
    uid = "00000000-0000-0000-0000-000000000001"
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "id": uid,
                "email": "fake@example.test",
                "email_confirmed_at": "2026-09-18T00:00:00Z",
            },
        )
    )
    with httpx.Client(
        base_url="https://auth.example.test", transport=transport
    ) as client:
        assert module.verify_accounts({"fake@example.test": uid}, client) == {
            "fake@example.test": uid
        }
        with pytest.raises(ValueError):
            module.verify_accounts({"other@example.test": uid}, client)


def test_seed_requires_vendor_with_equipment_or_legacy_operator():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, json={"id": "fake", "operator_enabled": False}
        )
    )
    with (
        httpx.Client(
            base_url="https://api.example.test/v1", transport=transport
        ) as client,
        pytest.raises(ValueError),
    ):
        load("seed_demo").seed(client)


def test_seed_creates_only_group_never_arbitrary_equipment():
    writes = []

    def respond(request):
        if request.url.path == "/v1/me":
            body = {"id": "vendor", "operator_enabled": True}
        elif request.url.path == "/v1/operator/stations":
            body = {"items": [], "total": 0}
        else:
            writes.append((request.method, request.url.path))
            body = {"id": "new-station", "owner_id": "vendor", "connectors": []}
        return httpx.Response(201 if request.method == "POST" else 200, json=body)

    with httpx.Client(
        base_url="https://api.example.test/v1", transport=httpx.MockTransport(respond)
    ) as client:
        assert load("seed_demo").seed(client) == "new-station"
    assert writes == [("POST", "/v1/stations")]


def test_seed_url_never_sends_token_to_lookalike_host():
    valid = load("seed_demo").valid_api_url
    assert valid("https://api.example.test/v1")
    assert valid("http://localhost:8000/v1")
    assert valid("http://[::1]:8000/v1")
    assert not valid("http://localhost:80@evil.example/v1")
    assert not valid("http://api.example.test/v1")
    assert not valid("https://api.example.test/v1?token=visible")


def legacy_fixture():
    uid = "00000000-0000-0000-0000-000000000101"
    data = {
        "users": {
            "fake@example.test": {
                "name": "Fictício",
                "password": "never-import",
                "stations": [
                    {
                        "name": "Bancada",
                        "endereco": "Endereço fictício",
                        "lat": "-23",
                        "lng": "-46",
                        "power": "7.4",
                        "price": "R$ 1,50",
                        "max_time": "60",
                    }
                ],
                "history": [
                    {
                        "owner": "fake@example.test",
                        "local": "Bancada",
                        "status": "Pago",
                        "timestamp": 1700000000,
                        "kwh": "1.0 kWh",
                        "valor": "R$ 1,50",
                    }
                ],
                "coupons": [
                    {
                        "code": "FICTICIO",
                        "desc": "Exemplo",
                        "discount_percent": 10,
                        "valid_until": "2027-01-01T00:00:00Z",
                        "station": "Bancada",
                    }
                ],
            }
        }
    }
    return data, {"fake@example.test": uid}


def test_import_plan_preserves_values_and_skips_unknowns():
    module = load("import_legacy")
    data, accounts = legacy_fixture()
    rows, report = module.plan_import(data, accounts, "fictitious-test", "Type 2")
    assert report["planned"]["charging_sessions"] == 1
    assert rows["charging_sessions"][0]["energy_wh"] == 1000
    assert rows["charging_sessions"][0]["started_at"] is None
    assert "never-import" not in str(rows)
    assert not rows["connectors"][0]["active"]
    data["users"]["fake@example.test"]["history"][0]["timestamp"] = "unknown"
    _, report = module.plan_import(data, accounts, "fictitious-test", "Type 2")
    assert report["skipped"]["history"] == 1
    _, report = module.plan_import(data, {}, "fictitious-test", "Type 2")
    assert report["planned"]["stations"] == 0


@pytest.mark.skipif(
    not os.getenv("CHARGEGRID_IMPORT_TEST_DATABASE_URL"),
    reason="banco descartável de importação não configurado",
)
def test_apply_is_idempotent_and_conflicts_roll_back():
    import psycopg

    module = load("import_legacy")
    data, accounts = legacy_fixture()
    rows, _ = module.plan_import(data, accounts, "fictitious-integration", "Type 2")
    database = os.environ["CHARGEGRID_IMPORT_TEST_DATABASE_URL"]
    # This test deletes all rows from its target. Refuse ambiguous or production names
    # before opening a connection, even when the environment variable was set by mistake.
    require_test_database_url(database)
    tables = ("charging_sessions", "coupons", "connectors", "stations", "profiles")
    with psycopg.connect(database) as connection:
        with connection.cursor() as cursor:
            # CASCADE also clears rows that other suites (devices, reservations...) left behind.
            cursor.execute(f"TRUNCATE {', '.join(tables)} CASCADE")
        assert module.apply_import(connection, rows) == {
            "profiles": 1,
            "stations": 1,
            "connectors": 1,
            "coupons": 1,
            "charging_sessions": 1,
        }
        assert module.apply_import(connection, rows) == {table: 0 for table in rows}
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM stations")
            assert cursor.fetchone()[0] == 1

    conflicting_rows, _ = module.plan_import(
        data, accounts, "different-source", "Type 2"
    )
    conflicting_rows["connectors"][0]["public_code"] = rows["connectors"][0][
        "public_code"
    ]
    with pytest.raises(ValueError), psycopg.connect(database) as connection:
        module.apply_import(connection, conflicting_rows)
    with psycopg.connect(database) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM stations")
        assert cursor.fetchone()[0] == 1


def test_destructive_import_test_requires_test_database_name():
    require_test_database_url("postgresql://localhost/chargegrid_import_test")
    with pytest.raises(ValueError):
        require_test_database_url("postgresql://localhost/chargegrid")


def test_seed_forecast_history_plans_only_labeled_synthetic_rows():
    module = load("seed_forecast_history")
    station = "00000000-0000-0000-0000-0000000000aa"
    connectors = [("00000000-0000-0000-0000-0000000000c1", 22.0), ("00000000-0000-0000-0000-0000000000c2", 22.0)]
    now = datetime(2026, 10, 20, 15, 30, tzinfo=timezone.utc)
    rows = module.plan(station, connectors, 14, "shopping", 1, now)
    assert rows and {row["origin"] for row in rows} == {"synthetic"}
    assert {row["connector_id"] for row in rows} <= {cid for cid, _ in connectors}
    assert max(row["hour_start"] for row in rows) < now.replace(minute=0)
    assert rows == module.plan(station, connectors, 14, "shopping", 1, now)  # determinístico
