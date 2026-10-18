"""Assistente de recarga (rota ``booking``): regras puras e fluxo completo na conta demo."""

import unittest
from datetime import datetime
from decimal import Decimal

import flet as ft

from chargegrid_app.api_client import ApiError
from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DemoApi
from chargegrid_app.screens import booking
from chargegrid_app.services import booking as rules
from chargegrid_app.services import wallet
from test_behavior import HandlerApp, descendants

STATION = {'id': 's1', 'active': True, 'name': 'Villa Lobos', 'address': 'Av. Prof Fonseca Rodrigues, 4777',
           'connectors': [
               {'id': 'a', 'connector_type': 'CCS2', 'power_kw': '60.000', 'price_per_kwh': '1.89', 'available': True,
                'online': True, 'active': True},
               {'id': 'b', 'connector_type': 'CCS2', 'power_kw': '60.000', 'price_per_kwh': '1.89', 'available': False,
                'online': True, 'active': True},
               {'id': 'c', 'connector_type': 'Tipo 2', 'power_kw': '22.000', 'price_per_kwh': '1.50', 'available': True,
                'online': True, 'active': True},
               {'id': 'd', 'connector_type': 'Tipo 2', 'power_kw': '22.000', 'price_per_kwh': '1.50', 'available': True,
                'online': True, 'active': True}]}


def texts(control):
    return [str(item.value) for item in descendants(control) if isinstance(item, ft.Text)]


def tap(screen, label):
    for item in descendants(screen):
        if getattr(item, 'on_click', None) and any(
                isinstance(sub, ft.Text) and sub.value == label for sub in descendants(item)):
            return item.on_click
    raise AssertionError(f'sem controle {label!r}')


class RulesTests(unittest.TestCase):
    def test_groups_titles_and_free_counts(self):
        groups = rules.group_connectors(STATION)
        self.assertEqual([rules.group_title(g) for g in groups], ['CCS2 - 60 kW', 'Tipo 2 - 22 kW'])
        self.assertEqual([rules.group_subtitle(g) for g in groups], ['1 de 2 conectores livre', '2 conectores livres'])

    def test_price_by_time_matches_reference_total(self):
        result = rules.estimate(60, '1.89', minutes=30)
        self.assertEqual((result['energy_kwh'], result['cost']), (Decimal('30.00'), Decimal('56.70')))
        self.assertEqual(rules.money(rules.total(result['cost'], False)), 'R$56,70')
        self.assertEqual(rules.total(result['cost'], True), Decimal('61.60'))

    def test_price_by_value_derives_minutes(self):
        result = rules.estimate(60, '1.89', value='56,70')
        self.assertEqual(result['minutes'], 30)
        self.assertEqual(result['cost'], Decimal('56.70'))

    def test_parsing_and_formatting(self):
        self.assertEqual(rules.parse_value('249,90'), Decimal('249.90'))
        self.assertEqual(rules.parse_value('1.249,90'), Decimal('1249.90'))
        self.assertEqual(rules.parse_minutes(' 30 '), 30)
        for bad in ('', 'abc', '0', '-5', '2,5'):
            with self.assertRaises(ValueError):
                rules.parse_minutes(bad)
        with self.assertRaises(ValueError):
            rules.parse_value('0')
        self.assertEqual(rules.money('1234.5'), 'R$1.234,50')
        self.assertEqual(rules.fmt_number('7.200'), '7,2')

    def test_time_slots_are_future_half_hours(self):
        self.assertEqual(rules.time_slots(datetime(2026, 10, 18, 12, 5)), ['12:30', '13:00', '13:30'])
        self.assertEqual(rules.time_slots(datetime(2026, 10, 18, 12, 25)), ['13:00', '13:30', '14:00'])
        self.assertEqual(rules.time_slots(datetime(2026, 10, 18, 23, 40))[0], '00:00')

    def test_reservation_code_is_stable(self):
        self.assertEqual(rules.reservation_code('x'), rules.reservation_code('x'))
        self.assertRegex(rules.reservation_code('demo-reservation-9'), r'^CG-\d{4}$')


class BookingFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        wallet.reset_demo()
        self.app = HandlerApp()
        self.app.api = DemoApi(clock=lambda: 0.0)
        await self.app.api.login(DEMO_EMAIL, DEMO_PASSWORD)
        self.app.profile = await self.app.api.request('GET', 'me')
        self.app.back = lambda event=None: None
        self.sid = 'demo-station-1'

    async def screen(self, step, **kwargs):
        return await booking.build(self.app, step=step, station_id=self.sid, **kwargs)

    async def test_without_station_offers_search(self):
        screen = await booking.build(self.app, step=1)
        self.assertIn('Buscar estação', texts(screen))

    async def test_step_one_requires_a_connector(self):
        screen = await self.screen(1)
        self.assertIn('Qual conector deseja usar?', texts(screen))
        with self.assertRaises(AssertionError):  # desabilitado: sem ação até escolher um conector
            tap(screen, 'Continuar')

    async def test_reserve_with_balance_creates_reservation_and_debits(self):
        before = wallet.balance(self.app)
        screen = await self.screen(1)
        await tap(screen, next(t for t in texts(screen) if ' - ' in t))()
        screen = await self.screen(1)
        await tap(screen, 'Continuar')()
        self.assertEqual(self.app.go.await_args.kwargs['step'], 2)
        self.app.booking['minutes_text'] = '30'
        screen = await self.screen(6)
        self.assertIn('Confirmar Recarga', texts(screen))
        self.assertTrue(any(t.startswith('Inclui taxa de reserva') for t in texts(screen)))
        await tap(screen, 'Confirmar Recarga')()
        self.assertEqual(self.app.go.await_args.args[0], 'booking')
        self.assertEqual(self.app.go.await_args.kwargs['step'], 8)
        result = self.app.booking['result']
        self.assertRegex(result['code'], r'^CG-\d{4}$')
        current = await self.app.api.request('GET', 'reservations/current')
        self.assertEqual(current['id'], result['id'])
        self.assertEqual(wallet.balance(self.app), before - Decimal(result['paid']))
        done = await self.screen(8)
        self.assertIn('Reserva confirmada', texts(done))
        await tap(done, 'Cancelar Recarga')()
        self.assertEqual(wallet.balance(self.app), before)

    async def test_insufficient_balance_blocks_payment(self):
        wallet.debit(self.app, wallet.balance(self.app) - Decimal('1.00'), 'teste')
        await self.screen(1)
        self.app.booking['minutes_text'] = '30'
        screen = await self.screen(5)
        with self.assertRaises(ApiError):
            await tap(screen, 'Continuar')()

    async def test_now_hands_off_to_charging(self):
        await self.screen(1)
        self.app.booking.update(mode='now', minutes_text='20', pay='pix')
        screen = await self.screen(6)
        await tap(screen, 'Confirmar Recarga')()
        self.assertEqual(self.app.go.await_args.kwargs['step'], 7)
        screen = await self.screen(7)
        await tap(screen, 'Já paguei (Confirmar)')()
        self.assertEqual(self.app.go.await_args.args[0], 'charging')
        self.assertIn('point_context', self.app.go.await_args.kwargs)

    async def test_card_form_never_keeps_card_data(self):
        await self.screen(1)
        self.app.booking.update(mode='now', minutes_text='20', pay='card')
        screen = await self.screen(7)
        with self.assertRaises(ApiError):
            await tap(screen, 'Efetuar Pagamento')()
        for name in ('number', 'cvv'):
            self.assertNotIn(name, self.app.booking)


if __name__ == '__main__':
    unittest.main()
