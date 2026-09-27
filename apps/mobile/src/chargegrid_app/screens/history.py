import flet as ft

from ..ui import theme
from ..ui.components import button, card, date_time, title
from ..ui.point_summary import point_summary
from .charging import session_card


async def build(app, station_id=None, offset=0, manage=False):
    demo = getattr(app.api,'is_demo',False) is True
    demo_controls = [card([ft.Text('CONTA DEMO · HISTÓRICO SIMULADO',weight=ft.FontWeight.BOLD,color=theme.RED),
                           ft.Text('Sessões de exemplo e testes feitos nesta conta. Estes valores não são cobranças ou medições reais.',size=13,color=theme.GRAY_TEXT)])] if demo else []
    if manage and not app.profile.get('operator_enabled'):
        return ft.Column(demo_controls+[
            title('Histórico dos meus postos', 'Vincule sua primeira tela para começar a registrar recargas nos seus postos.'),
            button('Ir para meus postos', app.link('operator')),
        ], spacing=15)
    path = (f'stations/{station_id}/charging-sessions' if station_id else
            'operator/charging-sessions' if manage else 'me/charging-sessions')
    result = await app.api.request('GET',path,params={'limit':20,'offset':offset})
    controls = [title('Histórico do posto' if station_id else 'Histórico dos meus postos' if manage else 'Meu histórico',
                      'Sessões registradas e valores estimados. Nenhuma cobrança real.')]
    for session in result['items']:
        controls += [point_summary(session,'Local da recarga'),session_card(session,demo=demo),ft.Text('Início: '+date_time(session.get('started_at'))),ft.Text('Fim: '+date_time(session.get('ended_at')))]
    if not result['items']:
        controls.append(ft.Text('Nenhuma sessão registrada.'))
    if offset:
        controls.append(button('Anterior',app.link('history',station_id=station_id,offset=max(0,offset-20),**({'manage':True} if manage else {})),secondary=True))
    if offset+20 < result['total']:
        controls.append(button('Mais sessões',app.link('history',station_id=station_id,offset=offset+20,**({'manage':True} if manage else {}))))
    return ft.Column(demo_controls+controls,spacing=15,scroll=ft.ScrollMode.AUTO)
