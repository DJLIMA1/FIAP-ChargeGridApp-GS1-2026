"""Pagamento Stripe (teste) no fluxo do motorista: serviço, assistente, início com payment_id e acerto.

O app nunca coleta dados de cartão: abre a Checkout hospedada (``ft.UrlLauncher``, mockado aqui),
consulta o pagamento a cada 2 s e só segue com a confirmação do servidor.
"""

import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import flet as ft

from chargegrid_app.api_client import ApiError
from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DemoApi
from chargegrid_app.screens import booking, charging
from chargegrid_app.services import payments, prepaid, wallet
from chargegrid_app.session import Session
from test_behavior import HandlerApp, descendants
from test_booking import STATION, tap


def texts(control):
    return [str(item.value) for item in descendants(control) if isinstance(item, ft.Text)]


def by_data(control, data):
    return next((item for item in descendants(control) if getattr(item, 'data', None) == data), None)


def iso(**delta):
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


def payment(status='awaiting_payment', **extra):
    row = {'id': 'p1', 'status': status, 'status_label': payments.METHOD_LABEL, 'amount': '57.00',
           'environment': 'test', 'connector_id': 'a', 'session_id': None, 'expires_at': iso(minutes=30),
           'start_deadline': None, 'checkout_url': 'https://checkout.stripe.com/c/pay/cs_test_1',
           'settlement': None}
    row.update(extra)
    return row


class PollApp(HandlerApp):
    """``HandlerApp`` que guarda também o intervalo da consulta."""

    def set_poll(self, callback, interval):
        self.poll, self.poll_interval = callback, interval


class FakeApi:
    """API real simulada por rotas ``(método, caminho)``: valor, exceção ou função ``(body, key)``."""

    is_demo = False

    def __init__(self, routes):
        self.routes, self.calls, self.cleared = routes, [], []
        self.session = Session()
        self.last_session_id = None
        self.counter = 0

    def new_key(self):
        self.counter += 1
        return f'key-{self.counter}'

    def clear_operation(self, path):
        self.cleared.append(path)

    async def request(self, method, path, body=None, *, key=None, params=None, auth=True):
        self.calls.append((method, path, deepcopy(body), key))
        handler = self.routes.get((method, path))
        if isinstance(handler, Exception):
            raise handler
        if callable(handler):
            return handler(body, key)
        return deepcopy(handler)


class PaymentServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_config_is_disabled_when_the_api_has_no_payments(self):
        app = HandlerApp()
        app.api.request = AsyncMock(side_effect=ApiError('não encontrado', 404, 'not_found'))
        self.assertEqual((await payments.config(app))['enabled'], False)
        app.api.request = AsyncMock(return_value={'enabled': True})
        self.assertFalse((await payments.config(app))['enabled'])  # guardado durante a sessão do app
        self.assertTrue((await payments.config(app, refresh=True))['enabled'])

    def test_request_body_lets_the_api_compute_the_cap(self):
        self.assertEqual(payments.request_body('a', {'mode': 'time', 'minutes': 30, 'max_power_kw': '22.0'}),
                         {'connector_id': 'a', 'mode': 'time', 'minutes': 30, 'max_power_kw': '22.0'})
        self.assertEqual(payments.request_body('a', {'mode': 'value', 'max_cost': '50.00'}),
                         {'connector_id': 'a', 'mode': 'value', 'max_cost': '50.00'})
        self.assertEqual(payments.request_body('a', {'mode': 'autonomy', 'km': 80}, Decimal('11.20')),
                         {'connector_id': 'a', 'mode': 'energy', 'energy_kwh': '11.20'})

    def test_settlement_badge_and_deadline_texts(self):
        done = payment('completed', settlement={'status': 'done', 'charged': '12.40', 'returned': '44.60',
                                                'return_kind': 'released', 'overstay_amount': '2.00'})
        self.assertEqual(payments.settlement_text(done), 'Cobrado R$ 12,40 · Devolvido R$ 44,60 (teste)')
        self.assertIn('Inclui R$ 2,00 de taxa de permanência.', payments.settlement_note(done))
        self.assertEqual(payments.settlement_text(payment('completed', settlement={'status': 'done', 'charged': '0.00',
                                                                                    'returned': '57.00'})),
                         'Nada cobrado · Devolvido R$ 57,00 (teste)')
        self.assertIsNone(payments.settlement_text(payment('in_use')))
        self.assertTrue(payments.pending_settlement(payment('in_use')))
        self.assertTrue(payments.pending_settlement(payment('in_use', settlement={'status': 'due'})))
        self.assertFalse(payments.pending_settlement(done))
        self.assertEqual(payments.badge_text({'status_label': 'Pago (teste) · em uso'}), 'Stripe · Pago (teste) · em uso')
        self.assertEqual(payments.badge_text({'status_label': 'Aguardando pagamento'}),
                         'Stripe · Aguardando pagamento (teste)')
        now = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(payments.seconds_left({'status': 'awaiting_payment',
                                                'expires_at': '2026-10-20T12:01:15+00:00'}, now), 75)
        self.assertEqual(payments.clock(75), '01:15')
        self.assertEqual(payments.money('1234.5'), 'R$ 1.234,50')


class RealAccountBookingTests(unittest.IsolatedAsyncioTestCase):
    """Conta real com Stripe (teste) ligada: só "Cartão ou Pix · Stripe (teste)"; nada de Saldo."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.env = patch.dict('os.environ', {'FLET_APP_STORAGE_DATA': self.directory.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.directory.cleanup()

    async def asyncSetUp(self):
        self.payment = payment()
        self.created = []

        def create(body, key):
            self.created.append((body, key))
            return deepcopy(self.payment)
        station = deepcopy(STATION)
        station['overstay'] = {'enabled': True, 'version': 'ovs-1', 'grace_minutes': 10, 'interval_minutes': 1,
                               'amount': '1.00', 'max_amount': '30.00',
                               'summary': 'Após a recarga: 10 min de tolerância, depois R$ 1,00/min (máx. R$ 30,00)'}
        self.api = FakeApi({
            ('GET', 'stations/s1'): station,
            ('GET', 'payments/config'): {'enabled': True, 'environment': 'test', 'test_card': '4242 4242 4242 4242'},
            ('POST', 'payments'): create,
            ('GET', 'payments/p1'): lambda body, key: deepcopy(self.payment),
            ('POST', 'payments/p1/cancel'): lambda body, key: {**self.payment, 'status': 'canceled'},
        })
        self.app = PollApp()
        self.app.api = self.api
        self.app.profile = {'id': 'driver-1'}
        self.app.back = lambda event=None: None

    async def screen(self, step, **kwargs):
        return await booking.build(self.app, step=step, station_id='s1', **kwargs)

    async def review(self, **state):
        await self.screen(1, kind='now', pick=1)
        self.app.booking.update(minutes_text='30', **state)
        return await self.screen(6)

    async def test_payment_step_only_offers_stripe_and_reservation_fee_is_not_charged(self):
        await self.screen(1, kind='reserve', pick=1)
        fee = await self.screen(2)
        spans = [span.text for item in descendants(fee) if isinstance(item, ft.Text) for span in item.spans or []]
        self.assertEqual(spans, ['Taxa de reserva: ', 'sem cobrança no pagamento de teste'])
        self.app.booking['minutes_text'] = '30'
        options = texts(await self.screen(5))
        self.assertIn('Cartão ou Pix · Stripe (teste)', options)
        self.assertNotIn('Saldo Disponível', options)
        self.assertEqual(self.app.booking['pay'], 'stripe')

    async def test_review_shows_stripe_total_and_overstay_summary(self):
        review = await self.review()
        copy = texts(review)
        self.assertIn('Total estimado', copy)
        self.assertIn('R$56,70', copy)  # estimativa; o teto final é calculado pela API
        self.assertIn('Após a recarga: 10 min de tolerância, depois R$ 1,00/min (máx. R$ 30,00)', copy)
        self.assertIsNotNone(by_data(review, 'overstay-terms'))

    async def test_confirm_creates_payment_with_idempotency_key_and_opens_the_hosted_checkout(self):
        await tap(await self.review(), 'Confirmar e iniciar no ponto')()
        self.assertEqual(self.created, [({'connector_id': 'a', 'mode': 'time', 'minutes': 30, 'max_power_kw': '60.0'},
                                         'key-1')])
        self.assertEqual(self.app.go.await_args.kwargs['step'], 7)
        waiting = await self.screen(7)
        copy = texts(waiting)
        for expected in ('Aguardando pagamento', 'R$ 57,00', 'Cartão de teste: 4242 4242 4242 4242',
                         'Abrir pagamento seguro', 'Aguardando a confirmação da Stripe (teste)…'):
            self.assertIn(expected, copy)
        self.assertTrue(any(text.startswith('Expira em 29:') or text.startswith('Expira em 30:') for text in copy))
        self.assertFalse([c for c in descendants(waiting) if isinstance(c, ft.TextField)])  # nada de cartão no app
        self.assertEqual(self.app.poll_interval, 2)
        launcher = AsyncMock()
        with patch('flet.UrlLauncher', return_value=launcher):
            await tap(waiting, 'Abrir pagamento seguro')()
        launcher.launch_url.assert_awaited_once_with('https://checkout.stripe.com/c/pay/cs_test_1')
        # Voltar e confirmar de novo o mesmo pedido repete a mesma chave (sem pagamento duplicado).
        await tap(await self.screen(6), 'Confirmar e iniciar no ponto')()
        self.assertEqual(self.created[1][1], 'key-1')

    async def test_polling_shows_declined_then_hands_off_with_the_payment_id(self):
        await tap(await self.review(), 'Confirmar e iniciar no ponto')()
        waiting = await self.screen(7)
        self.payment = payment('declined')
        await self.app.poll()
        copy = texts(waiting)
        self.assertIn('Pagamento recusado. Tente de novo com outro cartão de teste na mesma página.', copy)
        self.assertIn('Tentar de novo', copy)  # recusado não é final: reabre a mesma Checkout
        self.assertEqual(self.app.go.await_count, 1)
        self.payment = payment('authorized', start_deadline=iso(minutes=15), checkout_url=None)
        await self.app.poll()
        route, kwargs = self.app.go.await_args.args[0], self.app.go.await_args.kwargs
        self.assertEqual(route, 'charging')
        self.assertEqual(kwargs['planning_intent']['payment_id'], 'p1')
        self.assertEqual(kwargs['planning_intent']['payment_amount'], '57.00')
        self.assertEqual(kwargs['planning_intent']['overstay_terms_version'], 'ovs-1')
        self.assertEqual(prepaid.records(self.app), [])  # Stripe não usa a carteira simulada

    async def test_expired_payment_offers_retry_with_a_fresh_key(self):
        await tap(await self.review(), 'Confirmar e iniciar no ponto')()
        waiting = await self.screen(7)
        self.payment = payment('expired', checkout_url=None)
        await self.app.poll()
        copy = texts(waiting)
        self.assertIn('O prazo do pagamento acabou. Nada foi cobrado.', copy)
        retry = next(c for c in descendants(waiting) if isinstance(c, ft.Container) and c.on_click
                     and 'Tentar de novo' in texts(c))
        self.assertTrue(retry.visible)
        self.payment = payment()
        await retry.on_click(None)
        self.assertEqual([key for _, key in self.created], ['key-1', 'key-2'])
        self.assertIn('payments', self.api.cleared)  # o cliente esquece a chave do pedido anterior

    async def test_cancel_returns_to_the_review(self):
        await tap(await self.review(), 'Confirmar e iniciar no ponto')()
        await tap(await self.screen(7), 'Cancelar pagamento')()
        self.assertIn(('POST', 'payments/p1/cancel', None, None), self.api.calls)
        self.assertEqual(self.app.go.await_args.kwargs['step'], 6)
        self.assertIsNone(self.app.booking['payment'])

    async def test_without_stripe_in_the_api_falls_back_to_balance_only(self):
        self.api.routes[('GET', 'payments/config')] = ApiError('não encontrado', 404, 'not_found')
        await self.screen(1, kind='now', pick=1)
        self.app.booking['minutes_text'] = '30'
        options = texts(await self.screen(5))
        self.assertIn('Saldo Disponível', options)
        self.assertNotIn('Cartão ou Pix · Stripe (teste)', options)


class DemoStripeJourneyTests(unittest.IsolatedAsyncioTestCase):
    """Conta demo offline: pagar (simulado), iniciar com payment_id, terminar e ver o acerto."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.env = patch.dict('os.environ', {'FLET_APP_STORAGE_DATA': self.directory.name})
        self.env.start()
        wallet.reset_demo()

    def tearDown(self):
        self.env.stop()
        self.directory.cleanup()

    async def asyncSetUp(self):
        self.clock = [0.0]
        self.app = PollApp()
        self.app.api = DemoApi(clock=lambda: self.clock[0])
        await self.app.api.login(DEMO_EMAIL, DEMO_PASSWORD)
        self.app.profile = await self.app.api.request('GET', 'me')
        self.app.back = lambda event=None: None
        self.sid = 'demo-station-1'

    async def asyncTearDown(self):
        await self.app.api.close()

    async def test_pay_start_with_payment_id_and_see_charged_and_returned(self):
        before = wallet.balance(self.app)
        await booking.build(self.app, step=1, station_id=self.sid, kind='now', pick=1)
        self.app.booking.update(minutes_text='30', pay='stripe')
        options = texts(await booking.build(self.app, step=5, station_id=self.sid))
        self.assertIn('Saldo Disponível', options)  # demo: Saldo e Stripe simulada
        self.assertIn('Cartão ou Pix · Stripe (teste)', options)
        await tap(await booking.build(self.app, step=6, station_id=self.sid), 'Confirmar e iniciar no ponto')()
        waiting = await booking.build(self.app, step=7, station_id=self.sid)
        launcher = AsyncMock()
        with patch('flet.UrlLauncher', return_value=launcher):
            await tap(waiting, 'Abrir pagamento seguro')()  # demo: confirma como o cartão de teste
        launcher.launch_url.assert_not_awaited()
        await self.app.poll()
        self.assertEqual(self.app.go.await_args.kwargs['step'], 7)  # ainda aguardando (2 s)
        self.clock[0] = 3
        await self.app.poll()
        route, handoff = self.app.go.await_args.args[0], self.app.go.await_args.kwargs
        self.assertEqual(route, 'charging')
        payment_id = handoff['planning_intent']['payment_id']
        self.assertEqual(wallet.balance(self.app), before)  # Stripe: o Saldo não é tocado

        self.app.api.request = AsyncMock(wraps=self.app.api.request)
        start = await charging.build(self.app, **handoff)
        await tap(start, 'Continuar')()
        review = await charging.build(self.app, **{**handoff, 'step': 3})
        self.assertTrue(any(text.startswith('Stripe (teste) · R$ ') for text in texts(review)))
        await tap(review, 'Solicitar início')()
        posts = [call for call in self.app.api.request.await_args_list
                 if call.args[:2] == ('POST', 'charging-sessions')]
        self.assertEqual(posts[-1].args[2]['payment_id'], payment_id)
        session_id = self.app.go.await_args.kwargs['session_id']

        self.clock[0] = 10
        running = await charging.build(self.app, session_id=session_id)
        self.assertIn('Stripe · Pago (teste) · em uso', texts(running))
        self.clock[0] = 4000  # passa do teto/duração: a recarga simulada termina
        ended = await charging.build(self.app, session_id=session_id)
        await self.app.poll()  # primeira consulta do fim: busca o pagamento (o servidor acerta)
        copy = texts(ended)
        settled = [text for text in copy if text.startswith('Cobrado R$ ')]
        self.assertEqual(len(settled), 1)
        self.assertTrue(settled[0].endswith('(teste)'))
        current = await self.app.api.request('GET', f'payments/{payment_id}')
        settlement = current['settlement']
        self.assertEqual(Decimal(settlement['charged']) + Decimal(settlement['returned']), Decimal(current['amount']))
        self.assertEqual(current['status'], 'completed')
        self.assertEqual(wallet.balance(self.app), before)  # sobra volta pela Stripe, não como crédito
        self.assertIsNone(by_data(ended, 'prepaid-credit'))

    async def test_demo_payment_rules_mirror_the_api(self):
        api = self.app.api
        station = (await api.request('GET', f'stations/{self.sid}'))
        point = next(p for p in station['connectors'] if p['available'])
        body = {'connector_id': point['id'], 'mode': 'time', 'minutes': 20}
        created = await api.request('POST', 'payments', body, key='k1')
        self.assertEqual(await api.request('POST', 'payments', body, key='k1'), created)  # idempotente
        self.assertEqual(created['status'], 'awaiting_payment')
        start = {'presence_code': '#F12345', 'public_code': point['public_code'], 'max_duration_minutes': 20,
                 'payment_id': created['id']}
        with self.assertRaises(ApiError) as error:
            await api.request('POST', 'charging-sessions', start, key='s1')
        self.assertEqual(error.exception.code, 'payment_not_ready')
        await api.request('POST', f"payments/{created['id']}/demo-checkout")
        self.clock[0] = 3
        self.assertEqual((await api.request('GET', f"payments/{created['id']}"))['status'], 'authorized')
        canceled = await api.request('POST', f"payments/{created['id']}/cancel")
        self.assertEqual((canceled['status'], canceled['settlement']['charged']), ('canceled', '0.00'))


if __name__ == '__main__':
    unittest.main()
