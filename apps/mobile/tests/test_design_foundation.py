"""Foundation of the redesign: theme tokens, design kit, route contract, shell hooks, demo identity."""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import flet as ft

from chargegrid_app import app as app_module
from chargegrid_app.demo import DemoApi
from chargegrid_app.navigation import (
    SCREENS,
    active_tab,
    nav_visible,
    parent_route,
    screen_params,
    tab_entries,
)
from chargegrid_app.ui import design, theme

NEW_ROUTES = ('notifications', 'wallet', 'payout', 'booking', 'tariffs', 'station_admin')


def walk(control):
    yield control
    content = getattr(control, 'content', None)
    if content is not None and not isinstance(content, str):
        yield from walk(content)
    for child in getattr(control, 'controls', None) or []:
        yield from walk(child)


def texts(control):
    return [str(item.value) for item in walk(control) if isinstance(item, ft.Text)]


class FakeApp:
    def __init__(self, demo=True):
        async def request(*args, **kwargs):
            return {}
        self.api = SimpleNamespace(is_demo=demo, request=request)
        self.profile = {'name': 'Ana'}
        self.browsing_mode = 'consumer'
        self.back = lambda event=None: None

    def link(self, *args, **kwargs):
        return lambda event=None: None


class ThemeTests(unittest.TestCase):
    def test_dark_palette_matches_reference_samples(self):
        theme.set_dark(True)
        self.assertEqual(
            (theme.BG_COLOR, theme.CARD, theme.NAV_BG, theme.TILE, theme.SEGMENT_OFF, theme.WARN_BG, theme.RED),
            ('#1F1F1F', '#1A1A1A', '#191919', '#2B2B2B', '#343434', '#2D1D20', '#D72B32'))
        self.assertEqual((theme.BTN_PRIMARY, theme.BTN_PRIMARY_FG), ('#FFFFFF', '#000000'))

    def test_light_theme_defines_every_token_of_the_dark_one(self):
        self.assertEqual(set(theme.LIGHT), set(theme.DARK))


class RouteContractTests(unittest.TestCase):
    def test_new_routes_registered_and_accept_arbitrary_params(self):
        for route in NEW_ROUTES:
            self.assertIn(route, SCREENS)
            if route == 'station_admin':  # needs a real station: covered by test_station_admin.py
                continue
            control = asyncio.run(SCREENS[route](FakeApp(), step=2, station_id='s', page='power', anything='x'))
            self.assertIsInstance(control, ft.Column)

    def test_back_contract(self):
        self.assertEqual(parent_route('notifications', {}), ('home', {}))
        self.assertEqual(parent_route('wallet', {}), ('profile', {}))
        self.assertEqual(parent_route('wallet', {'step': 3}), ('wallet', {'step': 2}))
        self.assertEqual(parent_route('wallet', {'step': 1, 'origin': 'home'}), ('home', {}))
        self.assertEqual(parent_route('booking', {'step': 2, 'station_id': 's'}), ('booking', {'step': 1, 'station_id': 's'}))
        self.assertEqual(parent_route('booking', {'step': 1, 'station_id': 's'}), ('stations', {'station_id': 's'}))
        self.assertEqual(parent_route('payout', {}, 'vendor'), ('home', {}))
        self.assertEqual(parent_route('tariffs', {'station_id': 's'}, 'vendor'), ('station_admin', {'station_id': 's'}))
        self.assertEqual(parent_route('tariffs', {}, 'vendor'), ('home', {}))
        # Editor de horário -> lista de horários -> Tarifa -> posto.
        self.assertEqual(parent_route('tariffs', {'station_id': 's', 'page': 'schedule', 'interval': 0}, 'vendor'),
                         ('tariffs', {'station_id': 's', 'page': 'schedule'}))
        self.assertEqual(parent_route('tariffs', {'station_id': 's', 'page': 'schedule'}, 'vendor'),
                         ('tariffs', {'station_id': 's'}))
        self.assertEqual(parent_route('station_admin', {'station_id': 's', 'page': 'power'}, 'vendor'),
                         ('station_admin', {'station_id': 's'}))
        self.assertEqual(parent_route('station_admin', {'station_id': 's'}, 'vendor'), ('operator', {}))
        self.assertIsNone(parent_route('home', {}))

    def test_active_tabs(self):
        self.assertEqual(active_tab('booking', {}, 'consumer'), 'stations')
        self.assertEqual(active_tab('wallet', {}, 'consumer'), 'profile')
        self.assertEqual(active_tab('payout', {}, 'vendor'), 'operator')
        self.assertEqual(active_tab('tariffs', {}, 'vendor'), 'operator')
        self.assertEqual(active_tab('station_admin', {}, 'vendor'), 'operator')
        self.assertIsNone(active_tab('notifications', {}, 'consumer'))

    def test_tabs_follow_reference_labels(self):
        self.assertEqual([label for _, label, _ in tab_entries('consumer')],
                         ['Início', 'Recarga', 'Histórico', 'Chat', 'Conta'])
        self.assertEqual([label for _, label, _ in tab_entries('vendor')],
                         ['Início', 'Estações', 'Histórico', 'Chat', 'Conta'])

    def test_nav_hidden_only_for_registration_wizard_or_explicit_flag(self):
        self.assertTrue(nav_visible('operator', {'station_id': 's'}))
        self.assertFalse(nav_visible('operator', {'onboarding': True}))
        self.assertFalse(nav_visible('booking', {'nav': False}))
        self.assertEqual(screen_params({'nav': False, 'step': 1}), {'step': 1})

    def test_vendor_home_uses_build_vendor_when_present(self):
        from chargegrid_app.screens import home

        async def vendor(app, **_):
            return 'vendor-home'
        app = FakeApp()
        app.browsing_mode = 'vendor'
        with patch.object(home, 'build_vendor', vendor, create=True):
            self.assertEqual(asyncio.run(SCREENS['home'](app)), 'vendor-home')


class DesignKitTests(unittest.TestCase):
    def setUp(self):
        theme.set_dark(True)

    def test_page_scaffold_has_title_back_progress_and_pinned_footer(self):
        back = object
        page = design.page(ft.Text('body'), title='Qual conector?', on_back=back, steps=4, step=2,
                           footer=design.primary_button('Continuar'))
        flat = list(walk(page))
        segments = [c for c in flat if isinstance(c, ft.Container) and c.height == 3]
        self.assertEqual(len(segments), 4)
        self.assertEqual([c.bgcolor for c in segments], [theme.BTN_PRIMARY] * 2 + [theme.SEGMENT_OFF] * 2)
        self.assertIn('Qual conector?', texts(page))
        self.assertIn('Continuar', texts(page))

    def test_buttons_follow_reference_colors(self):
        primary, secondary, danger = (design.primary_button('A'), design.secondary_button('B'), design.danger_button('C'))
        self.assertEqual((primary.bgcolor, secondary.bgcolor, danger.bgcolor),
                         ('#FFFFFF', '#252525', '#D72B32'))
        self.assertEqual(design.primary_button('A', disabled=True).on_click, None)

    def test_list_row_variants(self):
        clicked = []
        row = design.list_row('Villa Lobos', 'Pinheiros', trailing='R$ 1,89/kWh', on_click=lambda e: clicked.append(e))
        self.assertEqual(texts(row), ['Villa Lobos', 'Pinheiros', 'R$ 1,89/kWh'])
        self.assertEqual(row.bgcolor, theme.CARD)
        selected = design.list_row('x', selected=True, chevron=False)
        self.assertIsNotNone(selected.border)
        self.assertIsNone(design.list_row('x', plain=True).bgcolor)

    def test_radio_segmented_warning_success_input(self):
        self.assertIsNotNone(design.radio_option('CCS2', 'x', selected=True).border)
        values = []
        segmented = design.segmented([('on', 'Ativa'), ('off', 'Inativa')], 'on', values.append)
        self.assertEqual([c.bgcolor for c in segmented.content.controls], [theme.BTN_PRIMARY, None])
        warning = design.warning_box('Aviso')
        self.assertEqual(warning.bgcolor, theme.WARN_BG)
        self.assertEqual(texts(design.success_state('Pronto', 'Sub')), ['Pronto', 'Sub'])
        field = design.labeled_input('Nome', 'Ana').controls[1]
        self.assertIsInstance(field, ft.TextField)
        self.assertEqual((field.value, field.fill_color), ('Ana', theme.INPUT_BG))

    def test_money_and_number_use_condensed_font(self):
        self.assertEqual(design.money_text(214.8).value, 'R$ 214,80')
        self.assertEqual(design.money_text('R$ 2485,90').value, 'R$ 2485,90')
        self.assertEqual(design.num('1').font_family, design.FONT_NUM)

    def test_shell_header_and_nav(self):
        app = FakeApp()
        header = design.app_header(app)
        self.assertEqual(len([c for c in walk(header) if isinstance(c, ft.Image)]), 2)  # logo + demo avatar
        nav = design.bottom_nav(app, tab_entries('vendor'), 'operator')
        self.assertEqual(texts(nav), ['Início', 'Estações', 'Histórico', 'Chat', 'Conta'])
        selected = [c for c in walk(nav) if isinstance(c, ft.Semantics) and c.selected]
        self.assertEqual(len(selected), 1)

    def test_real_account_gets_initial_not_demo_photo(self):
        avatar = design.avatar(FakeApp(demo=False), 25)
        self.assertEqual(texts(avatar), ['A'])

    def test_demo_note_only_in_demo(self):
        self.assertEqual(len(texts(design.demo_note(FakeApp(demo=True)))), 1)
        self.assertFalse(design.demo_note(FakeApp(demo=False)).visible)


class CaptureHookTests(unittest.TestCase):
    def test_params_are_typed(self):
        raw = json.dumps({'step': '3', 'flag': 'true', 'station_id': 'abc', 'raw': 4})
        self.assertEqual(app_module._capture_params(raw), {'step': 3, 'flag': True, 'station_id': 'abc', 'raw': 4})
        self.assertEqual(app_module._capture_params('not json'), {})

    def test_hook_inactive_without_env_or_without_demo(self):
        app = SimpleNamespace()
        with patch.dict('os.environ', {}, clear=False):
            self.assertFalse(asyncio.run(app_module.capture_boot(app)))
        with patch.dict('os.environ', {'CHARGEGRID_CAPTURE_ROUTE': 'home'}), \
                patch.object(app_module, 'demo_enabled', return_value=False):
            self.assertFalse(asyncio.run(app_module.capture_boot(app)))


class DemoIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_demo_profile_matches_reference_persona(self):
        demo = DemoApi()
        await demo.login('demo@chargegrid.example', 'demo1234')
        profile = await demo.request('GET', 'me')
        self.assertEqual((profile['name'], profile['phone']), ('João Pedro Sousa', '(11) 91234-5678'))


if __name__ == '__main__':
    unittest.main()
