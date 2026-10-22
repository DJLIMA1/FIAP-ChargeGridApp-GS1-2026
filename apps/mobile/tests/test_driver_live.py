"""Potência ao vivo, taxa de permanência (revisão, fim da recarga, avisos, tarifa) e o pré-pago na conta real."""

import tempfile
import unittest
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import flet as ft

from chargegrid_app.api_client import ApiError
from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DemoApi
from chargegrid_app.screens import charging, tariffs
from chargegrid_app.services import notifications, prepaid, station_settings, wallet
from test_behavior import HandlerApp, descendants
from test_booking import tap
from test_driver_payments import FakeApi, PollApp, by_data, texts
from test_station_admin import demo_app

REASON = '6 kW porque a loja usa 12 de 30 kW e há 3 carros carregando.'
TERMS = {'enabled': True, 'version': 'ovs-abc', 'grace_minutes': 10, 'interval_minutes': 1, 'amount': '1.00',
         'max_amount': '30.00', 'summary': 'Após a recarga: 10 min de tolerância, depois R$ 1,00/min (máx. R$ 30,00)'}


def session(status='charging', **extra):
    row = {'id': 's9', 'status': status, 'connector': {'power_kw': '22.000', 'public_code': 'CG-1'},
           'power_limit_kw': '11.000', 'started_at': '2026-10-20T12:00:00+00:00',
           'last_measurement_at': '2026-10-20T12:10:00+00:00', 'max_duration_minutes': 60, 'energy_wh': '1000.000',
           'cost_estimate': '1.8900', 'online': True, 'station_address': 'Rua A, 1', 'source': 'simulated'}
    row.update(extra)
    return row


class StorageCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.env = patch.dict('os.environ', {'FLET_APP_STORAGE_DATA': self.directory.name})
        self.env.start()
        wallet.reset_demo()

    def tearDown(self):
        self.env.stop()
        self.directory.cleanup()


class LivePowerTests(StorageCase):
    def test_power_text_prefers_the_applied_power_and_shows_adjusting_and_paused(self):
        legacy = session()
        self.assertEqual(charging.power_text(legacy), '11 kW')  # API antiga: min(nominal, limite do início)
        self.assertEqual(charging.power_text(session(applied_power_kw='6.000', power_state='applied')), '6 kW')
        self.assertEqual(charging.power_text(session(applied_power_kw='7.400', power_state='waiting')), '7,4 kW')
        for state in ('reducing', 'raising'):
            self.assertEqual(charging.power_text(session(applied_power_kw='6.000', power_state=state)), 'Ajustando…')
        self.assertEqual(charging.power_text(session(applied_power_kw='0.000', power_state='paused')), 'Pausada')
        self.assertEqual(charging.power_text(session('starting', applied_power_kw='6.000')), '- kW')
        self.assertEqual(charging.power_reason(session(power_reason=REASON)), REASON)
        self.assertEqual(charging.power_reason(session(power_reason={'text': REASON})), REASON)
        self.assertIsNone(charging.power_reason(legacy))
        self.assertIsNone(charging.power_reason(session('completed', power_reason=REASON)))

    async def test_screen_updates_power_state_and_reason_every_second(self):
        current = {'row': session(applied_power_kw='6.000', power_state='applied', power_reason=REASON)}
        api = FakeApi({('GET', 'charging-sessions/s9'): lambda body, key: deepcopy(current['row'])})
        app = PollApp()
        app.api = api
        app.profile = {'id': 'driver-1'}
        screen = await charging.build(app, session_id='s9')
        self.assertEqual(app.poll_interval, 1)
        self.assertIn('6 kW', texts(screen))
        self.assertIn(REASON, texts(screen))
        current['row'] = session(applied_power_kw='6.000', power_state='reducing',
                                 power_reason='Reduzindo: a loja passou a usar mais energia.')
        await app.poll()
        self.assertIn('Ajustando…', texts(screen))
        self.assertIn('Reduzindo: a loja passou a usar mais energia.', texts(screen))
        current['row'] = session(applied_power_kw='0.000', power_state='paused', power_reason='Pausada: sem potência.')
        await app.poll()
        self.assertIn('Pausada', texts(screen))

    async def test_legacy_session_has_no_reason_line(self):
        api = FakeApi({('GET', 'charging-sessions/s9'): session()})
        app = PollApp()
        app.api = api
        screen = await charging.build(app, session_id='s9')
        self.assertIn('11 kW', texts(screen))
        self.assertFalse(by_data(screen, 'power-reason').visible)
        self.assertFalse(by_data(screen, 'payment-slot').visible)


class OverstayEndTests(StorageCase):
    def ended(self, overstay=None, payment=None, **extra):
        row = session('completed', ended_at='2026-10-20T12:30:00+00:00', end_reason='duration_limit', **extra)
        if overstay is not None:
            row['overstay'] = overstay
        if payment is not None:
            row['payment'] = payment
        return row

    async def test_grace_countdown_then_fee_until_closed_polling_every_five_seconds(self):
        rows = [self.ended({'status': 'grace', 'grace_remaining_seconds': 300, 'fee_due': '0.00'})]
        api = FakeApi({('GET', 'charging-sessions/s9'): lambda body, key: deepcopy(rows[-1])})
        app = PollApp()
        app.api = api
        screen = await charging.build(app, session_id='s9')
        self.assertIn('Recarga concluída — desconecte em 05:00', texts(screen))
        self.assertEqual(app.poll_interval, 1)  # contagem local de 1 s; consulta a cada 5 s
        await app.poll()  # 1ª consulta já no primeiro segundo
        fetched = sum(1 for call in api.calls if call[1] == 'charging-sessions/s9')
        rows.append(self.ended({'status': 'billing', 'grace_remaining_seconds': 0, 'fee_due': '2.00'}))
        for _ in range(4):
            await app.poll()
        self.assertEqual(sum(1 for call in api.calls if call[1] == 'charging-sessions/s9'), fetched)
        await app.poll()  # 5 s depois
        self.assertIn('Taxa de permanência: R$ 2,00', texts(screen))
        rows.append(self.ended({'status': 'closed', 'grace_remaining_seconds': 0, 'fee_due': '3.00'}))
        for _ in range(5):
            await app.poll()
        self.assertIn('Taxa de permanência: R$ 3,00', texts(screen))
        self.assertIn('Carro desconectado. Valor final da permanência.', texts(screen))
        self.assertEqual(app.poll_interval, 60)  # fechou: para de consultar

    async def test_settlement_waits_for_overstay_and_fetches_the_payment(self):
        in_use = {'id': 'p1', 'status': 'in_use', 'status_label': 'Pago (teste) · em uso', 'amount': '57.00',
                  'settlement': None}
        done = {**in_use, 'status': 'completed', 'status_label': 'Cobrado R$ 15,00 (teste) · Devolvido R$ 42,00',
                'settlement': {'status': 'done', 'charged': '15.00', 'returned': '42.00', 'return_kind': 'released',
                               'overstay_amount': '2.00'}}
        payment = {'row': in_use}
        api = FakeApi({('GET', 'charging-sessions/s9'): self.ended({'status': 'closed', 'fee_due': '2.00'},
                                                                   payment=in_use),
                       ('GET', 'payments/p1'): lambda body, key: deepcopy(payment['row'])})
        app = PollApp()
        app.api = api
        screen = await charging.build(app, session_id='s9')
        self.assertIn('Acertando o valor com a Stripe…', texts(screen))
        payment['row'] = done
        await app.poll()
        self.assertIn(('GET', 'payments/p1', None, None), api.calls)  # o GET dispara o acerto no servidor
        copy = texts(screen)
        self.assertIn('Cobrado R$ 15,00 · Devolvido R$ 42,00', copy)
        self.assertTrue(any('Inclui R$ 2,00 de taxa de permanência.' in text for text in copy))
        self.assertEqual(app.poll_interval, 60)

    async def test_nothing_shows_without_overstay_or_payment_fields(self):
        api = FakeApi({('GET', 'charging-sessions/s9'): self.ended()})
        app = PollApp()
        app.api = api
        screen = await charging.build(app, session_id='s9')
        self.assertIsNone(by_data(screen, 'overstay-slot'))
        self.assertIsNone(by_data(screen, 'settlement-slot'))
        self.assertIsNone(getattr(app, 'poll_interval', None))

    async def test_closed_within_grace_has_no_fee(self):
        api = FakeApi({('GET', 'charging-sessions/s9'): self.ended({'status': 'closed', 'fee_due': '0.00'})})
        app = PollApp()
        app.api = api
        screen = await charging.build(app, session_id='s9')
        self.assertIn('Desconectado dentro da tolerância', texts(screen))
        self.assertIsNone(getattr(app, 'poll_interval', None))


class OverstayStartTests(StorageCase):
    async def asyncSetUp(self):
        self.app = PollApp()
        self.app.api = DemoApi(clock=lambda: 0.0)
        await self.app.api.login(DEMO_EMAIL, DEMO_PASSWORD)
        self.app.profile = await self.app.api.request('GET', 'me')
        self.app.back = lambda event=None: None
        real = self.app.api._station_row
        self.terms = dict(TERMS)
        self.app.api._station_row = lambda station: {**real(station), 'overstay': dict(self.terms)}
        station = (await self.app.api.request('GET', 'stations'))['items'][0]
        point = next(p for p in station['connectors'] if p['available'])
        from chargegrid_app.ui.point_summary import point_context
        self.route = {'public_code': point['public_code'], 'point_context': point_context(station, point),
                      'max_duration': 30}

    async def asyncTearDown(self):
        await self.app.api.close()

    async def review(self):
        await charging.build(self.app, **self.route)
        self.app.charging_draft.update(presence_digits='12345', furthest=3)
        return await charging.build(self.app, **{**self.route, 'step': 3})

    async def test_review_shows_the_summary_and_start_sends_the_terms_version(self):
        review = await self.review()
        self.assertIn(TERMS['summary'], texts(review))
        self.app.api.request = unittest.mock.AsyncMock(wraps=self.app.api.request)
        await tap(review, 'Solicitar início')()
        post = next(call for call in self.app.api.request.await_args_list
                    if call.args[:2] == ('POST', 'charging-sessions'))
        self.assertEqual(post.args[2]['overstay_terms_version'], 'ovs-abc')
        self.assertIn('session_id', self.app.go.await_args.kwargs)

    async def test_changed_terms_are_shown_again_before_starting(self):
        review = await self.review()
        self.terms.update(version='ovs-new', summary='Após a recarga: 5 min de tolerância, depois R$ 2,00/min')
        await tap(review, 'Solicitar início')()
        self.assertEqual(self.app.go.await_args.kwargs['step'], 3)
        self.assertIn('A taxa de permanência deste posto mudou. Confira os termos antes de iniciar.', self.app.notices)
        again = await charging.build(self.app, **{**self.route, 'step': 3})
        self.assertIn('Após a recarga: 5 min de tolerância, depois R$ 2,00/min', texts(again))

    async def test_server_409_terms_changed_reloads_the_terms(self):
        review = await self.review()
        real = self.app.api.request

        async def request(method, path, body=None, **kwargs):
            if (method, path) == ('POST', 'charging-sessions'):
                raise ApiError('Os termos mudaram', 409, 'overstay_terms_changed')
            return await real(method, path, body, **kwargs)
        self.app.api.request = request
        await tap(review, 'Solicitar início')()
        self.assertFalse(self.app.charging_draft['uncertain'])
        self.assertFalse(self.app.charging_draft['overstay_loaded'])
        self.assertEqual(self.app.go.await_args.kwargs['step'], 3)

    async def test_station_without_overstay_sends_no_version(self):
        self.app.api._station_row = DemoApi._station_row.__get__(self.app.api)
        review = await self.review()
        self.assertFalse(any('tolerância' in text for text in texts(review)))
        self.assertNotIn('overstay_terms_version', charging._body(self.app.charging_draft))


class OverstayNotificationTests(unittest.IsolatedAsyncioTestCase):
    def test_grace_and_fee_items(self):
        grace = notifications.overstay_item({'status': 'grace', 'grace_remaining_seconds': 125, 'session_id': 's9',
                                             'station_name': 'Villa Lobos'})
        self.assertEqual((grace['title'], grace['subtitle']), ('Recarga concluída: desconecte o carro',
                                                              'Estação Villa Lobos'))
        self.assertIn('02:05', grace['detail'])
        fee = notifications.overstay_item({'status': 'billing', 'fee_due': '4.5', 'session_id': 's9'})
        self.assertEqual(fee['title'], 'Taxa de permanência em cobrança')
        self.assertIn('R$ 4,50 até agora', fee['detail'])
        self.assertNotEqual(grace['id'], fee['id'])
        self.assertIn('teto atingido', notifications.overstay_item({'status': 'capped', 'fee_due': '30'})['detail'])
        for value in (None, {'status': 'closed'}, {'status': 'no_fee'}):
            self.assertIsNone(notifications.overstay_item(value))

    async def test_collect_adds_the_overstay_and_ignores_an_old_api(self):
        app = HandlerApp()
        app.api = FakeApi({('GET', 'charging-sessions/current'): None,
                           ('GET', 'overstays/current'): {'status': 'billing', 'fee_due': '2.00', 'session_id': 's9'}})
        items = await notifications.collect(app)
        self.assertEqual([item['kind'] for item in items], ['overstay'])
        app.api.routes[('GET', 'overstays/current')] = ApiError('não encontrado', 404, 'not_found')
        self.assertEqual(await notifications.collect(app), [])


class OverstayTariffTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        station_settings.reset_demo()

    async def asyncSetUp(self):
        self.app = await demo_app()
        self.app.set_poll = lambda callback, interval: None
        self.app.page = SimpleNamespace(update=lambda: None, show_dialog=lambda d: None)
        self.sid = (await self.app.api.request('GET', 'operator/stations'))['items'][0]['id']

    async def asyncTearDown(self):
        await self.app.api.close()

    def fields(self, screen):
        return [c for c in descendants(screen) if isinstance(c, ft.TextField)
                and c.keyboard_type == ft.KeyboardType.NUMBER]

    async def test_old_api_has_no_cap_field(self):
        real = self.app.api._pricing_payload

        def payload(station):
            data = real(station)
            data['rules']['rotation'].pop('max_amount', None)
            return data
        self.app.api._pricing_payload = payload
        screen = await tariffs.build(self.app, station_id=self.sid, page='rotation')
        self.assertIn('Taxa de permanência', texts(screen))
        self.assertEqual(len(self.fields(screen)), 3)
        self.assertNotIn('Teto por recarga', texts(screen))

    async def test_cap_field_is_saved_as_max_amount_and_zero_tolerance_is_allowed(self):
        real = self.app.api._pricing_payload

        def payload(station):
            data = real(station)
            data['rules']['rotation'].update(enabled=True, start_after_min=10, interval_min=1, amount='1.00',
                                             max_amount='30.00')
            return data
        self.app.api._pricing_payload = payload
        overview = await tariffs.build(self.app, station_id=self.sid)
        self.assertIn('R$ 1,00 a cada 1 min após 10 min · máx. R$ 30,00', texts(overview))
        screen = await tariffs.build(self.app, station_id=self.sid, page='rotation')
        after, every, amount, cap = self.fields(screen)
        self.assertIn('Teto por recarga', texts(screen))
        self.assertEqual(cap.value, '30,00')
        sent = []
        original = self.app.api.request

        async def request(method, path, body=None, **kwargs):
            if method == 'PUT':
                sent.append(body)
                return None
            return await original(method, path, body, **kwargs)
        self.app.api.request = request
        after.value, cap.value = '0', '1,50'
        after.on_change(None)
        self.assertIn('2 intervalos × R$ 1,00, limitado ao teto: R$ 1,50', texts(screen))
        save = next(c for c in descendants(screen) if isinstance(c, ft.Container) and c.on_click
                    and 'Salvar regra' in texts(c))
        await save.on_click(None)
        rule = sent[-1]['rotation']
        self.assertEqual((rule['enabled'], rule['start_after_min'], rule['interval_min']), (True, 0, 1))
        self.assertEqual((Decimal(rule['amount']), Decimal(rule['max_amount'])), (Decimal('1'), Decimal('1.5')))


class PrepaidRealAccountTests(StorageCase):
    def test_real_account_never_credits_the_wallet(self):
        app = HandlerApp()
        app.profile = {'id': 'driver-1'}
        before = wallet.balance(app)
        prepaid.record(app, amount=Decimal('30.00'), energy_amount=Decimal('30.00'), method='balance',
                       connector_id='a')
        prepaid.link_session(app, 's9', connector_id='a')
        ended = {'id': 's9', 'status': 'completed', 'cost_estimate': '5.00', 'end_reason': 'battery_full'}
        self.assertIsNone(prepaid.settle(app, ended))
        self.assertEqual(wallet.balance(app), before)

    async def test_demo_balance_credit_is_unchanged_but_a_stripe_session_does_not_credit(self):
        app = HandlerApp()
        app.api = DemoApi()
        await app.api.login(DEMO_EMAIL, DEMO_PASSWORD)
        before = wallet.balance(app)
        prepaid.record(app, amount=Decimal('30.00'), energy_amount=Decimal('30.00'), method='balance',
                       connector_id='a')
        prepaid.link_session(app, 's1', connector_id='a')
        prepaid.record(app, amount=Decimal('30.00'), energy_amount=Decimal('30.00'), method='balance',
                       connector_id='b')
        prepaid.link_session(app, 's2', connector_id='b')
        paid = {'id': 's2', 'status': 'completed', 'cost_estimate': '5.00', 'payment': {'id': 'p1'}}
        self.assertIsNone(prepaid.settle(app, paid))
        self.assertEqual(prepaid.settle(app, {'id': 's1', 'status': 'completed', 'cost_estimate': '5.00'}),
                         Decimal('25.00'))
        self.assertEqual(wallet.balance(app), before + Decimal('25.00'))
        await app.api.close()


if __name__ == '__main__':
    unittest.main()
