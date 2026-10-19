"""Car chosen once (sign-up or profile) and reused by the driver planner without asking again."""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import flet as ft

from chargegrid_app.api_client import ApiError
from chargegrid_app.app import ChargeGridApp
from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DemoApi
from chargegrid_app.preferences import PendingVehicleStore
from chargegrid_app.screens import auth, driver
from chargegrid_app.services import driver as helpers
from chargegrid_app.services.driver_profile import apply_signup_vehicle
from chargegrid_app.ui.vehicle import VehiclePicker
from test_behavior import HandlerApp, click, descendants
from test_driver_mode import DriverApp, battery, fields, texts

DRIVER_PROFILE = {'saved': False, 'vehicle': {'preset': 'byd_dolphin'}, 'preferences': {'shift_start': '07:00'}}


class Recorder:
    """API double that records calls and answers driver/profile."""

    def __init__(self, profile=None, fail_put=None):
        self.calls, self.profile, self.fail_put = [], dict(profile or DRIVER_PROFILE), fail_put
        self.session = SimpleNamespace(user={'email': 'Nova@Example.com'})

    async def request(self, method, path, body=None, **kwargs):
        self.calls.append((method, path, body))
        if method == 'PUT' and self.fail_put:
            raise self.fail_put
        if path == 'driver/profile':
            return self.profile
        return {'id': 'u', 'email': 'nova@example.com', 'account_type': 'consumer'}


class VehiclePickerTests(unittest.IsolatedAsyncioTestCase):
    async def test_preset_custom_and_later_choices(self):
        changes = []
        picker = VehiclePicker({'preset': 'byd_seal'}, on_change=changes.append)
        self.assertEqual(picker.read(), {'preset': 'byd_seal'})
        self.assertIn('autonomia', picker.summary.value)
        self.assertFalse(picker.custom.visible)
        picker.model.value = 'custom'
        await picker._changed(SimpleNamespace(control=picker.model))
        # "Outro carro" starts from the last model, so only differences need typing.
        self.assertTrue(picker.custom.visible)
        self.assertEqual(picker.battery.value, '82,5')
        picker.name.value, picker.consumption.value = ' Táxi ', '15'
        self.assertEqual(picker.read(), {'preset': 'custom', 'name': 'Táxi', 'usable_battery_kwh': 82.5,
                                         'consumption_kwh_per_100km': 15.0})
        self.assertEqual(changes[-1]['preset'], 'custom')
        picker.battery.value = '900'
        self.assertIsNone(picker.read(strict=False))
        with self.assertRaises(ApiError):
            picker.read()
        later = VehiclePicker(allow_later=True)
        self.assertEqual(later.value, 'later')
        self.assertIsNone(later.read())
        self.assertNotIn('later', [option.key for option in VehiclePicker().model.options])

    def test_headline_and_battery_range(self):
        self.assertEqual(helpers.vehicle_headline({'preset': 'byd_dolphin'}), 'BYD Dolphin · ~321 km de autonomia')
        self.assertEqual(helpers.range_km({'preset': 'byd_dolphin'}, 50), 160)
        self.assertIn('acima da reserva de 15%', helpers.battery_line({'preset': 'byd_dolphin'}, 60, 15))
        self.assertEqual(helpers.vehicle_name({'preset': 'custom', 'name': 'Meu', 'usable_battery_kwh': 40}), 'Meu')
        self.assertIsNone(helpers.vehicle_profile({'preset': 'nao_existe'}))


class SignupVehicleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.env = patch.dict('os.environ', {'FLET_APP_STORAGE_DATA': self.directory.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.directory.cleanup()

    async def register(self, app, account='consumer', model='byd_seal'):
        screen = await auth.build(app, mode='register')
        section = next(c for c in descendants(screen) if isinstance(c, ft.Container)
                       and any(isinstance(t, ft.Text) and t.value == 'Seu carro elétrico' for t in descendants(c)))
        if account == 'vendor':
            await click(screen, 'Sou operador')(None)
        model_control = next(c for c in descendants(screen) if isinstance(c, ft.Dropdown))
        model_control.value = model
        fields = [c for c in descendants(screen) if isinstance(c, ft.TextField)]
        for control, value in zip(fields, ['Nova', 'nova@example.com', 'senha1234']):
            control.value = value
        await click(screen, 'Criar conta')(None)
        return section

    async def test_driver_signup_with_confirmation_keeps_car_pending_on_device(self):
        app = HandlerApp()
        app.api.request.return_value = {'requires_email_confirmation': True}
        section = await self.register(app)
        self.assertTrue(section.visible)
        self.assertEqual(PendingVehicleStore().load('NOVA@example.com'), {'preset': 'byd_seal'})
        app.go.assert_awaited_once_with('auth', mode='verify', email_value='nova@example.com')
        raw = (Path(self.directory.name) / 'pending_vehicle.json').read_text()
        self.assertNotIn('nova@example.com', raw)  # keyed by a hash, not the address

    async def test_operator_signup_hides_and_ignores_the_car(self):
        app = HandlerApp()
        app.api.request.return_value = {'requires_email_confirmation': True}
        section = await self.register(app, account='vendor')
        self.assertFalse(section.visible)
        self.assertIsNone(PendingVehicleStore().load('nova@example.com'))

    async def test_signup_with_session_saves_car_after_sign_in(self):
        app = HandlerApp()
        api = Recorder()
        tokens = {'access_token': 'a', 'refresh_token': 'r', 'user': {'email': 'nova@example.com'}}
        api.session = SimpleNamespace(update=lambda data: None, user={'email': 'nova@example.com'})

        async def request(method, path, body=None, **kwargs):
            return tokens if path == 'auth/register' else await Recorder.request(api, method, path, body)
        api.request = request
        app.api = api
        await self.register(app)
        app.signed_in.assert_awaited_once_with()
        self.assertIn(('PUT', 'driver/profile', {'vehicle': {'preset': 'byd_seal'},
                                                 'preferences': {'shift_start': '07:00'}}), api.calls)
        self.assertIsNone(PendingVehicleStore().load('nova@example.com'))

    async def test_first_sign_in_applies_pending_car_keeping_preferences(self):
        PendingVehicleStore().save('nova@example.com', {'preset': 'byd_seal'})
        api = Recorder()
        app = SimpleNamespace(api=api, go=AsyncMock(), reset_account_ui=lambda: None,
                              reset_account_operations=lambda: None)
        await ChargeGridApp.signed_in(app)
        self.assertEqual(api.calls[1:], [('GET', 'driver/profile', None),
                                         ('PUT', 'driver/profile', {'vehicle': {'preset': 'byd_seal'},
                                                                    'preferences': {'shift_start': '07:00'}})])
        self.assertIsNone(PendingVehicleStore().load('nova@example.com'))
        app.go.assert_awaited_once_with('home')

    async def test_pending_car_failures_never_block_sign_in(self):
        PendingVehicleStore().save('nova@example.com', {'preset': 'byd_seal'})
        api = Recorder(fail_put=ApiError('Sem conexão', 0))
        app = SimpleNamespace(api=api, go=AsyncMock(), reset_account_ui=lambda: None,
                              reset_account_operations=lambda: None)
        await ChargeGridApp.signed_in(app)
        app.go.assert_awaited_once_with('home')
        self.assertEqual(PendingVehicleStore().load('nova@example.com'), {'preset': 'byd_seal'})  # retried later
        # A profile already saved elsewhere is never overwritten by the sign-up choice.
        saved = Recorder({**DRIVER_PROFILE, 'saved': True})
        self.assertFalse(await apply_signup_vehicle(saved, {}))
        self.assertNotIn('PUT', [method for method, *_ in saved.calls])
        self.assertIsNone(PendingVehicleStore().load('nova@example.com'))
        # Other accounts and the demo are untouched.
        other = Recorder()
        other.session.user = {'email': 'outra@example.com'}
        self.assertFalse(await apply_signup_vehicle(other, {}))
        self.assertEqual(other.calls, [])


class PlannerInferenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # 9h UTC = 6h in São Paulo: before the default 10:00 shift.
        self.api = DemoApi(start_at=datetime(2026, 10, 13, 9, tzinfo=timezone.utc))
        await self.api.login(DEMO_EMAIL, DEMO_PASSWORD)
        self.app = DriverApp(self.api)

    async def asyncTearDown(self):
        await self.api.close()

    def test_auto_mode_follows_shift_including_overnight(self):
        day, night = {'shift_start': '10:00', 'shift_end': '22:00'}, {'shift_start': '18:00', 'shift_end': '02:00'}
        self.assertEqual(helpers.auto_mode(day, datetime(2026, 1, 1, 9, 59)), 'full_shift')
        self.assertEqual(helpers.auto_mode(day, datetime(2026, 1, 1, 12)), 'auto')
        self.assertEqual(helpers.auto_mode(night, datetime(2026, 1, 1, 1)), 'auto')
        self.assertEqual(helpers.auto_mode(night, datetime(2026, 1, 1, 12)), 'full_shift')
        self.assertIn('Almoço 12:30', helpers.shift_summary({'shift_start': '10:00', 'shift_end': '22:00',
                                                             'earnings_per_hour': 38,
                                                             'meals': [{'kind': 'almoco', 'start': '12:30'}]}))

    async def test_saved_car_is_a_summary_and_mode_is_inferred_before_shift(self):
        await self.api.request('PUT', 'driver/profile', {'vehicle': {'preset': 'byd_seal'}, 'preferences': {}})
        screen = await driver.build(self.app)
        visible = texts(screen)
        self.assertIn('BYD Seal - 500 km de autonomia', visible)
        picker_box = next(c for c in descendants(screen) if isinstance(c, ft.Column) and len(c.controls) == 1
                          and any(isinstance(d, ft.Dropdown) and d.label == 'Modelo do carro' for d in descendants(c)))
        self.assertFalse(picker_box.visible)
        # Tapping the car line ("Trocar o carro") opens the picker inline.
        swap = next(item for item in descendants(screen) if getattr(item, 'tooltip', None) == 'Trocar o carro')
        await swap.on_click(None)
        self.assertTrue(picker_box.visible)
        self.assertEqual(fields(screen)['O que planejar'].value, 'full_shift')
        self.assertIn('Turno completo 10:00–22:00', visible)
        self.assertIn('Turno completo', visible)  # row title follows the inferred mode
        # The estimated range lives in the slider bubble and the screen-reader label, not as card text.
        slider = battery(screen)
        self.assertIn('km', slider.label)
        self.assertTrue(any('acima da reserva' in (item.label or '') for item in descendants(screen)
                            if isinstance(item, ft.Semantics)))
        battery(screen).value = 30
        await battery(screen).on_change(None)
        self.assertIn('30%', texts(screen))
        await click(screen, 'Planejar meu turno')(None)
        plan = self.app.driver_state['plan']
        self.assertEqual((plan['mode'], plan['window']['start']), ('full_shift', '10:00'))

    async def test_demo_shows_default_car_and_plan_saves_the_chosen_one(self):
        screen = await driver.build(self.app)
        # The demo ships with the default car: summary line, picker closed (opens on tap).
        self.assertIn('BYD Dolphin - 321 km de autonomia', texts(screen))
        self.assertNotIn('Qual é o seu carro?', texts(screen))
        form = fields(screen)
        form['Modelo do carro'].value = 'byd_dolphin_mini'
        await click(screen, 'Próxima parada agora')(None)
        saved = await self.api.request('GET', 'driver/profile')
        self.assertTrue(saved['saved'])
        self.assertEqual(saved['vehicle']['preset'], 'byd_dolphin_mini')
        self.assertIn('BYD Dolphin Mini - 304 km de autonomia', texts(screen))

    async def test_rain_override_and_location_are_optional_context(self):
        bodies = []
        original = self.api.request

        async def request(method, path, body=None, **kwargs):
            bodies.append((path, body))
            return await original(method, path, body, **kwargs)
        self.api.request = request
        screen = await driver.build(self.app)
        await click(screen, 'Planejar meu turno')(None)
        body = next(body for path, body in bodies if path == 'driver/plan')
        self.assertEqual(body['context'], {})  # weather comes from the API, not a checkbox
        self.assertIn('lat', body)  # demo region resolved without asking
        rain = next(c for c in descendants(screen) if isinstance(c, ft.Checkbox))
        rain.value = True
        await click(screen, 'Planejar meu turno')(None)
        body = [body for path, body in bodies if path == 'driver/plan'][-1]
        self.assertEqual(body['context'], {'rain': True})


if __name__ == '__main__':
    unittest.main()
