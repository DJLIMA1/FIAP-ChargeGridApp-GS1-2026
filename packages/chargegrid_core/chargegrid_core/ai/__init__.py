"""Núcleo do assistente de IA do ChargeGrid (somente biblioteca padrão, sem rede).

API e prévia demo injetam o transporte (``complete``) e a fonte de dados; o
prompt, as ferramentas, a validação e o laço são os mesmos nos dois lados.
"""

from .completion import LLMUnavailable, build_payload, extract_json, parse_completion
from .insights import (
    owner_indicators,
    owner_recommendations,
    owner_summary,
    session_facts,
    session_summary,
    session_tips,
)
from .loop import ChatOutcome, run_chat, sanitize_history
from .prompt import system_prompt
from .search import filters_from_tool, parse_search_rules, screen_params, search_request
from .tools import Toolbox

__all__ = [
    "ChatOutcome", "LLMUnavailable", "Toolbox", "build_payload", "extract_json", "filters_from_tool",
    "owner_indicators", "owner_recommendations", "owner_summary", "parse_completion", "parse_search_rules",
    "run_chat", "sanitize_history", "screen_params", "search_request", "session_facts", "session_summary",
    "session_tips", "system_prompt",
]
