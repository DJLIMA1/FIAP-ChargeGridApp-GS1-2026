"""Credentials and factory reset belong to station data, separately from charger editing."""

import flet as ft

from .. import api_cache
from ..api_client import ApiError
from ..ui import design, theme
from ..ui.components import date_time
from . import chargers


async def build(app, station):
    status = ft.Container(chargers.screens_card(station), data='central-status')

    async def updated():
        try:
            with api_cache.network_only():
                fresh = await app.api.request('GET', f"stations/{station['id']}")
        except ApiError:
            return  # An acknowledged write must not look failed because its follow-up read failed.
        station.update({key: fresh[key] for key in ('screens', 'screen_online', 'connectors') if key in fresh})
        status.content = chargers.screens_card(station)
        app.page.update()

    ids = list(dict.fromkeys(screen.get('connector_id') for screen in chargers.station_screens(station)
                             if screen.get('connector_id')))
    if not ids:
        target = chargers.screen_connector_id(station)
        ids = [target] if target else []
    sections = [status] if status.content is not None else []
    polls = []
    polling = False

    async def poll_all():
        for poll in polls:
            await poll()

    def ensure_poll():
        nonlocal polling
        if not polling:
            polling = True
            app.set_poll(poll_all, 5)

    for identifier in ids:
        connector = next((p for p in station.get('connectors', []) if p['id'] == identifier), None)
        if connector is None:
            continue
        control, poll = await maintenance(app, connector, updated, ensure_poll)
        sections.append(control)
        polls.append(poll)

    from .setup_ui import cta
    is_demo = bool(getattr(app.api, 'is_demo', False))
    sections.append(cta('Adicionar central simulada a este posto' if is_demo else 'Vincular outra central a este posto',
                        app.link('operator', station_id=station['id'], claim=True), primary=False, weight='semibold'))
    return ft.Column(sections, spacing=15, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)


async def maintenance(app, connector, updated, ensure_poll):
    from . import operator
    from .operator import _mini_button
    is_demo = bool(getattr(app.api, 'is_demo', False))
    linked_device = None
    reset_state = {'status': 'not_requested'}
    if connector:
        try:
            linked_device = await app.api.request('GET',f"connectors/{connector['id']}/device")
        except ApiError as exc:
            if exc.status != 404:
                raise
    if linked_device and not linked_device.get('retired'):
        reset_state = await app.api.request('GET',f"devices/{linked_device['device_id']}/factory-reset")
    elif linked_device and linked_device.get('retired'):
        reset_state = {'status': 'applied'}

    device = design.txt(linked_device['device_id'] if linked_device else '', 12.5, 'bold', data='device-id',
                        text_align=ft.TextAlign.END)
    device_status = ft.Text(
        ('Desvinculado após restauração de fábrica' if linked_device.get('retired') else
         'Último contato: '+date_time(linked_device.get('last_seen')))
        if linked_device else 'Nenhuma central simulada vinculada.' if is_demo else
        'Nenhuma central vinculada. Provisione uma credencial abaixo.',
        size=13,color=theme.TEXT_COLOR,expand=True,font_family=design.FONT,
    )
    def update_device(identifier, message):
        nonlocal linked_device
        linked_device = {'device_id':identifier,'retired':False} if identifier else None
        reset_state.clear()
        reset_state['status'] = 'not_requested'
        device.value = identifier
        device_row.visible = bool(identifier)
        device_status.value = message
        provision_row.visible = provision_button.visible = not identifier
        key_row.visible = rotate_button.visible = revoke_button.visible = bool(identifier)
        reset_box.visible = bool(identifier)
        reset_button.visible = bool(identifier)
        reset_info.visible = False
        reset_info.value = reset_messages['not_requested']
        app.page.update()
    async def provision():
        result = await app.api.request('POST',f"connectors/{connector['id']}/device")
        update_device(result['device_id'],'Credencial simulada criada. Nada precisa ser instalado.' if is_demo else
                      'Credencial criada. Configure a chave na central para conectar.')
        operator.show_key(app,result)
        await updated()
    async def rotate():
        if not device.value.strip():
            raise ApiError('Informe o ID do dispositivo.')
        result = await app.api.request('POST',f'devices/{device.value.strip()}/rotate-key')
        device_status.value = 'Chave fictícia renovada nesta demonstração.' if is_demo else 'Chave renovada. Atualize a configuração da central para reconectar.'
        app.page.update()
        operator.show_key(app,result)
        await updated()
    async def revoke():
        if not device.value.strip():
            raise ApiError('Informe o ID do dispositivo.')
        await app.api.request('POST',f'devices/{device.value.strip()}/revoke')
        update_device('','Credencial simulada revogada. Simule outra quando quiser.' if is_demo else
                      'Credencial revogada. Provisione outra para reconectar a central.')
        app.notice('Revogação simulada concluída.' if is_demo else 'Central revogada; chave anterior recusada.')
        await updated()
    reset_messages = {
        'not_requested': 'Remove o vínculo e preserva o Wi-Fi. Os carregadores sairão de operação; o histórico fica.',
        'pending': 'Aguardando a central confirmar a restauração. Mantenha a central ligada e conectada.',
        'received': 'A central recebeu o comando. Aguarde a confirmação antes de desligá-la.',
        'applied': 'Restauração confirmada. O Wi-Fi foi preservado. Escaneie o novo QR para vincular a central novamente.',
        'failed': 'A central não conseguiu restaurar. Verifique se está livre e tente novamente.',
        'expired': 'A central não confirmou a tempo. Confira a conexão e tente novamente.',
    }
    if is_demo:
        reset_messages.update({
            'not_requested':'Desativa este ponto fictício e mantém o histórico da demonstração.',
            'pending':'Aguardando a confirmação simulada da restauração.',
            'received':'A central fictícia recebeu o comando simulado.',
            'applied':'Restauração simulada confirmada. Adicione outra central simulada para criar um novo vínculo.',
            'failed':'A restauração simulada falhou. Encerre reservas e recargas simuladas e tente novamente.',
            'expired':'O comando simulado expirou. Tente novamente nesta demonstração.',
        })
    initial_status = reset_state.get('status', 'not_requested')
    reset_info = ft.Text(reset_messages.get(initial_status, reset_messages['not_requested']),
                         size=12, color=theme.WARNING, visible=bool(linked_device) and initial_status != 'not_requested')
    def paint_reset(state):
        reset_state.clear()
        reset_state.update(state)
        status = state.get('status', 'not_requested')
        reset_info.value = reset_messages.get(status, reset_messages['not_requested'])
        reset_info.visible = status != 'not_requested'
        reset_button.visible = status in ('not_requested', 'failed', 'expired') and not (linked_device or {}).get('retired')
        if status in ('pending', 'received', 'applied'):
            key_row.visible = rotate_button.visible = revoke_button.visible = False
        elif status in ('failed', 'expired'):
            key_row.visible = rotate_button.visible = revoke_button.visible = True
        if status == 'applied':
            if linked_device:
                linked_device['retired'] = True
            device_status.value = 'Desvinculado após restauração de fábrica'
        app.page.update()
    async def poll_reset():
        if not linked_device or reset_state.get('status') not in ('pending', 'received'):
            return
        state = await app.api.request('GET', f"devices/{linked_device['device_id']}/factory-reset")
        paint_reset(state)
        await updated()
    async def reset_device():
        if hasattr(app, 'prepare_navigation') and not await app.prepare_navigation():
            return
        def cancel(event):
            app.page.pop_dialog()
        async def confirm():
            app.page.pop_dialog()
            if not linked_device or linked_device.get('retired'):
                raise ApiError('Abra novamente o ponto para conferir o dispositivo vinculado.')
            state = await app.api.request('POST', f"devices/{linked_device['device_id']}/factory-reset")
            paint_reset(state)
            await updated()
            if state.get('status') in ('pending', 'received'):
                ensure_poll()
        app.page.show_dialog(ft.AlertDialog(
            modal=True,
            title=ft.Text('Simular restauração da central?' if is_demo else 'Restaurar central de fábrica?'),
            content=ft.Text('Esta ação altera apenas o ponto fictício desta demonstração. Ele será desativado e o histórico simulado será mantido. Nenhum dispositivo físico ou Wi-Fi será alterado.' if is_demo else
                            'O vínculo desta central será removido e o Wi-Fi será preservado. Os carregadores desta central sairão de operação, mas seu histórico será mantido. Faça isso somente com a central online e sem reserva ou recarga. Depois, escaneie o novo QR para vincular a central novamente.'),
            actions=[ft.TextButton('Cancelar', on_click=cancel),
                     ft.TextButton('Simular restauração' if is_demo else 'Restaurar', on_click=app.action(confirm),
                                   style=ft.ButtonStyle(color=theme.RED))],
        ))

    provision_button = _mini_button('Provisionar',app.action(provision),'primary')
    rotate_button = _mini_button('Rotacionar',app.action(rotate))
    revoke_button = _mini_button('Revogar',app.action(revoke))
    reset_button = _mini_button('Restaurar',app.action(reset_device),'danger')
    for button in (rotate_button, revoke_button):
        button.expand = True
    provision_row = ft.Row([design.txt('Sem credencial. Gere uma para a central conectar.' if not is_demo else
                                       'Sem credencial simulada.', 11.5, 'regular', theme.GRAY_TEXT, expand=True),
                            provision_button], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    key_row = ft.Row([rotate_button, revoke_button], spacing=10)
    reset_box = ft.Container(
        ft.Row([design.txt(reset_messages['not_requested'], 10.5, 'regular', theme.GRAY_TEXT, expand=True),
                reset_button], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor=theme.WARN_BG, border=ft.Border.all(1, ft.Colors.with_opacity(0.45, theme.RED)),
        border_radius=design.RADIUS_BTN, padding=ft.Padding(left=12, right=10, top=10, bottom=10))
    device_row = chargers.row('ID da central', device)
    maintenance_ok = bool(linked_device) and not linked_device.get('retired', False) and \
        reset_state.get('status', 'not_requested') not in ('pending', 'received', 'applied')
    provision_row.visible = provision_button.visible = not linked_device
    key_row.visible = rotate_button.visible = revoke_button.visible = maintenance_ok
    reset_button.visible = bool(linked_device) and not linked_device.get('retired', False) and reset_state.get('status', 'not_requested') in ('not_requested', 'failed', 'expired')
    reset_box.visible = device_row.visible = bool(linked_device)
    content = chargers.card('Manutenção da central', *([design.txt('Credencial e restauração simuladas', 11, 'bold', theme.GRAY_TEXT)] if is_demo else []), device_status, device_row, reset_info,
                            provision_row, key_row, reset_box,
                            subtitle=connector.get('public_code') or 'Central')
    if reset_state.get('status') in ('pending', 'received'):
        ensure_poll()
    return content, poll_reset
