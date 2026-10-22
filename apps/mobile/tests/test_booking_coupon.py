"""Cupom do motorista: bloco "Cupom de desconto" na revisão do assistente, desconto só na energia,
pagamento/início levando o código e o campo opcional de volta na etapa de limites do #F."""

import unittest
from decimal import Decimal

import flet as ft

from chargegrid_app.api_client import ApiError
from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DemoApi
from chargegrid_app.screens import booking, charging
from chargegrid_app.services import booking as rules
from chargegrid_app.services import payments, wallet
from test_behavior import HandlerApp, click, descendants
from test_booking import tap, texts
from test_consumer_flows import next_charging_step

CODE = 'BEMVINDO10'


def by_data(control, data):
    return next((item for item in descendants(control) if getattr(item, 'data', None) == data), None)


def money(text):
    return Decimal(text.replace('R$', '').replace('.', '').replace(',', '.').strip())


class BookingCouponTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        wallet.reset_demo()
        self.app = HandlerApp()
        self.app.api = DemoApi(clock=lambda: 0.0)
        await self.app.api.login(DEMO_EMAIL, DEMO_PASSWORD)
        self.app.profile = await self.app.api.request('GET', 'me')
        self.app.back = lambda event=None: None
        # Posto do próprio dono do cupom de boas-vindas (o cupom só vale nos postos dele).
        self.sid = (await self.app.api.request('GET', 'operator/stations'))['items'][0]['id']

    async def asyncTearDown(self):
        await self.app.api.close()

    async def screen(self, step, **kwargs):
        return await booking.build(self.app, step=step, station_id=self.sid, **kwargs)

    async def review(self, by='time', amount='30', kind='now'):
        await self.screen(1, kind=kind, pick=1, by=by, amount=amount)
        self.app.booking['pay'] = 'balance'
        return await self.screen(6)

    async def apply(self, review, code=CODE):
        field = by_data(review, 'coupon-code')
        field.value = code
        field.on_change(None)
        await tap(review, 'Aplicar')()
        return await self.screen(6)

    async def test_review_applies_coupon_and_strikes_the_full_total(self):
        review = await self.review()
        self.assertIn('Cupom de desconto', texts(review))
        full = money(by_data(review, 'total-amount').value)
        self.assertIsNone(by_data(review, 'total-full'))
        review = await self.apply(review, ' bemvindo10 ')
        self.assertEqual(self.app.booking['coupon'], {'code': CODE, 'discount_percent': 10})
        self.assertIsNotNone(by_data(review, 'coupon-applied'))
        self.assertIn(f'{CODE} · 10% OFF', texts(review))
        struck = by_data(review, 'total-full')
        self.assertEqual(money(struck.value), full)
        self.assertEqual(struck.style.decoration, ft.TextDecoration.LINE_THROUGH)
        discounted = money(by_data(review, 'total-amount').value)
        self.assertEqual(discounted, rules.discounted(full, 10))  # "Carregar agora": sem taxa de reserva
        self.assertIn(f'Cupom {CODE}: − {rules.money(full - discounted)} na energia', texts(review))
        await tap(review, 'Remover')()
        self.assertIsNone(self.app.booking['coupon'])

    async def test_reservation_fee_is_not_discounted(self):
        review = await self.apply(await self.review(kind='reserve'))
        full, discounted = money(by_data(review, 'total-full').value), money(by_data(review, 'total-amount').value)
        energy = full - rules.RESERVATION_FEE
        self.assertEqual(discounted, rules.discounted(energy, 10) + rules.RESERVATION_FEE)

    async def test_invalid_code_shows_inline_error_without_applying(self):
        review = await self.review()
        field = by_data(review, 'coupon-code')
        field.value = 'NAOEXISTE'
        field.on_change(None)
        await tap(review, 'Aplicar')()
        self.assertEqual(by_data(review, 'coupon-error').value, 'Cupom inválido para este posto.')
        self.assertTrue(by_data(review, 'coupon-error').visible)
        self.assertIsNone(self.app.booking['coupon'])
        field.value = ''
        await tap(review, 'Aplicar')()
        self.assertEqual(by_data(review, 'coupon-error').value, 'Digite o código do cupom.')

    async def test_value_mode_keeps_the_total_and_explains_more_energy(self):
        review = await self.apply(await self.review(by='value', amount='50,00'))
        self.assertIsNone(by_data(review, 'total-full'))
        # O total é o valor escolhido (já limitado ao máximo do carro), sem desconto no valor.
        self.assertEqual(money(by_data(review, 'total-amount').value), rules.parse_value(self.app.booking['value_text']))
        self.assertIn('o mesmo valor rende cerca de', by_data(review, 'total-coupon').value)

    async def test_balance_now_flow_debits_discount_and_starts_with_the_coupon(self):
        review = await self.apply(await self.review())
        discounted = money(by_data(review, 'total-amount').value)
        before = wallet.balance(self.app)
        await tap(review, 'Confirmar e iniciar no ponto')()
        self.assertEqual(wallet.balance(self.app), before - discounted)
        kwargs = self.app.go.await_args.kwargs
        self.assertEqual(kwargs['planning_intent']['coupon_code'], CODE)
        start = await charging.build(self.app, **kwargs)
        start = await next_charging_step(self.app, start)  # código #F → revisão (limites já escolhidos)
        self.assertIn(CODE, texts(start))
        await click(start, 'Solicitar início')(None)
        session = await self.app.api.request('GET', f"charging-sessions/{self.app.go.call_args.kwargs['session_id']}")
        self.assertEqual(session['discount_percent'], 10)

    async def test_coupon_disabled_before_start_is_removed_with_a_notice(self):
        review = await self.apply(await self.review())
        await tap(review, 'Confirmar e iniciar no ponto')()
        kwargs = self.app.go.await_args.kwargs
        self.app.api._coupons['demo-coupon-welcome']['active'] = False  # o dono desativou no meio do caminho
        start = await next_charging_step(self.app, await charging.build(self.app, **kwargs))
        await click(start, 'Solicitar início')(None)
        self.assertIn('não vale mais', self.app.notices[-1])
        self.assertEqual(self.app.charging_draft['coupon_code'], '')
        self.assertEqual(self.app.go.await_args.kwargs['step'], 3)

    async def test_stripe_payment_body_carries_the_coupon_and_demo_applies_it(self):
        intent = {'mode': 'time', 'minutes': 30, 'coupon_code': CODE}
        self.assertEqual(payments.request_body('a', intent)['coupon_code'], CODE)
        self.assertNotIn('coupon_code', payments.request_body('a', {'mode': 'time', 'minutes': 30}))
        point = (await self.app.api.request('GET', f'stations/{self.sid}'))['connectors'][0]
        plain = await self.app.api.request('POST', 'payments', {'connector_id': point['id'], 'mode': 'time',
                                                                'minutes': 30}, key='plain')
        await self.app.api.request('POST', f"payments/{plain['id']}/cancel")
        paid = await self.app.api.request('POST', 'payments', {'connector_id': point['id'], 'mode': 'time',
                                                               'minutes': 30, 'coupon_code': 'bemvindo10'},
                                          key='coupon')
        self.assertEqual((paid['discount_percent'], paid['coupon_code']), (10, CODE))
        self.assertLess(Decimal(paid['energy_cap']), Decimal(plain['energy_cap']))
        with self.assertRaises(ApiError) as refused:
            await self.app.api.request('POST', 'payments', {'connector_id': point['id'], 'mode': 'time',
                                                            'minutes': 30, 'coupon_code': 'NAOEXISTE'}, key='bad')
        self.assertEqual(refused.exception.code, 'invalid_coupon')

    async def test_demo_check_matches_the_api_contract(self):
        point = (await self.app.api.request('GET', f'stations/{self.sid}'))['connectors'][0]
        result = await self.app.api.request('POST', 'coupons/check', {'code': 'bemvindo10', 'connector_id': point['id']})
        self.assertEqual((result['code'], result['discount_percent']), (CODE, 10))
        with self.assertRaises(ApiError) as refused:
            await self.app.api.request('POST', 'coupons/check', {'code': 'X', 'connector_id': point['id']})
        self.assertEqual((refused.exception.code, str(refused.exception)), ('invalid_coupon', 'Cupom inválido para este posto.'))


class ChargingCouponFieldTests(unittest.IsolatedAsyncioTestCase):
    async def test_limits_step_offers_the_optional_coupon_and_sends_it(self):
        app = HandlerApp()
        app.api = DemoApi(clock=lambda: 0.0)
        await app.api.login(DEMO_EMAIL, DEMO_PASSWORD)
        app.profile = await app.api.request('GET', 'me')
        app.back = lambda event=None: None
        sid = (await app.api.request('GET', 'operator/stations'))['items'][0]['id']
        station = await app.api.request('GET', f'stations/{sid}')
        point = next(p for p in station['connectors'] if p.get('available'))
        screen = await charging.build(app, public_code=point['public_code'])
        screen = await next_charging_step(app, screen)
        self.assertIn('Cupom de desconto', texts(screen))
        coupon = next(c for c in descendants(screen) if isinstance(c, ft.TextField) and c.label == 'Cupom (opcional)')
        coupon.value = 'bemvindo10'
        await coupon.on_change(None)
        screen = await next_charging_step(app, screen)
        self.assertIn('bemvindo10', texts(screen))
        await click(screen, 'Solicitar início')(None)
        session = await app.api.request('GET', f"charging-sessions/{app.go.call_args.kwargs['session_id']}")
        self.assertEqual(session['discount_percent'], 10)
        await app.api.close()


if __name__ == '__main__':
    unittest.main()
