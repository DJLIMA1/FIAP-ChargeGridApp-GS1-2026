import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.modules.app_updates import routes

MANIFEST = {"version": "0.6.7", "build": 35, "size_bytes": 172510946, "sha256": "a" * 64, "notes": "Novidades.",
            "url": "https://9x2lhsbjqbuqehzd.public.blob.vercel-storage.com/app/chargegrid-0.6.7.apk",
            "published_at": "2026-10-20T04:00:00Z"}


@pytest.fixture(autouse=True)
def fresh():
    routes.clear_cache()
    yield
    routes.clear_cache()


def respond(monkeypatch, payload=None, error=None):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        if error:
            raise error
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))
    monkeypatch.setattr(routes.httpx, "get", fake_get)
    return calls


def test_latest_is_public_validated_and_cached(monkeypatch):
    calls = respond(monkeypatch, MANIFEST)
    client = TestClient(app)
    body = client.get("/v1/app/latest").json()  # sem login: o aviso aparece antes de entrar
    assert body["version"] == "0.6.7" and body["url"].endswith("chargegrid-0.6.7.apk") and body["build"] == 35
    assert client.get("/v1/app/latest").status_code == 200 and len(calls) == 1


@pytest.mark.parametrize("payload", [{"version": "latest", "url": MANIFEST["url"]},
                                     {"version": "0.6.7", "url": "http://inseguro/x.apk"},
                                     {"version": "0.6.7", "url": "https://x/arquivo.zip"}, ["lista"]])
def test_invalid_or_missing_manifest_is_404(monkeypatch, payload):
    respond(monkeypatch, payload)
    response = TestClient(app).get("/v1/app/latest")
    assert response.status_code == 404 and response.json()["error"]["code"] == "updates_unavailable"


def test_storage_offline_is_404(monkeypatch):
    respond(monkeypatch, error=httpx.ConnectTimeout("offline"))
    assert TestClient(app).get("/v1/app/latest").status_code == 404
