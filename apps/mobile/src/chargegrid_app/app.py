import asyncio
import contextlib
import hashlib
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path

import flet as ft

from . import api_cache
from .api_client import ApiClient, ApiError
from .config import demo_enabled, packaged_version
from .navigation import (
    SCREENS,
    active_tab,
    can_manage,
    editable_controls,
    form_route,
    nav_visible,
    parent_route,
    resolve_route,
    screen_params,
    tab_entries,
)
from .preferences import Preferences
from .services import prefetch, updates
from .services.driver_profile import apply_signup_vehicle
from .ui import design, motion, theme
from .ui.components import button, title

ASSETS_DIR = str(Path(__file__).resolve().parents[2] / 'assets')
POLL_BACKOFF_MAX = 60
UPDATE_RECHECK_SECONDS = 15 * 60
_log = logging.getLogger(__name__)


# Recarga em andamento e reserva decidem o próximo passo (iniciar, encerrar, cancelar) com o estado
# do servidor: sempre montadas da rede, nunca do cache.
NETWORK_ROUTES = ('auth', 'charging', 'reservations')


def stale_allowed(route, data):
    """Telas que podem abrir com a última resposta conhecida e se atualizar logo em seguida.

    O Modo motorista, o vínculo de equipamento, o cadastro guiado, o formulário de ponto e o fim do
    assistente de reserva (revisão e pagamento) abrem só com respostas frescas (segundos)."""
    if route in NETWORK_ROUTES or route == 'driver':
        return False
    if route == 'operator' and any(data.get(key) for key in ('claim', 'onboarding', 'connector_id')):
        return False
    if route == 'booking':
        # Escolhas do assistente (conector, horário, cobrança) sim; revisão, pagamento e conclusão, não.
        try:
            return int(data.get('step') or 1) < 6
        except (TypeError, ValueError):
            return False
    return True


class ChargeGridApp:
    def __init__(self, page):
        self.page, self.api = page, ApiClient()
        self.preferences = Preferences()
        self.dark_mode = self.preferences.load()
        theme.set_dark(self.dark_mode)
        self.route, self.profile, self.data = 'auth', {}, {}
        self.browsing_mode = 'consumer'
        self.charging_draft = None
        self.planning_intent = None
        self.chat_messages = []
        self.chat_draft = ''
        self._chat_account_id = None
        self.building_generation = None
        self.tasks, self.poll_task = set(), None
        self.generation = 0
        self.closed = False
        self.active_actions = set()
        self.form_baseline = []
        self.prompting = False
        self.reduced_motion = False
        self.loading_task = None
        self.backgrounded = False
        self.poll_callback = None
        self.poll_interval = None
        self.last_refresh_at = None
        self.refresh_failed = False
        self.refresh_in_progress = False
        self.refresh_task = None
        self.silent_next = False
        self.superseded_polls = set()
        self.freshness_text = ft.Text(size=11, color=theme.GRAY_TEXT, expand=True)
        self.freshness_retry = ft.TextButton('Atualizar', on_click=self.retry_refresh,
                                            style=ft.ButtonStyle(color=theme.TEXT_COLOR))
        self.freshness = ft.Semantics(content=ft.Container(
            ft.Row([self.freshness_text, self.freshness_retry], spacing=8),
            padding=ft.Padding.symmetric(horizontal=20, vertical=2)), visible=False)
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
            'Inter': '/Inter-Regular.ttf',
            'InterMedium': '/Inter-Medium.ttf',
            'InterSemiBold': '/Inter-SemiBold.ttf',
            'InterBold': '/Inter-Bold.ttf',
            'BarlowCondensedMedium': '/BarlowCondensed-Medium.ttf',
            'Barlow': '/Barlow-Regular.ttf',
            'BarlowMedium': '/Barlow-Medium.ttf',
            'BarlowSemiBold': '/Barlow-SemiBold.ttf',
            'BarlowCondensed': '/BarlowCondensed-Bold.ttf',
            'BarlowCondensedBold': '/BarlowCondensed-Bold.ttf',
            'BarlowCondensedSemiBold': '/BarlowCondensed-SemiBold.ttf',
        }
        page.window.width, page.window.height = 400, 800
        page.add(self.root)
        page.on_connect = self.connect
        page.on_disconnect = self.disconnect
        page.on_resize = self.resize
        page.on_app_lifecycle_state_change = self.lifecycle

    async def resize(self, event):
        if self.root.content:
            width = min(self.page.width or 400, 520 if self.route == 'auth' else 600)
            if width == self.root.content.width:
                return  # Height-only resizes (keyboard, rotation bars) need no diff.
            self.root.content.width = width
            self.page.update()

    def link(self, route, **data):
        async def handler(e):
            if (route, data) == (self.route, self.data):
                return
            if await self.prepare_navigation():
                await self.go(route, **data)
        return handler

    async def native_back(self, event):
        destination = parent_route(self.route, self.data, getattr(self, 'browsing_mode', 'consumer'))
        if not await self.prepare_navigation():
            await event.control.confirm_pop(False)
            return
        await event.control.confirm_pop(destination is None)
        if destination:
            await self.go(destination[0], **destination[1])

    async def back(self, event=None):
        destination = parent_route(self.route, self.data, getattr(self, 'browsing_mode', 'consumer'))
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
            view.can_pop = parent_route(self.route, self.data, self.browsing_mode) is None and not self.active_actions
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

    async def offer_update(self, current=None, delay=2.5, manual=False):
        """Android: se o GitHub tiver um APK mais novo, oferece o download.

        Roda ao abrir o app e ao voltar do segundo plano (no máximo a cada ``UPDATE_RECHECK_SECONDS``;
        o Android costuma só retomar o app, sem abrir de novo). ``manual`` (Conta → Verificar
        atualização) sempre consulta e avisa também quando não há versão nova.
        """
        current = current or packaged_version()
        self.update_checked_at = time.monotonic()
        info = await updates.available_update(current)
        if not info or self.closed:
            if manual:
                self.notice(f'Você já está na versão mais recente ({current}).' if current else
                            'Não foi possível identificar a versão instalada.')
            return False
        await asyncio.sleep(delay)  # deixa a primeira tela terminar de abrir
        while self.prompting:  # não cobre o diálogo "Descartar alterações?"
            await asyncio.sleep(1)

        async def download(event=None):
            self.page.pop_dialog()
            await ft.UrlLauncher().launch_url(info['url'])
            self.notice('Download iniciado. Ao terminar, toque na notificação e instale por cima: '
                        'sua conta e seus dados continuam.')

        def later(event=None):
            self.page.pop_dialog()
        size = f" ({info['size_mb']} MB)" if info.get('size_mb') else ''
        body = [ft.Text(f"A versão {info['version']} do ChargeGrid está disponível{size}. "
                        f"Você está na {current}.")]
        if info.get('notes'):
            body.append(ft.Text(info['notes'][:600], size=12, color=theme.GRAY_TEXT))
        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text('Atualização disponível'),
            content=ft.Column(body, tight=True, spacing=10, scroll=ft.ScrollMode.AUTO),
            actions=[ft.TextButton('Agora não', on_click=later), ft.TextButton('Baixar', on_click=download)],
            data='app-update'))
        return True

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
        if asyncio.current_task() in (self.poll_task, self.refresh_task) and (self.active_actions or self.prompting):
            return
        self.cancel_screen()
        theme.set_dark(self.dark_mode)
        motion.set_reduced(self.reduced_motion)
        route, data = resolve_route(route, data)
        if route not in SCREENS:
            route, data = 'home', {}
        if route != 'auth' and not self.api.session.access_token:
            route, data = 'auth', {}
        if route == 'auth' and not self.api.session.access_token:
            self.profile = {}
            self.reset_account_ui()
            self.reset_account_operations()
        # Revalidação: a mesma tela, remontada com as respostas novas, sem barra de carregamento nem transição.
        silent, self.silent_next = self.silent_next, False
        self.generation += 1
        generation = self.generation
        self.building_generation = generation
        self.route, self.data = route, data
        self.sync_back()
        self.poll_callback = None
        self.poll_interval = None
        self.last_refresh_at = None
        self.refresh_failed = False
        self.freshness.visible = False
        self.refresh_in_progress = False
        self.freshness_retry.disabled = False
        self.form_baseline = []
        self.loading.visible = False
        if not silent:
            self.scene.content.disabled = True
            self.loading_task = asyncio.create_task(self.delayed_loading(generation))
            self.page.update()
        task = asyncio.current_task()
        self.tasks.add(task)
        # Montagem da tela: respostas guardadas valem (cache); polls e ações continuam indo à rede.
        caching = isinstance(getattr(self.api, 'cache', None), api_cache.ResponseCache) and route not in NETWORK_ROUTES
        reads = None
        try:
            with (api_cache.reading(stale_ok=stale_allowed(route, data)) if caching
                  else contextlib.nullcontext()) as reads:
                body = await SCREENS[route](self, **screen_params(data))
        except ApiError as exc:
            if exc.status == 401 and not self.api.session.access_token and route != 'auth':
                await self.go('auth')
                return
            body = ft.Column([title('Não foi possível carregar', str(exc)), button('Tentar novamente', self.action(lambda: self.go(route, **data)))])
        finally:
            self.tasks.discard(task)
            if self.building_generation == generation:
                self.building_generation = None
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
        # STANDARD density keeps 48 px touch targets on web/desktop builds too
        # (Flutter defaults those platforms to COMPACT, shrinking buttons by 8 px).
        authenticated = bool(self.api.session.access_token) and route != 'auth'
        show_nav = authenticated and nav_visible(route, data) and getattr(self, 'hide_nav_for_route', None) != route
        # A faixa da barra de gestos (fora da área segura) mostra o fundo da página: metade de cima com a cor
        # do conteúdo e metade de baixo com a cor da barra inferior, sem mudar o layout.
        self.page.decoration = ft.BoxDecoration(gradient=ft.LinearGradient(
            begin=ft.Alignment(0, -1), end=ft.Alignment(0, 1),
            colors=[theme.BG_COLOR, theme.BG_COLOR, theme.NAV_BG, theme.NAV_BG],
            stops=[0, 0.5, 0.5, 1])) if show_nav else None
        # Barra de gestos/botões do Android com a cor da barra inferior (não a do fundo da página).
        self.page.theme = ft.Theme(color_scheme_seed=theme.RED,font_family='Inter',
                                   visual_density=ft.VisualDensity.STANDARD,
                                   system_overlay_style=ft.SystemOverlayStyle(
                                       system_navigation_bar_color=theme.NAV_BG if show_nav else theme.BG_COLOR,
                                       system_navigation_bar_divider_color=theme.NAV_BG if show_nav else theme.BG_COLOR,
                                       system_navigation_bar_icon_brightness=(
                                           ft.Brightness.LIGHT if theme.is_dark() else ft.Brightness.DARK)))
        if authenticated:
            header = design.app_header(self)
            nav = (design.bottom_nav(self, tab_entries(self.browsing_mode), active_tab(route, data, self.browsing_mode))
                   if show_nav else ft.Container(height=0))
            content = ft.SafeArea(ft.Column([
                header, self.freshness,
                ft.Container(body, padding=ft.Padding(left=design.GUTTER, right=design.GUTTER, top=26, bottom=16),
                             expand=True),
                nav,
            ], expand=True, spacing=0, horizontal_alignment=ft.CrossAxisAlignment.STRETCH), expand=True)
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
        durations = self.scene.duration, self.scene.reverse_duration
        if silent:
            self.scene.duration = self.scene.reverse_duration = 0
        self.scene.content = ft.Container(content, expand=True)
        if self.poll_callback:
            self.mark_refresh(True)
        self.page.update()
        self.scene.duration, self.scene.reverse_duration = durations
        if self.poll_callback:
            self.start_poll()
        if authenticated and isinstance(self.page, ft.Page):
            asyncio.create_task(self.refresh_notification_badge(generation))
        if reads is not None and reads.served and not silent:
            self.track(asyncio.create_task(self.revalidate_screen(generation, reads.served)))
        if authenticated and not silent:
            try:
                prefetch.after_render(self, route, data)
            except Exception:  # noqa: BLE001 - busca antecipada nunca derruba a navegação
                _log.debug('Busca antecipada falhou', exc_info=True)

    def track(self, task):
        """Tarefa da tela atual: a próxima navegação a cancela."""
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def revalidate_screen(self, generation, reads):
        """A tela abriu com respostas guardadas: confere na rede e atualiza só se algo mudou.

        Com poll, a própria atualização da tela troca só os controles que mudaram (lendo as respostas
        que acabaram de chegar). Sem poll, ou se o poll não cobre o que mudou, a tela é remontada em
        silêncio, exceto se houver formulário editado, ação em andamento ou diálogo aberto."""
        try:
            changed = await self.api.revalidate(reads)
        except Exception:  # noqa: BLE001 - sem rede: a tela segue com o último estado e o poll tenta de novo
            return
        if not changed or generation != self.generation or self.closed:
            return
        callback = self.poll_callback
        if callback:
            if self.active_actions or self.prompting or self.refresh_in_progress:
                return  # o poll em andamento (ou o próximo) traz o estado novo
            self.refresh_in_progress = True
            seen = None
            try:
                with api_cache.reading() as mode:
                    await callback()
                seen = mode.seen
            except ApiError:
                pass
            finally:
                if generation == self.generation:
                    self.refresh_in_progress = False
            if generation != self.generation or self.closed:
                return
            if seen is not None and set(changed) <= seen:
                self.mark_refresh(True)
                self.page.update()
                return
        if self.active_actions or self.prompting or self.dirty_form() or generation != self.generation:
            return
        self.silent_next = True
        await self.go(self.route, **self.data)

    async def refresh_notification_badge(self, generation=None):
        """Acende a bolinha do sino só quando há aviso não lido (nunca bloqueia a tela)."""
        from .services import notifications
        try:
            # Reaproveita as respostas frescas que a tela acabou de buscar (sem um segundo pedido igual).
            with api_cache.reading():
                items = await notifications.collect(self)
            has_unread = bool(notifications.unread(self, items))
        except Exception:  # noqa: BLE001 - aviso é opcional
            return
        self.has_unread_notifications = has_unread
        dot = getattr(self, 'notification_dot', None)
        if dot is None or (generation is not None and generation != self.generation) or dot.visible == has_unread:
            return
        dot.visible = has_unread
        try:
            dot.update()
        except (RuntimeError, AssertionError, AttributeError):
            pass

    def set_poll(self, callback, interval):
        self.poll_callback, self.poll_interval = callback,interval
        if self.building_generation is None and not self.closed:
            self.start_poll()

    def start_poll(self, immediate=False):
        if self.poll_task and self.poll_task is not asyncio.current_task():
            self.poll_task.cancel()
        elif self.poll_task:
            self.superseded_polls.add(self.poll_task)
        self.poll_task = asyncio.create_task(
            self.poll(self.poll_callback, self.poll_interval, self.generation, immediate=immediate))

    async def lifecycle(self, event):
        """Pause polling in background; refresh immediately when shown again."""
        state = getattr(event, 'state', None)
        hidden = state in (ft.AppLifecycleState.HIDE, ft.AppLifecycleState.PAUSE)
        resumed = state in (ft.AppLifecycleState.SHOW, ft.AppLifecycleState.RESUME)
        was_hidden = self.backgrounded
        if hidden:
            self.backgrounded = True
        elif resumed:
            self.backgrounded = False
            # Voltar ao app não executa main() de novo: confere atualização aqui também.
            if (was_hidden and getattr(self.page, 'platform', None) == ft.PagePlatform.ANDROID and not self.closed
                    and time.monotonic() - getattr(self, 'update_checked_at', 0) >= UPDATE_RECHECK_SECONDS):
                self.update_task = asyncio.create_task(self.offer_update(delay=0.5))
            if was_hidden and self.poll_callback and not self.closed and self.building_generation is None:
                self.start_poll(immediate=True)

    def mark_refresh(self, success):
        """Receipt time of a service query is never a device measurement time."""
        if success:
            self.last_refresh_at = datetime.now().astimezone()
        self.refresh_failed = not success
        stamp = self.last_refresh_at.strftime('%H:%M:%S') if self.last_refresh_at else 'não disponível'
        self.freshness_text.value = (
            f'Consulta atualizada às {stamp}' if success else
            f'Não conseguimos atualizar — exibindo o último estado conhecido. Última consulta: {stamp}.')
        self.freshness_text.color = theme.GRAY_TEXT if success else theme.ERROR
        self.freshness_retry.content = ft.Text('Atualizar' if success else 'Tentar novamente')
        self.freshness_retry.style.color = theme.TEXT_COLOR
        # Announce failure/recovery, without reading every routine polling tick.
        self.freshness.live_region = not success
        # Routine successful polls should not occupy permanent screen space.
        self.freshness.visible = not success

    async def retry_refresh(self, event=None):
        if not self.poll_callback or self.refresh_in_progress or self.active_actions or self.prompting:
            return
        generation, callback = self.generation, self.poll_callback
        task = asyncio.current_task()
        self.tasks.add(task)
        self.refresh_in_progress = True
        self.refresh_task = task
        self.freshness_retry.disabled = True
        self.page.update()
        try:
            await callback()
            if generation == self.generation and not self.closed:
                recovered = self.refresh_failed
                self.mark_refresh(True)
                self.freshness.live_region = recovered
        except ApiError as exc:
            if generation == self.generation and not self.closed:
                if exc.status == 401 and not self.api.session.access_token:
                    await self.go('auth')
                else:
                    self.mark_refresh(False)
        finally:
            self.tasks.discard(task)
            if self.refresh_task is task:
                self.refresh_task = None
            if generation == self.generation:
                self.refresh_in_progress = False
                self.freshness_retry.disabled = False
            if generation == self.generation and not self.closed:
                self.page.update()

    async def poll(self, callback, interval, generation, immediate=False):
        failed = False
        failures = 0
        delay = 0 if immediate else interval
        while self.generation == generation and not self.closed:
            await asyncio.sleep(delay)
            superseded = getattr(self, 'superseded_polls', set())
            if asyncio.current_task() in superseded:
                # A tela trocou o poll (``set_poll`` de dentro do próprio poll): este laço para aqui,
                # senão os dois continuariam consultando.
                superseded.discard(asyncio.current_task())
                return
            delay = interval
            if self.active_actions or self.prompting or getattr(self, 'refresh_in_progress', False):
                continue
            if getattr(self, 'backgrounded', False):
                # Hidden app: no network or battery use; resuming refreshes at once.
                continue
            self.refresh_in_progress = True
            try:
                await callback()
                # A tela pode espaçar ou apressar o próprio poll (``poll_interval``), ex.: sem recarga ativa.
                if getattr(self, 'poll_callback', None) is callback and getattr(self, 'poll_interval', None):
                    interval = delay = self.poll_interval
                if generation == self.generation and hasattr(self, 'mark_refresh'):
                    self.mark_refresh(True)
                    self.freshness.live_region = failed
                    self.page.update()
                failed = False
                failures = 0
            except ApiError as exc:
                # Adaptive polling: back off while the server or network is
                # failing (5 s → 10 → 20 → 40 → 60 s), reset after a success.
                failures += 1
                delay = min(POLL_BACKOFF_MAX, interval * 2 ** min(failures, 4))
                if generation != self.generation or self.closed:
                    return
                if exc.status == 401 and not self.api.session.access_token:
                    await self.go('auth')
                    return
                if not failed:
                    self.notice(str(exc))
                if hasattr(self, 'mark_refresh'):
                    self.mark_refresh(False)
                    self.page.update()
                failed = True
            finally:
                if generation == self.generation:
                    self.refresh_in_progress = False

    async def signed_in(self, destination=None):
        self.reset_account_ui()
        self.reset_account_operations()
        if not destination:
            # O Início do motorista sai junto com o perfil (em paralelo), não depois dele.
            prefetch.fetch(self, prefetch.consumer_home())
        self.profile = await self.api.request('GET','me')
        await apply_signup_vehicle(self.api, self.profile)
        self.browsing_mode = 'vendor' if can_manage(self.profile) and not getattr(self.api,'is_demo',False) else 'consumer'
        destination = destination or 'home'
        await self.go(destination)

    async def login(self, email, password):
        from .demo import DEMO_EMAIL, DemoApi
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
        self.reset_account_ui()
        self.reset_account_operations()

    def reset_account_operations(self):
        """Never reuse a previous account's operation keys or historical IDs."""
        self.api.operation_keys.clear()
        self.api.charging_operation_sessions.clear()
        self.api.last_session_id = None
        self.api.last_reservation_id = None

    def reset_account_ui(self):
        """Discard account-scoped conversation and unfinished forms at auth boundaries."""
        self.charging_draft = None
        self.planning_intent = None
        self.chat_messages = []
        self.chat_draft = ''
        self._chat_account_id = None
        self._chat_pending = None
        self.driver_state = {}

    async def enter_demo(self):
        if not demo_enabled():
            raise ApiError('Demonstração indisponível neste aplicativo.')
        from .demo import DEMO_EMAIL, DEMO_PASSWORD
        await self.login(DEMO_EMAIL, DEMO_PASSWORD)
        await self.signed_in()

    async def switch_mode(self, mode):
        if mode not in ('vendor', 'consumer') or (mode == 'vendor' and not can_manage(self.profile)):
            return
        if await self.prepare_navigation():
            self.browsing_mode = mode
            await self.go('home')

    async def logout(self):
        if not await self.prepare_navigation():
            return
        self.cancel_screen()
        offline = False
        try:
            await self.api.request('POST','auth/logout')
        except ApiError as exc:
            # Leaving must always work locally; an expired token or a network
            # failure only means the server could not revoke it right now.
            offline = exc.status not in (401, 403)
        finally:
            self.api.session.clear()
            self.reset_account_operations()
            if getattr(self.api, 'is_demo', False):
                await self.api.close()
                self.api = ApiClient()
                self.dark_mode = self.preferences.load()
            self.profile = {}
            self.reset_account_ui()
            await self.go('auth')
        if offline:
            self.notice('Você saiu deste aparelho. Sem conexão para avisar o servidor; o acesso expira sozinho.')

    async def disconnect(self, e):
        self.closed = True
        self.cancel_screen()
        self.reset_account_ui()
        await self.api.close()

    async def connect(self, e):
        if not self.closed:
            return
        # Tokens existem somente em memória e o cliente HTTP anterior foi
        # fechado no disconnect. Uma reconexão começa com cliente e login
        # novos, evitando reaproveitar transporte ou autenticação inválidos.
        self.api = ApiClient()
        self.reset_account_ui()
        self.profile = {}
        self.dark_mode = self.preferences.load()
        self.browsing_mode = 'consumer'
        self.closed = False
        self.form_baseline = []
        await self.go('auth')


def _capture_params(raw):
    """``{"step": "3", "x": "true"}`` -> typed values (ints/bools/JSON) for the screenshot harness."""
    try:
        values = json.loads(raw or '{}')
    except ValueError:
        return {}
    result = {}
    for key, value in (values if isinstance(values, dict) else {}).items():
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                pass
        result[str(key)] = value
    return result


async def _capture_setup(app, raw):
    """Demo requests that put the account in the state to capture (never runs outside the demo capture)."""
    try:
        steps = json.loads(raw) if raw else []
    except ValueError:
        return
    owned = None
    for method, path, *rest in steps if isinstance(steps, list) else []:
        if '@owned_station' in path:
            if owned is None:
                listing = await app.api.request('GET', 'operator/stations')
                owned = ((listing or {}).get('items') or [{}])[0].get('id')
            path = path.replace('@owned_station', str(owned))
        await app.api.request(method, path, rest[0] if rest else None)


async def capture_boot(app):
    """Screenshot harness hook (tools/screen_capture.py): demo account straight to a route.

    Only active when ``CHARGEGRID_CAPTURE_ROUTE`` is set AND the demo is enabled.
    ``CHARGEGRID_CAPTURE_MODE`` consumer|vendor, ``CHARGEGRID_CAPTURE_PARAMS`` JSON object,
    ``CHARGEGRID_CAPTURE_THEME`` dark|light. A param value ``@first_station`` becomes the first
    station id and ``@first_connector`` the first connector id of the demo account.
    ``CHARGEGRID_CAPTURE_SETUP`` (optional) is a JSON list of ``[method, path, body]`` demo requests run
    before navigating (``@owned_station`` in the path = the vendor's first station), e.g. the simulated
    station traffic: ``[["POST", "stations/@owned_station/demo-traffic", {}]]``.
    """
    route = os.getenv('CHARGEGRID_CAPTURE_ROUTE')
    if not route or not demo_enabled():
        return False
    from .demo import DEMO_EMAIL, DEMO_PASSWORD
    await app.login(DEMO_EMAIL, DEMO_PASSWORD)
    app.profile = await app.api.request('GET', 'me')
    app.browsing_mode = 'vendor' if os.getenv('CHARGEGRID_CAPTURE_MODE') == 'vendor' else 'consumer'
    app.dark_mode = os.getenv('CHARGEGRID_CAPTURE_THEME', 'dark') != 'light'
    theme.set_dark(app.dark_mode)
    await _capture_setup(app, os.getenv('CHARGEGRID_CAPTURE_SETUP'))
    params = _capture_params(os.getenv('CHARGEGRID_CAPTURE_PARAMS'))
    if '@first_station' in params.values() or '@first_connector' in params.values():
        async def listing(path):
            try:
                result = await app.api.request('GET', path)
            except Exception:  # not allowed for this account type: fall back below
                return []
            return (result.get('items') or result.get('stations') or []) if isinstance(result, dict) else (result or [])
        stations = (await listing('operator/stations') if app.browsing_mode == 'vendor' else []) or await listing('stations') \
            or await listing('operator/stations')
        station = (stations or [{}])[0]
        connector = ((station.get('connectors') or [{}]) or [{}])[0]
        params = {key: (station.get('id') if value == '@first_station' else
                        connector.get('id') if value == '@first_connector' else value)
                  for key, value in params.items()}
    await app.go(route, **params)
    return True


async def main(page: ft.Page):
    if page.platform in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS):
        await page.set_allowed_device_orientations([ft.DeviceOrientation.PORTRAIT_UP])
    app = ChargeGridApp(page)
    warm_up = getattr(app.api, 'warm_up', None)
    if warm_up is not None and not os.getenv('CHARGEGRID_CAPTURE_ROUTE'):
        # Conexão e função do servidor acordadas enquanto a tela de login aparece.
        app.warm_task = asyncio.create_task(warm_up())
    await app.configure_motion()
    try:
        booted = await capture_boot(app)
    except Exception:  # harness only: show the error on screen instead of hanging on the splash
        import traceback
        detail = traceback.format_exc()
        print(detail, flush=True)
        page.controls.clear()
        page.add(ft.SafeArea(ft.Text('Erro na captura:\n' + detail[-1800:], size=9, color='#FF6B6B', selectable=True)))
        page.update()
        return
    if not booted:
        await app.go('auth')
    if page.platform == ft.PagePlatform.ANDROID and not booted:
        app.update_task = asyncio.create_task(app.offer_update())
