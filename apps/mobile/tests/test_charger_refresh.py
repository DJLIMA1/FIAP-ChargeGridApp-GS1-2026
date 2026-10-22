"""Visible charger pages follow telemetry without rebuilding the editable form."""

import asyncio
import copy
import unittest
from unittest.mock import Mock, patch

import flet as ft

from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DemoApi
from chargegrid_app.screens import operator, station_admin
from chargegrid_app.services.charger_refresh import StationRefresh
from test_behavior import HandlerApp, click, descendants
from test_charger_link_ui import ONLINE, SCREEN, point
from test_seller_flow_fixes import fields, station_fixture, texts


class ChargerRefreshTests(unittest.IsolatedAsyncioTestCase):
    def station(self, link='online'):
        result = station_fixture()
        result['connectors'] = [point(active=True, online=link == 'online', charger_address=1,
                                     charger_link={**ONLINE, 'link': link}, screen=SCREEN)]
        result['screen_online'] = True
        return result

    async def test_list_updates_offline_and_recovery_without_navigation_or_duplicate_rows(self):
        app = HandlerApp()
        app.set_poll = Mock(wraps=app.set_poll)
        page = station_admin._connectors_page(app, self.station())
        app.set_poll.assert_called_once_with(app.poll, 2)
        holder = next(c for c in descendants(page) if c.data == 'charger-row:point')
        for link, label in [('offline', 'Offline'), ('online', 'Online')]:
            app.api.request.return_value = self.station(link)
            await app.poll()
            self.assertIs(holder, next(c for c in descendants(page) if c.data == 'charger-row:point'))
            self.assertIn(label, texts(holder))
            self.assertNotIn('Central da estação', texts(page))
            self.assertEqual(texts(page).count('CG-POINT'), 1)
        app.go.assert_not_awaited()

    async def test_detail_keeps_input_identity_values_selection_and_handler_during_polls(self):
        app = HandlerApp()
        page = await operator.connector_form(app, 'station', self.station()['connectors'][0])
        original = fields(page)
        power = original['Potência']
        address = original[operator.CHARGER_FIELD]
        power.value, address.value = '19,5', '23'
        address.selection = ft.TextSelection(base_offset=1, extent_offset=1)
        save = next(c for c in descendants(page) if isinstance(getattr(c, 'content', None), ft.Text)
                    and c.content.value == 'Salvar alterações')
        handler = save.on_click
        for link in ('offline', 'online', 'offline'):
            fresh = self.station(link)
            fresh['connectors'][0]['power_kw'] = '44'
            app.api.request.return_value = fresh
            await app.poll()
            current = fields(page)
            self.assertIs(current['Potência'], power)
            self.assertIs(current[operator.CHARGER_FIELD], address)
            self.assertEqual((power.value, address.value, address.selection.base_offset), ('19,5', '23', 1))
            self.assertIs(save.on_click, handler)
        self.assertIn('Offline', texts(page))
        self.assertNotIn('Rotacionar', texts(page))
        app.go.assert_not_awaited()

    async def test_detail_opens_from_fresh_station_instead_of_navigation_snapshot(self):
        app = HandlerApp()
        app.api.request.side_effect = [{'operator_enabled': True}, self.station('offline')]
        stale = self.station()['connectors'][0]
        page = await operator.build(app, station_id='station', connector_id='point', connector=stale)
        self.assertIn('Offline', texts(page))
        self.assertEqual([call.args[:2] for call in app.api.request.await_args_list],
                         [('GET', 'me'), ('GET', 'stations/station')])

    async def test_reads_are_serial_and_old_mutation_route_or_hidden_results_are_discarded(self):
        for reason in ('mutation', 'route', 'hidden'):
            app = HandlerApp()
            app.generation = 1
            future = asyncio.get_running_loop().create_future()
            started = asyncio.Event()

            async def request(*_args, **_kwargs):
                started.set()
                return await future

            app.api.request.side_effect = request
            refresh = StationRefresh(app, 'station')
            task = asyncio.create_task(refresh.read())
            await started.wait()
            self.assertIsNone(await refresh.read())
            self.assertEqual(app.api.request.await_count, 1)
            if reason == 'mutation':
                refresh.invalidate()
            elif reason == 'route':
                app.generation += 1
            else:
                app.backgrounded = True
            future.set_result(copy.deepcopy(self.station()))
            self.assertIsNone(await task)

    async def test_hidden_or_departed_page_does_not_start_another_request(self):
        app = HandlerApp()
        app.generation = 1
        refresh = StationRefresh(app, 'station')
        app.backgrounded = True
        self.assertIsNone(await refresh.read())
        app.backgrounded = False
        app.generation = 2
        self.assertIsNone(await refresh.read())
        app.api.request.assert_not_awaited()

    async def test_station_data_keeps_maintenance_and_reset_poll_without_touching_station_draft(self):
        clock = [0.0]
        app = HandlerApp()
        app.back = lambda _event=None: None
        app.page.show_dialog, app.page.pop_dialog = Mock(), Mock()
        with patch('httpx.AsyncClient', side_effect=AssertionError('Demo must stay local')):
            app.api = DemoApi(clock=lambda: clock[0])
            await app.api.login(DEMO_EMAIL, DEMO_PASSWORD)
            claimed = await app.api.request('POST', 'ownership/claim', {'token': app.api.new_claim_token()})
            page = await station_admin.build(app, station_id=claimed['station_id'], page='data')
            self.assertIn('Central CG-', texts(page))  # status e manutenção num só cartão por central
            self.assertNotIn('Central da estação', texts(page))
            self.assertIsNone(app.poll)
            await click(page, 'Restaurar')(None)
            dialog = app.page.show_dialog.call_args.args[0]
            self.assertIn('O Wi-Fi não será alterado', dialog.content.value)
            await dialog.actions[1].on_click(None)
            self.assertIsNotNone(app.poll)
            name = next(c for c in descendants(page) if isinstance(c, ft.TextField))
            name.value = 'Still typing'
            clock[0] += 3
            await app.poll()
            self.assertIn('Restauração confirmada', texts(page))
            self.assertIs(name, next(c for c in descendants(page) if isinstance(c, ft.TextField)))
            self.assertEqual(name.value, 'Still typing')
            fresh = await app.api.request('GET', f"stations/{claimed['station_id']}")
            self.assertTrue(next(p for p in fresh['connectors'] if p['id'] == claimed['connector_id'])['retired'])
            await app.api.close()

    async def test_secret_popup_still_erases_the_key_when_closed(self):
        app = HandlerApp()
        app.page.show_dialog, app.page.pop_dialog = Mock(), Mock()
        operator.show_key(app, {'device_id': 'test-central', 'device_key': 'test-only-key'})
        dialog = app.page.show_dialog.call_args.args[0]
        secret = dialog.content.controls[1]
        await dialog.actions[0].on_click(None)
        self.assertEqual(secret.value, '')
        app.page.pop_dialog.assert_called_once()
