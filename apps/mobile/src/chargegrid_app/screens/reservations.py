import flet as ft

from ..ui import theme
from ..ui.components import button, date_time, title
from ..ui.point_summary import journey_summary, point_summary

LABELS = {'pending_device':'Aguardando confirmação do posto','confirmed':'Reserva confirmada pelo equipamento','cancelling':'Liberação pendente no equipamento','cancelled':'Reserva cancelada','expired':'Reserva expirada','consumed':'Reserva usada na recarga'}
DEMO_LABELS = {'pending_device':'Aguardando confirmação simulada','confirmed':'Reserva simulada confirmada','cancelling':'Liberação simulada pendente','cancelled':'Reserva simulada cancelada','expired':'Reserva simulada expirada','consumed':'Reserva usada na recarga simulada'}


async def build(app):
    demo = getattr(app.api,'is_demo',False) is True
    reservation = await app.api.request('GET','reservations/current')
    if not reservation:
        return ft.Column([title('Minha reserva','Nenhuma reserva ativa.'),button('Buscar um ponto',app.link('stations'))])
    async def update():
        current = await app.api.request('GET','reservations/current')
        if current != reservation:
            await app.go('reservations')
    app.set_poll(update,5)
    async def cancel():
        await app.api.request('POST',f"reservations/{reservation['id']}/cancel")
        app.planning_intent = None
        await app.go('reservations')
    labels = DEMO_LABELS if demo else LABELS
    controls = [title('Minha reserva', labels.get(reservation['status'], reservation['status']))]
    if reservation.get('expires_at') and reservation['status'] == 'confirmed':
        controls.append(ft.Text('Chegue até: '+date_time(reservation['expires_at']), color=theme.TEXT_COLOR))
    if reservation['status'] == 'confirmed':
        connector = reservation.get('connector') or {}
        controls.append(button('Cheguei: informar código',app.link('charging',reservation_id=reservation['id'],
                               point_context=reservation,max_duration=min(30,connector.get('max_duration_minutes') or 30))))
    if reservation['status'] != 'confirmed':
        controls.append(journey_summary(reservation, reservation=True, demo=demo))
    controls.append(point_summary(reservation, 'Ponto reservado'))
    if reservation['status'] == 'confirmed':
        controls.append(ft.ExpansionTile(
            title=ft.Text('Sobre esta confirmação', size=13, color=theme.GRAY_TEXT),
            controls=[journey_summary(reservation, reservation=True, demo=demo)]))
    if demo:
        controls.append(ft.Text('Reserva simulada. Ao chegar ao ponto de exemplo, use #F12345 para testar.',
                                size=12, color=theme.GRAY_TEXT))
    if reservation.get('station_id'):
        controls.append(button('Ver posto e endereço',app.link('stations',station_id=reservation['station_id']),secondary=True))
    if reservation['status'] in ('confirmed','pending_device'):
        controls.append(button('Cancelar reserva',app.action(cancel),secondary=True))
    controls.append(ft.Text('O estado é atualizado a cada 5 segundos.',size=12,color=theme.GRAY_TEXT))
    return ft.Column(controls,spacing=15,scroll=ft.ScrollMode.AUTO)
