import flet as ft

from ..ui import theme
from ..ui.components import button, card, date_time, title
from ..ui.point_summary import point_summary

LABELS = {'pending_device':'Aguardando confirmação do posto','confirmed':'Reserva confirmada pelo equipamento','cancelling':'Liberação pendente no equipamento','cancelled':'Reserva cancelada','expired':'Reserva expirada','consumed':'Reserva usada na recarga'}
DEMO_LABELS = {'pending_device':'Aguardando confirmação simulada','confirmed':'Reserva simulada confirmada','cancelling':'Liberação simulada pendente','cancelled':'Reserva simulada cancelada','expired':'Reserva simulada expirada','consumed':'Reserva usada na recarga simulada'}


async def build(app):
    demo = getattr(app.api,'is_demo',False) is True
    demo_controls = [card([ft.Text('CONTA DEMO · RESERVA SIMULADA',weight=ft.FontWeight.BOLD,color=theme.RED),
                           ft.Text('Esta reserva usa somente um posto de exemplo. Para testar a chegada, use o código #F12345.',size=13,color=theme.GRAY_TEXT)])] if demo else []
    reservation = await app.api.request('GET','reservations/current')
    if not reservation:
        return ft.Column(demo_controls+[title('Minha reserva','Nenhuma reserva ativa.'),button('Buscar um ponto',app.link('stations'))])
    async def update():
        current = await app.api.request('GET','reservations/current')
        if current != reservation:
            await app.go('reservations')
    app.set_poll(update,5)
    async def cancel():
        await app.api.request('POST',f"reservations/{reservation['id']}/cancel")
        await app.go('reservations')
    labels = DEMO_LABELS if demo else LABELS
    details = [ft.Text(labels.get(reservation['status'],reservation['status']),size=18,color=theme.TEXT_COLOR)]
    if reservation.get('expires_at'):
        details.append(ft.Text('Chegue até: '+date_time(reservation['expires_at'])))
    else:
        details.append(ft.Text('O prazo de chegada aparecerá assim que o ponto confirmar.'))
    explanations = {
        'pending_device':'Seu pedido foi enviado. Aguarde o posto confirmar antes de se deslocar.',
        'confirmed':'O ponto está reservado para você até o horário abaixo. Ao chegar, informe o código #F da tela.',
        'cancelling':'A liberação foi solicitada. O ponto só fica livre após a confirmação do equipamento.',
        'expired':'O prazo terminou. Encontre um ponto disponível para tentar novamente.',
        'cancelled':'A reserva foi cancelada.',
        'consumed':'Sua reserva foi usada para iniciar uma recarga.',
    }
    if demo:
        explanations.update(pending_device='Aguarde o simulador confirmar a reserva.',
                            confirmed='O ponto de exemplo está reservado. Toque em Cheguei e use #F12345 para testar uma recarga.',
                            cancelling='Aguarde o simulador confirmar a liberação do ponto.')
    controls = [title('Minha reserva',explanations.get(reservation['status'],'')),
                point_summary(reservation,'Ponto reservado'),card(details)]
    if reservation['status'] == 'confirmed':
        connector = reservation.get('connector') or {}
        controls.append(button('Cheguei: informar código',app.link('charging',reservation_id=reservation['id'],
                               point_context=reservation,max_duration=min(30,connector.get('max_duration_minutes') or 30))))
    if reservation.get('station_id'):
        controls.append(button('Ver posto e endereço',app.link('stations',station_id=reservation['station_id']),secondary=True))
    if reservation['status'] in ('confirmed','pending_device'):
        controls.append(button('Cancelar reserva',app.action(cancel),secondary=True))
    controls.append(ft.Text('O estado é atualizado a cada 5 segundos.',size=12,color=theme.GRAY_TEXT))
    return ft.Column(demo_controls+controls,spacing=15,scroll=ft.ScrollMode.AUTO)
