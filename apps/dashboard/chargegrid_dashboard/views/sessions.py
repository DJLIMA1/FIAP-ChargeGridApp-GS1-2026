import flet as ft

from chargegrid_app.api_client import ApiError
from chargegrid_app.ui import theme
from chargegrid_app.ui.components import badge
from chargegrid_app.ui.kpi import skeleton_block
from chargegrid_app.ui.tables import cell_badge, data_table, pagination
from chargegrid_core import analytics
from chargegrid_core.formatting import brl, duration, kwh

from ..state import (
    END_REASON_LABELS,
    RESERVATION_STATUS_LABELS,
    SESSION_STATUS_LABELS,
    SOURCE_LABELS,
    local_time,
)
from .base import View, section

PAGE_SIZE = 25
SESSION_COLUMNS = (('created_at', 'Criada em'), ('station', 'Posto'), ('public_code', 'Ponto'),
                   ('status', 'Status'), ('duration', 'Duração'), ('energy', 'Energia'), ('cost', 'Valor estimado'),
                   ('source', 'Origem'), ('end_reason', 'Término'))
RESERVATION_COLUMNS = (('created_at', 'Criada em'), ('station', 'Posto'), ('public_code', 'Ponto'),
                       ('status', 'Status'), ('expires_at', 'Expira em'), ('no_show', 'Compareceu?'))
STATUS_COLORS = {'completed': 'GREEN', 'consumed': 'GREEN', 'charging': 'BLUE', 'starting': 'BLUE',
                 'stopping': 'BLUE', 'confirmed': 'BLUE', 'pending_device': 'BLUE', 'interrupted': 'AMBER',
                 'cancelling': 'AMBER', 'cancelled': 'SLATE', 'expired': 'AMBER', 'failed': 'RED'}


def status_badge(status, labels):
    return cell_badge(badge(labels.get(status, status), getattr(theme, STATUS_COLORS.get(status, 'SLATE')), width=150))


def session_row(item):
    minutes = item.get('duration_minutes')
    return {
        'created_at': local_time(item.get('created_at')),
        'station': item.get('station_name'),
        'public_code': item.get('public_code'),
        'status': status_badge(item.get('status'), SESSION_STATUS_LABELS),
        'duration': duration(float(minutes)) if minutes is not None else '—',
        'energy': kwh(item.get('energy_kwh'), 2),
        'cost': brl(item.get('cost_estimate')),
        'source': SOURCE_LABELS.get(item.get('source'), item.get('source') or 'Não informada'),
        'end_reason': END_REASON_LABELS.get(item.get('end_reason'), item.get('end_reason') or '—'),
    }


def reservation_row(item):
    return {
        'created_at': local_time(item.get('created_at')),
        'station': item.get('station_name'),
        'public_code': item.get('public_code'),
        'status': status_badge(item.get('status'), RESERVATION_STATUS_LABELS),
        'expires_at': local_time(item.get('expires_at')),
        'no_show': 'Não' if item.get('no_show') else 'Sim' if item.get('status') == 'consumed' else '—',
    }


class SessionsView(View):
    def __init__(self, dash, tab='sessions', **data):
        super().__init__(dash, **data)
        filters = dash.state.filters
        self.tab = filters.get('tab', tab)
        self.offset = 0
        self.status = ft.Dropdown(label='Status', width=230, dense=True, text_size=13, color=theme.TEXT_COLOR,
                                  bgcolor=theme.WHITE, value=filters.get('status') or '__all__',
                                  on_select=self.filter_changed)
        self.search = ft.TextField(label='Buscar posto, ponto ou ID', width=280, dense=True, text_size=13,
                                   value=filters.get('q', ''), on_submit=self.filter_changed,
                                   prefix_icon=ft.Icons.SEARCH, color=theme.TEXT_COLOR)
        self.table = ft.Column(spacing=8, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        self.refresh_status_options()

    def refresh_status_options(self):
        labels = SESSION_STATUS_LABELS if self.tab == 'sessions' else RESERVATION_STATUS_LABELS
        self.status.options = [ft.DropdownOption(key='__all__', text='Todos')] + [
            ft.DropdownOption(key=key, text=label) for key, label in labels.items()]
        if self.status.value not in labels:
            self.status.value = '__all__'

    def skeleton(self):
        return [skeleton_block(48), skeleton_block(320)]

    def params(self):
        status = None if self.status.value in (None, '__all__') else self.status.value
        return self.dash.state.params(status=status, q=(self.search.value or '').strip() or None)

    async def load(self):
        loader = self.dash.api.owner_sessions if self.tab == 'sessions' else self.dash.api.owner_reservations
        result = await loader({**self.params(), 'limit': PAGE_SIZE, 'offset': self.offset})
        renderer, columns = ((session_row, SESSION_COLUMNS) if self.tab == 'sessions'
                             else (reservation_row, RESERVATION_COLUMNS))
        self.table.controls = [
            data_table(columns, [renderer(item) for item in result['items']],
                       empty_message='Nenhum registro no período e filtros escolhidos.',
                       numeric=('energy', 'cost', 'duration')),
            pagination(result['total'], PAGE_SIZE, self.offset, self.change_page,
                       label='sessões' if self.tab == 'sessions' else 'reservas'),
        ]
        self.set([self.toolbar(), section(
            'Sessões de recarga' if self.tab == 'sessions' else 'Reservas', self.table,
            subtitle=f'{self.dash.state.period_label()} · sem dados pessoais dos motoristas. '
                     + ('Reservas expiradas contam como não comparecimento.' if self.tab != 'sessions' else
                        'Filtradas pela data de criação; valores estimados.'))])

    def toolbar(self):
        tabs = ft.Row([self.tab_button('sessions', 'Sessões'), self.tab_button('reservations', 'Reservas')],
                      spacing=6)
        exports = ft.Row([
            ft.OutlinedButton('Exportar CSV', icon=ft.Icons.DOWNLOAD, on_click=self.dash.action(
                lambda: self.export('csv'))),
            ft.OutlinedButton('Exportar JSON', icon=ft.Icons.DATA_OBJECT, on_click=self.dash.action(
                lambda: self.export('json'))),
        ], spacing=8)
        search = ft.IconButton(ft.Icons.FILTER_ALT_OUTLINED, tooltip='Aplicar filtros', icon_color=theme.TEXT_COLOR,
                               on_click=self.filter_changed)
        return ft.Row([tabs, self.status, self.search, search, exports],
                      wrap=True, spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def tab_button(self, key, label):
        active = key == self.tab

        async def choose(event=None):
            if key != self.tab:
                self.tab, self.offset = key, 0
                self.dash.state.filters = {'tab': key}
                self.status.value = '__all__'
                self.refresh_status_options()
                await self.reload()
        control = ft.TextButton(
            content=ft.Text(label, color='#FFFFFF' if active else theme.TEXT_COLOR,
                            weight=ft.FontWeight.BOLD if active else None),
            on_click=choose,
            style=ft.ButtonStyle(bgcolor=theme.RED if active else theme.WHITE,
                                 shape=ft.RoundedRectangleBorder(radius=6),
                                 side={ft.ControlState.DEFAULT: ft.BorderSide(1, theme.LIGHT_GRAY),
                                       ft.ControlState.FOCUSED: ft.BorderSide(2, theme.FOCUS)}),
        )
        return ft.Semantics(content=control, selected=active, button=True, label=label)

    async def reload(self):
        self.dash.sync_context()
        try:
            await self.load()
        except ApiError as exc:
            self.show_error(str(exc))
        self.dash.update()

    async def filter_changed(self, event=None):
        self.offset = 0
        status = None if self.status.value in (None, '__all__') else self.status.value
        self.dash.state.filters = {'tab': self.tab, 'status': status, 'q': (self.search.value or '').strip()}
        await self.reload()

    async def change_page(self, offset):
        self.offset = max(0, offset)
        await self.reload()

    async def export(self, fmt):
        dataset = 'sessions' if self.tab == 'sessions' else 'reservations'
        content = await self.dash.api.owner_export(dataset, fmt, self.params())
        stamp = analytics.parse_time(self.params()['to']).astimezone(analytics.REPORT_TZ).strftime('%Y%m%d')
        name = f"chargegrid-{'sessoes' if dataset == 'sessions' else 'reservas'}-{stamp}.{fmt}"
        await save_bytes(self.dash.page, name, content)
        self.dash.notice(f'Arquivo {name} gerado ({len(content) // 1024 + 1} KB).')


async def save_bytes(page, file_name, content):
    """Baixa no navegador (web) ou abre "Salvar como" no desktop."""
    picker = ft.FilePicker()
    await picker.save_file(file_name=file_name, src_bytes=content, dialog_title='Salvar exportação')
