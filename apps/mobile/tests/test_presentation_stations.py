"""Postos de vitrine do Modo apresentação: pino branco, parecem postos comuns indisponíveis, nunca chegam à API."""
import unittest
from unittest.mock import AsyncMock, patch

import flet as ft
from chargegrid_map import VectorMap

from chargegrid_app.screens import stations
from chargegrid_app.services import showcase_stations as showcase
from chargegrid_app.ui.vector_map import map_records
from test_behavior import HandlerApp, descendants, station_responses

REAL = {'id': '9df9cd94-0000-4000-8000-000000000001', 'name': 'Lab-Goodwe FIAP',
        'address': 'Av. Paulista, 1106, Bela Vista, São Paulo - SP', 'latitude': -23.5640, 'longitude': -46.6527,
        'connectors': [{'id': 'p1', 'public_code': 'CG-01', 'connector_type': 'Tipo 2', 'power_kw': '7.000',
                        'price_per_kwh': '1.5000', 'max_duration_minutes': 60, 'available': True, 'online': True}]}


def viewport(screen):
    return next(item for item in descendants(screen) if isinstance(item, VectorMap))


def texts(screen):
    return [item.value for item in descendants(screen) if isinstance(item, ft.Text)]


def assert_no_demo_wording(case, screen):
    shown = ' '.join(str(value) for value in texts(screen)).casefold()
    for word in ('demonstra', 'demo', 'ilustrativ', 'simulad', 'simulaç'):
        case.assertNotIn(word, shown)


def app_with(presentation):
    app = HandlerApp()
    app.presentation_override = presentation
    return app


class ShowcaseCatalogTests(unittest.TestCase):
    def test_network_is_display_only_and_spread_across_sao_paulo(self):
        self.assertGreaterEqual(len(showcase.STATIONS), 8)
        areas = {station['address'].split(',')[2].strip() for station in showcase.STATIONS}
        self.assertTrue({'Bela Vista', 'Pinheiros', 'Moema', 'Tatuapé', 'Santana', 'Morumbi',
                         'Vila Olímpia', 'Lapa'} <= areas)
        for station in showcase.STATIONS:
            self.assertTrue(station['id'].startswith(showcase.PREFIX))
            self.assertTrue(-23.75 < station['latitude'] < -23.40 and -46.80 < station['longitude'] < -46.50)
            for point in station['connectors']:
                self.assertFalse(point['available'])
                self.assertEqual(point['public_code'], '')

    def test_filters_apply_without_radius_and_available_only_hides_them(self):
        self.assertEqual(len(showcase.matches()), len(showcase.STATIONS))
        far = showcase.matches(lat=-22.9, lng=-43.2)  # longe de SP: sem raio, todos continuam
        self.assertEqual(len(far), len(showcase.STATIONS))
        self.assertEqual(showcase.matches(available_only=True), [])
        ac_only = showcase.matches(connector_type='CCS2')
        self.assertTrue(ac_only and all(any(p['connector_type'] == 'CCS2' for p in s['connectors']) for s in ac_only))
        cheap = showcase.matches(max_price_per_kwh='1.40')
        self.assertTrue(cheap and all(showcase.price(s) <= 1.40 for s in cheap))
        by_price = showcase.matches(sort='price')
        self.assertEqual([showcase.price(s) for s in by_price], sorted(showcase.price(s) for s in by_price))
        self.assertEqual(len(showcase.matches(sort='distance')), len(showcase.STATIONS))  # sem lat/lng: não quebra

    def test_inject_only_with_presentation_mode_on_the_first_page_after_real_ones(self):
        self.assertEqual(showcase.inject(app_with(False), [REAL]), ([REAL], 0))
        items, extra = showcase.inject(app_with(True), [REAL])
        self.assertEqual(items[0], REAL)
        self.assertEqual(extra, len(showcase.STATIONS))
        self.assertTrue(all(showcase.is_demo(item) for item in items[1:]))
        self.assertEqual(showcase.inject(app_with(True), [REAL], offset=20), ([REAL], 0))

    def test_only_demo_records_get_the_white_marker_tone(self):
        markers = map_records([REAL, showcase.get(showcase.STATIONS[0]['id'])])
        self.assertNotIn('tone', markers[0])
        self.assertEqual(markers[1]['tone'], 'demo')


class ShowcaseScreenTests(unittest.IsolatedAsyncioTestCase):
    async def test_presentation_off_keeps_the_list_unchanged(self):
        app = app_with(False)
        app.api.request.side_effect = station_responses({'items': [REAL], 'total': 1})
        screen = await stations.build(app)
        self.assertEqual([record['id'] for record in viewport(screen).markers], [REAL['id']])
        self.assertIn('1 posto nesta página · 1 encontrado', texts(screen))

    async def test_presentation_on_adds_white_demo_pins_after_the_real_station(self):
        app = app_with(True)
        app.api.request.side_effect = station_responses({'items': [REAL], 'total': 1},
                                                        {'items': [REAL], 'total': 1})
        screen = await stations.build(app, lat=-23.56, lng=-46.65, radius=5)
        markers = viewport(screen).markers
        self.assertEqual(markers[0]['id'], REAL['id'])
        self.assertNotIn('tone', markers[0])
        self.assertEqual(len(markers), 1 + len(showcase.STATIONS))  # sem o raio de 5 km
        self.assertTrue(all(marker['tone'] == 'demo' for marker in markers[1:]))
        self.assertIn('Sem pontos livres', texts(screen))  # como qualquer posto sem vaga, com a tarifa normal
        self.assertIn('R$ 1,49/kWh', texts(screen))  # menor tarifa do posto, como nos reais
        assert_no_demo_wording(self, screen)
        found = 1 + len(showcase.STATIONS)
        self.assertIn(f'{found} postos nesta página · {found} encontrados', texts(screen))
        self.assertNotIn('Mais postos', texts(screen))  # a paginação continua a da API
        await app.poll()
        self.assertEqual(len(viewport(screen).markers), found)
        for call in app.api.request.await_args_list:
            self.assertNotIn(showcase.PREFIX, repr(call))

    async def test_initial_camera_frames_the_real_station(self):
        app = app_with(True)
        app.api.request.side_effect = station_responses({'items': [REAL], 'total': 1})
        screen = await stations.build(app)
        camera = viewport(screen).on_camera.__self__
        self.assertAlmostEqual(camera.center[1], REAL['longitude'], places=3)

    async def test_demo_detail_is_local_and_offers_no_reservation_or_charge(self):
        app = app_with(True)
        demo_id = showcase.STATIONS[0]['id']
        with patch.object(stations, 'station_map_widget', new=AsyncMock(return_value=ft.Text('Map'))):
            screen = await stations.build(app, station_id=demo_id)
            await app.poll()
        app.api.request.assert_not_awaited()
        shown = texts(screen)
        self.assertIn(showcase.STATIONS[0]['name'], shown)
        self.assertIn(showcase.NOTICE, shown)
        self.assertIn(showcase.GROUP_NOTE, shown)
        self.assertNotIn('Reservar estação', shown)
        self.assertNotIn('Carregar agora', shown)
        self.assertEqual(showcase.NOTICE, 'Indisponível no momento. Este posto não aceita reservas nem recargas agora.')
        assert_no_demo_wording(self, screen)
        app.go.assert_not_awaited()

    async def test_real_detail_still_offers_reservation(self):
        app = app_with(True)
        app.api.request.return_value = REAL
        with patch.object(stations, 'station_map_widget', new=AsyncMock(return_value=ft.Text('Map'))):
            screen = await stations.build(app, station_id=REAL['id'])
        self.assertIn('Reservar estação', texts(screen))
        self.assertNotIn(showcase.NOTICE, texts(screen))


if __name__ == '__main__':
    unittest.main()
