import flet as ft

from chargegrid_app.api_client import ApiError
from chargegrid_app.ui import theme
from chargegrid_app.ui.components import badge, button, pill
from chargegrid_app.ui.kpi import empty_state, skeleton_block

from ..state import IMPACT_LABELS, KIND_LABELS, local_time
from .base import View, section

IMPACT_COLORS = {'high': 'RED', 'medium': 'AMBER', 'low': 'SLATE'}
UNAVAILABLE = {404, 405, 501}


def recommendation_card(item):
    impact = item.get('impact') or 'medium'
    color = getattr(theme, IMPACT_COLORS.get(impact, 'SLATE'))
    card = ft.Semantics(content=ft.Container(ft.Column([
        ft.Row([ft.Text(item.get('title') or 'Recomendação', size=15, weight=ft.FontWeight.BOLD,
                        color=theme.TEXT_COLOR, expand=True),
                badge(IMPACT_LABELS.get(impact, impact), color, width=120)]),
        ft.Text(item.get('detail') or '', size=13, color=theme.TEXT_COLOR),
        ft.Row([pill(KIND_LABELS.get(item.get('kind'), item.get('kind') or 'Geral'))]),
    ], spacing=8), padding=14, border_radius=10, bgcolor=theme.WHITE, border=ft.Border.all(1, theme.LIGHT_GRAY)),
        label=f"Recomendação: {item.get('title')}. {item.get('detail')}")
    card.col = {'xs': 12, 'lg': 6}
    return card


class InsightsView(View):
    """Gera recomendações sob demanda (não faz polling: chamadas de IA têm custo)."""

    cache = {}

    def skeleton(self):
        return [skeleton_block(100), skeleton_block(160)]

    def key(self):
        state = self.dash.state
        return (id(self.dash.api), state.period, state.custom_start, state.custom_end, state.station_id)

    async def load(self):
        cached = InsightsView.cache.get(self.key())
        self.set([self.intro()] + (self.render(cached) if cached else [empty_state(
            'Recomendações para seus postos',
            'Gere uma análise do período selecionado: horários de pico, tarifa, manutenção e promoções.',
            icon=ft.Icons.AUTO_AWESOME_OUTLINED)]))

    def intro(self):
        return ft.Row([
            ft.Text(f'Período: {self.dash.state.period_label()}', size=13, color=theme.GRAY_TEXT, expand=True),
            button('Gerar recomendações', self.dash.action(self.generate)),
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER)

    async def generate(self):
        self.set([self.intro(), skeleton_block(100), skeleton_block(160)])
        self.dash.update()
        try:
            result = await self.dash.api.owner_insights(self.dash.state.params())
        except ApiError as exc:
            if exc.status in UNAVAILABLE:
                self.set([self.intro(), empty_state(
                    'Insights de IA indisponíveis',
                    'Este servidor ainda não oferece recomendações automáticas. Os indicadores e relatórios '
                    'continuam disponíveis nas outras seções.', icon=ft.Icons.CLOUD_OFF_OUTLINED)])
            else:
                self.set([self.intro(), empty_state(
                    'Não foi possível gerar agora', f'{exc} Tente novamente em instantes.',
                    icon=ft.Icons.ERROR_OUTLINE)])
            return
        if not isinstance(result, dict) or not (result.get('summary') or result.get('recommendations')):
            self.set([self.intro(), empty_state('Sem recomendações', 'Não há dados suficientes no período.')])
            return
        InsightsView.cache[self.key()] = result
        self.set([self.intro()] + self.render(result))

    def render(self, result):
        recommendations = result.get('recommendations') or []
        model = result.get('model') or ''
        origin = ('Gerado por regras do ChargeGrid' if model in ('', 'chargegrid-regras') else
                  f'Gerado por IA ({model})')
        footer = f"{origin} · {local_time(result.get('generated_at'))}"
        if getattr(self.dash.api, 'is_demo', False):
            # The demo may call the real AI (local key) or the rules: both use fictitious data.
            footer += ' · dados fictícios da conta demo'
        return [
            section('Resumo', ft.Text(result.get('summary') or '—', size=14, color=theme.TEXT_COLOR,
                                      selectable=True)),
            ft.ResponsiveRow([recommendation_card(item) for item in recommendations], spacing=12, run_spacing=12)
            if recommendations else empty_state('Sem recomendações', 'A análise não sugeriu ações.'),
            ft.Text(footer + '. Sugestões automáticas: revise antes de aplicar mudanças de tarifa.',
                    size=11, color=theme.GRAY_TEXT),
        ]
