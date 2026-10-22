"""Modo apresentação: sem Stripe, o pagamento simulado da 0.6.x (Saldo / Pix / Cartão).

Com o modo ligado o app não consulta ``payments/*``, não abre navegador, não envia ``payment_id`` e a
sobra do pré-pagamento simulado volta ao saldo (também em conta real). Desligado, a Stripe (teste) segue.
"""

import tempfile
import unittest
from copy import deepcopy
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import flet as ft

from chargegrid_app.api_client import ApiError
from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DemoApi
from chargegrid_app.screens import booking, charging
from chargegrid_app.services import payments, prepaid, vehicle_state, wallet
from test_behavior import descendants
from test_booking import STATION, tap
from test_driver_payments import FakeApi, PollApp, by_data, payment, texts

OLD_OPTIONS = ['Saldo Disponível', 'Pix', 'Cartão de Crédito / Débito']


def payment_calls(api):
    return [call for call in api.calls if call[1].startswith('payments')]


class TempStorage(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.env = patch.dict('os.environ', {'FLET_APP_STORAGE_DATA': self.directory.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.directory.cleanup()


class RealAccountPresentationTests(TempStorage):
    """Conta real com a Stripe ligada na API: no modo apresentação ela é ignorada por completo."""

    async def asyncSetUp(self):
        self.station = deepcopy(STATION)
        self.api = FakeApi({
            ('GET', 'stations/s1'): self.station,
            ('GET', 'payments/config'): {'enabled': True, 'environment': 'test'},
            ('POST', 'payments'): lambda body, key: payment(),
            ('POST', 'reservations'): lambda body, key: {'id': 'r1', 'status': 'pending'},
        })
        self.app = PollApp()
        self.app.api = self.api
        self.app.profile = {'id': 'driver-1'}
        self.app.back = lambda event=None: None
        self.assertTrue(vehicle_state.set_presentation_mode(self.app, True))

    async def screen(self, step, **kwargs):
        return await booking.build(self.app, step=step, station_id='s1', **kwargs)

    async def test_old_options_and_no_payments_route_is_called(self):
        await self.screen(1, kind='reserve', pick=1)
        fee = await self.screen(2)
        spans = [span.text for item in [i for i in descendants(fee) if isinstance(i, ft.Text)] for span in item.spans or []]
        self.assertEqual(spans, ['Taxa de reserva: ', 'R$4,90'])  # taxa simulada da 0.6.x
        self.app.booking['minutes_text'] = '30'
        copy = texts(await self.screen(5))
        for label in OLD_OPTIONS:
            self.assertIn(label, copy)
        self.assertNotIn(payments.METHOD_LABEL, copy)
        self.assertEqual(self.app.booking['pay'], 'balance')
        self.assertEqual(payment_calls(self.api), [])

    async def test_pix_already_paid_hands_off_without_payment_id_and_records_the_prepayment(self):
        await self.screen(1, kind='now', pick=1)
        self.app.booking.update(minutes_text='30', pay='pix')
        review = await self.screen(6)
        copy = texts(review)
        self.assertIn('Pix', copy)
        self.assertIn('Total', copy)
        self.assertNotIn('Total estimado', copy)
        await tap(review, 'Confirmar e iniciar no ponto')()
        self.assertEqual(self.app.go.await_args.kwargs['step'], 7)
        launcher = AsyncMock()
        with patch('flet.UrlLauncher', return_value=launcher):
            pix = await self.screen(7)
            copy = texts(pix)
            for expected in ('Efetuar Pagamento', 'Copiar código Pix', 'Já efetuei o pagamento', 'Expira em 14:59'):
                self.assertIn(expected, copy)
            self.assertNotIn('Abrir pagamento seguro', copy)
            await tap(pix, 'Já efetuei o pagamento')()
        launcher.launch_url.assert_not_awaited()
        route, handoff = self.app.go.await_args.args[0], self.app.go.await_args.kwargs
        self.assertEqual(route, 'charging')
        self.assertNotIn('payment_id', handoff['planning_intent'])
        self.assertEqual([row['method'] for row in prepaid.records(self.app)], ['pix'])
        self.assertEqual(payment_calls(self.api), [])

    async def test_card_form_is_illustrative_and_reservation_is_created(self):
        await self.screen(1, kind='reserve', pick=1)
        self.app.booking.update(minutes_text='30', pay='card')
        await tap(await self.screen(6), 'Confirmar reserva')()
        form = await self.screen(7)
        fields = [c for c in descendants(form) if isinstance(c, ft.TextField)]
        self.assertEqual(len(fields), 4)
        with self.assertRaises(ApiError) as error:
            await tap(form, 'Efetuar Pagamento')()
        self.assertIn('Preencha os dados do cartão', str(error.exception))
        for field, value in zip(fields, ('4111111111111111', 'Fulano', '12/30', '123')):
            field.value = value
        await tap(form, 'Efetuar Pagamento')()
        self.assertTrue(all(not field.value for field in fields))  # nada fica guardado
        self.assertEqual(self.app.go.await_args.kwargs['step'], 8)
        row = prepaid.records(self.app)[0]
        self.assertEqual((row['method'], row['reservation_id'], row['amount']), ('card', 'r1', '61.60'))
        self.assertEqual(payment_calls(self.api), [])

    async def test_balance_debits_the_wallet_like_before(self):
        wallet.credit(self.app, Decimal('100.00'), 'Recarga de saldo')
        await self.screen(1, kind='now', pick=1)
        self.app.booking.update(minutes_text='30', pay='balance')
        await tap(await self.screen(6), 'Confirmar e iniciar no ponto')()
        self.assertEqual(self.app.go.await_args.args[0], 'charging')
        self.assertEqual(wallet.balance(self.app), Decimal('100.00') - Decimal('56.70'))
        self.assertEqual(payment_calls(self.api), [])

    async def test_prepay_required_station_shows_the_warning_instead_of_starting(self):
        self.station['prepay_required'] = True
        await self.screen(1, kind='now', pick=1)
        self.app.booking.update(minutes_text='30', pay='pix')
        step5 = await self.screen(5)
        self.assertIn(payments.PRESENTATION_PREPAY, texts(step5))
        self.assertIsNotNone(by_data(step5, 'prepay-presentation'))
        with self.assertRaises(ApiError) as error:
            await tap(step5, 'Continuar')()
        self.assertEqual(str(error.exception), payments.PRESENTATION_PREPAY)
        review = await self.screen(6)
        self.assertIn(payments.PRESENTATION_PREPAY, texts(review))
        with self.assertRaises(ApiError):
            await tap(review, 'Confirmar e iniciar no ponto')()
        self.assertEqual(self.app.go.await_count, 0)
        self.assertEqual(payment_calls(self.api), [])

    async def test_mode_off_keeps_the_stripe_flow(self):
        vehicle_state.set_presentation_mode(self.app, False)
        await self.screen(1, kind='now', pick=1)
        self.app.booking['minutes_text'] = '30'
        copy = texts(await self.screen(5))
        self.assertIn(payments.METHOD_LABEL, copy)
        self.assertNotIn('Pix', copy)
        self.assertEqual(payment_calls(self.api), [('GET', 'payments/config', None, None)])
        await tap(await self.screen(6), 'Confirmar e iniciar no ponto')()
        self.assertIn('POST', [call[0] for call in payment_calls(self.api)])
        self.assertEqual(self.app.go.await_args.kwargs['step'], 7)
        self.assertIn('Abrir pagamento seguro', texts(await self.screen(7)))


class RealAccountSurplusCreditTests(TempStorage):
    def make_app(self):
        app = PollApp()
        app.api = FakeApi({})
        app.profile = {'id': 'driver-1'}
        return app

    def test_presentation_credits_the_surplus_in_a_real_account(self):
        app = self.make_app()
        prepaid.record(app, amount=Decimal('30.00'), energy_amount=Decimal('30.00'), method='pix',
                       connector_id='a')
        prepaid.link_session(app, 'sess-1', connector_id='a')
        ended = {'id': 'sess-1', 'status': 'completed', 'cost_estimate': '12.00', 'end_reason': 'battery_full'}
        vehicle_state.set_presentation_mode(app, False)
        self.assertIsNone(prepaid.settle(app, ended))  # 0.7.0: conta real sem crédito
        vehicle_state.set_presentation_mode(app, True)
        self.assertEqual(prepaid.settle(app, ended), Decimal('18.00'))
        self.assertEqual(wallet.balance(app), Decimal('18.00'))
        self.assertEqual(prepaid.settle(app, ended), Decimal('18.00'))  # uma única vez
        self.assertEqual(wallet.balance(app), Decimal('18.00'))
        self.assertIsNone(prepaid.settle(app, {**ended, 'payment': {'id': 'p1'}}))


class DemoPresentationJourneyTests(TempStorage):
    """Demo: Pix simulado → início sem ``payment_id`` → fim com a sobra creditada; sem selo da Stripe."""

    def setUp(self):
        super().setUp()
        wallet.reset_demo()

    async def asyncSetUp(self):
        self.clock = [0.0]
        self.app = PollApp()
        self.app.api = DemoApi(clock=lambda: self.clock[0])
        await self.app.api.login(DEMO_EMAIL, DEMO_PASSWORD)
        self.app.profile = await self.app.api.request('GET', 'me')
        self.app.back = lambda event=None: None
        self.sid = 'demo-station-1'
        vehicle_state.set_presentation_mode(self.app, True)

    async def asyncTearDown(self):
        await self.app.api.close()

    async def test_pix_start_without_payment_id_and_surplus_credit(self):
        self.app.api.request = AsyncMock(wraps=self.app.api.request)
        await booking.build(self.app, step=1, station_id=self.sid, kind='now', pick=1)
        self.app.booking.update(minutes_text='30', pay='pix')
        self.assertEqual(texts(await booking.build(self.app, step=5, station_id=self.sid)).count('Pix'), 1)
        await tap(await booking.build(self.app, step=6, station_id=self.sid), 'Confirmar e iniciar no ponto')()
        await tap(await booking.build(self.app, step=7, station_id=self.sid), 'Já efetuei o pagamento')()
        handoff = self.app.go.await_args.kwargs
        before = wallet.balance(self.app)

        start = await charging.build(self.app, **handoff)
        await tap(start, 'Continuar')()
        review = await charging.build(self.app, **{**handoff, 'step': 3})
        self.assertFalse([text for text in texts(review) if text.startswith('Stripe')])
        await tap(review, 'Solicitar início')()
        posts = [call for call in self.app.api.request.await_args_list
                 if call.args[:2] == ('POST', 'charging-sessions')]
        self.assertNotIn('payment_id', posts[-1].args[2])
        session_id = self.app.go.await_args.kwargs['session_id']

        self.clock[0] = 10
        running = await charging.build(self.app, session_id=session_id)
        self.assertFalse([text for text in texts(running) if text.startswith('Stripe')])
        # Bateria cheia (o celular chegou a 100 %): a recarga termina antes de gastar o valor pago.
        await self.app.api.request('POST', f'charging-sessions/{session_id}/soc', {'soc_percent': 100})
        self.clock[0] += 5
        ended = await charging.build(self.app, session_id=session_id)
        self.assertIsNotNone(by_data(ended, 'prepaid-credit'))
        self.assertGreater(wallet.balance(self.app), before)
        used = [call.args[1] for call in self.app.api.request.await_args_list]
        self.assertFalse([path for path in used if str(path).startswith('payments')])

    async def test_stale_stripe_session_shows_no_badge_or_settlement(self):
        vehicle_state.set_presentation_mode(self.app, False)
        await booking.build(self.app, step=1, station_id=self.sid, kind='now', pick=1)
        self.app.booking.update(minutes_text='30', pay='stripe')
        await tap(await booking.build(self.app, step=6, station_id=self.sid), 'Confirmar e iniciar no ponto')()
        await tap(await booking.build(self.app, step=7, station_id=self.sid), 'Abrir pagamento seguro')()
        self.clock[0] = 3
        await self.app.poll()
        handoff = self.app.go.await_args.kwargs
        await tap(await charging.build(self.app, **handoff), 'Continuar')()
        await tap(await charging.build(self.app, **{**handoff, 'step': 3}), 'Solicitar início')()
        session_id = self.app.go.await_args.kwargs['session_id']
        vehicle_state.set_presentation_mode(self.app, True)
        self.clock[0] = 10
        running = await charging.build(self.app, session_id=session_id)
        self.assertFalse([text for text in texts(running) if text.startswith('Stripe')])
        self.clock[0] = 4000
        self.app.api.request = AsyncMock(wraps=self.app.api.request)
        ended = await charging.build(self.app, session_id=session_id)
        if self.app.poll:
            await self.app.poll()
        self.assertFalse([text for text in texts(ended) if text.startswith('Cobrado')])
        self.assertIsNone(by_data(ended, 'payment-settlement'))
        used = [call.args[1] for call in self.app.api.request.await_args_list]
        self.assertFalse([path for path in used if str(path).startswith('payments')])


class ChargingPrepayTests(TempStorage):
    """Início pelo #F num posto com ``prepay_required``: o 402 vira o aviso do modo apresentação."""

    async def asyncSetUp(self):
        self.clock = [0.0]
        self.app = PollApp()
        self.app.api = DemoApi(clock=lambda: self.clock[0])
        await self.app.api.login(DEMO_EMAIL, DEMO_PASSWORD)
        self.app.profile = await self.app.api.request('GET', 'me')
        self.app.back = lambda event=None: None
        self.app.api._stations['demo-station-1']['prepay_required'] = True

    async def asyncTearDown(self):
        await self.app.api.close()

    async def start(self):
        station = await self.app.api.request('GET', 'stations/demo-station-1')
        point = next(p for p in station['connectors'] if p['available'])
        screen = await charging.build(self.app, public_code=point['public_code'])
        for _ in range(3):  # código #F → limites → revisão
            if 'Solicitar início' in texts(screen):
                break
            await tap(screen, 'Continuar')()
            screen = await charging.build(self.app, **self.app.go.await_args.kwargs)
        review = screen
        with self.assertRaises(ApiError) as error:
            await tap(review, 'Solicitar início')()
        return error.exception

    async def test_payment_required_becomes_the_presentation_warning(self):
        vehicle_state.set_presentation_mode(self.app, True)
        error = await self.start()
        self.assertEqual((str(error), error.code), (payments.PRESENTATION_PREPAY, 'payment_required'))

    async def test_mode_off_keeps_the_api_message(self):
        vehicle_state.set_presentation_mode(self.app, False)
        error = await self.start()
        self.assertEqual(error.code, 'payment_required')
        self.assertNotEqual(str(error), payments.PRESENTATION_PREPAY)


if __name__ == '__main__':
    unittest.main()
