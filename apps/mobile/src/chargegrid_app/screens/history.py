import asyncio

import flet as ft

from ..services import owner_sessions
from ..ui import theme
from ..ui.components import button, date_time, title
from ..ui.design import card_box, icon_tile, page_title, section_label, txt
from ..ui.design import page as layout
from ..ui.states import empty_state
from . import charge_detail, history_export, history_owner

PAGE = 20


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


def detail_link(app, session, scope):
    """Toque no cartão: abre os detalhes da recarga (``history?session=<id>``) no mesmo escopo da lista."""
    return app.link('history', session=session['id'], **scope)


def _summary(app, session, *, seller, scope):
    """Cabeçalho "DATA: dd/mm/aaaa" + cartão da estação; o toque abre os detalhes da recarga."""
    connector = session.get('connector') or {}
    identity = ' · '.join(str(value) for value in (connector.get('public_code'), connector.get('connector_type')) if value)
    day, hour = _when(session.get('started_at') or session.get('created_at'))
    head = ft.Row([txt(f'DATA: {day}', 11.8, 'regular'), txt(hour, 11.8, 'regular')],
                  alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
    row = ft.Row([icon_tile(None, size=46),
                  ft.Column([txt(session.get('station_name') or 'Posto não identificado', 13.5, 'semibold'),
                             txt(charge_detail.area(session.get('station_address')) or identity or '—', 10.5, 'regular',
                                 theme.GRAY_TEXT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)],
                            spacing=4, expand=True, alignment=ft.MainAxisAlignment.CENTER),
                  ft.Icon(ft.Icons.CHEVRON_RIGHT, size=24, color=theme.TEXT_COLOR)],
                 spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    # Vendedor (histórico dos postos): pagamento e permanência visíveis sem abrir os detalhes.
    extra = money_lines(session) if seller else []
    money_box = [ft.Container(ft.Column(extra, spacing=3), data='session-money',
                              padding=ft.Padding(left=60, right=0, top=10, bottom=0))] if extra else []
    open_detail = detail_link(app, session, scope) if session.get('id') else None
    return ft.Column([head, card_box(ft.Column([row, *money_box], spacing=0), padding=16, radius=18,
                                     on_click=open_detail, tooltip=charge_detail.TITLE, data='session-card')],
                     spacing=12.5)


async def build(app, station_id=None, offset=0, manage=False, page=None, days=7, chart=True, receipt=None,
                session=None, **_):
    if session or receipt:
        return await charge_detail.build(app, session or receipt, manage=bool(manage), station_id=station_id,
                                         offset=offset)
    if manage and not app.profile.get('operator_enabled'):
        return ft.Column([
            title('Histórico dos meus postos', 'Vincule sua primeira central para começar a registrar recargas nos seus postos.'),
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
    seller = bool(manage or station_id)
    # Os detalhes reaproveitam o item da listagem: o vendedor não tem recibo (documento do motorista) e o
    # motorista evita um GET da sessão além do recibo.
    app.history_sessions = {item['id']: item for item in result['items'] if item.get('id')}
    scope = {key: value for key, value in (('manage', True if manage else None), ('station_id', station_id),
                                           ('offset', offset or None)) if value}
    for item in result['items']:
        controls.append(_summary(app, item, seller=seller, scope=scope))
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
                      ft.Container(ft.Column(controls, spacing=30),
                                   margin=ft.Margin(left=0, top=36 if chart not in (False, 0, 'false') else 240, right=0, bottom=0)),
                      gap=0)
    if not station_id and not offset and result['items']:
        controls.append(history_export.history_card(app))
    heading = [] if station_id else [ft.Container(page_title('Histórico', size=14.7), margin=ft.Margin(left=0, top=4, right=0, bottom=0))]
    return layout(*heading, ft.Container(height=0 if station_id else 34.5),
                  ft.Column(controls, spacing=36.5 if not station_id else 20),
                  gap=0)
