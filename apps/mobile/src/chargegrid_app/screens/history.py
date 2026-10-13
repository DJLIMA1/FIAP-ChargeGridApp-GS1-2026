import flet as ft

from chargegrid_core.formatting import kwh

from ..ui import theme
from ..ui.components import button, card, date_time, money, title
from ..ui.point_summary import event_disclosure, point_summary
from ..ui.states import SESSION_TONES, empty_state, status_chip
from .charging import DEMO_LABELS, LABELS, session_card

PAGE = 20


def _summary(app, session, *, demo, events):
    """Compact, scannable row; the full receipt stays one tap away."""
    labels = DEMO_LABELS if demo else LABELS
    connector = session.get('connector') or {}
    identity = ' · '.join(str(value) for value in (connector.get('public_code'), connector.get('connector_type')) if value)
    when = date_time(session.get('started_at') or session.get('created_at'))
    details = [point_summary(session, 'Local da recarga'), session_card(session, demo=demo),
               ft.Text('Início: '+date_time(session.get('started_at')), size=12, color=theme.GRAY_TEXT),
               ft.Text('Fim: '+date_time(session.get('ended_at')), size=12, color=theme.GRAY_TEXT)]
    if events:
        details.extend(event_disclosure(app, session['id']))
    return card([
        ft.Row([status_chip(labels.get(session['status'], session['status']), SESSION_TONES.get(session['status'], 'SLATE')),
                ft.Text(when, size=12, color=theme.GRAY_TEXT)],
               alignment=ft.MainAxisAlignment.SPACE_BETWEEN, wrap=True, run_spacing=6),
        ft.Text(session.get('station_name') or 'Posto não identificado', size=18, weight=ft.FontWeight.BOLD,
                color=theme.TEXT_COLOR, font_family='BarlowSemiBold'),
        *([ft.Text(identity, size=13, color=theme.GRAY_TEXT)] if identity else []),
        ft.Row([
            ft.Column([ft.Text('Energia', size=11, color=theme.GRAY_TEXT),
                       ft.Text(kwh(float(session.get('energy_wh') or 0)/1000, 2), size=16,
                               weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR)], spacing=2, expand=True),
            ft.Column([ft.Text('Custo estimado', size=11, color=theme.GRAY_TEXT),
                       ft.Text(money(session.get('cost_estimate')), size=16,
                               weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR)], spacing=2, expand=True),
        ], spacing=12),
        ft.ExpansionTile(title=ft.Text('Detalhes da sessão', size=13, color=theme.TEXT_COLOR),
                         controls=details, maintain_state=True, tile_padding=ft.Padding(left=0, right=0, top=0, bottom=0),
                         controls_padding=ft.Padding(left=0, right=0, top=0, bottom=8),
                         shape=ft.RoundedRectangleBorder(radius=8), collapsed_shape=ft.RoundedRectangleBorder(radius=8)),
    ], padding=16)


async def build(app, station_id=None, offset=0, manage=False):
    demo = getattr(app.api,'is_demo',False) is True
    demo_controls = [card([ft.Text('CONTA DEMO · HISTÓRICO SIMULADO',weight=ft.FontWeight.BOLD,color=theme.ACCENT),
                           ft.Text('Sessões de exemplo e testes feitos nesta conta. Estes valores não são cobranças ou medições reais.',size=13,color=theme.GRAY_TEXT)])] if demo else []
    if manage and not app.profile.get('operator_enabled'):
        return ft.Column(demo_controls+[
            title('Histórico dos meus postos', 'Vincule sua primeira tela para começar a registrar recargas nos seus postos.'),
            button('Ir para meus postos', app.link('operator')),
        ], spacing=15)
    path = (f'stations/{station_id}/charging-sessions' if station_id else
            'operator/charging-sessions' if manage else 'me/charging-sessions')
    result = await app.api.request('GET',path,params={'limit':PAGE,'offset':offset})
    total = result.get('total', len(result['items']))
    subtitle = 'Sessões registradas e valores estimados. Nenhuma cobrança real.'
    if result['items']:
        first, last = offset + 1, offset + len(result['items'])
        subtitle = f'{first}–{last} de {total} {"sessão" if total == 1 else "sessões"} · valores estimados, sem cobrança real.'
    controls = [title('Histórico do posto' if station_id else 'Histórico dos meus postos' if manage else 'Meu histórico',
                      subtitle)]
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
    return ft.Column(demo_controls+controls,spacing=15,scroll=ft.ScrollMode.AUTO)
