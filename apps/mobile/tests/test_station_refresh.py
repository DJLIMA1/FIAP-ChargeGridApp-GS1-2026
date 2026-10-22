import unittest
from unittest.mock import AsyncMock, Mock, patch

import flet as ft
from chargegrid_map import VectorMap
from test_station_ux import open_station

from chargegrid_app.api_client import ApiError
from chargegrid_app.screens import stations
from test_behavior import HandlerApp, descendants, station_responses


def camera(screen):
    return next(item.on_camera.__self__ for item in descendants(screen)
                if isinstance(item, VectorMap))


class StationRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_page_after_catalog_shrinks_points_back_to_previous_page(self):
        app = HandlerApp()
        station = {'id': 's', 'name': 'Posto', 'address': 'Rua', 'latitude': 0,
                   'longitude': 0, 'connectors': []}
        app.api.request.side_effect = station_responses(
            {'items': [station], 'total': 21},
            {'items': [], 'total': 19},
        )
        with patch.object(stations, 'station_map_widget', new=AsyncMock(return_value=ft.Text('Map'))):
            screen = await stations.build(app, offset=20)
            await app.poll()
        self.assertIn('Anterior', [c.content.value for c in descendants(screen)
                                   if isinstance(c, ft.TextButton) and isinstance(c.content, ft.Text)])
        messages = [c.value for c in descendants(screen) if isinstance(c, ft.Text)]
        self.assertIn('Nenhum posto nesta página. Volte para a página anterior.', messages)
        self.assertNotIn('Nenhum posto encontrado para esta busca.', messages)

    async def test_callout_refreshes_name_and_tariff_and_its_action_keeps_station_identity(self):
        app = HandlerApp()
        point = {'id':'p','public_code':'CG-01','connector_type':'Tipo 2','power_kw':'7.2',
                 'price_per_kwh':'2','max_duration_minutes':60,'available':True,'online':True}
        station = {'id':'s','name':'Posto','address':'Rua','latitude':-23.5,'longitude':-46.6,'connectors':[point]}
        app.api.request.return_value = {'items':[station],'total':1}
        with patch.object(stations,'station_map_widget',new=AsyncMock(return_value=ft.Text('Map'))) as render:
            screen = await stations.build(app)
            viewer = camera(screen)
            await open_station(screen, 'Posto')(None)
            selected_center = viewer.center
            field = next(item for item in descendants(screen) if isinstance(item,ft.TextField))
            field.value = 'Busca em edição'
            station['name'] = 'Posto renomeado'
            point['price_per_kwh'] = '1.95'
            await app.poll()
            self.assertIs(camera(screen), viewer)
            self.assertEqual(viewer.records[0]['name'],'Posto renomeado')
            self.assertEqual(viewer.records[0]['price'],1.95)
            self.assertEqual(viewer.center, selected_center)
            await open_station(screen, 'Ver estação')(None)
            app.go.assert_awaited_once_with('stations',station_id='s')
            self.assertEqual(field.value,'Busca em edição')
            await app.poll()
            render.assert_not_awaited()  # Polling updates pins, never a static preview.

    async def test_map_tracks_availability_and_appearance_without_rebuilding_form(self):
        app = HandlerApp()
        app.page.update = Mock()
        point = {'id': 'p', 'public_code': 'CG-01', 'connector_type': 'Tipo 2',
                 'power_kw': '1', 'price_per_kwh': '2', 'max_duration_minutes': 60, 'available': True}
        station = {'id': 's', 'name': 'Posto', 'address': 'Rua', 'latitude': -23.5,
                   'longitude': -46.6, 'connectors': [point]}
        state = {'items': [], 'total': 0}

        async def request(*args, **kwargs):
            return state

        app.api.request.side_effect = request
        with patch.object(stations, 'station_map_widget', new=AsyncMock(side_effect=lambda *a, **k: ft.Text('Map'))) as render:
            screen = await stations.build(app)
            viewer = camera(screen)
            fields = [c for c in descendants(screen) if isinstance(c, ft.TextField)]
            fields[0].value = 'Endereço em edição'
            state = {'items': [station], 'total': 1}
            await app.poll()
            self.assertEqual(viewer.records[0]['free_points'],1)
            self.assertEqual(viewer.records[0]['price'],2)
            self.assertIs(camera(screen), viewer)
            state = {'items': [{**station, 'connectors': [{**point, 'available': False}]}], 'total': 1}
            await app.poll()
            self.assertEqual(viewer.records[0]['free_points'],0)
            self.assertIsNone(viewer.records[0]['price'])
            self.assertEqual(fields[0].value, 'Endereço em edição')
            self.assertIs(fields[0], next(c for c in descendants(screen) if isinstance(c, ft.TextField)))
            state = {'items': [], 'total': 0}
            await app.poll()
            self.assertEqual(viewer.records, [])
            self.assertNotIn('Map', [c.value for c in descendants(screen) if isinstance(c, ft.Text)])
            await app.poll()
            render.assert_not_awaited()

    async def test_typed_address_search_failures_are_actionable_and_do_not_navigate(self):
        cases = [(AsyncMock(return_value=None), 'Endereço não encontrado'),
                 (AsyncMock(side_effect=OSError('offline')), 'Não foi possível localizar o endereço')]
        for geocode, message in cases:
            with self.subTest(message=message):
                app = HandlerApp()
                app.api.request.return_value = {'items': [], 'total': 0}
                screen = await stations.build(app)
                field = next(c for c in descendants(screen) if isinstance(c, ft.TextField))
                field.value = 'Rua sem posto'
                with patch.object(stations, 'geocode_address', new=geocode), \
                        self.assertRaisesRegex(ApiError, message):
                    await field.on_submit(None)
                app.go.assert_not_awaited()

    async def test_typed_text_matching_a_listed_station_only_filters_locally(self):
        app = HandlerApp()
        station = {'id': 's', 'name': 'Posto Central', 'address': 'Rua', 'latitude': 0, 'longitude': 0, 'connectors': []}
        app.api.request.return_value = {'items': [station], 'total': 1}
        with patch.object(stations, 'station_map_widget', new=AsyncMock(return_value=ft.Text('Map'))):
            screen = await stations.build(app)
            field = next(c for c in descendants(screen) if isinstance(c, ft.TextField))
            field.value = 'central'
            await field.on_change(None)
            with patch.object(stations, 'geocode_address', new=AsyncMock(side_effect=AssertionError('geocoder'))):
                await field.on_submit(None)
        self.assertIn('Resultados Encontrados', [c.value for c in descendants(screen) if isinstance(c, ft.Text)])
        app.go.assert_not_awaited()
