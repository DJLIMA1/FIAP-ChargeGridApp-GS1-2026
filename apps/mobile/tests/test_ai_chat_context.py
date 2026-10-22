"""Chat de IA: contexto do aparelho, botões novos e a prévia demo com o cartão da conta (sem rede)."""

import json
import unittest
from unittest.mock import AsyncMock, patch

from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DemoApi
from chargegrid_app.screens import chat
from chargegrid_app.services import demo_ai, geolocation, vehicle_state
from test_ai_features import AI_REPLY, AiApi, ChatApp

DEMAND_WORDS = ('demand', 'demanda', 'multiplier', 'multiplicador', 'acréscimo')


class ChatContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_app_battery_and_allowed_position_without_asking(self):
        request = AsyncMock(return_value=AI_REPLY)
        app = ChatApp(AiApi(request))
        with patch.object(vehicle_state, 'current_soc', AsyncMock(return_value=(41.0, 'phone'))), \
                patch.object(geolocation, 'current_position', AsyncMock(return_value=(-23.561234567, -46.65)))as gps:
            await chat.ai_answer(app, [{'role': 'user', 'content': 'quanto custa encher?'}])
        gps.assert_awaited_once_with(app, ask=False)
        self.assertEqual(request.await_args.args[2]['context'],
                         {'mode': 'driver', 'soc_percent': 41.0, 'soc_source': 'phone', 'lat': -23.56123, 'lng': -46.65})

    async def test_context_failures_never_block_the_question(self):
        request = AsyncMock(return_value=AI_REPLY)
        app = ChatApp(AiApi(request))
        with patch.object(vehicle_state, 'current_soc', AsyncMock(side_effect=RuntimeError('x'))), \
                patch.object(geolocation, 'current_position', AsyncMock(side_effect=OSError('x'))):
            await chat.ai_answer(app, [{'role': 'user', 'content': 'oi'}])
        self.assertEqual(request.await_args.args[2]['context'], {'mode': 'driver'})

    async def test_owner_mode_sends_no_battery(self):
        request = AsyncMock(return_value=AI_REPLY)
        app = ChatApp(AiApi(request))
        app.browsing_mode = 'vendor'
        with patch.object(vehicle_state, 'current_soc', AsyncMock(return_value=(41.0, 'phone'))) as soc:
            await chat.ai_answer(app, [{'role': 'user', 'content': 'receita'}])
        soc.assert_not_awaited()
        self.assertNotIn('soc_percent', request.await_args.args[2]['context'])

    def test_new_actions_open_existing_screens(self):
        mapped = chat._ai_actions([
            {'type': 'open_receipt', 'session_id': 's9', 'label': 'Ver recibo'},
            {'type': 'open_tariffs', 'station_id': 'st1', 'label': 'Abrir tarifas'},
            {'type': 'open_owner_history', 'label': 'Ver histórico dos postos'},
        ])
        self.assertEqual(mapped, [
            {'label': 'Ver recibo', 'route': 'history', 'data': {'receipt': 's9'}},
            {'label': 'Abrir tarifas', 'route': 'tariffs', 'data': {'station_id': 'st1'}},
            {'label': 'Ver histórico dos postos', 'route': 'history', 'data': {'manage': True}}])
        mapped = chat._ai_actions([{'type': 'open_receipt', 'label': 'Sem sessão'},
                                   {'type': 'open_wallet', 'label': 'Abrir carteira'},
                                   {'type': 'open_coupons', 'label': 'Abrir cupons'}])
        self.assertEqual([(a['route'], a['data']) for a in mapped],
                         [('wallet', {}), ('coupons', {'manage': True})])


class DemoContextTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        demo_ai._recent.clear()
        self.api = DemoApi()
        await self.api.login(DEMO_EMAIL, DEMO_PASSWORD)

    async def _chat(self, calls, *, mode='driver', **context):
        seen = []

        async def fake_complete(messages, tools, timeout=None, tool_choice='auto', **options):
            seen.append({'messages': messages, 'tools': [t['function']['name'] for t in tools]})
            if len(seen) == 1:
                return {'content': '', 'model': 'fake', 'usage': {}, 'tool_calls': [
                    {'id': str(i), 'name': name, 'arguments': json.dumps(args)} for i, (name, args) in enumerate(calls)]}
            return {'content': 'Pronto.', 'model': 'fake', 'usage': {}, 'tool_calls': []}

        with patch.dict('os.environ', {'CHARGEGRID_ENABLE_DEMO': '1', 'OPENROUTER_API_KEY': 'test-key'}), \
                patch.object(demo_ai, 'complete', fake_complete), \
                patch('httpx.AsyncClient', side_effect=AssertionError('network')):
            result = await self.api.request('POST', 'ai/chat', {
                'messages': [{'role': 'user', 'content': 'pergunta'}], 'context': {'mode': mode, **context}})
        tools = [json.loads(m['content']) for m in seen[1]['messages'] if m['role'] == 'tool']
        return result, seen, tools

    async def test_demo_driver_cost_question_uses_car_card(self):
        result, seen, tools = await self._chat([('estimate_charge', {'from_percent': 20, 'to_percent': 80})],
                                               soc_percent=33, soc_source='simulated')
        system = seen[0]['messages'][0]['content']
        self.assertIn('DADOS DA CONTA', system)
        self.assertIn('BYD Dolphin', system)
        self.assertIn('nível estimado pelo app', system)
        self.assertIn('estimate_charge', seen[0]['tools'])
        self.assertNotIn('get_owner_overview', seen[0]['tools'])
        estimate = tools[0]
        self.assertNotIn('error', estimate)
        self.assertEqual(estimate['options'][0]['energy_kwh'], round(44.9 * 0.6, 2))
        self.assertTrue(result['suggested_actions'])
        text = json.dumps(tools, ensure_ascii=False).lower()
        for word in DEMAND_WORDS:
            self.assertNotIn(word, text)

    async def test_demo_owner_tools_use_the_demo_dashboard(self):
        self.api._profile['operator_enabled'] = True
        result, seen, tools = await self._chat([('get_owner_overview', {'period': '30d'}),
                                                 ('get_owner_ranking', {'order': 'bottom'}),
                                                 ('get_margin_report', {}), ('get_owner_alerts', {})], mode='owner')
        self.assertIn('get_tariff_suggestions', seen[0]['tools'])
        self.assertNotIn('estimate_charge', seen[0]['tools'])
        self.assertIn('Modo dono de posto', seen[0]['messages'][0]['content'])
        overview, ranking, margin, alerts = tools
        for data in tools:
            self.assertNotIn('error', data)
        self.assertEqual(overview['period'], 'últimos 30 dias')
        self.assertIn('items', ranking)
        self.assertIn('totals', margin)
        self.assertIn('total', alerts)
        self.assertIn('open_owner_history', [a['type'] for a in result['suggested_actions']])
