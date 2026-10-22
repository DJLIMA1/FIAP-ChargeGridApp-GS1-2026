"""Remover estação: caixa de perigo na página da estação, confirmação, ``DELETE stations/{id}`` e a demo."""
import unittest
from unittest.mock import Mock

from chargegrid_app.api_client import ApiError
from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DEMO_PRESENCE_CODE, DemoApi
from chargegrid_app.screens import station_admin
from chargegrid_app.ui import theme
from test_behavior import HandlerApp, click, descendants
from test_seller_flow_fixes import station_fixture, texts

ONLINE_MESSAGE = ('Restaure a central (Dados da estação → Restaurar) antes de remover a estação: '
                  'ela volta ao QR de fábrica e pode ser usada em outro posto.')


def seller_app():
    app = HandlerApp()
    app.back = lambda event=None: None
    return app


class RemoveStationScreenTests(unittest.IsolatedAsyncioTestCase):
    def page(self, app):
        return station_admin._main_page(app, station_fixture(), 'CG-001')

    async def open(self, app):
        app.page.show_dialog, app.page.pop_dialog = Mock(), Mock()
        screen = self.page(app)
        await click(screen, station_admin.REMOVE_STATION_LABEL)(None)
        return screen, app.page.show_dialog.call_args.args[0]

    def test_danger_box_is_the_last_item_of_the_station_page(self):
        screen = self.page(seller_app())
        boxes = [item for item in descendants(screen) if getattr(item, 'data', None) == 'remove-station']
        self.assertEqual(len(boxes), 1)
        copy = texts(boxes[0])
        self.assertIn('Remover estação', copy)
        self.assertIn('Fecha o posto: ele sai do mapa e da sua lista. O histórico de recargas continua.', copy)
        self.assertTrue(texts(screen).rstrip().endswith(copy.rstrip()))  # por último na página

    async def test_confirm_dialog_is_destructive_and_cancel_sends_nothing(self):
        app = seller_app()
        _, dialog = await self.open(app)
        self.assertEqual(dialog.title.value, 'Remover Posto Central?')
        self.assertEqual(dialog.content.value,
                         'A estação sai do mapa e da sua lista. Recargas e recibos continuam no histórico.')
        cancel, remove = dialog.actions
        self.assertEqual((cancel.content, remove.content), ('Cancelar', 'Remover'))
        self.assertEqual(remove.style.color, theme.RED)
        cancel.on_click(None)
        app.api.request.assert_not_awaited()

    async def test_confirm_deletes_and_goes_to_the_stations_list(self):
        app = seller_app()
        app.api.request.return_value = None  # 204
        _, dialog = await self.open(app)
        await dialog.actions[1].on_click(None)
        app.api.request.assert_awaited_once_with('DELETE', 'stations/station')
        self.assertEqual(app.notices[-1], 'Estação Posto Central removida.')
        app.go.assert_awaited_once_with('operator')

    async def test_api_conflicts_are_explained(self):
        for code, message, expected in (
                ('station_busy', 'x', 'Há recarga, reserva ou pedido do totem em andamento. Encerre antes de remover.'),
                ('central_online', ONLINE_MESSAGE, ONLINE_MESSAGE)):
            app = seller_app()
            app.api.request.side_effect = ApiError(message, 409, code)
            _, dialog = await self.open(app)
            with self.assertRaises(ApiError) as caught:
                await dialog.actions[1].on_click(None)
            self.assertEqual(str(caught.exception), expected)
            self.assertEqual(caught.exception.code, code)
            app.go.assert_not_awaited()
            self.assertEqual(app.notices, [])


class DemoRemoveStationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = [0.0]
        self.api = DemoApi(clock=lambda: self.clock[0])
        await self.api.login(DEMO_EMAIL, DEMO_PASSWORD)
        self.station = (await self.api.request('GET', 'operator/stations'))['items'][0]
        self.ids = {point['id'] for point in self.station['connectors']}

    def devices(self):
        return [d for d in self.api._devices.values() if d['connector_id'] in self.ids]

    def turn_off_centrals(self):
        for device in self.devices():
            device['online'] = False

    async def remove(self):
        return await self.api.request('DELETE', f"stations/{self.station['id']}")

    async def test_online_central_is_refused(self):
        self.assertTrue(any(d['online'] and not d['revoked'] for d in self.devices()))
        with self.assertRaises(ApiError) as caught:
            await self.remove()
        self.assertEqual((caught.exception.status, caught.exception.code, str(caught.exception)),
                         (409, 'central_online', ONLINE_MESSAGE))

    async def test_busy_station_is_refused(self):
        point = next(p for p in self.station['connectors'] if p['active'] and p.get('available'))
        await self.api.request('POST', 'charging-sessions', {
            'presence_code': DEMO_PRESENCE_CODE, 'public_code': point['public_code'], 'max_duration_minutes': 30},
            key=self.api.new_key())
        self.turn_off_centrals()
        with self.assertRaises(ApiError) as caught:
            await self.remove()
        self.assertEqual((caught.exception.status, caught.exception.code), (409, 'station_busy'))

    async def test_removed_station_disappears_and_history_stays(self):
        sessions_before = (await self.api.request('GET', 'operator/charging-sessions'))['items']
        self.turn_off_centrals()
        self.assertIsNone(await self.remove())
        sid = self.station['id']
        self.assertNotIn(sid, [s['id'] for s in (await self.api.request('GET', 'operator/stations'))['items']])
        self.assertNotIn(sid, [s['id'] for s in (await self.api.request('GET', 'stations'))['items']])
        for path in (f'stations/{sid}',):
            with self.assertRaises(ApiError) as caught:
                await self.api.request('GET', path)
            self.assertEqual(caught.exception.status, 404)
        for method, body in (('PATCH', {'active': True}), ('DELETE', None)):
            with self.assertRaises(ApiError) as caught:
                await self.api.request(method, f'stations/{sid}', body)
            self.assertEqual(caught.exception.status, 404)
        self.assertTrue(all(d['revoked'] for d in self.devices()))
        summary = await self.api.request('GET', 'operator/summary')
        self.assertEqual(summary['stations'], 0)
        overview = await self.api.request('GET', 'owner/overview')
        self.assertEqual(overview['stations']['total'], 0)
        # Histórico: as recargas antigas continuam listadas.
        sessions_after = (await self.api.request('GET', 'operator/charging-sessions'))['items']
        self.assertEqual([s['id'] for s in sessions_after], [s['id'] for s in sessions_before])


if __name__ == '__main__':
    unittest.main()
