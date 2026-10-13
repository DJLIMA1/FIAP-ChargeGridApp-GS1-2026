"""Dashboard web do proprietário de postos ChargeGrid (Flet).

Reaproveita do app: tema, componentes, tela de login, ``ApiClient``/``Session``,
conta demo, preferências e formulários de posto/ponto/cupom. Cálculos vêm de
``chargegrid_core``. Esta classe oferece a mesma interface mínima que as telas
do app esperam (``action``, ``link``, ``go``, ``notice``, ``set_poll``...).
"""

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path

import flet as ft

from chargegrid_app.api_client import ApiClient, ApiError
from chargegrid_app.config import demo_enabled
from chargegrid_app.navigation import can_manage
from chargegrid_app.preferences import Preferences
from chargegrid_app.screens import auth
from chargegrid_app.ui import motion, theme
from chargegrid_app.ui.components import brand, button, card, title
from chargegrid_app.ui.tables import period_selector

from .state import SECTIONS, DashboardState
from .views import VIEWS

_PACKAGED_ASSETS = Path(__file__).resolve().parents[1] / 'assets'
# Fontes, ícone e marca são os mesmos do app (apps/mobile/assets); um build
# empacotado pode trazer uma cópia em apps/dashboard/assets.
ASSETS_DIR = str(_PACKAGED_ASSETS if _PACKAGED_ASSETS.is_dir()
                 else Path(__file__).resolve().parents[2] / 'mobile' / 'assets')
logger = logging.getLogger('chargegrid_dashboard')
ICONS = {
    'overview': (ft.Icons.DASHBOARD_OUTLINED, ft.Icons.DASHBOARD),
    'stations': (ft.Icons.EV_STATION_OUTLINED, ft.Icons.EV_STATION),
    'sessions': (ft.Icons.RECEIPT_LONG_OUTLINED, ft.Icons.RECEIPT_LONG),
    'coupons': (ft.Icons.LOCAL_OFFER_OUTLINED, ft.Icons.LOCAL_OFFER),
    'insights': (ft.Icons.AUTO_AWESOME_OUTLINED, ft.Icons.AUTO_AWESOME),
}
FONTS = {
    'Barlow': '/Barlow-Regular.ttf',
    'BarlowMedium': '/Barlow-Medium.ttf',
    'BarlowSemiBold': '/Barlow-SemiBold.ttf',
    'BarlowCondensed': '/BarlowCondensed-Bold.ttf',
    'BarlowCondensedBold': '/BarlowCondensed-Bold.ttf',
    'BarlowCondensedSemiBold': '/BarlowCondensed-SemiBold.ttf',
}


def dashboard_preferences():
    """Mesmo formato do app, em arquivo próprio: o tema do painel não altera o do app."""
    storage = Path(os.environ.get('FLET_APP_STORAGE_DATA') or Path.home() / '.chargegrid')
    return Preferences(storage / 'dashboard-preferences.json')


class DashboardApp:
    def __init__(self, page, api=None, preferences=None):
        self.page = page
        self.api = api or ApiClient()
        self.preferences = preferences or dashboard_preferences()
        self.dark_mode = self.preferences.load()
        self.reduced_motion = False
        self.state = DashboardState()
        self.profile, self.stations, self.data = {}, [], {}
        self.route = 'auth'
        self.generation = 0
        self.closed = False
        self.active_actions = set()
        self.prompting = False
        self.view = None
        self.view_task = None
        self.poll_task = None
        self.poll_callback = None
        self.last_refresh = None
        self.content = ft.Container(expand=True)
        self.status_text = ft.Text('', size=11, color=theme.GRAY_TEXT)
        self.root = ft.Container(expand=True)
        theme.set_dark(self.dark_mode)
        page.title = 'ChargeGrid · Painel do proprietário'
        page.padding, page.spacing = 0, 0
        page.fonts = FONTS
        page.on_resize = self.resize
        page.on_disconnect = self.disconnect
        page.on_connect = self.reconnect
        page.on_close = self.close
        self.apply_page_theme()
        page.add(self.root)

    # ------------------------------------------------------------ utilidades
    def sync_context(self):
        """Eventos do Flet rodam em contextos distintos; reaplica tema/movimento."""
        theme.set_dark(self.dark_mode)
        motion.set_reduced(self.reduced_motion)

    def apply_page_theme(self):
        self.page.bgcolor = theme.BG_COLOR
        self.page.theme_mode = ft.ThemeMode.DARK if self.dark_mode else ft.ThemeMode.LIGHT
        self.page.theme = ft.Theme(color_scheme_seed=theme.RED, font_family='Barlow')
        self.page.dark_theme = ft.Theme(color_scheme_seed=theme.RED, font_family='Barlow')

    def update(self):
        if not self.closed:
            self.page.update()

    def notice(self, message):
        self.page.show_dialog(ft.SnackBar(ft.Text(message)))

    def action(self, operation):
        """Mesmo contrato de ``ChargeGridApp.action``: erros viram aviso, sem duplo clique."""
        busy = False

        async def handler(event=None):
            nonlocal busy
            if busy:
                return
            busy = True
            self.sync_context()
            control = getattr(event, 'control', None)
            if isinstance(control, (ft.Container, ft.TextButton, ft.IconButton)):
                control.disabled = True
                self.update()
            task = asyncio.current_task()
            self.active_actions.add(task)
            try:
                await operation()
            except ApiError as exc:
                if exc.status == 401 and not self.api.session.access_token:
                    await self.go('auth')
                self.notice(str(exc))
            except (ValueError, TypeError) as exc:
                self.notice(str(exc) or 'Confira os campos preenchidos.')
            finally:
                busy = False
                self.active_actions.discard(task)
                if control is not None:
                    control.disabled = False
                self.update()
        return handler

    def link(self, route, **data):
        async def handler(event=None):
            await self.go(route, **data)
        return handler

    def set_poll(self, callback, interval):
        """Formulários do app (ex.: restauração de fábrica) pedem polling curto."""
        self.poll_callback = (callback, interval)

    def mark_saved(self):
        pass

    async def prepare_navigation(self):
        return not self.active_actions - {asyncio.current_task()}

    # ------------------------------------------------------------ navegação
    async def go(self, route, **data):
        """Rotas do app mapeadas para seções do dashboard (reuso de telas)."""
        self.sync_context()
        if route == 'auth' or not self.api.session.access_token:
            await self.show_auth(**(data if route == 'auth' else {}))
            return
        if route == 'operator':
            if data.get('claim') or data.get('onboarding'):
                self.notice('Vincule e configure novos equipamentos pelo app ChargeGrid (QR do painel).')
                return
            await self.open_section('stations', **{k: v for k, v in data.items()
                                                   if k in ('station_id', 'connector_id', 'connector')})
            return
        if route == 'history':
            if data.get('station_id'):
                self.state.station_id = data['station_id']
            await self.open_section('sessions')
            return
        if route == 'coupons':
            await self.open_section('coupons', **{k: v for k, v in data.items() if k in ('create', 'coupon')})
            return
        await self.open_section(route if route in VIEWS else 'overview', **data)

    async def show_auth(self, **data):
        self.stop_view()
        self.route = 'auth'
        self.generation += 1
        self.apply_page_theme()
        body = await auth.build(self, **data)
        intro = ft.Column([
            ft.Text('PAINEL DO PROPRIETÁRIO', size=12, color=theme.ACCENT, weight=ft.FontWeight.BOLD,
                    font_family='BarlowCondensedSemiBold'),
            ft.Text('Acompanhe receita, energia, ocupação e alertas dos seus postos. Use a mesma conta do app.',
                    size=13, color=theme.GRAY_TEXT),
        ], spacing=4)
        self.root.content = ft.Container(
            ft.Container(ft.Column([intro, body], spacing=16, scroll=ft.ScrollMode.AUTO,
                                   horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                         width=440, padding=28, bgcolor=theme.WHITE, border_radius=16),
            alignment=ft.Alignment(0, 0), expand=True, padding=16,
        )
        self.update()

    async def login(self, email, password):
        from chargegrid_app.demo import DEMO_EMAIL, DemoApi
        if email.strip().casefold() == DEMO_EMAIL:
            if not demo_enabled():
                raise ApiError('Use uma conta válida para entrar.')
            demo = DemoApi()
            await demo.login(email, password)
            await self.api.close()
            self.api = demo
        else:
            if getattr(self.api, 'is_demo', False):
                await self.api.close()
                self.api = ApiClient()
            await self.api.login(email, password)

    async def enter_demo(self):
        if not demo_enabled():
            raise ApiError('Demonstração indisponível neste ambiente.')
        from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD
        await self.login(DEMO_EMAIL, DEMO_PASSWORD)
        await self.signed_in()

    async def signed_in(self, destination=None):
        self.sync_context()
        self.profile = await self.api.request('GET', 'me')
        if not can_manage(self.profile) or not self.profile.get('operator_enabled'):
            self.show_restricted()
            return
        await self.load_stations()
        await self.open_section(destination or 'overview')

    async def load_stations(self):
        stations, offset = [], 0
        while True:
            result = await self.api.request('GET', 'operator/stations', params={'limit': 100, 'offset': offset})
            stations.extend(result['items'])
            offset += len(result['items'])
            if not result['items'] or offset >= result['total']:
                break
        self.stations = stations
        if self.state.station_id and self.state.station_id not in {s['id'] for s in stations}:
            self.state.station_id = None
        return stations

    def show_restricted(self):
        self.stop_view()
        self.route = 'restricted'
        vendor = can_manage(self.profile)
        message = ('Vincule seu primeiro equipamento pelo app ChargeGrid (QR de propriedade). '
                   'Depois disso, o painel mostra os indicadores dos seus postos.' if vendor else
                   'Este painel é exclusivo para proprietários e operadores de postos. '
                   'Motoristas acompanham recargas e histórico pelo app.')
        self.root.content = ft.Container(
            card([brand(compact=True),
                  title('Acesso restrito', message),
                  button('Sair', self.action(self.logout), secondary=True)], padding=28, width=460),
            alignment=ft.Alignment(0, 0), expand=True, padding=16,
        )
        self.update()

    async def logout(self):
        self.stop_view()
        try:
            await self.api.request('POST', 'auth/logout')
        except ApiError:
            pass
        finally:
            self.api.session.clear()
            if getattr(self.api, 'is_demo', False):
                await self.api.close()
                self.api = ApiClient()
            self.profile, self.stations, self.state = {}, [], DashboardState()
            await self.show_auth()

    async def disconnect(self, event=None):
        """Aba oculta/rede instável: pausa o polling; a sessão pode reconectar."""
        self.closed = True
        self.stop_view()

    async def reconnect(self, event=None):
        if not self.closed:
            return
        self.closed = False
        if self.route == 'section' and self.api.session.access_token:
            await self.open_section(self.state.section, **self.data)
        else:
            self.update()

    async def close(self, event=None):
        """Sessão encerrada pelo servidor: descarta tokens em memória."""
        self.closed = True
        self.stop_view()
        await self.api.close()

    # ------------------------------------------------------------ shell
    def stop_view(self):
        current = asyncio.current_task()
        for task in (self.view_task, self.poll_task):
            if task and task is not current and not task.done():
                task.cancel()
        self.view_task = self.poll_task = None
        self.poll_callback = None

    def compact(self):
        # Icons-only menu below 1100 px: on 1024 px screens the tables keep all columns visible.
        return (self.page.width or 1280) < 1100

    async def resize(self, event=None):
        if self.route != 'section':
            return
        collapsed = self.state.sidebar_collapsed or self.compact()
        if self.sidebar.data != collapsed:
            self.build_shell()
            self.update()

    def build_shell(self):
        self.sync_context()
        self.apply_page_theme()
        self.sidebar = self.build_sidebar()
        self.header = self.build_header()
        demo_bar = [ft.Container(
            ft.Text('DEMONSTRAÇÃO · postos, recargas e indicadores fictícios', size=11, color=theme.TEXT_COLOR,
                    text_align=ft.TextAlign.CENTER),
            padding=ft.Padding(left=12, right=12, top=6, bottom=6), bgcolor=theme.LIGHT_GRAY,
            alignment=ft.Alignment(0, 0),
        )] if getattr(self.api, 'is_demo', False) else []
        self.content.padding = ft.Padding(left=24, right=24, top=20, bottom=24)
        self.root.content = ft.Row([
            self.sidebar,
            ft.Column([*demo_bar, self.header, self.content], spacing=0, expand=True,
                      horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
        ], spacing=0, expand=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH)

    def build_sidebar(self):
        collapsed = self.state.sidebar_collapsed or self.compact()
        items = []
        for key, label in SECTIONS:
            active = key == self.state.section
            icon = ICONS[key][1 if active else 0]
            row = ft.Row([ft.Icon(icon, size=22, color=theme.ACCENT if active else theme.GRAY_TEXT)] +
                         ([] if collapsed else [ft.Text(label, size=14, color=theme.TEXT_COLOR,
                                                        weight=ft.FontWeight.BOLD if active else None)]),
                         spacing=12, alignment=ft.MainAxisAlignment.CENTER if collapsed else
                         ft.MainAxisAlignment.START)
            entry = ft.TextButton(
                content=row, on_click=self.link(key), tooltip=label if collapsed else None,
                style=ft.ButtonStyle(
                    padding=ft.Padding(left=12, right=12, top=12, bottom=12),
                    bgcolor=theme.LIGHT_GRAY if active else None,
                    shape=ft.RoundedRectangleBorder(radius=8), overlay_color=theme.LIGHT_GRAY,
                    side={ft.ControlState.FOCUSED: ft.BorderSide(2, theme.FOCUS)},
                ),
            )
            items.append(ft.Semantics(content=entry, selected=active, label=label, button=True))
        toggle = ft.IconButton(
            ft.Icons.MENU_OPEN if not collapsed else ft.Icons.MENU, icon_color=theme.TEXT_COLOR,
            tooltip='Recolher menu' if not collapsed else 'Expandir menu',
            on_click=self.toggle_sidebar, disabled=self.compact(),
        )
        mark = brand(compact=True)
        if collapsed:
            mark = mark.controls[0]
        sidebar = ft.Container(
            ft.Column([ft.Row([mark], alignment=ft.MainAxisAlignment.CENTER if collapsed else
                              ft.MainAxisAlignment.START), ft.Divider(color=theme.LIGHT_GRAY), *items,
                       ft.Container(expand=True), toggle],
                      spacing=6, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
            width=76 if collapsed else 240, bgcolor=theme.NAV_BG, padding=12,
        )
        sidebar.data = collapsed
        return sidebar

    def build_header(self):
        current = dict(SECTIONS).get(self.state.section, '')
        station_options = [ft.DropdownOption(key='__all__', text='Todos os postos')] + [
            ft.DropdownOption(key=s['id'], text=s['name']) for s in self.stations]
        station = ft.Dropdown(
            value=self.state.station_id or '__all__', options=station_options, width=230, dense=True,
            label='Posto', text_size=13, color=theme.TEXT_COLOR, bgcolor=theme.WHITE,
            on_select=self.choose_station,
        )
        dark = ft.IconButton(ft.Icons.LIGHT_MODE_OUTLINED if self.dark_mode else ft.Icons.DARK_MODE_OUTLINED,
                             tooltip='Tema claro' if self.dark_mode else 'Tema escuro',
                             icon_color=theme.TEXT_COLOR, on_click=self.toggle_theme)
        refresh = ft.IconButton(ft.Icons.REFRESH, tooltip='Atualizar agora', icon_color=theme.TEXT_COLOR,
                                on_click=self.manual_refresh)
        name = self.profile.get('name') or 'Proprietário'
        account = ft.PopupMenuButton(
            content=ft.Row([ft.Icon(ft.Icons.ACCOUNT_CIRCLE_OUTLINED, color=theme.TEXT_COLOR),
                            ft.Text(name, size=13, color=theme.TEXT_COLOR, max_lines=1)], spacing=6, tight=True),
            items=[ft.PopupMenuItem(content=ft.Text('Sair'), on_click=self.action(self.logout))],
            tooltip='Conta',
        )
        periods = period_selector(self.state.period, self.choose_period)
        custom_label = [ft.Text(self.state.period_label(), size=12, color=theme.GRAY_TEXT)] \
            if self.state.period == 'custom' else []
        uses_period = self.state.section in ('overview', 'sessions', 'insights')
        return ft.Container(
            ft.Column([
                ft.Row([
                    ft.Text(current, size=24, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR,
                            font_family='BarlowCondensed', expand=True),
                    self.status_text, refresh, dark, account,
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Row([*([periods, *custom_label] if uses_period else []), station], spacing=12, wrap=True,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ], spacing=10),
            padding=ft.Padding(left=24, right=16, top=16, bottom=12), bgcolor=theme.BG_COLOR,
            border=ft.Border(bottom=ft.BorderSide(1, theme.LIGHT_GRAY)),
        )

    async def open_section(self, section, **data):
        self.stop_view()
        self.sync_context()
        self.route = 'section'
        self.state.section = section if section in VIEWS else 'overview'
        self.generation += 1
        self.data = data
        self.build_shell()
        self.view = VIEWS[self.state.section](self, **data)
        self.content.content = self.view.control()
        self.update()
        generation = self.generation
        self.view_task = asyncio.create_task(self.load_view(generation))

    async def load_view(self, generation):
        try:
            await self.view.load()
            if generation == self.generation:
                self.mark_refresh(True)
        except asyncio.CancelledError:
            raise
        except ApiError as exc:
            if generation != self.generation:
                return
            if exc.status == 401 and not self.api.session.access_token:
                await self.go('auth')
                return
            self.view.show_error(str(exc))
            self.mark_refresh(False)
        except Exception:  # noqa: BLE001 - nunca deixar a seção presa no skeleton
            logger.exception('Falha ao carregar a seção %s', self.state.section)
            if generation != self.generation:
                return
            self.view.show_error('Erro inesperado ao montar esta seção. Tente novamente.')
            self.mark_refresh(False)
        if generation == self.generation and not self.closed:
            self.update()
            self.poll_task = asyncio.create_task(self.poll(generation))

    async def poll(self, generation):
        """Atualização leve: só a seção visível e somente se ela pedir polling."""
        while generation == self.generation and not self.closed:
            callback = self.poll_callback
            interval = callback[1] if callback else getattr(self.view, 'poll_seconds', None)
            if not interval:
                return
            await asyncio.sleep(interval)
            if generation != self.generation or self.active_actions:
                continue
            self.sync_context()
            try:
                await (callback[0]() if callback else self.view.refresh())
                self.mark_refresh(True)
            except ApiError as exc:
                if exc.status == 401 and not self.api.session.access_token:
                    await self.go('auth')
                    return
                self.mark_refresh(False)
            self.update()

    def mark_refresh(self, success):
        if success:
            self.last_refresh = datetime.now().astimezone()
        stamp = self.last_refresh.strftime('%H:%M:%S') if self.last_refresh else '—'
        self.status_text.value = (f'Atualizado às {stamp}' if success else
                                  f'Falha ao atualizar · último dado às {stamp}')
        self.status_text.color = theme.GRAY_TEXT if success else theme.ERROR

    # ------------------------------------------------------------ eventos
    async def choose_period(self, key):
        self.sync_context()
        if key == 'custom':
            picker = ft.DateRangePicker(
                start_value=self.state.custom_start, end_value=self.state.custom_end,
                first_date=datetime(2024, 1, 1), last_date=datetime.now(),
                help_text='Escolha o período', save_text='Aplicar', cancel_text='Cancelar',
                on_change=self.apply_custom_period,
            )
            self.page.show_dialog(picker)
            return
        self.state.period = key
        await self.open_section(self.state.section)

    async def apply_custom_period(self, event):
        self.sync_context()
        picker = event.control
        try:
            self.state.set_custom(picker.start_value, picker.end_value)
        except ValueError as exc:
            self.notice(str(exc))
            return
        await self.open_section(self.state.section)

    async def choose_station(self, event):
        value = event.control.value
        self.state.station_id = None if value in (None, '__all__') else value
        await self.open_section(self.state.section)

    async def toggle_theme(self, event=None):
        self.dark_mode = not self.dark_mode
        self.preferences.save(self.dark_mode)
        await self.open_section(self.state.section, **self.data)

    async def toggle_sidebar(self, event=None):
        self.state.sidebar_collapsed = not self.state.sidebar_collapsed
        self.sync_context()
        index = self.root.content.controls.index(self.sidebar)
        self.sidebar = self.build_sidebar()
        self.root.content.controls[index] = self.sidebar
        self.update()

    async def manual_refresh(self, event=None):
        if self.route == 'section':
            await self.open_section(self.state.section, **self.data)


async def main(page: ft.Page):
    dashboard = DashboardApp(page)
    try:
        semantics = ft.SemanticsService()
        features = await asyncio.wait_for(semantics.get_accessibility_features(), 1)
        dashboard.reduced_motion = features.disable_animations or features.reduce_motion
    except (TimeoutError, RuntimeError, ValueError, AttributeError):
        dashboard.reduced_motion = True
    await dashboard.go('auth')
