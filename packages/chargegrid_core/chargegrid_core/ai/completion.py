"""Formato de requisição/resposta compatível com OpenAI/OpenRouter (sem rede).

O transporte (httpx na API ou na prévia demo) chama ``build_payload``, envia
para o provedor e devolve ``parse_completion(json)`` ao laço do assistente.
"""

from __future__ import annotations

import json
import uuid


class LLMUnavailable(RuntimeError):
    """Provedor indisponível, sem crédito/limite ou resposta inválida."""

    def __init__(self, message: str = "Assistente de IA indisponível no momento.", *, status: int = 503,
                 code: str = "ai_unavailable"):
        super().__init__(message)
        self.status, self.code = status, code


def build_payload(messages: list[dict], tools: list[dict] | None, *, models: list[str], max_tokens: int = 900,
                  temperature: float = 0.2, tool_choice: object = None, reasoning_effort: str | None = "low") -> dict:
    if not models:
        raise LLMUnavailable("Nenhum modelo configurado.")
    payload = {"model": models[0], "messages": messages, "max_tokens": max_tokens, "temperature": temperature,
               "usage": {"include": True}}
    if len(models) > 1:
        payload["models"] = list(models[:3])
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice or "auto"
        payload["parallel_tool_calls"] = True
    if reasoning_effort:
        payload["reasoning"] = {"effort": reasoning_effort, "exclude": True}
    return payload


def parse_completion(data: dict) -> dict:
    """Normaliza a resposta: {'content','tool_calls','model','usage','reasoning_details'}."""
    if not isinstance(data, dict):
        raise LLMUnavailable("Resposta inválida do provedor de IA.")
    if data.get("error"):
        raise LLMUnavailable("O provedor de IA recusou o pedido.")
    choices = data.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        raise LLMUnavailable("Resposta vazia do provedor de IA.")
    if choices[0].get("finish_reason") == "error":
        # Ex.: MALFORMED_FUNCTION_CALL do Gemini; o laço tenta a rodada novamente uma vez.
        raise LLMUnavailable("O modelo devolveu uma resposta malformada.", status=502, code="ai_bad_response")
    message = choices[0].get("message") or {}
    calls = []
    for call in message.get("tool_calls") or []:
        function = (call or {}).get("function") or {}
        if not function.get("name"):
            continue
        arguments = function.get("arguments")
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments or {}, ensure_ascii=False)
        # Alguns provedores prefixam o nome (ex.: "default_api.search_stations").
        name = str(function["name"]).rsplit(".", 1)[-1][:64]
        calls.append({"id": call.get("id") or "call_" + uuid.uuid4().hex[:12], "name": name,
                      "arguments": arguments[:4000]})
    usage = data.get("usage") or {}
    return {
        "content": message.get("content") if isinstance(message.get("content"), str) else "",
        "tool_calls": calls,
        "model": str(data.get("model") or ""),
        "usage": {"prompt_tokens": int(usage.get("prompt_tokens") or 0),
                  "completion_tokens": int(usage.get("completion_tokens") or 0),
                  "cost": float(usage.get("cost") or 0.0)},
        "reasoning_details": message.get("reasoning_details"),
        "finish_reason": choices[0].get("finish_reason"),
    }


def assistant_message(response: dict) -> dict:
    """Mensagem do assistente (com chamadas de ferramenta) para reenviar ao modelo."""
    message = {"role": "assistant", "content": response.get("content") or "",
               "tool_calls": [{"id": call["id"], "type": "function",
                               "function": {"name": call["name"], "arguments": call["arguments"]}}
                              for call in response.get("tool_calls") or []]}
    if response.get("reasoning_details"):
        message["reasoning_details"] = response["reasoning_details"]
    return message


def extract_json(text: str) -> dict | None:
    """Primeiro objeto JSON de um texto (tolerando blocos ```json)."""
    if not text:
        return None
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = escape = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        value = json.loads(text[start:index + 1])
                    except ValueError:
                        break
                    return value if isinstance(value, dict) else None
        start = text.find("{", start + 1)
    return None
