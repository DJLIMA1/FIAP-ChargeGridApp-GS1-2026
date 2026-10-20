"""Previsão no app: cartão "Melhor horário" (fora do detalhe do posto) e previsão do vendedor (conta demo)."""

import unittest
from unittest.mock import patch

import flet as ft

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

    async def test_station_detail_follows_the_reference_without_the_best_time_card(self):
        # O detalhe do posto segue o design de referência (estacao_3): sem "Melhor horário".
        original = self.app.api.request
        paths = []

        async def recording(method, path, *args, **kwargs):
            paths.append(path)
            return await original(method, path, *args, **kwargs)

        first = (await original('GET', 'stations'))['items'][0]
        with patch.object(self.app.api, 'request', side_effect=recording), \
                patch.object(maps, 'build_map_png', side_effect=AssertionError('network tiles')):
            screen = await stations.build(self.app, station_id=first['id'])
        text = joined(screen)
        self.assertNotIn('Melhor horário para carregar', text)
        self.assertFalse([path for path in paths if path.endswith('/best-times')])
        for expected in ('Detalhes da estação', 'Conectores', 'Abrir rota no Google Maps', 'Reservar estação',
                         'Carregar agora'):
            self.assertIn(expected, text)

    async def test_best_time_card_still_renders_from_the_station_forecast(self):
        # A funcionalidade continua pronta (cartão + rota); só saiu do detalhe do posto.
        first = (await self.app.api.request('GET', 'stations'))['items'][0]
        payload = await self.app.api.request('GET', f"stations/{first['id']}/best-times", params={'hours': 12})
        card = forecast_ui.best_time_card(payload)
        text = joined(card)
        self.assertIn('Melhor horário para carregar', text)
        self.assertIn('a partir de R$', text)
        self.assertIn('Estimativa. O preço é travado', text)

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
