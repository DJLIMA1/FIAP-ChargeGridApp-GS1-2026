import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import flet as ft

from chargegrid_app.app import ChargeGridApp
from chargegrid_app.navigation import parent_route
from chargegrid_app.preferences import Preferences
from chargegrid_app.screens import history, home, profile, stations
from chargegrid_app.ui import theme
from test_behavior import HandlerApp, click, descendants


class PreferencesTests(unittest.TestCase):
    def test_theme_survives_new_preferences_instance(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'preferences.json'
            self.assertTrue(Preferences(path).save(False))
            self.assertFalse(Preferences(path).load())
            self.assertTrue(Preferences(path).save(True))
            self.assertTrue(Preferences(path).load())

    def test_malformed_preferences_fall_back_without_crashing_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'preferences.json'
            for value in [[], None, 'false', {'dark_mode':'false'}, {'dark_mode':None}]:
                path.write_text(json.dumps(value))
                self.assertTrue(Preferences(path).load())

    def test_mobile_storage_directory_used(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {'FLET_APP_STORAGE_DATA':directory}):
            self.assertEqual(Preferences().path, Path(directory) / 'preferences.json')

    def test_reset_restores_persisted_default(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'preferences.json'
            preferences = Preferences(path)
            self.assertTrue(preferences.save(False))
            self.assertTrue(preferences.reset())
            self.assertTrue(Preferences(path).load())


class SettingsResetTests(unittest.IsolatedAsyncioTestCase):
    async def test_reset_requires_confirmation_and_keeps_account_data(self):
        with tempfile.TemporaryDirectory() as directory:
            app = HandlerApp()
            app.api.request.return_value = {'name': 'Ana', 'account_type': 'consumer'}
            app.api.session.access_token = 'token'
            app.preferences = Preferences(Path(directory) / 'preferences.json')
            self.assertTrue(app.preferences.save(False))
            app.dark_mode = False
            app.prepare_navigation = AsyncMock(return_value=True)
            app.logout = AsyncMock()
            app.page.show_dialog = Mock()
            app.page.pop_dialog = Mock()
            theme.set_dark(False)
            try:
                screen = await profile.build(app)
                await click(screen, 'Restaurar configurações')(None)
                dialog = app.page.show_dialog.call_args.args[0]
                self.assertEqual(dialog.title.value, 'Restaurar configurações?')
                self.assertFalse(app.preferences.load())
                dialog.actions[0].on_click(None)
                self.assertFalse(app.preferences.load())
                app.go.assert_not_awaited()

                await click(screen, 'Restaurar configurações')(None)
                dialog = app.page.show_dialog.call_args.args[0]
                await dialog.actions[1].on_click(None)
                self.assertTrue(app.preferences.load())
                self.assertTrue(theme.is_dark())
                self.assertTrue(app.dark_mode)
                self.assertEqual(app.api.session.access_token, 'token')
                self.assertEqual(app.api.request.call_count, 1)
                app.go.assert_awaited_once_with('profile')
                self.assertEqual(app.notices, ['Configurações restauradas.'])
            finally:
                theme.set_dark(True)


class NavigationTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_back_cancels_platform_pop_then_navigates_to_parent(self):
        app = SimpleNamespace(route='auth', data={'mode':'register'}, go=AsyncMock(), prepare_navigation=AsyncMock(return_value=True))
        event = SimpleNamespace(control=SimpleNamespace(confirm_pop=AsyncMock()))
        await ChargeGridApp.native_back(app, event)
        event.control.confirm_pop.assert_awaited_once_with(False)
        app.go.assert_awaited_once_with('auth')

    async def test_native_back_home_allows_exit_without_logout_or_mutation(self):
        app = SimpleNamespace(route='home', data={}, go=AsyncMock(), prepare_navigation=AsyncMock(return_value=True))
        event = SimpleNamespace(control=SimpleNamespace(confirm_pop=AsyncMock()))
        await ChargeGridApp.native_back(app, event)
        event.control.confirm_pop.assert_awaited_once_with(True)
        app.go.assert_not_called()

    async def test_logical_parents_preserve_operator_context(self):
        self.assertEqual(parent_route('operator', {'station_id':'s','connector_id':'c'}), ('operator',{'station_id':'s'}))
        self.assertEqual(parent_route('history', {'station_id':'s'}), ('operator',{'station_id':'s'}))
        self.assertEqual(parent_route('coupons', {'manage':True,'create':True}), ('coupons',{'manage':True}))
        self.assertEqual(parent_route('charging', {'session_id':'s'}), ('stations',{}))
        self.assertIsNone(parent_route('auth', {}))

    async def test_station_poll_updates_empty_state_when_first_station_appears(self):
        app = HandlerApp()
        station = {'id':'s','name':'Posto','address':'Rua','latitude':0,'longitude':0,'connectors':[]}
        app.api.request.side_effect = [{'items':[],'total':0}, {'items':[station],'total':1}, {'items':[],'total':0}]
        screen = await stations.build(app)
        empty = next(item for item in descendants(screen) if isinstance(item,ft.Text) and item.value == 'Nenhum posto encontrado para esta busca.')
        self.assertTrue(empty.visible)
        await app.poll()
        self.assertFalse(empty.visible)
        self.assertIn('Este posto ainda não tem pontos de recarga.', [item.value for item in descendants(screen) if isinstance(item,ft.Text)])
        await app.poll()
        self.assertTrue(empty.visible)
        self.assertEqual(home._station_status(station)[0], 'Sem pontos')

    async def test_history_empty_and_pagination_preserves_station_scope(self):
        app = HandlerApp()
        app.api.request.return_value = {'items':[],'total':60}
        screen = await history.build(app, station_id='s', offset=20)
        app.api.request.assert_awaited_once_with('GET','stations/s/charging-sessions',params={'limit':20,'offset':20})
        await click(screen,'Anterior')(None)
        app.go.assert_awaited_with('history',station_id='s',offset=0)
        await click(screen,'Mais sessões')(None)
        app.go.assert_awaited_with('history',station_id='s',offset=40)
