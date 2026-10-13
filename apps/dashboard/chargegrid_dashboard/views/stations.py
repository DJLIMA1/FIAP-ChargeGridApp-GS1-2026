from decimal import Decimal, InvalidOperation

import flet as ft

from chargegrid_app.screens import operator
from chargegrid_app.ui import theme
from chargegrid_app.ui.components import badge, button, field
from chargegrid_app.ui.kpi import empty_state, point_status_badge, skeleton_block
from chargegrid_app.ui.tables import cell_badge, data_table
from chargegrid_core.formatting import brl, kwh

from .base import View, embed, section

COLUMNS = (('code', 'Ponto'), ('type', 'Conector'), ('power', 'Potência'), ('price', 'Tarifa'),
           ('status', 'Status'), ('live', 'Sessão ativa'), ('actions', 'Ações'))


def parse_price(text):
    try:
        value = Decimal(str(text).strip().replace('R$', '').replace(',', '.'))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError('Informe uma tarifa válida, por exemplo 1,50.') from exc
    if not value.is_finite() or not 0 <= value <= 10000:
        raise ValueError('A tarifa deve ficar entre R$ 0,00 e R$ 10.000,00 por kWh.')
    return format(value.quantize(Decimal('0.0001')), 'f')


def live_summary(point):
    session = point.get('session')
    if not session:
        return '—'
    parts = [kwh(float(session.get('energy_wh') or 0) / 1000, 2)]
    if session.get('power_w'):
        parts.append(f"{float(session['power_w']) / 1000:.1f} kW".replace('.', ','))
    parts.append(brl(session.get('cost_estimate')))
    return ' · '.join(parts)


class StationsView(View):
    poll_seconds = 15

    def __init__(self, dash, station_id=None, connector_id=None, connector=None, **data):
        super().__init__(dash, **data)
        self.edit_station_id, self.connector_id, self.connector = station_id, connector_id, connector
        self.live = {}

    def skeleton(self):
        return [skeleton_block(160), skeleton_block(160)]

    async def load(self):
        if self.connector_id:
            # Formulário completo do app: tarifa, limites e manutenção do dispositivo.
            form = await operator.connector_form(self.dash, self.edit_station_id, self.connector)
            self.set([self.back_link(), embed(form)])
            return
        if self.edit_station_id:
            station = await self.dash.api.request('GET', f'stations/{self.edit_station_id}')
            form = await operator.station_form(self.dash, station)
            self.set([self.back_link(), embed(form)])
            return
        stations = await self.dash.load_stations()
        live = await self.dash.api.owner_live({'station_id': self.dash.state.station_id})
        self.live = {item['connector_id']: item for item in live['items']}
        self.set(self.render(stations))

    async def refresh(self):
        if self.connector_id or self.edit_station_id:
            return
        live = await self.dash.api.owner_live({'station_id': self.dash.state.station_id})
        self.live = {item['connector_id']: item for item in live['items']}
        self.set(self.render(self.dash.stations))

    def back_link(self):
        return ft.Row([ft.TextButton('← Voltar para postos e pontos', on_click=self.dash.link('stations'),
                                     style=ft.ButtonStyle(color=theme.TEXT_COLOR))])

    def render(self, stations):
        selected = self.dash.state.station_id
        visible = [s for s in stations if not selected or s['id'] == selected]
        if not visible:
            return [empty_state('Nenhum posto vinculado',
                                'Vincule equipamentos pelo app ChargeGrid usando o QR de propriedade.',
                                icon=ft.Icons.EV_STATION_OUTLINED)]
        return [ft.Text('Status atualizado automaticamente a cada 15 s. Vincular novos equipamentos e ler o '
                        'QR continuam no app.', size=12, color=theme.GRAY_TEXT)] + [
            self.station_card(station) for station in visible]

    def station_card(self, station):
        points = station.get('connectors') or []
        published = bool(station.get('active'))
        rows = []
        for point in points:
            live = {**point, **self.live.get(point['id'], {})}
            rows.append({
                'code': ft.Text(point['public_code'], size=13, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
                'type': point.get('connector_type'),
                'power': f"{float(point.get('power_kw') or 0):.1f} kW".replace('.', ','),
                'price': brl(point.get('price_per_kwh')) + '/kWh',
                'status': cell_badge(point_status_badge(live)),
                'live': live_summary(live),
                'actions': self.point_actions(station, point),
            })
        toggle = button('Despublicar posto' if published else 'Publicar posto',
                        self.dash.action(lambda: self.set_station_active(station, not published)),
                        secondary=published)
        edit = button('Editar posto', self.dash.link('operator', station_id=station['id']), secondary=True)
        online = sum(bool(self.live.get(p['id'], p).get('online')) for p in points)
        return section(
            station['name'],
            data_table(COLUMNS, rows, empty_message='Nenhum ponto neste posto.', numeric=('power', 'price')),
            subtitle=f"{station.get('address', '')} · {len(points)} ponto(s), {online} online",
            actions=[badge('Publicado' if published else 'Não publicado',
                           theme.GREEN if published else theme.SLATE, width=110), edit, toggle],
        )

    def point_actions(self, station, point):
        active = bool(point.get('active'))
        retired = bool(point.get('retired'))
        items = [ft.PopupMenuItem(content=ft.Text('Editar tarifa'),
                                  on_click=self.dash.action(lambda: self.edit_price(point)))]
        if not retired:
            items.append(ft.PopupMenuItem(
                content=ft.Text('Despublicar ponto' if active else 'Publicar ponto'),
                on_click=self.dash.action(lambda: self.set_point_active(point, not active))))
        items.append(ft.PopupMenuItem(
            content=ft.Text('Editar ponto e dispositivo'),
            on_click=self.dash.link('operator', station_id=station['id'], connector_id=point['id'],
                                    connector=point)))
        items.append(ft.PopupMenuItem(content=ft.Text('Ver sessões do posto'),
                                      on_click=self.dash.link('history', station_id=station['id'])))
        return ft.PopupMenuButton(icon=ft.Icons.MORE_VERT, icon_color=theme.TEXT_COLOR, items=items,
                                  tooltip=f"Ações do ponto {point['public_code']}")

    async def set_station_active(self, station, active):
        await self.dash.api.request('PATCH', f"stations/{station['id']}", {'active': active})
        self.dash.notice('Posto publicado para motoristas.' if active else 'Posto despublicado.')
        await self.load()

    async def set_point_active(self, point, active):
        await self.dash.api.request('PATCH', f"connectors/{point['id']}", {'active': active})
        self.dash.notice('Ponto publicado.' if active else 'Ponto despublicado.')
        await self.load()

    async def edit_price(self, point):
        price = field('Tarifa por kWh (R$)', str(point.get('price_per_kwh', '')).replace('.', ','))
        feedback = ft.Text('', size=12, color=theme.ERROR, visible=False)

        def close(event=None):
            self.dash.page.pop_dialog()

        async def save():
            try:
                value = parse_price(price.value)
            except ValueError as exc:
                feedback.value, feedback.visible = str(exc), True
                self.dash.update()
                return
            await self.dash.api.request('PATCH', f"connectors/{point['id']}", {'price_per_kwh': value})
            close()
            self.dash.notice(f"Tarifa de {point['public_code']} atualizada para {brl(value)}/kWh.")
            await self.load()

        self.dash.page.show_dialog(ft.AlertDialog(
            modal=True, title=ft.Text(f"Tarifa do ponto {point['public_code']}"),
            content=ft.Column([price, feedback, ft.Text(
                'Vale para novas recargas. Pontos com reserva ou recarga em andamento não podem ser alterados.',
                size=12, color=theme.GRAY_TEXT)], tight=True, width=360),
            actions=[ft.TextButton('Cancelar', on_click=close),
                     ft.TextButton('Salvar', on_click=self.dash.action(save))],
        ))

