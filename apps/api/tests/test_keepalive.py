from fastapi.testclient import TestClient

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


def test_keepalive_requires_secret_and_reads_database(monkeypatch):
    database = FakeDatabase()
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
        assert response.json() == {"status": "ok"}
        assert response.headers["cache-control"] == "no-store"
        assert len(database.queries) == 3
        assert all("LIMIT" in query for query in database.queries)
    finally:
        app.dependency_overrides.clear()
