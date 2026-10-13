import asyncio

import flet as ft

from chargegrid_app.ui import theme
from chargegrid_app.ui.charts import bar_chart, heatmap, ranking_bars
from chargegrid_app.ui.kpi import alert_tile, empty_state, kpi_card, kpi_grid, skeleton_block, skeleton_cards
from chargegrid_core.formatting import brl, integer, kwh, percent

from ..state import bucket_label
from .base import View, section

HALF = {'xs': 12, 'lg': 6}


def kpi_cards(kpis):
    """Oito indicadores principais, na mesma ordem para API e demo."""
    sessions = kpis.get('sessions') or 0
    return [
        kpi_card('Receita estimada', brl(kpis.get('revenue')), icon=ft.Icons.PAYMENTS_OUTLINED,
                 hint='Sessões encerradas no período'),
        kpi_card('Energia entregue', kwh(kpis.get('energy_kwh'), 1), icon=ft.Icons.BOLT,
                 hint='Simulada, medida ou estimada'),
        kpi_card('Sessões', integer(sessions), icon=ft.Icons.EV_STATION_OUTLINED,
                 hint=f"{kpis.get('active_sessions', 0)} em andamento · {kpis.get('interrupted_sessions', 0)} "
                      'interrompidas'),
        kpi_card('Ticket médio', brl(kpis.get('average_ticket')), icon=ft.Icons.RECEIPT_OUTLINED,
                 hint='Receita ÷ sessões encerradas'),
        kpi_card('Ocupação', percent(kpis.get('occupancy_percent')), icon=ft.Icons.TIMELAPSE,
                 hint='Tempo em recarga ÷ tempo disponível'),
        kpi_card('Disponibilidade', percent(kpis.get('uptime_percent')), icon=ft.Icons.WIFI_TETHERING,
                 hint=f"{kpis.get('points_online', 0)} de {kpis.get('points', 0)} pontos online agora",
                 tone=theme.GREEN),
        kpi_card('Reservas', integer(kpis.get('reservations')), icon=ft.Icons.EVENT_AVAILABLE_OUTLINED,
                 hint='Criadas no período'),
        kpi_card('Não comparecimento', integer(kpis.get('no_shows')), icon=ft.Icons.EVENT_BUSY_OUTLINED,
                 hint=f"{percent(kpis.get('no_show_percent'))} das reservas expiraram",
                 tone=theme.ACCENT),
    ]


class OverviewView(View):
    poll_seconds = 30

    def skeleton(self):
        return [skeleton_cards(8),
                ft.ResponsiveRow([ft.Container(skeleton_block(220), col=HALF) for _ in range(2)],
                                 spacing=16, run_spacing=16),
                skeleton_block(180)]

    async def load(self):
        state, api = self.dash.state, self.dash.api
        params = state.params()
        granularity = state.granularity()
        overview, series, heat, alerts = await asyncio.gather(
            api.owner_overview(params),
            api.owner_timeseries({**params, 'granularity': granularity}),
            api.owner_heatmap(params),
            api.owner_alerts({'station_id': state.station_id}),
        )
        self.set(self.render(overview, series, heat, alerts['items'], granularity))

    def render(self, overview, series, heat, alerts, granularity):
        kpis = overview['kpis']
        labels = [bucket_label(bucket, granularity) for bucket in series['buckets']]
        every = max(1, len(labels) // 12)
        per = 'hora' if granularity == 'hour' else 'dia'
        revenue = bar_chart(series['series']['revenue'], labels, format_value=brl, label_every=every,
                            color=theme.RED)
        energy = bar_chart(series['series']['energy_kwh'], labels, format_value=lambda v: kwh(v, 2),
                           label_every=every, color=theme.BLUE)
        peaks = ', '.join(f"{item['hour']:02d}h" for item in heat.get('peak_hours', [])) or '—'
        heat_chart = heatmap(heat['cells'], heat['days'], [f'{h:02d}' for h in heat['hours']],
                             format_value=lambda v: f'{v} sessões', label_every=3)
        ranking = overview.get('ranking') or []
        ranking_view = ranking_bars(
            [{**item, 'label': f"{item['public_code']} · {item['station_name']}",
              'caption': f"{item['sessions']} sessões · {kwh(item['energy_kwh'], 1)} · ocupação "
                         f"{percent(item['occupancy_percent'])}"} for item in ranking],
            value_key='revenue', label_key='label', caption_key='caption', format_value=brl,
        ) if any(item['sessions'] for item in ranking) else empty_state(
            'Sem recargas no período', 'O ranking aparece quando houver sessões encerradas.',
            icon=ft.Icons.LEADERBOARD_OUTLINED)
        alert_view = ft.Column([alert_tile(alert) for alert in alerts[:8]], spacing=8) if alerts else empty_state(
            'Tudo certo', 'Nenhum dispositivo offline, falha de comando ou ponto parado.',
            icon=ft.Icons.VERIFIED_OUTLINED)
        stations = overview.get('stations', {})
        return [
            kpi_grid(kpi_cards(kpis)),
            ft.Text(f"{stations.get('total', 0)} posto(s) · {stations.get('points_published', 0)} ponto(s) "
                    f"publicados de {stations.get('points', 0)}. Receita e energia atribuídas ao término "
                    'da sessão (fuso de São Paulo); valores estimados, sem cobrança real.',
                    size=12, color=theme.GRAY_TEXT),
            ft.ResponsiveRow([
                section(f'Receita por {per}', revenue, col=HALF),
                section(f'Energia por {per}', energy, col=HALF),
            ], spacing=16, run_spacing=16),
            ft.ResponsiveRow([
                section('Sessões por dia da semana e hora', heat_chart, subtitle=f'Horários de pico: {peaks}',
                        col={'xs': 12, 'xl': 7}),
                section('Ranking de pontos', ranking_view, subtitle='Por receita estimada no período',
                        col={'xs': 12, 'xl': 5}),
            ], spacing=16, run_spacing=16),
            section(f'Alertas ({len(alerts)})', alert_view),
        ]
