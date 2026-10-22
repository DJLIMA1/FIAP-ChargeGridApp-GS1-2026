"""Bateria escondida do carro (SoC), modo apresentação, "Por autonomia" e devolução da sobra pré-paga."""

import json
import random
import tempfile
import unittest
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import flet as ft

from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DEMO_PRESENCE_CODE, DemoApi
from chargegrid_app.screens import booking, charging, profile
from chargegrid_app.services import booking as rules
from chargegrid_app.services import prepaid, vehicle_state, wallet
from test_behavior import HandlerApp, click, descendants
from test_booking import tap
from test_charging_wizard import (
    CONTEXT,
    WizardApp,
    fields,
    limits_screen,
    texts,
    without_soc,
)


class StorageCase(unittest.IsolatedAsyncioTestCase):
    """Cada teste com arquivos do aparelho próprios (SoC, modo apresentação, pré-pagamentos)."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.env = patch.dict('os.environ', {'FLET_APP_STORAGE_DATA': self.directory.name})
        self.env.start()
        wallet.reset_demo()

    def tearDown(self):
        self.env.stop()
        self.directory.cleanup()


def real_app(user='user-a'):
    app = HandlerApp()
    app.profile = {'id': user}
    return app


def phone(level):
    return SimpleNamespace(get_battery_level=AsyncMock(return_value=level))


class VehicleStateTests(StorageCase):
    async def test_random_soc_is_drawn_once_per_account_and_persisted(self):
        app = real_app()
        first = vehicle_state.simulated_soc(app, rng=random.Random(7))
        self.assertTrue(15 <= first <= 60)
        self.assertEqual(vehicle_state.simulated_soc(real_app()), first)  # novo processo, mesmo aparelho
        stored = json.loads((Path(self.directory.name) / 'vehicle_state.json').read_text())
        self.assertEqual(stored['user-a']['soc'], first)
        other = vehicle_state.simulated_soc(real_app('user-b'), rng=random.Random(99))
        self.assertNotEqual(other, first)  # por conta
        self.assertEqual(await vehicle_state.current_soc(app), (first, 'simulated'))

    async def test_demo_keeps_soc_in_memory_per_session(self):
        app = HandlerApp()
        app.api = DemoApi()
        value = vehicle_state.simulated_soc(app)
        self.assertEqual(vehicle_state.simulated_soc(app), value)
        self.assertFalse((Path(self.directory.name) / 'vehicle_state.json').exists())
        await app.api.close()

    async def test_presentation_uses_phone_battery_and_falls_back_silently(self):
        app = real_app()
        vehicle_state.set_simulated_soc(app, 33)
        self.assertFalse(vehicle_state.presentation_mode(app))
        self.assertTrue(vehicle_state.set_presentation_mode(app, True))
        self.assertTrue(vehicle_state.presentation_mode(real_app()))  # preferência do aparelho
        # Sem serviço de bateria (desktop/web/testes): cai no valor sorteado.
        self.assertEqual(await vehicle_state.current_soc(app), (33, 'simulated'))
        app.battery_service = phone(None)
        self.assertEqual(await vehicle_state.current_soc(app), (33, 'simulated'))
        app.battery_service = SimpleNamespace(get_battery_level=AsyncMock(side_effect=RuntimeError('sem plugin')))
        self.assertEqual(await vehicle_state.current_soc(app), (33, 'simulated'))
        app.battery_service = phone(73)
        self.assertEqual(await vehicle_state.current_soc(app), (73.0, 'phone'))
        fields_sent = await vehicle_state.start_fields(app)
        self.assertEqual(fields_sent, {'soc_percent': 73.0, 'battery_kwh': 44.9, 'soc_source': 'phone'})

    def test_presentation_toggle_only_on_phones_and_demo(self):
        app = real_app()
        self.assertFalse(vehicle_state.presentation_available(app))
        app.page.platform = ft.PagePlatform.ANDROID
        self.assertTrue(vehicle_state.presentation_available(app))
        demo = HandlerApp()
        demo.api.is_demo = True
        self.assertTrue(vehicle_state.presentation_available(demo))

    def test_charge_end_sets_final_soc_once_and_never_regresses(self):
        app = real_app()
        vehicle_state.set_simulated_soc(app, 20)
        done = {'id': 's2', 'status': 'completed', 'soc_percent': '87.50', 'ended_at': '2026-10-19T12:00:00Z'}
        self.assertTrue(vehicle_state.record_session_end(app, done))
        self.assertEqual(vehicle_state.simulated_soc(app), 87.5)
        self.assertFalse(vehicle_state.record_session_end(app, done))
        old = {'id': 's1', 'status': 'completed', 'soc_percent': '40', 'ended_at': '2026-10-01T12:00:00Z'}
        self.assertFalse(vehicle_state.record_session_end(app, old))  # histórico antigo não muda o carro
        self.assertFalse(vehicle_state.record_session_end(app, {**done, 'id': 's3', 'status': 'charging'}))
        self.assertEqual(vehicle_state.simulated_soc(app), 87.5)

    async def test_vehicle_comes_from_driver_profile_with_dolphin_default(self):
        app = real_app()
        app.api.request = AsyncMock(return_value={'vehicle': {'preset': 'byd_seal'}})
        self.assertEqual(vehicle_state.car_specs(await vehicle_state.vehicle(app))['usable_kwh'], 82.5)
        await vehicle_state.vehicle(app)
        self.assertEqual(app.api.request.await_count, 1)  # em cache na sessão
        offline = real_app()
        offline.api.request = AsyncMock(side_effect=OSError('offline'))
        self.assertEqual(vehicle_state.car_specs(await vehicle_state.vehicle(offline))['name'], 'BYD Dolphin')


class AutonomyRulesTests(unittest.TestCase):
    def test_energy_is_km_times_consumption_capped_by_free_battery(self):
        free = rules.autonomy_energy(100, 14, 20, 44.9)
        self.assertEqual((free['energy_kwh'], free['capped'], free['km']), (Decimal('14.000'), False, 100))
        self.assertIsNone(rules.autonomy_note(free))
        capped = rules.autonomy_energy(300, 14, 80, 44.9)  # cabem 8,98 kWh
        self.assertEqual((capped['energy_kwh'], capped['capped'], capped['km']), (Decimal('8.980'), True, 64))
        self.assertIn('64 km', rules.autonomy_note(capped))
        self.assertNotIn('80', rules.autonomy_note(capped))  # o SoC nunca aparece
        self.assertIn('cheia', rules.autonomy_note(rules.autonomy_energy(50, 14, 100, 44.9)))

    def test_autonomy_converts_to_time_and_value_limits(self):
        car = {'consumption': 14.0, 'usable_kwh': 44.9, 'soc': 20}
        limits = rules.autonomy_limits(100, car, 60, '1.89')
        self.assertEqual(limits['max_duration_minutes'], 14)  # 14 kWh / 60 kW = 14 min
        self.assertEqual(limits['max_cost'], Decimal('26.46'))  # 14 kWh x R$1,89
        self.assertEqual(rules.autonomy_limits(100, car, 60, '1.89', max_minutes=10)['max_duration_minutes'], 10)
        self.assertNotIn('max_cost', rules.autonomy_limits(100, car, 60, 0))
        with self.assertRaises(ValueError):
            rules.autonomy_limits(100, {**car, 'soc': 100}, 60, '1.89')
        quote = rules.estimate(60, '1.89', energy=Decimal('14'))
        self.assertEqual((quote['minutes'], quote['cost']), (14, Decimal('26.46')))
        self.assertEqual(rules.parse_km(' 120 km'), 120)
        for bad in ('', '0', '2,5', 'abc', '99999'):
            with self.assertRaises(ValueError):
                rules.parse_km(bad)


class ChargingWizardBatteryTests(StorageCase):
    async def test_start_sends_hidden_soc_battery_and_phone_source(self):
        app = WizardApp()
        vehicle_state.set_presentation_mode(app, True)
        app.battery_service = phone(64)
        screen = await limits_screen(app)
        await click(screen, 'Continuar')(None)
        review = await charging.build(app, **app.go.call_args.kwargs)
        await click(review, 'Solicitar início')(None)
        body = app.posts[0][0]
        self.assertEqual(without_soc(body), {'presence_code': '#F12345', 'public_code': 'CG-ONE',
                                             'max_duration_minutes': 10,'power_tier':'max'})
        self.assertEqual((body['soc_percent'], body['battery_kwh'], body['soc_source']), (64.0, 44.9, 'phone'))

    async def test_older_api_rejecting_battery_fields_gets_one_retry_without_them(self):
        from chargegrid_app.api_client import ApiError
        app = WizardApp()
        app.outcomes = [ApiError('Dados inválidos', 422, 'validation_error'), {'id': 'new-session'}]
        screen = await limits_screen(app)
        await click(screen, 'Continuar')(None)
        review = await charging.build(app, **app.go.call_args.kwargs)
        await click(review, 'Solicitar início')(None)
        self.assertEqual(len(app.posts), 2)
        first, retry = app.posts
        self.assertIn('soc_percent', first[0])
        self.assertEqual(retry[0], without_soc(first[0]))
        self.assertNotEqual(first[1], retry[1])  # nova chave de idempotência

    async def test_by_autonomy_sends_time_and_value_limits(self):
        app = WizardApp()
        app.station['connectors'][0].update(max_duration_minutes=600)
        context = {**CONTEXT, 'connector': {**CONTEXT['connector'], 'max_duration_minutes': 600}}
        vehicle_state.set_simulated_soc(app, 20)
        screen = await limits_screen(app, point_context=context)
        await click(screen, 'Por autonomia')(None)
        self.assertIn('Autonomia desejada (km)', fields(screen))
        fields(screen)['Autonomia desejada (km)'].value = '50'
        await fields(screen)['Autonomia desejada (km)'].on_change(None)
        self.assertIn('~50 km', texts(screen))
        await click(screen, 'Continuar')(None)
        review = await charging.build(app, **app.go.call_args.kwargs)
        self.assertIn('50 km', texts(review))
        await click(review, 'Solicitar início')(None)
        body = app.posts[0][0]
        # 50 km x 14 kWh/100 km = 7 kWh; 6 kW -> 70 min; 7 kWh x R$2 = R$14.
        self.assertEqual((body['max_duration_minutes'], body['max_cost']), (70, '14.00'))
        self.assertEqual(body['soc_percent'], 20)

    async def test_autonomy_shows_the_battery_maximum_and_blocks_more_before_review(self):
        app = WizardApp()
        app.station['connectors'][0].update(max_duration_minutes=600)
        context = {**CONTEXT, 'connector': {**CONTEXT['connector'], 'max_duration_minutes': 600}}
        vehicle_state.set_simulated_soc(app, 90)
        screen = await limits_screen(app, point_context=context)
        await click(screen, 'Por autonomia')(None)
        # 10% livres de 44,9 kWh = 4,49 kWh / 14 kWh por 100 km = 32 km (o SoC nunca aparece).
        self.assertIn('Máx.: 32 km · o que cabe na bateria do seu carro', texts(screen))
        field = fields(screen)['Autonomia desejada (km)']
        field.value = '300'
        await field.on_change(None)
        self.assertEqual(field.error, 'Acima do máximo (32 km). Toque em Máx. ou diminua.')
        self.assertNotIn('90', texts(screen))
        from chargegrid_app.api_client import ApiError
        with self.assertRaisesRegex(ApiError, 'Acima do máximo'):
            await click(screen, 'Continuar')(None)
        await click(screen, 'Máx. 32 km')(None)
        self.assertEqual((field.value, field.error), ('32', None))


class DemoChargingTests(StorageCase):
    async def asyncSetUp(self):
        self.clock = [0.0]
        self.app = HandlerApp()
        self.app.api = DemoApi(clock=lambda: self.clock[0])
        await self.app.api.login(DEMO_EMAIL, DEMO_PASSWORD)
        self.app.profile = await self.app.api.request('GET', 'me')
        self.app.back = lambda event=None: None
        stations = (await self.app.api.request('GET', 'stations'))['items']
        self.point = next(p for s in stations for p in s['connectors'] if p['available'])

    async def asyncTearDown(self):
        await self.app.api.close()

    async def start(self, **extra):
        return await self.app.api.request('POST', 'charging-sessions', {
            'presence_code': DEMO_PRESENCE_CODE, 'public_code': self.point['public_code'],
            'max_duration_minutes': 60, **extra}, key=self.app.api.new_key())

    async def test_presentation_pushes_phone_soc_each_poll_and_stops_at_full(self):
        vehicle_state.set_presentation_mode(self.app, True)
        self.app.battery_service = phone(81)
        session = await self.start(soc_percent=80, battery_kwh=44.9, soc_source='phone')
        self.clock[0] = 30
        screen = await charging.build(self.app, session_id=session['id'])
        self.assertIn('Recarga em andamento', texts(screen))
        await self.app.poll()
        current = await self.app.api.request('GET', f"charging-sessions/{session['id']}")
        self.assertEqual((current['soc_percent'], current['soc_source']), ('81.00', 'phone'))
        self.assertIn('81%', texts(screen))  # o mesmo valor que o totem mostra
        self.app.battery_service = phone(100)
        await self.app.poll()
        self.app.go.assert_awaited_with('charging', session_id=session['id'])  # parou: battery_full
        self.clock[0] += 5
        done = await charging.build(self.app, session_id=session['id'])
        self.assertIn('Bateria cheia', texts(done))
        self.assertIn('100%', texts(done))

    async def test_official_mode_never_pushes_soc(self):
        session = await self.start(soc_percent=30, battery_kwh=44.9, soc_source='simulated')
        self.app.battery_service = phone(99)
        self.clock[0] = 30
        await charging.build(self.app, session_id=session['id'])
        self.app.api.request = AsyncMock(wraps=self.app.api.request)
        await self.app.poll()
        self.assertFalse(any(call.args[1].endswith('/soc') for call in self.app.api.request.await_args_list))

    async def test_prepaid_surplus_is_credited_once_on_battery_full(self):
        before = wallet.balance(self.app)
        prepaid.record(self.app, amount=Decimal('30.00'), energy_amount=Decimal('30.00'), method='pix',
                       connector_id=self.point['id'])
        session = await self.start(soc_percent=99, battery_kwh=44.9, soc_source='phone')
        self.assertTrue(prepaid.link_session(self.app, session['id'], connector_id=self.point['id']))
        self.clock[0] = 30
        await self.app.api.request('POST', f"charging-sessions/{session['id']}/soc", {'soc_percent': 100})
        self.clock[0] += 5
        ended = await self.app.api.request('GET', f"charging-sessions/{session['id']}")
        self.assertEqual(ended['end_reason'], 'battery_full')
        expected = Decimal('30.00') - Decimal(str(ended['cost_estimate'])).quantize(Decimal('0.01'), ROUND_HALF_UP)
        for _ in range(3):  # leituras repetidas / recarga da tela: crédito único
            screen = await charging.build(self.app, session_id=session['id'])
        self.assertEqual(wallet.balance(self.app), before + expected)
        credits = [row for row in wallet.transactions(self.app) if row['title'] == prepaid.CREDIT_TITLE]
        self.assertEqual(len(credits), 1)
        self.assertTrue(any(t.endswith('voltou como crédito') for t in texts(screen).split('  ')) or
                        'voltou como crédito' in texts(screen))
        self.assertIsNotNone(next(c for c in descendants(screen) if getattr(c, 'data', None) == 'prepaid-credit'))

    async def test_booking_autonomy_option_and_now_handoff_records_prepayment(self):
        vehicle_state.set_simulated_soc(self.app, 30)
        sid = 'demo-station-1'
        await booking.build(self.app, step=1, station_id=sid)
        self.app.booking.update(by='autonomy')
        screen = await booking.build(self.app, step=3, station_id=sid)
        visible = [str(c.value) for c in descendants(screen) if isinstance(c, ft.Text)]
        for label in ('Por tempo', 'Por valor', 'Por autonomia', 'Autonomia desejada (km)'):
            self.assertIn(label, visible)
        self.app.booking.update(mode='now', km_text='80', pay='balance')
        review = await booking.build(self.app, step=6, station_id=sid)
        visible = [str(c.value) for c in descendants(review) if isinstance(c, ft.Text)]
        self.assertTrue(any(text.startswith('Por autonomia') for text in visible))
        self.assertTrue(any(text.startswith('80 km |') for text in visible))
        await tap(review, 'Confirmar e iniciar no ponto')()  # Saldo (simulado): segue direto ao início
        kwargs = self.app.go.await_args.kwargs
        self.assertEqual(kwargs['planning_intent'], {'mode': 'autonomy', 'km': 80, 'max_power_kw': '60.0','power_tier':'max'})
        rows = prepaid.records(self.app)
        self.assertEqual((len(rows), rows[0]['method'], rows[0]['status']), (1, 'balance', 'open'))
        draft_screen = await charging.build(self.app, **kwargs)
        self.assertEqual(self.app.charging_draft['mode'], 'autonomy')
        self.assertEqual(self.app.charging_draft['autonomy_km'], '80')
        self.assertTrue(draft_screen)
        # O assistente já definiu a cobrança: do código #F vai direto à revisão, sem repetir os limites.
        await tap(draft_screen, 'Continuar')()
        self.assertEqual(self.app.go.await_args.kwargs['step'], 3)
        review = await charging.build(self.app, **{**kwargs, 'step': 3})
        texts = [str(c.value) for c in descendants(review) if isinstance(c, ft.Text)]
        self.assertIn('Revisar recarga', texts)
        limits_button = next(c for c in descendants(review) if isinstance(c, ft.Container)
                             and isinstance(c.content, ft.Text) and c.content.value == 'Voltar aos limites')
        self.assertFalse(limits_button.visible)
        self.assertNotIn('Por tempo', texts)
        back = await charging.build(self.app, **{**kwargs, 'step': 2})
        self.assertIn('Confirmar ponto', [str(c.value) for c in descendants(back) if isinstance(c, ft.Text)])


class ProfileToggleTests(StorageCase):
    async def test_presentation_row_after_dark_theme_and_persisted(self):
        app = HandlerApp()
        app.api = DemoApi()
        await app.api.login(DEMO_EMAIL, DEMO_PASSWORD)
        app.dark_mode = True
        app.logout = AsyncMock()
        screen = await profile.build(app)
        visible = [str(c.value) for c in descendants(screen) if isinstance(c, ft.Text)]
        self.assertIn('Bateria do celular como a do carro e pagamento simulado (sem Stripe)', visible)
        self.assertLess(visible.index('Tema escuro'), visible.index('Modo apresentação'))
        switch = next(c for c in descendants(screen) if isinstance(c, ft.Switch) and c.data == 'presentation')
        self.assertFalse(switch.value)
        switch.value = True
        await switch.on_change(SimpleNamespace(control=switch))
        self.assertTrue(vehicle_state.presentation_mode())
        again = await profile.build(app)
        self.assertTrue(next(c for c in descendants(again) if isinstance(c, ft.Switch) and c.data == 'presentation').value)
        await app.api.close()

    async def test_hidden_on_desktop_real_account(self):
        app = HandlerApp()
        app.api.request = AsyncMock(side_effect=lambda method, path, *a, **k: {'id': 'u'} if path == 'me' else None)
        app.api.session.user = {'email': 'a@b.c'}
        app.dark_mode = True
        app.logout = AsyncMock()
        screen = await profile.build(app)
        self.assertNotIn('Modo apresentação', [str(c.value) for c in descendants(screen) if isinstance(c, ft.Text)])


if __name__ == '__main__':
    unittest.main()
