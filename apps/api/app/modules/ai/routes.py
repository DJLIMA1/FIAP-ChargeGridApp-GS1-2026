"""Endpoints de IA: chat com ferramentas somente leitura, busca em linguagem natural,
resumo de recarga e insights para donos de posto.

A orquestração (prompt, ferramentas, laço, alternativas por regras) vem de
``chargegrid_core.ai`` e é a mesma da prévia demo; aqui ficam autenticação,
limites, acesso ao banco e registro de uso.
"""

import time
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends

from chargegrid_core.ai import (
    LLMUnavailable,
    Toolbox,
    indicators_from_dashboard,
    natural_search,
    owner_insights_from_indicators,
    run_chat,
    session_insight,
    system_prompt,
)

from ...database import db_session
from ...errors import fail
from ...http_helpers import session_row
from ...models import ChargingSession
from ...security import current_user
from ..owner import routes as owner_routes
from ..owner import service as owner_service
from .client import get_llm
from .schemas import ChatInput, OwnerInsightsInput, SearchInput, SessionInsightInput
from .service import enforce_limits, record_usage
from .source import DbSource

router = APIRouter(prefix="/ai")


def _now():
    return datetime.now(UTC)


def _elapsed_ms(started):
    return (time.monotonic() - started) * 1000


def _released(db, llm):
    """Encerra a transação de leitura antes de cada chamada ao provedor.

    Sem isso a conexão ficaria "idle in transaction" durante até ~22 s de espera
    pelo modelo (prendendo uma conexão do pooler do Supabase por requisição)."""
    if llm is None:
        return None

    async def complete(*args, **kwargs):
        db.commit()
        return await llm(*args, **kwargs)

    return complete


@router.post("/chat")
async def chat(data: ChatInput, user=Depends(current_user), db=Depends(db_session), llm=Depends(get_llm)):
    """Resposta do assistente: {reply, suggested_actions, tools_used, model}."""
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
        outcome = await run_chat(_released(db, llm), toolbox, [m.model_dump() for m in data.messages], system=system)
    except LLMUnavailable as error:
        record_usage(db, user, "chat", "error", latency_ms=_elapsed_ms(started), commit=True)
        fail(error.code, str(error) or "Assistente de IA indisponível no momento.", 504 if error.code == "ai_timeout" else 503)
    record_usage(db, user, "chat", "ok", model=outcome.model, usage=outcome.usage, latency_ms=outcome.latency_ms,
                 tools=outcome.tools_used)
    return {"reply": outcome.reply, "suggested_actions": outcome.suggested_actions,
            "tools_used": outcome.tools_used, "model": outcome.model}


@router.post("/search")
async def search(data: SearchInput, user=Depends(current_user), db=Depends(db_session), llm=Depends(get_llm)):
    """Busca em linguagem natural -> {filters, unsupported, explanation, params, model}."""
    enforce_limits(db, user)
    origin = {"lat": data.lat, "lng": data.lng} if data.lat is not None and data.lng is not None else None
    started = time.monotonic()
    result, meta = await natural_search(data.query, origin=origin, llm=_released(db, llm))
    record_usage(db, user, "search", meta["status"], model=meta["model"], usage=meta["usage"],
                 latency_ms=_elapsed_ms(started))
    return result


@router.post("/session-insight")
async def insight(data: SessionInsightInput, user=Depends(current_user), db=Depends(db_session), llm=Depends(get_llm)):
    """Resumo de uma recarga do próprio usuário: custo vs média e dicas de economia."""
    obj = db.get(ChargingSession, data.session_id)
    if not obj or obj.user_id != user.id:
        fail("not_found", "Sessão não encontrada", 404)
    enforce_limits(db, user)
    started = time.monotonic()
    result, meta = await session_insight(session_row(db, obj), DbSource(db, user).recent_sessions(30), now=_now(),
                                         llm=_released(db, llm))
    record_usage(db, user, "session_insight", meta["status"], model=meta["model"], usage=meta["usage"],
                 latency_ms=_elapsed_ms(started))
    return result


@router.post("/owner-insights")
async def insights_for_owner(data: OwnerInsightsInput | None = None, user=Depends(current_user),
                             db=Depends(db_session), llm=Depends(get_llm)):
    """Contrato estável (dashboard web):
    {summary, recommendations: [{title, detail, impact, kind}], generated_at, model}.

    Indicadores calculados por ``chargegrid_core.analytics`` (os mesmos de ``/owner/*``)."""
    data = data or OwnerInsightsInput()
    scope = owner_routes.scope_for(db, user, data.station_id)
    enforce_limits(db, user)
    end = data.end or _now()
    window = owner_routes.window_for(data.start or end - timedelta(days=data.days), end)
    indicators = indicators_from_dashboard(owner_service.overview(db, scope, window),
                                           owner_service.heatmap(db, scope, window),
                                           owner_service.alerts(db, scope)["items"])
    started = time.monotonic()
    result, meta = await owner_insights_from_indicators(indicators, now=_now(), llm=_released(db, llm))
    record_usage(db, user, "owner_insights", meta["status"], model=meta["model"], usage=meta["usage"],
                 latency_ms=_elapsed_ms(started))
    return result
