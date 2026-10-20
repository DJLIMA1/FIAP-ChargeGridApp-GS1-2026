"""Lacunas do vendedor fechadas no app: Ao vivo, Energia do estabelecimento, Pagamentos (teste),
pagamento/permanência nas sessões e o posto que exige pagamento antecipado no fluxo do motorista.

Mesmos dados do painel web (``apps/owner-web``): ``/owner/live`` (potência aplicada, motivo e ``occupancy``),
``/stations/{id}/power`` (+ ``power-site`` e ``building-load``), ``prepay_required``/``kiosk_payments`` e os
blocos ``payment``/``overstay`` das sessões. A conta demo responde as mesmas rotas (``demo_site``).
"""

import asyncio
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import flet as ft

from chargegrid_app.api_client import ApiError
from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DEMO_PRESENCE_CODE, DemoApi
from chargegrid_app.screens import booking, history, station_admin, station_ops
from chargegrid_app.services import owner_sessions
from chargegrid_app.services import site_power as sp
from test_behavior import HandlerApp, descendants


def texts(control):
    return ' '.join(str(item.value) for item in descendants(control) if isinstance(item, ft.Text))


def by_data(control, data):
    return next((item for item in descendants(control) if getattr(item, 'data', None) == data), None)


def press(screen, label):
    best = None
    for item in descendants(screen):
        if getattr(item, 'on_click', None) and isinstance(item, ft.Container) and label in texts(item):
            best = item
    return best.on_click


class PollApp(HandlerApp):
    def set_poll(self, callback, interval):
        self.poll, self.poll_interval = callback, interval


async def demo_app(clock=None):
    app = PollApp()
    app.back = lambda event=None: None
    app.api = DemoApi(clock=clock) if clock else DemoApi()
    await app.api.login(DEMO_EMAIL, DEMO_PASSWORD)
    app.profile = await app.api.request('GET', 'me')
    app.api.is_demo = True
    return app


async def owned(app):
    return (await app.api.request('GET', 'operator/stations'))['items'][0]


ROTATION_ON = {'rotation': {'enabled': True, 'start_after_min': 2, 'interval_min': 1, 'amount': '1.00',
                            'max_amount': '30.00'}}


# ---------------------------------------------------------------- regras puras
class SitePowerRulesTests(unittest.IsolatedAsyncioTestCase):
    def test_kw_usage_and_availability_text(self):
        self.assertEqual((sp.kw('6.000'), sp.kw('28.5'), sp.kw(None), sp.kw('', 'sem limite')),
                         ('6 kW', '28,5 kW', '—', 'sem limite'))
        view = {'site_limit_kw': '30.0', 'building_load_kw': '12.0', 'available_kw': '18.0',
                'envelope_kw': '9.000', 'exceeded_kw': '0', 'station_cap_kw': None}
        info = sp.usage(view)
        self.assertEqual((info['used'], info['available'], info['fraction'], info['over']),
                         (Decimal('9.000'), Decimal('18.0'), 0.5, False))
        self.assertEqual(sp.availability_text(view), '30 kW contratados − 12 kW da loja = 18 kW para recarga')
        self.assertEqual(sp.availability_text({'site_limit_kw': None, 'station_cap_kw': '80'}),
                         'Sem limite contratado: vale o teto do posto (80 kW).')
        self.assertEqual(sp.load_max(view), 30)
        self.assertEqual(sp.load_max({'site_limit_kw': None, 'building_load_kw': None}), 100)
        self.assertEqual(sp.load_max({'site_limit_kw': '4', 'building_load_kw': None}), 10)

    def test_over_text_depends_on_rebalancing(self):
        view = {'available_kw': '18', 'envelope_kw': '60', 'exceeded_kw': '42', 'rebalance_enabled': True}
        self.assertIn('Excesso transitório de 42 kW', sp.over_text(view, sp.usage(view)))
        view['rebalance_enabled'] = False
        self.assertIn('ligue o rebalanceamento', sp.over_text(view, sp.usage(view)))
        view.update(envelope_kw='10', exceeded_kw='0')
        self.assertIsNone(sp.over_text(view, sp.usage(view)))

    def test_site_limit_validation_matches_web(self):
        self.assertEqual(sp.parse_site_limit(''), (None, None))
        self.assertEqual(sp.parse_site_limit('75,5'), ('75.5', None))
        self.assertEqual(sp.parse_site_limit('30'), ('30.0', None))
        for bad, message in (('7,55', 'até 1 casa'), ('0', 'maior que zero'), ('20000', '10.000 kW'),
                             ('abc', 'até 1 casa')):
            self.assertIn(message, sp.parse_site_limit(bad)[1])
        self.assertEqual(sp.limit_input('75.50'), '75,5')
        self.assertEqual(sp.limit_input(None), '')

    def test_state_labels_and_decision_detail(self):
        self.assertEqual(sp.state_label(None), ('Livre', 'SLATE'))
        self.assertEqual(sp.state_label({'power_state': None}), ('Em recarga', 'BLUE'))
        self.assertEqual(sp.state_label({'power_state': 'paused'}), ('Pausada', 'RED'))
        self.assertEqual(sp.point_detail({'power_kw': '22', 'adjustable': False, 'online': False}),
                         '22 kW nominal · carga fixa · offline')
        self.assertEqual(sp.decision_detail({'trigger': 'building_load_changed', 'available_kw': '18',
                                             'exceeded_kw': '3'}),
                         'Consumo da loja · 18 kW disponíveis · excesso 3 kW')

    async def test_debouncer_sends_only_the_last_value_and_flushes(self):
        sent = []

        async def send(value):
            sent.append(value)
        debounce = sp.Debouncer(send, wait=0.02)
        for value in (1, 2, 3):
            debounce(value)
        self.assertTrue(debounce.pending)
        await asyncio.sleep(0.06)
        self.assertEqual(sent, [3])
        self.assertFalse(debounce.pending)
        debounce(7)
        await debounce.flush()
        self.assertEqual(sent, [3, 7])
        debounce(9)
        debounce.cancel()
        await asyncio.sleep(0.04)
        self.assertEqual(sent, [3, 7])


class OwnerSessionTextTests(unittest.TestCase):
    def test_occupancy_phases(self):
        self.assertEqual(owner_sessions.countdown(277), '04:37')
        self.assertEqual(owner_sessions.countdown(3725), '1:02:05')
        self.assertEqual(owner_sessions.occupancy_text({'status': 'grace', 'grace_remaining_seconds': 277}),
                         'Tolerância: restam 04:37')
        self.assertEqual(owner_sessions.occupancy_text({'status': 'billing', 'fee_due': '6.00', 'max_fee': '30.00'}),
                         'Taxa acumulada R$ 6,00 de R$ 30,00')
        self.assertEqual(owner_sessions.occupancy_text({'status': 'capped', 'fee_due': '30.00'}),
                         'Taxa no máximo: R$ 30,00')
        self.assertEqual(owner_sessions.occupancy_text({'status': 'no_fee'}),
                         'Recarga concluída, sem taxa de permanência')
        self.assertEqual(owner_sessions.occupancy_label({'status': 'grace'}), ('Em tolerância', 'AMBER'))
        self.assertIsNone(owner_sessions.occupancy_text(None))

    def test_overstay_and_payment_cells(self):
        self.assertIsNone(owner_sessions.overstay_summary({'overstay': {'status': 'none'}}))
        self.assertIsNone(owner_sessions.overstay_summary({}))  # API antiga: sem o bloco
        closed = {'status': 'closed', 'billable_seconds': 840, 'fee_due': '4.00', 'fee_applies': True}
        self.assertEqual(owner_sessions.overstay_summary({'overstay': closed}), '14 min na vaga · taxa R$ 4,00')
        no_fee = {'status': 'no_fee', 'billable_seconds': 300, 'fee_due': '0.00', 'fee_applies': False}
        self.assertEqual(owner_sessions.overstay_summary({'overstay': no_fee}),
                         '5 min na vaga · sem taxa · na vaga · sem taxa')
        self.assertEqual(owner_sessions.overstay_summary({'overstay_fee': '6.00', 'overstay_minutes': 6}),
                         'R$ 6,00 · 6 min cobrados')
        self.assertIsNone(owner_sessions.overstay_summary({'overstay_fee': '0.00', 'overstay_minutes': 0}))
        self.assertIsNone(owner_sessions.payment_summary(None))
        done = {'status': 'completed', 'status_label': 'Cobrado R$ 21,83 (teste) · Devolvido R$ 18,17',
                'environment': 'test', 'settlement': {'status': 'done', 'charged': '21.83', 'captured': '21.83',
                                                      'returned': '18.17', 'return_kind': 'released',
                                                      'overstay_amount': '0.00'}}
        self.assertEqual(owner_sessions.payment_summary(done),
                         ('Cobrado R$ 21,83 (teste) · Devolvido R$ 18,17', 'Capturado R$ 21,83 · liberado R$ 18,17'))
        refunded = {'status': 'completed', 'status_label': 'Cobrado', 'environment': 'test',
                    'settlement': {'status': 'done', 'captured': '10.00', 'returned': '5.00',
                                   'return_kind': 'refunded', 'overstay_amount': '2.00'}}
        self.assertEqual(owner_sessions.payment_summary(refunded),
                         ('Cobrado (teste)', 'Capturado R$ 10,00 · devolvido R$ 5,00 · inclui R$ 2,00 de permanência'))
        self.assertEqual(owner_sessions.payment_summary({'status': 'in_use', 'status_label': 'Pago (teste) · em uso',
                                                         'amount': '40.00', 'settlement': None}),
                         ('Pago (teste) · em uso', 'Teto autorizado R$ 40,00'))


# ---------------------------------------------------------------- demo (mesmas rotas da API)
class DemoSiteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = [0.0]
        self.api = DemoApi(clock=lambda: self.clock[0])
        await self.api.login(DEMO_EMAIL, DEMO_PASSWORD)
        self.station = (await self.api.request('GET', 'operator/stations'))['items'][0]
        self.sid = self.station['id']

    async def test_station_exposes_api_columns_and_flags_patch(self):
        for key, value in (('prepay_required', False), ('kiosk_payments', False), ('rebalance_enabled', False),
                           ('site_limit_kw', None), ('building_load_kw', None)):
            self.assertIs(self.station[key], value)
        saved = await self.api.request('PATCH', f'stations/{self.sid}', {'prepay_required': True,
                                                                          'kiosk_payments': True})
        self.assertTrue(saved['prepay_required'] and saved['kiosk_payments'])
        with self.assertRaises(ApiError):
            await self.api.request('PATCH', f'stations/{self.sid}', {'prepay_required': None})

    async def test_prepay_required_refuses_start_without_payment(self):
        await self.api.request('PATCH', f'stations/{self.sid}', {'prepay_required': True})
        point = self.station['connectors'][0]
        with self.assertRaises(ApiError) as caught:
            await self.api.request('POST', 'charging-sessions', {'presence_code': DEMO_PRESENCE_CODE,
                                                                 'public_code': point['public_code']},
                                   key=self.api.new_key())
        self.assertEqual((caught.exception.status, caught.exception.code), (402, 'payment_required'))

    async def test_power_view_site_settings_and_validation(self):
        view = await self.api.request('GET', f'stations/{self.sid}/power')
        self.assertEqual((view['cars'], view['available_kw'], view['rebalance_enabled']), (0, None, False))
        self.assertEqual([p['public_code'] for p in view['points']], sorted(p['public_code'] for p in view['points']))
        view = await self.api.request('PUT', f'stations/{self.sid}/power-site',
                                      {'site_limit_kw': '30.04', 'rebalance_enabled': True})
        self.assertEqual((view['site_limit_kw'], view['rebalance_enabled'], view['available_kw']), ('30.0', True, '30.0'))
        view = await self.api.request('PUT', f'stations/{self.sid}/building-load', {'building_load_kw': '12.5'})
        self.assertEqual((view['building_load_kw'], view['building_load_simulated'], view['available_kw']),
                         ('12.5', True, '17.5'))
        self.assertEqual(view['decisions'][0]['trigger'], 'building_load_changed')
        for body, code in (({'site_limit_kw': 0}, 'invalid_power_limit'), ({'site_limit_kw': 10001},
                                                                           'invalid_power_limit'),
                           ({'rebalance_enabled': None}, 'null_not_allowed')):
            with self.assertRaises(ApiError) as caught:
                await self.api.request('PUT', f'stations/{self.sid}/power-site', body)
            self.assertEqual(caught.exception.code, code)
        with self.assertRaises(ApiError):
            await self.api.request('PUT', f'stations/{self.sid}/building-load', {'building_load_kw': -1})
        other = next(s for s in (await self.api.request('GET', 'stations'))['items'] if s['owner_id'] != 'demo-user')
        with self.assertRaises(ApiError) as caught:
            await self.api.request('GET', f"stations/{other['id']}/power")
        self.assertEqual(caught.exception.status, 404)

    async def test_rebalancing_applies_target_and_counts_energy_at_the_new_power(self):
        ccs = next(p for p in self.station['connectors'] if p['connector_type'] == 'CCS2')
        session = await self.api.request('POST', 'charging-sessions', {
            'presence_code': DEMO_PRESENCE_CODE, 'public_code': ccs['public_code'], 'max_duration_minutes': 60},
            key=self.api.new_key())
        self.assertIsNone(session['applied_power_kw'])  # rebalanceamento desligado: campos nulos, como na API
        self.clock[0] = 1 + 60  # 1 min a 60 kW = 1 kWh
        await self.api.request('PUT', f'stations/{self.sid}/power-site',
                               {'site_limit_kw': '30', 'rebalance_enabled': True})
        view = await self.api.request('PUT', f'stations/{self.sid}/building-load', {'building_load_kw': '12'})
        point = next(p for p in view['points'] if p['connector_id'] == ccs['id'])
        self.assertEqual((point['session']['target_kw'], point['session']['applied_kw'],
                          point['session']['power_state']), ('18.0', '18.000', 'applied'))
        self.assertEqual(point['session']['reason'],
                         '18 kW porque a loja usa 12 de 30 kW e só o seu carro está carregando.')
        self.assertEqual((view['envelope_kw'], view['exceeded_kw']), ('18.000', '0'))
        self.clock[0] = 1 + 60 + 120  # +2 min a 18 kW = 0,6 kWh
        current = await self.api.request('GET', f"charging-sessions/{session['id']}")
        self.assertEqual(Decimal(current['energy_wh']), Decimal('1600.000'))
        self.assertEqual((current['applied_power_kw'], current['power_state']), ('18.000', 'applied'))
        self.assertIn('loja usa 12 de 30 kW', current['power_reason'])
        live = await self.api.owner_live({'station_id': self.sid})
        item = next(i for i in live['items'] if i['connector_id'] == ccs['id'])
        self.assertEqual(item['session']['applied_power_kw'], '18.000')
        # Loja quase no limite: sem o mínimo para mais um carro, o início é recusado (409 site_power_full).
        await self.api.request('POST', f"charging-sessions/{session['id']}/stop", key=self.api.new_key())
        self.clock[0] += 5
        await self.api.request('PUT', f'stations/{self.sid}/building-load', {'building_load_kw': '29.5'})
        other = next(p for p in self.station['connectors'] if p['id'] != ccs['id'] and p['online'])
        with self.assertRaises(ApiError) as caught:
            await self.api.request('POST', 'charging-sessions', {'presence_code': DEMO_PRESENCE_CODE,
                                                                 'public_code': other['public_code']},
                                   key=self.api.new_key())
        self.assertEqual(caught.exception.code, 'site_power_full')

    async def test_demo_traffic_occupancy_and_paid_history(self):
        await self.api.request('PUT', f'stations/{self.sid}/pricing', ROTATION_ON)
        view = await self.api.request('POST', f'stations/{self.sid}/demo-traffic', {})
        self.assertEqual((view['site_limit_kw'], view['building_load_kw'], view['rebalance_enabled'], view['cars']),
                         ('30.0', '12.0', True, 1))
        live = await self.api.owner_live({'station_id': self.sid})
        parked = [i for i in live['items'] if i['occupancy']]
        self.assertEqual(len(parked), 1)
        occupancy = parked[0]['occupancy']
        self.assertEqual(parked[0]['availability_status'], 'occupied')
        self.assertEqual((occupancy['status'], occupancy['driver_label']), ('billing', 'Marina · Volvo EX30'))
        self.assertEqual(occupancy['fee_due'], '2.00')  # 4 min na vaga, 2 de tolerância, R$ 1,00/min
        charging = [i for i in live['items'] if i['session']]
        self.assertEqual(charging[0]['session']['applied_power_kw'], '18.000')
        # Idempotente enquanto o movimento continua no posto.
        await self.api.request('POST', f'stations/{self.sid}/demo-traffic', {})
        self.assertEqual((await self.api.request('GET', f'stations/{self.sid}/power'))['cars'], 1)
        history_page = await self.api.request('GET', 'operator/charging-sessions', params={'limit': 20})
        paid = [s for s in history_page['items'] if s['payment']]
        self.assertEqual({s['payment']['status'] for s in paid}, {'in_use', 'completed'})
        done = next(s for s in paid if s['payment']['status'] == 'completed')
        self.assertEqual((done['overstay']['status'], done['overstay']['billable_seconds'], done['overstay']['fee_due']),
                         ('closed', 840, '12.00'))
        self.assertEqual(done['payment']['settlement']['overstay_amount'], '12.00')
        self.assertNotIn('_driver_label', done)
        # O motorista da demo não vê os pagamentos dos motoristas fictícios.
        self.assertIsNone(await self.api.request('GET', 'payments/current'))
        # Depois que o carro desconecta, o pagamento é acertado com a taxa e a vaga fica livre.
        self.clock[0] = 30 * 60
        live = await self.api.owner_live({'station_id': self.sid})
        self.assertFalse(any(i['occupancy'] for i in live['items']))
        sessions = (await self.api.request('GET', 'operator/charging-sessions', params={'limit': 20}))['items']
        settled = [s for s in sessions if s['payment'] and s['overstay']['status'] == 'closed']
        self.assertEqual(len(settled), 2)
        self.assertTrue(all(s['payment']['status'] == 'completed' for s in settled))


# ---------------------------------------------------------------- telas do vendedor
class StationMenuTests(unittest.IsolatedAsyncioTestCase):
    async def test_menu_routes_to_operation_pages(self):
        app = await demo_app()
        station = await owned(app)
        screen = await station_admin.build(app, station_id=station['id'])
        copy = texts(screen)
        for label in ('Ao vivo', 'Energia do estabelecimento', 'Pagamentos · teste',
                      'Sem limite contratado · rebalanceamento desligado',
                      'Antecipado desligado · QR do painel desligado'):
            self.assertIn(label, copy)
        for label, page in (('Pontos agora', 'live'), ('Sem limite contratado', 'energy'),
                            ('Antecipado desligado', 'payments')):
            await press(screen, label)(None)
            self.assertEqual(app.go.await_args.kwargs, {'station_id': station['id'], 'page': page})
        await app.api.close()

    async def test_entries_hidden_when_api_does_not_send_the_fields(self):
        app = PollApp()
        app.back = lambda event=None: None
        station = {'id': 's1', 'name': 'Posto', 'address': 'Rua A, 1, Centro, São Paulo - SP', 'connectors': []}

        async def request(method, path, body=None, **kwargs):
            return station if path == 'stations/s1' else {'items': [station], 'total': 1}
        app.api.request.side_effect = request
        copy = texts(await station_admin.build(app, station_id='s1'))
        self.assertIn('Ao vivo', copy)
        self.assertNotIn('Energia do estabelecimento', copy)
        self.assertNotIn('Pagamentos', copy)


class EnergyPageTests(unittest.IsolatedAsyncioTestCase):
    async def test_energy_page_saves_limit_toggle_load_and_polls(self):
        app = await demo_app()
        station = await owned(app)
        sid = station['id']
        screen = await station_admin.build(app, station_id=sid, page='energy')
        copy = texts(screen)
        for expected in ('Energia do estabelecimento', 'Limite contratado', 'Rebalanceamento ao vivo', 'SIMULADO',
                         'Consumo da loja', 'Em uso 0 kW de sem limite disponíveis', '0 carros carregando',
                         'Sem limite contratado: vale o teto do posto', 'Livre', 'Nenhuma decisão registrada',
                         'Simular carros no posto (demo)'):
            self.assertIn(expected, copy)
        self.assertEqual(app.poll_interval, sp.POLL_SECONDS)
        field = by_data(screen, 'site_limit')
        field.value = '7,55'
        await press(screen, 'Salvar')(None)
        self.assertIn('até 1 casa', field.error_text)
        field.value = '30'
        field.on_change(None)
        await press(screen, 'Salvar')(None)
        self.assertEqual(app.notices[-1], 'Limite contratado salvo')
        self.assertEqual((await app.api.request('GET', f'stations/{sid}/power'))['site_limit_kw'], '30.0')
        switch = by_data(screen, 'rebalance')
        switch.value = True
        await switch.on_change(SimpleNamespace(control=switch))
        self.assertEqual(app.notices[-1], 'Rebalanceamento ligado')
        self.assertIn('Ligado: ajusta os pontos', texts(screen))
        slider = by_data(screen, 'building_load')
        self.assertEqual(slider.max, 30.0)
        for value in (5.2, 9.0, 12.4):
            slider.value = value
            await slider.on_change(SimpleNamespace(control=slider))
        self.assertIn('12,5 kW', texts(screen))
        await slider.on_change_end(None)  # soltar o controle envia já (só o último valor)
        view = await app.api.request('GET', f'stations/{sid}/power')
        self.assertEqual(view['building_load_kw'], '12.5')
        self.assertEqual([d['trigger'] for d in view['decisions']][:1], ['building_load_changed'])
        await app.api.request('POST', f'stations/{sid}/demo-traffic', {})
        await app.poll()
        copy = texts(screen)
        for expected in ('30 kW contratados − 12,5 kW da loja = 17,5 kW para recarga', '1 carro carregando',
                         'Alvo 17,5 kW · Aplicada 17,5 kW', 'Aplicada',
                         '17,5 kW porque a loja usa 12,5 de 30 kW e só o seu carro está carregando.',
                         'Em uso 17,5 kW de 17,5 kW disponíveis'):
            self.assertIn(expected, copy)
        await app.api.close()

    async def test_unsupported_api_and_failed_toggle_revert(self):
        app = PollApp()
        station = {'id': 's1', 'name': 'Posto'}
        app.api.request.side_effect = ApiError('Não encontrado', 404, 'not_found')
        screen = await station_ops.energy_page(app, station)
        self.assertIn('ainda não tem o rebalanceamento ao vivo', texts(screen))
        view = {'station_id': 's1', 'rebalance_enabled': False, 'site_limit_kw': None, 'building_load_kw': None,
                'available_kw': None, 'envelope_kw': '0', 'exceeded_kw': '0', 'cars': 0, 'points': [],
                'decisions': []}

        async def request(method, path, body=None, **kwargs):
            if method == 'PUT':
                raise ApiError('Sem permissão', 403, 'forbidden')
            return view
        app.api.request.side_effect = request
        screen = await station_ops.energy_page(app, station)
        switch = by_data(screen, 'rebalance')
        switch.value = True
        await switch.on_change(SimpleNamespace(control=switch))
        self.assertFalse(switch.value)
        self.assertIn('Alteração de energia não salva', app.notices[-1])


class LivePageTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_shows_applied_power_reason_and_who_holds_the_spot(self):
        app = await demo_app()
        station = await owned(app)
        await app.api.request('PUT', f"stations/{station['id']}/pricing", ROTATION_ON)
        await app.api.request('POST', f"stations/{station['id']}/demo-traffic", {})
        screen = await station_admin.build(app, station_id=station['id'], page='live')
        self.assertEqual(app.poll_interval, station_ops.LIVE_POLL_SECONDS)
        copy = texts(screen)
        for expected in ('Ao vivo', '1 carregando', '1 na vaga após a recarga', 'Em recarga', 'Ocupado',
                         'Potência aplicada: 18 kW', '18 kW agora', '18 kW porque a loja usa 12 de 30 kW',
                         'Cobrando permanência', 'Marina · Volvo EX30', 'Taxa acumulada R$ 2,00 de R$ 30,00',
                         'Recarga terminou às', 'Offline'):
            self.assertIn(expected, copy)
        self.assertIsNotNone(by_data(screen, 'occupancy'))
        # Alertas do posto (``/owner/alerts``): o ponto offline aparece como crítico.
        self.assertTrue(by_data(screen, 'alerts').visible)
        self.assertIn('Crítico', copy)
        self.assertIn('Dispositivo offline', copy)
        await app.poll()
        await app.api.close()

    async def test_live_without_new_fields_hides_power_and_occupancy(self):
        app = PollApp()
        item = {'connector_id': 'c1', 'public_code': 'CG-AB12', 'connector_type': 'Tipo 2', 'power_kw': '22.000',
                'price_per_kwh': '1.89', 'online': True, 'has_device': True, 'availability_status': 'charging',
                'session': {'id': 's', 'status': 'charging', 'started_at': '2026-10-20T12:00:00+00:00',
                            'energy_wh': '2500', 'cost_estimate': '4.72', 'power_w': '7200', 'soc_percent': None}}

        async def request(method, path, body=None, **kwargs):
            if path == 'owner/alerts':
                raise ApiError('Não encontrado', 404, 'not_found')  # API sem alertas: a página segue
            return {'items': [item], 'generated_at': '2026-10-20T12:05:00+00:00'}
        app.api.request.side_effect = request
        screen = await station_ops.live_page(app, {'id': 's1'})
        copy = texts(screen)
        self.assertIn('2,50 kWh entregues · 7,2 kW agora · R$ 4,72', copy)
        self.assertFalse(by_data(screen, 'alerts').visible)  # sem itens de alerta: seção oculta
        self.assertNotIn('Potência aplicada', copy)
        self.assertNotIn('Tolerância', copy)


class PaymentsPageTests(unittest.IsolatedAsyncioTestCase):
    async def test_switches_patch_station_without_optimistic_update(self):
        app = await demo_app()
        station = await owned(app)
        screen = await station_admin.build(app, station_id=station['id'], page='payments')
        copy = texts(screen)
        for expected in ('Exigir pagamento antecipado (Stripe · teste)', 'Pagamento pelo QR do painel', 'TESTE',
                         'nenhum valor real é cobrado'):
            self.assertIn(expected, copy)
        prepay = by_data(screen, 'prepay_required')
        prepay.value = True
        await prepay.on_change(SimpleNamespace(control=prepay))
        self.assertEqual(app.notices[-1], 'Pagamento antecipado exigido')
        self.assertTrue((await app.api.request('GET', f"stations/{station['id']}"))['prepay_required'])
        await app.api.close()

        failing = PollApp()
        failing.api.request = AsyncMock(side_effect=ApiError('Sem conexão', 0, 'network'))
        screen = station_ops.payments_page(failing, {'id': 's1', 'kiosk_payments': False})
        self.assertIsNone(by_data(screen, 'prepay_required'))  # campo ausente: interruptor some
        kiosk = by_data(screen, 'kiosk_payments')
        kiosk.value = True
        await kiosk.on_change(SimpleNamespace(control=kiosk))
        self.assertFalse(kiosk.value)
        self.assertIn('Configuração de pagamento não salva', failing.notices[-1])


class SellerHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_seller_history_shows_payment_and_overstay(self):
        app = await demo_app()
        station = await owned(app)
        await app.api.request('PUT', f"stations/{station['id']}/pricing", ROTATION_ON)
        await app.api.request('POST', f"stations/{station['id']}/demo-traffic", {})
        screen = await history.build(app, manage=True, chart=False)
        copy = texts(screen)
        self.assertIn('Pagamento: Stripe · Pago (teste) · em uso', copy)
        self.assertIn('Pagamento: Stripe · Cobrado R$', copy)
        self.assertIn('Capturado R$', copy)
        self.assertIn('liberado R$', copy)
        self.assertIn('Permanência: 14 min na vaga · taxa R$ 12,00', copy)
        self.assertIn('Permanência: 4 min na vaga · taxa R$ 2,00 · cobrando permanência', copy)
        await app.api.close()

    def test_money_lines_empty_without_fields(self):
        self.assertEqual(history.money_lines({'status': 'completed'}), [])


class DriverPrepayTests(unittest.TestCase):
    def test_prepay_station_offers_only_stripe(self):
        self.assertEqual(booking.pay_options(True, True), ['balance', 'stripe'])
        self.assertEqual(booking.pay_options(True, True, prepay=True), ['stripe'])
        self.assertEqual(booking.pay_options(False, False, prepay=True), ['balance'])
        self.assertIn('exige pagamento antecipado pelo app', texts(booking.prepay_note(True)))
        self.assertIn('não poderá começar', texts(booking.prepay_note(False)))


if __name__ == '__main__':
    unittest.main()
