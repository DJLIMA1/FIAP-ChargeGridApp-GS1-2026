"""Modo motorista: rotas demo (mesmo motor da API), tela, persistência local e navegação."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import flet as ft

import chargegrid_core.driver as driver_package
from chargegrid_app.api_client import ApiError
from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DemoApi
from chargegrid_app.navigation import SCREENS, active_tab, parent_route
from chargegrid_app.preferences import DriverProfileStore
from chargegrid_app.screens import driver, home
from chargegrid_app.services import driver as helpers
from chargegrid_app.services import geolocation, vehicle_state
from chargegrid_app.services.search_location import SearchLocation

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


def shown(control):
    """Like ``descendants`` but skips hidden controls (what the driver actually sees)."""
    if control is None or getattr(control, 'visible', True) is False:
        return
    yield control
    content = getattr(control, 'content', None)
    if content is not None and not isinstance(content, str):
        yield from shown(content)
    if isinstance(control, ft.ExpansionTile):
        return  # collapsed section
    for child in getattr(control, 'controls', []) or []:
        yield from shown(child)


def texts(control):
    return [item.value for item in descendants(control) if isinstance(item, ft.Text) and item.value]


def click(control, label):
    return next(item.on_click for item in descendants(control)
                if getattr(item, 'on_click', None) and isinstance(getattr(item, 'content', None), ft.Text)
                and item.content.value == label)


def fields(control):
    return {item.label: item for item in descendants(control) if isinstance(item, (ft.TextField, ft.Dropdown))}


class FakeGeolocator:
    """Stand-in for flet_geolocator.Geolocator (the extension only exists in the phone build)."""

    def __init__(self, status='whileInUse', position=(-23.5614, -46.6559), grant=True, last=None):
        self.status, self.position, self.grant, self.last = status, position, grant, last
        self.asked = 0

    async def get_permission_status(self):
        return SimpleNamespace(value=self.status)

    async def request_permission(self):
        self.asked += 1
        if self.grant:
            self.status = 'whileInUse'
        return SimpleNamespace(value=self.status)

    async def get_last_known_position(self):
        return self.last

    async def get_current_position(self):
        lat, lng = self.position
        return SimpleNamespace(latitude=lat, longitude=lng, timestamp=datetime.now(timezone.utc))


def battery(control):
    """The old "Bateria agora" slider; the screen no longer asks the battery (hidden SoC), so ``None``."""
    return next((item for item in descendants(control) if isinstance(item, ft.Slider)), None)


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


@patch.object(driver_package, 'DISCONTINUED', False)  # código guardado do Modo motorista descontinuado
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
        self.assertEqual(plan['demand']['signals'][0]['status'], 'simulado')
        self.assertEqual(plan['demand']['weather']['label'], '23° · nublado · chuva às 18h (simulado)')
        self.assertTrue(any(alert['code'] == 'rain' and 'simulado' in alert['message'] for alert in plan['alerts']))
        dinner = [stop for stop in plan['stops'] if stop['meal'] == 'Jantar']
        self.assertTrue(dinner and dinner[0]['amenity']['kind'] in ('restaurante', 'shopping'))
        self.assertFalse(any(stop['in_peak'] for stop in plan['stops']))
        self.assertGreaterEqual(plan['totals']['net_profit'], plan['baseline']['totals']['net_profit'])
        station = await self.api.request('GET', f"stations/{dinner[0]['station_id']}")
        self.assertTrue(station['connectors'])
        quick = await self.api.request('POST', 'driver/next-stop', {'soc_percent': 16, **SE})
        self.assertEqual(quick['recommendation']['action'], 'stop_now')
        self.assertTrue(quick['alternatives'])
        context = await self.api.request('GET', 'driver/context', params=SE)
        # 12h, saved shift 14:00–22:00: the next shift, with today's peaks and the simulated weather.
        self.assertFalse(context['in_shift'])
        self.assertEqual((context['window']['start'], context['shift_source']), ('14:00', 'informado'))
        self.assertTrue(context['estimate'] and context['demand']['peaks'])
        self.assertEqual(context['weather']['status'], 'simulado')
        self.assertEqual(context['earnings']['label'], 'R$ 38/h estimado')

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
        with self.assertRaises(ApiError):
            await self.api.request('GET', 'driver/context', params={'lat': -23.5})

    async def test_owner_can_edit_amenities_in_demo(self):
        station = (await self.api.request('GET', 'operator/stations'))['items'][0]
        updated = await self.api.request('PATCH', f"stations/{station['id']}",
                                         {'amenities': [{'kind': 'restaurante', 'name': 'Bistrô', 'distance_m': 30}]})
        self.assertEqual(updated['amenities'], [{'kind': 'restaurante', 'name': 'Bistrô', 'distance_m': 30}])
        for bad in ([{'kind': 'cinema'}], 'restaurante', [{'kind': 'cafe', 'distance_m': -1}]):
            with self.subTest(bad=bad), self.assertRaises(ApiError):
                await self.api.request('PATCH', f"stations/{station['id']}", {'amenities': bad})


@patch.object(driver_package, 'DISCONTINUED', False)  # código guardado do Modo motorista descontinuado
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
        # Reference layout without the battery card: car line, collapsible shift, "O APP já considera", buttons.
        self.assertNotIn('Bateria agora', visible)
        self.assertIsNone(battery(screen))
        self.assertFalse(any(text.endswith('%') for text in visible))  # the hidden SoC is never a number here
        for label in ('BYD Dolphin - 321 km de autonomia', 'O APP JÁ CONSIDERA',
                      'No turno até 22:00 · demanda normal, pico 16h45–20h', 'Perto de Villa Lobos',
                      '23° · nublado · chuva às 18h (simulado)', 'R$ 38/h estimado', 'Ajustes',
                      'Próxima parada agora'):
            self.assertIn(label, visible)
        self.assertLess(visible.index('R$ 38/h estimado'), visible.index('Planejar meu turno'))
        self.assertLess(visible.index('Próxima parada agora'), visible.index('Ajustes'))
        # Nothing to fill in: no visible field on the main screen (Ajustes starts collapsed).
        self.assertEqual([item for item in shown(screen) if isinstance(item, (ft.TextField, ft.Dropdown))], [])
        self.assertNotIn('Está chovendo agora', [item.label for item in shown(screen) if isinstance(item, ft.Checkbox)])
        form = fields(screen)
        self.assertEqual(form['Modelo do carro'].value, 'byd_dolphin')
        vehicle_state.set_simulated_soc(self.app, 45)
        await click(screen, 'Planejar meu turno')(None)
        self.assertEqual(self.app.driver_state['plan']['slots'][0]['soc'], 45)  # planner uses the hidden SoC
        visible = texts(screen)
        self.assertIn('Estimativa — sem dados oficiais da Uber/99.', visible)
        for label in ('LUCRO LÍQUIDO ESTIMADO DO TURNO', 'LINHA DO TEMPO DO TURNO', 'BATERIA PROJETADA (SoC)',
                      'Paradas recomendadas', 'Pico estimado', 'COMO CALCULAMOS'):
            self.assertIn(label, visible)
        self.assertTrue(any(text.startswith('Primeira parada ') for text in visible))
        self.assertTrue(any('estimado pelo ChargeGrid' in text for text in visible))
        # Technical details (battery chart, block list) stay inside the collapsed "Ver detalhes".
        self.assertNotIn('BATERIA PROJETADA (SoC)', [item.value for item in shown(screen) if isinstance(item, ft.Text)])
        self.assertTrue(any('vs. recarregar só quando a bateria fica baixa' in text for text in visible))
        plan = self.app.driver_state['plan']
        # 12h is inside the default 10:00–22:00 shift: the mode is inferred as "rest of the shift".
        self.assertEqual(plan['mode'], 'auto')
        self.assertEqual(plan['window']['end'], '22:00')
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
        vehicle_state.set_simulated_soc(self.app, 16)
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
        for label, value in (('Km rodados por hora', '999'),
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
            self.assertEqual(form['Início do turno'].value, '06:00')
            self.assertIsNone(battery(screen))
            vehicle_state.set_simulated_soc(app, 55)
            await click(screen, 'Planejar meu turno')(None)
            self.assertIn(('PUT', 'driver/profile'), calls)
            self.assertIn(('POST', 'driver/plan'), calls)
            stored = json.loads((Path(directory) / 'driver_profile.json').read_text())
            self.assertNotIn('soc_percent', stored)  # the battery is no longer a form value
            self.assertEqual(vehicle_state.simulated_soc(app), 55)
            await demo.close()


@patch.object(driver_package, 'DISCONTINUED', False)  # código guardado do Modo motorista descontinuado
class LeanDriverScreenTests(unittest.IsolatedAsyncioTestCase):
    """Tela enxuta: nada a preencher, Ajustes recolhido, GPS opcional, compatível com APIs antigas."""

    async def asyncSetUp(self):
        self.api = DemoApi(start_at=TUESDAY_NOON)
        await self.api.login(DEMO_EMAIL, DEMO_PASSWORD)
        self.app = DriverApp(self.api)

    async def asyncTearDown(self):
        await self.api.close()

    async def test_typed_earnings_become_informado_and_hidden_meals_are_kept(self):
        await self.api.request('PUT', 'driver/profile', {'vehicle': {'preset': 'byd_dolphin'}, 'preferences': {
            'meals': [{'kind': 'almoco', 'start': '12:30', 'duration_minutes': 90, 'flex_minutes': 60},
                      {'kind': 'lanche', 'start': '16:30', 'duration_minutes': 20, 'flex_minutes': 30}]}})
        screen = await driver.build(self.app)
        form = fields(screen)
        self.assertEqual(form['Almoço às'].value, '12:30')
        self.assertNotIn('Lanche às', form)  # only lunch and dinner are shown
        form['Ganho médio por hora rodando (R$)'].value = '45'
        await form['Ganho médio por hora rodando (R$)'].on_change(SimpleNamespace(control=form['Ganho médio por hora rodando (R$)']))
        self.assertIn('R$ 45/h (seu ganho)', texts(screen))
        form['Almoço às'].value = '13:00'
        vehicle_state.set_simulated_soc(self.app, 50)
        await click(screen, 'Planejar meu turno')(None)
        saved = (await self.api.request('GET', 'driver/profile'))['preferences']
        self.assertEqual(saved['sources'], {'earnings_per_hour': 'informado', 'shift': 'auto'})
        meals = {meal['kind']: meal for meal in saved['meals']}
        self.assertEqual((meals['almoco']['start'], meals['almoco']['duration_minutes']), ('13:00', 90))
        self.assertEqual(meals['lanche']['duration_minutes'], 20)  # kept although not on screen
        self.assertTrue(any('informado por você' in text for text in self.app.driver_state['plan']['assumptions']))

    async def test_settings_open_from_earnings_link_and_shift_uses_half_hour_dropdowns(self):
        screen = await driver.build(self.app)
        form = fields(screen)
        self.assertIsInstance(form['Início do turno'], ft.Dropdown)
        self.assertEqual(len(form['Fim do turno'].options), 48)
        self.assertNotIn(form['Início do turno'], list(shown(screen)))
        await click(screen, 'Ajustar')(None)
        self.assertIn(form['Início do turno'], list(shown(screen)))
        form['Início do turno'].value = '06:00'
        await form['Início do turno'].on_select(SimpleNamespace(control=form['Início do turno']))
        self.assertIn('Turno informado por você.', texts(screen))

    async def test_never_set_shift_plans_from_now_when_outside_the_default_hours(self):
        late = DemoApi(start_at=datetime(2026, 10, 14, 2, tzinfo=timezone.utc))  # 23h em São Paulo
        await late.login(DEMO_EMAIL, DEMO_PASSWORD)
        app = DriverApp(late)
        screen = await driver.build(app)
        self.assertTrue(any(text.startswith('No turno até 09:00') for text in texts(screen)))
        vehicle_state.set_simulated_soc(app, 60)
        await click(screen, 'Planejar meu turno')(None)
        plan = app.driver_state['plan']
        self.assertEqual((plan['mode'], plan['window']['start'], plan['window']['end']), ('auto', '23:00', '09:00'))
        saved = (await late.request('GET', 'driver/profile'))['preferences']
        self.assertEqual((saved['shift_start'], saved['shift_end']), ('10:00', '22:00'))  # override not saved
        # A shift the driver typed is respected: outside it, plan the next full shift.
        app.driver_state = {}
        await late.request('PUT', 'driver/profile', {'preferences': {'sources': {'shift': 'informado'}}})
        screen = await driver.build(app)
        self.assertIn('Próximo turno 10:00–22:00', [text.split(' · ')[0] for text in texts(screen)])
        await click(screen, 'Planejar meu turno')(None)
        self.assertEqual(app.driver_state['plan']['mode'], 'full_shift')
        await late.close()

    async def test_older_api_without_sources_gets_one_retry(self):
        calls = []

        async def request(method, path, body=None, **kwargs):
            calls.append((method, path, 'sources' in ((body or {}).get('preferences') or {})))
            if method in ('PUT', 'POST') and 'sources' in ((body or {}).get('preferences') or {}):
                raise ApiError('Campo não permitido', 422)
            if path == 'driver/context':
                raise ApiError('Not found', 404)  # API before /driver/context
            return await self.api.request(method, path, body, **kwargs)

        api = SimpleNamespace(is_demo=True, request=request, new_key=lambda: 'key', _now=self.api._now,
                              chargegrid_vehicle_state={'soc': 50})
        app = DriverApp(api)
        screen = await driver.build(app)
        visible = texts(screen)
        self.assertIn('Clima ainda não consultado · usando horários típicos', visible)
        self.assertIn('Está chovendo agora', [item.label for item in shown(screen) if isinstance(item, ft.Checkbox)])
        await click(screen, 'Planejar meu turno')(None)
        self.assertIn('plan', app.driver_state)
        self.assertIn(('PUT', 'driver/profile', False), calls)
        self.assertIn(('POST', 'driver/plan', False), calls)
        self.assertTrue(app.driver_state['sources_unsupported'])
        calls.clear()
        await click(screen, 'Próxima parada agora')(None)
        self.assertNotIn(('POST', 'driver/next-stop', True), calls)  # no second 422 round trip

    async def test_gps_used_silently_when_permission_exists_and_asked_only_on_tap(self):
        self.app.geolocator = FakeGeolocator(status='whileInUse')
        screen = await driver.build(self.app)
        await self.app.driver_state['gps_task']
        self.assertIn('Perto de você · localização atual', texts(screen))
        self.assertEqual(self.app.geolocator.asked, 0)
        self.assertEqual(self.app.driver_state['place']['source'], 'gps')

        other = DriverApp(self.api)
        other.geolocator = FakeGeolocator(status='denied')
        screen = await driver.build(other)
        await other.driver_state['gps_task']
        self.assertIn('Perto de Villa Lobos', texts(screen))  # no permission: never asks on open
        self.assertEqual(other.geolocator.asked, 0)
        await click(screen, 'Usar minha localização')(None)
        self.assertEqual(other.geolocator.asked, 1)
        self.assertIn('Perto de você · localização atual', texts(screen))
        sent = []
        original = self.api.request

        async def spy(method, path, body=None, **kwargs):
            sent.append((path, body))
            return await original(method, path, body, **kwargs)
        self.api.request = spy
        await click(screen, 'Planejar meu turno')(None)
        plan_body = next(body for path, body in sent if path == 'driver/plan')
        self.assertEqual((plan_body['lat'], plan_body['lng']), (-23.5614, -46.6559))

    async def test_gps_refused_falls_back_with_a_notice(self):
        self.app.geolocator = FakeGeolocator(status='denied', grant=False)
        screen = await driver.build(self.app)
        await click(screen, 'Usar minha localização')(None)
        self.assertTrue(any('Informe um bairro ou endereço' in notice for notice in self.app.notices))
        self.assertEqual(self.app.driver_state['place']['source'], 'demo')

    async def test_typed_address_is_resolved_and_saved_for_a_real_account(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {'FLET_APP_STORAGE_DATA': directory}):
            async def request(method, path, body=None, **kwargs):
                return await self.api.request(method, path, body, **kwargs)
            api = SimpleNamespace(is_demo=False, request=request, new_key=lambda: 'key')
            app = DriverApp(api)
            app.profile = {'id': 'user-1'}
            screen = await driver.build(app)
            self.assertIn('Onde você está? Informe para ver clima e postos perto', texts(screen))
            region = fields(screen)['Bairro ou endereço']
            self.assertIn(region, list(shown(screen)))  # the only (optional) field when there is no location
            region.value = 'Avenida Paulista'
            await region.on_submit(None)
            self.assertIn('Perto de Avenida Paulista', texts(screen))
            saved = SearchLocation('user-1').load()
            self.assertEqual(saved['query'], 'Avenida Paulista')
            self.assertAlmostEqual(saved['lat'], -23.5648865, places=4)
            app.driver_state = {}
            again = await driver.build(app)
            self.assertIn('Perto de Avenida Paulista', texts(again))  # last saved location on the next visit


class GeolocationServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_desktop_and_web_have_no_gps(self):
        app = SimpleNamespace(page=SimpleNamespace(platform='macos'))
        self.assertFalse(geolocation.available(app))
        self.assertIsNone(await geolocation.current_position(app, ask=True))

    async def test_fresh_last_known_position_is_used_and_failures_return_none(self):
        last = SimpleNamespace(latitude=-23.5, longitude=-46.6, timestamp=datetime.now(timezone.utc))
        app = SimpleNamespace(geolocator=FakeGeolocator(last=last))
        self.assertEqual(await geolocation.current_position(app), (-23.5, -46.6))
        stale = SimpleNamespace(latitude=1.0, longitude=1.0, timestamp=datetime(2020, 1, 1, tzinfo=timezone.utc))
        app = SimpleNamespace(geolocator=FakeGeolocator(last=stale, position=(-23.6, -46.7)))
        self.assertEqual(await geolocation.current_position(app), (-23.6, -46.7))
        self.assertEqual(await geolocation.permission(app), 'whileInUse')
        app = SimpleNamespace(geolocator=FakeGeolocator(status='deniedForever'))
        self.assertIsNone(await geolocation.current_position(app, ask=True))
        self.assertEqual(app.geolocator.asked, 0)  # permanently denied: the system dialog never opens

        class Broken(FakeGeolocator):
            async def get_current_position(self):
                raise RuntimeError('gps off')
        self.assertIsNone(await geolocation.current_position(SimpleNamespace(geolocator=Broken())))
        with patch.object(geolocation, 'TIMEOUT', 0.01):
            class Slow(FakeGeolocator):
                async def get_current_position(self):
                    import asyncio
                    await asyncio.sleep(1)
            self.assertIsNone(await geolocation.current_position(SimpleNamespace(geolocator=Slow())))


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
        self.assertIn(('06:15', '06:15'), helpers.time_options('06:15'))
        self.assertEqual(len(helpers.time_options('06:00')), 48)
        merged = helpers.merge_meals([{'kind': 'jantar', 'start': '20:00', 'duration_minutes': 30, 'flex_minutes': 15,
                                       'flexible': False, 'enabled': True}],
                                     {'almoco': (True, '12:00'), 'jantar': (False, '20:30')})
        self.assertEqual([(m['kind'], m['enabled'], m['start']) for m in merged],
                         [('almoco', True, '12:00'), ('jantar', False, '20:30')])
        self.assertEqual(merged[1]['duration_minutes'], 30)
        self.assertEqual(helpers.merge_meals([], {'almoco': (False, '12:00')}), [])
        late = datetime(2026, 10, 13, 23, 10)
        self.assertEqual(helpers.effective_preferences({'shift_start': '10:00', 'shift_end': '22:00'}, late)
                         ['shift_start'], '23:00')
        typed = {'shift_start': '10:00', 'shift_end': '22:00', 'sources': {'shift': 'informado'}}
        self.assertEqual(helpers.effective_preferences(typed, late)['shift_start'], '10:00')
        self.assertEqual(helpers.weather_line({'status': 'sem_localizacao'}), 'Informe onde você está para ver o clima')
        self.assertEqual(helpers.shift_line({'shift_start': '10:00', 'shift_end': '22:00'}, 'full_shift'),
                         'Próximo turno 10:00–22:00')
        self.assertIn('estimativa', helpers.vehicle_summary({'preset': 'byd_dolphin'}))

    async def test_driver_mode_is_discontinued_everywhere(self):
        app = DriverApp(SimpleNamespace(is_demo=False))
        state = {'reservations/current': None, 'charging-sessions/current': None,
                 'stations': {'items': [], 'total': 0}, 'me/summary': {}}

        async def request(method, path, **kwargs):
            return state[path]
        app.api.request = request
        app.set_poll = lambda callback, interval: None
        self.assertNotIn('Modo motorista', texts(await home.build(app)))  # sem entrada no Início
        app.api.request = AsyncMock(side_effect=AssertionError('não chama a API'))
        old_link = await driver.build(app)  # links antigos: aviso, sem consultar a API
        self.assertIn('O Modo motorista foi descontinuado.', texts(old_link))
        demo = DemoApi()
        await demo.login(DEMO_EMAIL, DEMO_PASSWORD)
        with self.assertRaises(ApiError) as raised:
            await demo.request('GET', 'driver/profile')
        self.assertEqual((raised.exception.status, raised.exception.code), (410, 'driver_mode_discontinued'))
        await demo.close()

if __name__ == '__main__':
    unittest.main()
