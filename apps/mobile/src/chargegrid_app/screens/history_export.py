"""Cartão "Exportar (PDF/CSV)" do histórico: escolhe o período e entrega o arquivo da API.

Motorista: ``/v1/me/charging-sessions/export.{csv,pdf}``. Dono: ``/v1/owner/export/margin.{csv,pdf}``
(resultado do período). Download autenticado (``api.download``) e entrega pela folha de
compartilhamento ou "Salvar como" (``services.files``). Na conta demo só o CSV (gerado localmente).
"""

from datetime import datetime, timedelta, timezone

import flet as ft

from chargegrid_core import analytics

from ..api_client import ApiError
from ..services import files
from ..ui import theme
from ..ui.design import card_box, secondary_button, txt

PERIODS = ((30, 'Últimos 30 dias'), (90, 'Últimos 90 dias'), (365, 'Últimos 12 meses'))
PDF_DEMO_NOTE = 'PDF indisponível nesta conta; exporte o CSV.'


def window(days, now=None):
    """``{'from', 'to'}`` (ISO, UTC) dos últimos ``days`` dias até agora."""
    end = now or datetime.now(timezone.utc)
    return {'from': (end - timedelta(days=days)).isoformat(), 'to': end.isoformat()}


def stamp():
    return datetime.now(analytics.REPORT_TZ).strftime('%Y%m%d-%H%M')


def is_demo(app):
    return getattr(getattr(app, 'api', None), 'is_demo', False) is True


def export_card(app, fetch, filename, *, title='Exportar (PDF/CSV)', subtitle=None, params=None,
                periods=PERIODS, data='history-export'):
    """``fetch(fmt, params) -> bytes``; ``filename(fmt) -> str``. Sem ``params`` mostra o seletor de período."""
    demo = is_demo(app)
    state = {'days': periods[0][0] if periods else None}
    controls = [txt(title, 13.5, 'semibold')]
    if subtitle:
        controls.append(txt(subtitle, 10.5, 'regular', theme.GRAY_TEXT))
    if params is None and periods:
        label = txt(periods[0][1], 12, 'bold')

        def choose(days, text):
            def handler(_=None):
                state['days'] = days
                label.value = text
                try:
                    label.update()
                except (RuntimeError, AssertionError, AttributeError):
                    pass  # fora da tela (testes)
            return handler
        controls.append(ft.PopupMenuButton(
            content=ft.Container(ft.Row([label, ft.Icon(ft.Icons.CALENDAR_TODAY_OUTLINED, size=17,
                                                        color=theme.TEXT_COLOR)],
                                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                        vertical_alignment=ft.CrossAxisAlignment.CENTER),
                                 padding=ft.Padding(left=14, right=14, top=0, bottom=0), height=40,
                                 border_radius=12, bgcolor=theme.BTN_SECONDARY, alignment=ft.Alignment(-1, 0)),
            tooltip='Escolher período', data='export-period',
            items=[ft.PopupMenuItem(content=text, on_click=choose(days, text)) for days, text in periods]))

    def run(fmt):
        async def operation():
            query = params if params is not None else window(state['days'])
            try:
                content = await fetch(fmt, query)
                app.notice(await files.deliver(app, content, filename(fmt)))
            except ApiError as exc:
                app.notice(str(exc))
            except Exception:  # serviço de arquivos indisponível nesta plataforma
                app.notice('Não foi possível salvar o arquivo neste aparelho. Tente novamente.')
        return app.action(operation)

    controls.append(ft.Row([
        secondary_button('CSV', run('csv'), icon=ft.Icons.TABLE_CHART_OUTLINED, height=42, expand=True, size=13),
        secondary_button('PDF', None if demo else run('pdf'), icon=ft.Icons.PICTURE_AS_PDF_OUTLINED, height=42,
                         expand=True, size=13, disabled=demo),
    ], spacing=10))
    if demo:
        controls.append(txt(PDF_DEMO_NOTE, 10.5, 'regular', theme.GRAY_TEXT))
    return card_box(ft.Column(controls, spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                    padding=ft.Padding(left=16, right=16, top=16, bottom=16), data=data)


def history_card(app):
    """Exportação do histórico do motorista (sessões encerradas no período)."""
    async def fetch(fmt, params):
        return await app.api.download(f'me/charging-sessions/export.{fmt}', params=params)
    return export_card(app, fetch, lambda fmt: f'chargegrid-historico-{stamp()}.{fmt}',
                       subtitle='Recargas encerradas no período, com energia, preço travado e valor.')
