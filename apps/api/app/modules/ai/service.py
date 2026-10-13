"""Limites de uso e registro de consumo do assistente (somente metadados)."""

from decimal import Decimal

from fastapi import HTTPException

from ...errors import fail
from ...models import AiUsage
from ..auth.routes import limit

# Por usuário: 20 pedidos a cada 10 minutos e 200 por dia (todas as funções de IA).
# Global: 5.000 por dia protege a cota/crédito compartilhado da chave.
USER_WINDOW = (20, 600)
USER_DAILY = (200, 86400)
GLOBAL_DAILY = (5000, 86400)


def enforce_limits(db, user):
    try:
        limit(db, f"ai:user:{user.id}", maximum=USER_WINDOW[0], seconds=USER_WINDOW[1])
        limit(db, f"ai:user-day:{user.id}", maximum=USER_DAILY[0], seconds=USER_DAILY[1])
        limit(db, "ai:global-day", maximum=GLOBAL_DAILY[0], seconds=GLOBAL_DAILY[1])
    except HTTPException as exc:
        if exc.status_code == 429:
            fail("ai_rate_limited", "Você atingiu o limite de perguntas ao assistente. Tente novamente mais tarde.", 429)
        raise


def record_usage(db, user, feature, status, *, model="", usage=None, latency_ms=0, tools=(), commit=False):
    usage = usage or {}
    db.add(AiUsage(
        user_id=user.id, feature=feature, status=status, model=(model or "")[:100],
        prompt_tokens=int(usage.get("prompt_tokens") or 0), completion_tokens=int(usage.get("completion_tokens") or 0),
        cost_usd=Decimal(str(round(float(usage.get("cost") or 0), 6))), latency_ms=int(latency_ms),
        tools=",".join(tools)[:200],
    ))
    if commit:
        # Erros encerram a requisição com rollback; o registro de uso precisa sobreviver.
        db.commit()
