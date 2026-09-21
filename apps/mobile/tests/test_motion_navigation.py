import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import flet as ft
from chargegrid_app.api_client import ApiError
from chargegrid_app.app import ChargeGridApp
from chargegrid_app.navigation import editable_controls, parent_route
from chargegrid_app.session import Session
from chargegrid_app.ui import motion
from test_behavior import click


class MotionNavigationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.page = SimpleNamespace(width=390, window=SimpleNamespace(), views=[SimpleNamespace()],
                                    add=Mock(), update=Mock(), show_dialog=Mock(), pop_dialog=Mock())
        self.client = SimpleNamespace(session=Session(), request=AsyncMock(), close=AsyncMock())
        with patch('chargegrid_app.app.ApiClient', return_value=self.client), patch('chargegrid_app.app.Preferences') as preferences:
            preferences.return_value.load.return_value = True
            self.app = ChargeGridApp(self.page)
        self.client.session.access_token = 'test-session'
        self.field = ft.TextField(value='Original')
        self.app.form_baseline = [(self.field, self.app.field_digest(self.field))]
        motion.set_reduced(False)

    async def asyncTearDown(self):
        self.app.cancel_screen()
        await asyncio.sleep(0)
        motion.set_reduced(False)

    async def test_discard_dialog_keep_preserves_input_and_route(self):
        self.field.value = 'Não salvo'
        self.app.go = AsyncMock()
        task = asyncio.create_task(self.app.link('home')(None))
        await asyncio.sleep(0)
        dialog = self.page.show_dialog.call_args.args[0]
        self.assertEqual(dialog.title.value, 'Descartar alterações?')
        await dialog.actions[0].on_click(None)
        await task
        self.assertEqual(self.field.value, 'Não salvo')
        self.app.go.assert_not_awaited()
        self.assertFalse(self.app.prompting)

    async def test_discard_dialog_confirm_navigates_once(self):
        self.field.value = 'Alterado'
        self.app.go = AsyncMock()
        task = asyncio.create_task(self.app.link('home')(None))
        await asyncio.sleep(0)
        self.assertFalse(await self.app.prepare_navigation())
        dialog = self.page.show_dialog.call_args.args[0]
        await dialog.actions[1].on_click(None)
        dialog.on_dismiss(None)
        await task
        self.app.go.assert_awaited_once_with('home')

    async def test_dismiss_dialog_cancels_navigation(self):
        self.field.value = 'Alterado'
        task = asyncio.create_task(self.app.prepare_navigation())
        await asyncio.sleep(0)
        self.page.show_dialog.call_args.args[0].on_dismiss(None)
        self.assertFalse(await task)

    async def test_mark_saved_clears_dirty_state_without_retaining_plaintext(self):
        self.field.value = 'segredo temporário'
        self.assertTrue(self.app.dirty_form())
        self.app.mark_saved()
        self.assertFalse(self.app.dirty_form())
        self.assertIsInstance(self.app.form_baseline[0][1], bytes)
        self.assertNotIn(b'segredo', self.app.form_baseline[0][1])

    async def test_pending_operation_blocks_back_and_double_click(self):
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def operation():
            calls.append('mutation')
            entered.set()
            await release.wait()

        self.app.route = 'charging'
        control = ft.Container()
        event = SimpleNamespace(control=control)
        handler = self.app.action(operation)
        task = asyncio.create_task(handler(event))
        await entered.wait()
        self.assertTrue(control.disabled)
        self.assertEqual(control.scale, 0.985)
        self.assertFalse(self.page.views[0].can_pop)
        self.app.go = AsyncMock()
        back_event = SimpleNamespace(control=SimpleNamespace(confirm_pop=AsyncMock()))
        await self.app.native_back(back_event)
        back_event.control.confirm_pop.assert_awaited_once_with(False)
        self.app.go.assert_not_awaited()
        await handler(event)
        self.assertEqual(calls, ['mutation'])
        second_operation = AsyncMock()
        await self.app.action(second_operation)(SimpleNamespace(control=ft.Container()))
        second_operation.assert_not_called()
        release.set()
        await task
        self.assertFalse(control.disabled)
        self.assertEqual(control.scale, 1)
        self.assertFalse(self.app.active_actions)

    async def test_failed_operation_restores_interaction(self):
        operation = AsyncMock(side_effect=ApiError('Indisponível'))
        control = ft.Container()
        await self.app.action(operation)(SimpleNamespace(control=control))
        self.assertFalse(control.disabled)
        self.assertEqual(control.opacity, 1)
        self.assertFalse(self.app.active_actions)

    async def test_same_tab_does_not_reload_or_drop_fields(self):
        self.app.route = 'profile'
        self.field.value = 'Alterado'
        self.app.go = AsyncMock()
        await self.app.link('profile')(None)
        self.app.go.assert_not_called()
        self.page.show_dialog.assert_not_called()

    async def test_error_retry_reloads_same_route(self):
        screen = AsyncMock(side_effect=[ApiError('Falha temporária'), ft.Column([ft.Text('OK')])])
        with patch.dict('chargegrid_app.app.SCREENS', {'home': screen}):
            await self.app.go('home')
            await click(self.app.scene.content, 'Tentar novamente')(None)
        self.assertEqual(screen.await_count, 2)
        self.assertFalse(self.app.loading.visible)

    async def test_fast_route_uses_switcher_without_loading_flash(self):
        with patch.dict('chargegrid_app.app.SCREENS', {'profile': AsyncMock(return_value=ft.Column([self.field]))}):
            old = self.app.scene.content
            await self.app.go('profile')
        self.assertIsInstance(self.app.scene, ft.AnimatedSwitcher)
        self.assertTrue(old.disabled)
        self.assertFalse(self.app.scene.content.disabled)
        self.assertFalse(self.app.loading.visible)
        self.assertIsNone(self.app.loading_task)
        self.field.value = 'Editado'
        self.assertTrue(self.app.dirty_form())

    async def test_slow_route_exposes_loading_until_response(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def screen(app):
            entered.set()
            await release.wait()
            return ft.Column([ft.Text('OK')])

        with patch.dict('chargegrid_app.app.SCREENS', {'home': screen}):
            task = asyncio.create_task(self.app.go('home'))
            await entered.wait()
            await asyncio.sleep(0.21)
            self.assertTrue(self.app.loading.visible)
            self.assertIsInstance(self.app.loading.content, ft.ProgressBar)
            release.set()
            await task
        self.assertFalse(self.app.loading.visible)

    async def test_new_navigation_cancels_outgoing_request(self):
        entered = asyncio.Event()

        async def slow(app):
            entered.set()
            await asyncio.Event().wait()

        with patch.dict('chargegrid_app.app.SCREENS', {'home': slow, 'help': AsyncMock(return_value=ft.Column())}):
            previous = asyncio.create_task(self.app.go('home'))
            await entered.wait()
            await self.app.go('help')
            with self.assertRaises(asyncio.CancelledError):
                await previous
        self.assertEqual(self.app.route, 'help')
        self.assertFalse(self.app.loading.visible)

    async def test_reduced_motion_disables_transition_hover_and_press(self):
        service = SimpleNamespace(get_accessibility_features=AsyncMock(return_value=SimpleNamespace(disable_animations=False, reduce_motion=True)))
        with patch('chargegrid_app.app.ft.SemanticsService', return_value=service):
            await self.app.configure_motion()
        self.assertEqual(self.app.scene.duration, 0)
        self.assertEqual(motion.animation().duration, 0)
        control = SimpleNamespace(disabled=False, scale=1, update=Mock())
        await motion.hover(SimpleNamespace(control=control, data='true'))
        self.assertEqual(control.scale, 1)
        self.app.generation = 1
        with patch('chargegrid_app.app.asyncio.sleep', new=AsyncMock()):
            await self.app.delayed_loading(1)
        self.assertIsInstance(self.app.loading.content, ft.Text)

    async def test_accessibility_probe_failure_uses_static_fallback(self):
        with patch('chargegrid_app.app.ft.SemanticsService', side_effect=RuntimeError('Unavailable')):
            await self.app.configure_motion()
        self.assertTrue(self.app.reduced_motion)
        self.assertEqual(self.app.scene.duration, 0)

    async def test_editable_controls_skip_hidden_readonly_and_preferences(self):
        visible = ft.TextField(value='A')
        controls = ft.Column([visible, ft.TextField(read_only=True), ft.TextField(disabled=True),
                              ft.Container(ft.TextField(), visible=False), ft.Switch(data='preference')])
        self.assertEqual(list(editable_controls(controls)), [visible])

    async def test_back_preserves_reservation_and_station_context(self):
        self.assertEqual(parent_route('charging', {'reservation_id': 'r'}), ('reservations', {}))
        self.assertEqual(parent_route('coupons', {'station_id': 's'}), ('stations', {'station_id': 's'}))
        self.app.route, self.app.data = 'charging', {'reservation_id': 'r'}
        self.app.go = AsyncMock()
        await self.app.back()
        self.app.go.assert_awaited_once_with('reservations')
        self.client.request.assert_not_called()

    async def test_poll_cannot_replace_screen_during_pending_mutation(self):
        self.app.active_actions.add(object())
        original = self.app.scene.content

        async def polling():
            self.app.poll_task = asyncio.current_task()
            await self.app.go('charging')

        task = asyncio.create_task(polling())
        await task
        self.app.poll_task = None
        self.assertIs(self.app.scene.content, original)
        self.assertEqual(self.app.route, 'auth')
        self.client.request.assert_not_called()
