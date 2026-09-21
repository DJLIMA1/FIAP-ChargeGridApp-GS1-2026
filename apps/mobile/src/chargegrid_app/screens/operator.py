import flet as ft

from ..api_client import ApiError
from ..services.location import geocode_address
from ..ui import theme
from ..ui.components import badge, button, card, date_time, field, money, title
from . import onboarding as onboarding_screen
from . import ownership


async def build(app, station_id=None, connector_id=None, device_id=None, offset=0, connector=None,
                claim=False, onboarding=False, point_id=None, step=1):
    profile = await app.api.request('GET','me')
    app.profile = profile
    if not profile.get('operator_enabled') and profile.get('account_type') != 'vendor':
        return title('Gestão de postos','Entre com uma conta de vendedor para vincular equipamentos.')
    if claim:
        return await ownership.build(app, station_id=station_id)
    if onboarding:
        return await onboarding_screen.build(app, station_id=station_id, point_id=point_id, step=step)
    if not profile.get('operator_enabled'):
        return ft.Column([
            title('Configure sua primeira tela', 'Vincule o ESP32 à sua conta de vendedor'),
            card([ft.Icon(ft.Icons.QR_CODE_SCANNER, size=48, color=theme.RED),
                  ft.Text('A tela sem dono mostra um QR de vinculação. Escaneie-o para se tornar o proprietário.',
                          color=theme.TEXT_COLOR),
                  ft.Text('Depois informe nome, endereço e tarifa. O ponto só aparece aos consumidores quando você publicar.',
                          size=13, color=theme.GRAY_TEXT)]),
            button('Escanear QR da tela', app.link('operator', claim=True)),
        ], spacing=15)
    if connector_id:
        if connector_id == 'new':
            return await ownership.build(app, station_id=station_id)
        connector = connector or app.data.get('connector')
        return await connector_form(app,station_id,connector,device_id)
    if station_id == 'new':
        return await station_form(app)
    if station_id:
        station = await app.api.request('GET',f'stations/{station_id}')
        return await station_form(app,station)
    summary = await app.api.request('GET','operator/summary')
    result = await app.api.request('GET','operator/stations',params={'limit':100,'offset':offset})
    stations = result['items']
    controls = [title('Meus postos','Acompanhe seus pontos, recargas e configurações'),
                card([ft.Text('CONFIGURAR UMA NOVA TELA',size=11,weight=ft.FontWeight.BOLD,color=theme.RED),
                      ft.Text('O QR aparece no visor do ESP32 ainda sem dono.',size=15,
                              weight=ft.FontWeight.BOLD,color=theme.TEXT_COLOR),
                      ft.Text('1. Ligue a tela e configure o Wi-Fi, se necessário.\n'
                              '2. Escaneie o QR com sua conta de vendedor.\n'
                              '3. Defina nome, local e tarifa; revise e publique.',
                              size=12,color=theme.GRAY_TEXT),
                      button('Escanear QR da tela',app.link('operator',claim=True))]),
                card([ft.Text('VISÃO GERAL',size=11,weight=ft.FontWeight.BOLD,color=theme.RED),
                      ft.Text(f"{summary['stations']} postos · {summary['total_sessions']} recargas",size=18,
                              weight=ft.FontWeight.BOLD,color=theme.TEXT_COLOR),
                      ft.Text(f"{float(summary['total_energy_wh'])/1000:.3f} kWh entregues · {money(summary['total_estimated_cost'])} estimados",
                              size=12,color=theme.GRAY_TEXT)])]
    for station in stations:
        points = station.get('connectors') or []
        drafts = [point for point in points if not point.get('active') and not point.get('retired')]
        retired = [point for point in points if point.get('retired')]
        online = sum(bool(point.get('online')) for point in points)
        status = ('Tela restaurada' if retired and len(retired) == len(points) else
                  'Configuração pendente' if drafts or not station.get('active') else
                  'Online' if online else 'Offline')
        color = theme.SLATE if retired and len(retired) == len(points) else theme.AMBER if drafts or not station.get('active') else theme.GREEN if online else theme.SLATE
        details = [ft.Row([ft.Text(station['name'],size=19,weight=ft.FontWeight.BOLD,
                                   color=theme.TEXT_COLOR,expand=True),badge(status,color,width=138)],spacing=8),
                   ft.Text(station['address'],size=12,color=theme.GRAY_TEXT),
                   ft.Text(f'{len(points)} pontos · {online} online',size=12,color=theme.GRAY_TEXT)]
        if drafts:
            details.append(button('Concluir configuração',app.link('operator',station_id=station['id'],
                                                                  point_id=drafts[0]['id'],onboarding=True,step=1)))
        if retired:
            details.append(ft.Text('Tela restaurada? Configure o Wi-Fi no ESP32 e escaneie o novo QR para vincular novamente.',
                                   size=12,color=theme.GRAY_TEXT))
        details += [button('Editar estação',app.link('operator',station_id=station['id']),secondary=True),
                    button('Ver recargas',app.link('history',station_id=station['id']),secondary=True)]
        controls.append(card(details))
    if offset + 100 < result['total']:
        controls.append(button('Mais postos',app.link('operator',offset=offset+100)))
    if not stations:
        controls.append(card([ft.Icon(ft.Icons.EV_STATION_OUTLINED,size=35,color=theme.RED),
                              ft.Text('Seu primeiro ponto começa no QR do equipamento.',
                                      color=theme.TEXT_COLOR,weight=ft.FontWeight.BOLD),
                              ft.Text('Vincule-o e siga a configuração guiada para publicar a estação.',
                                      size=12,color=theme.GRAY_TEXT)]))
    controls += [button('Gerenciar cupons',app.link('coupons',manage=True),secondary=True)]
    return ft.Column(controls,spacing=15,scroll=ft.ScrollMode.AUTO)


async def station_form(app, station=None):
    station = station or {}
    name, address = field('Nome do posto',station.get('name','')),field('Endereço',station.get('address',''))
    latitude, longitude = field('Latitude',str(station.get('latitude',''))),field('Longitude',str(station.get('longitude','')))
    active = ft.Switch(label='Posto ativo',value=station.get('active',True),visible=bool(station))
    async def locate():
        try:
            coordinates = await geocode_address(address.value)
        except Exception as exc:
            raise ApiError('Consulta de endereço indisponível. Informe coordenadas.') from exc
        if not coordinates:
            raise ApiError('Endereço não encontrado.')
        latitude.value,longitude.value = map(str,coordinates)
        app.page.update()
    async def save():
        if not name.value.strip() or not address.value.strip():
            raise ApiError('Preencha o nome e o endereço do posto.')
        body = {'name':name.value,'address':address.value,'latitude':float(latitude.value.replace(',','.')),'longitude':float(longitude.value.replace(',','.'))}
        if not -90 <= body['latitude'] <= 90 or not -180 <= body['longitude'] <= 180:
            raise ApiError('As coordenadas do posto são inválidas.')
        if station:
            body['active'] = active.value
        result = await app.api.request('PATCH' if station else 'POST',f"stations/{station['id']}" if station else 'stations',body)
        await app.go('operator',station_id=result['id'])
    controls = [title('Editar posto' if station else 'Novo posto'),card(ft.Column([name,address,button('Localizar endereço',app.action(locate),secondary=True),latitude,longitude,active],spacing=12)),button('Salvar posto',app.action(save))]
    if station:
        controls += [button('Vincular outra tela a este posto',app.link('operator',station_id=station['id'],claim=True))]
        for connector in station['connectors']:
            controls.append(card([ft.Text(f"{connector['public_code']} · {connector['connector_type']}"),ft.Text('Tela restaurada' if connector.get('retired') else 'Online' if connector.get('online') else 'Offline'),button('Editar ponto / dispositivo',app.link('operator',station_id=station['id'],connector_id=connector['id'],connector=connector))]))
    controls.append(button('Voltar à gestão',app.link('operator'),secondary=True))
    return ft.Column(controls,spacing=15,scroll=ft.ScrollMode.AUTO)


async def connector_form(app, station_id, connector=None, device_id=None):
    connector = connector or {}
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
    public, kind, power = field('Código público',connector.get('public_code','')),field('Tipo de conector',connector.get('connector_type','Type 2')),field('Potência kW',str(connector.get('power_kw','7.4')))
    price, duration = field('Tarifa estimada por kWh',str(connector.get('price_per_kwh','1.00'))),field('Limite máximo min',str(connector.get('max_duration_minutes','60')))
    active = ft.Switch(label='Ponto ativo',value=connector.get('active',True),visible=bool(connector))
    device = field('Dispositivo vinculado',linked_device['device_id'] if linked_device else '')
    device.read_only = True
    device.visible = bool(linked_device)
    device_status = ft.Text(
        ('Desvinculado após restauração de fábrica' if linked_device.get('retired') else
         ('Online' if linked_device.get('online') else 'Offline')+' · Último contato: '+date_time(linked_device.get('last_seen')))
        if linked_device else 'Nenhum dispositivo vinculado. Provisione para conectar o ESP32.',
        size=12,color=theme.GRAY_TEXT,
    )
    def update_device(identifier, message):
        device.value = identifier
        device.visible = bool(identifier)
        device_status.value = message
        provision_button.visible = not identifier
        rotate_button.visible = revoke_button.visible = bool(identifier)
        reset_button.visible = bool(identifier)
        reset_info.visible = bool(identifier)
        app.page.update()
    async def save():
        if not public.value.strip() or not kind.value.strip():
            raise ApiError('Informe o código público e o tipo de conector.')
        body = {'public_code':public.value,'connector_type':kind.value,'power_kw':float(power.value.replace(',','.')),'price_per_kwh':price.value.replace(',','.'),'max_duration_minutes':int(duration.value)}
        if not 0 < body['power_kw'] <= 1000 or not 0 <= float(body['price_per_kwh']) <= 10000 or not 1 <= body['max_duration_minutes'] <= 1440:
            raise ApiError('Confira potência, tarifa e duração: os limites devem ser válidos e positivos (a tarifa pode ser zero).')
        if connector:
            body['active'] = active.value
        await app.api.request('PATCH' if connector else 'POST',f"connectors/{connector['id']}" if connector else f'stations/{station_id}/connectors',body)
        await app.go('operator',station_id=station_id)
    async def provision():
        result = await app.api.request('POST',f"connectors/{connector['id']}/device")
        update_device(result['device_id'],'Dispositivo provisionado. Configure a chave no ESP32 para conectar.')
        show_key(app,result)
    async def rotate():
        if not device.value.strip():
            raise ApiError('Informe o ID do dispositivo.')
        result = await app.api.request('POST',f'devices/{device.value.strip()}/rotate-key')
        device_status.value = 'Chave renovada. Atualize a configuração do ESP32 para reconectar.'
        app.page.update()
        show_key(app,result)
    async def revoke():
        if not device.value.strip():
            raise ApiError('Informe o ID do dispositivo.')
        await app.api.request('POST',f'devices/{device.value.strip()}/revoke')
        update_device('','Dispositivo revogado. Provisione novamente para conectar o ESP32.')
        app.notice('Dispositivo revogado; chave anterior recusada.')
    reset_messages = {
        'not_requested': 'Apaga Wi-Fi e vínculo desta tela. O ponto antigo será desativado; histórico e recargas anteriores permanecem.',
        'pending': 'Aguardando a tela confirmar a restauração. Mantenha o ESP32 ligado e conectado.',
        'received': 'A tela recebeu o comando. Aguarde a confirmação antes de desligá-la.',
        'applied': 'Restauração confirmada. Configure o Wi-Fi na tela e escaneie o novo QR para criar outro ponto.',
        'failed': 'A tela não conseguiu restaurar. Verifique se está livre e tente novamente.',
        'expired': 'A tela não confirmou a tempo. Confira a conexão e tente novamente.',
    }
    reset_info = ft.Text(reset_messages.get(reset_state.get('status'), reset_messages['not_requested']),
                         size=12, color=theme.GRAY_TEXT)
    def paint_reset(state):
        reset_state.clear()
        reset_state.update(state)
        status = state.get('status', 'not_requested')
        reset_info.value = reset_messages.get(status, reset_messages['not_requested'])
        reset_button.visible = status in ('not_requested', 'failed', 'expired') and not (linked_device or {}).get('retired')
        if status in ('pending', 'received', 'applied'):
            active.value = False
            active.disabled = True
        if status == 'applied':
            device_status.value = 'Desvinculado após restauração de fábrica'
            rotate_button.visible = revoke_button.visible = False
        app.page.update()
    async def poll_reset():
        if reset_state.get('status') not in ('pending', 'received'):
            return
        state = await app.api.request('GET', f"devices/{linked_device['device_id']}/factory-reset")
        paint_reset(state)
    async def reset_device():
        if hasattr(app, 'prepare_navigation') and not await app.prepare_navigation():
            return
        def cancel(event):
            app.page.pop_dialog()
        async def confirm():
            app.page.pop_dialog()
            state = await app.api.request('POST', f"devices/{linked_device['device_id']}/factory-reset")
            paint_reset(state)
            if state.get('status') in ('pending', 'received'):
                app.set_poll(poll_reset, 5)
        app.page.show_dialog(ft.AlertDialog(
            modal=True,
            title=ft.Text('Restaurar ESP32 de fábrica?'),
            content=ft.Text('O Wi-Fi e o vínculo desta tela serão apagados. O ponto atual sairá de operação, mas seu histórico será preservado. Faça isso somente com a tela online e sem reserva ou recarga. Depois, configure o Wi-Fi e escaneie o novo QR.'),
            actions=[ft.TextButton('Cancelar', on_click=cancel),
                     ft.TextButton('Restaurar ESP32', on_click=app.action(confirm),
                                   style=ft.ButtonStyle(color=theme.RED))],
        ))
    controls = [title('Editar ponto' if connector else 'Novo ponto'),card(ft.Column([public,kind,power,price,duration,active],spacing=12)),ft.Text('Confira os dados e ative o ponto. O posto também precisa estar ativo para aparecer aos consumidores.',size=12,color=theme.GRAY_TEXT),button('Salvar ponto',app.action(save))]
    if connector:
        provision_button = button('Provisionar dispositivo',app.action(provision))
        provision_button.visible = not linked_device
        rotate_button = button('Rotacionar chave',app.action(rotate),secondary=True)
        revoke_button = button('Revogar dispositivo',app.action(revoke),secondary=True)
        rotate_button.visible = revoke_button.visible = bool(linked_device) and not linked_device.get('retired', False)
        reset_button = button('Restaurar ESP32 de fábrica',app.action(reset_device),secondary=True)
        reset_button.visible = bool(linked_device) and not linked_device.get('retired', False) and reset_state.get('status', 'not_requested') in ('not_requested', 'failed', 'expired')
        reset_info.visible = bool(linked_device)
        if linked_device and (linked_device.get('retired') or reset_state.get('status') in ('pending', 'received', 'applied')):
            active.value = False
            active.disabled = True
        controls += [card([ft.Text('Dispositivo ESP32',size=18),ft.Text('Configure a chave no equipamento. Ela é exibida somente após provisionar ou renovar.'),device_status,provision_button,device,rotate_button,revoke_button,ft.Divider(color=theme.LIGHT_GRAY),reset_info,reset_button])]
        if reset_state.get('status') in ('pending', 'received'):
            app.set_poll(poll_reset, 5)
    controls += [button('Voltar ao posto',app.link('operator',station_id=station_id),secondary=True)]
    return ft.Column(controls,spacing=15,scroll=ft.ScrollMode.AUTO)


def show_key(app, result):
    secret = ft.Text(result['device_key'],selectable=True)
    identifier = ft.Text('Device ID: '+result['device_id'],selectable=True)
    async def dismiss(e):
        secret.value = ''
        app.page.pop_dialog()
    dialog = ft.AlertDialog(modal=True,title=ft.Text('Chave exibida uma vez'),content=ft.Column([identifier,secret,ft.Text('Copie para a configuração do ESP32 agora. Não compartilhe. Ao fechar, a chave não será armazenada no app.')],tight=True),actions=[ft.TextButton('Copiei, fechar',on_click=dismiss)])
    app.page.show_dialog(dialog)
