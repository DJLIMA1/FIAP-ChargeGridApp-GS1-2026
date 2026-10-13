"""Regressões da revisão de integração (docs/revisao-integracao-2026-10.md)."""

import asyncio
import json
import time
from datetime import datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

from app.database import db_session
from app.main import app
from app.models import ChargingSession, Connector, Device, Profile, Station, now
from app.modules.ai.client import OpenRouterClient, get_llm
from app.modules.ai.source import DbSource
from app.modules.driver import routes as driver_routes
from app.modules.driver import weather
from app.security import current_user, digest
from chargegrid_core.ai import LLMUnavailable

SAO_PAULO = {"lat": -23.5505, "lng": -46.6333}


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    weather.clear_cache()
    monkeypatch.setattr(driver_routes, "local_now", lambda: datetime(2026, 10, 13, 14, 0))
    monkeypatch.setattr(driver_routes, "weather_signal", lambda lat, lng: None)
    yield
    app.dependency_overrides.clear()


def client_for(factory, user_id, llm=None):
    selected, sessions = {"id": user_id}, []

    def database():
        with factory() as db:
            sessions.append(db)
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
    app.dependency_overrides[get_llm] = lambda: llm
    return TestClient(app), selected, sessions


def completion(content="", calls=()):
    return {"content": content, "model": "fake/model", "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": 0},
            "tool_calls": [{"id": f"c{i}", "name": name, "arguments": json.dumps(args)}
                           for i, (name, args) in enumerate(calls)]}


def hidden_point(db, owner, *, station_active=True, point_active=True):
    station = Station(owner_id=owner, name="Oculto", address="Rua X", latitude=0, longitude=0, active=station_active)
    db.add(station)
    db.flush()
    point = Connector(station_id=station.id, public_code=f"HID-{station_active}-{point_active}",
                      connector_type="CCS2", power_kw=50, price_per_kwh=Decimal("9.99"), active=point_active)
    db.add(point)
    db.flush()
    return point.id


# --- IA ---------------------------------------------------------------------------

def test_assistant_cannot_read_unpublished_points_or_stations(factory, seed):
    with factory.begin() as db:
        inactive_station = hidden_point(db, seed["owner"], station_active=False)
        inactive_point = hidden_point(db, seed["owner"], point_active=False)
        orphan = Station(owner_id=None, name="Fábrica", address="-", latitude=0, longitude=0, active=True)
        db.add(orphan)
        db.flush()
        orphan_id = orphan.id
    with factory() as db:
        user = db.get(Profile, seed["a"])
        source = DbSource(db, user)
        assert source.get_connector(str(inactive_station)) is None
        assert source.get_connector(str(inactive_point)) is None
        assert source.get_station(str(orphan_id)) is None
        assert source.get_connector(str(seed["point"]))["code"] == "CG-01"


def test_chat_estimate_on_hidden_point_returns_tool_error(factory, seed):
    with factory.begin() as db:
        hidden = hidden_point(db, seed["owner"], station_active=False)

    class Script:
        def __init__(self):
            self.calls = []

        async def __call__(self, messages, tools, timeout=None, tool_choice="auto", **options):
            self.calls.append(messages)
            if len(self.calls) == 1:
                return completion(calls=[("estimate_charge", {"connector_id": str(hidden), "energy_kwh": 10})])
            return completion("Não encontrei esse ponto.")

    llm = Script()
    client, _, _ = client_for(factory, seed["a"], llm)
    response = client.post("/v1/ai/chat", json={"messages": [{"role": "user", "content": "quanto custa?"}]})
    assert response.status_code == 200, response.text
    tool_result = json.loads(llm.calls[1][-1]["content"])
    assert "error" in tool_result and "9.99" not in llm.calls[1][-1]["content"]


def test_ai_routes_end_the_db_transaction_before_waiting_for_the_model(factory, seed):
    seen = []

    class Probe:
        def __init__(self, sessions):
            self.sessions = sessions

        async def __call__(self, messages, tools, timeout=None, tool_choice="auto", **options):
            seen.append(self.sessions[-1].in_transaction())
            if len(seen) == 1:
                return completion(calls=[("get_my_charging_history", {})])
            return completion("Você ainda não tem recargas.")

    client, _, sessions = client_for(factory, seed["a"])
    app.dependency_overrides[get_llm] = lambda: Probe(sessions)
    response = client.post("/v1/ai/chat", json={"messages": [{"role": "user", "content": "meu histórico"}]})
    assert response.status_code == 200, response.text
    assert seen == [False, False]  # nenhuma conexão "idle in transaction" durante a chamada ao modelo
    assert client.post("/v1/ai/search", json={"query": "ccs2 perto da paulista"}).status_code == 200
    assert seen[-1] is False


def test_malformed_provider_payload_is_a_friendly_503_not_a_500(factory, seed):
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": "texto solto"}], "usage": "x"})

    llm = OpenRouterClient("sk-test", ["a"], transport=httpx.MockTransport(handler))
    client, _, _ = client_for(factory, seed["a"], llm)
    response = client.post("/v1/ai/chat", json={"messages": [{"role": "user", "content": "oi"}]})
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] in ("ai_bad_response", "ai_unavailable")


def test_openrouter_client_enforces_a_total_deadline():
    async def slow(request):
        await asyncio.sleep(5)
        return httpx.Response(200, json={"choices": [{"message": {"content": "tarde"}}]})

    llm = OpenRouterClient("sk-test", ["a"], transport=httpx.MockTransport(slow))
    started = time.monotonic()
    with pytest.raises(LLMUnavailable) as error:
        asyncio.run(llm([{"role": "user", "content": "oi"}], None, timeout=1))
    assert error.value.code == "ai_timeout"
    assert time.monotonic() - started < 3


# --- Dashboard do proprietário ------------------------------------------------------------

def test_owner_search_treats_like_wildcards_literally(factory, seed):
    moment = now()
    with factory.begin() as db:
        db.add(ChargingSession(user_id=seed["a"], connector_id=seed["point"], status="completed",
                               max_duration_minutes=30, price_per_kwh=2, energy_wh=1000, cost_estimate=2,
                               created_at=moment - timedelta(hours=2), started_at=moment - timedelta(hours=2),
                               ended_at=moment - timedelta(hours=1)))
    client, _, _ = client_for(factory, seed["owner"])
    params = {"from": (moment - timedelta(days=1)).isoformat(), "to": (moment + timedelta(minutes=1)).isoformat()}
    assert client.get("/v1/owner/sessions", params={**params, "q": "cg-01"}).json()["total"] == 1
    for wildcard in ("%", "_G-01", "C%1"):
        body = client.get("/v1/owner/sessions", params={**params, "q": wildcard}).json()
        assert body["total"] == 0, wildcard
        assert client.get("/v1/owner/reservations", params={**params, "q": wildcard}).json()["total"] == 0


# --- Modo Motorista -------------------------------------------------------------------------

def test_next_stop_with_empty_battery_never_says_keep_driving(factory, seed):
    with factory.begin() as db:
        station = Station(owner_id=seed["owner"], name="Hub Rápido", address="Rua Teste", latitude=-23.552,
                          longitude=-46.634)
        db.add(station)
        db.flush()
        point = Connector(station_id=station.id, public_code="DRV-1", connector_type="CCS2", power_kw=60,
                          price_per_kwh="2.20", max_duration_minutes=120)
        db.add(point)
        db.flush()
        db.add(Device(connector_id=point.id, key_hash=digest("review-driver"), reconciled=True, last_seen=now(),
                      physical_state="idle"))
    client, _, _ = client_for(factory, seed["a"])
    client.put("/v1/driver/profile", json={"preferences": {"shift_start": "10:00", "shift_end": "20:00"}})
    empty = client.post("/v1/driver/next-stop", json={"soc_percent": 0, **SAO_PAULO})
    assert empty.status_code == 200, empty.text
    recommendation = empty.json()["recommendation"]
    assert recommendation["action"] == "charge_needed" and recommendation["station_name"] == "Hub Rápido"
    far = client.post("/v1/driver/next-stop", json={"soc_percent": 5, "lat": -10.0, "lng": -50.0, "radius_km": 5})
    assert far.json()["recommendation"]["action"] == "charge_needed"
    assert "station_id" not in far.json()["recommendation"]


def test_session_insight_only_for_finished_sessions(factory, seed):
    moment = now()
    with factory.begin() as db:
        active = ChargingSession(user_id=seed["a"], connector_id=seed["point"], status="charging",
                                 max_duration_minutes=30, price_per_kwh=2, energy_wh=500, cost_estimate=1,
                                 created_at=moment - timedelta(minutes=5), started_at=moment - timedelta(minutes=4))
        db.add(active)
        db.flush()
        active_id = active.id
    client, _, _ = client_for(factory, seed["a"])
    response = client.post("/v1/ai/session-insight", json={"session_id": str(active_id)})
    assert response.status_code == 409 and response.json()["error"]["code"] == "session_not_finished"


def test_driver_planner_is_rate_limited_per_user(factory, seed, monkeypatch):
    monkeypatch.setattr(driver_routes, "PLAN_LIMIT", (2, 60))
    client, selected, _ = client_for(factory, seed["a"])
    codes = [client.post("/v1/driver/next-stop", json={"soc_percent": 50}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    selected["id"] = seed["b"]  # limite é por usuário
    assert client.post("/v1/driver/plan", json={"soc_percent": 50}).status_code == 200


def test_assistant_station_list_prefers_the_nearest_when_capped(factory, seed, monkeypatch):
    from app.modules.ai import source as ai_source
    monkeypatch.setattr(ai_source, "MAX_STATIONS", 2)
    with factory.begin() as db:
        for index, lat in enumerate((-23.70, -23.5614, -23.40, -23.5620)):
            db.add(Station(owner_id=seed["owner"], name=f"Posto {index}", address="Rua", latitude=lat,
                           longitude=-46.6559))
    with factory() as db:
        source = DbSource(db, db.get(Profile, seed["a"]))
        names = [row["name"] for row in source.list_stations({"lat": -23.5614, "lng": -46.6559}, 30)]
    assert names == ["Posto 1", "Posto 3"]
