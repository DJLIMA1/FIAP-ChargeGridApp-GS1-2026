"""Funcionalidades de IA além do chat, com alternativa por regras.

Cada função recebe ``llm`` (a mesma ``complete`` do laço, ou ``None``) e devolve
``(resultado, meta)``; ``meta`` = {'model','usage','status'} para registro de uso.
Status: ``ok`` (IA), ``rules`` (sem IA configurada) ou ``fallback`` (IA falhou e
as regras responderam). Nunca há troca silenciosa para outro modelo.
"""

from __future__ import annotations

from datetime import datetime

from .completion import LLMUnavailable
from .insights import (
    owner_indicators,
    owner_recommendations,
    owner_summary,
    session_facts,
    session_summary,
    session_tips,
)
from .schema import ToolArgumentError, parse_arguments
from .search import filters_from_tool, parse_search_rules, screen_params, search_request
from .writer import (
    owner_insights_messages,
    parse_owner_insights,
    parse_session_insight,
    session_insight_messages,
)

RULES_MODEL = "chargegrid-regras"
# Tarefas de extração/redação não precisam de raciocínio: sem ele, a resposta sai em ~1 s e
# não esgota ``max_tokens`` (DeepSeek V4.1 Flash raciocina mesmo com effort "low").
WRITER_TIMEOUT = 12.0


def _meta(model=RULES_MODEL, usage=None, status="rules"):
    return {"model": model, "usage": usage or {}, "status": status}


async def natural_search(query: str, *, origin: dict | None = None, llm=None) -> tuple[dict, dict]:
    """Texto livre -> {filters, unsupported, explanation, params, model}."""
    result, meta = None, _meta()
    if llm is not None:
        messages, tools, choice = search_request(query)
        try:
            response = await llm(messages, tools, timeout=WRITER_TIMEOUT, tool_choice=choice, max_tokens=400,
                                 reasoning_effort="none")
            meta = _meta(usage=response.get("usage"), status="fallback")
            call = next((c for c in response.get("tool_calls") or [] if c["name"] == "apply_station_filters"), None)
            if call:
                result = filters_from_tool(parse_arguments(call["arguments"]), origin=origin)
                meta.update(model=response.get("model") or RULES_MODEL, status="ok")
        except (LLMUnavailable, ToolArgumentError):
            meta["status"] = "fallback"
    if result is None:
        result = parse_search_rules(query, origin=origin)
    return {**result, "params": screen_params(result["filters"]), "model": meta["model"]}, meta


async def session_insight(session: dict, history: list[dict], *, now: datetime, llm=None) -> tuple[dict, dict]:
    """Resumo da recarga: {session_id, summary, tips, comparison, generated_at, model}."""
    facts = session_facts(session, history)
    tips = session_tips(facts)
    result, meta = {"summary": session_summary(facts), "tips": tips}, _meta()
    if llm is not None:
        try:
            response = await llm(session_insight_messages(facts, tips), None, timeout=WRITER_TIMEOUT, max_tokens=500,
                                 reasoning_effort="none")
            written = parse_session_insight(response.get("content") or "")
            meta = _meta(usage=response.get("usage"), status="fallback")
            if written:
                result = written
                meta.update(model=response.get("model") or RULES_MODEL, status="ok")
        except LLMUnavailable:
            meta["status"] = "fallback"
    comparison = {key: facts[key] for key in ("cost_brl", "energy_kwh", "price_per_kwh", "avg_cost_brl", "avg_price_per_kwh",
                                              "cost_vs_avg_percent", "peak_hour", "history_sessions")}
    return {"session_id": str(session.get("id")), **result, "comparison": comparison,
            "generated_at": now.isoformat(timespec="seconds"), "model": meta["model"]}, meta


async def owner_insights(stations: list[dict], sessions: list[dict], *, now: datetime, days: int = 30,
                         llm=None) -> tuple[dict, dict]:
    """Variante a partir de registros REST (postos + sessões)."""
    indicators = owner_indicators(stations, [s for s in sessions if s], now=now, days=days)
    return await owner_insights_from_indicators(indicators, now=now, llm=llm)


async def owner_insights_from_indicators(indicators: dict, *, now: datetime, llm=None) -> tuple[dict, dict]:
    """Contrato estável: {summary, recommendations:[{title, detail, impact, kind}], generated_at, model}.

    ``indicators`` vem de ``owner_indicators`` ou de ``indicators_from_dashboard`` (analytics)."""
    base = owner_recommendations(indicators)
    result, meta = {"summary": owner_summary(indicators), "recommendations": base}, _meta()
    if llm is not None and indicators["points"]:
        try:
            response = await llm(owner_insights_messages(indicators, base), None, timeout=WRITER_TIMEOUT, max_tokens=900,
                                 reasoning_effort="none")
            written = parse_owner_insights(response.get("content") or "")
            meta = _meta(usage=response.get("usage"), status="fallback")
            if written:
                result = written
                meta.update(model=response.get("model") or RULES_MODEL, status="ok")
        except LLMUnavailable:
            meta["status"] = "fallback"
    return {"summary": result["summary"], "recommendations": result["recommendations"],
            "generated_at": now.isoformat(timespec="seconds"), "model": meta["model"]}, meta
