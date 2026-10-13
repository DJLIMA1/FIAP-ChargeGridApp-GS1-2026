import flet as ft

from chargegrid_app.ui import theme
from chargegrid_app.ui.kpi import error_state


class View:
    """Seção do dashboard: mostra skeleton imediatamente e preenche em ``load``."""

    poll_seconds = None

    def __init__(self, dash, **data):
        self.dash, self.data = dash, data
        self.body = ft.Column(spacing=20, scroll=ft.ScrollMode.AUTO, expand=True,
                              horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    def control(self):
        self.body.controls = self.skeleton()
        return self.body

    def skeleton(self):
        return []

    async def load(self):
        raise NotImplementedError

    async def refresh(self):
        await self.load()

    def show_error(self, message):
        self.body.controls = [error_state(message, self.dash.action(self.retry))]

    async def retry(self):
        self.body.controls = self.skeleton()
        self.dash.update()
        await self.load()
        self.dash.update()

    def set(self, controls):
        self.body.controls = controls


def section(title_text, content, *, subtitle=None, actions=None, col=None):
    """Cartão de seção com título (e ações à direita)."""
    header = [ft.Text(title_text, size=16, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR,
                      font_family='BarlowSemiBold', expand=True)]
    if actions:
        header.extend(actions)
    controls = [ft.Row(header, vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=False)]
    if subtitle:
        controls.append(ft.Text(subtitle, size=12, color=theme.GRAY_TEXT))
    controls.append(content)
    box = ft.Container(ft.Column(controls, spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                       bgcolor=theme.WHITE, border_radius=12, padding=16,
                       border=ft.Border.all(1, theme.LIGHT_GRAY))
    if col is not None:
        box.col = col
    return box


def embed(form, width=640):
    """Formulário do app dentro do dashboard: a rolagem fica a cargo da seção."""
    if isinstance(form, ft.Column):
        form.scroll = None
        form.expand = False
    return ft.Row([ft.Container(form, width=width)], vertical_alignment=ft.CrossAxisAlignment.START)
