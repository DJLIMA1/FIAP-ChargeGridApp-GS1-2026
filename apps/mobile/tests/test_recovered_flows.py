import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import flet as ft

from chargegrid_app.api_client import ApiError
from chargegrid_app.app import ChargeGridApp
from chargegrid_app.navigation import active_tab, parent_route, tab_entries
from chargegrid_app.screens import chat, history, profile
from chargegrid_app.session import Session
from test_behavior import HandlerApp, click, descendants


class RecoveredAccountTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_vendor_history_explains_first_step_without_forbidden_request(self):
        app = HandlerApp()
        app.profile = {'account_type': 'vendor', 'operator_enabled': False}
        screen = await history.build(app, manage=True)
        app.api.request.assert_not_called()
        await click(screen, 'Ir para meus postos')(None)
        app.go.assert_awaited_once_with('operator')

    async def test_profile_management_shortcut_switches_mode(self):
        app = HandlerApp()
        app.api.request.return_value = {'account_type': 'vendor', 'operator_enabled': True}
        app.logout = AsyncMock()
        app.switch_mode = AsyncMock()
        screen = await profile.build(app)
        await click(screen, 'Usar como operador')(None)
        app.switch_mode.assert_awaited_once_with('vendor')

    async def test_fields_have_space_for_validation_messages(self):
        screen = profile.password_form(HandlerApp())
        fields = [c for c in descendants(screen) if isinstance(c, ft.TextField)]
        self.assertTrue(all(c.height is None and c.error_max_lines == 3 for c in fields))

    async def test_password_change_checks_confirmation_without_trimming_secret(self):
        app = HandlerApp()
        app.api.session.access_token = 'session'
        app.api.clear_operation = Mock()
        screen = await profile.build(app, mode='password')
        fields = [c for c in descendants(screen) if isinstance(c, ft.TextField)]
        fields[0].value, fields[1].value = ' newpassword ', 'different'
        with self.assertRaisesRegex(ApiError, 'não coincidem'):
            await click(screen, 'Salvar nova senha')(None)
        app.api.request.assert_not_called()
        fields[1].value = fields[0].value
        await click(screen, 'Salvar nova senha')(None)
        app.api.request.assert_awaited_once_with('POST', 'auth/password/update', {'password': ' newpassword '})
        self.assertFalse(app.api.session.access_token)
        self.assertEqual([f.value for f in fields], ['', ''])
        app.go.assert_awaited_once_with('auth')
        self.assertEqual(app.api.clear_operation.call_count, 2)

    async def test_password_error_keeps_form_and_session(self):
        app = HandlerApp()
        app.api.session.access_token = 'session'
        app.api.request.side_effect = ApiError('Senha fraca', 422)
        screen = profile.password_form(app)
        fields = [c for c in descendants(screen) if isinstance(c, ft.TextField)]
        fields[0].value = fields[1].value = 'password123'
        with self.assertRaises(ApiError):
            await click(screen, 'Salvar nova senha')(None)
        self.assertEqual(app.api.session.access_token, 'session')
        self.assertEqual(fields[0].value, 'password123')
        app.go.assert_not_called()

    async def test_short_password_never_reaches_api(self):
        app = HandlerApp()
        screen = profile.password_form(app)
        for c in descendants(screen):
            if isinstance(c, ft.TextField):
                c.value = 'short'
        with self.assertRaisesRegex(ApiError, '8 a 128'):
            await click(screen, 'Salvar nova senha')(None)
        app.api.request.assert_not_called()

    async def test_chat_is_interactive_local_and_does_not_claim_support_ticket(self):
        app = HandlerApp()
        screen = await chat.build(app)
        question = next(c for c in descendants(screen) if isinstance(c, ft.TextField))
        question.value = 'Como faço uma RECARGA com código #F?'
        await question.on_submit(None)
        texts = ' '.join(str(c.value) for c in descendants(screen) if isinstance(c, ft.Text))
        self.assertIn('cinco números atuais após #F', texts)
        self.assertIn('Não guarde o código para usar depois.', texts)
        self.assertEqual(question.value, '')
        question.value = 'Como funcionam tempo, valor e cupons?'
        await question.on_submit(None)
        texts = ' '.join(str(c.value) for c in descendants(screen) if isinstance(c, ft.Text))
        self.assertIn('Não há Pix, cobrança real', texts)
        app.api.request.assert_not_called()
        self.assertNotIn('chamado registrado',texts.casefold())

    async def test_vendor_tabs_have_scoped_history_and_coupons(self):
        entries = tab_entries('vendor')
        self.assertIn(('history', 'Histórico', {'manage': True}), entries)
        self.assertIn(('coupons', 'Cupons', {'manage': True}), entries)
        self.assertNotIn('home', [route for route, _, _ in entries])
        self.assertEqual(active_tab('charging', {}, 'consumer'), 'stations')
        self.assertEqual(active_tab('coupons', {}, 'vendor'), 'profile')
        self.assertIsNone(parent_route('operator', {}, 'vendor'))
        self.assertEqual(parent_route('profile', {'mode': 'password'}, 'vendor'), ('profile', {}))
        self.assertEqual(parent_route('charging', {'point_context': {'station_id': 's'}}),
                         ('stations', {'station_id': 's'}))


class PollAndModeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        page = SimpleNamespace(width=390, window=SimpleNamespace(), views=[SimpleNamespace()],
                               add=Mock(), update=Mock(), show_dialog=Mock(), pop_dialog=Mock())
        self.client = SimpleNamespace(session=Session(), request=AsyncMock(), close=AsyncMock())
        with patch('chargegrid_app.app.ApiClient', return_value=self.client), patch('chargegrid_app.app.Preferences') as prefs:
            prefs.return_value.load.return_value = True
            self.app = ChargeGridApp(page)
        self.client.session.access_token = 'session'

    async def asyncTearDown(self):
        self.app.cancel_screen()
        await asyncio.sleep(0)

    async def test_poll_registered_by_action_starts_and_replaces_old_task(self):
        called = asyncio.Event()
        callback = AsyncMock(side_effect=called.set)
        async def operation():
            self.app.set_poll(callback, 0.001)
        await self.app.action(operation)(None)
        await asyncio.wait_for(called.wait(), 1)
        old = self.app.poll_task
        self.app.set_poll(AsyncMock(), 10)
        await asyncio.sleep(0)
        self.assertTrue(old.cancelled())
        self.assertIsNot(old, self.app.poll_task)

    async def test_poll_waits_for_screen_build_then_starts(self):
        callback = AsyncMock()
        async def screen(app):
            app.set_poll(callback, 10)
            await asyncio.sleep(0)
            self.assertIsNone(app.poll_task)
            return ft.Column()
        with patch.dict('chargegrid_app.app.SCREENS', {'operator': screen}):
            await self.app.go('operator')
        self.assertIsNotNone(self.app.poll_task)
        callback.assert_not_called()

    async def test_mode_switch_preserves_account_and_asks_before_discard(self):
        self.app.profile = {'account_type': 'vendor', 'operator_enabled': True}
        self.app.go = AsyncMock()
        self.app.prepare_navigation = AsyncMock(return_value=False)
        await self.app.switch_mode('vendor')
        self.assertEqual(self.app.browsing_mode, 'consumer')
        self.app.go.assert_not_called()
        self.app.prepare_navigation.return_value = True
        await self.app.switch_mode('vendor')
        self.app.go.assert_awaited_once_with('operator')
        self.assertEqual(self.client.session.access_token, 'session')
        self.assertEqual(self.app.profile['account_type'], 'vendor')
        self.client.request.assert_not_called()

    async def test_consumer_cannot_gain_vendor_permissions_by_switch(self):
        self.app.go = AsyncMock()
        await self.app.switch_mode('vendor')
        self.assertEqual(self.app.browsing_mode, 'consumer')
        self.app.go.assert_not_called()
