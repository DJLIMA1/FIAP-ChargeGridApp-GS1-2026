import unittest
from unittest.mock import AsyncMock, Mock, patch

import flet as ft

from chargegrid_app.api_client import ApiError
from chargegrid_app.screens import stations
from test_behavior import HandlerApp, click, descendants


class StationRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_callout_refreshes_name_and_tariff_and_its_action_keeps_station_identity(self):
        app = HandlerApp()
        point = {'id':'p','public_code':'CG-01','connector_type':'Tipo 2','power_kw':'7.2',
                 'price_per_kwh':'2','max_duration_minutes':60,'available':True,'online':True}
        station = {'id':'s','name':'Posto','address':'Rua','latitude':-23.5,'longitude':-46.6,'connectors':[point]}
        app.api.request.return_value = {'items':[station],'total':1}
        with patch.object(stations,'station_map_widget',new=AsyncMock(return_value=ft.Text('Map'))) as render:
            screen = await stations.build(app)
            field = next(item for item in descendants(screen) if isinstance(item,ft.TextField))
            field.value = 'Busca em edição'
            station['name'] = 'Posto renomeado'
            point['price_per_kwh'] = '1.95'
            await app.poll()
            self.assertEqual(render.await_count,2)
            self.assertEqual(render.call_args.args[0][0]['name'],'Posto renomeado')
            self.assertEqual(render.call_args.args[0][0]['price'],1.95)
            await render.call_args.args[1]('s')(None)
            app.go.assert_awaited_once_with('stations',station_id='s')
            self.assertEqual(field.value,'Busca em edição')
            await app.poll()
            self.assertEqual(render.await_count,2)

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
            fields = [c for c in descendants(screen) if isinstance(c, ft.TextField)]
            fields[0].value = 'Endereço em edição'
            state = {'items': [station], 'total': 1}
            await app.poll()
            self.assertEqual(render.await_count,1)
            self.assertEqual(render.call_args.args[0][0]['free_points'],1)
            self.assertEqual(render.call_args.args[0][0]['price'],2)
            self.assertEqual(render.call_args.kwargs,dict(offline=False,width=360,reference=None))
            state = {'items': [{**station, 'connectors': [{**point, 'available': False}]}], 'total': 1}
            await app.poll()
            self.assertEqual(render.call_args.args[0][0]['free_points'],0)
            self.assertIsNone(render.call_args.args[0][0]['price'])
            self.assertEqual(fields[0].value, 'Endereço em edição')
            self.assertIs(fields[0], next(c for c in descendants(screen) if isinstance(c, ft.TextField)))
            state = {'items': [], 'total': 0}
            await app.poll()
            self.assertNotIn('Map', [c.value for c in descendants(screen) if isinstance(c, ft.Text)])
            await app.poll()
            self.assertEqual(render.await_count, 2)

    async def test_search_invalid_numbers_have_actionable_validation(self):
        for latitude, longitude, radius in [('abc', '0', '5'), ('0', '0', ''), ('0', '0', 'abc')]:
            with self.subTest(latitude=latitude, radius=radius):
                app = HandlerApp()
                app.api.request.return_value = {'items': [], 'total': 0}
                screen = await stations.build(app)
                search_mode = next(c for c in descendants(screen) if isinstance(c,ft.Dropdown))
                search_mode.value = 'coordinates'
                await search_mode.on_select(None)
                fields = {c.label: c for c in descendants(screen) if isinstance(c, ft.TextField)}
                fields['Latitude'].value, fields['Longitude'].value = latitude, longitude
                fields['Raio (km)'].value = radius
                with self.assertRaises(ApiError):
                    await click(screen, 'Buscar')(None)
                app.go.assert_not_awaited()
