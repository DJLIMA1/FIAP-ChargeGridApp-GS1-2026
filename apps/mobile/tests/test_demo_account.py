"""Verify the boundary between public local demo and authenticated API accounts."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import flet as ft

from chargegrid_app.api_client import ApiError
from chargegrid_app.app import ChargeGridApp
from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DemoApi
from chargegrid_app.screens import auth, profile
from chargegrid_app.session import Session
from test_behavior import HandlerApp, click, descendants


class DemoAccountTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.real = SimpleNamespace(session=Session(), close=AsyncMock(), login=AsyncMock(),
                                    request=AsyncMock(), operation_keys={},
                                    charging_operation_sessions={}, last_session_id=None,
                                    last_reservation_id=None)
        page = SimpleNamespace(width=390, window=SimpleNamespace(), views=[SimpleNamespace()],
                               add=Mock(), update=Mock(), show_dialog=Mock(), pop_dialog=Mock())
        with patch('chargegrid_app.app.ApiClient', return_value=self.real), patch('chargegrid_app.app.Preferences') as prefs:
            prefs.return_value.load.return_value = True
            self.app = ChargeGridApp(page)
        self.app.go = AsyncMock()

    async def asyncTearDown(self):
        self.app.cancel_screen()
        await self.app.api.close()

    async def test_public_credentials_enter_local_demo_without_api_auth(self):
        await self.app.login('  DEMO@CHARGEGRID.EXAMPLE  ', DEMO_PASSWORD)
        self.assertIsInstance(self.app.api, DemoApi)
        self.real.login.assert_not_called()
        self.real.request.assert_not_called()
        self.real.close.assert_awaited_once()
        await self.app.signed_in()
        self.assertEqual(self.app.browsing_mode, 'consumer')
        self.assertTrue(self.app.profile['operator_enabled'])
        self.app.go.assert_awaited_once_with('home')

    async def test_wrong_demo_password_does_not_send_credentials_or_replace_client(self):
        with self.assertRaises(ApiError):
            await self.app.login(DEMO_EMAIL, 'wrong-password')
        self.assertIs(self.app.api, self.real)
        self.real.login.assert_not_called()
        self.real.close.assert_not_called()

    async def test_ordinary_account_keeps_real_login(self):
        await self.app.login('person@example.com', ' secret ')
        self.real.login.assert_awaited_once_with('person@example.com', ' secret ')
        self.assertIs(self.app.api, self.real)

    async def test_new_login_clears_previous_accounts_operations_and_drafts(self):
        self.real.operation_keys['charging-sessions'] = ('old-body','old-key')
        self.real.charging_operation_sessions['old-key'] = 'old-session'
        self.real.last_session_id = 'old-session'
        self.real.last_reservation_id = 'old-reservation'
        self.app.charging_draft = {'owner':'previous'}
        self.app.chat_messages = [{'content':'previous private message'}]
        await self.app.login('next@example.com','existing-password')
        self.assertEqual(self.real.operation_keys,{})
        self.assertEqual(self.real.charging_operation_sessions,{})
        self.assertIsNone(self.real.last_session_id)
        self.assertIsNone(self.real.last_reservation_id)
        self.assertIsNone(self.app.charging_draft)
        self.assertEqual(self.app.chat_messages,[])

    async def test_logout_discards_demo_state_and_restores_real_preferences(self):
        await self.app.enter_demo()
        demo = self.app.api
        await demo.request('PATCH', 'me', {'name': 'Edited demo'})
        self.app.dark_mode = False
        self.app.prepare_navigation = AsyncMock(return_value=True)
        replacement = SimpleNamespace(close=AsyncMock())
        with patch('chargegrid_app.app.ApiClient', return_value=replacement):
            await self.app.logout()
        self.assertIs(self.app.api, replacement)
        self.assertFalse(demo.session.access_token)
        self.assertEqual(self.app.profile, {})
        self.assertTrue(self.app.dark_mode)
        self.app.go.assert_awaited_with('auth')
        await demo.login(DEMO_EMAIL, DEMO_PASSWORD)
        self.assertNotEqual((await demo.request('GET', 'me'))['name'], 'Edited demo')
        await demo.close()

    async def test_demo_button_enters_without_form_or_api_call(self):
        app = HandlerApp()
        app.enter_demo = AsyncMock()
        screen = await auth.build(app)
        await click(screen, 'Entrar na conta demo')(None)
        app.enter_demo.assert_awaited_once_with()
        app.api.request.assert_not_called()

    async def test_demo_credentials_use_app_login_boundary(self):
        app = HandlerApp()
        app.login = AsyncMock()
        screen = await auth.build(app)
        fields = [c for c in descendants(screen) if isinstance(c, ft.TextField)]
        fields[0].value, fields[1].value = DEMO_EMAIL, DEMO_PASSWORD
        await click(screen, 'Entrar')(None)
        app.login.assert_awaited_once_with(DEMO_EMAIL, DEMO_PASSWORD)
        app.signed_in.assert_awaited_once_with()
        app.api.request.assert_not_called()

    async def test_demo_signup_recovery_and_confirmation_never_reach_provider(self):
        for mode, label in [('register', 'Criar conta'), ('forgot', 'Enviar link'),
                            ('reset', 'Alterar senha'), ('verify', 'Reenviar confirmação')]:
            with self.subTest(mode=mode):
                app = HandlerApp()
                screen = await auth.build(app, mode=mode, email_value=DEMO_EMAIL)
                await click(screen, label)(None)
                app.api.request.assert_not_called()
                self.assertIn('demo', ' '.join(str(c.value) for c in descendants(screen) if isinstance(c, ft.Text)))

    async def test_demo_password_form_cannot_change_real_credentials(self):
        app = HandlerApp()
        app.api.is_demo = True
        screen = profile.password_form(app)
        self.assertFalse(any(isinstance(c, ft.TextField) for c in descendants(screen)))
        app.api.request.assert_not_called()
