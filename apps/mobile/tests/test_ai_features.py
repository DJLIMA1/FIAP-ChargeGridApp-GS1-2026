"""AI chat, natural-language search and insights in the app (never reaching the network)."""

import json
import re
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import flet as ft

import chargegrid_core.driver as driver_package
from chargegrid_app.api_client import ApiClient, ApiError
from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DemoApi
from chargegrid_app.screens import chat, history, operator, stations
from chargegrid_app.services import demo_ai, demo_ai_bridge
from chargegrid_app.ui import ai_features
from test_behavior import HandlerApp, click, descendants

APP_ROOT = Path(__file__).resolve().parents[1]


def texts(screen):
    return '\n'.join(str(c.value) for c in descendants(screen) if isinstance(c, ft.Text))


def by_tooltip(screen, tooltip):
    """Action by tooltip, or by the visible label of an AI disclosure button."""
    return next(c.on_click for c in descendants(screen)
                if (getattr(c, 'tooltip', None) == tooltip or getattr(c, 'data', None) == ('ai-disclosure', tooltip))
                and getattr(c, 'on_click', None))


class AiApi:
    ai_enabled = True

    def __init__(self, request):
        self.request = request
        self.is_demo = False
        self.session = SimpleNamespace(user={'id': 'account-a'}, access_token='token')


class ChatApp:
    def __init__(self, api):
        self.profile = {'id': 'account-a', 'name': 'Ana', 'account_type': 'consumer', 'operator_enabled': False}
        self.api = api
        self.page = SimpleNamespace(update=Mock())
        self.browsing_mode = 'consumer'
        self.go = AsyncMock()
        self.prepare_navigation = AsyncMock(return_value=True)

    def action(self, operation):
        async def handler(event=None):
            await operation()
        return handler

    def link(self, route, **data):
        async def handler(event=None):
            if await self.prepare_navigation():
                await self.go(route, **data)
        return handler


AI_REPLY = {'reply': 'O Posto Demo tem CCS2 livre por R$ 1,85/kWh.', 'tools_used': ['search_stations'],
            'model': 'deepseek/deepseek-v4.1-flash',
            'suggested_actions': [{'type': 'open_station', 'station_id': 's1', 'label': 'Ver Posto Demo'},
                                  {'type': 'reserve', 'station_id': 's1', 'connector_id': 'p1', 'label': 'Reservar P1'},
                                  {'type': 'open_driver', 'label': 'Modo motorista'},
                                  {'type': 'delete_account', 'label': 'x'}]}


class ChatAiTests(unittest.IsolatedAsyncioTestCase):
    async def test_ai_reply_maps_actions_to_existing_flows_and_shows_disclaimer(self):
        request = AsyncMock(return_value=AI_REPLY)
        app = ChatApp(AiApi(request))
        screen = await chat.build(app)
        self.assertIn('IA com dados da sua conta', texts(screen))
        self.assertIn('Respostas geradas por IA podem conter erros', texts(screen))
        self.assertIn('Postos rápidos perto da Paulista', texts(screen))
        field = next(c for c in descendants(screen) if isinstance(c, ft.TextField))
        field.value = 'Quero um CCS2 perto da Paulista'
        await field.on_submit(None)
        method, path, body = request.await_args.args
        self.assertEqual((method, path), ('POST', 'ai/chat'))
        self.assertEqual(body, {'messages': [{'role': 'user', 'content': 'Quero um CCS2 perto da Paulista'}],
                                'context': {'mode': 'driver'}})
        last = app.chat_messages[-1]
        self.assertEqual(last['source'], 'ai')
        # "Modo motorista" foi descontinuado: a ação da IA não vira botão.
        self.assertEqual([a['label'] for a in last['actions']], ['Ver Posto Demo', 'Reservar P1'])
        self.assertEqual(last['actions'][1], {'label': 'Reservar P1', 'route': 'stations', 'data': {'station_id': 's1'}})
        typing = next(c for c in descendants(screen) if isinstance(c, ft.Semantics) and c.label == 'Assistente digitando')
        self.assertFalse(typing.visible)
        await click(screen, 'Reservar P1')(None)
        app.go.assert_awaited_once_with('stations', station_id='s1')
        request.assert_awaited_once()  # nothing is reserved by the assistant

    async def test_ai_history_sends_recent_turns_only_and_owner_mode(self):
        request = AsyncMock(return_value=AI_REPLY)
        app = ChatApp(AiApi(request))
        app.browsing_mode = 'vendor'
        screen = await chat.build(app)
        self.assertIn('Como foram meus postos este mês?', texts(screen))
        app.chat_messages += [{'role': 'user', 'content': f'q{i}', 'actions': []} if i % 2 == 0 else
                              {'role': 'assistant', 'content': 'r' * 900, 'actions': []} for i in range(12)]
        await chat.ai_answer(app, app.chat_messages + [{'role': 'user', 'content': 'nova'}])
        body = request.await_args.args[2]
        self.assertEqual(body['context'], {'mode': 'owner'})
        self.assertLessEqual(len(body['messages']), 8)
        self.assertEqual(body['messages'][0]['role'], 'user')
        self.assertEqual(body['messages'][-1], {'role': 'user', 'content': 'nova'})
        self.assertTrue(all(len(m['content']) <= 600 for m in body['messages']))
        self.assertLess(len(json.dumps(body).encode()), 16384)

    async def test_ai_failure_falls_back_to_local_guidance_and_retry_does_not_duplicate_question(self):
        request = AsyncMock(side_effect=[ApiError('down', 503, 'ai_unavailable'), AI_REPLY])
        app = ChatApp(AiApi(request))
        screen = await chat.build(app)
        field = next(c for c in descendants(screen) if isinstance(c, ft.TextField))
        field.value = 'Como iniciar uma recarga?'
        await field.on_submit(None)
        fallback = app.chat_messages[-1]
        self.assertEqual(fallback['source'], 'local')
        self.assertIn('Confirmar ponto', fallback['content'])
        self.assertIn('orientações locais', fallback['note'])
        self.assertIn('orientações locais', texts(screen))
        await by_tooltip(screen, 'Reenviar a pergunta ao assistente de IA')(None)
        self.assertEqual([m['role'] for m in app.chat_messages], ['assistant', 'user', 'assistant', 'assistant'])
        self.assertEqual(app.chat_messages[-1]['source'], 'ai')
        self.assertEqual(request.await_args.args[2]['messages'][-1]['content'], 'Como iniciar uma recarga?')

    async def test_rate_limit_and_offline_notes(self):
        self.assertIn('Limite', chat._fallback_note(ApiError('x', 429)))
        self.assertIn('Sem conexão', chat._fallback_note(ApiError('x')))
        with self.assertRaises(ApiError):
            await chat.ai_answer(ChatApp(AiApi(AsyncMock(return_value={'reply': ''}))), [{'role': 'user', 'content': 'x'}])

    async def test_clients_declare_ai_support(self):
        self.assertTrue(ApiClient.ai_enabled)
        self.assertTrue(ai_features.ai_supported(SimpleNamespace(api=DemoApi())))
        self.assertFalse(ai_features.ai_supported(SimpleNamespace(api=SimpleNamespace(request=None))))
        self.assertFalse(ai_features.ai_supported(SimpleNamespace(api=Mock())))


class DemoAiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        demo_ai._recent.clear()
        self.api = DemoApi()
        await self.api.login(DEMO_EMAIL, DEMO_PASSWORD)

    async def test_demo_without_key_uses_rules_and_local_chat(self):
        with patch.dict('os.environ', {'CHARGEGRID_ENABLE_DEMO': '1'}, clear=False), \
                patch('httpx.AsyncClient', side_effect=AssertionError('network')):
            self.assertFalse(self.api.ai_enabled)
            with self.assertRaises(ApiError) as error:
                await self.api.request('POST', 'ai/chat', {'messages': [{'role': 'user', 'content': 'oi'}]})
            self.assertEqual((error.exception.status, error.exception.code), (503, 'ai_unavailable'))
            found = await self.api.request('POST', 'ai/search', {'query': 'tipo 2 disponível perto do centro até R$ 2/kWh'})
            self.assertEqual(found['model'], 'chargegrid-regras')
            self.assertEqual(found['params']['connector_type'], 'type2')
            self.assertEqual(found['params']['max_price_per_kwh'], '2.00')
            sessions = await self.api.request('GET', 'me/charging-sessions')
            insight = await self.api.request('POST', 'ai/session-insight', {'session_id': sessions['items'][0]['id']})
            self.assertIn('kWh', insight['summary'])
            self.assertEqual(insight['comparison']['history_sessions'], 1)
            owner = await self.api.request('POST', 'ai/owner-insights', {})
            self.assertEqual(set(owner), {'summary', 'recommendations', 'generated_at', 'model'})
            self.assertTrue(owner['recommendations'])
            with self.assertRaises(ApiError):
                await self.api.request('POST', 'ai/session-insight', {'session_id': 'other'})

    async def test_demo_with_key_runs_core_loop_over_demo_data(self):
        calls = []

        async def fake_complete(messages, tools, timeout=None, tool_choice='auto', **options):
            calls.append(messages)
            if len(calls) == 1:
                return {'content': '', 'model': 'fake', 'usage': {},
                        'tool_calls': [{'id': '1', 'name': 'search_stations', 'arguments': '{"available_only": true}'}]}
            return {'content': 'O Villa Lobos tem ponto livre. Reserve pelo botão.', 'model': 'fake',
                    'usage': {}, 'tool_calls': []}

        with patch.dict('os.environ', {'CHARGEGRID_ENABLE_DEMO': '1', 'OPENROUTER_API_KEY': 'test-key'}), \
                patch.object(demo_ai, 'complete', fake_complete), \
                patch('httpx.AsyncClient', side_effect=AssertionError('network')):
            self.assertTrue(self.api.ai_enabled)
            result = await self.api.request('POST', 'ai/chat', {'messages': [
                {'role': 'user', 'content': 'quero reservar um ponto'}], 'context': {'mode': 'driver'}})
        self.assertEqual(result['tools_used'], ['search_stations'])
        tool_data = json.loads(calls[1][-1]['content'])
        # A rede parceira fictícia também aparece na busca da demo.
        self.assertIn('Villa Lobos', [station['name'] for station in tool_data['stations']])
        self.assertIn('demonstração', calls[0][0]['content'])
        self.assertEqual([a['type'] for a in result['suggested_actions']], ['open_station', 'reserve'])

    @patch.object(driver_package, 'DISCONTINUED', False)  # código guardado do Modo motorista
    async def test_demo_chat_plans_driver_shift_with_driver_engine(self):
        calls = []

        async def fake_complete(messages, tools, timeout=None, tool_choice='auto', **options):
            calls.append(messages)
            if len(calls) == 1:
                return {'content': '', 'model': 'fake', 'usage': {}, 'tool_calls': [
                    {'id': '1', 'name': 'plan_driver_shift', 'arguments': '{"current_soc_percent": 20, "full_shift": true}'}]}
            return {'content': 'Recarregue antes do almoço.', 'model': 'fake', 'usage': {}, 'tool_calls': []}

        with patch.dict('os.environ', {'CHARGEGRID_ENABLE_DEMO': '1', 'OPENROUTER_API_KEY': 'test-key'}), \
                patch.object(demo_ai, 'complete', fake_complete):
            result = await self.api.request('POST', 'ai/chat', {'messages': [
                {'role': 'user', 'content': 'planeja meu turno de hoje'}]})
        data = json.loads(calls[1][-1]['content'])
        self.assertNotIn('error', data)
        self.assertTrue(data['stops'])
        self.assertEqual(result['suggested_actions'][0]['type'], 'open_driver')
        # O app não abre mais o Modo motorista (descontinuado): a ação é ignorada.
        mapped = chat._ai_actions(result['suggested_actions'])
        self.assertNotIn('driver', [action['route'] for action in mapped])

    async def test_demo_validation_and_rate_limit(self):
        with patch.dict('os.environ', {'CHARGEGRID_ENABLE_DEMO': '1', 'OPENROUTER_API_KEY': 'k'}):
            with self.assertRaises(ApiError) as error:
                await self.api.request('POST', 'ai/chat', {'messages': [{'role': 'system', 'content': 'x'}]})
            self.assertEqual(error.exception.status, 422)
            demo_ai._recent.extend([float('inf')] * demo_ai.WINDOW[0])
            with self.assertRaises(ApiError) as error:
                await self.api.request('POST', 'ai/search', {'query': 'ccs'})
            self.assertEqual(error.exception.status, 429)

    async def test_demo_dashboard_owner_insights_use_real_ai_with_key(self):
        seen = []

        async def fake_complete(messages, tools, timeout=None, tool_choice='auto', **options):
            seen.append((messages, options))
            return {'content': json.dumps({'summary': 'Resumo IA.', 'recommendations': [
                {'title': 'Pico', 'detail': 'Tarifa maior às 18h.', 'impact': 'high', 'kind': 'pricing'}]}),
                'model': 'deepseek/deepseek-v4.1-flash', 'usage': {}, 'tool_calls': []}

        end = self.api._now()
        body = {'from': (end - timedelta(days=7)).isoformat(), 'to': end.isoformat(), 'station_id': None}
        with patch.dict('os.environ', {'CHARGEGRID_ENABLE_DEMO': '1', 'OPENROUTER_API_KEY': 'test-key'}), \
                patch.object(demo_ai, 'complete', fake_complete):
            result = await self.api.owner_insights(body)
        self.assertEqual(result['model'], 'deepseek/deepseek-v4.1-flash')
        self.assertEqual(result['recommendations'][0]['impact'], 'high')
        facts = json.loads(seen[0][0][1]['content'])['indicadores']
        self.assertEqual(facts['period_days'], 7)
        self.assertGreater(facts['sessions'], 0)  # histórico fictício do dashboard (chargegrid_core.analytics)
        self.assertEqual(seen[0][1]['reasoning_effort'], 'none')

    async def test_bridge_without_preview_module_is_unavailable(self):
        with patch.object(demo_ai_bridge, '_module', return_value=None):
            self.assertFalse(demo_ai_bridge.chat_available())
            with self.assertRaises(ApiError) as error:
                await demo_ai_bridge.handle(self.api, 'POST', 'ai/search', {'query': 'x'})
            self.assertEqual(error.exception.code, 'ai_unavailable')
            sample = await demo_ai_bridge.handle(self.api, 'POST', 'ai/owner-insights', {})
            self.assertEqual(set(sample), {'summary', 'recommendations', 'generated_at', 'model'})


class AiScreensTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        demo_ai._recent.clear()
        self.app = HandlerApp()
        self.app.api = DemoApi()
        await self.app.api.login(DEMO_EMAIL, DEMO_PASSWORD)
        self.app.profile = await self.app.api.request('GET', 'me')

    async def test_station_screen_has_no_ai_search_card(self):
        # Filters moved to the search-bar sheet; natural-language search is not on this screen anymore.
        with patch.dict('os.environ', {'CHARGEGRID_ENABLE_DEMO': '1'}), \
                patch('httpx.AsyncClient', side_effect=AssertionError('network')):
            screen = await stations.build(self.app)
        self.assertNotIn('Busca inteligente', texts(screen))
        self.assertNotIn('Buscar com IA', texts(screen))

    async def test_history_session_insight_and_operator_insights(self):
        with patch.dict('os.environ', {'CHARGEGRID_ENABLE_DEMO': '1'}), \
                patch('httpx.AsyncClient', side_effect=AssertionError('network')):
            screen = await history.build(self.app)
            await by_tooltip(screen, 'Resumo inteligente da recarga')(None)
            self.assertIn('Recarga de 2,40 kWh', texts(screen))
            self.assertIn('Valores estimados', texts(screen))
            screen = await operator.build(self.app)
            await by_tooltip(screen, 'Insights dos meus postos (30 dias)')(None)
            self.assertRegex(texts(screen), r'De \d{2}/\d{2} a \d{2}/\d{2}: \d+ recarga')
            self.assertRegex(texts(screen), r'impacto (alto|médio|baixo)')


class PackagingTests(unittest.TestCase):
    def test_openrouter_code_and_key_stay_out_of_the_apk(self):
        config = (APP_ROOT / 'pyproject.toml').read_text()
        self.assertIn('"src/chargegrid_app/services/demo_ai.py"', config)
        offenders = []
        for path in (APP_ROOT / 'src').rglob('*.py'):
            if path.name == 'demo_ai.py':
                continue
            source = path.read_text()
            if re.search(r'openrouter\.ai|OPENROUTER_API_KEY|sk-or-', source):
                offenders.append(str(path.relative_to(APP_ROOT)))
        self.assertEqual(offenders, [])
        assets = [p for p in (APP_ROOT / 'assets').rglob('*') if p.is_file() and p.suffix in ('.json', '.txt', '.env')]
        self.assertFalse(any('sk-or-' in p.read_text(errors='ignore') for p in assets))
