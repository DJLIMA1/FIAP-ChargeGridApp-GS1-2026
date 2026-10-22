"""Componentes das funcionalidades de IA: busca em linguagem natural, resumo de
recarga e insights do dono. Cada tela só chama um construtor daqui."""

import flet as ft

from ..api_client import ApiError
from . import theme
from .components import card

RULES_MODEL = 'chargegrid-regras'
_KIND_LABELS = {'pricing': 'Preço', 'operations': 'Operação', 'marketing': 'Divulgação', 'maintenance': 'Manutenção'}
_IMPACT_LABELS = {'high': 'alto', 'medium': 'médio', 'low': 'baixo'}


def ai_supported(app):
    """Clientes reais e demo declaram ``ai_enabled``; fakes antigos não exibem IA."""
    return getattr(type(getattr(app, 'api', None)), 'ai_enabled', None) is not None


def _origin_label(model):
    if not model or model == RULES_MODEL:
        return 'Interpretado automaticamente por regras do ChargeGrid.'
    return 'Gerado por IA · pode conter erros. Confira antes de confirmar.'


def _heading(icon, text):
    return ft.Row([ft.Icon(icon, color=theme.RED, size=20),
                   ft.Text(text, size=15, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR, expand=True)], spacing=8)


def _loading(text):
    return ft.Row([ft.ProgressRing(width=16, height=16, stroke_width=2, color=theme.RED),
                   ft.Text(text, size=12, color=theme.GRAY_TEXT)], spacing=10)


def _expandable(app, label, icon, loader):
    """Botão que carrega sob demanda, mostra carregando/erro/resultado e permite tentar de novo."""
    body = ft.Column(spacing=8, visible=False)
    state = {'loaded': False}

    async def toggle():
        if state['loaded']:
            body.visible = not body.visible
            app.page.update()
            return
        body.controls, body.visible = [_loading('Gerando análise… pode levar alguns segundos.')], True
        app.page.update()
        try:
            body.controls = await loader()
            state['loaded'] = True
        except ApiError as exc:
            message = ('Limite de uso da IA atingido. Tente mais tarde.' if exc.status == 429 else
                       str(exc) if exc.status == 409 else  # e.g. the charge has not finished yet
                       'Não foi possível gerar agora. Verifique a conexão e tente novamente.')
            body.controls = [ft.Text(message, size=12, color=theme.GRAY_TEXT)]
        app.page.update()

    header = ft.TextButton(content=ft.Row([ft.Icon(icon, color=theme.RED, size=18),
                                           ft.Text(label, size=13, color=theme.TEXT_COLOR, weight=ft.FontWeight.BOLD)],
                                          spacing=6, tight=True),
                           # No tooltip: it would repeat the visible label over the loading text.
                           on_click=app.action(toggle), data=('ai-disclosure', label))
    return ft.Column([header, body], spacing=4)


def session_insight_control(app, session_id):
    """Resumo inteligente de uma recarga do histórico (POST /v1/ai/session-insight)."""
    async def load():
        result = await app.api.request('POST', 'ai/session-insight', {'session_id': session_id})
        if not isinstance(result, dict) or not result.get('summary'):
            raise ApiError('Resposta inválida do resumo.')
        controls = [ft.Text(str(result['summary']), size=13, color=theme.TEXT_COLOR)]
        controls += [ft.Text('• ' + str(tip), size=12, color=theme.TEXT_COLOR) for tip in (result.get('tips') or [])[:3]]
        controls.append(ft.Text(_origin_label(result.get('model')) + ' Valores estimados.', size=11,
                                color=theme.GRAY_TEXT, italic=True))
        return [card(ft.Column(controls, spacing=6), padding=12, border=ft.Border.all(1, theme.LIGHT_GRAY))]
    return _expandable(app, 'Resumo inteligente da recarga', ft.Icons.AUTO_AWESOME, load)


def owner_insights_control(app, days=30):
    """Diagnóstico e recomendações para o dono (POST /v1/ai/owner-insights)."""
    async def load():
        result = await app.api.request('POST', 'ai/owner-insights', {'days': days})
        if not isinstance(result, dict) or not isinstance(result.get('recommendations'), list):
            raise ApiError('Resposta inválida dos insights.')
        controls = [ft.Text(str(result.get('summary') or ''), size=13, color=theme.TEXT_COLOR)]
        for item in result['recommendations'][:5]:
            kind = _KIND_LABELS.get(item.get('kind'), 'Operação')
            controls.append(card(ft.Column([
                ft.Text(str(item.get('title') or ''), size=14, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
                ft.Text(str(item.get('detail') or ''), size=12, color=theme.TEXT_COLOR),
                ft.Text(f"{kind} · impacto {_IMPACT_LABELS.get(item.get('impact'), 'médio')}", size=11, color=theme.GRAY_TEXT),
            ], spacing=4), padding=10, border=ft.Border.all(1, theme.LIGHT_GRAY)))
        origin = _origin_label(result.get('model'))
        if getattr(app.api, 'is_demo', False):
            # The demo owner analytics include a simulated 30-day history (same as the web dashboard),
            # so these totals are larger than the sessions created during the presentation.
            origin += ' A análise usa um histórico de 30 dias, o mesmo do painel web.'
        controls.append(ft.Text(origin, size=11, color=theme.GRAY_TEXT, italic=True))
        return controls
    return _expandable(app, f'Insights dos meus postos ({days} dias)', ft.Icons.INSIGHTS, load)
