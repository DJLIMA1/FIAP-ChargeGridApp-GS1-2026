"""Exercise real JWT signature verification and persisted profile permissions."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from types import SimpleNamespace

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import security
from app.config import settings
from app.database import db_session
from app.main import app
from app.models import Profile, now
from app.modules.auth import routes as auth_routes


@pytest.fixture
def identity_client(factory, monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setattr(
        security.jwks, "get_signing_key_from_jwt", lambda token: SimpleNamespace(key=key.public_key())
    )

    def database():
        with factory() as db:
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    def token(uid, metadata=None, **changes):
        claims = {
            "sub": str(uid),
            "iss": settings().supabase_url + "/auth/v1",
            "aud": "authenticated",
            "exp": now() + timedelta(minutes=10),
            "user_metadata": metadata or {},
        }
        claims.update(changes)
        return jwt.encode(claims, key, algorithm="ES256")

    app.dependency_overrides[db_session] = database
    try:
        yield TestClient(app), token
    finally:
        app.dependency_overrides.clear()


def test_account_type_persists_without_granting_operator_privilege(identity_client, monkeypatch):
    client, token = identity_client
    uid = uuid.uuid4()
    headers = {
        "Authorization": "Bearer "
        + token(
            uid,
            {
                "name": "Ana",
                "account_type": "vendor",
                "operator_enabled": True,
            },
        )
    }
    first = client.get("/v1/me", headers=headers)
    assert first.status_code == 200
    assert first.json()["account_type"] == "vendor"
    assert first.json()["operator_enabled"] is False

    def unexpected_insert(*args, **kwargs):
        raise AssertionError("Existing profiles must not issue INSERT on every authenticated request")

    monkeypatch.setattr(security, "insert", unexpected_insert)
    assert client.get("/v1/operator/stations", headers=headers).status_code == 403
    assert client.patch("/v1/me", headers=headers, json={"operator_enabled": True}).status_code == 422
    assert client.patch("/v1/me", headers=headers, json={"name": "Ana Maria"}).status_code == 200
    # A subsequent login's metadata must not overwrite edits or persisted type.
    renewed = {"Authorization": "Bearer " + token(uid, {"name": "Ana", "account_type": "consumer"})}
    second = client.get("/v1/me", headers=renewed)
    assert second.json()["name"] == "Ana Maria"
    assert second.json()["account_type"] == "vendor"


def test_legacy_account_defaults_to_consumer(identity_client):
    client, token = identity_client
    response = client.get(
        "/v1/me", headers={"Authorization": "Bearer " + token(uuid.uuid4(), {"name": "Ana"})}
    )
    assert response.status_code == 200
    assert response.json()["account_type"] == "consumer"


def test_concurrent_first_access_creates_one_profile_with_account_metadata(
    identity_client, factory, monkeypatch
):
    client, token = identity_client
    uid = uuid.uuid4()
    headers = {"Authorization": "Bearer " + token(uid, {"name": "Ana", "account_type": "vendor"})}
    barrier = Barrier(2)
    original_get = factory.class_.get

    def synchronized_get(db, entity, identifier, *args, **kwargs):
        result = original_get(db, entity, identifier, *args, **kwargs)
        if entity is Profile and identifier == uid and result is None and not db.info.get("checked_missing"):
            db.info["checked_missing"] = True
            barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(factory.class_, "get", synchronized_get)
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: client.get("/v1/me", headers=headers), range(2)))
    assert [response.status_code for response in responses] == [200, 200]
    assert all(response.json()["account_type"] == "vendor" for response in responses)
    assert all(response.json()["name"] == "Ana" for response in responses)
    assert all(response.json()["operator_enabled"] is False for response in responses)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Profile).where(Profile.id == uid)) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"exp": 1},
        {"iss": "https://untrusted.example/auth/v1"},
        {"aud": "anon"},
        {"sub": "invalid"},
    ],
)
def test_invalid_identity_cannot_create_profile(identity_client, change):
    client, token = identity_client
    response = client.get("/v1/me", headers={"Authorization": "Bearer " + token(uuid.uuid4(), **change)})
    assert response.status_code == 401


def test_jwks_outage_is_retryable_not_invalid_credentials(identity_client, monkeypatch):
    client, token = identity_client

    def offline(_token):
        raise jwt.PyJWKClientConnectionError("Connection unavailable")

    monkeypatch.setattr(security.jwks, "get_signing_key_from_jwt", offline)
    response = client.get("/v1/me", headers={"Authorization": "Bearer " + token(uuid.uuid4())})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "auth_unavailable"


def test_recovery_link_updates_exact_password_and_revokes_sessions(identity_client, monkeypatch):
    client, token = identity_client
    calls = []

    class Provider:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def request(self, method, url, **kwargs):
            calls.append((method, url, kwargs))
            return httpx.Response(200, json={})

    monkeypatch.setattr(auth_routes.httpx, "AsyncClient", lambda **kwargs: Provider())
    endpoint = "/v1/auth/password/update"
    payload = {"password": " New password "}
    assert client.post(endpoint, json=payload).status_code == 401
    assert calls == []
    headers = {"Authorization": "Bearer " + token(uuid.uuid4())}
    response = client.post(endpoint, json=payload, headers=headers)
    assert response.status_code == 200
    assert calls[0][0] == "PUT"
    assert calls[0][1].endswith("/user")
    assert calls[0][2]["json"] == payload
    assert calls[1][0] == "POST"
    assert calls[1][1].endswith("/logout?scope=global")
    assert payload["password"] not in response.text
