"""Home prioritizes real current activity and keeps its controls stable on polls."""
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import flet as ft

from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DemoApi
from chargegrid_app.screens import home


def descendants(control, *, visible_only=False):
    if visible_only and getattr(control, 'visible', True) is False:
        return
    yield control
    content = getattr(control, 'content', None)
    if content is not None and not isinstance(content, str):
        yield from descendants(content, visible_only=visible_only)
    for child in getattr(control, 'controls', []) or []:
        yield from descendants(child, visible_only=visible_only)


def text_values(control, *, visible_only=False):
    return [item.value for item in descendants(control, visible_only=visible_only)
            if isinstance(item, ft.Text)]


def click(control, label):
    return next(item.on_click for item in descendants(control, visible_only=True)
                if getattr(item, 'on_click', None)
                and isinstance(getattr(item, 'content', None), ft.Text)
                and item.content.value == label)


def point(**changes):
    return dict({'id':'point', 'active':True, 'online':True, 'available':True,
                 'availability_status':'available', 'price_per_kwh':'2.00'}, **changes)


def station(**changes):
    return dict({'id':'station', 'name':'Posto real', 'address':'Rua conhecida, 10',
                 'latitude':-23.55,'longitude':-46.63,'active':True, 'connectors':[point()]}, **changes)


class HomeApp:
    def __init__(self):
        self.profile = {'name':'Marina Silva', 'account_type':'consumer'}
        self.page = SimpleNamespace(update=Mock())
        self.go = AsyncMock()
        self.state = {
            'reservations/current':None,
            'charging-sessions/current':None,
            'stations':{'items':[station()], 'total':1},
            'me/summary':{'sessions_count':3, 'estimated_cost':'12.50', 'energy_wh':'1450'},
        }
        self.api = SimpleNamespace(is_demo=False, request=AsyncMock(side_effect=self.request))
        self.poll = None

    async def request(self, method, path, **kwargs):
        return self.state[path]

    def link(self, route, **kwargs):
        async def callback(event=None):
            await self.go(route, **kwargs)
        return callback

    def set_poll(self, callback, interval):
        self.poll, self.interval = callback, interval


class HomeUxTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        render = patch('chargegrid_app.services.maps.build_map_png',return_value=b'fixture-png')
        render.start()
        self.addCleanup(render.stop)

    async def test_idle_home_places_primary_action_before_map_and_summary(self):
        app = HomeApp()
        screen = await home.build(app)
        visible = text_values(screen, visible_only=True)
        self.assertIn('Olá, Marina', visible)
        self.assertLess(visible.index('Recarregar agora'), visible.index('GASTO ESTIMADO NESTE MÊS'))
        self.assertLess(visible.index('Recarregar agora'), visible.index('Postos no mapa'))
        self.assertLess(visible.index('Postos no mapa'), visible.index('GASTO ESTIMADO NESTE MÊS'))
        self.assertNotIn('Guia de recarga',visible)
        self.assertIn('R$ 12,50', visible)
        self.assertIn('ENCONTRE SEU PONTO', visible)
        self.assertEqual(visible.count('Recarregar agora'), 1)
        self.assertFalse(any('informar código #F' in str(value) for value in visible))
        await click(screen, 'Recarregar agora')(None)
        app.go.assert_awaited_once_with('stations')

    async def test_session_takes_priority_over_reservation_and_summary(self):
        app = HomeApp()
        app.state['charging-sessions/current'] = {
            'id':'session', 'status':'charging', 'station_name':'Posto da sessão',
            'source':'device', 'soc_percent':42, 'online':False,
        }
        app.state['reservations/current'] = {'id':'reserve', 'status':'confirmed'}
        screen = await home.build(app)
        visible = text_values(screen, visible_only=True)
        self.assertLess(visible.index('Acompanhar recarga'), visible.index('GASTO ESTIMADO NESTE MÊS'))
        self.assertNotIn('Cheguei: informar código', visible)
        self.assertNotIn('Recarregar agora', visible)
        self.assertTrue(any('Equipamento offline, últimos dados recebidos' in str(text) for text in visible))
        await click(screen, 'Acompanhar recarga')(None)
        app.go.assert_awaited_once_with('charging', session_id='session')

    async def test_confirmed_reservation_arrival_preserves_point_context_and_limit(self):
        app = HomeApp()
        reservation = {'id':'reserve', 'status':'confirmed', 'station_name':'Posto reservado',
                       'connector':{'id':'reserved-point', 'max_duration_minutes':15}}
        app.state['reservations/current'] = reservation
        screen = await home.build(app)
        self.assertNotIn('Recarregar agora', text_values(screen, visible_only=True))
        await click(screen, 'Cheguei: informar código')(None)
        app.go.assert_awaited_once_with('charging', reservation_id='reserve',
                                       point_context=reservation, max_duration=15)

    async def test_pending_and_cancelling_reservations_do_not_offer_arrival(self):
        for status, label in [('pending_device', 'Acompanhar reserva'), ('cancelling', 'Acompanhar liberação')]:
            with self.subTest(status=status):
                app = HomeApp()
                app.state['reservations/current'] = {'id':'reserve', 'status':status}
                screen = await home.build(app)
                self.assertNotIn('Cheguei: informar código', text_values(screen, visible_only=True))
                self.assertNotIn('Recarregar agora', text_values(screen, visible_only=True))
                await click(screen, label)(None)
                app.go.assert_awaited_once_with('reservations')

    async def test_poll_transitions_in_place_and_unchanged_snapshot_does_not_redraw(self):
        app = HomeApp()
        screen = await home.build(app)
        original_controls = tuple(screen.controls)
        await app.poll()
        app.page.update.assert_not_called()
        app.state['reservations/current'] = {'id':'reserve', 'status':'pending_device'}
        await app.poll()
        self.assertIn('Acompanhar reserva', text_values(screen, visible_only=True))
        app.state['reservations/current']['status'] = 'confirmed'
        await app.poll()
        self.assertIn('Cheguei: informar código', text_values(screen, visible_only=True))
        app.state['charging-sessions/current'] = {'id':'session', 'status':'starting'}
        await app.poll()
        self.assertIn('Acompanhar recarga', text_values(screen, visible_only=True))
        app.state['charging-sessions/current'] = None
        app.state['reservations/current'] = None
        app.state['me/summary']['estimated_cost'] = '18.75'
        app.state['stations']['items'][0]['connectors'][0]['online'] = False
        await app.poll()
        visible = text_values(screen, visible_only=True)
        self.assertIn('Recarregar agora', visible)
        self.assertIn('R$ 18,75', visible)
        self.assertIn('Offline', visible)
        self.assertFalse(any('/kWh' in str(text) for text in visible))
        self.assertTrue(all(old is new for old, new in zip(original_controls, screen.controls)))
        app.go.assert_not_called()
        self.assertEqual(app.page.update.call_count, 4)
        await app.poll()
        self.assertEqual(app.page.update.call_count, 4)
        self.assertEqual(app.interval, 10)

    async def test_home_omits_guide_for_idle_reservation_and_charging(self):
        app = HomeApp()
        screen = await home.build(app)
        self.assertNotIn('Guia de recarga',text_values(screen))
        app.state['reservations/current'] = {'id':'private-reservation-id', 'status':'confirmed'}
        await app.poll()
        self.assertNotIn('Guia de recarga',text_values(screen))
        app.state['charging-sessions/current'] = {'id':'private-session-id', 'status':'charging'}
        await app.poll()
        self.assertNotIn('Guia de recarga',text_values(screen))

    async def test_only_available_enabled_online_points_contribute_to_displayed_price(self):
        app = HomeApp()
        app.state['stations']['items'] = [station(connectors=[
            point(active=False, price_per_kwh='0.10'),
            point(online=False, price_per_kwh='0.20'),
            point(available=False, availability_status='charging', price_per_kwh='0.30'),
            point(retired=True, price_per_kwh='0.40'),
            point(availability_status='fault', price_per_kwh='0.50'),
            point(price_per_kwh='2.00'),
        ])]
        screen = await home.build(app)
        prices = [text for text in text_values(screen) if '/kWh' in str(text)]
        self.assertEqual(prices, ['Desde R$ 2,00/kWh'])

    async def test_inactive_station_does_not_advertise_available_points_or_price(self):
        app = HomeApp()
        app.state['stations']['items'] = [station(active=False)]
        screen = await home.build(app)
        visible = text_values(screen, visible_only=True)
        self.assertIn('Desativado', visible)
        self.assertNotIn('Disponível', visible)
        self.assertFalse(any('/kWh' in str(text) for text in visible))

    async def test_home_caps_map_stations_and_does_not_invent_distance_or_discounts(self):
        app = HomeApp()
        app.state['stations']['items'] = [station(id=f's{i}', name=f'Posto {i}') for i in range(5)]
        with patch.object(home,'station_map_widget',new=AsyncMock(return_value=ft.Text('Map'))) as draw:
            screen = await home.build(app)
        visible = text_values(screen, visible_only=True)
        self.assertEqual([station['name'] for station in draw.call_args.args[0]], ['Posto 0', 'Posto 1', 'Posto 2'])
        self.assertNotRegex(' '.join(visible).lower(), r'próxim|distância|\bkm\b|desconto|economize|22h')
        app.api.request.assert_any_await('GET', 'stations', params={'limit':3, 'offset':0})
        await click(screen, 'Recarregar agora')(None)
        app.go.assert_awaited_with('stations')

    async def test_primary_action_uses_shared_button_sizes_at_every_width(self):
        app = HomeApp()
        app.page.width = 600
        screen = await home.build(app)
        section = screen.controls[2]
        action = next(item for item in descendants(screen) if isinstance(item, ft.TextButton)
                      and isinstance(item.content, ft.Text) and item.content.value == 'Recarregar agora')
        self.assertEqual(section.spacing,16)
        self.assertIsNone(action.height)
        self.assertGreaterEqual(action.style.padding.top,14)
        self.assertEqual(action.content.size,16)
        self.assertEqual(action.style.bgcolor,home.theme.RED)
        with patch.object(section,'update'):
            await section.on_size_change(SimpleNamespace(width=320))
        self.assertIsNone(action.height)
        self.assertGreaterEqual(action.style.padding.top,14)
        self.assertEqual(action.content.size,16)
        self.assertEqual(section.spacing,16)

    async def test_demo_vendor_home_remains_compact_and_has_no_remote_download(self):
        app = HomeApp()
        with patch('httpx.AsyncClient', side_effect=AssertionError('Home demo must remain local')):
            app.api = DemoApi()
            await app.api.login(DEMO_EMAIL, DEMO_PASSWORD)
            app.profile = await app.api.request('GET', 'me')
            screen = await home.build(app)
            await app.poll()
        visible = text_values(screen, visible_only=True)
        self.assertIn('© OpenStreetMap', visible)
        self.assertIn('Recarregar agora', visible)
        self.assertNotIn('Sua conta de operador', visible)
        self.assertFalse(any('ESP32' in str(text) for text in visible))

    async def test_snapshot_failure_does_not_partially_change_display(self):
        app = HomeApp()
        screen = await home.build(app)
        before = deepcopy(text_values(screen))
        app.api.request.side_effect = RuntimeError('temporarily unavailable')
        with self.assertRaises(RuntimeError):
            await app.poll()
        self.assertEqual(text_values(screen), before)
        app.page.update.assert_not_called()

    def test_invalid_prices_and_all_disabled_connectors_have_safe_fallbacks(self):
        self.assertIsNone(home._station_price(station(connectors=[point(price_per_kwh=value)
                                                                  for value in (None, 'NaN', 'inf', '-1', 'invalid') ])))
        self.assertEqual(home._station_status(station(connectors=[point(active=False)]))[0], 'Desativado')
        self.assertEqual(home._station_status(station(connectors=[]))[0], 'Sem pontos')
