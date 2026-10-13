"""Laço de tool-calling agnóstico de transporte.

``complete(messages, tools, timeout=segundos, tool_choice="auto"|"none"|{...}, max_tokens=None,
reasoning_effort=<padrão do transporte>)``
é injetada (OpenRouter via httpx na API ou na prévia demo; fakes nos testes) e devolve o formato normalizado de
``completion.parse_completion``. O laço limita rodadas, chamadas por rodada,
tempo total e tamanho do histórico.
"""

from __future__ import annotations

import inspect
import time
from dataclasses import asdict, dataclass, field

from .actions import derive_actions
from .completion import LLMUnavailable, assistant_message
from .text import clean, plain_text, strip_identifiers

MAX_MESSAGE_CHARS = 500
MAX_HISTORY_MESSAGES = 10
MAX_HISTORY_CHARS = 4000
MAX_REPLY_CHARS = 1500
MAX_ROUNDS = 4
MAX_CALLS_PER_ROUND = 4
BUDGET_SECONDS = 22.0
MIN_ROUND_SECONDS = 2.5
FALLBACK_REPLY = "Não consegui concluir a resposta agora. Tente reformular a pergunta ou use as telas do app."


@dataclass
class ChatOutcome:
    reply: str
    suggested_actions: list = field(default_factory=list)
    tools_used: list = field(default_factory=list)
    model: str = ""
    usage: dict = field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0})
    rounds: int = 0
    latency_ms: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


def sanitize_history(history: list, *, max_messages: int = MAX_HISTORY_MESSAGES,
                     max_chars: int = MAX_HISTORY_CHARS) -> list[dict]:
    """Somente papéis user/assistant, textos curtos e as mensagens mais recentes."""
    cleaned = []
    for item in history or []:
        if not isinstance(item, dict) or item.get("role") not in ("user", "assistant"):
            continue
        content = clean(item.get("content"), MAX_MESSAGE_CHARS if item["role"] == "user" else 800)
        if content:
            cleaned.append({"role": item["role"], "content": content})
    cleaned = cleaned[-max_messages:]
    while len(cleaned) > 1 and sum(len(m["content"]) for m in cleaned) > max_chars:
        cleaned.pop(0)
    while cleaned and cleaned[0]["role"] != "user":
        cleaned.pop(0)
    return cleaned


async def _complete(complete, messages, tools, timeout, tool_choice):
    result = complete(messages, tools, timeout=timeout, tool_choice=tool_choice)
    return await result if inspect.isawaitable(result) else result


def _add_usage(total: dict, usage: dict | None):
    for key in ("prompt_tokens", "completion_tokens", "cost"):
        total[key] = total.get(key, 0) + ((usage or {}).get(key) or 0)


async def run_chat(complete, toolbox, history: list, *, system: str, max_rounds: int = MAX_ROUNDS,
                   budget_seconds: float = BUDGET_SECONDS, clock=time.monotonic) -> ChatOutcome:
    """Conversa com ferramentas; levanta ``LLMUnavailable`` se o provedor falhar."""
    started = clock()
    conversation = sanitize_history(history)
    if not conversation or conversation[-1]["role"] != "user":
        raise ValueError("a última mensagem deve ser do usuário")
    user_text = conversation[-1]["content"]
    messages = [{"role": "system", "content": system}, *conversation]
    outcome = ChatOutcome(reply="")
    used: list[str] = []
    reply = ""
    retried = False
    for round_index in range(max_rounds):
        remaining = budget_seconds - (clock() - started)
        if remaining < MIN_ROUND_SECONDS:
            break
        # Na última rodada as ferramentas continuam declaradas (alguns provedores
        # exigem isso quando há histórico de chamadas), mas o modelo deve responder.
        final_round = round_index == max_rounds - 1
        tools = toolbox.definitions()
        try:
            response = await _complete(complete, messages, tools, remaining, "none" if final_round else "auto")
        except LLMUnavailable as exc:
            if exc.code != "ai_bad_response" or retried:
                raise
            retried = True
            response = await _complete(complete, messages, tools, budget_seconds - (clock() - started),
                                       "none" if final_round else "auto")
        outcome.rounds += 1
        outcome.model = response.get("model") or outcome.model
        _add_usage(outcome.usage, response.get("usage"))
        calls = response.get("tool_calls") or []
        if calls and not final_round:
            calls = calls[:MAX_CALLS_PER_ROUND]
            messages.append(assistant_message({**response, "tool_calls": calls}))
            for call in calls:
                data = await toolbox.execute(call["name"], call["arguments"])
                if call["name"] not in used:
                    used.append(call["name"])
                messages.append({"role": "tool", "tool_call_id": call["id"], "name": call["name"],
                                 "content": toolbox.serialize(data)})
            continue
        reply = (response.get("content") or "").strip()
        break
    if not reply and outcome.rounds == 0:
        raise LLMUnavailable("O assistente demorou demais para responder.", status=504, code="ai_timeout")
    reply = plain_text(strip_identifiers(reply)) or FALLBACK_REPLY
    if len(reply) > MAX_REPLY_CHARS:
        reply = reply[: MAX_REPLY_CHARS - 1].rstrip() + "…"
    outcome.reply = reply
    outcome.tools_used = used
    outcome.suggested_actions = derive_actions(toolbox.records, reply, user_text)
    outcome.usage["cost"] = round(outcome.usage["cost"], 6)
    outcome.latency_ms = int((clock() - started) * 1000)
    return outcome
