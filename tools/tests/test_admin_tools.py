import importlib.util
import os
from datetime import datetime, timezone
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


def test_seed_reuses_station_and_connector():
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
    def __init__(self):
        self.queries = []
        self.rowcount = 2

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, query, params):
        self.queries.append((query, params))

    def fetchone(self):
        return (2,)


def test_maintenance_preview_and_apply_preserve_replay():
    module = load("maintenance")
    now = datetime(2026, 9, 18, tzinfo=timezone.utc)
    connection = Connection()
    module.maintain(connection, now=now)
    assert all(q.startswith("SELECT") for q, _ in connection.queries)
    assert (now - connection.queries[0][1][0]).days == 7
    connection = Connection()
    module.maintain(connection, True, now)
    assert len([q for q, _ in connection.queries if q.startswith("DELETE")]) == 2
    assert not any(
        "device_boots" in q or "idempotency" in q for q, _ in connection.queries
    )


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


def test_seed_requires_approved_operator():
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
            for table in tables:
                cursor.execute(f"DELETE FROM {table}")
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
