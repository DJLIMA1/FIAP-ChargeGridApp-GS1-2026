"""Totem 0.8.0 no app: Modo apresentação da conta, interruptor do totem do posto e "Ponto em uso no totem".

* Conta: o interruptor grava no aparelho e em ``PATCH /me {presentation_mode}`` (cache de ``me`` descartado);
  ao entrar, na conta de dono o servidor manda; motorista e API antiga continuam só no aparelho.
* Posto (vendedor): ``kiosk_mode`` (``PATCH stations``) com o método efetivo (simulado × Stripe teste) e o
  motivo de indisponível (``payments_unavailable``).
* Motorista: ``409 point_unavailable`` com ``reason: kiosk_in_use`` vira "Ponto em uso no totem".
"""

import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import flet as ft
import httpx

from chargegrid_app import api_cache
from chargegrid_app.api_client import KIOSK_IN_USE_MESSAGE, ApiClient, ApiError
from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DEMO_PRESENCE_CODE, DemoApi
from chargegrid_app.screens import history, profile, station_admin, station_ops
from chargegrid_app.services import account_mode, owner_sessions, vehicle_state
from chargegrid_app.services import booking as rules
from chargegrid_app.ui.availability import point_status
from test_behavior import descendants
from test_driver_payments import FakeApi, PollApp

OWNER = {'id': 'owner-1', 'account_type': 'vendor', 'operator_enabled': True}
DRIVER = {'id': 'driver-1', 'account_type': 'consumer', 'operator_enabled': False}


def texts(control):
    return ' '.join(str(item.value) for item in descendants(control) if isinstance(item, ft.Text))


def by_data(control, data):
    return next((item for item in descendants(control) if getattr(item, 'data', None) == data), None)


class StorageCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.env = patch.dict('os.environ', {'FLET_APP_STORAGE_DATA': self.directory.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.directory.cleanup()


def fake_app(profile, routes):
    app = PollApp()
    app.api = FakeApi(routes)
    app.profile = dict(profile)
    app.back = lambda event=None: None
    return app


async def demo_app():
    app = PollApp()
    app.back = lambda event=None: None
    app.api = DemoApi()
    await app.api.login(DEMO_EMAIL, DEMO_PASSWORD)
    app.profile = await app.api.request('GET', 'me')
    app.dark_mode = True
    app.logout = AsyncMock()
    return app


# ---------------------------------------------------------------- modo apresentação da conta
class AccountModeSyncTests(StorageCase):
    async def test_toggle_writes_device_and_account(self):
        app = fake_app({**OWNER, 'presentation_mode': False},
                       {('PATCH', 'me'): lambda body, key: {**OWNER, 'presentation_mode': body['presentation_mode']}})
        saved, synced = await account_mode.toggle(app, True)
        self.assertEqual((saved, synced), (True, True))
        self.assertTrue(vehicle_state.presentation_mode(app))
        self.assertIs(app.profile['presentation_mode'], True)
        self.assertEqual(app.api.calls[-1][:3], ('PATCH', 'me', {'presentation_mode': True}))
        self.assertEqual(account_mode.totem_caption(app), 'Totem: sem cobrança')
        await account_mode.toggle(app, False)
        self.assertEqual(account_mode.totem_caption(app), 'Totem: Stripe')

    async def test_owner_reverts_when_the_account_is_not_saved(self):
        app = fake_app({**OWNER, 'presentation_mode': False},
                       {('PATCH', 'me'): ApiError('Sem conexão', 0, 'network_error')})
        saved, synced = await account_mode.toggle(app, True)
        self.assertIs(synced, False)
        self.assertFalse(vehicle_state.presentation_mode(app))  # totem e aparelho continuam iguais

    async def test_driver_and_old_api_keep_the_device_preference(self):
        for account in (DRIVER, {**DRIVER, 'presentation_mode': False}, OWNER):  # OWNER sem o campo: API antiga
            app = fake_app(account, {('PATCH', 'me'): ApiError('Campo desconhecido', 422, 'validation_error')})
            vehicle_state.set_presentation_mode(app, False)
            saved, synced = await account_mode.toggle(app, True)
            self.assertIsNone(synced)
            self.assertTrue(vehicle_state.presentation_mode(app))

    async def test_on_sign_in_the_server_wins_for_owner_accounts(self):
        app = fake_app({}, {})
        vehicle_state.set_presentation_mode(app, False)
        self.assertTrue(await account_mode.adopt(app, {**OWNER, 'presentation_mode': True}))
        self.assertTrue(vehicle_state.presentation_mode(app))
        self.assertTrue(await account_mode.adopt(app, {**OWNER, 'presentation_mode': False}))
        self.assertFalse(vehicle_state.presentation_mode(app))
        # Motorista e API antiga (sem o campo): nada muda.
        vehicle_state.set_presentation_mode(app, True)
        self.assertFalse(await account_mode.adopt(app, {**DRIVER, 'presentation_mode': False}))
        self.assertFalse(await account_mode.adopt(app, OWNER))
        self.assertTrue(vehicle_state.presentation_mode(app))
        self.assertEqual(app.api.calls, [])

    async def test_demo_account_follows_the_device(self):
        app = await demo_app()
        vehicle_state.set_presentation_mode(app, True)
        self.assertFalse(await account_mode.adopt(app, app.profile))
        self.assertTrue(vehicle_state.presentation_mode(app))
        self.assertIs((await app.api.request('GET', 'me'))['presentation_mode'], True)
        await app.api.close()

    async def test_patch_me_drops_the_cached_profile(self):
        def handle(request):
            if request.method == 'PATCH':
                return httpx.Response(200, json={**OWNER, 'presentation_mode': True})
            return httpx.Response(200, json={**OWNER, 'presentation_mode': False})
        client = ApiClient('https://api.example.com/v1', httpx.MockTransport(handle))
        client.session.update({'access_token': 'a', 'refresh_token': 'r', 'expires_in': 3600})
        client.seed('me', {**OWNER, 'presentation_mode': False})
        self.assertIsNotNone(client.cached_at('me'))
        await client.request('PATCH', 'me', {'presentation_mode': True})
        self.assertIsNone(client.cached_at('me'))
        self.assertEqual(api_cache.invalidation('me').pattern, api_cache._ACCOUNT.pattern)
        await client.close()

    async def test_profile_switch_shows_the_totem_method_for_owners(self):
        app = await demo_app()
        vehicle_state.set_presentation_mode(app, False)
        screen = await profile.build(app)
        caption = by_data(screen, 'presentation-totem')
        self.assertEqual(caption.value, 'Totem: Stripe')
        self.assertIn('O totem de autoatendimento dos seus postos segue este modo da conta.', texts(screen))
        switch = by_data(screen, 'presentation')
        switch.value = True
        await switch.on_change(SimpleNamespace(control=switch))
        self.assertTrue(switch.value and not switch.disabled)
        self.assertEqual(caption.value, 'Totem: sem cobrança')
        self.assertIs((await app.api.request('GET', 'me'))['presentation_mode'], True)
        await app.api.close()

    async def test_driver_profile_has_no_totem_caption(self):
        app = await demo_app()
        app.api._profile.update(account_type='consumer', operator_enabled=False)
        screen = await profile.build(app)
        self.assertIsNotNone(by_data(screen, 'presentation'))
        self.assertIsNone(by_data(screen, 'presentation-totem'))
        await app.api.close()


# ---------------------------------------------------------------- totem do posto (vendedor, em Dados da estação)
def segment(screen, holder, label):
    """``on_click`` da opção ``label`` (Ligado/Desligado) do controle segmentado ``holder``."""
    box = by_data(screen, holder)
    return next(item.on_click for item in descendants(box)
                if isinstance(item, ft.Container) and item.on_click and texts(item) == label)


class KioskSwitchTests(StorageCase):
    def test_status_follows_the_account_mode(self):
        station = {'id': 's1', 'active': True, 'kiosk_mode': True}
        simulated = station_ops.kiosk_status(station, True, {'enabled': False})
        self.assertEqual((simulated['method'], simulated['label'], simulated['reason']), ('simulated', 'SIMULADO', None))
        self.assertEqual(simulated['text'], 'Pagamento: sem cobrança')
        stripe = station_ops.kiosk_status(station, False, {'enabled': True})
        self.assertEqual((stripe['method'], stripe['label'], stripe['text']), ('stripe', 'TESTE', 'Pagamento: Stripe'))
        missing = station_ops.kiosk_status(station, False, {'enabled': False})
        self.assertEqual((missing['enabled'], missing['reason']), (False, 'payments_unavailable'))
        self.assertEqual(missing['text'], 'Indisponível: pagamentos Stripe não configurados no servidor')
        off = station_ops.kiosk_status({**station, 'active': False}, True)
        self.assertEqual((off['reason'], off['text']), ('point_disabled', 'Indisponível: estação inativa'))

    def test_kiosk_field_detection(self):
        self.assertTrue(station_ops.has_kiosk({'kiosk_mode': False}))
        self.assertFalse(station_ops.has_kiosk({'kiosk_payments': False}))
        for removed in ('has_payments', 'payments_subtitle', 'payments_page', 'kiosk_section'):
            self.assertFalse(hasattr(station_ops, removed))

    async def test_switch_in_station_data_patches_kiosk_mode_and_shows_the_method(self):
        app = await demo_app()
        vehicle_state.set_presentation_mode(app, False)
        station = (await app.api.request('GET', 'operator/stations'))['items'][0]
        self.assertIs(station['kiosk_mode'], False)
        menu = await station_admin.build(app, station_id=station['id'])
        self.assertIn('Nome, endereço, status, central e totem (desligado)', texts(menu))
        screen = await station_admin.build(app, station_id=station['id'], page='data')
        self.assertIn('Totem de autoatendimento', texts(screen))
        self.assertEqual(by_data(screen, 'kiosk-status').value, 'Pagamento: Stripe')
        await segment(screen, 'kiosk_mode', 'Ligado')(None)
        self.assertEqual(app.notices[-1], 'Totem de autoatendimento ligado')
        self.assertTrue((await app.api.request('GET', f"stations/{station['id']}"))['kiosk_mode'])
        # Estação inativa: o totem fica indisponível (motivo em uma linha).
        await segment(screen, 'data-status', 'Inativa')(None)
        self.assertEqual(by_data(screen, 'kiosk-status').value, 'Indisponível: estação inativa')
        await segment(screen, 'data-status', 'Ativa')(None)
        await segment(screen, 'kiosk_mode', 'Desligado')(None)
        self.assertEqual(app.notices[-1], 'Totem de autoatendimento desligado')
        # Conta em Modo apresentação: o totem usa o pagamento simulado.
        app.profile['presentation_mode'] = True
        screen = await station_admin.build(app, station_id=station['id'], page='data')
        self.assertEqual(by_data(screen, 'kiosk-status').value, 'Pagamento: sem cobrança')
        await app.api.close()

    async def test_unavailable_without_stripe_and_no_optimistic_update(self):
        app = fake_app({**OWNER, 'presentation_mode': False}, {
            ('GET', 'payments/config'): {'enabled': False},
            ('PATCH', 'stations/s1'): ApiError('Sem conexão', 0, 'network_error'),
        })
        app.api.request = AsyncMock(wraps=app.api.request)
        station = {'id': 's1', 'name': 'Posto', 'address': 'Rua A', 'active': True, 'kiosk_mode': False,
                   'connectors': []}
        with patch.object(station_admin, '_load', AsyncMock(return_value=(station, 'CG-1'))):
            screen = await station_admin.build(app, station_id='s1', page='data')
        self.assertEqual(by_data(screen, 'kiosk-status').value,
                         'Indisponível: pagamentos Stripe não configurados no servidor')
        await segment(screen, 'kiosk_mode', 'Ligado')(None)
        self.assertIs(station['kiosk_mode'], False)
        self.assertIn('Totem não alterado', app.notices[-1])
        selected = [texts(item) for item in descendants(by_data(screen, 'kiosk_mode'))
                    if isinstance(item, ft.Container) and item.on_click and item.bgcolor]
        self.assertEqual(selected, ['Desligado'])  # sem atualização otimista

    async def test_hidden_on_old_api(self):
        app = fake_app({**OWNER}, {})
        station = {'id': 's1', 'name': 'Posto', 'address': 'Rua A', 'active': True, 'connectors': []}
        with patch.object(station_admin, '_load', AsyncMock(return_value=(station, 'CG-1'))):
            screen = await station_admin.build(app, station_id='s1', page='data')
        self.assertIsNone(by_data(screen, 'kiosk_mode'))
        self.assertNotIn('Totem', texts(screen))

    def test_server_kiosk_status_wins_unless_the_account_mode_changed(self):
        station = {'id': 's1', 'active': True, 'kiosk_mode': True,
                   'kiosk_status': {'method': None, 'label': None, 'reason': 'payments_unavailable',
                                    'reason_label': 'Pagamento indisponível'}}
        # Sem consultar payments/config (supõe Stripe), o bloco da API diz indisponível.
        unavailable = station_ops.kiosk_status(station, False)
        self.assertEqual((unavailable['enabled'], unavailable['reason']), (False, 'payments_unavailable'))
        stripe = {**station, 'kiosk_status': {'method': 'stripe', 'label': 'TESTE', 'reason': None}}
        self.assertEqual(station_ops.kiosk_status(stripe, False, {'enabled': False})['method'], 'stripe')
        # Conta virou Modo apresentação depois de ler o posto (cache): o bloco não bate, vale o cálculo.
        self.assertEqual(station_ops.kiosk_status(stripe, True)['method'], 'simulated')
        simulated = {**station, 'kiosk_status': {'method': 'simulated', 'label': 'SIMULADO', 'reason': None}}
        self.assertEqual(station_ops.kiosk_status(simulated, True)['label'], 'SIMULADO')
        self.assertEqual(station_ops.kiosk_status(simulated, False, {'enabled': True})['method'], 'stripe')
        off = {**station, 'kiosk_status': {'method': None, 'label': None, 'reason': 'point_disabled'}}
        self.assertEqual(station_ops.kiosk_status(off, True)['reason'], 'point_disabled')

    async def test_data_page_skips_payments_config_when_the_api_decides(self):
        app = fake_app({**OWNER, 'presentation_mode': False}, {('GET', 'payments/config'): {'enabled': True}})
        app.api.request = AsyncMock(wraps=app.api.request)
        station = {'id': 's1', 'name': 'Posto', 'address': 'Rua A', 'active': True, 'kiosk_mode': True,
                   'connectors': [], 'kiosk_status': {'method': None, 'label': None, 'reason': 'payments_unavailable'}}
        with patch.object(station_admin, '_load', AsyncMock(return_value=(station, 'CG-1'))):
            screen = await station_admin.build(app, station_id='s1', page='data')
        self.assertIn('Indisponível', by_data(screen, 'kiosk-status').value)
        called = [call.args[:2] for call in app.api.request.await_args_list]
        self.assertNotIn(('GET', 'payments/config'), called)


# ---------------------------------------------------------------- ponto em uso no totem (motorista)
class KioskInUseTests(StorageCase):
    async def test_client_maps_reason_to_the_driver_message(self):
        def handle(request):
            return httpx.Response(409, json={'error': {'code': 'point_unavailable', 'message': 'Ponto indisponível',
                                                       'reason': 'kiosk_in_use'}})
        client = ApiClient('https://api.example.com/v1', httpx.MockTransport(handle))
        client.session.update({'access_token': 'a', 'refresh_token': 'r', 'expires_in': 3600})
        with self.assertRaises(ApiError) as caught:
            await client.request('POST', 'reservations', {'connector_id': 'c1'}, key='k')
        error = caught.exception
        self.assertEqual((str(error), error.status, error.reason, error.kiosk_in_use),
                         (KIOSK_IN_USE_MESSAGE, 409, 'kiosk_in_use', True))
        await client.close()

    async def test_other_reasons_keep_the_server_message(self):
        def handle(request):
            return httpx.Response(409, json={'error': {'code': 'point_unavailable', 'message': 'Ponto indisponível',
                                                       'reason': 'reserved'}})
        client = ApiClient('https://api.example.com/v1', httpx.MockTransport(handle))
        client.session.update({'access_token': 'a', 'refresh_token': 'r', 'expires_in': 3600})
        with self.assertRaises(ApiError) as caught:
            await client.request('POST', 'charging-sessions', {'public_code': 'CG-1'}, key='k')
        self.assertEqual((str(caught.exception), caught.exception.kiosk_in_use), ('Ponto indisponível', False))
        await client.close()

    async def test_demo_hold_blocks_reservation_and_start_by_code(self):
        api = DemoApi()
        await api.login(DEMO_EMAIL, DEMO_PASSWORD)
        station = (await api.request('GET', 'operator/stations'))['items'][0]
        point = next(p for p in station['connectors'] if p['available'])
        self.assertIs(point['kiosk_in_use'], False)
        api.hold_for_kiosk(point['id'])
        held = next(p for p in (await api.request('GET', f"stations/{station['id']}"))['connectors']
                    if p['id'] == point['id'])
        self.assertEqual((held['availability_status'], held['kiosk_in_use'], held['available']),
                         ('occupied', True, False))
        self.assertEqual(point_status(held)[0], 'Em uso no totem')
        for path, body in (('reservations', {'connector_id': point['id']}),
                           ('charging-sessions', {'presence_code': DEMO_PRESENCE_CODE,
                                                  'public_code': point['public_code']})):
            with self.assertRaises(ApiError) as caught:
                await api.request('POST', path, body, key=api.new_key())
            self.assertEqual((str(caught.exception), caught.exception.status, caught.exception.reason),
                             ('Ponto em uso no totem', 409, 'kiosk_in_use'))
        api.hold_for_kiosk(point['id'], held=False)
        # Rota só da demo (capturas): trava o primeiro ponto livre do posto.
        routed = await api.request('POST', f"stations/{station['id']}/demo-kiosk-hold", {})
        self.assertTrue(any(p['kiosk_in_use'] for p in routed['connectors']))
        for p in routed['connectors']:
            api.hold_for_kiosk(p['id'], held=False)
        reservation = await api.request('POST', 'reservations', {'connector_id': point['id']}, key=api.new_key())
        self.assertEqual(reservation['connector_id'], point['id'])
        await api.close()

    def test_booking_group_says_kiosk_in_use(self):
        held = {'id': 'c1', 'connector_type': 'Tipo 2', 'power_kw': '7.2', 'price_per_kwh': '2', 'online': True,
                'available': False, 'availability_status': 'occupied', 'kiosk_in_use': True}
        group = rules.group_connectors({'connectors': [held]})[0]
        self.assertEqual(rules.group_subtitle(group), 'Ponto em uso no totem')
        other = {**held, 'id': 'c2', 'kiosk_in_use': False}
        group = rules.group_connectors({'connectors': [held, other]})[0]
        self.assertEqual(rules.group_subtitle(group), 'Nenhum conector livre · 1 em uso no totem')
        free = {**held, 'id': 'c3', 'available': True, 'availability_status': 'available', 'kiosk_in_use': False}
        group = rules.group_connectors({'connectors': [held, free]})[0]
        self.assertEqual(rules.group_subtitle(group), '1 de 2 conectores livre · 1 em uso no totem')
        self.assertEqual(point_status({**held, 'kiosk_in_use': False})[0], 'Ocupado')


# ---------------------------------------------------------------- canal e método nas sessões do vendedor
class SessionChannelTests(StorageCase):
    def test_payment_source_by_channel(self):
        simulated = {'status_label': 'Pago (simulado) · em uso', 'provider': 'simulated', 'method': 'simulated',
                     'environment': 'test', 'origin': 'kiosk', 'channel': 'kiosk_totem'}
        self.assertEqual(owner_sessions.payment_source(simulated), 'Totem · Sem cobrança')
        self.assertEqual(owner_sessions.payment_summary(simulated)[0], 'Pago · em uso')  # sem a marca da API antiga
        self.assertEqual(owner_sessions.payment_source({'origin': 'kiosk', 'channel': 'kiosk_qr', 'provider': 'stripe'}),
                         'QR do painel · Stripe')
        self.assertEqual(owner_sessions.payment_source({'origin': 'app', 'provider': 'stripe'}), 'Stripe')
        # Sem ``channel`` (API antiga): simulado só existe no totem.
        self.assertEqual(owner_sessions.payment_source({'origin': 'kiosk', 'provider': 'simulated'}), 'Totem · Sem cobrança')
        self.assertEqual(owner_sessions.payment_source({'origin': 'kiosk', 'provider': 'stripe'}), 'Painel · Stripe')

    async def test_demo_totem_sale_in_seller_history(self):
        app = await demo_app()
        vehicle_state.set_presentation_mode(app, True)
        await account_mode.adopt(app, app.profile)
        station = (await app.api.request('GET', 'operator/stations'))['items'][0]
        await app.api.request('PATCH', f"stations/{station['id']}", {'kiosk_mode': True})
        await app.api.request('POST', f"stations/{station['id']}/demo-traffic", {})
        copy = texts(await history.build(app, manage=True, chart=False))
        self.assertIn('Pagamento: Totem · Sem cobrança · Cobrado R$', copy)
        self.assertNotIn('(simulado)', copy)
        self.assertIn('Pagamento: Stripe · Pago · em uso', copy)  # visitantes do app continuam iguais
        await app.api.close()


if __name__ == '__main__':
    unittest.main()
