"""Vector viewport identity, geographic camera, selection and polling contracts."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from chargegrid_map import VectorMap
from test_consumer_flows import STATION, texts
from test_station_ux import open_station

from chargegrid_app.screens import stations
from chargegrid_app.services import maps
from chargegrid_app.ui.explorer_map import ExplorerMap, coordinates, unproject
from test_behavior import HandlerApp, descendants


def record(**changes):
    return {**STATION, 'free_points': 1, 'price': 2, 'status': 'Disponível', **changes}


def camera(screen):
    return next(item.on_camera.__self__ for item in descendants(screen) if isinstance(item, VectorMap))


class GeographicCameraTests(unittest.TestCase):
    def test_projection_round_trip_wraps_at_antimeridian(self):
        for point in ((-23.55, -46.63), (0, 179.99), (0, -179.99), (80, 0)):
            self.assertAlmostEqual(unproject(*maps._lonlat_to_px(*point, 14), 14)[0], point[0])
            self.assertAlmostEqual(unproject(*maps._lonlat_to_px(*point, 14), 14)[1], point[1])

    def test_invalid_coordinates_never_become_pins(self):
        for values in ({'latitude': 'NaN'}, {'longitude': 181}, {'latitude': None}, {'latitude': 90}):
            self.assertIsNone(coordinates(record(**values)))


class ExplorerMapTests(unittest.IsolatedAsyncioTestCase):
    async def test_initial_layout_uses_vector_map_without_composing_images(self):
        engine = ExplorerMap(HandlerApp(), [record()], Mock())
        with patch.object(maps, 'build_map_png', side_effect=AssertionError('raster map')):
            await engine.resize(SimpleNamespace(width=390, height=740))
        self.assertIsInstance(engine.viewport, VectorMap)
        self.assertEqual(engine.viewport.markers[0]['name'], STATION['name'])
        self.assertNotIn('price', engine.viewport.markers[0])
        self.assertEqual(engine.viewport.zoom, engine.zoom - 1)
        self.assertEqual((engine.viewport.latitude, engine.viewport.longitude), engine.center)
        self.assertIn('tiles.openfreemap.org/planet', engine.viewport.style_json)

    async def test_native_gesture_camera_updates_area_search_without_remounting_map(self):
        moved = Mock()
        engine = ExplorerMap(HandlerApp(), [record()], Mock(), on_move=moved)
        viewport, revision = engine.viewport, engine.viewport.camera_revision
        await engine.camera_changed(SimpleNamespace(data=json.dumps({'latitude': -23.56, 'longitude': -46.65, 'zoom': 14.4})))
        self.assertEqual(engine.center, (-23.56, -46.65))
        self.assertEqual(engine.zoom, 15.4)
        self.assertIs(engine.viewport, viewport)
        self.assertEqual(viewport.camera_revision, revision)
        moved.assert_called_once()

    async def test_invalid_or_disposed_camera_events_do_not_move_the_map(self):
        engine = ExplorerMap(HandlerApp(), [record()], Mock())
        center = engine.center
        for data in ('bad json', '{}', '{"latitude":0,"longitude":0,"zoom":"NaN"}',
                     '{"latitude":90,"longitude":0,"zoom":10}'):
            await engine.camera_changed(SimpleNamespace(data=data))
        self.assertEqual(engine.center, center)
        engine.app.closed = True
        await engine.camera_changed(SimpleNamespace(data='{"latitude":0,"longitude":0,"zoom":10}'))
        self.assertEqual(engine.center, center)

    async def test_programmatic_zoom_and_recenter_use_native_camera_revision(self):
        engine = ExplorerMap(HandlerApp(), [record()], Mock())
        initial = engine.viewport.camera_revision
        await engine.zoom_by(1)
        self.assertGreater(engine.viewport.camera_revision, initial)
        self.assertEqual(engine.viewport.zoom, engine.zoom - 1)
        engine.reference = (-23.5, -46.6)
        await engine.recenter()
        self.assertEqual(engine.center, engine.reference)

    async def test_poll_updates_pins_without_resetting_camera_and_new_pins_remain_selectable(self):
        select = Mock(return_value=Mock())
        engine = ExplorerMap(HandlerApp(), [record()], select)
        camera = (engine.center, engine.zoom, engine.viewport.camera_revision)
        engine.set_records([record(id='new-station', name='Novo posto')])
        await engine.viewport.on_select(SimpleNamespace(data='new-station'))
        select.assert_called_once_with('new-station')
        self.assertEqual((engine.center, engine.zoom, engine.viewport.camera_revision), camera)
        engine.set_records([])
        self.assertEqual(engine.viewport.markers, [])

    async def test_disabled_station_status_is_preserved(self):
        item = {**STATION, 'active': False}
        records = stations._map_records([item])
        engine = ExplorerMap(HandlerApp(), records, Mock())
        self.assertEqual(engine.viewport.markers[0]['status'], records[0]['status'])

    async def test_selection_sheet_drag_and_close_keep_map_and_planning_filters(self):
        app = HandlerApp()
        app.api.request.return_value = {'items': [STATION], 'total': 1}
        screen = await stations.build(app, connector_type='type2', planning_intent={'mode': 'time', 'minutes': 30})
        viewer = camera(screen)
        await viewer.viewport.on_select(SimpleNamespace(data='station-one'))
        app.go.assert_not_awaited()
        self.assertIn('Ver estação', texts(screen))
        self.assertIn(STATION['address'], texts(screen))
        sheet = next(item for item in descendants(screen) if getattr(item, 'data', None) == 'station-sheet')
        handle = next(item for item in descendants(screen) if getattr(item, 'data', None) == 'station-sheet-handle')
        original_height = sheet.height
        handle.on_vertical_drag_update(SimpleNamespace(primary_delta=-100))
        self.assertGreater(sheet.height, original_height)
        self.assertEqual(viewer.viewport.credit_bottom, sheet.height + 8)
        anchor_height = sheet.height
        handle.on_vertical_drag_start(SimpleNamespace(global_position=SimpleNamespace(y=400)))
        handle.on_vertical_drag_update(SimpleNamespace(global_position=SimpleNamespace(y=330)))
        self.assertEqual(sheet.height, anchor_height + 70)
        self.assertIs(camera(screen), viewer)
        await open_station(screen, 'Ver estação')(None)
        self.assertEqual(app.go.await_args.kwargs['connector_type'], 'type2')
        self.assertEqual(app.go.await_args.kwargs['planning_intent'], {'mode': 'time', 'minutes': 30})
        close = next(item for item in descendants(screen) if getattr(item, 'tooltip', None) == 'Voltar às estações próximas')
        close.on_click(None)
        self.assertIsNone(viewer.selected)
        self.assertIs(camera(screen), viewer)
