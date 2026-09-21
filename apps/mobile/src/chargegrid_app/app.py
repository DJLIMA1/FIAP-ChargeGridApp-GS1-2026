import asyncio
import hashlib
from pathlib import Path

import flet as ft

from .api_client import ApiClient, ApiError
from .navigation import SCREENS, TABS, editable_controls, form_route, parent_route
from .preferences import Preferences
from .ui import motion, theme
from .ui.components import button, title

ASSETS_DIR = str(Path(__file__).resolve().parents[2] / 'assets')


class ChargeGridApp:
    def __init__(self, page):
        self.page, self.api = page, ApiClient()
        self.preferences = Preferences()
        self.dark_mode = self.preferences.load()
        theme.set_dark(self.dark_mode)
        self.route, self.profile, self.data = 'auth', {}, {}
        self.tasks, self.poll_task = set(), None
        self.generation = 0
        self.closed = False
        self.active_actions = set()
        self.form_baseline = []
        self.prompting = False
        self.reduced_motion = False
        self.loading_task = None
        self.poll_callback = None
        self.poll_interval = None
        self.root = ft.Container(expand=True, alignment=ft.Alignment(0,0))
        self.scene = motion.switcher(ft.Column([
            ft.Icon(ft.Icons.EV_STATION, size=40, color=theme.RED),
            ft.Text('ChargeGrid', size=26, color=theme.TEXT_COLOR, font_family='BarlowSemiBold'),
        ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER), expand=True)
        self.loading = ft.Container(top=0, left=0, right=0, visible=False)
        self.root.content = ft.Container(ft.Stack([self.scene, self.loading], expand=True),
                                         width=min(page.width or 400, 520), expand=True)
        page.title, page.padding, page.spacing = 'ChargeGrid', 0, 0
        page.bgcolor = theme.BG_COLOR
        page.theme_mode = ft.ThemeMode.DARK if self.dark_mode else ft.ThemeMode.LIGHT
        page.fonts = {
            'Barlow': '/Barlow-Regular.ttf',
            'BarlowMedium': '/Barlow-Medium.ttf',
            'BarlowSemiBold': '/Barlow-SemiBold.ttf',
            'BarlowCondensed': '/BarlowCondensed-Bold.ttf',
            'BarlowCondensedSemiBold': '/BarlowCondensed-SemiBold.ttf',
        }
        page.window.width, page.window.height = 400, 800
        page.add(self.root)
        page.on_connect = self.connect
        page.on_disconnect = self.disconnect
        page.on_resize = self.resize

    async def resize(self, event):
        if self.root.content:
            self.root.content.width = min(self.page.width or 400, 520 if self.route == 'auth' else 600)
            self.page.update()

    def link(self, route, **data):
        async def handler(e):
            if (route, data) == (self.route, self.data):
                return
            if await self.prepare_navigation():
                await self.go(route, **data)
        return handler

    async def native_back(self, event):
        destination = parent_route(self.route, self.data)
        if not await self.prepare_navigation():
            await event.control.confirm_pop(False)
            return
        await event.control.confirm_pop(destination is None)
        if destination:
            await self.go(destination[0], **destination[1])

    async def back(self, event=None):
        destination = parent_route(self.route, self.data)
        if destination and await self.prepare_navigation():
            await self.go(destination[0], **destination[1])

    async def configure_motion(self):
        # Read the OS preference; a failed capability probe conservatively disables motion.
        try:
            self.semantics = ft.SemanticsService()
            features = await asyncio.wait_for(self.semantics.get_accessibility_features(), 1)
            self.reduced_motion = features.disable_animations or features.reduce_motion
        except (TimeoutError, RuntimeError, ValueError):
            self.reduced_motion = True
        motion.set_reduced(self.reduced_motion)
        self.scene.duration = motion.duration(220)
        self.scene.reverse_duration = motion.duration(120)

    @staticmethod
    def field_digest(control):
        # Avoid keeping an extra plaintext copy of passwords in navigation state.
        return hashlib.sha256(str(control.value).encode()).digest()

    def mark_saved(self):
        self.form_baseline = [(control, self.field_digest(control)) for control, _ in self.form_baseline]

    def dirty_form(self):
        return any(self.field_digest(control) != original for control, original in self.form_baseline)

    def sync_back(self):
        if getattr(self.page, 'views', None):
            view = self.page.views[0]
            view.can_pop = parent_route(self.route, self.data) is None and not self.active_actions
            view.on_confirm_pop = self.native_back

    async def prepare_navigation(self):
        if self.active_actions - {asyncio.current_task()}:
            self.notice('Aguarde a operação terminar antes de sair desta tela.')
            return False
        if self.prompting:
            return False
        if not self.dirty_form():
            return True
        self.prompting = True
        decision = asyncio.get_running_loop().create_future()

        async def choose(value):
            if not decision.done():
                decision.set_result(value)
            self.page.pop_dialog()

        async def keep(event):
            await choose(False)

        async def discard(event):
            await choose(True)

        def dismissed(event):
            if not decision.done():
                decision.set_result(False)

        dialog = ft.AlertDialog(
            modal=True, title=ft.Text('Descartar alterações?'),
            content=ft.Text('Há campos editados nesta tela. Se continuar, o que ainda não foi salvo será descartado.'),
            actions=[ft.TextButton('Continuar editando', on_click=keep), ft.TextButton('Descartar', on_click=discard)],
            on_dismiss=dismissed,
        )
        self.page.show_dialog(dialog)
        try:
            return await decision
        finally:
            self.prompting = False

    def action(self, operation):
        busy = False
        async def handler(e):
            nonlocal busy
            if busy:
                return
            if self.active_actions:
                self.notice('Aguarde a operação atual terminar.')
                return
            busy = True
            theme.set_dark(self.dark_mode)
            motion.set_reduced(self.reduced_motion)
            control = getattr(e, 'control', None)
            if isinstance(control, (ft.Container, ft.TextButton)):
                control.disabled = True
                control.opacity = 0.65
                if isinstance(control, ft.Container):
                    control.scale = 0.985 if not self.reduced_motion else 1
                self.page.update()
            task = asyncio.current_task()
            self.tasks.add(task)
            self.active_actions.add(task)
            self.sync_back()
            self.page.update()
            generation = self.generation
            try:
                await operation()
            except ApiError as exc:
                if generation == self.generation:
                    if exc.status == 401 and not self.api.session.access_token:
                        await self.go('auth')
                    self.notice(str(exc))
            except (ValueError, TypeError):
                self.notice('Confira os números e os campos preenchidos.')
            finally:
                busy = False
                self.active_actions.discard(task)
                self.sync_back()
                if control is not None and generation == self.generation and not self.closed:
                    control.disabled = False
                    control.opacity = 1
                    if isinstance(control, ft.Container):
                        control.scale = 1
                if not self.closed:
                    self.page.update()
                self.tasks.discard(task)
        return handler

    def notice(self, message):
        self.page.show_dialog(ft.SnackBar(ft.Text(message)))

    def cancel_screen(self):
        current = asyncio.current_task()
        for task in tuple(self.tasks):
            if task is not current:
                task.cancel()
        if self.poll_task and self.poll_task is not current:
            self.poll_task.cancel()
        self.poll_task = None
        if self.loading_task and self.loading_task is not current:
            self.loading_task.cancel()
        self.loading_task = None

    async def delayed_loading(self, generation):
        await asyncio.sleep(0.18)
        if generation == self.generation and not self.closed:
            self.loading.content = (
                ft.Text('Carregando…', text_align=ft.TextAlign.CENTER, color=theme.GRAY_TEXT)
                if self.reduced_motion else ft.ProgressBar(color=theme.RED, bgcolor=theme.LIGHT_GRAY, bar_height=3,
                                                           semantics_label='Carregando tela')
            )
            self.loading.visible = True
            self.page.update()

    async def go(self, route, **data):
        # A polling status change must not cancel an in-flight start/stop/save.
        if asyncio.current_task() is self.poll_task and (self.active_actions or self.prompting):
            return
        self.cancel_screen()
        theme.set_dark(self.dark_mode)
        motion.set_reduced(self.reduced_motion)
        if route not in SCREENS:
            route, data = 'home', {}
        if route != 'auth' and not self.api.session.access_token:
            route, data = 'auth', {}
        self.generation += 1
        generation = self.generation
        self.route, self.data = route, data
        self.sync_back()
        self.poll_callback = None
        self.poll_interval = None
        self.scene.content.disabled = True
        self.form_baseline = []
        self.loading.visible = False
        self.loading_task = asyncio.create_task(self.delayed_loading(generation))
        self.page.update()
        task = asyncio.current_task()
        self.tasks.add(task)
        try:
            body = await SCREENS[route](self, **data)
        except ApiError as exc:
            if exc.status == 401 and not self.api.session.access_token and route != 'auth':
                await self.go('auth')
                return
            body = ft.Column([title('Não foi possível carregar', str(exc)), button('Tentar novamente', self.action(lambda: self.go(route, **data)))])
        finally:
            self.tasks.discard(task)
        if generation != self.generation or self.closed:
            return
        if self.loading_task:
            self.loading_task.cancel()
            self.loading_task = None
        self.loading.visible = False
        if form_route(route, data):
            self.form_baseline = [(control, self.field_digest(control)) for control in editable_controls(body)]
        if isinstance(body, ft.Column):
            body.horizontal_alignment = ft.CrossAxisAlignment.STRETCH
            body.expand = True
        self.page.bgcolor = theme.BG_COLOR
        self.page.theme_mode = ft.ThemeMode.DARK if theme.is_dark() else ft.ThemeMode.LIGHT
        self.page.theme = ft.Theme(color_scheme_seed=theme.RED,font_family='Barlow')
        authenticated = bool(self.api.session.access_token) and route != 'auth'
        nav = []
        if authenticated:
            entries = TABS
            icons = {'home':ft.Icons.HOME_OUTLINED,'stations':ft.Icons.EV_STATION_OUTLINED,'history':ft.Icons.HISTORY,'profile':ft.Icons.PERSON_OUTLINE,'help':ft.Icons.HELP_OUTLINE}
            items = []
            for name, label in entries:
                active = name == route or (name == 'stations' and route in ('stations','reservations','charging'))
                items.append(ft.Container(ft.Column([
                    ft.Container(ft.Icon(icons[name],size=22,color=theme.RED if active else theme.GRAY_TEXT),
                                 bgcolor=theme.LIGHT_GRAY if active else None, border_radius=12,
                                 padding=ft.Padding(left=14,right=14,top=3,bottom=3), animate=motion.animation()),
                    ft.Text(label,size=10,color=theme.RED if active else theme.GRAY_TEXT),
                ],horizontal_alignment=ft.CrossAxisAlignment.CENTER,alignment=ft.MainAxisAlignment.CENTER,spacing=2,tight=True),padding=8,on_click=self.link(name),ink=True,expand=True))
            nav = [ft.Container(ft.Row(items,spacing=0),height=64,bgcolor=theme.WHITE,border=ft.Border(top=ft.BorderSide(1,theme.LIGHT_GRAY)))]

        if authenticated:
            back_button = [ft.IconButton(icon=ft.Icons.ARROW_BACK_ROUNDED, icon_color=theme.TEXT_COLOR,
                                        tooltip='Voltar', on_click=self.back)] if parent_route(route, data) else []
            header = ft.Container(
                ft.Row([
                    ft.Row([*back_button,ft.Image(src='/icon.png',width=24,height=24),ft.Text('ChargeGrid',size=18,weight=ft.FontWeight.BOLD,color=theme.TEXT_COLOR,font_family='BarlowCondensed')],spacing=5),
                    ft.TextButton('Sair',on_click=self.action(self.logout),style=ft.ButtonStyle(color=theme.TEXT_COLOR)),
                ],alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                height=52,padding=ft.Padding(left=20,right=12,top=4,bottom=4),bgcolor=theme.BG_COLOR,
            )
            content = ft.SafeArea(ft.Column([header,ft.Container(body,padding=ft.Padding(left=20,right=20,top=16,bottom=16),expand=True),*nav],expand=True,spacing=0),expand=True)
        else:
            content = ft.SafeArea(
                ft.Container(
                    body,
                    padding=ft.Padding(left=24,right=24,top=24,bottom=24),
                    expand=True,
                    alignment=ft.Alignment(0,0),
                ),
                expand=True,
            )
        max_width = 520 if not authenticated else 600
        self.root.content.width = min(self.page.width or 400,max_width)
        self.scene.content = ft.Container(content, expand=True)
        self.page.update()
        if self.poll_callback:
            self.poll_task = asyncio.create_task(self.poll(self.poll_callback,self.poll_interval,generation))

    def set_poll(self, callback, interval):
        self.poll_callback, self.poll_interval = callback,interval

    async def poll(self, callback, interval, generation):
        failed = False
        while self.generation == generation and not self.closed:
            await asyncio.sleep(interval)
            if self.active_actions or self.prompting:
                continue
            try:
                await callback()
                failed = False
            except ApiError as exc:
                if exc.status == 401 and not self.api.session.access_token:
                    await self.go('auth')
                    return
                if not failed:
                    self.notice(str(exc))
                failed = True

    async def signed_in(self, destination=None):
        self.profile = await self.api.request('GET','me')
        destination = destination or ('operator' if self.profile.get('account_type') == 'vendor' and self.profile.get('operator_enabled') else 'home')
        await self.go(destination)

    async def logout(self):
        if not await self.prepare_navigation():
            return
        self.cancel_screen()
        try:
            await self.api.request('POST','auth/logout')
        finally:
            self.api.session.clear()
            self.api.operation_keys.clear()
            self.api.charging_operation_sessions.clear()
            self.api.last_session_id = None
            self.api.last_reservation_id = None
            self.profile = {}
            await self.go('auth')

    async def disconnect(self, e):
        self.closed = True
        self.cancel_screen()
        await self.api.close()

    async def connect(self, e):
        if not self.closed:
            return
        # Tokens existem somente em memória e o cliente HTTP anterior foi
        # fechado no disconnect. Uma reconexão começa com cliente e login
        # novos, evitando reaproveitar transporte ou autenticação inválidos.
        self.api = ApiClient()
        self.profile = {}
        self.closed = False
        self.form_baseline = []
        await self.go('auth')


async def main(page: ft.Page):
    if page.platform in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS):
        await page.set_allowed_device_orientations([ft.DeviceOrientation.PORTRAIT_UP])
    app = ChargeGridApp(page)
    await app.configure_motion()
    await app.go('auth')
