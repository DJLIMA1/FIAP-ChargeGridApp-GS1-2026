import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import flet as ft
from chargegrid_map import VectorMap

from chargegrid_app.services import maps
from chargegrid_app.ui import design, theme
from test_behavior import descendants


def mapped_station(**changes):
    return {'id':'point-station','name':'Posto no mapa','latitude':-23.5505,'longitude':-46.6333,
            'free_points':2,'price':1.95,'status':'Disponível',**changes}


def viewport(screen):
    return next(item for item in descendants(screen) if isinstance(item, VectorMap))


class HomeMapTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.addCleanup(theme.set_dark, theme.is_dark())
        theme.set_dark(False)

    async def test_all_geographic_maps_and_gallery_use_shared_vector_provider(self):
        with patch.object(maps, 'build_map_png', side_effect=AssertionError('raster')):
            screens = [await maps.station_map_widget([mapped_station()], Mock()),
                       await maps.map_widget(-23.55, -46.63, []), design.map_image()]
        for screen in screens:
            with self.subTest(screen=screen):
                data = json.loads(viewport(screen).style_json)
                source = data['sources']['openmaptiles']
                self.assertEqual(source['url'], 'https://tiles.openfreemap.org/planet')
                self.assertIn('OpenStreetMap', source['attribution'])
                self.assertIn('OpenMapTiles', source['attribution'])

    async def test_station_selection_keeps_identity_and_ignores_unrecognized_events(self):
        go = AsyncMock()
        def select(station_id):
            async def callback(event=None):
                await go(station_id)
            return callback
        screen = await maps.station_map_widget([mapped_station()], select)
        control = viewport(screen)
        await control.on_select(SimpleNamespace(data='other-station'))
        go.assert_not_awaited()
        await control.on_select(SimpleNamespace(data='point-station'))
        go.assert_awaited_once_with('point-station')

    async def test_responsive_detail_preserves_camera_and_control_identity(self):
        screen = await maps.station_map_widget([mapped_station()], Mock(), width=360, variant='detail')
        control = viewport(screen)
        screen.update = Mock()
        await screen.on_size_change(SimpleNamespace(width=560))
        self.assertEqual(screen.height, 560 / maps.DETAIL_MAP_RATIO)
        self.assertIs(viewport(screen), control)
        self.assertEqual(control.camera_revision, 0)

    async def test_demo_crops_never_replace_real_coordinates_with_reference_artwork(self):
        for crop in ('marginal', 'villa', None):
            record = mapped_station(latitude=-22.9, longitude=-43.2)
            screen = await maps.station_map_widget([record], Mock(), offline=True, crop=crop, variant='detail')
            control = viewport(screen)
            self.assertEqual((control.latitude, control.longitude), (-22.9, -43.2))
            self.assertFalse(any(isinstance(item, ft.Image) for item in descendants(screen)))

    async def test_reference_camera_does_not_relocate_station_marker(self):
        screen = await maps.station_map_widget([mapped_station()], Mock(), reference=(-23.6, -46.7))
        control = viewport(screen)
        self.assertEqual((control.latitude, control.longitude), (-23.6, -46.7))
        self.assertEqual(control.markers[0]['latitude'], -23.5505)

    async def test_unavailable_station_retains_status_without_a_price_label(self):
        screen = await maps.station_map_widget([mapped_station(free_points=0, price=None, status='Indisponível')], Mock())
        marker = viewport(screen).markers[0]
        self.assertEqual(marker['status'], 'Indisponível')
        self.assertNotIn('price', marker)
        self.assertEqual(marker['name'], 'Posto no mapa')

    async def test_invalid_coordinates_show_explicit_placeholder(self):
        for values in ({'latitude': None}, {'latitude': 'NaN'}, {'longitude': 200}, {'latitude': 90}):
            screen = await maps.station_map_widget([mapped_station(**values)], Mock())
            self.assertFalse(any(isinstance(item, VectorMap) for item in descendants(screen)))
            self.assertIn('coordenadas válidas', screen.content.controls[1].value)
