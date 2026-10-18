"""Vendor stations: landing list, station detail, data, connector power and battery limit."""
import unittest
from types import SimpleNamespace

import flet as ft

from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DemoApi
from chargegrid_app.screens import operator, station_admin
from chargegrid_app.services import station_settings
from test_behavior import HandlerApp, descendants


def texts(screen):
    return ' '.join(str(c.value) for c in descendants(screen) if isinstance(c, ft.Text))


def press(screen, label):
    """on_click of the container whose subtree shows ``label`` (innermost match)."""
    best = None
    for item in descendants(screen):
        if getattr(item, 'on_click', None) and isinstance(item, ft.Container) and label in texts(item):
            best = item
    return best.on_click


async def demo_app():
    app = HandlerApp()
    app.back = lambda event=None: None
    app.api = DemoApi()
    await app.api.login(DEMO_EMAIL, DEMO_PASSWORD)
    app.profile = await app.api.request('GET', 'me')
    app.api.is_demo = True
    return app


class StationAdminTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        station_settings.reset_demo()

    async def test_list_opens_station_detail_and_keeps_operator_actions(self):
        app = await demo_app()
        screen = await operator.build(app)
        copy = texts(screen)
        self.assertIn('Suas Estações', copy)
        self.assertIn('Fale com o ChatBot', copy)
        self.assertIn('Gerenciar cupons', copy)
        self.assertIn('Adicionar equipamento simulado', copy)
        await press(screen, 'Marginal Pinheiros')(None)
        self.assertEqual(app.go.await_args.args[0], 'station_admin')
        await press(screen, 'Adicionar equipamento simulado')(None)
        app.go.assert_awaited_with('operator', claim=True)
        await app.api.close()

    async def test_detail_menu_routes(self):
        app = await demo_app()
        sid = (await app.api.request('GET', 'operator/stations'))['items'][0]['id']
        screen = await station_admin.build(app, station_id=sid)
        self.assertIn('Estação CG-001', texts(screen))
        for label, expected in (('Dados da estação', ('station_admin', {'station_id': sid, 'page': 'data'})),
                                ('Potência por conector', ('station_admin', {'station_id': sid, 'page': 'power'})),
                                ('Tarifas dinâmicas', ('tariffs', {'station_id': sid})),
                                ('Limite de bateria', ('station_admin', {'station_id': sid, 'page': 'battery'}))):
            await press(screen, label)(None)
            self.assertEqual((app.go.await_args.args[0], app.go.await_args.kwargs), expected)
        await app.api.close()

    async def test_data_page_patches_name_address_and_status(self):
        app = await demo_app()
        sid = (await app.api.request('GET', 'operator/stations'))['items'][0]['id']
        screen = await station_admin.build(app, station_id=sid, page='data')
        fields = [c for c in descendants(screen) if isinstance(c, ft.TextField)]
        self.assertEqual(fields[2].value, 'CG-001')
        self.assertTrue(fields[2].read_only)
        fields[0].value = 'Marginal Pinheiros'
        await fields[0].on_blur(SimpleNamespace(control=fields[0]))
        self.assertEqual((await app.api.request('GET', f'stations/{sid}'))['name'], 'Marginal Pinheiros')
        await press(screen, 'Inativa')(None)
        self.assertFalse((await app.api.request('GET', f'stations/{sid}'))['active'])
        await app.api.close()

    async def test_power_slider_patches_connector_power(self):
        app = await demo_app()
        station = (await app.api.request('GET', 'operator/stations'))['items'][0]
        screen = await station_admin.build(app, station_id=station['id'], page='power')
        sliders = [c for c in descendants(screen) if isinstance(c, ft.Slider)]
        self.assertEqual(len(sliders), len(station['connectors']))
        sliders[0].value = 22.0
        await sliders[0].on_change_end(SimpleNamespace(control=sliders[0]))
        point = (await app.api.request('GET', f'stations/{station["id"]}'))['connectors'][0]
        self.assertEqual(float(point['power_kw']), 22.0)
        await app.api.close()

    async def test_battery_rule_is_saved_locally_without_api_calls(self):
        app = HandlerApp()
        app.back = lambda event=None: None
        app.api.is_demo = True
        app.profile = {'id': 'u'}
        app.api.request.return_value = {'id': 's', 'name': 'Posto', 'address': 'Rua', 'connectors': []}
        screen = await station_admin.build(app, station_id='s', page='battery')
        self.assertIn('80%', texts(screen))
        slider = next(c for c in descendants(screen) if isinstance(c, ft.Slider))
        slider.value = 65
        await slider.on_change(SimpleNamespace(control=slider))
        self.assertIn('65%', texts(screen))
        calls = app.api.request.await_count
        await press(screen, 'Salvar regra')(None)
        self.assertEqual(app.api.request.await_count, calls)
        self.assertEqual(station_settings.battery_rule(app, 's'), {'limit': 65, 'active': True, 'action': 'notify'})

    def test_battery_rule_validation(self):
        app = HandlerApp()
        app.api.is_demo = True
        from chargegrid_app.api_client import ApiError
        with self.assertRaises(ApiError):
            station_settings.save_battery_rule(app, 's', 140)
        self.assertEqual(station_settings.battery_rule(app, 'other')['limit'], 80)


if __name__ == '__main__':
    unittest.main()
