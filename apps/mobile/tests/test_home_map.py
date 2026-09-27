import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import flet as ft
from PIL import Image

from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DemoApi
from chargegrid_app.screens import home
from chargegrid_app.services import maps
from test_behavior import HandlerApp, descendants
from test_consumer_flows import texts


def mapped_station(**changes):
    return {'id':'point-station','name':'Posto no mapa','latitude':-23.5505,'longitude':-46.6333,
            'free_points':2,'price':1.95,'status':'Disponível',**changes}


class HomeMapTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_geographic_maps_share_shell_and_compact_visible_licence_link(self):
        with patch.object(maps,'build_map_png',return_value=b'fixture-png') as render:
            home_map = await maps.station_map_widget([mapped_station()],Mock(),width=560)
            generic_map = await maps.map_widget(-23.5505,-46.6333,[],width=560)
        for screen in (home_map,generic_map):
            with self.subTest(screen=type(screen)):
                frame = next(item for item in descendants(screen) if isinstance(item,ft.Container)
                             and item.border_radius == 18 and isinstance(item.content,ft.Stack))
                credit = next(item for item in descendants(frame) if isinstance(item,ft.Container) and item.url)
                self.assertEqual(frame.height,560/maps.STATION_MAP_RATIO)
                self.assertEqual(credit.url,'https://www.openstreetmap.org/copyright')
                self.assertEqual(credit.content.value,'© OpenStreetMap')
                self.assertGreaterEqual(credit.content.size,11)
                self.assertEqual(credit.right,8)
                self.assertIsNone(credit.left)
                self.assertIsNone(credit.width)
        self.assertFalse(render.call_args.kwargs['dark'])

    async def test_demo_home_uses_bundled_geography_without_network_or_gps(self):
        app = HandlerApp()
        app.api = DemoApi()
        await app.api.login(DEMO_EMAIL, DEMO_PASSWORD)
        app.profile = await app.api.request('GET','me')
        with patch.object(maps,'_fetch_bytes',side_effect=AssertionError('network')), \
                patch.object(maps,'build_map_png',side_effect=AssertionError('tiles')):
            screen = await home.build(app)
            await app.poll()
        image = next(item for item in descendants(screen) if isinstance(item,ft.Image))
        self.assertEqual(image.src,'maps/demo-centro.png')
        self.assertIn('© OpenStreetMap',texts(screen))
        self.assertIn('1 vaga',texts(screen))
        self.assertNotRegex(texts(screen).lower(),r'estações próximas|\bkm\b|20%|22h')

    async def test_real_map_is_light_cartography_and_callout_opens_selected_station(self):
        go = AsyncMock()
        def select(station_id):
            async def callback(event=None):
                await go(station_id)
            return callback
        with patch.object(maps,'build_map_png',return_value=b'fixture-png') as draw:
            screen = await maps.station_map_widget([mapped_station()],select)
        draw.assert_called_once()
        self.assertEqual(draw.call_args.args[2],[(-23.5505,-46.6333,'⚡')])
        self.assertEqual(draw.call_args.kwargs,dict(width=720,height=497,zoom=16,center_glyph=None,dark=False,
                                                   selected_marker=(-23.5505,-46.6333)))
        marker_x,marker_y = maps._lonlat_to_px(-23.5505,-46.6333,16)
        center_x,center_y = maps._lonlat_to_px(*draw.call_args.args[:2],16)
        self.assertAlmostEqual(marker_y-center_y+497/2,497*0.43,places=5)
        self.assertAlmostEqual(marker_x-center_x+720/2,720*0.4,places=5)
        self.assertIn('2 vagas',texts(screen))
        self.assertIn('Desde R$ 1,95/kWh',texts(screen))
        callout = next(item for item in descendants(screen) if isinstance(item,ft.Container) and item.on_click)
        self.assertTrue(callout.content.button)
        self.assertEqual(callout.content.label,'Ver pontos em Posto no mapa')
        await callout.on_click(None)
        go.assert_awaited_once_with('point-station')

    async def test_reference_proportions_and_side_callout_resize_without_new_download(self):
        with patch.object(maps,'build_map_png',return_value=b'fixture-png') as draw:
            screen = await maps.station_map_widget([mapped_station()],Mock(),width=320)
            callout = next(item for item in descendants(screen) if isinstance(item,ft.Container) and item.on_click)
            self.assertAlmostEqual(screen.height,320*389/563)
            self.assertAlmostEqual(callout.left,320*.455)
            self.assertAlmostEqual(callout.top,screen.height*.367)
            self.assertIsNone(callout.bottom)
            self.assertIsNotNone(callout.shadow)
            with patch.object(screen,'update') as update:
                await screen.on_size_change(SimpleNamespace(width=560))
                await screen.on_size_change(SimpleNamespace(width=560))
                update.assert_called_once()
            self.assertAlmostEqual(screen.height,560*389/563)
            self.assertAlmostEqual(callout.width,560*.295)
            self.assertLess(callout.left+callout.width,560)
            draw.assert_called_once()

    async def test_availability_badge_is_blue_only_when_points_are_available(self):
        for count,color in ((2,'#D5E6FF'),(0,'#E7EBEF')):
            with self.subTest(count=count),patch.object(maps,'build_map_png',return_value=b'fixture-png'):
                screen = await maps.station_map_widget([mapped_station(free_points=count,status='Offline')],Mock())
                badge = next(item for item in descendants(screen) if isinstance(item,ft.Container) and item.bgcolor == color)
                self.assertEqual(badge.content.value,'2 vagas' if count else 'Offline')

    async def test_no_coordinates_never_draws_fake_map_or_uses_gps(self):
        for items in ([],[mapped_station(latitude='NaN')],[mapped_station(longitude=181)],
                      [mapped_station(latitude=None)]):
            with self.subTest(items=items), patch.object(maps,'build_map_png') as draw:
                screen = await maps.station_map_widget(items,Mock())
                draw.assert_not_called()
                self.assertFalse(any(isinstance(item,ft.Image) for item in descendants(screen)))
                self.assertNotIn('A partir de',texts(screen))

    async def test_demo_different_coordinate_never_reuses_fixed_geographic_marker(self):
        with patch.object(maps,'build_map_png',side_effect=AssertionError('network')):
            screen = await maps.station_map_widget([mapped_station(latitude=-23.59)],Mock(),offline=True)
        self.assertFalse(any(isinstance(item,ft.Image) for item in descendants(screen)))
        self.assertIn('Mapa esquemático da demonstração',texts(screen))

    async def test_unavailable_station_has_no_fake_free_slots_or_price(self):
        with patch.object(maps,'build_map_png',return_value=b'fixture-png'):
            screen = await maps.station_map_widget([mapped_station(free_points=0,status='Offline',price=None)],Mock())
        self.assertIn('Offline',texts(screen))
        self.assertNotIn('pontos livres',texts(screen))
        self.assertNotIn('/kWh',texts(screen))

    async def test_demo_unavailable_station_does_not_reuse_available_pin_asset(self):
        with patch.object(maps,'build_map_png',side_effect=AssertionError('network')):
            screen = await maps.station_map_widget([mapped_station(free_points=0,status='Offline',price=None)],Mock(),offline=True)
        self.assertFalse(any(isinstance(item,ft.Image) for item in descendants(screen)))
        self.assertIn('Offline',texts(screen))

    async def test_search_reference_keeps_explicit_coordinate_identity(self):
        reference = (-23.551,-46.634)
        with patch.object(maps,'build_map_png',return_value=b'fixture-png') as render:
            await maps.station_map_widget([mapped_station()],Mock(),reference=reference)
        self.assertIn((*reference,'🚗'),render.call_args.args[2])
        self.assertEqual(render.call_args.kwargs['selected_marker'],(-23.5505,-46.6333))

    async def test_online_failure_is_explicit_and_keeps_selected_station(self):
        with patch.object(maps,'build_map_png',side_effect=OSError('offline')):
            screen = await maps.station_map_widget([mapped_station()],Mock())
        self.assertIn('mapa online indisponível',texts(screen))
        self.assertIn('Posto no mapa',texts(screen))
        self.assertFalse(any(isinstance(item,ft.Image) for item in descendants(screen)))


class TileRenderingTests(unittest.TestCase):
    def test_tiles_are_cached_across_memory_cache_resets(self):
        with tempfile.TemporaryDirectory(prefix='chargegrid-map-test-') as folder, \
                patch.object(maps,'_TILE_CACHE_DIR',Path(folder)), \
                patch.object(maps,'_fetch_bytes',return_value=b'cached-viewport') as fetch:
            maps._tile_bytes.cache_clear()
            first = maps._tile_bytes(15,12,13)
            maps._tile_bytes.cache_clear()
            second = maps._tile_bytes(15,12,13)
            self.assertEqual(first,second)
            fetch.assert_called_once()
        maps._tile_bytes.cache_clear()

    def test_actual_raster_pipeline_renders_markers_without_downloading_other_areas(self):
        buffer = io.BytesIO()
        Image.new('RGB',(256,256),'#eef1e8').save(buffer,format='PNG')
        with patch.object(maps,'_tile_bytes',return_value=buffer.getvalue()) as tiles:
            rendered = maps.build_map_png(-23.5505,-46.6333,[(-23.5505,-46.6333,'⚡')],
                                         width=640,height=488,zoom=16,center_glyph=None,dark=False)
        self.assertEqual(Image.open(io.BytesIO(rendered)).size,(640,488))
        self.assertLessEqual(tiles.call_count,12)
        self.assertTrue(all(call.args[0] == 16 for call in tiles.call_args_list))
