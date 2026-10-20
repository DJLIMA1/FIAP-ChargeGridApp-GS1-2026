"""Regression tests for the QA audit of 2026-10 (docs/qa-auditoria-2026-10.md)."""
import ast
import asyncio
import io
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import flet as ft
from PIL import Image

import chargegrid_core.driver as driver_package
from chargegrid_app.api_client import ApiError
from chargegrid_app.app import POLL_BACKOFF_MAX, ChargeGridApp
from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DEMO_PRESENCE_CODE, DemoApi
from chargegrid_app.services import maps
from chargegrid_app.session import Session
from chargegrid_app.ui import theme
from chargegrid_app.ui.components import money
from test_brand_accessibility import contrast

SOURCE = Path(__file__).resolve().parents[1] / 'src' / 'chargegrid_app'


def make_app():
    real = SimpleNamespace(session=Session(), close=AsyncMock(), login=AsyncMock(), request=AsyncMock(),
                           operation_keys={}, charging_operation_sessions={}, last_session_id=None,
                           last_reservation_id=None)
    page = SimpleNamespace(width=390, window=SimpleNamespace(), views=[SimpleNamespace()],
                           add=Mock(), update=Mock(), show_dialog=Mock(), pop_dialog=Mock())
    with patch('chargegrid_app.app.ApiClient', return_value=real), patch('chargegrid_app.app.Preferences') as prefs:
        prefs.return_value.load.return_value = True
        app = ChargeGridApp(page)
    app.go = AsyncMock()
    app.notice = Mock()
    return app, real


class MoneyFormattingTests(unittest.TestCase):
    def test_money_uses_half_up_rounding_and_thousands_separator(self):
        # Binary floats rounded R$ 2,675 to R$ 2,67 and showed R$ 1234,50 without a separator.
        self.assertEqual(money(2.675), 'R$ 2,68')
        self.assertEqual(money('1234.5'), 'R$ 1.234,50')
        self.assertEqual(money('3.6000'), 'R$ 3,60')
        self.assertEqual(money(None), 'R$ 0,00')
        self.assertEqual(money(''), 'R$ 0,00')


class ContrastRegressionTests(unittest.TestCase):
    def tearDown(self):
        theme.set_dark(True)

    def test_status_fills_are_never_used_as_text_colour(self):
        """RED/AMBER/BLUE/SLATE fail 4.5:1 as text on dark cards; text uses ACCENT/WARNING."""
        offenders = []
        for path in SOURCE.rglob('*.py'):
            if path.name == 'chat.py':  # Owned by the AI chat rewrite.
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                name = getattr(node.func, 'attr', None) or getattr(node.func, 'id', None) if isinstance(node, ast.Call) else None
                if name == 'Text':
                    colours = [keyword.value for keyword in node.keywords if keyword.arg == 'color']
                elif name == '_small':  # Text helper of the driver screen: (text, color=None).
                    colours = node.args[1:2] + [keyword.value for keyword in node.keywords if keyword.arg == 'color']
                else:
                    continue
                for value in colours:
                    if isinstance(value, ast.Attribute) and value.attr in ('RED', 'AMBER', 'BLUE', 'SLATE'):
                        offenders.append(f'{path.name}:{node.lineno}')
        self.assertEqual(offenders, [])

    def test_warning_text_meets_aa_in_both_themes(self):
        for dark in (False, True):
            theme.set_dark(dark)
            for background in (theme.WHITE, theme.BG_COLOR):
                with self.subTest(dark=dark, background=background):
                    self.assertGreaterEqual(contrast(theme.WARNING, background), 4.5)


class AppShellTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        self.app.cancel_screen()

    async def test_logout_without_network_still_signs_out_locally(self):
        self.app, real = make_app()
        real.session.access_token = 'token'
        real.request.side_effect = ApiError('Não foi possível conectar com segurança.')
        self.app.prepare_navigation = AsyncMock(return_value=True)
        await self.app.logout()  # Used to propagate the error to the action handler.
        self.assertIsNone(real.session.access_token)
        self.app.go.assert_awaited_with('auth')
        self.assertIn('Você saiu deste aparelho', self.app.notice.call_args.args[0])

    async def test_logout_with_expired_token_is_silent(self):
        self.app, real = make_app()
        real.request.side_effect = ApiError('Entre novamente para continuar.', 401)
        self.app.prepare_navigation = AsyncMock(return_value=True)
        await self.app.logout()
        self.app.notice.assert_not_called()
        self.app.go.assert_awaited_with('auth')

    async def test_poll_backs_off_while_failing_and_resets_after_success(self):
        self.app, _ = make_app()
        self.app.generation = 1
        outcomes = [ApiError('x'), ApiError('x'), ApiError('x'), ApiError('x'), ApiError('x'), ApiError('x'), None, None]
        delays = []

        async def sleep(seconds):
            delays.append(seconds)

        async def callback():
            outcome = outcomes.pop(0)
            if not outcomes:
                self.app.generation = 2
            if outcome:
                raise outcome
        with patch('chargegrid_app.app.asyncio.sleep', new=sleep):
            await self.app.poll(callback, 5, 1)
        self.assertEqual(delays, [5, 10, 20, 40, POLL_BACKOFF_MAX, POLL_BACKOFF_MAX, POLL_BACKOFF_MAX, 5])
        # Only the first failure of a streak interrupts the user.
        self.assertEqual(self.app.notice.call_count, 1)

    async def test_hidden_app_does_not_poll_and_refreshes_immediately_when_shown(self):
        self.app, _ = make_app()
        calls = []

        async def callback():
            calls.append('poll')
        self.app.poll_callback, self.app.poll_interval = callback, 3600
        await self.app.lifecycle(SimpleNamespace(state=ft.AppLifecycleState.HIDE))
        self.assertTrue(self.app.backgrounded)
        self.app.generation = 1
        task = asyncio.create_task(self.app.poll(callback, 0.001, 1))
        await asyncio.sleep(0.05)  # Dozens of intervals elapse while hidden.
        self.app.generation = 2
        await task
        self.assertEqual(calls, [])
        await self.app.lifecycle(SimpleNamespace(state=ft.AppLifecycleState.SHOW))
        self.assertFalse(self.app.backgrounded)
        for _ in range(5):
            await asyncio.sleep(0)
        self.assertEqual(calls, ['poll'])  # Immediate, not after the 1 h interval.

    async def test_resize_without_width_change_skips_page_update(self):
        self.app, _ = make_app()
        self.app.root.content.width = 390
        self.app.page.update.reset_mock()
        await self.app.resize(None)
        self.app.page.update.assert_not_called()


class MapPerformanceTests(unittest.TestCase):
    def setUp(self):
        maps._map_cache.clear()
        maps._network_down_until = 0.0

    def tearDown(self):
        maps._map_cache.clear()
        maps._network_down_until = 0.0

    @staticmethod
    def tile():
        buffer = io.BytesIO()
        Image.new('RGB', (256, 256), (200, 210, 220)).save(buffer, format='PNG')
        return buffer.getvalue()

    def test_map_is_jpeg_cached_and_tiles_fetched_once(self):
        maps._tile_bytes.cache_clear()
        with patch.object(maps, '_fetch_bytes', return_value=self.tile()) as fetch, \
                patch.object(maps, '_TILE_CACHE_DIR', Path(os.devnull) / 'unwritable'):
            first = maps.build_map_png(-23.55, -46.63, [(-23.55, -46.63, '⚡')], width=720, height=497, zoom=16,
                                       center_glyph=None)
            downloads = fetch.call_count
            second = maps.build_map_png(-23.55, -46.63, [(-23.55, -46.63, '⚡')], width=720, height=497, zoom=16,
                                        center_glyph=None)
        maps._tile_bytes.cache_clear()
        self.assertIs(first, second)
        self.assertEqual(fetch.call_count, downloads)
        self.assertEqual(first[:3], b'\xff\xd8\xff')
        self.assertTrue(maps.map_data_uri(first).startswith('data:image/jpeg;base64,'))
        self.assertTrue(maps.map_data_uri(b'\x89PNG').startswith('data:image/png;base64,'))

    def test_offline_tiles_fail_fast_after_first_network_error(self):
        maps._tile_bytes.cache_clear()
        with patch.object(maps, '_fetch_bytes', side_effect=OSError('offline')) as fetch, \
                patch.object(maps, '_TILE_CACHE_DIR', Path(os.devnull) / 'unwritable'):
            with self.assertRaises(RuntimeError):
                maps.build_map_png(10, 10, [], width=300, height=200, zoom=16, center_glyph=None)
            attempts = fetch.call_count
            with self.assertRaises(RuntimeError):
                maps.build_map_png(11, 11, [], width=300, height=200, zoom=16, center_glyph=None)
        maps._tile_bytes.cache_clear()
        self.assertGreaterEqual(attempts, 1)
        self.assertEqual(fetch.call_count, attempts)  # No new download while the network is down.


class DemoCouponTests(unittest.IsolatedAsyncioTestCase):
    async def test_coupon_code_is_case_insensitive(self):
        api = DemoApi()
        await api.login(DEMO_EMAIL, DEMO_PASSWORD)
        stations = await api.request('GET', 'operator/stations')
        point = next(p for s in stations['items'] for p in s['connectors'] if p['available'])
        session = await api.request('POST', 'charging-sessions', {
            'public_code': point['public_code'], 'presence_code': DEMO_PRESENCE_CODE,
            'max_duration_minutes': 10, 'coupon_code': 'demo10'}, key='k1')
        self.assertEqual(session['discount_percent'], 10)
        created = await api.request('POST', 'coupons', {
            'code': 'verao', 'description': '', 'discount_percent': 5,
            'valid_until': '2999-01-01T00:00:00+00:00'})
        self.assertEqual(created['code'], 'VERAO')
        with self.assertRaises(ApiError) as duplicate:
            await api.request('POST', 'coupons', {
                'code': 'Verao', 'description': '', 'discount_percent': 5,
                'valid_until': '2999-01-01T00:00:00+00:00'})
        self.assertEqual(duplicate.exception.status, 409)
        await api.close()


if __name__ == '__main__':
    unittest.main()


class DeferredContentTests(unittest.IsolatedAsyncioTestCase):
    def make_app(self):
        return SimpleNamespace(page=SimpleNamespace(update=Mock()), generation=1, tasks=set(), closed=False)

    async def test_fast_content_is_inline_without_placeholder(self):
        from chargegrid_app.ui.deferred import fill_when_ready
        app, box = self.make_app(), ft.Container()

        async def ready():
            return ft.Text('Mapa')
        await fill_when_ready(app, box, ready, placeholder=ft.Text('Carregando'))
        self.assertEqual(box.content.value, 'Mapa')
        self.assertEqual(app.tasks, set())

    async def test_slow_map_shows_skeleton_then_swaps_in_place(self):
        from chargegrid_app.ui.deferred import fill_when_ready, skeleton
        app, box, release = self.make_app(), ft.Container(), asyncio.Event()

        async def slow():
            await release.wait()
            return ft.Text('Mapa')
        placeholder = skeleton(120)
        await fill_when_ready(app, box, slow, placeholder=placeholder, wait=0.01)
        self.assertIs(box.content, placeholder)  # The screen paints without waiting for tiles.
        release.set()
        for _ in range(3):
            await asyncio.sleep(0)
        self.assertEqual(box.content.value, 'Mapa')
        app.page.update.assert_called_once()
        self.assertEqual(app.tasks, set())

    async def test_late_map_never_lands_on_another_screen(self):
        from chargegrid_app.ui.deferred import fill_when_ready
        app, box, release = self.make_app(), ft.Container(), asyncio.Event()

        async def slow():
            await release.wait()
            return ft.Text('Mapa')
        await fill_when_ready(app, box, slow, placeholder=ft.Text('Carregando'), wait=0.01)
        app.generation = 2  # User navigated away.
        release.set()
        for _ in range(3):
            await asyncio.sleep(0)
        self.assertEqual(box.content.value, 'Carregando')
        app.page.update.assert_not_called()


@patch.object(driver_package, 'DISCONTINUED', False)  # código guardado do Modo motorista descontinuado
class DriverScreenRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_screen_opens_offline_from_local_profile_without_battery_question(self):
        import tempfile

        from chargegrid_app.preferences import DriverProfileStore
        from chargegrid_app.screens import driver
        from test_driver_mode import DriverApp, battery, fields
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'FLET_APP_STORAGE_DATA': directory}):
            DriverProfileStore().save({'vehicle': {'preset': 'byd_seal'}, 'preferences': {'shift_start': '06:00'},
                                       'soc_percent': 0})

            async def offline(method, path, body=None, **kwargs):
                raise ApiError('Não foi possível conectar com segurança.')
            app = DriverApp(SimpleNamespace(is_demo=False, request=offline, new_key=lambda: 'k'))
            screen = await driver.build(app)  # Used to fail the whole screen.
            form = fields(screen)
            self.assertIsNone(battery(screen))  # The battery is hidden now (services.vehicle_state).
            self.assertEqual(form['Início do turno'].value, '06:00')
            self.assertIn('Sem conexão', app.notices[0])


class ChargingPresetTests(unittest.IsolatedAsyncioTestCase):
    async def test_duration_presets_fill_the_field_within_point_limit(self):
        from test_charging_wizard import WizardApp, fields, limits_screen, texts
        app = WizardApp()  # Point limit: 10 min.
        screen = await limits_screen(app)
        self.assertIn('Máx. 10 min', texts(screen))
        self.assertNotIn('15 min', texts(screen))  # Never offer more than the point allows.
        from test_behavior import click
        await click(screen, 'Máx. 10 min')(None)
        self.assertEqual(fields(screen)['Duração máxima (min)'].value, '10')
        self.assertEqual(app.charging_draft['duration_minutes'], '10')


class CouponAndFilterUxTests(unittest.IsolatedAsyncioTestCase):
    async def test_coupon_form_uppercases_code_and_empty_list_explains_next_step(self):
        from chargegrid_app.screens import coupons
        from test_behavior import HandlerApp, click
        from test_consumer_flows import fields, texts
        app = HandlerApp()
        app.api.request.return_value = {'items': [], 'total': 0}
        screen = await coupons.build(app)
        self.assertIn('Nenhum cupom disponível agora', texts(screen))
        app.profile = {'operator_enabled': True}
        app.api.request.return_value = {'items': [], 'total': 0}
        form = await coupons.build(app, manage=True, create=True)
        fields(form)['Código'].value = ' verao10 '
        fields(form)['Descrição'].value = 'Verão'
        await click(form, 'Salvar cupom')(None)
        method, path, body = app.api.request.call_args.args
        self.assertEqual((method, path, body['code']), ('POST', 'coupons', 'VERAO10'))

    async def test_filter_summary_uses_connector_label_not_internal_key(self):
        from unittest.mock import AsyncMock as Async

        from chargegrid_app.screens import stations
        from test_consumer_flows import texts
        from test_station_ux import open_filters, sheet_app
        app = sheet_app()
        app.api.request.return_value = {'items': [], 'total': 0}
        with patch.object(stations, 'station_map_widget', new=Async(return_value=ft.Text('Map'))):
            screen = await stations.build(app, connector_type='type2')
        sheet = open_filters(app, screen)
        self.assertIn('Ativos: Tipo 2', texts(sheet))
        self.assertNotIn('type2', texts(sheet))


class OperatorDashboardTests(unittest.IsolatedAsyncioTestCase):
    async def test_counts_are_pluralised_and_energy_is_unambiguous(self):
        from chargegrid_app.screens import operator
        from test_behavior import HandlerApp
        from test_consumer_flows import texts
        app = HandlerApp()
        app.api = DemoApi()
        await app.api.login(DEMO_EMAIL, DEMO_PASSWORD)
        screen = await operator.build(app)
        copy = texts(screen)
        self.assertIn('Suas Estações', copy)
        self.assertIn('Marginal Pinheiros', copy)
        self.assertIn('Online - Conectores livres', copy)
        self.assertNotIn('1 pontos', copy)
        await app.api.close()


class ExpansionTileLayoutTests(unittest.TestCase):
    def test_expanded_content_is_not_centred(self):
        """Flet centres expanded controls by default: buttons shrank to the middle of the card."""
        missing = []
        for path in SOURCE.rglob('*.py'):
            if path.name == 'chat.py':
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                if (isinstance(node, ast.Call) and getattr(node.func, 'attr', None) == 'ExpansionTile'
                        and 'expanded_cross_axis_alignment' not in {k.arg for k in node.keywords}):
                    missing.append(f'{path.name}:{node.lineno}')
        self.assertEqual(missing, [])
