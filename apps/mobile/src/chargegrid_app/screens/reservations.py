import flet as ft

from ..ui.components import button, card, date_time, title

LABELS = {'pending_device':'Aguardando confirmação do posto','confirmed':'Reserva confirmada pelo equipamento','cancelling':'Liberação pendente no equipamento','cancelled':'Reserva cancelada','expired':'Reserva expirada','consumed':'Reserva usada na recarga'}


async def build(app):
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
        await app.go('reservations')
    details = [ft.Text(LABELS.get(reservation['status'],reservation['status']),size=18)]
    if reservation.get('expires_at'):
        details.append(ft.Text('Chegue até: '+date_time(reservation['expires_at'])))
    else:
        details.append(ft.Text('O prazo de chegada aparecerá assim que o ponto confirmar.'))
    controls = [title('Minha reserva'),card(details)]
    if reservation['status'] == 'confirmed':
        controls.append(button('Cheguei: informar código',app.link('charging',reservation_id=reservation['id'])))
    if reservation['status'] in ('confirmed','pending_device'):
        controls.append(button('Cancelar reserva',app.action(cancel),secondary=True))
    controls.append(ft.Text('Cancelar solicita a liberação; disponibilidade depende da confirmação física. Atualiza a cada 5 s.',size=12))
    return ft.Column(controls,spacing=15,scroll=ft.ScrollMode.AUTO)
