"""Previsão no app: cartão "Melhor horário" do motorista e previsão do vendedor (conta demo)."""

import unittest
from unittest.mock import patch

import flet as ft

from chargegrid_app.api_client import ApiError
from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DemoApi
from chargegrid_app.screens import history, history_owner, stations
from chargegrid_app.services import maps
from chargegrid_app.ui import forecast as forecast_ui
from test_behavior import HandlerApp, descendants


def texts(control):
    return [str(item.value) for item in descendants(control) if isinstance(item, ft.Text)]


def joined(control):
    return ' | '.join(texts(control))


class Dialogs:
    def __init__(self):
        self.shown = []

    def show_dialog(self, dialog):
        self.shown.append(dialog)

    def pop_dialog(self):
        pass

    def update(self):
        pass


class ForecastScreenTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = HandlerApp()
        self.app.page = Dialogs()
        self.app.api = DemoApi(clock=lambda: 0.0)
        await self.app.api.login(DEMO_EMAIL, DEMO_PASSWORD)
        self.app.profile = await self.app.api.request('GET', 'me')

    async def test_driver_station_shows_best_time_to_charge(self):
        with patch.object(maps, 'build_map_png', side_effect=AssertionError('network tiles')):
            first = (await self.app.api.request('GET', 'stations'))['items'][0]
            screen = await stations.build(self.app, station_id=first['id'])
        text = joined(screen)
        self.assertIn('Melhor horário para carregar', text)
        self.assertIn('a partir de R$', text)
        self.assertIn('Estimativa. O preço é travado', text)
        self.assertIn('Reservar estação', text)  # o fluxo principal continua igual

    async def test_best_time_card_disappears_when_the_api_fails(self):
        original = self.app.api.request

        async def failing(method, path, *args, **kwargs):
            if path.endswith('/best-times'):
                raise ApiError('Indisponível', 503, 'unavailable')
            return await original(method, path, *args, **kwargs)

        first = (await original('GET', 'stations'))['items'][0]
        with patch.object(self.app.api, 'request', side_effect=failing), \
                patch.object(maps, 'build_map_png', side_effect=AssertionError('network tiles')):
            screen = await stations.build(self.app, station_id=first['id'])
        self.assertNotIn('Melhor horário para carregar', joined(screen))
        self.assertIn('Carregar agora', joined(screen))

    async def test_vendor_forecast_page_shows_method_accuracy_and_synthetic_label(self):
        screen = await history.build(self.app, manage=True, page='forecast')
        text = joined(screen)
        self.assertIn('Previsão de ocupação', text)
        self.assertIn('Em uso:', text)
        self.assertIn('Erro por hora:', text)
        self.assertIn(forecast_ui.SYNTHETIC_LABEL, text)

    async def test_energy_page_links_to_the_forecast(self):
        screen = await history.build(self.app, manage=True, page='energy')
        summary = next(item for item in descendants(screen) if getattr(item, 'data', None) == 'forecast-summary')
        self.assertIn('Previsão de ocupação', joined(summary))
        await summary.on_click(None)
        route, kwargs = self.app.go.call_args.args[0], self.app.go.call_args.kwargs
        self.assertEqual((route, kwargs['page']), ('history', 'forecast'))

    async def test_vendor_applies_a_suggestion_through_the_tariff_rules(self):
        stations_page = await self.app.api.request('GET', 'operator/stations', params={'limit': 100, 'offset': 0})
        station_id = stations_page['items'][0]['id']
        data = await self.app.api.owner_forecast(station_id)
        self.assertTrue(data['suggestions'])
        item = data['suggestions'][0]
        card = history_owner._suggestion_card(self.app, station_id, item)
        review = next(c.on_click for c in descendants(card)
                      if isinstance(c, ft.TextButton) and c.content == 'Revisar e aplicar')
        review(None)
        dialog = self.app.page.shown[-1]
        await dialog.actions[1].on_click(None)
        rules = (await self.app.api.request('GET', f'stations/{station_id}/pricing'))['rules']
        patch_keys = set(item['action']['patch'])
        if 'schedule' in patch_keys:
            self.assertTrue(rules['schedule']['intervals'])
        self.assertTrue(self.app.notices and 'Tarifa atualizada' in self.app.notices[-1])

    def test_window_text_and_empty_payload(self):
        self.assertEqual(forecast_ui.window_text('2026-10-21T14:00:00-03:00', '2026-10-21T16:00:00-03:00'), '14h–16h')
        self.assertEqual(forecast_ui.window_text('2026-10-21T22:00:00-03:00', '2026-10-22T00:00:00-03:00'), '22h–24h')
        self.assertIsNone(forecast_ui.best_time_card({'best': None, 'hours': []}))


if __name__ == '__main__':
    unittest.main()
