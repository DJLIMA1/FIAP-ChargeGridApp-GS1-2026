"""Aba Recarga do motorista: abre direto a busca de estações; a lista "Minhas recargas" foi removida."""

import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import flet as ft

from chargegrid_app import navigation
from chargegrid_app.navigation import (
    SCREENS,
    active_tab,
    parent_route,
    resolve_route,
    tab_entries,
)
from chargegrid_app.screens import chat, reservations, stations
from chargegrid_app.ui import design
from test_behavior import HandlerApp

STATION = {'id': 'st', 'name': 'Posto Centro', 'address': 'Rua A, 10, Pinheiros, São Paulo - SP',
           'latitude': -23.5, 'longitude': -46.6,
           'connectors': [{'id': 'p', 'public_code': 'CG-01', 'connector_type': 'type2', 'power_kw': '7.2',
                           'price_per_kwh': '2', 'max_duration_minutes': 60, 'available': True, 'online': True}]}
SESSION = {'id': 'ses', 'status': 'charging', 'station_name': 'Posto Centro',
           'station_address': 'Rua A, 10, Pinheiros, São Paulo - SP', 'started_at': '2026-10-20T12:00:00Z'}
RESERVATION = {'id': 'res', 'status': 'confirmed', 'station_name': 'Posto Norte',
               'station_address': 'Av. B, 20, Santana, São Paulo - SP', 'expires_at': '2026-10-20T12:15:00Z'}


def walk(control, visible_only=True):
    if visible_only and getattr(control, 'visible', True) is False:
        return
    yield control
    content = getattr(control, 'content', None)
    if content is not None and not isinstance(content, str):
        yield from walk(content, visible_only)
    for child in getattr(control, 'controls', None) or []:
        yield from walk(child, visible_only)


def texts(control):
    return [str(item.value) for item in walk(control) if isinstance(item, ft.Text)]


def by_data(control, data):
    return [item for item in walk(control) if getattr(item, 'data', None) == data]


def app_with(reservation=None, session=None, mode='consumer'):
    app = HandlerApp()
    app.browsing_mode = mode
    state = {'reservations/current': reservation, 'charging-sessions/current': session,
             'stations': {'items': [STATION], 'total': 1}}

    async def request(method, path, *args, **kwargs):
        return state[path]
    app.api.request.side_effect = request
    return app, state


async def build_stations(app, **params):
    with patch.object(stations, 'station_map_widget', new=AsyncMock(return_value=ft.Text('Map'))):
        return await stations.build(app, **params)


class RecargaTabRouteTests(unittest.TestCase):
    def test_recarga_tab_opens_station_search(self):
        self.assertEqual(tab_entries('consumer')[1], ('stations', 'Recarga', {}))
        self.assertEqual(navigation.TABS[1], ('stations', 'Recarga'))

    def test_recarga_tab_stays_highlighted_on_stations_and_its_flows(self):
        for route in ('stations', 'reservations', 'charging', 'booking'):
            with self.subTest(route=route):
                self.assertEqual(active_tab(route, {}, 'consumer'), 'stations')
                self.assertIsNone(active_tab(route, {}, 'vendor'))
        app = SimpleNamespace(link=lambda route, **params: None)
        nav = design.bottom_nav(app, tab_entries('consumer'), active_tab('stations', {}, 'consumer'))
        selected = [item.content.tooltip for item in nav.content.controls if item.selected]
        self.assertEqual(selected, ['Recarga'])

    def test_vendor_tabs_unchanged(self):
        self.assertEqual([route for route, _, _ in tab_entries('vendor')],
                         ['home', 'operator', 'history', 'chat', 'profile'])

    def test_old_list_route_resolves_to_station_search_and_detail_is_kept(self):
        self.assertEqual(resolve_route('reservations', {}), ('stations', {}))
        self.assertEqual(resolve_route('reservations', {'demo_seed': 'session', 'junk': 1}),
                         ('stations', {'demo_seed': 'session'}))
        self.assertEqual(resolve_route('reservations', {'detail': True}), ('reservations', {'detail': True}))
        self.assertEqual(resolve_route('stations', {'station_id': 's'}), ('stations', {'station_id': 's'}))
        self.assertIn('reservations', SCREENS)

    def test_back_from_detail_and_arrival_never_targets_removed_list(self):
        self.assertEqual(parent_route('reservations', {'detail': True}), ('stations', {}))
        self.assertEqual(parent_route('charging', {'reservation_id': 'r'}), ('reservations', {'detail': True}))
        self.assertEqual(parent_route('charging', {'session_id': 's'}), ('stations', {}))

    def test_list_screen_is_gone(self):
        source = inspect.getsource(reservations)
        self.assertNotIn("'Minhas recargas'", source)
        self.assertNotIn('Buscar mais estações', source)
        self.assertNotIn("'Próximas'", source)

    def test_no_screen_links_to_the_removed_list(self):
        import pathlib
        import re
        screens = pathlib.Path(reservations.__file__).parent
        pattern = re.compile(r"(?:link|go)\(\s*'reservations'\s*\)")
        offenders = [path.name for path in screens.glob('*.py') if pattern.search(path.read_text(encoding='utf-8'))]
        self.assertEqual(offenders, [])
        self.assertIn("app.go('reservations',detail=True)", (screens / 'stations.py').read_text(encoding='utf-8'))

    def test_chat_shortcuts_open_reservation_detail(self):
        actions = chat._ai_actions([{'type': 'open_reservation', 'label': 'Minha reserva'}])
        self.assertEqual(actions, [{'label': 'Minha reserva', 'route': 'reservations', 'data': {'detail': True}}])


class RecargaTabScreenTests(unittest.IsolatedAsyncioTestCase):
    async def test_old_route_builds_station_search(self):
        app, _ = app_with()
        with patch.object(stations, 'station_map_widget', new=AsyncMock(return_value=ft.Text('Map'))):
            screen = await reservations.build(app)
        shown = texts(screen)
        self.assertIn('Encontre uma estação', shown)
        self.assertNotIn('Minhas recargas', shown)

    async def test_no_active_recharge_shows_no_card(self):
        app, _ = app_with()
        screen = await build_stations(app)
        self.assertEqual(by_data(screen, 'active-session') + by_data(screen, 'active-reservation'), [])
        self.assertNotIn('Recarga em andamento', texts(screen))
        self.assertNotIn('Reserva ativa', texts(screen))
        self.assertIn('Encontre uma estação', texts(screen))

    async def test_running_session_card_opens_charging(self):
        app, _ = app_with(session=SESSION)
        screen = await build_stations(app)
        shown = texts(screen)
        self.assertIn('Recarga em andamento', shown)
        self.assertIn('Posto Centro', shown)
        self.assertLess(shown.index('Recarga em andamento'), shown.index('Encontre uma estação'))
        card, = by_data(screen, 'active-session')
        await card.on_click(None)
        app.go.assert_awaited_once_with('charging', session_id='ses')

    async def test_active_reservation_card_opens_detail(self):
        app, _ = app_with(reservation=RESERVATION)
        screen = await build_stations(app)
        self.assertIn('Reserva ativa', texts(screen))
        card, = by_data(screen, 'active-reservation')
        await card.on_click(None)
        app.go.assert_awaited_once_with('reservations', detail=True)

    async def test_finished_or_inactive_states_show_nothing(self):
        app, _ = app_with(reservation={**RESERVATION, 'status': 'consumed'}, session={**SESSION, 'status': 'completed'})
        screen = await build_stations(app)
        self.assertEqual(by_data(screen, 'active-session') + by_data(screen, 'active-reservation'), [])

    async def test_card_disappears_when_recharge_ends(self):
        app, state = app_with(session=SESSION)
        screen = await build_stations(app)
        self.assertIn('Recarga em andamento', texts(screen))
        state['charging-sessions/current'] = {**SESSION, 'status': 'completed'}
        with patch.object(stations, 'station_map_widget', new=AsyncMock(return_value=ft.Text('Map'))):
            await app.poll()
        self.assertNotIn('Recarga em andamento', texts(screen))
        self.assertIn('Encontre uma estação', texts(screen))

    async def test_api_failure_never_breaks_station_search(self):
        app = HandlerApp()

        async def request(method, path, *args, **kwargs):
            if path == 'stations':
                return {'items': [STATION], 'total': 1}
            raise RuntimeError('offline')
        app.api.request.side_effect = request
        screen = await build_stations(app)
        self.assertIn('Encontre uma estação', texts(screen))

    async def test_vendor_mode_and_station_detail_do_not_ask_for_active_recharge(self):
        app, _ = app_with(session=SESSION, mode='vendor')
        await build_stations(app)
        paths = [call.args[1] for call in app.api.request.await_args_list]
        self.assertNotIn('charging-sessions/current', paths)
        app, state = app_with(session=SESSION)
        state['stations/st'] = STATION
        state['stations/st/best-times'] = {}
        await build_stations(app, station_id='st')
        paths = [call.args[1] for call in app.api.request.await_args_list]
        self.assertNotIn('charging-sessions/current', paths)

    async def test_detail_back_and_cancel_return_to_station_search(self):
        app = HandlerApp()
        app.api.request.side_effect = [None]
        screen = await reservations.build(app, detail=True)
        self.assertIn('Nenhuma reserva ativa.', texts(screen))
        back = next(item.on_click for item in walk(screen) if getattr(item, 'on_click', None)
                    and getattr(item, 'tooltip', None) in ('Voltar',))
        await back(None)
        app.go.assert_awaited_with('stations')

        app = HandlerApp()
        app.planning_intent = {'x': 1}
        current = {**RESERVATION, 'connector': {'max_duration_minutes': 30}}
        app.api.request.side_effect = [current, {'status': 'cancelling'}]
        screen = await reservations.build(app, detail=True)
        cancel = next(item.on_click for item in walk(screen) if getattr(item, 'on_click', None)
                      and texts(item) == ['Cancelar Recarga'])
        await cancel(None)
        app.go.assert_awaited_with('stations')
        self.assertIsNone(app.planning_intent)


if __name__ == '__main__':
    unittest.main()
