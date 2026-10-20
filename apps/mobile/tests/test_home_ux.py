"""Home follows the reference layout and keeps real current activity, polling in place."""
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import flet as ft

from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DemoApi
from chargegrid_app.screens import home
from chargegrid_app.services import notifications as notification_service


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
    """on_click of the innermost visible control whose only text is ``label``."""
    return next(item.on_click for item in descendants(control, visible_only=True)
                if getattr(item, 'on_click', None) and text_values(item) == [label])


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
    async def test_idle_home_matches_reference_structure(self):
        app = HomeApp()
        screen = await home.build(app)
        visible = text_values(screen, visible_only=True)
        self.assertIn('Olá, Marina!', visible)
        self.assertEqual([v for v in visible if v in ('SALDO DISPONÍVEL', 'Perto de Você', 'Encontre uma Estação')],
                         ['SALDO DISPONÍVEL', 'Perto de Você', 'Encontre uma Estação'])
        self.assertLess(visible.index('SALDO DISPONÍVEL'), visible.index('Perto de Você'))
        self.assertLess(visible.index('Perto de Você'), visible.index('Posto real'))
        self.assertLess(visible.index('Posto real'), visible.index('Encontre uma Estação'))
        self.assertIn('R$ 2,00/kWh', visible)
        self.assertNotIn('SUA RECARGA', visible)
        self.assertNotIn('SUA RESERVA', visible)
        self.assertFalse(any('Postos no mapa' in str(v) or 'GASTO ESTIMADO' in str(v) for v in visible))
        self.assertTrue(any(str(v).startswith('R$ ') for v in visible))
        await click(screen, 'Encontre uma Estação')(None)
        app.go.assert_awaited_once_with('stations')

    async def test_balance_tiles_open_statement_and_add_balance(self):
        app = HomeApp()
        screen = await home.build(app)
        tiles = [item for item in descendants(screen) if getattr(item, 'tooltip', None) in ('Extrato', 'Adicionar saldo')]
        self.assertEqual([tile.tooltip for tile in tiles], ['Extrato', 'Adicionar saldo'])
        await tiles[0].on_click(None)
        app.go.assert_awaited_with('wallet', page='statement')
        await tiles[1].on_click(None)
        app.go.assert_awaited_with('wallet', page='add', step=1)

    async def test_station_row_opens_station_details(self):
        app = HomeApp()
        screen = await home.build(app)
        row = next(item for item in descendants(screen) if getattr(item, 'on_click', None)
                   and 'Posto real' in text_values(item))
        await row.on_click(None)
        app.go.assert_awaited_once_with('stations', station_id='station')

    async def test_session_card_appears_below_reference_content(self):
        app = HomeApp()
        app.state['charging-sessions/current'] = {
            'id': 'session', 'status': 'charging', 'station_name': 'Posto da sessão',
            'source': 'device', 'soc_percent': 42, 'online': False,
        }
        app.state['reservations/current'] = {'id': 'reserve', 'status': 'confirmed'}
        screen = await home.build(app)
        visible = text_values(screen, visible_only=True)
        self.assertLess(visible.index('Encontre uma Estação'), visible.index('Acompanhar recarga'))
        self.assertNotIn('Cheguei: informar código', visible)
        self.assertIn('SUA RECARGA', visible)
        self.assertTrue(any('Equipamento offline, últimos dados recebidos' in str(text) for text in visible))
        await click(screen, 'Acompanhar recarga')(None)
        app.go.assert_awaited_once_with('charging', session_id='session')

    async def test_confirmed_reservation_arrival_preserves_point_context_and_limit(self):
        app = HomeApp()
        reservation = {'id': 'reserve', 'status': 'confirmed', 'station_name': 'Posto reservado',
                       'connector': {'id': 'reserved-point', 'max_duration_minutes': 15}}
        app.state['reservations/current'] = reservation
        screen = await home.build(app)
        await click(screen, 'Cheguei: informar código')(None)
        app.go.assert_awaited_once_with('charging', reservation_id='reserve',
                                       point_context=reservation, max_duration=15)

    async def test_pending_and_cancelling_reservations_do_not_offer_arrival(self):
        for status, label in [('pending_device', 'Acompanhar reserva'), ('cancelling', 'Acompanhar liberação')]:
            with self.subTest(status=status):
                app = HomeApp()
                app.state['reservations/current'] = {'id': 'reserve', 'status': status}
                screen = await home.build(app)
                self.assertNotIn('Cheguei: informar código', text_values(screen, visible_only=True))
                await click(screen, label)(None)
                app.go.assert_awaited_once_with('reservations', detail=True)

    async def test_poll_updates_in_place_and_unchanged_snapshot_does_not_redraw(self):
        app = HomeApp()
        screen = await home.build(app)
        original_controls = tuple(screen.controls)
        await app.poll()
        app.page.update.assert_not_called()
        app.state['reservations/current'] = {'id': 'reserve', 'status': 'pending_device'}
        await app.poll()
        self.assertIn('Acompanhar reserva', text_values(screen, visible_only=True))
        app.state['reservations/current']['status'] = 'confirmed'
        await app.poll()
        self.assertIn('Cheguei: informar código', text_values(screen, visible_only=True))
        app.state['charging-sessions/current'] = {'id': 'session', 'status': 'starting'}
        await app.poll()
        self.assertIn('Acompanhar recarga', text_values(screen, visible_only=True))
        app.state['charging-sessions/current'] = None
        app.state['reservations/current'] = None
        app.state['stations']['items'][0]['connectors'][0]['online'] = False
        await app.poll()
        visible = text_values(screen, visible_only=True)
        self.assertNotIn('Acompanhar recarga', visible)
        self.assertIn('R$ 2,00/kWh', visible)
        self.assertTrue(all(old is new for old, new in zip(original_controls, screen.controls)))
        app.go.assert_not_called()
        self.assertEqual(app.page.update.call_count, 4)
        await app.poll()
        self.assertEqual(app.page.update.call_count, 4)
        self.assertEqual(app.interval, 10)

    async def test_poll_refreshes_balance_from_wallet_service(self):
        app = HomeApp()
        with patch.object(home, '_amount', new=AsyncMock(return_value=__import__('decimal').Decimal('10'))):
            screen = await home.build(app)
            self.assertIn('R$ 10,00', text_values(screen, visible_only=True))
        with patch.object(home, '_amount', new=AsyncMock(return_value=__import__('decimal').Decimal('25.5'))):
            await app.poll()
        self.assertIn('R$ 25,50', text_values(screen, visible_only=True))

    async def test_missing_wallet_service_falls_back_to_zero(self):
        app = HomeApp()
        with patch('importlib.import_module', side_effect=ImportError('missing')):
            self.assertEqual(await home._amount('wallet', 'balance', app), __import__('decimal').Decimal('0'))

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
        self.assertEqual(prices, ['R$ 2,00/kWh'])

    async def test_inactive_station_shows_status_instead_of_price(self):
        app = HomeApp()
        app.state['stations']['items'] = [station(active=False)]
        screen = await home.build(app)
        visible = text_values(screen, visible_only=True)
        self.assertIn('Desativado', visible)
        self.assertFalse(any('/kWh' in str(text) for text in visible))

    async def test_home_lists_at_most_two_stations_and_requests_three(self):
        app = HomeApp()
        app.state['stations']['items'] = [station(id=f's{i}', name=f'Posto {i}') for i in range(5)]
        screen = await home.build(app)
        visible = text_values(screen, visible_only=True)
        self.assertIn('Posto 0', visible)
        self.assertIn('Posto 1', visible)
        self.assertNotIn('Posto 2', visible)
        app.api.request.assert_any_await('GET', 'stations', params={'limit': 3, 'offset': 0})

    async def test_demo_consumer_home_is_local(self):
        app = HomeApp()
        with patch('httpx.AsyncClient', side_effect=AssertionError('Home demo must remain local')):
            app.api = DemoApi()
            await app.api.login(DEMO_EMAIL, DEMO_PASSWORD)
            app.profile = await app.api.request('GET', 'me')
            screen = await home.build(app)
            await app.poll()
        visible = text_values(screen, visible_only=True)
        self.assertIn('Olá, João!', visible)
        self.assertIn('Perto de Você', visible)
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
                                                                  for value in (None, 'NaN', 'inf', '-1', 'invalid')])))
        self.assertEqual(home._station_status(station(connectors=[point(active=False)]))[0], 'Desativado')
        self.assertEqual(home._station_status(station(connectors=[]))[0], 'Sem pontos')


class VendorHomeTests(unittest.IsolatedAsyncioTestCase):
    def vendor_app(self, items):
        app = HomeApp()
        app.profile = {'name': 'João Pedro', 'account_type': 'vendor', 'operator_enabled': True}
        app.state['me'] = app.profile
        app.state['operator/stations'] = {'items': items, 'total': len(items)}
        return app

    async def test_vendor_home_matches_reference_structure(self):
        app = self.vendor_app([station(name='Marginal Pinheiros')])
        with patch.object(home, '_amount', new=AsyncMock(return_value=__import__('decimal').Decimal('2485.90'))):
            screen = await home.build_vendor(app)
        visible = text_values(screen, visible_only=True)
        self.assertEqual(visible[:3], ['Olá, João!', 'SALDO A RECEBER', 'R$ 2485,90'])
        self.assertLess(visible.index('Suas estações'), visible.index('Marginal Pinheiros'))
        self.assertLess(visible.index('Marginal Pinheiros'), visible.index('Fale com o ChatBot'))
        self.assertIn('R$ 2,00/kWh', visible)

    async def test_vendor_links_go_to_payout_station_admin_and_chat(self):
        app = self.vendor_app([station(name='Marginal Pinheiros')])
        screen = await home.build_vendor(app)
        row = next(item for item in descendants(screen) if getattr(item, 'on_click', None)
                   and 'Marginal Pinheiros' in text_values(item) and 'Fale com o ChatBot' not in text_values(item))
        await row.on_click(None)
        app.go.assert_awaited_with('station_admin', station_id='station')
        balance = next(item for item in descendants(screen) if getattr(item, 'on_click', None)
                       and 'SALDO A RECEBER' in text_values(item))
        await balance.on_click(None)
        app.go.assert_awaited_with('payout')
        chat = next(item for item in descendants(screen) if getattr(item, 'on_click', None)
                    and 'Fale com o ChatBot' in text_values(item))
        await chat.on_click(None)
        app.go.assert_awaited_with('chat')

    async def test_vendor_without_stations_offers_to_scan_the_claim_qr(self):
        app = self.vendor_app([])
        screen = await home.build_vendor(app)
        visible = text_values(screen, visible_only=True)
        self.assertIn('Configure sua primeira tela', visible)
        self.assertNotIn('SALDO A RECEBER', visible)
        await click(screen, 'Escanear QR Code')(None)
        app.go.assert_awaited_once_with('operator', claim=True)

    async def test_vendor_poll_refreshes_rows_in_place(self):
        app = self.vendor_app([station(name='Primeiro')])
        screen = await home.build_vendor(app)
        app.state['operator/stations'] = {'items': [station(name='Segundo')], 'total': 1}
        await app.poll()
        self.assertIn('Segundo', text_values(screen, visible_only=True))
        self.assertNotIn('Primeiro', text_values(screen, visible_only=True))


class NotificationServiceTests(unittest.IsolatedAsyncioTestCase):
    def test_battery_item_only_when_target_reached(self):
        self.assertIsNone(notification_service.battery_item({'id': 's', 'soc_percent': 79}))
        self.assertIsNone(notification_service.battery_item({'id': 's', 'soc_percent': None}))
        item = notification_service.battery_item({'id': 's', 'soc_percent': '85', 'station_name': 'Posto',
                                                  'last_measurement_at': '2026-10-18T15:42:00+00:00'})
        self.assertEqual(item['title'], 'Meta de bateria atingida')
        self.assertEqual(item['subtitle'], 'Estação Posto')
        self.assertTrue(item['detail'].startswith('Bateria atingiu 80% - '))

    def test_offline_items_ignore_inactive_stations_and_online_points(self):
        stations = [station(id='a', connectors=[point(online=False)]),
                    station(id='b', connectors=[point(online=True)]),
                    station(id='c', active=False, connectors=[point(online=False)]),
                    station(id='d', connectors=[])]
        items = notification_service.offline_items(stations)
        self.assertEqual([item['id'] for item in items], ['offline-a'])
        self.assertEqual(items[0]['detail'], 'Verifique o status do dispositivo.')

    async def test_collect_uses_sample_only_in_demo(self):
        app = HomeApp()
        app.browsing_mode = 'consumer'
        app.state['charging-sessions/current'] = None
        self.assertEqual(await notification_service.collect(app), [])
        app.api.is_demo = True
        self.assertEqual(len(await notification_service.collect(app)), 2)

    async def test_vendor_collect_reports_offline_station(self):
        app = HomeApp()
        app.browsing_mode = 'vendor'
        app.state['operator/stations'] = {'items': [station(connectors=[point(online=False)])]}
        items = await notification_service.collect(app)
        self.assertEqual([item['title'] for item in items], ['Estação sem comunicação'])

    def test_grouping_labels_today_and_yesterday(self):
        from datetime import datetime, timedelta
        now = datetime.now().astimezone()
        groups = notification_service.grouped([
            {'id': 'a', 'at': now}, {'id': 'b', 'at': now - timedelta(days=1)}], now)
        self.assertEqual([label for label, _ in groups], ['Hoje', 'Ontem'])
