"""Modo motorista: rotas demo (mesmo motor da API), tela, persistência local e navegação."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import flet as ft

from chargegrid_app.api_client import ApiError
from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DemoApi
from chargegrid_app.navigation import SCREENS, active_tab, parent_route
from chargegrid_app.preferences import DriverProfileStore
from chargegrid_app.screens import driver, home
from chargegrid_app.services import driver as helpers

SE = {'lat': -23.5505, 'lng': -46.6333}
# 15h UTC = 12h em São Paulo, terça-feira.
TUESDAY_NOON = datetime(2026, 10, 13, 15, tzinfo=timezone.utc)


def descendants(control):
    if control is None:
        return
    yield control
    content = getattr(control, 'content', None)
    if content is not None and not isinstance(content, str):
        yield from descendants(content)
    for child in getattr(control, 'controls', []) or []:
        yield from descendants(child)


def texts(control):
    return [item.value for item in descendants(control) if isinstance(item, ft.Text) and item.value]


def click(control, label):
    return next(item.on_click for item in descendants(control)
                if getattr(item, 'on_click', None) and isinstance(getattr(item, 'content', None), ft.Text)
                and item.content.value == label)


def fields(control):
    return {item.label: item for item in descendants(control) if isinstance(item, (ft.TextField, ft.Dropdown))}


class DriverApp:
    def __init__(self, api):
        self.api = api
        self.page = SimpleNamespace(update=Mock(), width=400)
        self.go = AsyncMock()
        self.notices = []
        self.profile = {'name': 'Ana'}

    def action(self, operation):
        async def handler(event=None):
            await operation()
        return handler

    def link(self, route, **data):
        async def handler(event=None):
            await self.go(route, **data)
        return handler

    def notice(self, message):
        self.notices.append(message)


class DemoDriverRoutesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.api = DemoApi(start_at=TUESDAY_NOON)
        await self.api.login(DEMO_EMAIL, DEMO_PASSWORD)

    async def asyncTearDown(self):
        await self.api.close()

    async def test_profile_plan_and_next_stop_use_core_engine_and_partner_network(self):
        before = (await self.api.request('GET', 'stations'))['total']
        profile = await self.api.request('GET', 'driver/profile')
        self.assertFalse(profile['saved'])
        self.assertEqual(profile['vehicle']['preset'], 'byd_dolphin')
        self.assertTrue(any(p['key'] == 'renault_kwid_etech' for p in profile['presets']))
        stations = (await self.api.request('GET', 'stations'))['items']
        # A rede parceira já aparece na primeira busca pública (lista, busca IA e chat).
        self.assertEqual(len(stations), before)
        self.assertGreater(before, 1)
        self.assertTrue(any(a['kind'] == 'restaurante' for s in stations for a in s.get('amenities', [])))
        saved = await self.api.request('PUT', 'driver/profile', {
            'vehicle': {'preset': 'byd_dolphin'},
            'preferences': {'shift_start': '14:00', 'shift_end': '22:00',
                            'meals': [{'kind': 'jantar', 'start': '20:00', 'duration_minutes': 45, 'flex_minutes': 30}]}})
        self.assertTrue(saved['saved'])
        plan = await self.api.request('POST', 'driver/plan', {'soc_percent': 65, **SE, 'mode': 'full_shift'})
        self.assertEqual((plan['window']['start'], plan['window']['end']), ('14:00', '22:00'))
        self.assertTrue(plan['estimate'])
        self.assertEqual(plan['demand']['signals'][0]['status'], 'demo')
        dinner = [stop for stop in plan['stops'] if stop['meal'] == 'Jantar']
        self.assertTrue(dinner and dinner[0]['amenity']['kind'] in ('restaurante', 'shopping'))
        self.assertFalse(any(stop['in_peak'] for stop in plan['stops']))
        self.assertGreaterEqual(plan['totals']['net_profit'], plan['baseline']['totals']['net_profit'])
        station = await self.api.request('GET', f"stations/{dinner[0]['station_id']}")
        self.assertTrue(station['connectors'])
        quick = await self.api.request('POST', 'driver/next-stop', {'soc_percent': 16, **SE})
        self.assertEqual(quick['recommendation']['action'], 'stop_now')
        self.assertTrue(quick['alternatives'])

    async def test_demo_validation_matches_api_contract(self):
        for path, body in [
            ('driver/plan', {'soc_percent': 150}), ('driver/plan', {'soc_percent': 50, 'lat': 1}),
            ('driver/plan', {'soc_percent': 50, 'mode': 'amanha'}), ('driver/plan', {'soc_percent': 50, 'x': 1}),
            ('driver/next-stop', {'soc_percent': 'NaN'}),
        ]:
            with self.subTest(body=body), self.assertRaises(ApiError):
                await self.api.request('POST', path, body)
        with self.assertRaises(ApiError) as caught:
            await self.api.request('PUT', 'driver/profile', {'preferences': {'reserve_percent': 45, 'max_charge_percent': 50}})
        self.assertEqual(caught.exception.code, 'invalid_driver_profile')
        with self.assertRaises(ApiError):
            await self.api.request('DELETE', 'driver/profile')

    async def test_owner_can_edit_amenities_in_demo(self):
        station = (await self.api.request('GET', 'operator/stations'))['items'][0]
        updated = await self.api.request('PATCH', f"stations/{station['id']}",
                                         {'amenities': [{'kind': 'restaurante', 'name': 'Bistrô', 'distance_m': 30}]})
        self.assertEqual(updated['amenities'], [{'kind': 'restaurante', 'name': 'Bistrô', 'distance_m': 30}])
        for bad in ([{'kind': 'cinema'}], 'restaurante', [{'kind': 'cafe', 'distance_m': -1}]):
            with self.subTest(bad=bad), self.assertRaises(ApiError):
                await self.api.request('PATCH', f"stations/{station['id']}", {'amenities': bad})


class DriverScreenTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.api = DemoApi(start_at=TUESDAY_NOON)
        await self.api.login(DEMO_EMAIL, DEMO_PASSWORD)
        self.app = DriverApp(self.api)

    async def asyncTearDown(self):
        await self.api.close()

    async def test_plan_renders_profit_timeline_soc_chart_and_station_links(self):
        screen = await driver.build(self.app)
        visible = texts(screen)
        self.assertIn('Modo motorista', visible)
        self.assertIn('Estimativas', visible)
        form = fields(screen)
        self.assertEqual(form['Modelo do carro'].value, 'byd_dolphin')
        form['Bateria agora (%)'].value = '45'
        await click(screen, 'Planejar meu turno')(None)
        visible = texts(screen)
        for label in ('LUCRO LÍQUIDO ESTIMADO DO TURNO', 'LINHA DO TEMPO DO TURNO', 'BATERIA PROJETADA (SoC)',
                      'Paradas recomendadas', 'Pico estimado'):
            self.assertIn(label, visible)
        self.assertTrue(any('vs. recarregar só quando a bateria fica baixa' in text for text in visible))
        plan = self.app.driver_state['plan']
        self.assertEqual(plan['mode'], 'full_shift')
        await click(screen, 'Ver posto')(None)
        self.app.go.assert_awaited_with('stations', station_id=plan['stops'][0]['station_id'])
        saved = await self.api.request('GET', 'driver/profile')
        self.assertTrue(saved['saved'])  # perfil enviado ao "servidor" demo ao planejar
        semantics = [item.label for item in descendants(screen) if isinstance(item, ft.Semantics) and item.label]
        self.assertTrue(any(label.startswith('Plano de') for label in semantics))
        self.assertTrue(any(label.startswith('Bateria projetada') for label in semantics))
        # A volta para a tela reaproveita o último plano sem recalcular.
        again = await driver.build(self.app)
        self.assertIn('LINHA DO TEMPO DO TURNO', texts(again))

    async def test_next_stop_offers_reservation_of_recommended_point(self):
        screen = await driver.build(self.app)
        fields(screen)['Bateria agora (%)'].value = '16'
        await click(screen, 'Próxima parada agora')(None)
        self.assertIn('PRÓXIMA PARADA AGORA', texts(screen))
        recommendation = self.app.driver_state['next']['recommendation']
        self.assertEqual(recommendation['action'], 'stop_now')
        await click(screen, 'Reservar')(None)
        self.app.go.assert_awaited_with('reservations')
        current = await self.api.request('GET', 'reservations/current')
        self.assertEqual(current['connector_id'], recommendation['connector_id'])

    async def test_invalid_form_values_are_explained_before_any_request(self):
        screen = await driver.build(self.app)
        form = fields(screen)
        for label, value in (('Bateria agora (%)', '140'), ('Início do turno (HH:MM)', '25:99'),
                             ('Ganho médio por hora rodando (R$)', 'abc')):
            original = form[label].value
            form[label].value = value
            with self.subTest(label=label), self.assertRaises(ApiError):
                await click(screen, 'Planejar meu turno')(None)
            form[label].value = original
        self.assertNotIn('plan', self.app.driver_state)

    async def test_real_account_uses_local_profile_and_survives_offline_profile_save(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {'FLET_APP_STORAGE_DATA': directory}):
            DriverProfileStore().save({'vehicle': {'preset': 'byd_seal'},
                                       'preferences': {'shift_start': '06:00', 'shift_end': '14:00'},
                                       'soc_percent': 70})
            demo = DemoApi(start_at=TUESDAY_NOON)
            await demo.login(DEMO_EMAIL, DEMO_PASSWORD)
            calls = []

            async def request(method, path, body=None, **kwargs):
                calls.append((method, path))
                if method == 'PUT':
                    raise ApiError('Sem conexão', 0)
                return await demo.request(method, path, body, **kwargs)

            api = SimpleNamespace(is_demo=False, request=request, new_key=lambda: 'key')
            app = DriverApp(api)
            screen = await driver.build(app)
            form = fields(screen)
            self.assertEqual(form['Modelo do carro'].value, 'byd_seal')
            self.assertEqual(form['Início do turno (HH:MM)'].value, '06:00')
            self.assertEqual(form['Bateria agora (%)'].value, '70')
            form['Bateria agora (%)'].value = '55'
            await click(screen, 'Planejar meu turno')(None)
            self.assertIn(('PUT', 'driver/profile'), calls)
            self.assertIn(('POST', 'driver/plan'), calls)
            stored = json.loads((Path(directory) / 'driver_profile.json').read_text())
            self.assertEqual(stored['soc_percent'], 55)
            await demo.close()


class DriverIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def test_store_roundtrip_and_malformed_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'driver.json'
            store = DriverProfileStore(path)
            self.assertIsNone(store.load())
            self.assertTrue(store.save({'vehicle': {'preset': 'byd_seal'}, 'preferences': {}}))
            self.assertEqual(store.load()['vehicle']['preset'], 'byd_seal')
            for value in ('[]', '{"vehicle": 1}', 'nao-json'):
                path.write_text(value)
                self.assertIsNone(store.load())

    def test_navigation_exposes_driver_route_under_home(self):
        self.assertIn('driver', SCREENS)
        self.assertEqual(active_tab('driver', {}, 'consumer'), 'home')
        self.assertEqual(parent_route('driver', {}), ('home', {}))

    def test_helpers_validate_and_describe(self):
        self.assertEqual(helpers.clock('8:05', 'x'), '08:05')
        with self.assertRaises(ApiError):
            helpers.clock('99:00', 'o horário')
        with self.assertRaises(ApiError):
            helpers.number('NaN', 'a bateria', 0, 100)
        self.assertEqual(helpers.number('12,5', 'x', 0, 100), 12.5)
        meal = helpers.build_meal('jantar', True, '20:00', '45', 'flex')
        self.assertTrue(meal['flexible'])
        self.assertIn('estimativa', helpers.vehicle_summary({'preset': 'byd_dolphin'}))

    async def test_home_highlights_driver_mode(self):
        app = DriverApp(SimpleNamespace(is_demo=False))
        state = {'reservations/current': None, 'charging-sessions/current': None,
                 'stations': {'items': [], 'total': 0}, 'me/summary': {}}

        async def request(method, path, **kwargs):
            return state[path]
        app.api.request = request
        app.set_poll = lambda callback, interval: None
        with patch('chargegrid_app.services.maps.build_map_png', return_value=b'png'):
            screen = await home.build(app)
        visible = texts(screen)
        self.assertIn('MODO MOTORISTA DE APP', visible)
        self.assertLess(visible.index('MODO MOTORISTA DE APP'), visible.index('GASTO ESTIMADO NESTE MÊS'))
        await click(screen, 'Planejar meu turno')(None)
        app.go.assert_awaited_once_with('driver')


if __name__ == '__main__':
    unittest.main()
