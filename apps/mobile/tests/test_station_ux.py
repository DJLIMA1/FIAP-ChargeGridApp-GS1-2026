"""Posto selection precedes point actions; rotating codes are read on site."""
import unittest
from copy import deepcopy
from unittest.mock import AsyncMock, Mock, patch

import flet as ft

from chargegrid_app.screens import stations
from test_behavior import HandlerApp, click, descendants
from test_consumer_flows import CONTEXT, POINT, STATION, texts


class StationUxTests(unittest.IsolatedAsyncioTestCase):
    async def test_listing_only_offers_point_selection_without_starting_or_reserving(self):
        app = HandlerApp()
        app.api.request.return_value = {'items':[STATION], 'total':1}
        with patch.object(stations, 'station_map_widget', new=AsyncMock(return_value=ft.Text('Map'))):
            screen = await stations.build(app)
        visible = texts(screen)
        self.assertNotIn('Tenho o código', visible)
        self.assertNotIn('Já estou aqui: iniciar', visible)
        self.assertNotIn('Reservar para chegar', visible)
        self.assertNotIn('Ver cupons deste posto', visible)
        self.assertIn('1 ponto livre', visible)
        self.assertIn('1 posto nesta página · 1 encontrado', visible)
        await click(screen, 'Ver pontos')(None)
        app.go.assert_awaited_once_with('stations', station_id=STATION['id'])
        self.assertTrue(all(call.args[0] == 'GET' for call in app.api.request.call_args_list))

    async def test_detail_has_one_heading_local_code_instruction_and_distinct_actions(self):
        app = HandlerApp()
        app.api.request.return_value = STATION
        with patch.object(stations, 'station_map_widget', new=AsyncMock(return_value=ft.Text('Map'))) as render:
            screen = await stations.build(app, station_id=STATION['id'])
        render.assert_not_awaited()
        self.assertNotIn('Ver mapa dos postos',texts(screen))
        self.assertNotIn('Postos no mapa',texts(screen))
        values = [item.value for item in descendants(screen) if isinstance(item, ft.Text)]
        self.assertEqual(values.count(STATION['name']), 1)
        self.assertEqual(values.count(STATION['address']), 1)
        self.assertNotIn('Tenho o código', texts(screen))
        self.assertIn('Leia o código #F atual na tela do equipamento', texts(screen))
        self.assertIn('muda periodicamente', texts(screen))
        self.assertNotIn('Buscar perto de um endereço', texts(screen))
        self.assertIn('Pontos de recarga', values)
        self.assertIn(f"{float(POINT['power_kw']):g} kW".replace('.', ','), texts(screen))
        await click(screen, 'Já estou aqui: iniciar')(None)
        app.go.assert_awaited_once_with('charging', public_code=POINT['public_code'],
                                       max_duration=min(30, POINT['max_duration_minutes']), point_context=CONTEXT)
        self.assertTrue(all(call.args[0] == 'GET' for call in app.api.request.call_args_list))

    async def test_detail_keeps_reservation_for_the_selected_point(self):
        app = HandlerApp()
        app.api.request.return_value = STATION
        with patch.object(stations, 'station_map_widget', new=AsyncMock(return_value=ft.Text('Map'))):
            screen = await stations.build(app, station_id=STATION['id'])
        await click(screen, 'Reservar para chegar')(None)
        app.api.request.assert_awaited_with('POST', 'reservations', {'connector_id':POINT['id']}, key='intent')
        app.go.assert_awaited_once_with('reservations')

    async def test_poll_detects_in_place_changes_and_preserves_open_search(self):
        app = HandlerApp()
        app.page.update = Mock()
        state = {'items':[deepcopy(STATION)], 'total':1}
        app.api.request.return_value = state
        with patch.object(stations, 'station_map_widget', new=AsyncMock(return_value=ft.Text('Map'))):
            screen = await stations.build(app)
            search = next(item for item in descendants(screen) if isinstance(item, ft.ExpansionTile)
                          and item.title.value == 'Buscar perto de um endereço')
            search.expanded = True
            address = next(item for item in descendants(screen) if isinstance(item, ft.TextField)
                           and item.label == 'Endereço para buscar')
            address.value = 'Meu endereço em edição'
            await app.poll()
            app.page.update.assert_not_called()
            state['items'][0]['connectors'][0]['online'] = False
            await app.poll()
            self.assertIn('0 pontos livres', texts(screen))
            self.assertTrue(search.expanded)
            self.assertEqual(address.value, 'Meu endereço em edição')
            app.page.update.assert_called_once_with()

    async def test_explicit_negative_availability_never_offers_start_or_reserve(self):
        for changes in ({'active':False}, {'online':False}, {'retired':True},
                        {'availability_status':'fault'}, {'available':False}):
            with self.subTest(changes=changes):
                app = HandlerApp()
                app.api.request.return_value = {**STATION, 'connectors':[{**POINT, **changes}]}
                with patch.object(stations, 'station_map_widget', new=AsyncMock(return_value=ft.Text('Map'))):
                    screen = await stations.build(app, station_id=STATION['id'])
                self.assertNotIn('Já estou aqui: iniciar', texts(screen))
                self.assertNotIn('Reservar para chegar', texts(screen))

    async def test_disabled_station_and_empty_points_remain_informative(self):
        for data, label in (({**STATION, 'active':False}, 'Posto desativado'),
                            ({**STATION, 'connectors':[]}, 'Sem pontos cadastrados')):
            with self.subTest(label=label):
                app = HandlerApp()
                app.api.request.return_value = {'items':[data], 'total':1}
                with patch.object(stations, 'station_map_widget', new=AsyncMock(return_value=ft.Text('Map'))):
                    screen = await stations.build(app)
                self.assertIn(label, texts(screen))
                await click(screen, 'Ver pontos')(None)
                app.go.assert_awaited_once_with('stations', station_id=STATION['id'])
