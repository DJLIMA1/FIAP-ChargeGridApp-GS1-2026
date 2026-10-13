"""Cliente OpenRouter (httpx) usado pelo assistente. A chave nunca sai do backend."""

import httpx

from chargegrid_core.ai import LLMUnavailable, build_payload, parse_completion

from ...config import settings

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_TIMEOUT_SECONDS = 22.0  # a função da Vercel tem 30 s no total
_DEFAULT = object()


def configured_models(config=None) -> list[str]:
    config = config or settings()
    models = [config.openrouter_model.strip()]
    models += [m.strip() for m in config.openrouter_fallback_models.split(",") if m.strip()]
    unique = []
    for model in models:
        if model and model not in unique:
            unique.append(model)
    return unique[:3]


class OpenRouterClient:
    """Implementa ``complete(messages, tools, timeout, tool_choice)`` do laço do core."""

    def __init__(self, api_key: str, models: list[str], *, reasoning_effort: str | None = "low",
                 site_url: str = "", transport: httpx.AsyncBaseTransport | None = None):
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY ausente")
        self._api_key = api_key
        self.models = models
        self.reasoning_effort = reasoning_effort or None
        self.site_url = site_url
        self._transport = transport

    def __repr__(self):  # nunca expor a chave em logs/tracebacks
        return f"OpenRouterClient(models={self.models!r})"

    async def __call__(self, messages, tools, timeout: float = MAX_TIMEOUT_SECONDS, tool_choice="auto",
                       max_tokens: int = 900, reasoning_effort=_DEFAULT):
        effort = self.reasoning_effort if reasoning_effort is _DEFAULT else reasoning_effort
        payload = build_payload(messages, tools, models=self.models, tool_choice=tool_choice,
                                reasoning_effort=effort, max_tokens=max_tokens)
        headers = {"Authorization": f"Bearer {self._api_key}", "X-Title": "ChargeGrid"}
        if self.site_url:
            headers["HTTP-Referer"] = self.site_url
        limit = max(1.0, min(float(timeout), MAX_TIMEOUT_SECONDS))
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=httpx.Timeout(limit, connect=5.0)) as client:
                response = await client.post(OPENROUTER_URL, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise LLMUnavailable("O assistente demorou demais para responder.", status=504, code="ai_timeout") from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailable() from exc
        if response.status_code == 429:
            raise LLMUnavailable("Assistente sobrecarregado no momento. Tente em instantes.", code="ai_busy")
        if response.status_code == 402:
            raise LLMUnavailable("Limite de uso do assistente atingido.", code="ai_quota")
        if response.status_code >= 400:
            raise LLMUnavailable()
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMUnavailable("Resposta inválida do provedor de IA.") from exc
        return parse_completion(data)


def get_llm():
    """Dependência FastAPI: cliente configurado ou None (IA desligada/sem chave)."""
    config = settings()
    if not config.ai_enabled or not config.openrouter_api_key:
        return None
    return OpenRouterClient(config.openrouter_api_key, configured_models(config),
                            reasoning_effort=config.openrouter_reasoning_effort, site_url=config.openrouter_site_url)
