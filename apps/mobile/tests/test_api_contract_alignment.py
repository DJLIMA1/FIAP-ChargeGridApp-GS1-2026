"""App (e demo) alinhado à API real: permanência, potência ao vivo, pagamentos e recibo.

Os formatos daqui vêm do código da API (``apps/api/app``) e do núcleo compartilhado
(``chargegrid_core.overstay``/``receipt``), não da documentação do contrato.
"""

import tempfile
import unittest
from decimal import Decimal
from unittest.mock import patch

import flet as ft

from chargegrid_app import navigation
from chargegrid_app.api_client import ApiError
from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DemoApi
from chargegrid_app.screens import booking, charge_detail, charging
from chargegrid_app.services import tariffs as tariff_service
from chargegrid_app.services import wallet
from chargegrid_core import overstay as overstay_rules
from chargegrid_core import receipt as core_receipt
from test_behavior import descendants
from test_booking import STATION
from test_driver_payments import FakeApi, PollApp, by_data, texts

ROTATION = {'enabled': True, 'start_after_min': 10, 'interval_min': 1, 'amount': '1.00', 'max_amount': '5.00'}
# Bloco ``overstay`` de uma sessão como ``app.overstay.view`` devolve (sem termos aceitos, já fechado).
CLOSED_WITHOUT_TERMS = {'status': 'closed', 'fee_applies': False, 'started_at': '2026-10-20T13:00:00+00:00',
                        'ended_at': '2026-10-20T13:20:00+00:00', 'end_reason': 'disconnected',
                        'billable_seconds': 1200, 'billable_minutes': 0, 'grace_remaining_seconds': 0,
                        'fee_due': '0.00', 'max_fee': None, 'as_of': '2026-10-20T13:20:00+00:00', 'terms': None}


def all_texts(control):
    return '\n'.join(str(item.value) for item in descendants(control) if isinstance(item, ft.Text))


def api_receipt(payment=None, overstay=None, changes=None):
    """Recibo montado pelo MESMO núcleo da API com seções no formato de ``payments.receipt.receipt_payment``,
    ``app.overstay.receipt_extras`` e ``power.receipt.power_changes``."""
    session = {'id': '1a2b3c4d-0000-0000-0000-000000000000', 'status': 'completed', 'source': 'simulated',
               'created_at': '2026-10-20T12:59:00+00:00', 'started_at': '2026-10-20T13:00:00+00:00',
               'ended_at': '2026-10-20T13:40:00+00:00', 'energy_wh': '12500.000', 'price_per_kwh': '2.0000',
               'base_price_per_kwh': '2.0000', 'demand_multiplier': '1.00', 'discount_percent': 0,
               'cost_estimate': '25.0000', 'end_reason': 'duration_limit'}
    sections = {}
    if payment is not None:
        sections['payment'] = payment
    if overstay is not None:
        sections['overstay'] = overstay
    if changes is not None:
        sections['power_changes'] = changes
    return core_receipt.build_receipt({'session': session, 'station': {'name': 'Posto', 'address': 'Rua A'},
                                       'point': {'public_code': 'CG-1', 'connector_type': 'CCS2', 'power_kw': '22'},
                                       'events': [], 'samples': [], 'sections': sections})


STRIPE_PAYMENT = {  # ``payments.receipt.receipt_payment`` de um pagamento acertado
    'environment': 'sandbox', 'provider': 'stripe', 'provider_reference': 'pi_test_9', 'method': 'card',
    'status': 'completed', 'settlement_status': 'done', 'authorized_amount': '60.00', 'captured_amount': '27.00',
    'refunded_amount': '0.00', 'net_amount': '27.00', 'charged_amount': '27.00', 'energy_amount': '25.00',
    'overstay_amount': '2.00', 'waived_amount': '0.00', 'uncollected_amount': '0.00', 'below_minimum': False,
    'provider_fee': '1.10', 'refund_status': 'released', 'confirmed_at': '2026-10-20T12:58:00+00:00',
    'settled_at': '2026-10-20T13:45:00+00:00'}


def overstay_extra(phase='billing', final=False, terms=True):
    """``app.overstay.receipt_extras`` (o núcleo do recibo sobrescreve ``status`` com ``available``)."""
    return {'phase': phase, 'grace_minutes': 10 if terms else None, 'started_at': '2026-10-20T13:40:00+00:00',
            'ended_at': None if not final else '2026-10-20T14:00:00+00:00', 'end_reason': None,
            'billable_minutes': 4 if terms else 0, 'rate': '1.0000' if terms else None,
            'max_amount': '30.00' if terms else None, 'amount': '4.00' if terms else None, 'final': final,
            'summary': None, 'waived': False}


class OverstayRulesTests(unittest.TestCase):
    def test_rotation_fee_stops_at_the_max_amount_like_the_api(self):
        # API: chargegrid_core.overstay.fee_due = min(teto, valor × intervalos completos).
        self.assertEqual(tariff_service.rotation_fee({'rotation': ROTATION}, 60), Decimal('5.00'))
        self.assertEqual(tariff_service.rotation_fee({'rotation': ROTATION}, 13), Decimal('3.00'))
        terms = overstay_rules.terms_from_rotation(ROTATION)
        self.assertEqual(tariff_service.rotation_fee({'rotation': ROTATION}, 60),
                         overstay_rules.fee_due(terms, 60 * 60))

    def test_closed_overstay_without_accepted_terms_is_not_called_tolerance(self):
        self.assertIsNone(charging.overstay_lines(CLOSED_WITHOUT_TERMS))
        within = {**CLOSED_WITHOUT_TERMS, 'fee_applies': True, 'max_fee': '30.00'}
        self.assertEqual(charging.overstay_lines(within)[0], 'Desconectado dentro da tolerância')


class ReceiptShapeTests(unittest.TestCase):
    def test_payment_situation_comes_from_payment_status(self):
        data = api_receipt(payment=STRIPE_PAYMENT)
        self.assertEqual((data['payment']['status'], data['payment']['payment_status']), ('available', 'completed'))
        text = all_texts(charge_detail.payment_section(data['payment']))
        self.assertIn('Situação', text)
        self.assertIn('Concluído', text)
        self.assertIn('Cobrado', text)
        self.assertIn('R$ 27,00', text)

    def test_overstay_section_reads_phase_cap_and_partial_value(self):
        data = api_receipt(overstay=overstay_extra())
        self.assertEqual((data['overstay']['status'], data['overstay']['phase']), ('available', 'billing'))
        text = all_texts(charge_detail.payment_section(None, data['overstay']))
        for expected in ('Em cobrança (carro conectado)', 'Teto por recarga', 'R$ 30,00', 'R$ 4,00',
                         'Valor parcial'):
            self.assertIn(expected, text)
        closed = all_texts(charge_detail.payment_section(None, api_receipt(overstay=overstay_extra('closed', True))['overstay']))
        self.assertIn('Encerrada', closed)
        self.assertNotIn('Valor parcial', closed)

    def test_overstay_without_terms_says_no_fee(self):
        data = api_receipt(overstay=overstay_extra('closed', True, terms=False))
        text = all_texts(charge_detail.payment_section(None, data['overstay']))
        self.assertIn('Sem taxa', text)
        self.assertNotIn('—', text.split('Taxa de permanência', 1)[1])

    def test_failed_power_change_shows_the_api_failure_label(self):
        change = {'at': '2026-10-20T13:20:00+00:00', 'requested_kw': '6.000', 'applied_kw': None,
                  'previous_kw': '11.000', 'status': 'failed', 'reason_code': 'store_load',
                  'reason_label': 'Redução de potência: a loja usa mais energia', 'confirmed_at': None,
                  'source': 'rebalance', 'direction': 'reduce', 'failure_code': 'unconfirmed',
                  'failure_label': 'O equipamento não confirmou o ajuste a tempo'}
        data = api_receipt(changes=[change])
        text = all_texts(charge_detail.session_section({'power': data['power']}))
        self.assertIn('Não aplicada', text)
        self.assertIn('O equipamento não confirmou o ajuste a tempo', text)


class NavigationAndShortcutTests(unittest.IsolatedAsyncioTestCase):
    def test_native_back_from_charge_detail_returns_to_the_same_history_list(self):
        self.assertEqual(navigation.parent_route('history', {'session': 's1'}), ('history', {}))
        self.assertEqual(navigation.parent_route('history', {'session': 's1', 'manage': True, 'offset': 20}),
                         ('history', {'manage': True, 'offset': 20}))
        self.assertEqual(navigation.parent_route('history', {'session': 's1', 'station_id': 'st'}),
                         ('history', {'station_id': 'st'}))
        self.assertEqual(navigation.parent_route('history', {'receipt': 's1'}), ('history', {}))
        self.assertEqual(navigation.parent_route('history', {'receipt': 's1', 'offset': 50}),
                         ('history', {'offset': 50}))
        self.assertEqual(navigation.parent_route('history', {}), ('home', {}))

    async def test_finished_charge_offers_the_receipt_shortcut(self):
        row = {'id': 's9', 'status': 'completed', 'connector': {'power_kw': '22.000', 'public_code': 'CG-1'},
               'started_at': '2026-10-20T12:00:00+00:00', 'ended_at': '2026-10-20T12:30:00+00:00',
               'last_measurement_at': '2026-10-20T12:30:00+00:00', 'max_duration_minutes': 60,
               'energy_wh': '1000.000', 'cost_estimate': '1.8900', 'online': True, 'station_address': 'Rua A, 1',
               'source': 'simulated', 'end_reason': 'duration_limit', 'payment': None,
               'overstay': {**CLOSED_WITHOUT_TERMS, 'status': 'none'}, 'settlement_ready': True}
        app = PollApp()
        app.api = FakeApi({('GET', 'charging-sessions/s9'): row})
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ',
                                                                     {'FLET_APP_STORAGE_DATA': directory}):
            screen = await charging.build(app, session_id='s9')
        shortcut = by_data(screen, 'receipt-shortcut')
        self.assertIsNotNone(shortcut)
        self.assertIn('Ver detalhes da recarga', texts(shortcut))
        clickable = next(item for item in descendants(shortcut) if getattr(item, 'on_click', None))
        await clickable.on_click(None)
        app.go.assert_awaited_with('history', session='s9')

    async def test_running_charge_has_no_receipt_shortcut(self):
        row = {'id': 's9', 'status': 'charging', 'connector': {'power_kw': '22.000'}, 'max_duration_minutes': 60,
               'started_at': '2026-10-20T12:00:00+00:00', 'online': True, 'energy_wh': '0', 'cost_estimate': '0'}
        app = PollApp()
        app.api = FakeApi({('GET', 'charging-sessions/s9'): row})
        screen = await charging.build(app, session_id='s9')
        self.assertIsNone(by_data(screen, 'receipt-shortcut'))


class StripeReviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_review_says_the_authorization_includes_the_overstay_cap(self):
        # API: payments.service.quote -> amount_cents = teto da energia + overstay_reserve_cents (teto da taxa).
        station = {**STATION, 'overstay': overstay_rules.public(overstay_rules.terms_from_rotation(
            {**ROTATION, 'max_amount': '30.00'}))}
        app = PollApp()
        app.api = FakeApi({('GET', 'stations/s1'): station,
                           ('GET', 'payments/config'): {'enabled': True, 'environment': 'test'}})
        app.profile = {'id': 'driver-1'}
        app.back = lambda event=None: None
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ',
                                                                     {'FLET_APP_STORAGE_DATA': directory}):
            await booking.build(app, step=1, station_id='s1', kind='now', pick=1)
            app.booking.update(minutes_text='30')
            copy = all_texts(await booking.build(app, step=6, station_id='s1'))
        self.assertIn('A pré-autorização inclui até R$30,00 da taxa de permanência (teto)', copy)


class DemoMirrorsApiTests(unittest.IsolatedAsyncioTestCase):
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
        self.api = DemoApi(clock=lambda: self.clock[0])
        await self.api.login(DEMO_EMAIL, DEMO_PASSWORD)
        self.station = (await self.api.request('GET', 'operator/stations'))['items'][0]
        self.sid = self.station['id']
        self.point = next(p for p in self.station['connectors'] if p['available'])

    async def asyncTearDown(self):
        await self.api.close()

    async def enable_rotation(self):
        await self.api.request('PUT', f'stations/{self.sid}/pricing', {'rotation': ROTATION})
        return (await self.api.request('GET', f'stations/{self.sid}'))['overstay']

    def start_body(self, **extra):
        return {'presence_code': '#F12345', 'public_code': self.point['public_code'], 'max_duration_minutes': 20,
                **extra}

    async def test_station_overstay_block_matches_the_api_public_terms(self):
        disabled = (await self.api.request('GET', f'stations/{self.sid}'))['overstay']
        self.assertEqual(disabled, overstay_rules.public(None))
        shown = await self.enable_rotation()
        self.assertEqual(shown, overstay_rules.public(overstay_rules.terms_from_rotation(ROTATION)))
        self.assertEqual((shown['grace_minutes'], shown['interval_minutes'], shown['max_amount']), (10, 1, '5.00'))
        rules = (await self.api.request('GET', f'stations/{self.sid}/pricing'))['rules']['rotation']
        self.assertEqual((rules['start_after_min'], rules['interval_min']), (10, 1))  # regra continua com os nomes da API

    async def test_start_checks_the_terms_version_and_the_session_carries_the_overstay_block(self):
        shown = await self.enable_rotation()
        with self.assertRaises(ApiError) as error:
            await self.api.request('POST', 'charging-sessions', self.start_body(overstay_terms_version='ovs-old'),
                                   key='s-old')
        self.assertEqual((error.exception.status, error.exception.code), (409, 'overstay_terms_changed'))
        session = await self.api.request('POST', 'charging-sessions',
                                         self.start_body(overstay_terms_version=shown['version']), key='s-ok')
        block = session['overstay']
        self.assertEqual(set(block), {'status', 'fee_applies', 'started_at', 'ended_at', 'end_reason',
                                      'billable_seconds', 'billable_minutes', 'grace_remaining_seconds', 'fee_due',
                                      'max_fee', 'as_of', 'terms'})
        self.assertEqual((block['status'], block['fee_applies'], block['max_fee']), ('none', True, '5.00'))
        self.assertEqual(block['terms']['version'], shown['version'])
        self.assertNotIn('overstay_terms', session)
        self.assertFalse(session['settlement_ready'])
        for key in ('applied_power_kw', 'power_state', 'power_reason', 'target_power_kw', 'power_reason_code'):
            self.assertIn(key, session)
        self.assertIsNone(await self.api.request('GET', 'overstays/current'))
        live = (await self.api.request('GET', 'owner/live', params={'station_id': self.sid}))['items']
        self.assertTrue(all('occupancy' in item and item['occupancy'] is None for item in live))
        running = next(item['session'] for item in live if item['session'])
        for key in ('applied_power_kw', 'power_state', 'power_reason', 'soc_source'):
            self.assertIn(key, running)

    async def test_payment_reserves_the_overstay_cap_and_locks_the_terms(self):
        shown = await self.enable_rotation()
        created = await self.api.request('POST', 'payments', {'connector_id': self.point['id'], 'mode': 'time',
                                                              'minutes': 20}, key='p1')
        self.assertEqual(created['overstay_reserve'], '5.00')
        self.assertEqual(Decimal(created['amount']), Decimal(created['energy_cap']) + Decimal('5.00'))
        self.assertEqual(created['quote']['overstay']['version'], shown['version'])
        self.assertEqual(created['quote']['overstay']['reserve_cents'], 500)
        with self.assertRaises(ApiError) as error:
            await self.api.request('POST', 'charging-sessions', self.start_body(payment_id='nope'), key='s-x')
        self.assertEqual(error.exception.code, 'payment_not_found')
        await self.api.request('POST', f"payments/{created['id']}/demo-checkout")
        self.clock[0] = 3
        session = await self.api.request('POST', 'charging-sessions', self.start_body(payment_id=created['id']),
                                         key='s-paid')
        self.assertEqual(session['overstay']['terms']['version'], shown['version'])  # termos do orçamento pago
        self.assertEqual(session['max_cost'], f"{Decimal(created['energy_cap']):.4f}")  # teto só da energia

    async def test_demo_receipt_shows_the_stripe_payment_in_the_api_shape(self):
        created = await self.api.request('POST', 'payments', {'connector_id': self.point['id'], 'mode': 'time',
                                                              'minutes': 20}, key='p2')
        await self.api.request('POST', f"payments/{created['id']}/demo-checkout")
        self.clock[0] = 3
        session = await self.api.request('POST', 'charging-sessions', self.start_body(payment_id=created['id']),
                                         key='s-paid-2')
        self.clock[0] = 4000
        await self.api.request('GET', f"charging-sessions/{session['id']}")
        settled = await self.api.request('GET', f"payments/{created['id']}")
        self.assertEqual(settled['status'], 'completed')
        data = await self.api.request('GET', f"charging-sessions/{session['id']}/receipt")
        payment = data['payment']
        self.assertEqual((payment['status'], payment['payment_status'], payment['environment']),
                         ('available', 'completed', 'mock'))
        self.assertEqual(payment['authorized_amount'], created['amount'])
        self.assertEqual(payment['net_amount'], settled['settlement']['charged'])
        self.assertEqual(data['charges']['revenue_basis'], 'paid')
        self.assertIn('Concluído', all_texts(charge_detail.payment_section(payment)))


if __name__ == '__main__':
    unittest.main()
