"""Posto selection precedes point actions; rotating codes are read on site."""
import unittest
from copy import deepcopy
from unittest.mock import AsyncMock, Mock, patch

import flet as ft
from test_consumer_flows import POINT, STATION, texts

from chargegrid_app.screens import stations
from test_behavior import HandlerApp, click, descendants


def search_box(screen):
    return next(item for item in descendants(screen) if isinstance(item, ft.TextField)
                and item.hint_text == 'Buscar por endereço ou estação')


def filter_button(screen):
    return next(item for item in descendants(screen)
                if isinstance(item, ft.Container) and item.data == 'station-filters')


def filter_count(screen):
    return next(item for item in descendants(screen)
                if isinstance(item, ft.Container) and item.data == 'filter-count')


def sheet_app(app=None):
    app = app or HandlerApp()
    app.page.show_dialog = Mock()
    app.page.pop_dialog = Mock()
    return app


def open_filters(app, screen):
    """Tap the filter icon of the search bar and return the bottom sheet it shows."""
    filter_button(screen).on_click(None)
    sheet = app.page.show_dialog.call_args.args[0]
    assert isinstance(sheet, ft.BottomSheet)
    return sheet


def sheet_field(sheet, name):
    return next(item for item in descendants(sheet) if isinstance(item, ft.TextField) and item.data == name)


def open_station(screen, name):
    return next(item.on_click for item in descendants(screen)
                if getattr(item, 'on_click', None)
                and any(isinstance(t, ft.Text) and t.value == name for t in descendants(item)))


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
        self.assertIn(f"{float(POINT['price_per_kwh']):.2f}".replace('.', ','), visible)
        self.assertIn('1 posto nesta página · 1 encontrado', visible)
        await open_station(screen, STATION['name'])(None)
        app.go.assert_not_awaited()
        self.assertIn('Ver estação', texts(screen))
        await open_station(screen, 'Ver estação')(None)
        app.go.assert_awaited_once_with('stations', station_id=STATION['id'])
        self.assertTrue(all(call.args[0] == 'GET' for call in app.api.request.call_args_list))

    async def test_detail_has_one_heading_and_two_distinct_flows_without_repetition(self):
        app = HandlerApp()
        app.api.request.return_value = STATION
        with patch.object(stations, 'station_map_widget', new=AsyncMock(return_value=ft.Text('Map'))) as render:
            screen = await stations.build(app, station_id=STATION['id'])
        render.assert_awaited_once()
        self.assertEqual(render.call_args.kwargs['variant'], 'detail')
        self.assertIn('Conectores', texts(screen))
        await open_station(screen, 'Reservar estação')(None)
        app.go.assert_awaited_once_with('booking', station_id=STATION['id'], step=1, kind='reserve')
        app.go.reset_mock()
        await open_station(screen, 'Carregar agora')(None)
        app.go.assert_awaited_once_with('booking', station_id=STATION['id'], step=1, kind='now')
        self.assertNotIn('Ver mapa dos postos',texts(screen))
        values = [item.value for item in descendants(screen) if isinstance(item, ft.Text)]
        self.assertEqual(values.count(STATION['name']), 1)
        self.assertEqual(values.count(STATION['address']), 1)
        # Sem o aviso do código #F nem a lista "Pontos de recarga" (o assistente já escolhe o conector).
        for removed in ('Leia o código #F', 'Pontos de recarga', 'Já estou aqui: iniciar', 'Reservar para chegar',
                        f"{POINT['public_code']} · "):
            self.assertNotIn(removed, texts(screen))
        self.assertTrue(all(call.args[0] == 'GET' for call in app.api.request.call_args_list))

    async def test_poll_detects_in_place_changes_and_preserves_typed_search(self):
        app = HandlerApp()
        app.page.update = Mock()
        state = {'items':[deepcopy(STATION)], 'total':1}
        app.api.request.return_value = state
        with patch.object(stations, 'station_map_widget', new=AsyncMock(return_value=ft.Text('Map'))):
            screen = await stations.build(app)
            search = search_box(screen)
            search.value = 'Meu endereço em edição'
            await app.poll()
            app.page.update.assert_not_called()
            state['items'][0]['connectors'][0]['online'] = False
            await app.poll()
            self.assertIn('Sem pontos livres', texts(screen))
            self.assertIs(search_box(screen), search)
            self.assertEqual(search.value, 'Meu endereço em edição')
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
                await open_station(screen, STATION['name'])(None)
                await open_station(screen, 'Ver estação')(None)
                app.go.assert_awaited_once_with('stations', station_id=STATION['id'])


class StationFilterSheetTests(unittest.IsolatedAsyncioTestCase):
    async def build(self, app, **params):
        with patch.object(stations, 'station_map_widget', new=AsyncMock(return_value=ft.Text('Map'))):
            return await stations.build(app, **params)

    async def test_list_keeps_only_search_bar_map_and_rows(self):
        app = sheet_app()
        app.api.request.return_value = {'items':[STATION], 'total':1}
        screen = await self.build(app)
        visible = texts(screen)
        for removed in ('Buscar perto de um endereço', 'Busca inteligente', 'Buscar com IA',
                        'Comparar por conector, preço e tempo', 'Aplicar comparação',
                        'Salvar busca neste dispositivo', 'Usar busca salva', 'Comparação:'):
            self.assertNotIn(removed, visible)
        self.assertFalse(any(isinstance(item, (ft.ExpansionTile, ft.Dropdown, ft.Checkbox, ft.Switch))
                             for item in descendants(screen)))
        self.assertEqual([item for item in descendants(screen) if isinstance(item, ft.TextField)], [search_box(screen)])
        self.assertIn('Perto de Você', visible)
        self.assertFalse(filter_count(screen).visible)
        app.page.show_dialog.assert_not_called()

    async def test_filter_sheet_applies_every_filter_and_keeps_the_address_search(self):
        app = sheet_app()
        app.api.request.return_value = {'items':[STATION], 'total':1}
        screen = await self.build(app, lat=-23.5, lng=-46.6, query='Praça')
        sheet = open_filters(app, screen)
        self.assertIn('Filtros', texts(sheet))
        await click(sheet, 'CCS2')(None)
        switch = next(item for item in descendants(sheet) if isinstance(item, ft.Switch))
        switch.value = True
        await switch.on_change(None)
        sheet_field(sheet, 'max_price_per_kwh').value = '2,5'
        await click(sheet, 'Menor tarifa')(None)
        self.assertNotIn('Tempo disponível (min)', texts(sheet))
        await click(sheet, 'Por tempo')(None)
        self.assertIn('Tempo disponível (min)', texts(sheet))
        sheet_field(sheet, 'plan_value').value = '30'
        await open_station(sheet, 'Aplicar filtros')(None)
        app.page.pop_dialog.assert_called_once_with()
        app.go.assert_awaited_once_with('stations', lat=-23.5, lng=-46.6, query='Praça', connector_type='ccs2',
                                        available_only=True, max_price_per_kwh='2.5', sort='price',
                                        planning_intent={'mode':'time', 'minutes':30})

    async def test_active_filters_show_count_badge_and_prefill_the_sheet(self):
        app = sheet_app()
        app.api.request.return_value = {'items':[STATION], 'total':1}
        plan = {'mode':'value', 'max_cost':'8'}
        screen = await self.build(app, connector_type='type2', max_price_per_kwh='2', planning_intent=plan)
        badge = filter_count(screen)
        self.assertTrue(badge.visible)
        self.assertEqual(badge.content.value, '3')
        self.assertEqual(filter_button(screen).tooltip, 'Filtros (3 ativos)')
        # The per-row estimate of the plan stays on the list.
        self.assertIn('\n', next(item.value for item in descendants(screen)
                                 if isinstance(item, ft.Text) and str(item.value).startswith('Rua Central')))
        sheet = open_filters(app, screen)
        self.assertIn('Ativos: Tipo 2 · até R$ 2,00/kWh · até R$ 8,00', texts(sheet))
        self.assertEqual(sheet_field(sheet, 'max_price_per_kwh').value, '2')
        self.assertEqual(sheet_field(sheet, 'plan_value').value, '8')
        self.assertIn('Orçamento máximo (R$)', texts(sheet))
        selected = next(item for item in descendants(sheet) if isinstance(item, ft.Container)
                        and isinstance(item.content, ft.Text) and item.content.value == 'Tipo 2')
        self.assertEqual(selected.content.font_family, 'InterBold')
        await open_station(sheet, 'Limpar')(None)
        app.page.pop_dialog.assert_called_once_with()
        app.go.assert_awaited_once_with('stations')

    async def test_sheet_errors_are_inline_and_never_navigate(self):
        app = sheet_app()
        app.api.request.return_value = {'items':[], 'total':0}
        screen = await self.build(app)
        sheet = open_filters(app, screen)
        sheet_field(sheet, 'max_price_per_kwh').value = 'abc'
        await open_station(sheet, 'Aplicar filtros')(None)
        self.assertIn('Informe uma tarifa máxima', texts(sheet))
        sheet_field(sheet, 'max_price_per_kwh').value = ''
        await click(sheet, 'Mais perto')(None)
        await open_station(sheet, 'Aplicar filtros')(None)
        self.assertIn('Busque um endereço na barra de busca', texts(sheet))
        app.go.assert_not_awaited()
        app.page.pop_dialog.assert_not_called()

    async def test_capture_param_opens_sheet_and_typed_address_keeps_filters(self):
        app = sheet_app()
        app.api.request.return_value = {'items':[], 'total':0}
        screen = await self.build(app, connector_type='type2', filters_open=True)
        self.assertIsInstance(app.page.show_dialog.call_args.args[0], ft.BottomSheet)
        search_box(screen).value = 'Rua Nova, 10'
        with patch.object(stations, 'geocode_address', new=AsyncMock(return_value=(-23.4, -46.5))):
            await search_box(screen).on_submit(None)
        app.go.assert_awaited_once_with('stations', lat=-23.4, lng=-46.5, radius=5.0, query='Rua Nova, 10',
                                        connector_type='type2')

    async def test_address_search_chip_clears_location_but_not_filters(self):
        app = sheet_app()
        app.api.request.return_value = {'items':[], 'total':0}
        screen = await self.build(app, lat=-23.5, lng=-46.6, query='Praça', connector_type='type2')
        self.assertIn('Perto de Praça · 5 km', texts(screen))
        await next(item.on_click for item in descendants(screen) if getattr(item, 'tooltip', None) == 'Limpar endereço')(None)
        app.go.assert_awaited_once_with('stations', connector_type='type2')
