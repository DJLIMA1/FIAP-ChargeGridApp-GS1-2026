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

from chargegrid_core import analytics, economics
from chargegrid_core.ai import (
    LLMUnavailable,
    Toolbox,
    ToolDataError,
    build_context,
    build_payload,
    indicators_from_dashboard,
    natural_search,
    owner_insights_from_indicators,
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


def _owner_errors(function):
    """ApiError da demo (posto alheio, período inválido) vira ToolDataError, como na API."""
    def wrapper(self, *args, **kwargs):
        try:
            return function(self, *args, **kwargs)
        except ApiError as error:
            raise ToolDataError(str(error) or 'dado indisponível') from error
    wrapper.__name__ = function.__name__
    return wrapper


def _window(start, end, station_id=None):
    params = {'from': start.isoformat(), 'to': end.isoformat()}
    if station_id:
        params['station_id'] = station_id
    return params


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

    def driver_profile(self):
        return self.api._driver_profile

    def driver_stations(self):
        # Mesmos postos que POST driver/plan da demo usa (inclui a rede parceira com comodidades).
        from .driver_demo import ensure_network
        ensure_network(self.api)
        return [self.api._station_row(s) for s in self.api._stations.values() if s['active']]

    # ------------------------------------------------ motorista (contexto e ferramentas)
    def vehicle(self):
        profile = self.api._driver_profile
        return {'vehicle': (profile or {}).get('vehicle'), 'saved': profile is not None}

    def wallet(self):
        from . import wallet
        state = wallet._demo_state or wallet._demo_initial()
        return {'balance': state.get('balance'), 'transactions': list(reversed(state.get('transactions') or []))}

    def session_receipt(self, session_id=None):
        from .. import demo_receipt
        if not session_id:
            finished = [s for s in self.recent_sessions(20) if s.get('status') in ('completed', 'interrupted')]
            if not finished:
                return None
            session_id = finished[0]['id']
        try:
            return demo_receipt.receipt(self.api, session_id)
        except ApiError:
            return None

    def station_best_times(self, station_id):
        from . import forecast_demo
        try:
            return forecast_demo.best_times(self.api, station_id)
        except ApiError:
            return None

    # ------------------------------------------------ dono (mesmos números do painel demo)
    def _owner(self):
        from ..demo_owner import owner_for
        if not self.api._profile.get('operator_enabled'):
            raise ToolDataError('disponível somente para donos de posto')
        return owner_for(self.api)

    def owner_station_names(self):
        owner = self.api._profile.get('id')
        if not self.api._profile.get('operator_enabled'):
            return []
        return sorted(({'id': s['id'], 'name': s['name']} for s in self.api._stations.values()
                       if s['owner_id'] == owner and not s.get('removed_at')), key=lambda s: (s['name'], s['id']))

    @_owner_errors
    def owner_overview(self, start, end, station_id=None):
        return self._owner().overview(_window(start, end, station_id))

    @_owner_errors
    def owner_ranking(self, start, end, station_id=None):
        owner = self._owner()
        if station_id:
            self.api._owned(station_id)
        sessions, _ = owner.records(station_id)
        points = [{'connector_id': p['id'], 'station_id': p['station_id'],
                   'station_name': self.api._stations[p['station_id']]['name'], 'public_code': p['public_code']}
                  for p in owner._owned_points(station_id)]
        return analytics.ranking_payload(analytics.ranking_rows(sessions, points, start, end, self.api._now()), start, end)

    @_owner_errors
    def owner_timeseries(self, start, end, granularity='day', station_id=None):
        return self._owner().timeseries({**_window(start, end, station_id), 'granularity': granularity})

    @_owner_errors
    def owner_heatmap(self, start, end, station_id=None):
        return self._owner().heatmap(_window(start, end, station_id))

    @_owner_errors
    def owner_alerts(self, station_id=None):
        return self._owner().alerts({'station_id': station_id} if station_id else {})

    @_owner_errors
    def owner_live(self, station_id=None):
        return self._owner().live({'station_id': station_id} if station_id else {})

    @_owner_errors
    def owner_forecast(self, station_id):
        return self._owner().forecast({'station_id': station_id})

    @_owner_errors
    def owner_margin(self, start, end, station_id=None):
        return economics.serialize(self._owner().margin_report(_window(start, end, station_id)))

    def owner_coupons(self):
        return (self._get('coupons', {'mine': 'true', 'limit': 100}) or {}).get('items', [])


def _limit():
    now = time.monotonic()
    while _recent and now - _recent[0] > WINDOW[1]:
        _recent.popleft()
    if len(_recent) >= WINDOW[0]:
        raise ApiError('Você atingiu o limite de perguntas ao assistente. Tente novamente mais tarde.', 429, 'ai_rate_limited')
    _recent.append(now)


def _origin(context):
    try:
        lat, lng = float(context.get('lat')), float(context.get('lng'))
    except (TypeError, ValueError):
        return None
    return {'lat': lat, 'lng': lng} if -90 <= lat <= 90 and -180 <= lng <= 180 else None


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
        raise ApiError('Esta operação não está disponível nesta conta.', 404, 'demo_route_not_supported')
    _limit()
    llm = complete if available() else None
    now = api._now()
    source = DemoSource(api)
    if path == 'ai/chat':
        history = _messages(body)
        if llm is None:
            raise ApiError('Assistente de IA indisponível no momento.', 503, 'ai_unavailable')
        context = body.get('context') if isinstance(body.get('context'), dict) else {}
        owner = bool(api._profile.get('operator_enabled'))
        role = 'owner' if owner and context.get('mode') == 'owner' else 'driver'
        origin = _origin(context)
        card = await build_context(source, role=role, now=now,
                                   client={'soc_percent': context.get('soc_percent'),
                                           'soc_source': context.get('soc_source')})
        toolbox = Toolbox(source, owner=owner, now=now, origin=origin, role=role, context=card)
        system = system_prompt(role=role, demo=True, now=now, user_name=api._profile.get('name') or None, context=card,
                               location_label='localização atual do aparelho' if origin else None)
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
        if record.get('status') not in ('completed', 'interrupted'):
            raise ApiError('O resumo fica disponível quando a recarga terminar.', 409, 'session_not_finished')
        session = api._operation_row(record, 'session')
        return (await session_insight(session, source.recent_sessions(30), now=now, llm=llm))[0]
    if not api._profile.get('operator_enabled'):
        raise ApiError('Operador não habilitado.', 403, 'forbidden')
    return await _owner_insights(api, body, now, llm)


async def _owner_insights(api, body, now, llm):
    """Mesmo corpo do dashboard ({from, to, station_id}) e os mesmos indicadores
    (chargegrid_core.analytics via demo_owner) que a tela de Insights mostra."""
    from ..demo_owner import owner_for

    days = body.get('days', 30)
    if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= 366:
        raise ApiError('Período deve ter de 1 a 366 dias.', 422, 'validation_error')
    params = {key: body[key] for key in ('from', 'to', 'station_id') if body.get(key)}
    if 'from' not in params:
        end = analytics.parse_time(params.get('to')) or now
        params['from'] = (end - timedelta(days=days)).isoformat()
    owner = owner_for(api)
    overview, heatmap = owner.overview(params), owner.heatmap(params)
    alerts = owner.alerts({'station_id': params.get('station_id')})['items']
    indicators = indicators_from_dashboard(overview, heatmap, alerts)
    return (await owner_insights_from_indicators(indicators, now=now, llm=llm))[0]
