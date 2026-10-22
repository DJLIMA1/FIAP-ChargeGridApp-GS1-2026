"""Assistente com o contexto da conta e as ferramentas novas (motorista e dono), sem rede."""

import json
import uuid
from datetime import timedelta

from sqlalchemy import select
from test_ai import FakeLLM, ask, client_for, no_network, reply  # noqa: F401 - fixture autouse

from app.errors import fail
from app.models import ChargingSession, Connector, DriverProfile, Profile, SimulatedWallet, Station, now
from app.modules.ai import source as ai_source

DEMAND_WORDS = ("demand", "demanda", "multiplier", "multiplicador", "acréscimo")


def fast_point(factory, seed, price=2.5):
    with factory.begin() as db:
        point = Connector(station_id=seed["station"], public_code="CG-DC", connector_type="CCS2", power_kw=50,
                          price_per_kwh=price, max_duration_minutes=240)
        db.add(point)
        db.flush()
        return point.id


def finished_session(factory, user_id, connector_id, *, hours=2, **extra):
    with factory.begin() as db:
        obj = ChargingSession(user_id=user_id, connector_id=connector_id, status="completed", max_duration_minutes=60,
                              price_per_kwh=extra.pop("price", 2), energy_wh=extra.pop("energy_wh", 10000),
                              cost_estimate=extra.pop("cost", 20), created_at=now() - timedelta(hours=hours),
                              started_at=now() - timedelta(hours=hours), ended_at=now() - timedelta(hours=hours - 1),
                              soc_percent=80, **extra)
        db.add(obj)
        db.flush()
        return obj.id


def tool_result(llm, index=1):
    return json.loads(llm.calls[index]["messages"][-1]["content"])


def test_cost_question_uses_saved_car_and_app_soc(factory, seed):
    fast_point(factory, seed)
    finished_session(factory, seed["a"], seed["point"])
    with factory.begin() as db:
        db.add(DriverProfile(user_id=seed["a"], vehicle={"preset": "byd_seal"}, preferences={}))
    llm = FakeLLM(reply(calls=[("estimate_charge", {"from_percent": 20, "to_percent": 80})]),
                  reply("No seu BYD Seal, de 20% a 80% custa cerca de R$ 123,75."))
    client, _ = client_for(factory, seed["a"], llm)
    response = ask(client, "quanto custa para carregar de 20% a 80%", soc_percent=37, soc_source="simulated")
    assert response.status_code == 200, response.text
    system = llm.calls[0]["messages"][0]["content"]
    assert "DADOS DA CONTA" in system and "BYD Seal" in system and "nível estimado pelo app" in system
    assert "Nunca peça a capacidade da bateria" in system
    data = tool_result(llm)
    best = data["options"][0]
    assert data["car"] == "BYD Seal" and best["why"] == "posto que você mais usa"
    assert best["energy_kwh"] == 49.5 and best["point_code"] == "CG-DC" and best["power_used_kw"] == 50
    assert best["cost_brl"] == round(49.5 * 2.5, 2)
    assert response.json()["suggested_actions"][0] == {"type": "open_station", "station_id": str(seed["station"]),
                                                       "label": "Ver Demo"}


def test_driver_tools_hide_demand_and_explain_own_session_only(factory, seed):
    mine = finished_session(factory, seed["a"], seed["point"], price=2.6, cost=23.4, energy_wh=10000,
                            base_price_per_kwh=2, demand_multiplier=1.3, discount_percent=10,
                            price_terms={"demand": {"level_label": "Alta", "reason_label": "Posto cheio"},
                                         "coupon": {"code": "BEMVINDO", "discount_percent": 10}})
    other = finished_session(factory, seed["b"], seed["point"])
    llm = FakeLLM(reply(calls=[("explain_my_session", {}), ("get_station_details", {"station_id": str(seed["station"])}),
                               ("explain_my_session", {"session_id": str(other)})]),
                  reply("Sua última recarga custou R$ 23,40."))
    client, _ = client_for(factory, seed["a"], llm)
    body = ask(client, "explique minha última recarga").json()
    results = [json.loads(m["content"]) for m in llm.calls[1]["messages"] if m["role"] == "tool"]
    explained, station, foreign = results
    assert explained["session_id"] == str(mine) and explained["locked_price_per_kwh"] == 2.6
    assert explained["coupon"] == {"code": "BEMVINDO", "discount_percent": 10}
    assert foreign == {"error": "recarga não encontrada"}
    text = json.dumps(results + [llm.calls[0]["messages"][0]["content"].split("DADOS DA CONTA")[-1]],
                      ensure_ascii=False).lower()
    for word in DEMAND_WORDS:
        assert word not in text, word
    assert station["points"][0]["price_per_kwh"] == 2.0
    assert {"type": "open_receipt", "session_id": str(mine), "label": "Ver recibo"} in body["suggested_actions"]


def test_wallet_tool_reads_without_creating_rows(factory, seed):
    llm = FakeLLM(reply(calls=[("get_my_wallet", {})]), reply("Seu saldo é R$ 0,00."))
    client, _ = client_for(factory, seed["a"], llm)
    body = ask(client, "qual meu saldo?").json()
    assert tool_result(llm)["balance_brl"] == 0.0
    with factory() as db:
        assert db.scalar(select(SimulatedWallet.user_id)) is None
    assert body["suggested_actions"] == [{"type": "open_wallet", "label": "Abrir carteira"}]


def test_driver_cannot_get_owner_tools_even_in_owner_mode(factory, seed):
    llm = FakeLLM(reply(calls=[("get_owner_overview", {})]), reply("Não posso."))
    client, _ = client_for(factory, seed["a"], llm)
    ask(client, "receita dos postos", mode="owner")
    names = [t["function"]["name"] for t in llm.calls[0]["tools"]]
    assert not any(name.startswith(("get_owner", "get_margin", "get_tariff", "get_coupon")) for name in names)
    assert "não permitida" in tool_result(llm)["error"]


def test_owner_overview_matches_dashboard_and_context(factory, seed):
    finished_session(factory, seed["a"], seed["point"], cost=10, energy_wh=5000)
    llm = FakeLLM(reply(calls=[("get_owner_overview", {"period": "30d"})]), reply("Receita de R$ 10,00."))
    client, _ = client_for(factory, seed["owner"], llm)
    body = ask(client, "como foram meus postos?", mode="owner").json()
    names = [t["function"]["name"] for t in llm.calls[0]["tools"]]
    assert "get_owner_overview" in names and "estimate_charge" not in names and "get_owner_indicators" not in names
    system = llm.calls[0]["messages"][0]["content"]
    assert "Modo dono de posto" in system and '"last_7_days"' in system and "Demo" in system
    data = tool_result(llm)
    dashboard = client.get("/v1/owner/overview", params={"from": (now() - timedelta(days=29)).isoformat()}).json()
    assert data["kpis"]["revenue"] == dashboard["kpis"]["revenue"] == "10.00"
    assert data["kpis"]["sessions"] == dashboard["kpis"]["sessions"] == 1
    assert data["period"] == "últimos 30 dias"
    assert body["suggested_actions"] == [{"type": "open_owner_history", "label": "Ver histórico dos postos"}]


def test_owner_tools_never_reach_another_owners_station(factory, seed):
    with factory.begin() as db:
        rival = Profile(id=uuid.uuid4(), name="Rival", operator_enabled=True)
        db.add(rival)
        db.flush()
        db.add(Station(owner_id=rival.id, name="Rival Posto", address="X", latitude=0, longitude=0))
        rival_id = rival.id
    session = finished_session(factory, seed["a"], seed["point"])
    llm = FakeLLM(reply(calls=[("get_owner_overview", {"station": str(seed["station"])}),
                               ("get_owner_ranking", {"station": "Demo"}),
                               ("explain_owner_session", {"session_id": str(session)}),
                               ("get_tariff_suggestions", {"station": str(seed["station"])})]),
                  reply("Não encontrei."))
    client, _ = client_for(factory, rival_id, llm)
    ask(client, "como está o posto Demo?", mode="owner")
    results = [json.loads(m["content"]) for m in llm.calls[1]["messages"] if m["role"] == "tool"]
    assert results[0] == results[1] == {"error": "posto não encontrado entre os seus postos"}
    assert results[2] == {"error": "recarga não encontrada nos seus postos"}
    assert results[3]["error"] == "posto não encontrado entre os seus postos"
    assert "Demo" not in llm.calls[0]["messages"][0]["content"].split("DADOS DA CONTA")[-1]


def test_owner_session_and_tariffs_keep_demand_for_owner(factory, seed):
    session = finished_session(factory, seed["a"], seed["point"], price=2.6, cost=26, base_price_per_kwh=2,
                               demand_multiplier=1.3, price_terms={"demand": {"level_label": "Alta"}})
    llm = FakeLLM(reply(calls=[("explain_owner_session", {}), ("get_tariff_suggestions", {"station": "demo"})]),
                  reply("A recarga teve ajuste por demanda de 1,30×."))
    client, _ = client_for(factory, seed["owner"], llm)
    body = ask(client, "explique a última recarga", mode="owner").json()
    explained, tariffs = [json.loads(m["content"]) for m in llm.calls[1]["messages"] if m["role"] == "tool"]
    assert explained["session_id"] == str(session) and explained["demand"]["multiplier"] == "1.30"
    assert "user_id" not in json.dumps(explained) and str(seed["a"]) not in json.dumps(explained)
    assert tariffs["station_name"] == "Demo" and "how_to_apply" in tariffs and "error" not in tariffs
    assert {"type": "open_tariffs", "station_id": str(seed["station"]), "label": "Abrir tarifas"} in body["suggested_actions"]


def test_business_errors_become_tool_errors(factory, seed, monkeypatch):
    def too_large(*args, **kwargs):
        fail("export_too_large", "Mais de 10000 sessões. Reduza o período ou filtre um posto.", 413)
    monkeypatch.setattr(ai_source.economics_service, "margin_report", too_large)
    llm = FakeLLM(reply(calls=[("get_margin_report", {"period": "90d"})]), reply("Reduza o período."))
    client, _ = client_for(factory, seed["owner"], llm)
    response = ask(client, "margem dos últimos 90 dias", mode="owner")
    assert response.status_code == 200
    assert tool_result(llm) == {"error": "Mais de 10000 sessões. Reduza o período ou filtre um posto."}


def test_chat_context_validates_soc(factory, seed):
    client, _ = client_for(factory, seed["a"], FakeLLM())
    assert ask(client, "oi", soc_percent=140).status_code == 422
    assert ask(client, "oi", soc_source="hacked").status_code == 422
