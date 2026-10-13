"""Prévia local da IA na conta demo (somente desenvolvimento; excluído do APK).

Usa exatamente o laço, o prompt e as ferramentas de ``chargegrid_core.ai`` que a
API usa, mas sobre os dados em memória da ``DemoApi`` e chamando o OpenRouter
direto deste processo. Só é ativado com ``CHARGEGRID_ENABLE_DEMO=1`` e
``OPENROUTER_API_KEY`` no ambiente do processo (nunca em arquivos do app).
Sem chave: o chat cai nas orientações locais; busca e resumos usam regras.
"""

import os
import time
from collections import deque
from datetime import timedelta

import httpx

from chargegrid_core.ai import (
    LLMUnavailable,
    Toolbox,
    build_payload,
    natural_search,
    owner_insights,
    parse_completion,
    run_chat,
    session_insight,
    system_prompt,
)

from ..api_client import ApiError
from ..config import demo_enabled

OPENROUTER_URL = 'https://openrouter.ai/api/v1/chat/completions'
DEFAULT_MODEL = 'deepseek/deepseek-v4.1-flash'
DEFAULT_FALLBACKS = 'anthropic/claude-haiku-5.5,qwen/qwen3.7-flash'
WINDOW = (20, 600)
_recent = deque()


def _key():
    return os.environ.get('OPENROUTER_API_KEY', '').strip() if demo_enabled() else ''


def available():
    return bool(_key())


def models():
    names = [os.environ.get('OPENROUTER_MODEL') or DEFAULT_MODEL]
    names += (os.environ.get('OPENROUTER_FALLBACK_MODELS') or DEFAULT_FALLBACKS).split(',')
    unique = []
    for name in (n.strip() for n in names):
        if name and name not in unique:
            unique.append(name)
    return unique[:3]


async def complete(messages, tools, timeout=22.0, tool_choice='auto', max_tokens=900, reasoning_effort=None):
    key = _key()
    if not key:
        raise LLMUnavailable()
    payload = build_payload(messages, tools, models=models(), tool_choice=tool_choice, max_tokens=max_tokens,
                            reasoning_effort=reasoning_effort or os.environ.get('OPENROUTER_REASONING_EFFORT', 'low') or None)
    headers = {'Authorization': 'Bearer ' + key, 'X-Title': 'ChargeGrid (demo local)'}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(max(1.0, min(float(timeout), 22.0)), connect=5.0)) as client:
            response = await client.post(OPENROUTER_URL, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        raise LLMUnavailable('O assistente demorou demais para responder.', status=504, code='ai_timeout') from exc
    except httpx.HTTPError as exc:
        raise LLMUnavailable() from exc
    if response.status_code >= 400:
        raise LLMUnavailable(code='ai_busy' if response.status_code == 429 else 'ai_unavailable')
    try:
        return parse_completion(response.json())
    except ValueError as exc:
        raise LLMUnavailable() from exc


class DemoSource:
    """Fonte de dados do core sobre a DemoApi (mesmo formato REST da API real)."""

    def __init__(self, api):
        self.api = api

    def _get(self, path, params=None):
        try:
            return self.api._dispatch('GET', path, {}, dict(params or {}))
        except ApiError:
            return None

    def list_stations(self, near=None, radius_km=None):
        return (self._get('stations', {'limit': 100}) or {}).get('items', [])

    def get_station(self, station_id):
        return self._get(f'stations/{station_id}')

    def current_reservation(self):
        return self._get('reservations/current')

    def current_session(self):
        return self._get('charging-sessions/current')

    def recent_sessions(self, limit):
        return (self._get('me/charging-sessions', {'limit': limit}) or {}).get('items', [])

    def month_summary(self):
        return self._get('me/summary')

    def owner_stations(self):
        return (self._get('operator/stations', {'limit': 100}) or {}).get('items', [])

    def owner_sessions(self, since):
        return (self._get('operator/charging-sessions', {'limit': 100}) or {}).get('items', [])


def _limit():
    now = time.monotonic()
    while _recent and now - _recent[0] > WINDOW[1]:
        _recent.popleft()
    if len(_recent) >= WINDOW[0]:
        raise ApiError('Você atingiu o limite de perguntas ao assistente. Tente novamente mais tarde.', 429, 'ai_rate_limited')
    _recent.append(now)


def _messages(body):
    items = body.get('messages')
    if not isinstance(items, list) or not 1 <= len(items) <= 12:
        raise ApiError('Envie de 1 a 12 mensagens.', 422, 'validation_error')
    cleaned = []
    for item in items:
        if not isinstance(item, dict) or item.get('role') not in ('user', 'assistant') or not str(item.get('content') or '').strip():
            raise ApiError('Mensagem inválida.', 422, 'validation_error')
        cleaned.append({'role': item['role'], 'content': str(item['content'])[:2000]})
    if cleaned[-1]['role'] != 'user':
        raise ApiError('A última mensagem deve ser do usuário.', 422, 'validation_error')
    return cleaned


async def handle(api, method, path, body):
    if method != 'POST' or path not in ('ai/chat', 'ai/search', 'ai/session-insight', 'ai/owner-insights'):
        raise ApiError('Esta operação não está disponível na demonstração.', 404, 'demo_route_not_supported')
    _limit()
    llm = complete if available() else None
    now = api._now()
    source = DemoSource(api)
    if path == 'ai/chat':
        history = _messages(body)
        if llm is None:
            raise ApiError('Assistente de IA indisponível na demonstração sem chave.', 503, 'ai_unavailable')
        context = body.get('context') if isinstance(body.get('context'), dict) else {}
        owner = bool(api._profile.get('operator_enabled'))
        toolbox = Toolbox(source, owner=owner, now=now)
        system = system_prompt(role='owner' if owner and context.get('mode') == 'owner' else 'driver', demo=True,
                               now=now, user_name='Demo')
        try:
            outcome = await run_chat(llm, toolbox, history, system=system)
        except LLMUnavailable as error:
            raise ApiError(str(error), 504 if error.code == 'ai_timeout' else 503, error.code) from error
        return {'reply': outcome.reply, 'suggested_actions': outcome.suggested_actions,
                'tools_used': outcome.tools_used, 'model': outcome.model}
    if path == 'ai/search':
        query = str(body.get('query') or '').strip()
        if not 2 <= len(query) <= 300:
            raise ApiError('Descreva a busca com 2 a 300 caracteres.', 422, 'validation_error')
        return (await natural_search(query, llm=llm))[0]
    if path == 'ai/session-insight':
        record = api._sessions.get(str(body.get('session_id') or ''))
        if not record:
            raise ApiError('Sessão não encontrada.', 404, 'not_found')
        session = api._operation_row(record, 'session')
        return (await session_insight(session, source.recent_sessions(30), now=now, llm=llm))[0]
    if not api._profile.get('operator_enabled'):
        raise ApiError('Operador não habilitado.', 403, 'forbidden')
    days = body.get('days', 30)
    if not isinstance(days, int) or not 7 <= days <= 90:
        raise ApiError('Período deve ter de 7 a 90 dias.', 422, 'validation_error')
    sessions = source.owner_sessions(now - timedelta(days=days))
    return (await owner_insights(source.owner_stations(), sessions, now=now, days=days, llm=llm))[0]
