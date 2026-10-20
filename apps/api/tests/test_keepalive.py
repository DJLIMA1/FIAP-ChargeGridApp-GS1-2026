from contextlib import nullcontext

from fastapi.testclient import TestClient

from app import main
from app.database import db_session
from app.main import app


class FakeDatabase:
    def __init__(self):
        self.queries = []

    def execute(self, query):
        self.queries.append(str(query))
        return self

    def first(self):
        return None

    def begin_nested(self):
        return nullcontext()


def test_keepalive_requires_secret_and_reads_database(monkeypatch):
    database = FakeDatabase()
    rolled = []
    monkeypatch.setattr(main, "forecast_rollup", lambda db: rolled.append(db) or {"rows": 0})
    app.dependency_overrides[db_session] = lambda: database
    client = TestClient(app)
    try:
        monkeypatch.delenv("CRON_SECRET", raising=False)
        assert client.get("/internal/keepalive").status_code == 401
        assert client.get("/internal/keepalive", headers={"Authorization": "Bearer test-secret"}).status_code == 401

        monkeypatch.setenv("CRON_SECRET", "test-secret")
        assert client.get("/internal/keepalive").status_code == 401
        assert client.get("/internal/keepalive", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert database.queries == []

        response = client.get("/internal/keepalive", headers={"Authorization": "Bearer test-secret"})
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "rollup": {"rows": 0}}
        assert rolled == [database]  # agregados horários fechados no mesmo cron diário
        assert response.headers["cache-control"] == "no-store"
        assert len(database.queries) == 3
        assert all("LIMIT" in query for query in database.queries)
    finally:
        app.dependency_overrides.clear()


def test_keepalive_survives_a_failed_rollup(monkeypatch):
    database = FakeDatabase()

    def broken(db):
        raise RuntimeError("falha simulada")

    monkeypatch.setattr(main, "forecast_rollup", broken)
    monkeypatch.setenv("CRON_SECRET", "test-secret")
    app.dependency_overrides[db_session] = lambda: database
    try:
        response = TestClient(app).get("/internal/keepalive", headers={"Authorization": "Bearer test-secret"})
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "rollup": {"status": "failed"}}
    finally:
        app.dependency_overrides.clear()
