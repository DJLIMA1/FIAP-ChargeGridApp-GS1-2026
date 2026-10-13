from datetime import datetime, timezone

import flet as ft

from chargegrid_app.screens import coupons as app_coupons
from chargegrid_app.ui import theme
from chargegrid_app.ui.components import badge, button
from chargegrid_app.ui.kpi import skeleton_block
from chargegrid_app.ui.tables import cell_badge, data_table

from ..state import local_time
from .base import View, embed, section

COLUMNS = (('code', 'Código'), ('description', 'Descrição'), ('discount', 'Desconto'), ('valid_until', 'Validade'),
           ('scope', 'Válido em'), ('status', 'Status'), ('actions', 'Ações'))


def coupon_status(item, now=None):
    now = now or datetime.now(timezone.utc)
    if not item.get('active', True):
        return 'Inativo'
    try:
        expired = datetime.fromisoformat(item['valid_until'].replace('Z', '+00:00')) <= now
    except (KeyError, ValueError, AttributeError):
        expired = False
    return 'Expirado' if expired else 'Ativo'


class CouponsView(View):
    """Lista em tabela; criação e edição reutilizam o formulário do app."""

    def __init__(self, dash, create=False, coupon=None, **data):
        super().__init__(dash, **data)
        self.create, self.coupon = create, coupon

    def skeleton(self):
        return [skeleton_block(320)]

    async def load(self):
        stations = await app_coupons.owned_stations(self.dash)
        if self.create or self.coupon:
            form = app_coupons.form(self.dash, self.coupon, stations)
            self.set([ft.Row([ft.TextButton('← Voltar para cupons', on_click=self.dash.link('coupons'),
                                            style=ft.ButtonStyle(color=theme.TEXT_COLOR))]),
                      embed(form, 560)])
            return
        items, offset = [], 0
        while True:
            result = await self.dash.api.request('GET', 'coupons', params={'mine': 'true', 'limit': 100,
                                                                           'offset': offset})
            items.extend(result['items'])
            offset += len(result['items'])
            if not result['items'] or offset >= result.get('total', offset):
                break
        names = {station['id']: station['name'] for station in stations}
        selected = self.dash.state.station_id
        if selected:
            items = [item for item in items if item.get('station_id') in (None, selected)]
        rows = []
        for item in items:
            status = coupon_status(item)
            rows.append({
                'code': ft.Text(item['code'], weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR, selectable=True),
                'description': item.get('description') or '—',
                'discount': f"{item['discount_percent']}%",
                'valid_until': local_time(item.get('valid_until')),
                'scope': names.get(item['station_id'], 'Posto indisponível') if item.get('station_id')
                else 'Todos os meus postos',
                'status': cell_badge(badge(status, theme.GREEN if status == 'Ativo' else theme.SLATE, width=90)),
                'actions': ft.Row([
                    ft.IconButton(ft.Icons.EDIT_OUTLINED, tooltip=f"Editar {item['code']}",
                                  icon_color=theme.TEXT_COLOR,
                                  on_click=self.dash.link('coupons', coupon=item)),
                    ft.IconButton(ft.Icons.TOGGLE_ON if item.get('active', True) else ft.Icons.TOGGLE_OFF_OUTLINED,
                                  tooltip='Desativar' if item.get('active', True) else 'Reativar',
                                  icon_color=theme.GREEN if item.get('active', True) else theme.GRAY_TEXT,
                                  on_click=self.dash.action(lambda item=item: self.toggle(item))),
                ], spacing=0, tight=True),
            })
        self.set([section(
            f'Cupons ({len(items)})',
            data_table(COLUMNS, rows, empty_message='Nenhum cupom criado ainda.', numeric=('discount',)),
            subtitle='Desconto sobre o custo estimado; não há cobrança real.',
            actions=[button('Criar cupom', self.dash.link('coupons', create=True))],
        )])

    async def toggle(self, item):
        active = not item.get('active', True)
        await self.dash.api.request('PATCH', f"coupons/{item['id']}", {'active': active})
        self.dash.notice(f"Cupom {item['code']} {'reativado' if active else 'desativado'}.")
        await self.load()
