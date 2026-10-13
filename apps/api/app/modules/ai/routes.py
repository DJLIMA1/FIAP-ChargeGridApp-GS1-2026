"""Endpoints de IA: chat com ferramentas somente leitura, busca em linguagem natural,
resumo de recarga e insights para donos de posto."""

import time
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends

from chargegrid_core.ai import (
    LLMUnavailable,
    Toolbox,
    filters_from_tool,
    owner_indicators,
    owner_recommendations,
    owner_summary,
    parse_search_rules,
    run_chat,
    screen_params,
    search_request,
    session_facts,
    session_summary,
    session_tips,
    system_prompt,
)
from chargegrid_core.ai.schema import ToolArgumentError, parse_arguments
from chargegrid_core.ai.writer import (
    owner_insights_messages,
    parse_owner_insights,
    parse_session_insight,
    session_insight_messages,
)

from ...database import db_session
from ...errors import fail
from ...http_helpers import session_row
from ...models import ChargingSession
from ...security import current_user
from ...service import operator
from .client import get_llm
from .schemas import ChatInput, OwnerInsightsInput, SearchInput, SessionInsightInput
from .service import RULES_MODEL, enforce_limits, record_usage
from .source import DbSource

router = APIRouter(prefix="/ai")
WRITER_TIMEOUT = 12.0


def _now():
    return datetime.now(UTC)


def _unavailable(db, user, feature, error: LLMUnavailable, started):
    record_usage(db, user, feature, "error", latency_ms=(time.monotonic() - started) * 1000, commit=True)
    status = 504 if error.code == "ai_timeout" else 503
    fail(error.code, str(error) or "Assistente de IA indisponível no momento.", status)


@router.post("/chat")
async def chat(data: ChatInput, user=Depends(current_user), db=Depends(db_session), llm=Depends(get_llm)):
    if data.messages[-1].role != "user":
        fail("validation_error", "A última mensagem deve ser do usuário", 422)
    enforce_limits(db, user)
    if llm is None:
        fail("ai_unavailable", "Assistente de IA indisponível no momento. Use as orientações do app.", 503)
    owner = bool(user.operator_enabled)
    origin = ({"lat": data.context.lat, "lng": data.context.lng}
              if data.context.lat is not None and data.context.lng is not None else None)
    now = _now()
    toolbox = Toolbox(DbSource(db, user), owner=owner, now=now, origin=origin)
    system = system_prompt(role="owner" if owner and data.context.mode == "owner" else "driver", now=now,
                           user_name=(user.name or "").split(" ")[0] or None,
                           location_label="localização atual do aparelho" if origin else None)
    started = time.monotonic()
    try:
        outcome = await run_chat(llm, toolbox, [m.model_dump() for m in data.messages], system=system)
    except LLMUnavailable as error:
        _unavailable(db, user, "chat", error, started)
    record_usage(db, user, "chat", "ok", model=outcome.model, usage=outcome.usage, latency_ms=outcome.latency_ms,
                 tools=outcome.tools_used)
    return {"reply": outcome.reply, "suggested_actions": outcome.suggested_actions,
            "tools_used": outcome.tools_used, "model": outcome.model}


@router.post("/search")
async def search(data: SearchInput, user=Depends(current_user), db=Depends(db_session), llm=Depends(get_llm)):
    enforce_limits(db, user)
    origin = {"lat": data.lat, "lng": data.lng} if data.lat is not None and data.lng is not None else None
    result, model, usage, status = None, RULES_MODEL, None, "rules"
    started = time.monotonic()
    if llm is not None:
        messages, tools, choice = search_request(data.query)
        try:
            response = await llm(messages, tools, timeout=WRITER_TIMEOUT, tool_choice=choice, max_tokens=400)
            usage = response["usage"]
            call = next((c for c in response["tool_calls"] if c["name"] == "apply_station_filters"), None)
            if call:
                result = filters_from_tool(parse_arguments(call["arguments"]), origin=origin)
                model, status = response["model"], "ok"
        except (LLMUnavailable, ToolArgumentError):
            status = "fallback"
    if result is None:
        result = parse_search_rules(data.query, origin=origin)
    record_usage(db, user, "search", status, model=model, usage=usage, latency_ms=(time.monotonic() - started) * 1000)
    return {**result, "params": screen_params(result["filters"]), "model": model}


@router.post("/session-insight")
async def session_insight(data: SessionInsightInput, user=Depends(current_user), db=Depends(db_session),
                          llm=Depends(get_llm)):
    obj = db.get(ChargingSession, data.session_id)
    if not obj or obj.user_id != user.id:
        fail("not_found", "Sessão não encontrada", 404)
    enforce_limits(db, user)
    facts = session_facts(session_row(db, obj), DbSource(db, user).recent_sessions(30))
    tips = session_tips(facts)
    result = {"summary": session_summary(facts), "tips": tips}
    model, usage, status = RULES_MODEL, None, "rules"
    started = time.monotonic()
    if llm is not None:
        try:
            response = await llm(session_insight_messages(facts, tips), None, timeout=WRITER_TIMEOUT, max_tokens=500)
            usage = response["usage"]
            written = parse_session_insight(response["content"])
            if written:
                result, model, status = written, response["model"], "ok"
            else:
                status = "fallback"
        except LLMUnavailable:
            status = "fallback"
    record_usage(db, user, "session_insight", status, model=model, usage=usage,
                 latency_ms=(time.monotonic() - started) * 1000)
    comparison = {key: facts[key] for key in ("cost_brl", "energy_kwh", "price_per_kwh", "avg_cost_brl",
                                              "avg_price_per_kwh", "cost_vs_avg_percent", "peak_hour", "history_sessions")}
    return {"session_id": str(obj.id), **result, "comparison": comparison,
            "generated_at": _now().isoformat(timespec="seconds"), "model": model}


@router.post("/owner-insights")
async def owner_insights(data: OwnerInsightsInput | None = None, user=Depends(current_user), db=Depends(db_session),
                         llm=Depends(get_llm)):
    """Contrato estável (consumido pelo dashboard web):
    {summary, recommendations: [{title, detail, impact, kind}], generated_at, model}."""
    operator(user)
    enforce_limits(db, user)
    days = (data or OwnerInsightsInput()).days
    now = _now()
    source = DbSource(db, user)
    indicators = owner_indicators(source.owner_stations(), source.owner_sessions(now - timedelta(days=days)),
                                  now=now, days=days)
    base = owner_recommendations(indicators)
    result = {"summary": owner_summary(indicators), "recommendations": base}
    model, usage, status = RULES_MODEL, None, "rules"
    started = time.monotonic()
    if llm is not None and indicators["points"]:
        try:
            response = await llm(owner_insights_messages(indicators, base), None, timeout=WRITER_TIMEOUT, max_tokens=900)
            usage = response["usage"]
            written = parse_owner_insights(response["content"])
            if written:
                result, model, status = written, response["model"], "ok"
            else:
                status = "fallback"
        except LLMUnavailable:
            status = "fallback"
    record_usage(db, user, "owner_insights", status, model=model, usage=usage,
                 latency_ms=(time.monotonic() - started) * 1000)
    return {"summary": result["summary"], "recommendations": result["recommendations"],
            "generated_at": now.isoformat(timespec="seconds"), "model": model}
