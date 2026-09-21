import httpx
import pytest
from fastapi.testclient import TestClient

from app.database import db_session
from app.main import app
from app.modules.auth import routes as auth_routes


class FakeAuthClient:
    calls = []
    response_status = 400
    response_json = {"error": "invalid"}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return httpx.Response(self.response_status, json=self.response_json)


def configured_client(factory):
    def database():
        with factory() as db:
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    app.dependency_overrides[db_session] = database
    return TestClient(app)


def test_invalid_recovery_code_never_updates_password(factory, seed, monkeypatch):
    FakeAuthClient.calls = []
    monkeypatch.setattr(auth_routes.httpx, "AsyncClient", lambda **kwargs: FakeAuthClient())
    client = configured_client(factory)
    try:
        response = client.post(
            "/v1/auth/password/reset",
            json={"email": "person@example.com", "code": "000000", "password": "new-password"},
        )
        assert response.status_code == 401
        assert len(FakeAuthClient.calls) == 1
        assert FakeAuthClient.calls[0][0] == "POST"
        assert FakeAuthClient.calls[0][1].endswith("/verify")
        assert "new-password" not in response.text
    finally:
        app.dependency_overrides.clear()


def test_failed_logins_are_persistently_rate_limited(factory, seed, monkeypatch):
    FakeAuthClient.calls = []
    monkeypatch.setattr(auth_routes.httpx, "AsyncClient", lambda **kwargs: FakeAuthClient())
    client = configured_client(factory)
    try:
        payload = {"email": "person@example.com", "password": "wrong-password"}
        statuses = [client.post("/v1/auth/login", json=payload).status_code for _ in range(21)]
        assert statuses[:20] == [401] * 20
        assert statuses[20] == 429
        assert len(FakeAuthClient.calls) == 20
    finally:
        app.dependency_overrides.clear()


def test_unconfirmed_login_has_actionable_code(factory, seed, monkeypatch):
    FakeAuthClient.calls = []
    FakeAuthClient.response_json = {"code": "email_not_confirmed", "msg": "Email not confirmed"}
    monkeypatch.setattr(auth_routes.httpx, "AsyncClient", lambda **kwargs: FakeAuthClient())
    client = configured_client(factory)
    try:
        response = client.post(
            "/v1/auth/login", json={"email": "person@example.com", "password": "wrong-password"}
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "email_not_confirmed"
        assert "Email not confirmed" not in response.text
    finally:
        FakeAuthClient.response_json = {"error": "invalid"}
        app.dependency_overrides.clear()


def test_signup_returns_session_when_email_confirmation_is_disabled(factory, seed, monkeypatch):
    FakeAuthClient.calls = []
    FakeAuthClient.response_status = 200
    FakeAuthClient.response_json = {
        "access_token": "access-test",
        "refresh_token": "refresh-test",
        "expires_in": 3600,
        "user": {"id": "user-test"},
    }
    monkeypatch.setattr(auth_routes.httpx, "AsyncClient", lambda **kwargs: FakeAuthClient())
    client = configured_client(factory)
    try:
        response = client.post(
            "/v1/auth/register",
            json={"email": "new@example.com", "password": "safe-password", "name": "New"},
        )
        assert response.status_code == 200
        assert response.json()["access_token"] == "access-test"
        assert response.json()["requires_email_confirmation"] is False
    finally:
        FakeAuthClient.response_status = 400
        FakeAuthClient.response_json = {"error": "invalid"}
        app.dependency_overrides.clear()


def test_signup_masks_existing_account_without_claiming_email_sent(factory, seed, monkeypatch):
    FakeAuthClient.calls = []
    FakeAuthClient.response_status = 422
    FakeAuthClient.response_json = {"code": "user_already_exists"}
    monkeypatch.setattr(auth_routes.httpx, "AsyncClient", lambda **kwargs: FakeAuthClient())
    client = configured_client(factory)
    try:
        response = client.post(
            "/v1/auth/register",
            json={"email": "existing@example.com", "password": "safe-password", "name": "Existing"},
        )
        assert response.status_code == 200
        assert response.json() == {
            "message": "Cadastro recebido",
            "requires_email_confirmation": False,
        }
    finally:
        FakeAuthClient.response_status = 400
        FakeAuthClient.response_json = {"error": "invalid"}
        app.dependency_overrides.clear()


def test_signup_returns_actionable_weak_password_error(factory, seed, monkeypatch):
    FakeAuthClient.calls = []
    FakeAuthClient.response_status = 422
    FakeAuthClient.response_json = {"code": "weak_password"}
    monkeypatch.setattr(auth_routes.httpx, "AsyncClient", lambda **kwargs: FakeAuthClient())
    client = configured_client(factory)
    try:
        response = client.post(
            "/v1/auth/register",
            json={"email": "new@example.com", "password": "weak-pass", "name": "New"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "weak_password"
        assert "Não foi possível enviar" not in response.text
    finally:
        FakeAuthClient.response_status = 400
        FakeAuthClient.response_json = {"error": "invalid"}
        app.dependency_overrides.clear()


def test_signup_resend_is_generic_and_rate_limited(factory, seed, monkeypatch):
    FakeAuthClient.calls = []
    FakeAuthClient.response_status = 200
    FakeAuthClient.response_json = {"error": "invalid"}
    monkeypatch.setattr(auth_routes.httpx, "AsyncClient", lambda **kwargs: FakeAuthClient())
    client = configured_client(factory)
    try:
        first = client.post("/v1/auth/resend-signup", json={"email": "person@example.com"})
        second = client.post("/v1/auth/resend-signup", json={"email": "person@example.com"})
        assert first.status_code == 200
        assert first.json() == {"message": "Se a conta puder receber mensagens, uma confirmação será enviada"}
        assert second.status_code == 429
        assert len(FakeAuthClient.calls) == 1
        assert FakeAuthClient.calls[0][1].endswith("/resend")
        assert FakeAuthClient.calls[0][2]["json"] == {"email": "person@example.com", "type": "signup"}
    finally:
        FakeAuthClient.response_status = 400
        app.dependency_overrides.clear()


def test_signup_resend_does_not_hide_provider_rate_limit(factory, seed, monkeypatch):
    FakeAuthClient.calls = []
    FakeAuthClient.response_status = 429
    FakeAuthClient.response_json = {"code": "over_email_send_rate_limit"}
    monkeypatch.setattr(auth_routes.httpx, "AsyncClient", lambda **kwargs: FakeAuthClient())
    client = configured_client(factory)
    try:
        response = client.post("/v1/auth/resend-signup", json={"email": "person@example.com"})
        assert response.status_code == 429
        assert response.json()["error"]["code"] == "rate_limited"
        assert "over_email_send_rate_limit" not in response.text
    finally:
        FakeAuthClient.response_status = 400
        FakeAuthClient.response_json = {"error": "invalid"}
        app.dependency_overrides.clear()


def test_signup_resend_does_not_claim_success_on_provider_failure(factory, seed, monkeypatch):
    FakeAuthClient.calls = []
    FakeAuthClient.response_status = 400
    FakeAuthClient.response_json = {"code": "email_address_not_authorized"}
    monkeypatch.setattr(auth_routes.httpx, "AsyncClient", lambda **kwargs: FakeAuthClient())
    client = configured_client(factory)
    try:
        response = client.post("/v1/auth/resend-signup", json={"email": "person@example.com"})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "email_unavailable"
        assert "email_address_not_authorized" not in response.text
    finally:
        FakeAuthClient.response_json = {"error": "invalid"}
        app.dependency_overrides.clear()


@pytest.mark.parametrize("account_type", ["consumer", "vendor"])
def test_registration_keeps_account_type_and_exact_password(factory, monkeypatch, account_type):
    FakeAuthClient.calls = []
    monkeypatch.setattr(auth_routes.httpx, "AsyncClient", lambda **kwargs: FakeAuthClient())
    client = configured_client(factory)
    try:
        client.post(
            "/v1/auth/register",
            json={
                "email": " person@example.com ",
                "password": " Secret123 ",
                "name": " Ana ",
                "account_type": account_type,
            },
        )
        assert FakeAuthClient.calls[0][2]["json"] == {
            "email": "person@example.com",
            "password": " Secret123 ",
            "data": {"name": "Ana", "account_type": account_type},
        }
        client.post("/v1/auth/login", json={"email": "person@example.com", "password": " Secret123 "})
        assert FakeAuthClient.calls[1][2]["json"]["password"] == " Secret123 "
    finally:
        app.dependency_overrides.clear()


def test_login_accepts_legacy_short_password_but_registration_does_not(factory, monkeypatch):
    FakeAuthClient.calls = []
    monkeypatch.setattr(auth_routes.httpx, "AsyncClient", lambda **kwargs: FakeAuthClient())
    client = configured_client(factory)
    try:
        payload = {"email": "person@example.com", "password": "short"}
        assert client.post("/v1/auth/login", json=payload).status_code == 401
        assert FakeAuthClient.calls[0][2]["json"]["password"] == "short"
        assert client.post("/v1/auth/register", json={**payload, "name": "Ana"}).status_code == 422
        assert len(FakeAuthClient.calls) == 1
    finally:
        app.dependency_overrides.clear()


def test_registration_reports_email_confirmation_only_when_provider_requires_it(factory, monkeypatch):
    FakeAuthClient.response_status = 200
    FakeAuthClient.response_json = {"id": "pending-user", "email": "person@example.com"}
    monkeypatch.setattr(auth_routes.httpx, "AsyncClient", lambda **kwargs: FakeAuthClient())
    client = configured_client(factory)
    try:
        response = client.post(
            "/v1/auth/register",
            json={
                "email": "person@example.com",
                "password": "Secret123",
                "name": "Ana",
            },
        )
        assert response.json()["requires_email_confirmation"] is True
    finally:
        FakeAuthClient.response_status = 400
        FakeAuthClient.response_json = {"error": "invalid"}
        app.dependency_overrides.clear()


@pytest.mark.parametrize("provider_response", [[], "bad-response", {"code": "unexpected_failure"}])
def test_provider_failure_is_not_presented_as_email_failure(factory, monkeypatch, provider_response):
    FakeAuthClient.response_status = 500
    FakeAuthClient.response_json = provider_response
    monkeypatch.setattr(auth_routes.httpx, "AsyncClient", lambda **kwargs: FakeAuthClient())
    client = configured_client(factory)
    try:
        response = client.post(
            "/v1/auth/login", json={"email": "person@example.com", "password": "Secret123"}
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "auth_unavailable"
        assert "enviar" not in response.json()["error"]["message"]
    finally:
        FakeAuthClient.response_status = 400
        FakeAuthClient.response_json = {"error": "invalid"}
        app.dependency_overrides.clear()


@pytest.mark.parametrize("status", [200, 502])
def test_malformed_provider_json_returns_retryable_error(factory, monkeypatch, status):
    class BrokenJSONClient(FakeAuthClient):
        async def request(self, *args, **kwargs):
            return httpx.Response(status, text="<html>Proxy unavailable</html>")

    monkeypatch.setattr(auth_routes.httpx, "AsyncClient", lambda **kwargs: BrokenJSONClient())
    client = configured_client(factory)
    try:
        response = client.post(
            "/v1/auth/login", json={"email": "person@example.com", "password": "Secret123"}
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "auth_unavailable"
        assert "Proxy" not in response.text
    finally:
        app.dependency_overrides.clear()


def test_provider_connection_failure_is_retryable(factory, monkeypatch):
    class OfflineClient(FakeAuthClient):
        async def request(self, *args, **kwargs):
            raise httpx.ConnectError("Network unavailable")

    monkeypatch.setattr(auth_routes.httpx, "AsyncClient", lambda **kwargs: OfflineClient())
    client = configured_client(factory)
    try:
        response = client.post(
            "/v1/auth/login", json={"email": "person@example.com", "password": "Secret123"}
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "auth_unavailable"
    finally:
        app.dependency_overrides.clear()
