import flet as ft

from ..ui.components import button, date_time, title
from .charging import session_card


async def build(app, station_id=None, offset=0):
    path = f'stations/{station_id}/charging-sessions' if station_id else 'me/charging-sessions'
    result = await app.api.request('GET',path,params={'limit':20,'offset':offset})
    controls = [title('Histórico do posto' if station_id else 'Meu histórico','Acompanhe suas recargas e os valores estimados.')]
    for session in result['items']:
        controls += [session_card(session),ft.Text('Início: '+date_time(session.get('started_at'))),ft.Text('Fim: '+date_time(session.get('ended_at')))]
    if not result['items']:
        controls.append(ft.Text('Nenhuma sessão registrada.'))
    if offset:
        controls.append(button('Anterior',app.link('history',station_id=station_id,offset=max(0,offset-20)),secondary=True))
    if offset+20 < result['total']:
        controls.append(button('Mais sessões',app.link('history',station_id=station_id,offset=offset+20)))
    return ft.Column(controls,spacing=15,scroll=ft.ScrollMode.AUTO)
