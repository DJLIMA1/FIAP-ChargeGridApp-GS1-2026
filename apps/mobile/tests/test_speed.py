"""Velocidade: cache das respostas, invalidação, consultas em paralelo, revalidação e polls."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import flet as ft
import httpx

from chargegrid_app import api_cache
from chargegrid_app.api_client import ApiClient, ApiError
from chargegrid_app.app import ChargeGridApp
from chargegrid_app.services import notifications, payout, prefetch
from speed_harness import Harness, serial_depth

BASE = 'https://api.example.test/v1'


def tokens():
    return {'access_token': 'a', 'refresh_token': 'r', 'expires_in': 3600, 'user': {'id': 'u', 'email': 'u@x.test'}}


class Server:
    """Transporte falso: conta pedidos por rota e responde ``self.data[path]`` (pode mudar no meio)."""

    def __init__(self, data=None, delay=0.0):
        self.data = dict(data or {})
        self.delay = delay
        self.calls = []
        self.errors = {}

    async def handle(self, request):
        path = request.url.path.removeprefix('/v1/')
        self.calls.append((request.method, path, dict(request.url.params)))
        if self.delay:
            await asyncio.sleep(self.delay)
        if path in self.errors:
            raise self.errors.pop(path)
        if request.method != 'GET':
            return httpx.Response(200, json={'ok': True, 'id': 'x'})
        default = None if path.endswith('/current') else {'path': path}
        return httpx.Response(200, json=self.data.get(path, default))

    def count(self, path, method='GET'):
        return sum(1 for m, p, _ in self.calls if p == path and m == method)


def client(server):
    api = ApiClient(BASE, httpx.MockTransport(server.handle))
    api.session.update(tokens())
    return api


class ClockMixin:
    def setUp(self):
        self.now = 1000.0
        clock = patch.object(api_cache, 'clock', lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)


class CacheTests(ClockMixin, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = Server({'me': {'id': 'u', 'name': 'Ana'}, 'stations': {'items': [], 'total': 0}})
        self.api = client(self.server)

    async def asyncTearDown(self):
        await self.api.close()

    async def test_screen_build_reads_fresh_cache_but_polls_always_hit_the_network(self):
        await self.api.request('GET', 'me')  # poll/ação: rede e escrita no cache
        with api_cache.reading():
            self.assertEqual(await self.api.request('GET', 'me'), {'id': 'u', 'name': 'Ana'})
        self.assertEqual(self.server.count('me'), 1)
        self.server.data['me'] = {'id': 'u', 'name': 'Bia'}
        self.assertEqual((await self.api.request('GET', 'me'))['name'], 'Bia')  # fora da montagem: rede
        self.assertEqual(self.server.count('me'), 2)
        with api_cache.reading():
            self.assertEqual((await self.api.request('GET', 'me'))['name'], 'Bia')  # cache já atualizado
        self.assertEqual(self.server.count('me'), 2)

    async def test_returned_objects_are_copies(self):
        with api_cache.reading():
            first = await self.api.request('GET', 'me')
            first['name'] = 'mutated by a screen'
            second = await self.api.request('GET', 'me')
        self.assertEqual(second['name'], 'Ana')

    async def test_stale_is_served_only_when_the_screen_allows_and_is_reported(self):
        await self.api.request('GET', 'stations', params={'limit': 3})
        self.now += 30  # fresco: 10 s; velho aceitável: 900 s
        with api_cache.reading() as fresh_only:
            await self.api.request('GET', 'stations', params={'limit': 3})
        self.assertEqual(self.server.count('stations'), 2)
        self.assertEqual(fresh_only.served, [])
        self.now += 30
        with api_cache.reading(stale_ok=True) as mode:
            await self.api.request('GET', 'stations', params={'limit': 3})
        self.assertEqual(self.server.count('stations'), 2)
        self.assertEqual([read.path for read in mode.served], ['stations'])
        self.now += 1000  # passou do limite: rede
        with api_cache.reading(stale_ok=True) as mode:
            await self.api.request('GET', 'stations', params={'limit': 3})
        self.assertEqual(self.server.count('stations'), 3)

    async def test_params_are_part_of_the_key(self):
        with api_cache.reading():
            await self.api.request('GET', 'stations', params={'limit': 3, 'available_only': False})
            await self.api.request('GET', 'stations', params={'available_only': False, 'limit': 3})
            await self.api.request('GET', 'stations', params={'limit': 20})
        self.assertEqual(self.server.count('stations'), 2)

    async def test_live_operation_routes_are_never_cached(self):
        for path in ('charging-sessions/s1', 'payments/p1', 'devices/d1/factory-reset', 'charging-sessions/s1/events'):
            with api_cache.reading(stale_ok=True):
                await self.api.request('GET', path)
                await self.api.request('GET', path)
            self.assertEqual(self.server.count(path), 2, path)

    async def test_concurrent_identical_gets_share_one_request(self):
        self.server.delay = 0.02
        results = await asyncio.gather(*(self.api.request('GET', 'me') for _ in range(4)))
        self.assertEqual(self.server.count('me'), 1)
        self.assertEqual(results, [results[0]] * 4)

    async def test_leaving_the_screen_does_not_cancel_the_shared_request(self):
        self.server.delay = 0.05
        with api_cache.reading():
            task = asyncio.ensure_future(self.api.request('GET', 'me'))
            await asyncio.sleep(0.01)
            task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0.08)
        with api_cache.reading():
            await self.api.request('GET', 'me')
        self.assertEqual(self.server.count('me'), 1)  # a resposta chegou e ficou guardada

    async def test_errors_are_not_cached(self):
        self.server.errors = {'me': httpx.ReadTimeout('late')}
        with api_cache.reading(), self.assertRaises(ApiError):
            await self.api.request('GET', 'me')
        with api_cache.reading():
            self.assertEqual((await self.api.request('GET', 'me'))['name'], 'Ana')
        self.assertEqual(self.server.count('me'), 2)

    async def test_close_discards_everything(self):
        await self.api.request('GET', 'me')
        await self.api.close()
        self.assertEqual(self.api.cache.entries, {})


class InvalidationTests(ClockMixin, unittest.IsolatedAsyncioTestCase):
    PATHS = ('me', 'driver/profile', 'payments/config', 'stations', 'stations/s1', 'operator/stations',
             'reservations/current', 'charging-sessions/current', 'me/charging-sessions', 'owner/overview')

    async def asyncSetUp(self):
        self.server = Server()
        self.api = client(self.server)
        for path in self.PATHS:
            await self.api.request('GET', path)

    async def asyncTearDown(self):
        await self.api.close()

    def cached(self):
        return {key[0] for key in self.api.cache.entries}

    async def test_reserving_drops_availability_history_and_dashboard_but_keeps_stable_config(self):
        await self.api.request('POST', 'reservations', {'connector_id': 'c'}, key='k')
        self.assertEqual(self.cached(), {'driver/profile', 'payments/config'})

    async def test_starting_and_stopping_a_charge_and_cancelling_a_reservation(self):
        for path in ('charging-sessions', 'charging-sessions/s1/stop', 'reservations/r1/cancel'):
            for item in self.PATHS:
                await self.api.request('GET', item)
            await self.api.request('POST', path, {}, key='k' if path == 'charging-sessions' else None)
            self.assertNotIn('charging-sessions/current', self.cached(), path)
            self.assertNotIn('reservations/current', self.cached(), path)
            self.assertNotIn('stations', self.cached(), path)
            self.assertNotIn('me/charging-sessions', self.cached(), path)

    async def test_editing_a_station_drops_station_lists_and_owner_panel(self):
        await self.api.request('PATCH', 'stations/s1', {'name': 'Novo'})
        self.assertFalse({'stations', 'stations/s1', 'operator/stations', 'owner/overview'} & self.cached())
        for path in self.PATHS:
            await self.api.request('GET', path)
        await self.api.request('PUT', 'stations/s1/pricing', {})
        self.assertNotIn('stations/s1', self.cached())

    async def test_profile_edit_only_drops_account_data(self):
        await self.api.request('PATCH', 'me', {'name': 'Bia'})
        self.assertEqual(self.cached(), set(self.PATHS) - {'me', 'driver/profile'})

    async def test_phone_battery_only_drops_current_charge(self):
        await self.api.request('POST', 'charging-sessions/s1/soc', {'soc_percent': 50})
        self.assertEqual(self.cached(), set(self.PATHS) - {'charging-sessions/current'})

    async def test_ai_questions_keep_everything_and_auth_clears_everything(self):
        await self.api.request('POST', 'ai/chat', {'messages': []})
        self.assertEqual(self.cached(), set(self.PATHS))
        await self.api.request('POST', 'auth/logout')
        self.assertEqual(self.cached(), set())

    async def test_failed_mutation_still_invalidates(self):
        self.server.errors['reservations'] = httpx.ReadTimeout('late')
        with self.assertRaises(ApiError):
            await self.api.request('POST', 'reservations', {'connector_id': 'c'}, key='k')
        self.assertNotIn('reservations/current', self.cached())

    async def test_read_that_started_before_a_write_is_not_stored(self):
        self.server.delay = 0.05
        self.api.cache.entries.clear()
        reading = asyncio.ensure_future(self.api.request('GET', 'reservations/current'))
        await asyncio.sleep(0.01)
        self.server.delay = 0
        await self.api.request('POST', 'reservations', {'connector_id': 'c'}, key='k')
        await reading
        self.assertNotIn('reservations/current', self.cached())


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_is_retried_once_on_a_dropped_connection_but_writes_are_not(self):
        server = Server({'stations/s1/best-times': {'ok': 1}})
        api = client(server)
        server.errors['stations/s1/best-times'] = httpx.RemoteProtocolError('closed')
        self.assertEqual(await api.request('GET', 'stations/s1/best-times'), {'ok': 1})
        self.assertEqual(server.count('stations/s1/best-times'), 2)
        server.errors['reservations'] = httpx.RemoteProtocolError('closed')
        with self.assertRaises(ApiError):
            await api.request('POST', 'reservations', {'connector_id': 'c'}, key='k')
        self.assertEqual(server.count('reservations', 'POST'), 1)
        await api.close()

    def test_connections_are_kept_alive_between_taps(self):
        from chargegrid_app import api_client
        self.assertEqual(api_client.LIMITS.keepalive_expiry, 30)  # o padrão do httpx fecha após 5 s parado
        self.assertEqual((api_client.TIMEOUT.connect, api_client.TIMEOUT.read), (6, 12))

    async def test_warm_up_hits_health_without_credentials_and_never_raises(self):
        seen = []

        def handler(request):
            seen.append((str(request.url), request.headers.get('authorization')))
            raise httpx.ConnectError('offline')
        api = ApiClient(BASE, httpx.MockTransport(handler))
        await api.warm_up()
        self.assertEqual(seen[0], ('https://api.example.test/health', None))
        await api.close()


class PrefetchTests(ClockMixin, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = Server()
        self.api = client(self.server)
        self.app = SimpleNamespace(api=self.api, browsing_mode='consumer', closed=False,
                                   page=SimpleNamespace(width=390))

    async def asyncTearDown(self):
        await self.api.close()

    async def test_prefetch_uses_the_exact_screen_key_and_skips_fresh_entries(self):
        tasks = prefetch.fetch(self.app, [prefetch.STATIONS_TAB])
        await asyncio.gather(*tasks)
        self.assertEqual(prefetch.fetch(self.app, [prefetch.STATIONS_TAB]), [])  # já fresco
        with api_cache.reading():
            await self.api.request('GET', 'stations', params={'limit': 20, 'offset': 0, 'sort': 'default',
                                                              'available_only': False})
        self.assertEqual(self.server.count('stations'), 1)

    async def test_prefetch_errors_are_silent(self):
        self.server.errors['me'] = httpx.ReadTimeout('late')
        task = self.api.prefetch('me')
        with self.assertRaises(ApiError):
            await task
        self.assertIsNone(self.api.prefetch('charging-sessions/s1'))  # rota não guardada: nada

    async def test_demo_and_fake_clients_never_prefetch(self):
        self.assertEqual(prefetch.fetch(SimpleNamespace(api=Mock(), closed=False), [('me', None)]), [])

    async def test_owner_net_period_is_stable_for_minutes_and_never_cuts_recent_sessions(self):
        from datetime import datetime, timezone
        moment = datetime(2026, 10, 20, 13, 7, 41, tzinfo=timezone.utc)
        end = prefetch.period_end(moment)
        self.assertEqual(end, datetime(2026, 10, 20, 13, 10, tzinfo=timezone.utc))
        self.assertGreater(end, moment)
        self.assertEqual(payout.net_params(moment), payout.net_params(datetime(2026, 10, 20, 13, 9, 59,
                                                                               tzinfo=timezone.utc)))
        exact = datetime(2026, 10, 20, 13, 10, tzinfo=timezone.utc)
        self.assertGreater(prefetch.period_end(exact), exact)


class StationSeedTests(ClockMixin, unittest.IsolatedAsyncioTestCase):
    async def test_station_list_items_seed_the_detail_without_discovery(self):
        from chargegrid_app.screens.stations import _seed_details
        server = Server()
        api = client(server)
        params = {'limit': 20}
        server.data['stations'] = {'items': [{'id': 's1', 'name': 'A', 'connectors': [], 'discovery': {'x': 1}}],
                                   'total': 1}
        await api.request('GET', 'stations', params=params)
        _seed_details(SimpleNamespace(api=api), server.data['stations']['items'], 'stations', params)
        with api_cache.reading():
            detail = await api.request('GET', 'stations/s1')
        self.assertEqual(detail, {'id': 's1', 'name': 'A', 'connectors': []})
        self.assertEqual(server.count('stations/s1'), 0)
        self.now += 11  # mesma idade da lista: depois do frescor, o detalhe vai à rede
        with api_cache.reading():
            await api.request('GET', 'stations/s1')
        self.assertEqual(server.count('stations/s1'), 1)
        await api.close()


def fake_page():
    return SimpleNamespace(width=390, window=SimpleNamespace(), views=[SimpleNamespace()], add=Mock(),
                           update=Mock(), show_dialog=Mock(), pop_dialog=Mock(), platform=None)


class RevalidationTests(ClockMixin, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = Server({'me': {'id': 'u', 'name': 'Ana'}})
        self.api = client(self.server)
        with patch('chargegrid_app.app.ApiClient', return_value=self.api), \
                patch('chargegrid_app.app.Preferences') as preferences:
            preferences.return_value.load.return_value = True
            self.app = ChargeGridApp(fake_page())
        self.builds = []

    async def asyncTearDown(self):
        self.app.cancel_screen()
        await asyncio.sleep(0)
        await self.api.close()

    async def screen(self, app, **_):
        profile = await app.api.request('GET', 'me')
        self.builds.append(profile['name'])
        return ft.Column([ft.Text(profile['name'])])

    async def test_stale_screen_opens_at_once_and_is_rebuilt_silently_when_data_changed(self):
        await self.api.request('GET', 'me')
        self.now += 120
        self.server.data['me'] = {'id': 'u', 'name': 'Bia'}
        self.server.delay = 0.05
        with patch.dict('chargegrid_app.app.SCREENS', {'chat': self.screen}):
            await self.app.go('chat')
            self.assertEqual(self.builds, ['Ana'])  # sem esperar a rede
            await asyncio.sleep(0.15)
        self.assertEqual(self.builds, ['Ana', 'Bia'])
        self.assertEqual(self.server.count('me'), 2)
        self.assertGreater(self.app.scene.duration, 0)  # a transição volta ao normal depois do silêncio

    async def test_unchanged_data_is_not_rebuilt(self):
        await self.api.request('GET', 'me')
        self.now += 120
        with patch.dict('chargegrid_app.app.SCREENS', {'chat': self.screen}):
            await self.app.go('chat')
            await asyncio.sleep(0.05)
        self.assertEqual(self.builds, ['Ana'])

    async def test_edited_form_is_never_replaced_by_revalidation(self):
        await self.api.request('GET', 'me')
        self.now += 120
        self.server.data['me'] = {'id': 'u', 'name': 'Bia'}
        self.server.delay = 0.05
        field = ft.TextField(value='typed')

        async def form(app, **_):
            await app.api.request('GET', 'me')
            self.builds.append('form')
            return ft.Column([field])
        with patch.dict('chargegrid_app.app.SCREENS', {'profile': form}):
            await self.app.go('profile', mode='edit')
            field.value = 'changed by the person'
            await asyncio.sleep(0.15)
        self.assertEqual(self.builds, ['form'])

    async def test_screen_with_poll_updates_in_place_from_the_revalidated_answer(self):
        await self.api.request('GET', 'me')
        self.now += 120
        self.server.data['me'] = {'id': 'u', 'name': 'Bia'}
        self.server.delay = 0.05
        label = ft.Text()
        polled = []

        async def polled_screen(app, **_):
            label.value = (await app.api.request('GET', 'me'))['name']
            self.builds.append(label.value)

            async def update():
                label.value = (await app.api.request('GET', 'me'))['name']
                polled.append(label.value)
            app.set_poll(update, 30)
            return ft.Column([label])
        with patch.dict('chargegrid_app.app.SCREENS', {'home': polled_screen}):
            await self.app.go('home')
            await asyncio.sleep(0.15)
        self.assertEqual(self.builds, ['Ana'])  # não remontou
        self.assertEqual(polled, ['Bia'])
        self.assertEqual(label.value, 'Bia')
        self.assertEqual(self.server.count('me'), 2)  # o poll leu a resposta revalidada, sem pedir de novo

    async def test_live_charging_screen_is_always_built_from_the_network(self):
        await self.api.request('GET', 'charging-sessions/current')
        calls = self.server.count('charging-sessions/current')

        async def charging(app, **_):
            await app.api.request('GET', 'charging-sessions/current')
            return ft.Column()
        with patch.dict('chargegrid_app.app.SCREENS', {'charging': charging}):
            await self.app.go('charging')
        self.assertEqual(self.server.count('charging-sessions/current'), calls + 1)


class RoutePolicyTests(unittest.TestCase):
    def test_only_browsing_screens_open_from_stale_answers(self):
        from chargegrid_app.app import NETWORK_ROUTES, stale_allowed
        self.assertEqual(set(NETWORK_ROUTES), {'auth', 'charging', 'reservations'})
        for route, data in (('home', {}), ('stations', {}), ('stations', {'station_id': 's'}), ('history', {}),
                            ('history', {'receipt': 'x'}), ('profile', {}), ('operator', {}),
                            ('station_admin', {'station_id': 's', 'page': 'live'}), ('booking', {'step': 3})):
            self.assertTrue(stale_allowed(route, data), (route, data))
        for route, data in (('charging', {}), ('reservations', {'detail': True}), ('driver', {}),
                            ('operator', {'claim': True}), ('operator', {'connector_id': 'c'}),
                            ('booking', {'step': 6}), ('booking', {'step': 7})):
            self.assertFalse(stale_allowed(route, data), (route, data))


class PollTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        api = SimpleNamespace(session=SimpleNamespace(access_token='t'), close=Mock())
        with patch('chargegrid_app.app.ApiClient', return_value=api), \
                patch('chargegrid_app.app.Preferences') as preferences:
            preferences.return_value.load.return_value = True
            self.app = ChargeGridApp(fake_page())
        self.app.mark_refresh = Mock()

    async def asyncTearDown(self):
        self.app.cancel_screen()
        await asyncio.sleep(0)

    async def test_replacing_the_poll_from_inside_it_stops_the_old_loop(self):
        ticks = {'fast': 0, 'slow': 0}

        async def slow():
            ticks['slow'] += 1

        async def fast():
            ticks['fast'] += 1
            self.app.set_poll(slow, 10)  # ex.: fim da recarga troca o poll de 1 s por um de 60 s
        self.app.set_poll(fast, 0.01)
        await asyncio.sleep(0.08)
        self.assertEqual(ticks['fast'], 1)
        self.assertEqual(ticks['slow'], 0)

    async def test_screen_can_space_its_own_poll(self):
        ticks = []

        async def update():
            ticks.append(1)
            self.app.poll_interval = 10  # nada ativo: espaça
        self.app.set_poll(update, 0.01)
        await asyncio.sleep(0.08)
        self.assertEqual(len(ticks), 1)

    def test_home_polls_faster_only_with_an_active_reservation_or_charge(self):
        from chargegrid_app.screens import home
        self.assertEqual(home.poll_seconds(None, None), 20)
        self.assertEqual(home.poll_seconds({'id': 's'}, None), 10)
        self.assertEqual(home.poll_seconds(None, {'id': 'r'}), 10)


class NotificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_badge_queries_run_in_parallel_and_fail_independently(self):
        started, release = [], asyncio.Event()

        async def request(method, path, **_):
            started.append(path)
            await release.wait()
            if path == 'overstays/current':
                raise ApiError('sem rota', 404)
            return {'id': 's', 'status': 'charging', 'soc_percent': 95}
        app = SimpleNamespace(api=SimpleNamespace(request=request, is_demo=False), browsing_mode='consumer')
        task = asyncio.ensure_future(notifications.collect(app))
        await asyncio.sleep(0.01)
        self.assertEqual(sorted(started), ['charging-sessions/current', 'overstays/current'])
        release.set()
        await task


class LivePageTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_and_alerts_load_together_and_alerts_keep_refreshing_on_the_poll(self):
        from chargegrid_app.screens import station_ops
        from test_behavior import HandlerApp
        started, release = [], asyncio.Event()

        async def request(method, path, body=None, **kwargs):
            started.append(path)
            await release.wait()
            return {'items': []}
        app = HandlerApp()
        app.api = SimpleNamespace(request=request, is_demo=False)
        task = asyncio.ensure_future(station_ops.live_page(app, {'id': 's1'}))
        await asyncio.sleep(0.01)
        self.assertEqual(sorted(started), ['owner/alerts', 'owner/live'])  # em paralelo
        release.set()
        await task
        update = app.poll[0] if isinstance(app.poll, tuple) else app.poll
        started.clear()
        for _ in range(10):
            await update()
        self.assertEqual(started.count('owner/live'), 10)
        self.assertEqual(started.count('owner/alerts'), 1)  # a cada ~30 s, como antes


class ScreenSpeedTests(unittest.IsolatedAsyncioTestCase):
    """Orçamento de chamadas em série por tela (API com 20 ms de latência simulada)."""

    async def test_first_open_needs_at_most_one_wave_and_return_visits_need_none(self):
        harness = await Harness(latency=0.02).start('consumer')
        try:
            station = (await harness.demo.request('GET', 'stations', params={'limit': 1, 'offset': 0}))['items'][0]
            for label, route, params in (('home', 'home', {}), ('stations', 'stations', {}),
                                         ('detail', 'stations', {'station_id': station['id']}),
                                         ('history', 'history', {}), ('profile', 'profile', {})):
                row = await harness.open(label, route, **params)
                self.assertLessEqual(row['serial'], 1, row)
            harness.advance(30)
            for route in ('home', 'stations', 'history', 'profile'):
                row = await harness.open(route, route)
                self.assertEqual(row['calls'], 0, row)
        finally:
            await harness.close()

    async def test_vendor_screens_load_in_parallel(self):
        harness = await Harness(latency=0.1).start('vendor')
        try:
            owned = (await harness.demo.request('GET', 'operator/stations', params={'limit': 100, 'offset': 0}))
            sid = owned['items'][0]['id']
            harness.app.api.cache.entries.clear()  # sem nada guardado: só o paralelismo conta
            for route, params in (('home', {}), ('history', {'manage': True}),
                                  ('history', {'manage': True, 'page': 'energy'}),
                                  ('station_admin', {'station_id': sid, 'page': 'live'})):
                harness.app.api.cache.entries.clear()
                row = await harness.open(route, route, **params)
                self.assertLessEqual(row['serial'], 1, (route, params, row))
        finally:
            await harness.close()

    def test_serial_depth(self):
        calls = [{'start': 0, 'end': 1}, {'start': 0, 'end': 1}, {'start': 1, 'end': 2}, {'start': 0.5, 'end': 3}]
        self.assertEqual(serial_depth(calls), 2)


if __name__ == '__main__':
    unittest.main()
