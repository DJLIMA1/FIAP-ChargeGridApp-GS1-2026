"""Gerenciamento do posto pelo vendedor: tela Potência (Limites: contratado, margem ESTIMADA da loja e
máximo dos carregadores; rebalanceamento ligado por padrão; cada conector), páginas removidas (Ao vivo,
Energia do estabelecimento, Pagamentos), pagamento/permanência nas sessões e o posto que exige pagamento
antecipado.

Mesmos dados da API: ``/stations/{id}/power`` (+ ``power-site``; ``building-load`` responde 410) e os blocos
``payment``/``overstay`` das sessões. A conta demo responde as mesmas rotas (``demo_site``).
"""

import asyncio
import unittest
from contextvars import Context
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import flet as ft

from chargegrid_app.api_client import ApiError
from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DEMO_PRESENCE_CODE, DemoApi
from chargegrid_app.screens import booking, history, station_admin, station_power
from chargegrid_app.services import owner_sessions
from chargegrid_app.services import site_power as sp
from chargegrid_app.ui import theme
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

def segment(screen, holder, label, within=None):
    """``on_click`` da opção ``label`` de um controle segmentado (``holder`` = ``data`` do contêiner)."""
    box = within if holder is None else by_data(screen, holder)
    return next(item.on_click for item in descendants(box)
                if isinstance(item, ft.Container) and item.on_click and texts(item) == label)


# ---------------------------------------------------------------- regras puras
class SitePowerRulesTests(unittest.TestCase):
    def test_kw_and_typed_values(self):
        self.assertEqual((sp.kw('6.000'), sp.kw('28.5'), sp.kw(None), sp.kw('', 'sem limite')),
                         ('6 kW', '28,5 kW', '—', 'sem limite'))
        self.assertEqual(sp.parse_kw(''), (None, None))
        self.assertEqual(sp.parse_kw('75,5'), (Decimal('75.5'), None))
        self.assertEqual(sp.parse_kw('0', allow_zero=True), (Decimal(0), None))
        for bad, message in (('7,55', 'até 1 casa'), ('0', 'maior que zero'), ('20000', '10.000 kW'),
                             ('abc', 'até 1 casa')):
            self.assertIn(message, sp.parse_kw(bad)[1])
        self.assertEqual(sp.limit_input('75.50'), '75,5')
        self.assertEqual(sp.limit_input(None), '')

    def test_menu_subtitle_uses_the_limits_like_the_api(self):
        station = {'rebalance_enabled': True, 'site_limit_kw': None}
        self.assertEqual(sp.menu_subtitle(station), 'Até 53 kW para os carregadores · rebalanceamento ligado')
        station.update(store_min_kw='89.6', store_peak_kw='160')
        self.assertEqual(sp.menu_subtitle(station), 'Até 50 kW para os carregadores · rebalanceamento ligado')
        station.update(site_limit_kw='200.000', max_power_kw='30', rebalance_enabled=False)
        self.assertEqual(sp.menu_subtitle(station), 'Até 30 kW para os carregadores · rebalanceamento desligado')
        self.assertTrue(sp.has_rebalance({'rebalance_enabled': False}))
        self.assertFalse(sp.has_rebalance({}))

    def test_summary_card_values_show_an_estimated_margin_not_a_live_load(self):
        view = {'available_kw': '53.0', 'site_limit_kw': '75.0', 'site_limit_default': True, 'store_min_kw': '14.0',
                'store_peak_kw': '22.0', 'store_reserve_kw': '22.0', 'store_estimate_default': True,
                'envelope_kw': '22.000', 'cars': 1, 'exceeded_kw': '0'}
        info = sp.summary(view)
        self.assertEqual((info['available'], info['limit'], info['store'], info['cars']),
                         ('53 kW', '75 kW', '−22 kW', '22 kW'))
        self.assertEqual((info['limit_detail'], info['store_detail'], info['cars_detail'], info['over']),
                         ('Padrão (75 kW ou pico × 1,3)', 'Pico estimado, reservado o tempo todo (padrão)',
                          '1 carro carregando', None))
        view.update(exceeded_kw='3', site_limit_default=False, store_estimate_default=False, cars=2)
        info = sp.summary(view)
        self.assertEqual((info['store_detail'], info['limit_detail'], info['cars_detail']),
                         ('Pico estimado, reservado o tempo todo', 'Informado por você', '2 carros carregando'))
        self.assertIn('Excesso transitório de 3 kW', info['over'])
        self.assertEqual(sp.limits_subtitle(view), 'Contratado 75 kW · loja até 22 kW · carregadores até 53 kW')
        self.assertIn('Reservamos o pico estimado o tempo todo', sp.ESTIMATE_HELP)

    def test_ruler_scale_steps_and_segments(self):
        self.assertEqual((sp.scale_max(75, 22, 60), sp.scale_max(75, 22, 0), sp.scale_max(210, 160, 44),
                          sp.scale_max(980, 750, 0), sp.scale_max(5, 1, 0)),
                         (Decimal(100), Decimal(100), Decimal(300), Decimal(1500), Decimal(25)))
        self.assertEqual((sp.step_for(100), sp.step_for(500), sp.step_for(2000)), (1, 5, 10))
        self.assertEqual((sp.snap(13.6, 1), sp.snap('22.4', 1), sp.snap(-3, 1), sp.snap(37, 5)),
                         (Decimal(14), Decimal(22), Decimal(0), Decimal(35)))
        state = sp.limits_state({'site_limit_kw': '75.0', 'site_limit_default': True, 'store_min_kw': '14.0',
                                 'store_peak_kw': '22.0', 'store_estimate_default': True, 'station_cap_kw': None,
                                 'connectors_total_kw': '82.000', 'charger_floor_kw': '1.400',
                                 'chargers_floor_total_kw': '2.800', 'power_limit_notify': False})
        self.assertEqual((state['scale'], state['step'], sp.budget(state)), (Decimal(100), 1, Decimal(53)))  # 75 × 1,25
        self.assertEqual(sp.segments(state), [('store_base', Decimal(14)), ('store_peak', Decimal(8)),
                                              ('chargers', Decimal(53)), ('above', Decimal(25))])
        self.assertEqual(sp.segments(state, used=30)[2:4], [('cars', Decimal(30)), ('chargers', Decimal(23))])
        self.assertEqual((sp.equation(state), sp.store_text(state), sp.cap_text(state)),
                         ('75 kW contratados − 22 kW de margem da loja', '14 – 22 kW', '53 kW · sem teto'))

    def test_drags_clamp_and_build_one_put_body(self):
        view = {'site_limit_kw': '75.0', 'site_limit_default': True, 'store_min_kw': '14.0', 'store_peak_kw': '22.0',
                'store_estimate_default': True, 'station_cap_kw': None, 'connectors_total_kw': '44.000',
                'charger_floor_kw': '1.400', 'chargers_floor_total_kw': '2.800', 'power_limit_notify': False}
        original = sp.limits_state(view)
        state = dict(original)
        self.assertEqual(sp.cap_text(state), '44 kW · sem teto')
        self.assertEqual(sp.body(state, original), {})
        # Pico da loja além do contratado − piso: trava e explica.
        self.assertIn('aumente o limite contratado', sp.move_store(state, 10, 90))
        self.assertEqual((state['min'], state['peak']), (Decimal(10), Decimal('73.6')))
        self.assertIsNone(sp.move_store(state, 12.2, 30.4))
        self.assertEqual((state['min'], state['peak'], sp.budget(state)), (Decimal(12), Decimal(30), Decimal(45)))
        # Contratado abaixo do pico + piso: trava.
        self.assertIn('reduza o pico', sp.move_limit(state, 20))
        self.assertEqual(state['limit'], Decimal('31.4'))
        sp.move_limit(state, 90)
        self.assertEqual(sp.budget(state), Decimal(60))
        sp.move_cap(state, 40)
        self.assertEqual((state['cap'], sp.cap_text(state), sp.budget(state)), (Decimal(40), '40 kW', Decimal(40)))
        self.assertIn('limitado pelo máximo dos carregadores', sp.equation(state))
        self.assertEqual(sp.segments(state)[-2], ('unused', Decimal(20)))
        self.assertIn('O mínimo é 2,8 kW', sp.move_cap(state, 1))
        self.assertEqual(state['cap'], Decimal('2.8'))
        sp.move_cap(state, 60)  # fim da faixa (todos no máximo): sem teto próprio
        self.assertIsNone(state['cap'])
        sp.move_cap(state, 30)
        state['notify'] = True
        self.assertEqual(sp.body(state, original), {
            'site_limit_kw': '90.0', 'store_min_kw': '12.0', 'store_peak_kw': '30.0', 'max_power_kw': '30.0',
            'power_limit_notify': True})
        # Restaurar padrão volta aos nulls (o padrão nunca é gravado como valor do dono).
        saved = dict(state, limit_default=False, store_default=False)
        sp.restore_defaults(state)
        self.assertEqual(sp.body(state, saved), {'site_limit_kw': None, 'store_min_kw': None, 'store_peak_kw': None,
                                                 'max_power_kw': None})
        # Valores digitados.
        self.assertIn('não pode passar do pico', sp.set_values(state, Decimal(75), Decimal(30), Decimal(20), None))
        self.assertIn('ao menos 1,4 kW', sp.set_values(state, Decimal(75), Decimal(10), Decimal(74), None))
        self.assertIn('pelo menos 2,8 kW', sp.set_values(state, Decimal(75), Decimal(10), Decimal(20), Decimal(1)))
        self.assertIsNone(sp.set_values(state, Decimal(2000), Decimal(100), Decimal(400), None))
        self.assertEqual((state['scale'], state['step'], sp.budget(state)), (Decimal(2500), 10, Decimal(1600)))

    def test_connector_configured_versus_effective(self):
        station = {'max_power_kw': None, 'connectors': [
            {'id': 'a', 'power_kw': '60', 'power_limit_kw': None, 'active': True},
            {'id': 'b', 'power_kw': '22', 'power_limit_kw': '11', 'active': True},
            {'id': 'c', 'power_kw': '22', 'active': False}]}
        view = {'available_kw': '50', 'points': [{'connector_id': 'a', 'session': {'applied_kw': '47.000'}}]}
        a, b, c = station['connectors']
        self.assertEqual(sp.connector_line(a, station, view), '60 kW configurados · 47 kW efetivos')
        self.assertEqual(sp.connector_line(b, station, view), '11 kW configurados · até 11 kW efetivos')
        self.assertEqual(sp.connector_line(a, station, {'available_kw': '30'}), '60 kW configurados · até 30 kW efetivos')
        self.assertEqual(sp.connector_line(c, station, view), 'Inativo: fica fora da divisão do posto')
        self.assertEqual(sp.cap_subtitle({'max_power_kw': None}), 'Sem teto · aviso desligado')
        self.assertEqual(sp.cap_subtitle({'max_power_kw': '80', 'power_limit_notify': True}), '80 kW · aviso ligado')
        self.assertEqual(sp.point_name({'connector_type': 'CCS2'}, 1), 'CCS2 · Carregador 1')


class OwnerSessionTextTests(unittest.TestCase):
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

    async def test_station_defaults_match_the_api(self):
        for key, value in (('prepay_required', False), ('kiosk_payments', False), ('kiosk_mode', False),
                           ('rebalance_enabled', True), ('site_limit_kw', None), ('store_min_kw', None),
                           ('store_peak_kw', None)):
            self.assertIs(self.station[key], value)
        self.assertNotIn('building_profile', self.station)
        # A API ainda aceita os campos (painel web); o app não tem mais interruptor para eles.
        saved = await self.api.request('PATCH', f'stations/{self.sid}', {'prepay_required': True})
        self.assertTrue(saved['prepay_required'])
        with self.assertRaises(ApiError):
            await self.api.request('PATCH', f'stations/{self.sid}', {'prepay_required': None})
        point = self.station['connectors'][0]
        with self.assertRaises(ApiError) as caught:
            await self.api.request('POST', 'charging-sessions', {'presence_code': DEMO_PRESENCE_CODE,
                                                                 'public_code': point['public_code']},
                                   key=self.api.new_key())
        self.assertEqual((caught.exception.status, caught.exception.code), (402, 'payment_required'))

    async def test_power_view_default_limit_and_estimated_store_margin(self):
        url = f'stations/{self.sid}/power-site'
        view = await self.api.request('GET', f'stations/{self.sid}/power')
        self.assertEqual((view['cars'], view['rebalance_enabled'], view['site_limit_kw'], view['site_limit_default']),
                         (0, True, '75.0', True))
        self.assertEqual((view['store_min_kw'], view['store_peak_kw'], view['store_reserve_kw'],
                          view['store_estimate_default'], view['store_estimate_label'], view['available_kw']),
                         ('14', '22', '22', True, 'ESTIMATIVA', '53.0'))
        for gone in ('building_load_mode', 'building_load_simulated', 'building_profile', 'building_profile_label'):
            self.assertNotIn(gone, view)
        self.clock[0] = 6 * 3600  # fixo: nada muda com o relógio (sem simulação)
        self.assertEqual((await self.api.request('GET', f'stations/{self.sid}/power'))['available_kw'], '53.0')
        # Tipo/porte de apps antigos: aceitos e ignorados.
        view = await self.api.request('PUT', url, {'building_profile': 'supermercado', 'building_size': 'medio'})
        self.assertEqual(view['available_kw'], '53.0')
        view = await self.api.request('PUT', url, {'store_min_kw': '56', 'store_peak_kw': '100',
                                                   'max_power_kw': '20', 'power_limit_notify': True})
        self.assertEqual((view['site_limit_kw'], view['available_kw'], view['station_cap_kw'],
                          view['power_limit_notify']), ('130.0', '20.000', '20.000', True))
        view = await self.api.request('PUT', url, {'site_limit_kw': '150.04', 'max_power_kw': None})
        self.assertEqual((view['site_limit_kw'], view['site_limit_default'], view['available_kw']),
                         ('150.0', False, '50.0'))
        for body, code in (({'site_limit_kw': 0}, 'invalid_power_limit'),
                           ({'site_limit_kw': 10001}, 'invalid_power_limit'),
                           ({'site_limit_kw': '100'}, 'invalid_store_estimate'),
                           ({'store_min_kw': '120'}, 'invalid_store_estimate'),
                           ({'max_power_kw': '0.5'}, 'invalid_power_limit'),
                           ({'rebalance_enabled': None}, 'null_not_allowed'),
                           ({'colour': 'red'}, 'validation_error')):
            with self.assertRaises(ApiError) as caught:
                await self.api.request('PUT', url, body)
            self.assertEqual(caught.exception.code, code)
        with self.assertRaises(ApiError) as caught:
            await self.api.request('PUT', f'stations/{self.sid}/building-load', {'building_load_kw': 12})
        self.assertEqual((caught.exception.status, caught.exception.code), (410, 'store_load_removed'))
        other = next(s for s in (await self.api.request('GET', 'stations'))['items'] if s['owner_id'] != 'demo-user')
        with self.assertRaises(ApiError) as caught:
            await self.api.request('GET', f"stations/{other['id']}/power")
        self.assertEqual(caught.exception.status, 404)

    async def test_rebalancing_is_on_by_default_and_counts_energy_at_the_new_power(self):
        url = f'stations/{self.sid}/power-site'
        await self.api.request('PUT', url, {'site_limit_kw': '30', 'store_min_kw': '0', 'store_peak_kw': '12'})
        ccs = next(p for p in self.station['connectors'] if p['connector_type'] == 'CCS2')
        session = await self.api.request('POST', 'charging-sessions', {
            'presence_code': DEMO_PRESENCE_CODE, 'public_code': ccs['public_code'], 'max_duration_minutes': 60},
            key=self.api.new_key())
        self.clock[0] = 1 + 60  # 1 min a 18 kW = 0,3 kWh
        view = await self.api.request('GET', f'stations/{self.sid}/power')
        point = next(p for p in view['points'] if p['connector_id'] == ccs['id'])
        self.assertEqual((point['session']['target_kw'], point['session']['applied_kw'],
                          point['session']['power_state']), ('18.0', '18.000', 'applied'))
        self.assertEqual(point['session']['reason'],
                         '18 kW porque 12 kW dos 30 kW contratados ficam reservados para a loja (estimativa) '
                         'e só o seu carro está carregando.')
        self.assertEqual((view['envelope_kw'], view['exceeded_kw']), ('18.000', '0'))
        current = await self.api.request('GET', f"charging-sessions/{session['id']}")
        self.assertEqual(Decimal(current['energy_wh']), Decimal('300.000'))
        await self.api.request('PUT', url, {'store_peak_kw': '20'})  # o dono aumenta a margem estimada
        self.clock[0] = 1 + 60 + 120  # +2 min a 10 kW = 0,333 kWh
        current = await self.api.request('GET', f"charging-sessions/{session['id']}")
        self.assertEqual((current['applied_power_kw'], current['power_state']), ('10.000', 'applied'))
        self.assertEqual(Decimal(current['energy_wh']).quantize(Decimal(1)), Decimal(633))
        self.assertIn('20 kW dos 30 kW contratados ficam reservados para a loja', current['power_reason'])
        # Margem quase no limite (28,6 de 30): o carro em recarga fica no piso e o próximo é recusado.
        await self.api.request('PUT', url, {'store_peak_kw': '28.6'})
        self.clock[0] += 5
        current = await self.api.request('GET', f"charging-sessions/{session['id']}")
        self.assertEqual(current['applied_power_kw'], '1.400')
        view = await self.api.request('GET', f'stations/{self.sid}/power')
        self.assertEqual((view['available_kw'], view['store_reserve_kw']), ('1.4', '28.6'))

    async def test_demo_traffic_shares_the_default_limit_occupancy_and_paid_history(self):
        await self.api.request('PUT', f'stations/{self.sid}/pricing', ROTATION_ON)
        view = await self.api.request('POST', f'stations/{self.sid}/demo-traffic', {})
        self.assertEqual((view['site_limit_kw'], view['rebalance_enabled'], view['cars'], view['store_reserve_kw']),
                         ('75.0', True, 1, '22'))
        load = Decimal(view['store_reserve_kw'])
        self.assertLessEqual(load + Decimal(view['envelope_kw']), Decimal(75))
        live = await self.api.request('GET', 'owner/live', params={'station_id': self.sid})
        parked = [i for i in live['items'] if i['occupancy']]
        self.assertEqual(len(parked), 1)
        occupancy = parked[0]['occupancy']
        self.assertEqual(parked[0]['availability_status'], 'occupied')
        self.assertEqual((occupancy['status'], occupancy['driver_label']), ('billing', 'Marina · Volvo EX30'))
        self.assertEqual(occupancy['fee_due'], '2.00')  # 4 min na vaga, 2 de tolerância, R$ 1,00/min
        charging = [i for i in live['items'] if i['session']]
        self.assertEqual(Decimal(charging[0]['session']['applied_power_kw']), min(Decimal(60), Decimal(75) - load))
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
        self.assertIsNone(await self.api.request('GET', 'payments/current'))
        self.clock[0] = 30 * 60
        live = await self.api.request('GET', 'owner/live', params={'station_id': self.sid})
        self.assertFalse(any(i['occupancy'] for i in live['items']))
        sessions = (await self.api.request('GET', 'operator/charging-sessions', params={'limit': 20}))['items']
        settled = [s for s in sessions if s['payment'] and s['overstay']['status'] == 'closed']
        self.assertEqual(len(settled), 2)
        self.assertTrue(all(s['payment']['status'] == 'completed' for s in settled))


# ---------------------------------------------------------------- menu do posto
REMOVED = ('Ao vivo', 'Energia do estabelecimento', 'Pagamentos', 'Potência por conector', 'QR do painel',
           'Antecipado')


class StationMenuTests(unittest.IsolatedAsyncioTestCase):
    async def test_menu_has_power_and_no_removed_pages(self):
        app = await demo_app()
        station = await owned(app)
        screen = await station_admin.build(app, station_id=station['id'])
        copy = texts(screen)
        self.assertIn('Potência', copy)
        self.assertIn('Até 53 kW para os carregadores · rebalanceamento ligado', copy)
        for removed in REMOVED:
            self.assertNotIn(removed, copy)
        routes = []
        for label in ('Dados da estação', 'Carregadores', 'Até 53 kW', 'Tarifa base'):
            await press(screen, label)(None)
            routes.append((app.go.await_args.args[0], app.go.await_args.kwargs.get('page')))
        self.assertEqual(routes, [('station_admin', 'data'), ('station_admin', 'connectors'),
                                  ('station_admin', 'power'), ('tariffs', None)])
        # Rotas antigas caem no menu do posto (sem tela própria).
        for page in ('live', 'energy', 'payments'):
            old = texts(await station_admin.build(app, station_id=station['id'], page=page))
            self.assertIn('Estação CG-001', old)
            self.assertFalse(any(removed in old for removed in REMOVED))
        await app.api.close()

    async def test_old_api_keeps_the_previous_power_subtitle(self):
        app = PollApp()
        app.back = lambda event=None: None
        station = {'id': 's1', 'name': 'Posto', 'address': 'Rua A, 1, Centro, São Paulo - SP', 'max_power_kw': None,
                   'connectors': [{'id': 'p', 'connector_type': 'CCS2', 'power_kw': '60', 'active': True}]}

        async def request(method, path, body=None, **kwargs):
            return station if path == 'stations/s1' else {'items': [station], 'total': 1}
        app.api.request.side_effect = request
        copy = texts(await station_admin.build(app, station_id='s1'))
        self.assertIn('CCS2: 60 kW', copy)
        self.assertIn('Nome, endereço e status', copy)
        for removed in REMOVED:
            self.assertNotIn(removed, copy)


# ---------------------------------------------------------------- tela Potência
class PowerPageTests(unittest.IsolatedAsyncioTestCase):
    async def _screen(self, **params):
        app = await demo_app()
        station = await owned(app)
        screen = await station_admin.build(app, station_id=station['id'], page='power', **params)
        return app, station, screen

    async def test_overview_shows_limits_estimated_store_margin_and_connectors(self):
        app, station, screen = await self._screen()
        copy = texts(screen)
        for expected in ('Potência', 'Disponível para os carregadores', '53 kW', 'Limite contratado', '75 kW (padrão)',
                         'Margem da loja', 'ESTIMATIVA', '−22 kW', 'Pico estimado, reservado o tempo todo (padrão)',
                         'Carros agora', 'Rebalanceamento', sp.REBALANCE_HELP, 'Por carregador',
                         'CCS2 · Carregador 1', '60 kW configurados', 'Ajustes', 'Limites',
                         'Contratado 75 kW · loja até 22 kW · carregadores até 53 kW', 'Loja (estimativa)',
                         'Simular carros no posto (demo)'):
            self.assertIn(expected, copy)
        for gone in ('Loja agora', 'SIMULADO', 'Teto dos carregadores', 'Valor do simulador', 'Últimas decisões'):
            self.assertNotIn(gone, copy)
        self.assertIsNotNone(by_data(screen, 'limits-bar'))
        self.assertIsNotNone(by_data(screen, 'store-margin'))
        self.assertEqual(app.poll_interval, sp.POLL_SECONDS)
        await app.poll()  # atualização sem erro
        selected = [texts(item) for item in descendants(by_data(screen, 'rebalance'))
                    if isinstance(item, ft.Container) and item.on_click and item.bgcolor]
        self.assertEqual(selected, ['Ligado'])  # ligado por padrão
        routes = []
        for data in ('power-limits', f"power-connector:{station['connectors'][0]['id']}"):
            await by_data(screen, data).on_click(None)
            routes.append(app.go.await_args.kwargs)
        self.assertEqual([route.get('section') for route in routes], ['limits', 'connector'])
        self.assertEqual(routes[1]['connector_id'], station['connectors'][0]['id'])
        # Rotas antigas viram Limites.
        for section in ('site', 'cap'):
            old = await station_admin.build(app, station_id=station['id'], page='power', section=section)
            self.assertIsNotNone(by_data(old, 'limits-card'))
        await app.api.close()

    async def test_rebalance_toggle_waits_for_the_server(self):
        app, station, screen = await self._screen()
        await segment(screen, 'rebalance', 'Desligado')(None)
        self.assertEqual(app.notices[-1], 'Rebalanceamento desligado')
        self.assertFalse((await app.api.request('GET', f"stations/{station['id']}/power"))['rebalance_enabled'])
        original = app.api.request

        async def failing(method, path, body=None, **kwargs):
            if method == 'PUT':
                raise ApiError('Sem conexão.', 503, 'network')
            return await original(method, path, body, **kwargs)
        app.api.request = failing
        await segment(screen, 'rebalance', 'Ligado')(None)
        self.assertIn('Rebalanceamento não alterado', app.notices[-1])
        selected = [texts(item) for item in descendants(by_data(screen, 'rebalance'))
                    if isinstance(item, ft.Container) and item.on_click and item.bgcolor]
        self.assertEqual(selected, ['Desligado'])
        app.api.request = original
        await app.api.close()

    async def test_power_and_site_redraws_keep_session_theme_in_fresh_event_tasks(self):
        for dark, mode, palette in ((False, ft.ThemeMode.LIGHT, theme.LIGHT),
                                    (True, ft.ThemeMode.DARK, theme.DARK)):
            theme.set_dark(dark)
            app, station, screen = await self._screen()
            try:
                with patch.object(ft, 'context', SimpleNamespace(page=SimpleNamespace(theme_mode=mode))):
                    await asyncio.create_task(segment(screen, 'rebalance', 'Desligado')(None), context=Context())
                    self.assertEqual(by_data(screen, 'power-card').bgcolor, palette['CARD'])
                    selected = next(c for c in descendants(by_data(screen, 'rebalance'))
                                    if isinstance(c, ft.Container) and c.on_click and c.bgcolor)
                    self.assertEqual((selected.bgcolor, selected.content.color),
                                     (palette['BTN_PRIMARY'], palette['BTN_PRIMARY_FG']))
                    await asyncio.create_task(app.poll(), context=Context())
                    self.assertEqual(by_data(screen, 'power-card').bgcolor, palette['CARD'])
                    limits = await station_admin.build(app, station_id=station['id'], page='power', section='limits')
                    self.assertEqual(by_data(limits, 'limits-card').bgcolor, palette['CARD'])
                    limit = by_data(limits, 'limit-slider')
                    limit.value = 90.0
                    await asyncio.create_task(limit.on_change(SimpleNamespace(control=limit)), context=Context())
                    self.assertEqual(by_data(limits, 'limits-budget').value, '68 kW')
                    self.assertEqual(by_data(limits, 'bar-chargers').bgcolor, palette['GREEN'])
                    self.assertEqual(by_data(limits, 'bar-above').bgcolor, palette['SEGMENT_OFF'])
                    self.assertEqual((limit.active_color, by_data(limits, 'store-range').active_color),
                                     (palette['BTN_PRIMARY'], palette['AMBER']))
            finally:
                await app.api.close()
        theme.set_dark(True)

    async def test_limits_page_drags_and_saves_everything_in_one_put(self):
        app, station, screen = await self._screen(section='limits')
        sid = station['id']
        copy = texts(screen)
        for expected in ('Limites', 'Para os carregadores', '53 kW', '75 kW contratados − 22 kW de margem da loja',
                         'Loja', 'ESTIMATIVA', '14 – 22 kW', 'Reservamos o pico estimado o tempo todo',
                         'Limite contratado', '75 kW (padrão)', 'Máximo dos carregadores', 'Contratado 75 kW',
                         'Avisar quando os limites reduzirem uma recarga', 'Restaurar padrão', 'Salvar limites'):
            self.assertIn(expected, copy)
        for gone in ('Tipo de estabelecimento', 'Porte', 'SIMULADO', 'Loja agora'):
            self.assertNotIn(gone, copy)
        store, limit, cap = (by_data(screen, key) for key in ('store-range', 'limit-slider', 'cap-slider'))
        self.assertIsInstance(store, ft.RangeSlider)
        self.assertEqual((store.start_value, store.end_value, store.max, limit.value, limit.max),
                         (14.0, 22.0, limit.max, 75.0, store.max))
        # Mínimo e pico da loja.
        store.start_value, store.end_value = 10.2, 30.0
        await store.on_change(SimpleNamespace(control=store))
        self.assertEqual((by_data(screen, 'store-value').value, by_data(screen, 'limits-budget').value),
                         ('10 – 30 kW', '45 kW'))
        # Pico acima do contratado − 1,4: o controle volta e explica.
        store.end_value = 80.0
        await store.on_change(SimpleNamespace(control=store))
        self.assertEqual(store.end_value, 73.6)
        self.assertIn('aumente o limite contratado', by_data(screen, 'limits-hint').value)
        store.start_value, store.end_value = 10.0, 30.0
        await store.on_change(SimpleNamespace(control=store))
        self.assertFalse(by_data(screen, 'limits-hint').visible)
        limit.value = 100.0
        await limit.on_change(SimpleNamespace(control=limit))
        self.assertEqual((by_data(screen, 'limit-value').value, by_data(screen, 'limits-budget').value),
                         ('100 kW', '70 kW'))
        # A faixa dos carregadores fica embaixo da parte verde (pico → contratado).
        self.assertEqual(cap.max, 70.0)
        spacer, lane = by_data(screen, 'cap-lane').content.controls[:2]
        self.assertEqual((spacer.expand, lane.expand), (300, 700))
        cap.value = 40.0
        await cap.on_change(SimpleNamespace(control=cap))
        self.assertEqual((by_data(screen, 'cap-value').value, by_data(screen, 'limits-budget').value),
                         ('40 kW', '40 kW'))
        await segment(screen, None, 'Ligado', within=screen)(None)
        await press(screen, 'Salvar limites')(None)
        self.assertEqual(app.notices[-1], 'Limites salvos.')
        self.assertEqual(app.go.await_args.kwargs, {'station_id': sid, 'page': 'power'})
        view = await app.api.request('GET', f'stations/{sid}/power')
        self.assertEqual((view['site_limit_kw'], view['store_min_kw'], view['store_peak_kw'], view['station_cap_kw'],
                          view['power_limit_notify'], view['available_kw']),
                         ('100.0', '10.0', '30.0', '40.000', True, '40.000'))
        # Digitar valores e restaurar padrão.
        screen = await station_admin.build(app, station_id=sid, page='power', section='limits')
        self.assertEqual(by_data(screen, 'cap-value').value, '40 kW')
        shown = []
        app.page.show_dialog = shown.append
        app.page.pop_dialog = lambda: None
        await by_data(screen, 'type-values').on_click(None)
        dialog = shown[-1]
        fields = {item.data: item for item in descendants(dialog.content) if isinstance(item, ft.TextField)}
        fields['type-peak'].value = '2000'
        dialog.actions[1].on_click(None)
        self.assertIn('ao menos 1,4 kW', texts(dialog.content))
        fields['type-limit'].value, fields['type-peak'].value, fields['type-cap'].value = '2000', '400', ''
        dialog.actions[1].on_click(None)
        self.assertEqual((by_data(screen, 'limits-budget').value, by_data(screen, 'limit-slider').max),
                         ('1600 kW', 2500.0))
        self.assertEqual(by_data(screen, 'cap-value').value, '104 kW · sem teto')  # sem teto próprio: todos no máximo
        await press(screen, 'Restaurar padrão')(None)
        self.assertEqual(by_data(screen, 'limits-budget').value, '53 kW')
        await press(screen, 'Salvar limites')(None)
        view = await app.api.request('GET', f'stations/{sid}/power')
        self.assertEqual((view['site_limit_default'], view['store_estimate_default'], view['station_cap_kw'],
                          view['available_kw']), (True, True, None, '53.0'))
        await app.api.close()

    async def test_cap_page_saves_cap_and_notify_on_an_old_api(self):
        app, station, _ = await self._screen()
        old = {**station, 'rebalance_enabled': None}  # API sem Limites: a tela antiga do teto continua
        screen = await station_power.build(app, old, section='cap')
        slider = next(c for c in descendants(screen) if isinstance(c, ft.Slider))
        self.assertEqual(slider.data, 'station_power')
        self.assertIn('Sem teto: cada carregador usa a própria potência.', texts(screen))
        slider.value = 80.0
        await slider.on_change(SimpleNamespace(control=slider))
        self.assertIn('Dividido entre os carregadores ativos.', texts(screen))
        await segment(screen, None, 'Ligado', within=screen)(None)
        await press(screen, 'Salvar teto')(None)
        saved = await app.api.request('GET', f"stations/{station['id']}")
        self.assertEqual((float(saved['max_power_kw']), saved['power_limit_notify']), (80.0, True))
        self.assertEqual(app.notices[-1], 'Teto dos carregadores salvo.')
        await app.api.close()

    async def test_limits_save_error_stays_on_the_page(self):
        app, station, screen = await self._screen(section='limits')
        original = app.api.request

        async def failing(method, path, body=None, **kwargs):
            if method == 'PUT':
                raise ApiError('O pico estimado da loja deixa 0 kW.', 422, 'invalid_store_estimate')
            return await original(method, path, body, **kwargs)
        app.api.request = failing
        limit = by_data(screen, 'limit-slider')
        limit.value = 80.0
        await limit.on_change(SimpleNamespace(control=limit))
        await press(screen, 'Salvar limites')(None)
        self.assertIn('deixa 0 kW', texts(screen))
        app.api.request = original
        await app.api.close()

    async def test_connector_page_saves_power_and_shows_effective(self):
        app = await demo_app()
        station = await owned(app)
        point = station['connectors'][0]
        screen = await station_admin.build(app, station_id=station['id'], page='power', section='connector',
                                           connector_id=point['id'])
        copy = texts(screen)
        self.assertIn('CCS2 · Carregador 1', copy)
        self.assertIn('Máximo do carregador: 60 kW', copy)
        self.assertIn('60 kW configurados · até', by_data(screen, 'connector-effective').value)
        slider = next(c for c in descendants(screen) if isinstance(c, ft.Slider))
        slider.value = 40.0
        await slider.on_change(SimpleNamespace(control=slider))
        await press(screen, 'Salvar potência')(None)
        saved = await app.api.request('GET', f"stations/{station['id']}")
        self.assertEqual(float(saved['connectors'][0]['power_limit_kw']), 40.0)
        self.assertEqual(float(saved['connectors'][0]['power_kw']), 60.0)  # nominal intocada
        self.assertEqual(app.notices[-1], 'Potência do carregador salva.')
        screen = await station_admin.build(app, station_id=station['id'], page='power', section='connector',
                                           connector_id=point['id'])
        await press(screen, 'Usar o máximo')(None)
        await press(screen, 'Salvar potência')(None)
        self.assertIsNone((await app.api.request('GET', f"stations/{station['id']}"))['connectors'][0]['power_limit_kw'])
        await app.api.close()

    async def test_old_api_without_power_route(self):
        app = PollApp()
        app.back = lambda event=None: None
        station = {'id': 's1', 'name': 'Posto', 'address': 'Rua A', 'rebalance_enabled': True, 'max_power_kw': None,
                   'connectors': [{'id': 'p', 'connector_type': 'CCS2', 'power_kw': '60', 'active': True}]}

        async def request(method, path, body=None, **kwargs):
            if path == 'stations/s1/power':
                raise ApiError('Não encontrado', 404, 'not_found')
            return station if path == 'stations/s1' else {'items': [station], 'total': 1}
        app.api.request.side_effect = request
        screen = await station_power.build(app, station)
        copy = texts(screen)
        self.assertNotIn('Disponível para os carregadores', copy)
        self.assertIn('CCS2 · Carregador 1', copy)
        self.assertIn('Teto dos carregadores', copy)

    def test_navigation_back_from_a_power_subpage(self):
        from chargegrid_app.navigation import parent_route
        self.assertEqual(parent_route('station_admin', {'station_id': 's', 'page': 'power', 'section': 'limits'}),
                         ('station_admin', {'station_id': 's', 'page': 'power'}))
        self.assertEqual(parent_route('station_admin', {'station_id': 's', 'page': 'power'}),
                         ('station_admin', {'station_id': 's'}))


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
