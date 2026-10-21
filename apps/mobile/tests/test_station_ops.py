"""Gerenciamento do posto pelo vendedor: tela Potência (limite contratado, rebalanceamento ligado por
padrão, consumo SIMULADO da loja e cada conector), páginas removidas (Ao vivo, Energia do
estabelecimento, Pagamentos), pagamento/permanência nas sessões e o posto que exige pagamento antecipado.

Mesmos dados da API: ``/stations/{id}/power`` (+ ``power-site`` e ``building-load``) e os blocos
``payment``/``overstay`` das sessões. A conta demo responde as mesmas rotas (``demo_site``).
"""

import unittest
from decimal import Decimal
from types import SimpleNamespace

import flet as ft

from chargegrid_app.api_client import ApiError
from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DEMO_PRESENCE_CODE, DemoApi
from chargegrid_app.screens import booking, history, station_admin, station_power
from chargegrid_app.services import owner_sessions
from chargegrid_app.services import site_power as sp
from chargegrid_core import site_load
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
    def test_kw_and_site_limit_validation(self):
        self.assertEqual((sp.kw('6.000'), sp.kw('28.5'), sp.kw(None), sp.kw('', 'sem limite')),
                         ('6 kW', '28,5 kW', '—', 'sem limite'))
        self.assertEqual(sp.parse_site_limit(''), (None, None))
        self.assertEqual(sp.parse_site_limit('75,5'), ('75.5', None))
        self.assertEqual(sp.parse_site_limit('30'), ('30.0', None))
        for bad, message in (('7,55', 'até 1 casa'), ('0', 'maior que zero'), ('20000', '10.000 kW'),
                             ('abc', 'até 1 casa')):
            self.assertIn(message, sp.parse_site_limit(bad)[1])
        self.assertEqual(sp.limit_input('75.50'), '75,5')
        self.assertEqual(sp.limit_input(None), '')

    def test_menu_subtitle_uses_the_default_limit_like_the_api(self):
        station = {'rebalance_enabled': True, 'site_limit_kw': None, 'building_profile': None}
        self.assertEqual(sp.menu_subtitle(station), 'Limite 75 kW (padrão) · rebalanceamento ligado')
        station.update(building_profile='supermercado', building_size='grande')
        self.assertEqual(sp.menu_subtitle(station), 'Limite 210 kW (padrão) · rebalanceamento ligado')
        station.update(site_limit_kw='120.000', rebalance_enabled=False)
        self.assertEqual(sp.menu_subtitle(station), 'Limite 120 kW · rebalanceamento desligado')
        self.assertTrue(sp.has_rebalance({'rebalance_enabled': False}))
        self.assertFalse(sp.has_rebalance({}))

    def test_summary_card_values(self):
        view = {'available_kw': '55.0', 'site_limit_kw': '75.0', 'site_limit_default': True,
                'building_load_kw': '20.0', 'building_load_mode': 'profile', 'envelope_kw': '22.000', 'cars': 1,
                'exceeded_kw': '0', 'building_profile_label': 'Padaria · porte médio'}
        info = sp.summary(view)
        self.assertEqual((info['available'], info['limit'], info['load'], info['cars']),
                         ('55 kW', '75 kW', '20 kW', '22 kW'))
        self.assertEqual((info['limit_detail'], info['load_detail'], info['cars_detail'], info['over']),
                         ('Padrão para o tipo de estabelecimento', 'Padaria', '1 carro carregando', None))
        view.update(building_load_mode='manual', exceeded_kw='3', site_limit_default=False, cars=2)
        info = sp.summary(view)
        self.assertEqual((info['load_detail'], info['limit_detail'], info['cars_detail']),
                         ('Valor do simulador (30 min)', 'Informado por você', '2 carros carregando'))
        self.assertIn('Excesso transitório de 3 kW', info['over'])

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
        self.assertEqual(sp.point_name({'connector_type': 'CCS2'}, 1), 'CCS2 · Conector 01')


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
                           ('rebalance_enabled', True), ('site_limit_kw', None), ('building_load_kw', None),
                           ('building_profile', None)):
            self.assertIs(self.station[key], value)
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

    async def test_power_view_default_limit_and_simulated_store_load(self):
        view = await self.api.request('GET', f'stations/{self.sid}/power')
        self.assertEqual((view['cars'], view['rebalance_enabled'], view['site_limit_kw'], view['site_limit_default']),
                         (0, True, '75.0', True))
        self.assertEqual((view['building_load_mode'], view['building_load_simulated'], view['building_profile']),
                         ('profile', True, 'conveniencia'))
        expected = site_load.simulate(self.sid, self.api._now(), site_limit_kw=Decimal(75))
        self.assertEqual(view['building_load_kw'], str(expected))
        self.assertEqual(Decimal(view['available_kw']), Decimal(75) - expected)
        # Tipo/porte: outra curva e outro limite padrão.
        view = await self.api.request('PUT', f'stations/{self.sid}/power-site',
                                      {'building_profile': 'supermercado', 'building_size': 'medio'})
        self.assertEqual((view['site_limit_kw'], view['building_profile_label']),
                         ('130.0', 'Supermercado · porte médio'))
        # Valor do simulador vale 30 min; null volta à curva.
        view = await self.api.request('PUT', f'stations/{self.sid}/building-load', {'building_load_kw': '12.5'})
        self.assertEqual((view['building_load_kw'], view['building_load_mode'], view['available_kw']),
                         ('12.5', 'manual', '117.5'))
        self.clock[0] = 31 * 60
        self.assertEqual((await self.api.request('GET', f'stations/{self.sid}/power'))['building_load_mode'], 'profile')
        await self.api.request('PUT', f'stations/{self.sid}/building-load', {'building_load_kw': '20'})
        view = await self.api.request('PUT', f'stations/{self.sid}/building-load', {'building_load_kw': None})
        self.assertEqual(view['building_load_mode'], 'profile')
        view = await self.api.request('PUT', f'stations/{self.sid}/power-site', {'site_limit_kw': '30.04'})
        self.assertEqual((view['site_limit_kw'], view['site_limit_default']), ('30.0', False))
        self.assertLessEqual(Decimal(view['building_load_kw']), Decimal('25.5'))  # até 85 % do limite
        for body, code in (({'site_limit_kw': 0}, 'invalid_power_limit'), ({'site_limit_kw': 10001},
                                                                           'invalid_power_limit'),
                           ({'rebalance_enabled': None}, 'null_not_allowed'),
                           ({'building_profile': 'fabrica'}, 'validation_error')):
            with self.assertRaises(ApiError) as caught:
                await self.api.request('PUT', f'stations/{self.sid}/power-site', body)
            self.assertEqual(caught.exception.code, code)
        with self.assertRaises(ApiError):
            await self.api.request('PUT', f'stations/{self.sid}/building-load', {'building_load_kw': -1})
        other = next(s for s in (await self.api.request('GET', 'stations'))['items'] if s['owner_id'] != 'demo-user')
        with self.assertRaises(ApiError) as caught:
            await self.api.request('GET', f"stations/{other['id']}/power")
        self.assertEqual(caught.exception.status, 404)

    async def test_rebalancing_is_on_by_default_and_counts_energy_at_the_new_power(self):
        await self.api.request('PUT', f'stations/{self.sid}/power-site', {'site_limit_kw': '30'})
        await self.api.request('PUT', f'stations/{self.sid}/building-load', {'building_load_kw': '12'})
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
                         '18 kW porque a loja usa 12 de 30 kW e só o seu carro está carregando.')
        self.assertEqual((view['envelope_kw'], view['exceeded_kw']), ('18.000', '0'))
        current = await self.api.request('GET', f"charging-sessions/{session['id']}")
        self.assertEqual(Decimal(current['energy_wh']), Decimal('300.000'))
        await self.api.request('PUT', f'stations/{self.sid}/building-load', {'building_load_kw': '20'})
        self.clock[0] = 1 + 60 + 120  # +2 min a 10 kW = 0,333 kWh
        current = await self.api.request('GET', f"charging-sessions/{session['id']}")
        self.assertEqual((current['applied_power_kw'], current['power_state']), ('10.000', 'applied'))
        self.assertEqual(Decimal(current['energy_wh']).quantize(Decimal(1)), Decimal(633))
        self.assertIn('loja usa 20 de 30 kW', current['power_reason'])
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

    async def test_demo_traffic_shares_the_default_limit_occupancy_and_paid_history(self):
        await self.api.request('PUT', f'stations/{self.sid}/pricing', ROTATION_ON)
        view = await self.api.request('POST', f'stations/{self.sid}/demo-traffic', {})
        self.assertEqual((view['site_limit_kw'], view['rebalance_enabled'], view['cars'], view['building_load_mode']),
                         ('75.0', True, 1, 'profile'))
        load = Decimal(view['building_load_kw'])
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
        self.assertIn('Limite 75 kW (padrão) · rebalanceamento ligado', copy)
        for removed in REMOVED:
            self.assertNotIn(removed, copy)
        routes = []
        for label in ('Dados da estação', 'Conectores', 'Limite 75 kW', 'Tarifa base'):
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

    async def test_overview_shows_limit_rebalance_simulated_store_and_connectors(self):
        app, station, screen = await self._screen()
        copy = texts(screen)
        for expected in ('Potência', 'Disponível para os carregadores', 'Limite contratado', '75 kW',
                         'Padrão para o tipo de estabelecimento', 'Loja agora', 'SIMULADO', 'Carros agora',
                         'Rebalanceamento', sp.REBALANCE_HELP, 'Por conector', 'CCS2 · Conector 01',
                         '60 kW configurados', 'Ajustes', 'Teto dos carregadores', 'Sem teto · aviso desligado',
                         '75 kW (padrão) · Loja de conveniência',
                         'Simular carros no posto (demo)'):
            self.assertIn(expected, copy)
        self.assertNotIn('Últimas decisões', copy)  # sem excesso de informação
        self.assertEqual(app.poll_interval, sp.POLL_SECONDS)
        await app.poll()  # atualização sem erro
        selected = [texts(item) for item in descendants(by_data(screen, 'rebalance'))
                    if isinstance(item, ft.Container) and item.on_click and item.bgcolor]
        self.assertEqual(selected, ['Ligado'])  # ligado por padrão
        routes = []
        for data in ('power-site', 'power-cap', f"power-connector:{station['connectors'][0]['id']}"):
            await by_data(screen, data).on_click(None)
            routes.append(app.go.await_args.kwargs)
        self.assertEqual([route.get('section') for route in routes], ['site', 'cap', 'connector'])
        self.assertEqual(routes[2]['connector_id'], station['connectors'][0]['id'])
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

    async def test_site_page_saves_limit_type_and_size(self):
        app, station, screen = await self._screen(section='site')
        copy = texts(screen)
        self.assertIn('Tipo de estabelecimento', copy)
        self.assertIn('Padrão: 75 kW · pico típico da loja 22 kW (SIMULADO)', copy)
        field = by_data(screen, 'site_limit')
        self.assertEqual((field.value, field.hint_text), ('', '75 (padrão)'))
        await press(screen, 'Supermercado')(None)
        await segment(screen, None, 'Grande', within=screen)(None)
        self.assertIn('Padrão: 210 kW', by_data(screen, 'site-default').value)
        field.value = '7,55'
        await press(screen, 'Salvar limite')(None)
        self.assertIn('até 1 casa', texts(screen))
        field.value = '250'
        await press(screen, 'Salvar limite')(None)
        self.assertEqual(app.notices[-1], 'Limite contratado salvo.')
        self.assertEqual(app.go.await_args.kwargs, {'station_id': station['id'], 'page': 'power'})
        view = await app.api.request('GET', f"stations/{station['id']}/power")
        self.assertEqual((view['site_limit_kw'], view['building_profile'], view['building_size']),
                         ('250.0', 'supermercado', 'grande'))
        screen = await station_admin.build(app, station_id=station['id'], page='power', section='site')
        field = by_data(screen, 'site_limit')
        self.assertEqual(field.value, '250')
        field.value = ''
        await press(screen, 'Salvar limite')(None)
        self.assertTrue((await app.api.request('GET', f"stations/{station['id']}/power"))['site_limit_default'])
        await app.api.close()

    async def test_cap_page_saves_cap_and_notify(self):
        app, station, screen = await self._screen(section='cap')
        slider = next(c for c in descendants(screen) if isinstance(c, ft.Slider))
        self.assertEqual(slider.data, 'station_power')
        self.assertIn('Sem teto: cada conector usa a própria potência.', texts(screen))
        slider.value = 80.0
        await slider.on_change(SimpleNamespace(control=slider))
        self.assertIn('Dividido entre os conectores ativos.', texts(screen))
        await segment(screen, None, 'Ligado', within=screen)(None)
        await press(screen, 'Salvar teto')(None)
        saved = await app.api.request('GET', f"stations/{station['id']}")
        self.assertEqual((float(saved['max_power_kw']), saved['power_limit_notify']), (80.0, True))
        self.assertEqual(app.notices[-1], 'Teto dos carregadores salvo.')
        screen = await station_admin.build(app, station_id=station['id'], page='power', section='cap')
        await press(screen, 'Sem teto')(None)
        await press(screen, 'Salvar teto')(None)
        self.assertIsNone((await app.api.request('GET', f"stations/{station['id']}"))['max_power_kw'])
        await app.api.close()

    async def test_connector_page_saves_power_and_shows_effective(self):
        app = await demo_app()
        station = await owned(app)
        point = station['connectors'][0]
        screen = await station_admin.build(app, station_id=station['id'], page='power', section='connector',
                                           connector_id=point['id'])
        copy = texts(screen)
        self.assertIn('CCS2 · Conector 01', copy)
        self.assertIn('Máximo do carregador: 60 kW', copy)
        self.assertIn('60 kW configurados · até', by_data(screen, 'connector-effective').value)
        slider = next(c for c in descendants(screen) if isinstance(c, ft.Slider))
        slider.value = 40.0
        await slider.on_change(SimpleNamespace(control=slider))
        await press(screen, 'Salvar potência')(None)
        saved = await app.api.request('GET', f"stations/{station['id']}")
        self.assertEqual(float(saved['connectors'][0]['power_limit_kw']), 40.0)
        self.assertEqual(float(saved['connectors'][0]['power_kw']), 60.0)  # nominal intocada
        self.assertEqual(app.notices[-1], 'Potência do conector salva.')
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
        self.assertIn('CCS2 · Conector 01', copy)
        self.assertIn('Teto dos carregadores', copy)

    def test_navigation_back_from_a_power_subpage(self):
        from chargegrid_app.navigation import parent_route
        self.assertEqual(parent_route('station_admin', {'station_id': 's', 'page': 'power', 'section': 'site'}),
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
