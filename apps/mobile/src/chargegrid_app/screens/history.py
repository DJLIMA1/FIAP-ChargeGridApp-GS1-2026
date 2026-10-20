import asyncio

import flet as ft

from chargegrid_core.formatting import kwh

from ..services import owner_sessions
from ..ui import theme
from ..ui.ai_features import ai_supported, session_insight_control
from ..ui.components import button, date_time, money, title
from ..ui.design import card_box, icon_tile, page_title, section_label, txt
from ..ui.design import page as layout
from ..ui.point_summary import event_disclosure, point_summary
from ..ui.states import SESSION_TONES, empty_state, status_chip
from . import history_export, history_owner
from . import receipt as receipt_screen
from .charging import DEMO_LABELS, LABELS, session_card

PAGE = 20


def _area(address):
    """'Av. X, 10, Pinheiros, São Paulo - SP' -> 'Pinheiros - São Paulo' (subtítulo da referência)."""
    text = str(address or '').strip()
    head, _, uf = text.rpartition(' - ')
    if head and len(uf.strip()) == 2:
        text = head
    parts = [part.strip() for part in text.split(',') if part.strip()]
    return f'{parts[-2]} - {parts[-1]}' if len(parts) >= 3 else text


def _when(value):
    """(``dd/mm/aaaa``, ``hh:mm``) em horário local, ou (—, —)."""
    stamp = date_time(value)
    return tuple(stamp.split(' ')) if ' ' in stamp else ('—', '—')


def money_lines(session):
    """Pagamento (status, capturado e devolvido/liberado) e permanência (minutos/taxa) da sessão para o vendedor.

    Lista vazia quando a API não manda ``payment`` nem ``overstay`` (ou a sessão não teve nenhum dos dois)."""
    lines = []
    payment = owner_sessions.payment_summary(session.get('payment'))
    if payment:
        label, detail = payment
        source = owner_sessions.payment_source(session.get('payment'))
        lines.append(txt(f'Pagamento: {source} · {label}', 11, 'semibold'))
        if detail:
            lines.append(txt(detail, 10.5, 'regular', theme.GRAY_TEXT))
    overstay = owner_sessions.overstay_summary(session)
    if overstay:
        lines.append(txt(f'Permanência: {overstay}', 11, 'semibold'))
    return lines


def _summary(app, session, *, demo, events):
    """Cabeçalho "DATA: dd/mm/aaaa" + cartão da estação; o recibo completo abre ao tocar."""
    labels = DEMO_LABELS if demo else LABELS
    connector = session.get('connector') or {}
    identity = ' · '.join(str(value) for value in (connector.get('public_code'), connector.get('connector_type')) if value)
    day, hour = _when(session.get('started_at') or session.get('created_at'))
    details = [point_summary(session, 'Local da recarga'), session_card(session, demo=demo),
               ft.Text('Início: '+date_time(session.get('started_at')), size=12, color=theme.GRAY_TEXT),
               ft.Text('Fim: '+date_time(session.get('ended_at')), size=12, color=theme.GRAY_TEXT)]
    insight = []
    if events:
        details.extend(event_disclosure(app, session['id']))
        if ai_supported(app) and session.get('status') in ('completed', 'interrupted'):
            # Visible on the card (not inside the details): the AI summary is one tap away.
            insight.append(session_insight_control(app, session['id']))
    panel = ft.Container(ft.Column([
        ft.Row([status_chip(labels.get(session['status'], session['status']), SESSION_TONES.get(session['status'], 'SLATE')),
                ft.Text(f"{kwh(float(session.get('energy_wh') or 0)/1000, 2)} · {money(session.get('cost_estimate'))}",
                        size=12, color=theme.GRAY_TEXT)],
               alignment=ft.MainAxisAlignment.SPACE_BETWEEN, wrap=True, run_spacing=6),
        *([ft.Text(identity, size=12, color=theme.GRAY_TEXT)] if identity else []),
        *insight, *details], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
        visible=False, padding=ft.Padding(left=0, right=0, top=12, bottom=0))

    def toggle(_):
        panel.visible = not panel.visible
        panel.update()

    head = ft.Row([txt(f'DATA: {day}', 11.8, 'regular'), txt(hour, 11.8, 'regular')],
                  alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
    # Recibo explicável (só o titular da recarga: histórico do motorista).
    trailing = [receipt_link(app, session['id'])] if events and session.get('id') else []
    row = ft.Row([icon_tile(None, size=46),
                  ft.Column([txt(session.get('station_name') or 'Posto não identificado', 13.5, 'semibold'),
                             txt(_area(session.get('station_address')) or identity or '—', 10.5, 'regular', theme.GRAY_TEXT,
                                 max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)],
                            spacing=4, expand=True, alignment=ft.MainAxisAlignment.CENTER),
                  *trailing],
                 spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    # Vendedor (histórico dos postos): pagamento e permanência visíveis sem abrir os detalhes.
    extra = [] if events else money_lines(session)
    money_box = [ft.Container(ft.Column(extra, spacing=3), data='session-money',
                              padding=ft.Padding(left=60, right=0, top=10, bottom=0))] if extra else []
    return ft.Column([head, card_box(ft.Column([ft.Container(row, on_click=toggle, ink=False,
                                                              tooltip='Detalhes da sessão'), *money_box, panel],
                                               spacing=0),
                                     padding=16, radius=18)], spacing=12.5)


RECEIPT_LABEL = 'Ver recibo'


def receipt_link(app, session_id):
    """Atalho "Ver recibo" no cartão da recarga (abre ``history?receipt=<id>``)."""
    return ft.Container(txt(RECEIPT_LABEL, 11, 'semibold', theme.BTN_PRIMARY_FG), bgcolor=theme.BTN_PRIMARY,
                        border_radius=10, padding=ft.Padding(left=11, right=11, top=7, bottom=7),
                        on_click=app.link('history', receipt=session_id), ink=True, tooltip='Recibo explicável')


async def build(app, station_id=None, offset=0, manage=False, page=None, days=7, chart=True, receipt=None, **_):
    demo = getattr(app.api,'is_demo',False) is True
    if receipt and not manage and not station_id:
        return await receipt_screen.build(app, receipt)
    demo_controls = [ft.Column([txt('CONTA DEMO · HISTÓRICO SIMULADO', 10, 'bold', theme.ACCENT),
                                txt('Sessões de exemplo e testes feitos nesta conta. Estes valores não são cobranças ou medições reais.',
                                    10, 'regular', theme.GRAY_TEXT)], spacing=2)] if demo else []
    if manage and not app.profile.get('operator_enabled'):
        return ft.Column(demo_controls+[
            title('Histórico dos meus postos', 'Vincule sua primeira tela para começar a registrar recargas nos seus postos.'),
            button('Ir para meus postos', app.link('operator')),
        ], spacing=15)
    if manage and not station_id and page == 'energy':
        return await history_owner.energy_page(app, days=int(days or 7))
    if manage and not station_id and page == 'forecast':
        return await history_owner.forecast_page(app, station=_.get('station'))
    if manage and not station_id and page == 'economics':
        return await history_owner.economics_page(app, days=int(days or 7))
    path = (f'stations/{station_id}/charging-sessions' if station_id else
            'operator/charging-sessions' if manage else 'me/charging-sessions')
    listing = app.api.request('GET',path,params={'limit':PAGE,'offset':offset})
    dashboard = []
    if manage and not station_id and not offset:
        # Lista e painel do período em paralelo (antes: lista, resumo, resultado e gráfico em fila).
        result, dashboard = await asyncio.gather(
            listing, history_owner.dashboard(app, chart=chart not in (False, 0, 'false')))
    else:
        result = await listing
    total = result.get('total', len(result['items']))
    controls = []
    if manage and not station_id:
        if result['items']:
            controls.append(section_label('Recargas recentes'))
    elif station_id:
        controls.append(title('Histórico do posto', f'{total} {"sessão" if total == 1 else "sessões"} · valores estimados, sem cobrança real.'))
    for session in result['items']:
        controls.append(_summary(app, session, demo=demo, events=not manage and not station_id))
    if not result['items']:
        if offset:
            controls.append(empty_state(ft.Icons.HISTORY, 'Nada nesta página',
                                        'Volte para a página anterior para ver as sessões registradas.'))
        elif manage or station_id:
            controls.append(empty_state(ft.Icons.EV_STATION_OUTLINED, 'Nenhuma sessão registrada',
                                        'As recargas feitas nos seus pontos aparecem aqui, com energia e valor estimado.'))
        else:
            controls.append(empty_state(ft.Icons.EV_STATION_OUTLINED, 'Nenhuma sessão registrada',
                                        'Sua primeira recarga aparece aqui, com energia, tempo e valor estimado.',
                                        button('Encontrar um posto', app.link('stations'))))
    if offset:
        controls.append(button('Anterior',app.link('history',station_id=station_id,offset=max(0,offset-PAGE),**({'manage':True} if manage else {})),secondary=True))
    if offset+PAGE < total:
        controls.append(button('Mais sessões',app.link('history',station_id=station_id,offset=offset+PAGE,**({'manage':True} if manage else {}))))
    if manage and not station_id:
        return layout(ft.Container(page_title('Histórico', size=22.6), margin=ft.Margin(left=0, top=2, right=0, bottom=0)),
                      ft.Container(height=29), ft.Column(dashboard, spacing=0),
                      ft.Container(ft.Column([*controls, *demo_controls], spacing=30),
                                   margin=ft.Margin(left=0, top=36 if chart not in (False, 0, 'false') else 240, right=0, bottom=0)),
                      gap=0)
    if not station_id and not offset and result['items']:
        controls.append(history_export.history_card(app))
    heading = [] if station_id else [ft.Container(page_title('Histórico', size=14.7), margin=ft.Margin(left=0, top=4, right=0, bottom=0))]
    # A conta demo avisa que os dados são simulados, mas abaixo da dobra (a referência não mostra o aviso).
    notice = [ft.Container(height=500), *demo_controls] if demo_controls and not station_id else demo_controls
    return layout(*heading, ft.Container(height=0 if station_id else 34.5),
                  ft.Column([*controls, *notice], spacing=36.5 if not station_id else 20),
                  gap=0)
