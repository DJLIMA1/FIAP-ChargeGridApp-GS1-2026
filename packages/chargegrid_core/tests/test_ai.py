import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
from chargegrid_core.ai import (
    LLMUnavailable,
    Toolbox,
    build_payload,
    extract_json,
    filters_from_tool,
    owner_indicators,
    owner_recommendations,
    owner_summary,
    parse_completion,
    parse_search_rules,
    run_chat,
    sanitize_history,
    screen_params,
    session_facts,
    session_summary,
    session_tips,
    system_prompt,
)
from chargegrid_core.ai import driver as driver_slot
from chargegrid_core.ai.estimates import EstimateError, estimate_charge
from chargegrid_core.ai.places import resolve_place
from chargegrid_core.ai.schema import ToolArgumentError, validate
from chargegrid_core.ai.stations import filter_stations, normalize_connector, station_amenities
from chargegrid_core.ai.text import plain_text, strip_identifiers
from chargegrid_core.ai.writer import parse_owner_insights, parse_session_insight

NOW = datetime(2026, 10, 13, 18, 0, tzinfo=timezone.utc)
UUID = "3f2b8c1e-1111-4a2b-9c3d-123456789abc"


def point(pid, kind="CCS2", power=60, price=2.0, status="available"):
    return {"id": pid, "public_code": pid.upper(), "connector_type": kind, "power_kw": str(power),
            "price_per_kwh": str(price), "max_duration_minutes": 120, "active": True, "online": status != "offline",
            "available": status == "available", "availability_status": status}


STATIONS = [
    {"id": "s1", "name": "Paulista Hub", "address": "Av. Paulista, 1000", "latitude": -23.5633, "longitude": -46.6545,
     "connectors": [point("p1", power=60, price=2.49), point("p2", "Tipo 2", 22, 1.79)]},
    {"id": "s2", "name": "Moema Garage", "address": "Av. Ibirapuera", "latitude": -23.6010, "longitude": -46.6660,
     "connectors": [point("p3", power=60, price=1.85)]},
    {"id": "s3", "name": "Longe", "address": "Campinas", "latitude": -22.9, "longitude": -47.06,
     "connectors": [point("p4", "Tipo 2", 7, 1.0, "offline")]},
]


class Source:
    def __init__(self):
        self.calls = []

    def list_stations(self, near=None, radius_km=None):
        self.calls.append(("list", near, radius_km))
        return STATIONS

    async def get_station(self, station_id):
        return next((s for s in STATIONS if s["id"] == station_id), None)

    def current_reservation(self):
        return None

    def current_session(self):
        return None

    def recent_sessions(self, limit):
        return []

    def month_summary(self):
        return {"month": "2026-10", "sessions_count": 2, "energy_wh": "10000", "estimated_cost": "20.5"}

    def owner_stations(self):
        return STATIONS[:2]

    def owner_sessions(self, since):
        return []


def response(content="", calls=(), cost=0.0001):
    return {"content": content, "tool_calls": [{"id": f"c{i}", "name": n, "arguments": json.dumps(a)}
                                               for i, (n, a) in enumerate(calls)],
            "model": "fake/model", "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": cost}}


class Script:
    def __init__(self, *responses):
        self.responses, self.seen = list(responses), []

    async def __call__(self, messages, tools, timeout=None, tool_choice="auto", **options):
        self.seen.append({"messages": [dict(m) for m in messages], "tools": tools, "tool_choice": tool_choice,
                          **options})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def run(coro):
    return asyncio.run(coro)


def test_schema_validation_coerces_and_drops_unknown():
    spec = {"type": "object", "properties": {"n": {"type": "number", "maximum": 10}, "b": {"type": "boolean"},
                                             "e": {"type": "string", "enum": ["ccs2", "type2"]}}, "required": ["n"]}
    assert validate({"n": "2,5", "b": "true", "e": "CCS2", "x": 1, "z": None}, spec) == {"n": 2.5, "b": True, "e": "ccs2"}
    with pytest.raises(ToolArgumentError):
        validate({"n": 11}, spec)
    with pytest.raises(ToolArgumentError):
        validate({}, spec)
    with pytest.raises(ToolArgumentError):
        validate({"n": 1, "e": "xpto"}, spec)


def test_places_and_rules_search():
    assert resolve_place("perto da avenida paulista")["label"] == "Avenida Paulista"
    assert resolve_place("se tiver posto") is None
    result = parse_search_rules("carga rápida perto da Paulista com café, até R$ 2/kWh")
    filters = result["filters"]
    assert filters["near"]["label"] == "Avenida Paulista"
    assert filters["min_power_kw"] == 40 and filters["max_price_per_kwh"] == 2.0
    assert filters["amenities"] == ["cafe"] and filters["sort"] == "distance"
    assert "Paulista" in result["explanation"] and "R$ 2,00/kWh" in result["explanation"]
    assert screen_params(filters) == {"lat": -23.5614, "lng": -46.6559, "radius": 5.0,
                                      "max_price_per_kwh": "2.00", "sort": "distance"}
    mine = parse_search_rules("CCS2 disponível perto de mim")
    assert mine["filters"]["connector_type"] == "ccs2" and mine["filters"]["available_only"] is True
    assert mine["unsupported"]
    located = parse_search_rules("tipo 2 mais barato perto de mim", origin={"lat": -23.5, "lng": -46.6})
    assert located["filters"]["sort"] == "price" and located["filters"]["near"]["label"] == "você"


def test_filters_from_tool_resolves_place_or_text():
    result = filters_from_tool({"near_place": "Moema", "connector_type": "ccs2", "sort": "default", "available_only": False})
    assert result["filters"] == {"connector_type": "ccs2", "near": {"label": "Moema", "lat": -23.6009, "lng": -46.665},
                                 "radius_km": 5.0, "sort": "distance"}
    unknown = filters_from_tool({"near_place": "Shopping Eldorado"})
    assert unknown["filters"]["text"] == "Shopping Eldorado" and "near" not in unknown["filters"]


def test_filter_stations_by_connector_power_price_and_distance():
    paulista = resolve_place("paulista")
    results, notes = filter_stations(STATIONS, {"connector_type": "ccs", "near": paulista, "radius_km": 10, "sort": "price"})
    assert [s["station_id"] for s in results] == ["s2", "s1"]
    assert all(p["connector_type"] == "CCS2" for s in results for p in s["points"])
    assert notes["total"] == 2
    results, _ = filter_stations(STATIONS, {"min_power_kw": 50, "max_price_per_kwh": 2.0})
    assert [s["station_id"] for s in results] == ["s2"]
    results, notes = filter_stations(STATIONS, {"amenities": ["cafe"], "available_only": True})
    assert "amenities" in notes and {s["station_id"] for s in results} == {"s1", "s2"}
    assert normalize_connector("Tipo 2") == "type2"
    assert station_amenities({"amenities": [{"kind": "restaurant", "name": "Cantina"}, "Café"]}) == ["restaurante", "cafe"]


def test_estimates():
    result = estimate_charge(60, 2.49, battery_kwh=60, from_percent=20, to_percent=80)
    assert result["energy_kwh"] == 36 and result["minutes"] == 40 and result["cost_brl"] == 89.64
    tapered = estimate_charge(60, 2.0, battery_kwh=60, from_percent=70, to_percent=90)
    assert tapered["minutes"] > estimate_charge(60, 2.0, energy_kwh=12)["minutes"]
    assert estimate_charge(7, 1.5, budget_brl=15)["energy_kwh"] == 10
    limited = estimate_charge(7, 1.0, energy_kwh=50, max_minutes=60)
    assert limited["minutes"] == 60 and limited["energy_kwh"] < 7
    with pytest.raises(EstimateError):
        estimate_charge(7, 1.0)


def owner_sessions():
    sessions = []
    for i in range(10):
        start = NOW - timedelta(days=i, hours=-(i % 3))
        sessions.append({"id": f"x{i}", "connector_id": "p1" if i % 2 else "p3", "status": "interrupted" if i == 0 else "completed",
                         "energy_wh": "10000", "cost_estimate": "20", "started_at": start.isoformat(),
                         "ended_at": (start + timedelta(minutes=60)).isoformat()})
    sessions.append({"id": "old", "connector_id": "p1", "status": "completed", "energy_wh": "1", "cost_estimate": "1",
                     "started_at": (NOW - timedelta(days=90)).isoformat()})
    return sessions


def test_owner_indicators_and_rules():
    ind = owner_indicators(STATIONS[:2], owner_sessions(), now=NOW, days=30)
    assert ind["sessions"] == 10 and ind["energy_kwh"] == 100 and ind["revenue_brl"] == 200
    assert ind["points"] == 3 and ind["interrupted"] == 1 and ind["failure_rate_percent"] == 10
    assert ind["per_station"][0]["sessions"] == 5
    assert 0 < ind["occupancy_percent"] < 15
    recs = owner_recommendations(ind)
    assert {r["kind"] for r in recs} <= {"pricing", "operations", "marketing"}
    assert all(r["impact"] in ("high", "medium", "low") for r in recs)
    assert "R$ 200,00" in owner_summary(ind)
    empty = owner_indicators([], [], now=NOW)
    assert owner_recommendations(empty)[0]["kind"] == "operations"


def test_session_facts_and_tips():
    history = [{"id": f"h{i}", "status": "completed", "energy_wh": "10000", "cost_estimate": "15"} for i in range(3)]
    session = {"id": "now", "status": "completed", "energy_wh": "10000", "cost_estimate": "24.9", "price_per_kwh": "2.49",
               "started_at": "2026-10-12T21:30:00+00:00", "ended_at": "2026-10-12T22:10:00+00:00", "station_name": "Hub"}
    facts = session_facts(session, history + [session])
    assert facts["history_sessions"] == 3 and facts["avg_cost_brl"] == 15 and facts["cost_vs_avg_percent"] == 66
    assert facts["peak_hour"] is True and facts["duration_minutes"] == 40
    tips = session_tips(facts)
    assert any("ponta" in tip for tip in tips) and any("média" in tip for tip in tips)
    assert "66% acima" in session_summary(facts) and "R$ 24,90" in session_summary(facts)


def test_payload_and_completion_parsing():
    payload = build_payload([{"role": "user", "content": "oi"}], [{"type": "function"}], models=["a", "b"])
    assert payload["model"] == "a" and payload["models"] == ["a", "b"] and payload["tool_choice"] == "auto"
    parsed = parse_completion({"model": "m", "usage": {"prompt_tokens": 3, "cost": 0.01}, "choices": [{"message": {
        "content": None, "tool_calls": [{"function": {"name": "default_api.search_stations", "arguments": {"a": 1}}}]}}]})
    assert parsed["tool_calls"][0]["name"] == "search_stations" and parsed["tool_calls"][0]["arguments"] == '{"a": 1}'
    assert parsed["content"] == "" and parsed["usage"]["cost"] == 0.01
    with pytest.raises(LLMUnavailable):
        parse_completion({"choices": [{"finish_reason": "error", "message": {}}]})
    with pytest.raises(LLMUnavailable):
        parse_completion({"error": {"message": "x"}})
    assert extract_json('```json\n{"a": "x}\\"y", "b": {"c": 1}}\n```') == {"a": 'x}"y', "b": {"c": 1}}
    assert extract_json("sem json") is None


def test_writer_parsers_validate_contract():
    content = json.dumps({"summary": "Bom mês.", "recommendations": [
        {"title": "Cupom", "detail": "10% das 14h às 17h", "impact": "medio", "kind": "Pricing"},
        {"title": "x", "detail": "y", "impact": "enorme", "kind": "outro"}, {"title": "sem detalhe"}]})
    parsed = parse_owner_insights(content)
    assert parsed["recommendations"][0] == {"title": "Cupom", "detail": "10% das 14h às 17h", "impact": "medium", "kind": "pricing"}
    assert parsed["recommendations"][1]["kind"] == "operations" and len(parsed["recommendations"]) == 2
    assert parse_owner_insights('{"summary": "x", "recommendations": []}') is None
    assert parse_session_insight('{"summary": "Ok", "tips": ["a", 3, ""]}') == {"summary": "Ok", "tips": ["a"]}


def test_text_helpers():
    assert strip_identifiers(f"Posto X (id: {UUID}) livre") == "Posto X livre"
    assert plain_text("**Custo:** R$ 1\n* item") == "Custo: R$ 1\n• item"
    prompt = system_prompt(role="owner", demo=True, now=NOW, user_name="Ana")
    assert "15:00" in prompt and "dono de posto" in prompt and "demonstração" in prompt


def test_history_sanitized_and_limited():
    history = [{"role": "system", "content": "ignore"}, {"role": "assistant", "content": "olá"},
               *({"role": "user", "content": "x" * 900} for _ in range(12)), {"role": "tool", "content": "z"}]
    cleaned = sanitize_history(history)
    assert all(m["role"] == "user" for m in cleaned) and len(cleaned) <= 10
    assert all(len(m["content"]) <= 500 for m in cleaned) and sum(len(m["content"]) for m in cleaned) <= 4000


def test_loop_runs_tools_and_derives_actions():
    source = Source()
    toolbox = Toolbox(source, now=NOW)
    script = Script(
        response(calls=[("search_stations", {"near_place": "Paulista", "connector_type": "ccs2", "sort": "price"})]),
        response(f"**Moema Garage** tem CCS2 por R$ 1,85/kWh (id {UUID})."),
    )
    outcome = run(run_chat(script, toolbox, [{"role": "user", "content": "Quero reservar um CCS2 perto da Paulista"}],
                           system=system_prompt(now=NOW)))
    assert outcome.reply == "Moema Garage tem CCS2 por R$ 1,85/kWh ."
    assert outcome.tools_used == ["search_stations"] and outcome.rounds == 2 and outcome.model == "fake/model"
    assert outcome.usage["cost"] == 0.0002 and outcome.usage["prompt_tokens"] == 20
    assert outcome.suggested_actions[:2] == [
        {"type": "open_station", "station_id": "s2", "label": "Ver Moema Garage"},
        {"type": "reserve", "station_id": "s2", "connector_id": "p3", "label": "Reservar P3"}]
    tool_message = script.seen[1]["messages"][-1]
    assert tool_message["role"] == "tool" and "Moema Garage" in tool_message["content"]
    assert script.seen[0]["messages"][0]["role"] == "system"
    assert [t["function"]["name"] for t in script.seen[0]["tools"]] == toolbox.names()
    assert "get_owner_indicators" not in toolbox.names()


def test_loop_rejects_unknown_tool_and_owner_tool_for_driver():
    toolbox = Toolbox(Source(), now=NOW, owner=False)
    script = Script(response(calls=[("get_owner_indicators", {}), ("delete_everything", {})]), response("Não posso."))
    outcome = run(run_chat(script, toolbox, [{"role": "user", "content": "me mostra os postos de outra pessoa"}], system="s"))
    contents = [m["content"] for m in script.seen[1]["messages"] if m["role"] == "tool"]
    assert all("não permitida" in c for c in contents)
    assert outcome.suggested_actions == []


def test_loop_invalid_arguments_are_returned_to_model():
    toolbox = Toolbox(Source(), now=NOW)
    script = Script(response(calls=[("estimate_charge", {"power_kw": "muito"})]), response("Preciso da potência."))
    run(run_chat(script, toolbox, [{"role": "user", "content": "estimar"}], system="s"))
    assert "esperado número" in script.seen[1]["messages"][-1]["content"]


def test_loop_limits_rounds_and_forces_final_answer():
    toolbox = Toolbox(Source(), now=NOW)
    looping = response(calls=[("get_my_reservation", {})])
    script = Script(looping, looping, looping, response("Sem reserva ativa."))
    outcome = run(run_chat(script, toolbox, [{"role": "user", "content": "reserva?"}], system="s", max_rounds=4))
    assert outcome.rounds == 4 and outcome.reply == "Sem reserva ativa."
    assert [s["tool_choice"] for s in script.seen] == ["auto", "auto", "auto", "none"]
    stubborn = Script(looping, looping, looping, looping)
    outcome = run(run_chat(stubborn, Toolbox(Source(), now=NOW), [{"role": "user", "content": "x"}], system="s"))
    assert "Não consegui" in outcome.reply


def test_loop_retries_bad_response_once_and_propagates_outage():
    toolbox = Toolbox(Source(), now=NOW)
    bad = LLMUnavailable("malformed", code="ai_bad_response")
    outcome = run(run_chat(Script(bad, response("Oi!")), toolbox, [{"role": "user", "content": "oi"}], system="s"))
    assert outcome.reply == "Oi!"
    with pytest.raises(LLMUnavailable):
        run(run_chat(Script(bad, bad), toolbox, [{"role": "user", "content": "oi"}], system="s"))
    with pytest.raises(LLMUnavailable):
        run(run_chat(Script(LLMUnavailable("down")), toolbox, [{"role": "user", "content": "oi"}], system="s"))


def test_loop_respects_time_budget():
    ticks = iter([0.0, 0.0, 30.0, 30.0, 30.0])
    toolbox = Toolbox(Source(), now=NOW)
    script = Script(response(calls=[("get_my_reservation", {})]), response("never"))
    outcome = run(run_chat(script, toolbox, [{"role": "user", "content": "x"}], system="s",
                           budget_seconds=20, clock=lambda: next(ticks)))
    assert outcome.rounds == 1 and "Não consegui" in outcome.reply
    with pytest.raises(LLMUnavailable):
        run(run_chat(Script(), toolbox, [{"role": "user", "content": "x"}], system="s", budget_seconds=1))


def test_owner_tool_and_estimate_with_remembered_point():
    toolbox = Toolbox(Source(), now=NOW, owner=True)
    script = Script(
        response(calls=[("get_station_details", {"station_id": "s1"}), ("get_owner_indicators", {"days": 30})]),
        response(calls=[("estimate_charge", {"connector_id": "p1", "battery_kwh": 60, "from_percent": 20, "to_percent": 80})]),
        response("Custa R$ 89,64."),
    )
    outcome = run(run_chat(script, toolbox, [{"role": "user", "content": "quanto custa"}], system="s"))
    estimate = next(data for name, _, data in toolbox.records if name == "estimate_charge")
    assert estimate["cost_brl"] == 89.64 and estimate["station_name"] == "Paulista Hub"
    indicators = next(data for name, _, data in toolbox.records if name == "get_owner_indicators")
    assert indicators["points"] == 3 and indicators["base_recommendations"]
    types = [a["type"] for a in outcome.suggested_actions]
    assert types[:2] == ["open_station", "reserve"] and "open_operator" in types


def test_history_and_reservation_tools():
    toolbox = Toolbox(Source(), now=NOW)
    data = run(toolbox.execute("get_my_charging_history", "{}"))
    assert data["month_estimated_cost_brl"] == 20.5 and data["month_energy_kwh"] == 10
    assert run(toolbox.execute("get_my_reservation", None)) == {"reservation": None}
    assert run(toolbox.execute("search_stations", "não é json"))["error"]


def test_driver_slot_absent_is_silent(monkeypatch):
    monkeypatch.setattr(driver_slot, "planner", lambda: None)
    assert "plan_driver_shift" not in Toolbox(Source(), now=NOW).names()


def test_driver_slot_registers_when_planner_exists(monkeypatch):
    received = {}

    def plan(request, stations, now, saved):
        received.update(request=request, stations=len(stations), now=now, saved=saved)
        return {"summary": "Recarregue às 14h"}

    monkeypatch.setattr(driver_slot, "planner", lambda: plan)
    toolbox = Toolbox(Source(), now=NOW)
    assert "plan_driver_shift" in toolbox.names()
    assert run(toolbox.execute("plan_driver_shift", {"shift_start": "07:00", "current_soc_percent": 50})) == {
        "summary": "Recarregue às 14h"}
    assert received == {"request": {"shift_start": "07:00", "current_soc_percent": 50}, "stations": 3, "now": NOW,
                        "saved": None}


class DriverSource(Source):
    def driver_profile(self):
        return {"vehicle": {"preset": "byd_dolphin"}, "preferences": {"shift_start": "08:00", "shift_end": "20:00"}}


def test_plan_driver_shift_uses_real_driver_planner_and_saved_profile():
    toolbox = Toolbox(DriverSource(), now=datetime(2026, 10, 13, 10, 0, tzinfo=timezone.utc))
    assert "plan_driver_shift" in toolbox.names()
    data = run(toolbox.execute("plan_driver_shift", {"current_soc_percent": 25, "vehicle": "Dolphin Mini",
                                                     "dinner_time": "19:30", "near_place": "Paulista",
                                                     "full_shift": True}))
    assert "error" not in data, data
    assert data["window"].startswith("08:00–20:00") and data["vehicle"] == "BYD Dolphin Mini"
    assert data["stops"] and data["stops"][0]["station_id"] in {"s1", "s2"}
    assert data["totals"]["net_profit"] is not None and data["versus_naive"]
    assert data["notes"][-1].startswith("Demanda e ganhos são estimativas")
    missing = run(toolbox.execute("plan_driver_shift", {"vehicle": "Fusca"}))
    assert any("50%" in note for note in missing["notes"]) and any("não reconhecido" in n for n in missing["notes"])
    from chargegrid_core.ai.actions import derive_actions
    actions = derive_actions(toolbox.records[:1], "plano")
    assert [a["type"] for a in actions] == ["open_driver", "open_station"]



def test_indicators_from_dashboard_analytics_feed_rules_and_writer():
    from chargegrid_core import analytics
    from chargegrid_core.ai import indicators_from_dashboard, owner_insights_from_indicators

    start, end = NOW - timedelta(days=7), NOW
    sessions = [{"connector_id": "p1", "status": "interrupted" if i == 0 else "completed", "energy_wh": "10000",
                 "cost_estimate": "20", "started_at": (NOW - timedelta(days=i, hours=1)).isoformat(),
                 "ended_at": (NOW - timedelta(days=i, minutes=5)).isoformat(), "created_at": (NOW - timedelta(days=i, hours=1)).isoformat()}
                for i in range(5)]
    totals = analytics.summarize_sessions(sessions, start, end, NOW)
    totals.update(reservations=10, no_shows=3)
    overview = {"period": {"from": start.isoformat(), "to": end.isoformat()}, "station_id": None,
                "kpis": analytics.build_kpis(totals, points=2, points_online=1, start=start, end=end),
                "stations": {"total": 1}, "ranking": []}
    heat = analytics.heatmap_payload(analytics.heatmap_cells(sessions, start, end))
    heat["peak_hours"] = analytics.peak_hours(heat)
    alerts = [{"kind": "device_offline", "title": "Dispositivo offline", "detail": "P2: sem comunicação."}]
    ind = indicators_from_dashboard(overview, heat, alerts)
    assert ind["sessions"] == 5 and ind["revenue_brl"] == 100 and ind["energy_kwh"] == 50
    assert ind["offline_points"] == 1 and ind["no_show_percent"] == 30 and ind["period_days"] == 7
    assert sum(ind["sessions_by_hour"].values()) == 5 and ind["peak_hours"]
    result, meta = run(owner_insights_from_indicators(ind, now=NOW))
    titles = [r["title"] for r in result["recommendations"]]
    assert "Recupere os pontos sem comunicação" in titles and "Reduza reservas não utilizadas" in titles
    assert result["summary"].startswith("De 06/10 a 13/10") and meta["status"] == "rules"
    assert all(r["impact"] in ("high", "medium", "low") for r in result["recommendations"])
    writer = Script(response('{"summary": "ok", "recommendations": [{"title": "T", "detail": "D", '
                             '"impact": "alto", "kind": "maintenance"}]}'))
    result, meta = run(owner_insights_from_indicators(ind, now=NOW, llm=writer))
    assert result["recommendations"] == [{"title": "T", "detail": "D", "impact": "high", "kind": "operations"}]
    assert "Dispositivo" in writer.seen[0]["messages"][1]["content"] or "P2" in writer.seen[0]["messages"][1]["content"]


# --- revisão de integração (2026-10): regressões ------------------------------------

@pytest.mark.parametrize("payload", [
    {"choices": [{"message": "texto solto"}]},
    {"choices": [{"message": {"content": "oi", "tool_calls": {"function": {"name": "x"}}}}]},
    {"choices": [{"message": {"content": "oi", "tool_calls": ["lixo", None, {"function": "x"}]}}]},
    {"choices": [{"message": {"content": "oi"}}], "usage": "muitos"},
    {"choices": [{"message": {"content": "oi"}}], "usage": {"prompt_tokens": "abc", "completion_tokens": None,
                                                           "cost": "NaN"}},
    {"choices": "nenhuma"},
    {"choices": [{"message": {"content": None, "tool_calls": [
        {"id": 7, "function": {"name": "search_stations", "arguments": {"near_place": {1, 2}}}}]}}]},
])
def test_parse_completion_never_crashes_on_malformed_provider_payloads(payload):
    try:
        parsed = parse_completion(payload)
    except LLMUnavailable:
        return
    assert isinstance(parsed["content"], str)
    assert all(isinstance(call["arguments"], str) and isinstance(call["id"], str) for call in parsed["tool_calls"])
    assert parsed["usage"]["prompt_tokens"] >= 0 and parsed["usage"]["cost"] == parsed["usage"]["cost"]  # não é NaN


def test_loop_does_not_retry_bad_response_without_time_left():
    ticks = iter([0.0, 0.0, 21.0, 21.0])
    bad = LLMUnavailable("malformed", code="ai_bad_response")
    script = Script(bad, response("tarde demais"))
    with pytest.raises(LLMUnavailable):
        run(run_chat(script, Toolbox(Source(), now=NOW), [{"role": "user", "content": "oi"}], system="s",
                     budget_seconds=22, clock=lambda: next(ticks)))
    assert len(script.seen) == 1


def test_loop_timeout_after_tools_degrades_to_actions_instead_of_error():
    toolbox = Toolbox(Source(), now=NOW)
    timeout = LLMUnavailable("lento", status=504, code="ai_timeout")
    script = Script(response(calls=[("search_stations", {"text": "Paulista"})]), timeout)
    outcome = run(run_chat(script, toolbox, [{"role": "user", "content": "postos na paulista"}], system="s"))
    assert "demorou" in outcome.reply and outcome.rounds == 1
    assert outcome.tools_used == ["search_stations"]
    assert outcome.suggested_actions[0] == {"type": "open_station", "station_id": "s1", "label": "Ver Paulista Hub"}
    with pytest.raises(LLMUnavailable):  # sem nenhum dado consultado, o erro continua honesto
        run(run_chat(Script(timeout), Toolbox(Source(), now=NOW), [{"role": "user", "content": "oi"}], system="s"))
