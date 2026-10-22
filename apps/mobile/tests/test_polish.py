"""End-to-end polish: first impression, differentials and demo coherence."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import flet as ft

from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DemoApi
from chargegrid_app.screens import auth, chat, driver, history, home
from chargegrid_app.services.driver import amenities_text, amenity_label
from test_chat import ChatApp, composer, send_button
from test_home_ux import HomeApp, descendants, text_values
from test_screens import FakeApp


class PolishTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        render = patch('chargegrid_app.services.maps.build_map_png', return_value=b'fixture-png')
        render.start()
        self.addCleanup(render.stop)

    async def test_sign_in_stays_clean_without_differential_list(self):
        screen = await auth.build(FakeApp([]), mode='login')
        visible = ' '.join(str(value) for value in text_values(screen))
        for differential in ('Modo Motorista', 'Assistente com IA', 'Painel web'):
            self.assertNotIn(differential, visible)

    async def test_home_greets_demo_role_and_offers_driver_mode_and_assistant(self):
        app = HomeApp()
        app.api.is_demo = True
        app.api.ai_enabled = True
        app.profile = {'name': 'Conta demonstração'}
        screen = await home.build(app)
        visible = text_values(screen, visible_only=True)
        self.assertIn('Olá, motorista!', visible)
        self.assertNotIn('Olá, Conta', visible)
        # O Início não leva mais ao assistente; o chat segue na barra inferior.
        self.assertNotIn('Assistente com IA', visible)
        self.assertNotIn('Modo motorista', visible)  # descontinuado

    async def test_home_without_ai_has_no_assistant_entry(self):
        app = HomeApp()
        screen = await home.build(app)
        visible = text_values(screen, visible_only=True)
        self.assertNotIn('Assistente', visible)
        self.assertIn('Olá, Marina!', visible)

    def test_amenity_labels_do_not_repeat_the_kind(self):
        self.assertEqual(amenity_label({'kind': 'cafe', 'name': 'Café da Sé'}), 'Café da Sé')
        self.assertEqual(amenity_label({'kind': 'restaurante', 'name': 'Cantina da Vila'}), 'Restaurante Cantina da Vila')
        self.assertEqual(amenities_text([{'kind': 'banheiro'}, 'invalid']), 'Banheiro')

    def test_demand_source_is_readable(self):
        self.assertEqual(driver.demand_source_text('heuristica'), 'horários típicos')
        self.assertEqual(driver.demand_source_text('heuristica+open-meteo'), 'horários típicos + clima')
        self.assertEqual(driver.demand_source_text(''), 'estimativa')

    async def test_chat_suggestions_compact_after_the_first_question(self):
        app = ChatApp()
        app.api.request = AsyncMock(return_value=None)
        screen = await chat.build(app)
        chips = next(item for item in descendants(screen) if isinstance(item, ft.Row) and item.wrap)
        composer(screen).value = 'Como iniciar uma recarga?'
        await send_button(screen).on_click(None)
        self.assertFalse(chips.wrap)
        self.assertEqual(chips.scroll, ft.ScrollMode.AUTO)

    async def test_ai_summary_lives_in_the_charge_detail_not_on_the_card(self):
        api = DemoApi()
        await api.login(DEMO_EMAIL, DEMO_PASSWORD)
        app = SimpleNamespace(api=api, profile={}, page=SimpleNamespace(update=lambda: None),
                              action=lambda operation: operation, link=lambda *args, **kwargs: None)
        marker = ('ai-disclosure', 'Resumo inteligente da recarga')
        screen = await history.build(app)
        self.assertFalse(any(getattr(item, 'data', None) == marker for item in descendants(screen)))
        first = (await api.request('GET', 'me/charging-sessions'))['items'][0]
        detail = await history.build(app, session=first['id'])
        self.assertTrue(any(getattr(item, 'data', None) == marker for item in descendants(detail)))
        await api.close()

    def test_charge_needed_next_stop_is_highlighted(self):
        result = {'recommendation': {'action': 'charge_needed', 'headline': 'Recarregue antes de continuar',
                                     'message': 'A bateria não cobre o período.'},
                  'status': {'soc_percent': 3, 'range_above_reserve_km': 0, 'demand_now': 1.0, 'in_peak': False}}
        view = driver.next_stop_view(result, SimpleNamespace(link=lambda *a, **k: None), lambda key: None)[0]
        self.assertIn('RECARGA NECESSÁRIA', text_values(view))
        self.assertEqual(view.border.top.width, 2)
        result['status']['range_above_reserve_km'] = -0.0
        visible = ' '.join(text_values(driver.next_stop_view(result, SimpleNamespace(link=lambda *a, **k: None),
                                                             lambda key: None)[0]))
        self.assertIn('~0 km acima da reserva', visible)
        self.assertNotIn('-0', visible)

    async def test_session_insight_conflict_shows_the_reason(self):
        from chargegrid_app.api_client import ApiError
        from chargegrid_app.ui.ai_features import session_insight_control
        app = SimpleNamespace(page=SimpleNamespace(update=lambda: None), action=lambda operation: operation,
                              api=SimpleNamespace(request=AsyncMock(side_effect=ApiError(
                                  'O resumo fica disponível quando a recarga terminar.', 409, 'session_not_finished'))))
        control = session_insight_control(app, 'session')
        await control.controls[0].on_click()
        self.assertIn('O resumo fica disponível quando a recarga terminar.', text_values(control))

    async def test_chat_shows_partial_answer_with_actions_when_ai_times_out(self):
        from chargegrid_app.services import demo_ai
        from chargegrid_core.ai import LLMUnavailable
        demo_ai._recent.clear()
        calls = []

        async def slow_complete(messages, tools, timeout=None, tool_choice='auto', **options):
            calls.append(messages)
            if len(calls) == 1:
                return {'content': '', 'model': 'fake', 'usage': {},
                        'tool_calls': [{'id': '1', 'name': 'search_stations', 'arguments': '{"available_only": true}'}]}
            raise LLMUnavailable('O assistente demorou demais para responder.', status=504, code='ai_timeout')

        api = DemoApi()
        await api.login(DEMO_EMAIL, DEMO_PASSWORD)
        app = ChatApp()
        app.api = api
        app.profile = await api.request('GET', 'me')
        with patch.dict('os.environ', {'CHARGEGRID_ENABLE_DEMO': '1', 'OPENROUTER_API_KEY': 'test-key'}), \
                patch.object(demo_ai, 'complete', slow_complete):
            screen = await chat.build(app)
            composer(screen).value = 'Postos livres agora?'
            await send_button(screen).on_click(None)
        reply = app.chat_messages[-1]
        self.assertEqual(reply['role'], 'assistant')
        self.assertEqual(reply.get('source'), 'ai')
        self.assertIn('demorou mais que o permitido', reply['content'])
        self.assertTrue(reply['actions'])  # buttons from the data already consulted
        await api.close()

    async def test_demo_public_search_includes_partner_network(self):
        api = DemoApi()
        await api.login(DEMO_EMAIL, DEMO_PASSWORD)
        result = await api.request('GET', 'stations', params={'lat': -23.5614, 'lng': -46.6559, 'radius_km': 5,
                                                              'connector_type': 'CCS2'})
        self.assertIn('Posto Paulista 24h', [station['name'] for station in result['items']])
        await api.close()


if __name__ == '__main__':
    unittest.main()
