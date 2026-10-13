"""End-to-end polish: first impression, differentials and demo coherence."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import flet as ft

from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DemoApi
from chargegrid_app.screens import auth, chat, driver, history, home
from chargegrid_app.services.driver import amenities_text, amenity_label
from test_chat import ChatApp, composer, send_button
from test_home_ux import HomeApp, click, descendants, text_values
from test_screens import FakeApp


class PolishTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        render = patch('chargegrid_app.services.maps.build_map_png', return_value=b'fixture-png')
        render.start()
        self.addCleanup(render.stop)

    async def test_sign_in_presents_the_three_differentials(self):
        screen = await auth.build(FakeApp([]), mode='login')
        visible = ' '.join(str(value) for value in text_values(screen))
        for differential in ('Modo Motorista', 'Assistente com IA', 'Painel web'):
            self.assertIn(differential, visible)

    async def test_home_greets_demo_role_and_offers_driver_mode_and_assistant(self):
        app = HomeApp()
        app.api.is_demo = True
        app.api.ai_enabled = True
        app.profile = {'name': 'Conta demonstração'}
        screen = await home.build(app)
        visible = text_values(screen, visible_only=True)
        self.assertIn('Olá, motorista', visible)
        self.assertNotIn('Olá, Conta', visible)
        self.assertIn('ASSISTENTE COM IA', visible)
        # Differentials come right after the main action, before the map.
        self.assertLess(visible.index('MODO MOTORISTA DE APP'), visible.index('Postos no mapa'))
        await click(screen, 'Perguntar ao assistente')(None)
        app.go.assert_awaited_with('chat')

    async def test_home_without_ai_keeps_a_plain_assistant_entry(self):
        app = HomeApp()
        screen = await home.build(app)
        visible = text_values(screen, visible_only=True)
        self.assertIn('ASSISTENTE', visible)
        self.assertNotIn('ASSISTENTE COM IA', visible)
        self.assertIn('Olá, Marina', visible)

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

    async def test_history_shows_ai_summary_on_the_card(self):
        api = DemoApi()
        await api.login(DEMO_EMAIL, DEMO_PASSWORD)
        app = SimpleNamespace(api=api, profile={}, page=SimpleNamespace(update=lambda: None),
                              action=lambda operation: operation, link=lambda *args, **kwargs: None)
        screen = await history.build(app)
        cards = [item for item in descendants(screen) if isinstance(item, ft.ExpansionTile)]
        self.assertTrue(cards)
        # The disclosure lives on the card, not inside the collapsed "Detalhes da sessão".
        for tile in cards:
            self.assertFalse(any(getattr(item, 'data', None) == ('ai-disclosure', 'Resumo inteligente da recarga')
                                 for control in tile.controls for item in descendants(control)))
        self.assertTrue(any(getattr(item, 'data', None) == ('ai-disclosure', 'Resumo inteligente da recarga')
                            for item in descendants(screen)))
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
