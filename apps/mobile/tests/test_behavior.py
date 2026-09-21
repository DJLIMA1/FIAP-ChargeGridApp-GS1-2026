"""Exercise actual event callbacks, including async state changes and HTTP replay."""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import flet as ft
import httpx

from chargegrid_app.api_client import ApiClient, ApiError
from chargegrid_app.app import ChargeGridApp
from chargegrid_app.screens import auth, charging, coupons, home, stations
from chargegrid_app.session import Session
from chargegrid_app.ui import theme


def descendants(item):
    yield item
    content = getattr(item, 'content', None)
    if content and not isinstance(content, str):
        yield from descendants(content)
    for child in getattr(item, 'controls', []) or []:
        yield from descendants(child)


def click(screen, label):
    return next(item.on_click for item in descendants(screen)
                if getattr(item, 'on_click', None)
                and isinstance(getattr(item, 'content', None), ft.Text)
                and item.content.value == label)


class HandlerApp:
    def __init__(self):
        self.page = SimpleNamespace(update=lambda: None)
        self.api = SimpleNamespace(session=Session(), request=AsyncMock(), last_session_id=None,
                                   new_key=lambda: 'intent', clear_operation=lambda path: None)
        self.profile = {}
        self.active_actions = set()
        self.prompting = False
        self.go = AsyncMock()
        self.signed_in = AsyncMock()
        self.notices = []
        self.poll = None

    def action(self, callback):
        async def event(e=None):
            await callback()
        return event

    def link(self, route, **kwargs):
        async def event(e=None):
            await self.go(route, **kwargs)
        return event

    def notice(self, message):
        self.notices.append(message)

    def set_poll(self, callback, interval):
        self.poll = callback


class BehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def test_home_poll_refreshes_status_summary_and_availability_in_place(self):
        app = HandlerApp()
        app.page.update = Mock()
        station = {'id':'station','name':'Posto','address':'Rua','connectors':[{'available':True,'online':True,'price_per_kwh':'1'}]}
        state = {
            'reservations/current':None,
            'charging-sessions/current':{'id':'charge','status':'starting','source':'simulated','soc_percent':20,'online':True},
            'stations':{'items':[station],'total':1},
            'me/summary':{'estimated_cost':'0','sessions_count':0,'energy_wh':'0'},
        }
        async def request(method,path,**kwargs):
            return state[path]
        app.api.request.side_effect = request
        screen = await home.build(app)
        original_controls = list(screen.controls)
        active_card = next(item for item in screen.controls if isinstance(item,ft.Container) and isinstance(item.content,ft.Row) and item.on_click)
        self.assertIn('Aguardando equipamento iniciar', ' '.join(str(item.value) for item in descendants(screen) if isinstance(item,ft.Text)))
        await app.poll()
        app.page.update.assert_not_called()
        state['charging-sessions/current'] = None
        state['me/summary'] = {'estimated_cost':'1.25','sessions_count':1,'energy_wh':'1250'}
        state['stations'] = {'items':[{**station,'connectors':[{'available':False,'online':False,'price_per_kwh':'1'}]}],'total':1}
        await app.poll()
        texts = ' '.join(str(item.value) for item in descendants(screen) if isinstance(item,ft.Text))
        self.assertIn('Nenhuma reserva ou recarga ativa',texts)
        self.assertNotIn('Aguardando equipamento iniciar',texts)
        self.assertIn('R$ 1,25',texts)
        self.assertIn('1 recargas concluídas · 1.250 kWh',texts)
        self.assertIn('Offline',texts)
        self.assertTrue(all(before is after for before,after in zip(original_controls,screen.controls)))
        app.go.assert_not_called()
        app.page.update.assert_called_once_with()
        await active_card.on_click(None)
        app.go.assert_awaited_once_with('stations')
        await app.poll()
        app.page.update.assert_called_once_with()

    async def test_vendor_signup_keeps_fields_and_sends_type_with_unchanged_password(self):
        app = HandlerApp()
        app.api.request.return_value = {'requires_email_confirmation': True}
        screen = await auth.build(app, mode='register')
        fields = [item for item in descendants(screen) if isinstance(item, ft.TextField)]
        for control, value in zip(fields, ['Vendor Name', 'vendor@example.com', ' senha1234 ']):
            control.value = value
        await click(screen, 'Sou vendedor')(None)
        self.assertEqual(fields[0].value, 'Vendor Name')
        self.assertEqual(fields[2].value, ' senha1234 ')
        await click(screen, 'Criar conta')(None)
        body = app.api.request.call_args.args[2]
        self.assertEqual(body['account_type'], 'vendor')
        self.assertEqual(body['password'], ' senha1234 ')
        app.go.assert_awaited_once_with('auth', mode='verify', email_value='vendor@example.com')

    async def test_register_button_and_enter_share_one_inflight_submission(self):
        app = HandlerApp()
        entered, finish = asyncio.Event(), asyncio.Event()
        async def slow_request(*args, **kwargs):
            entered.set()
            await finish.wait()
            return {'requires_email_confirmation': True}
        app.api.request.side_effect = slow_request
        screen = await auth.build(app, mode='register')
        fields = [item for item in descendants(screen) if isinstance(item, ft.TextField)]
        for control, value in zip(fields, ['Name', 'u@example.com', 'password123']):
            control.value = value
        pending = asyncio.create_task(click(screen, 'Criar conta')(None))
        await entered.wait()
        await fields[-1].on_submit(None)
        self.assertEqual(app.api.request.await_count, 1)
        finish.set()
        await pending

    async def test_login_accepts_existing_short_password_unchanged(self):
        app = HandlerApp()
        app.api.login = AsyncMock()
        screen = await auth.build(app)
        fields = [item for item in descendants(screen) if isinstance(item, ft.TextField)]
        fields[0].value, fields[1].value = 'user@example.com', ' old '
        await click(screen, 'Entrar')(None)
        app.api.login.assert_awaited_once_with('user@example.com', ' old ')
        app.signed_in.assert_awaited_once_with()

    async def test_signed_in_vendor_requires_approved_operator_before_operator_destination(self):
        for approved, expected in [(False, 'home'), (True, 'operator')]:
            app = SimpleNamespace(api=SimpleNamespace(request=AsyncMock(return_value={
                'account_type': 'vendor', 'operator_enabled': approved})), go=AsyncMock())
            await ChargeGridApp.signed_in(app)
            app.go.assert_awaited_once_with(expected)

    async def test_theme_isolation_between_concurrent_user_sessions(self):
        ready = asyncio.Event()
        async def light_user():
            theme.set_dark(False)
            ready.set()
            await asyncio.sleep(0)
            return theme.BG_COLOR
        async def dark_user():
            await ready.wait()
            theme.set_dark(True)
            await asyncio.sleep(0)
            return theme.BG_COLOR
        self.assertEqual(await asyncio.gather(light_user(), dark_user()), ['#F2F2F3', '#131313'])

    async def test_charge_completed_poll_rebuilds_actions(self):
        app = HandlerApp()
        session = {'id': 's', 'status': 'charging', 'max_duration_minutes': 30, 'online': True}
        app.api.request.side_effect = [session, {**session, 'status': 'completed'}]
        await charging.build(app)
        await app.poll()
        app.go.assert_awaited_once_with('charging', session_id='s')

    async def test_explicit_new_point_does_not_reopen_old_completed_session(self):
        app = HandlerApp()
        app.api.last_session_id = 'old-completed'
        app.api.request.return_value = None
        screen = await charging.build(app, public_code='CG-NEW')
        self.assertEqual(app.api.request.await_count, 1)
        self.assertTrue(click(screen, 'Solicitar início'))

    async def test_invalid_charging_limits_do_not_call_api(self):
        for duration, cost in [('0', ''), ('1.5', ''), ('30', '-1'), ('30', 'NaN')]:
            app = HandlerApp()
            app.api.request.return_value = None
            screen = await charging.build(app, public_code='CG-ONE')
            fields = [item for item in descendants(screen) if isinstance(item, ft.TextField)]
            fields[1].value, fields[2].value = duration, cost
            app.api.request.reset_mock()
            with self.assertRaises(ApiError):
                await click(screen, 'Solicitar início')(None)
            app.api.request.assert_not_called()

    async def test_partial_coordinate_search_is_rejected_without_navigation(self):
        app = HandlerApp()
        app.api.request.return_value = {'items': [], 'total': 0}
        screen = await stations.build(app)
        fields = [item for item in descendants(screen) if isinstance(item, ft.TextField)]
        latitude = next(field for field in fields if field.label == 'Latitude')
        latitude.value = '-23.5'
        with self.assertRaisesRegex(ApiError, 'juntas'):
            await click(screen, 'Buscar')(None)
        app.go.assert_not_called()

    async def test_coupon_create_cannot_bypass_operator_guard(self):
        app = HandlerApp()
        await coupons.build(app, create=True)
        app.api.request.assert_not_called()

    async def test_coupon_form_rejects_fractional_discount_and_past_expiry(self):
        app = HandlerApp()
        screen = coupons.form(app)
        fields = [item for item in descendants(screen) if isinstance(item, ft.TextField)]
        by_label = {field.label: field for field in fields}
        by_label['Código'].value = 'DEMO'
        by_label['Desconto %'].value = '10.5'
        with self.assertRaisesRegex(ApiError, 'inteiro'):
            await click(screen, 'Salvar cupom')(None)
        by_label['Desconto %'].value = '10'
        by_label['Validade (dia/mês/ano hora:minuto)'].value = '01/01/2000 12:00'
        with self.assertRaisesRegex(ApiError, 'futura'):
            await click(screen, 'Salvar cupom')(None)
        app.api.request.assert_not_called()

    async def test_poll_recovers_after_temporary_network_failure(self):
        app = HandlerApp()
        app.generation, app.closed = 1, False
        count = 0
        async def update():
            nonlocal count
            count += 1
            if count == 1:
                raise ApiError('Rede indisponível')
            app.generation = 2
        with patch('chargegrid_app.app.asyncio.sleep', new=AsyncMock()):
            await ChargeGridApp.poll(app, update, 5, 1)
        self.assertEqual(count, 2)
        self.assertEqual(app.notices, ['Rede indisponível'])

    async def test_dark_and_light_account_selector_keeps_own_palette(self):
        app = HandlerApp()
        app.dark_mode = False
        theme.set_dark(False)
        screen = await auth.build(app, mode='register')
        theme.set_dark(True)
        await click(screen, 'Sou vendedor')(None)
        consumer = next(item for item in descendants(screen)
                        if getattr(item, 'data', None) == 'consumer')
        self.assertIsNone(consumer.bgcolor)
        self.assertEqual(consumer.content.color, theme.LIGHT['TEXT_COLOR'])

    async def test_numeric_password_is_submitted_for_provider_policy_validation(self):
        app = HandlerApp()
        app.api.request.return_value = {'requires_email_confirmation':True}
        screen = await auth.build(app, mode='register')
        fields = [item for item in descendants(screen) if isinstance(item, ft.TextField)]
        for control, value in zip(fields, ['Name', 'u@example.com', '12345678']):
            control.value = value
        await click(screen, 'Criar conta')(None)
        self.assertEqual(app.api.request.call_args.args[2]['password'], '12345678')

    async def test_second_unauthorized_response_clears_session(self):
        requests = []
        def handler(request):
            requests.append(request.url.path)
            if request.url.path.endswith('/refresh'):
                return httpx.Response(200, json={'access_token':'new', 'refresh_token':'refresh', 'expires_in':3600})
            return httpx.Response(401, json={'error': {'message':'Entre novamente', 'code':'unauthorized'}})
        client = ApiClient('https://example.test/v1', httpx.MockTransport(handler))
        client.session.update({'access_token':'old', 'refresh_token':'refresh', 'expires_in':3600})
        try:
            with self.assertRaises(ApiError):
                await client.request('GET', 'me')
            self.assertIsNone(client.session.access_token)
            self.assertEqual(requests, ['/v1/me', '/v1/auth/refresh', '/v1/me'])
        finally:
            await client.close()

    async def test_real_client_login_logout_login_preserves_credential_bytes(self):
        logins = []
        def handler(request):
            if request.url.path.endswith('/login'):
                logins.append(json.loads(request.content))
                return httpx.Response(200, json={'access_token': f'access-{len(logins)}', 'refresh_token':'refresh', 'expires_in':3600})
            return httpx.Response(200, json={'ok':True})
        client = ApiClient('https://example.test/v1', httpx.MockTransport(handler))
        try:
            for _ in range(2):
                await client.login('u@example.com', ' password123 ')
                await client.request('POST', 'auth/logout')
                client.session.clear()
            self.assertEqual(logins, [{'email':'u@example.com','password':' password123 '}] * 2)
        finally:
            await client.close()
