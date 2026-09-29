from decimal import Decimal

import flet as ft

from ..api_client import ApiError
from ..services.location import geocode_address
from ..ui import theme
from ..ui.components import badge, button, card, date_time, field, money, title
from . import onboarding as onboarding_screen
from . import ownership


async def build(app, station_id=None, connector_id=None, device_id=None, offset=0, connector=None,
                claim=False, onboarding=False, point_id=None, step=1, existing_station=False):
    is_demo = bool(getattr(app.api,'is_demo',False))
    profile = await app.api.request('GET','me')
    app.profile = profile
    if not profile.get('operator_enabled') and profile.get('account_type') != 'vendor':
        return title('Gestão de postos','Entre com uma conta de operador para vincular equipamentos.')
    if claim:
        return await ownership.build(app, station_id=station_id)
    if onboarding:
        return await onboarding_screen.build(app, station_id=station_id, point_id=point_id,
                                             step=step, existing_station=existing_station)
    if not profile.get('operator_enabled'):
        return ft.Column([
            title('Configure seu primeiro ponto simulado' if is_demo else 'Configure sua primeira tela',
                  'Experimente a gestão de postos com dados fictícios.' if is_demo else 'Vincule o ESP32 à sua conta de operador'),
            card([ft.Icon(ft.Icons.QR_CODE_SCANNER, size=48, color=theme.RED),
                  ft.Text('Adicione um equipamento simulado para criar seu posto. Todo o processo acontece nesta demonstração.' if is_demo else
                          'A tela sem dono mostra um QR de vinculação. Escaneie-o para se tornar o proprietário.',
                          color=theme.TEXT_COLOR),
                  ft.Text('Depois informe nome, endereço e tarifa. O ponto só aparece aos motoristas quando você publicar.',
                          size=13, color=theme.GRAY_TEXT),
                  ft.Text('Posto é o local com endereço. Cada ponto é um equipamento de recarga nesse local.',
                          size=13, color=theme.GRAY_TEXT)]),
            button('Adicionar equipamento simulado' if is_demo else 'Escanear QR da tela', app.link('operator', claim=True)),
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
    instructions = card([
        ft.Text('COMO FUNCIONA',size=15,font_family='BarlowCondensed',weight=ft.FontWeight.BOLD,color=theme.TEXT_COLOR),
        ft.Text('Adicione um equipamento fictício para experimentar a gestão.' if is_demo else
                'O QR aparece no visor do ESP32 ainda sem dono.',size=13,color=theme.TEXT_COLOR),
        ft.Text('1. Adicione um equipamento simulado.\n'
                '2. Configure nome, endereço de exemplo e tarifa.\n'
                '3. Revise, publique e teste a recarga simulada.' if is_demo else
                '1. Ligue a tela e configure o Wi-Fi, se necessário.\n'
                '2. Escaneie o QR com sua conta de operador.\n'
                '3. Defina nome, local e tarifa; revise e publique.',size=12,color=theme.GRAY_TEXT),
        ft.Text('Posto é o endereço; ponto é o equipamento. O botão no topo cria um novo posto. '
                'Para outro ponto no mesmo endereço, use “Vincular” no posto abaixo.',size=12,color=theme.GRAY_TEXT),
    ],visible=False)

    async def toggle_instructions():
        instructions.visible = not instructions.visible
        help_button.content.value = 'Ocultar orientações' if instructions.visible else 'Como funciona'
        app.page.update()

    help_button = button('Como funciona',app.action(toggle_instructions),secondary=True)
    help_button.height = 40
    help_button.content.size = 12
    help_button.width = 124
    controls = [
        button('Adicionar equipamento simulado' if is_demo else 'Escanear QR da tela',app.link('operator',claim=True)),
        ft.Row([
            ft.Text(f"{summary['stations']} postos · {summary['total_sessions']} recargas",size=18,
                    font_family='BarlowCondensed',weight=ft.FontWeight.BOLD,color=theme.TEXT_COLOR,expand=True),
            help_button,
        ],spacing=8),
        ft.Text(f"{float(summary['total_energy_wh'])/1000:.3f} kWh registrados · {money(summary['total_estimated_cost'])} estimados",
                size=12,color=theme.GRAY_TEXT),
        ft.Text('Energia simulada nesta conta.' if is_demo else
                'O total pode incluir energia simulada, medida ou estimada. Consulte a origem em cada sessão.',
                size=12,color=theme.GRAY_TEXT),
        instructions,
    ]
    for station in stations:
        points = station.get('connectors') or []
        disabled = [point for point in points if not point.get('active') and not point.get('retired')]
        retired = [point for point in points if point.get('retired')]
        online = sum(bool(point.get('online')) for point in points if not point.get('retired'))
        status = ('Tela restaurada' if retired and len(retired) == len(points) else
                  'Posto desativado' if not station.get('active') else
                  'Pontos desativados' if disabled and len(disabled) + len(retired) == len(points) else
                  'Online' if online else 'Offline')
        color = theme.SLATE if retired and len(retired) == len(points) else theme.AMBER if disabled or not station.get('active') else theme.GREEN if online else theme.SLATE
        details = [ft.Row([ft.Text(station['name'],size=18,font_family='BarlowCondensed',weight=ft.FontWeight.BOLD,
                                   color=theme.TEXT_COLOR,expand=True),badge(status,color,width=138)],spacing=8),
                   ft.Text(station['address'],size=12,color=theme.GRAY_TEXT),
                   ft.Text(f'{len(points)} pontos · {online} online',size=12,color=theme.GRAY_TEXT)]
        if disabled:
            details.append(ft.Text(f'{len(disabled)} ponto(s) desativado(s). Revise para publicar ou reativar.',
                                   size=12,color=theme.GRAY_TEXT))
        if retired:
            details.append(ft.Text('Equipamento simulado restaurado. Adicione outro equipamento para testar um novo vínculo.' if is_demo else
                                   'Tela restaurada? O Wi-Fi foi preservado. Escaneie o novo QR para vincular novamente.',
                                   size=12,color=theme.GRAY_TEXT))
        if is_demo:
            from ..demo import DEMO_PRESENCE_CODE
            details.append(ft.Text(f'Recarga de demonstração: {DEMO_PRESENCE_CODE}',size=12,color=theme.GRAY_TEXT))
        configure = button('Revisar pontos' if disabled else 'Configurar',app.link('operator',station_id=station['id']),secondary=True)
        configure.height = 40
        if not disabled:
            configure.content = ft.Row([
                ft.Image(src='/figma/configure.svg',width=16,height=16,color=theme.TEXT_COLOR),configure.content,
            ],spacing=6,alignment=ft.MainAxisAlignment.CENTER,tight=True)
        actions = [button('Vincular',app.link('operator',station_id=station['id'],claim=True),secondary=True),
                   button('Recargas',app.link('history',station_id=station['id']),secondary=True)]
        for action in actions:
            action.expand = True
            action.height = 40
            action.content.size = 13
        details += [configure,ft.Row(actions,spacing=8)]
        controls.append(card(ft.Column(details,spacing=6)))
    if offset + 100 < result['total']:
        controls.append(button('Mais postos',app.link('operator',offset=offset+100)))
    if offset:
        controls.append(button('Postos anteriores',app.link('operator',offset=max(0,offset-100)),secondary=True))
    if not stations:
        controls.append(card([ft.Icon(ft.Icons.EV_STATION_OUTLINED,size=35,color=theme.RED),
                              ft.Text('Seu primeiro ponto começa adicionando um equipamento simulado.' if is_demo else
                                      'Seu primeiro ponto começa no QR do equipamento.',
                                      color=theme.TEXT_COLOR,weight=ft.FontWeight.BOLD),
                              ft.Text('Vincule-o e siga a configuração guiada para publicar o posto.',
                                      size=12,color=theme.GRAY_TEXT)]))
    controls += [button('Gerenciar cupons',app.link('coupons',manage=True),secondary=True)]
    return ft.Column(controls,spacing=16,scroll=ft.ScrollMode.AUTO)


async def station_form(app, station=None):
    is_demo = bool(getattr(app.api,'is_demo',False))
    station = station or {}
    name, address = field('Nome do posto',station.get('name','')),field('Endereço',station.get('address',''))
    latitude, longitude = field('Latitude',str(station.get('latitude',''))),field('Longitude',str(station.get('longitude','')))
    active = ft.Switch(label='Posto ativo',value=station.get('active',True),visible=bool(station))
    async def locate():
        if is_demo:
            latitude.value,longitude.value = '-23.55','-46.63'
            app.page.update()
            return
        try:
            coordinates = await geocode_address(address.value)
        except Exception as exc:
            raise ApiError('Consulta de endereço indisponível. Informe coordenadas.') from exc
        if not coordinates:
            raise ApiError('Endereço não encontrado.')
        latitude.value,longitude.value = map(str,coordinates)
        app.page.update()
    async def save():
        body = {'name':onboarding_screen._required(name,'nome do posto',100),
                'address':onboarding_screen._required(address,'endereço',300),
                'latitude':onboarding_screen._number(latitude,'Latitude',-90,90),
                'longitude':onboarding_screen._number(longitude,'Longitude',-180,180)}
        if station:
            body['active'] = active.value
        result = await app.api.request('PATCH' if station else 'POST',f"stations/{station['id']}" if station else 'stations',body)
        if hasattr(app,'mark_saved'):
            app.mark_saved()
        await app.go('operator',station_id=result['id'])
    controls = [title('Editar posto' if station else 'Novo posto',
                      'O posto reúne os pontos instalados no mesmo endereço.'),
                card(ft.Column([name,address,button('Usar localização de exemplo' if is_demo else 'Localizar endereço',app.action(locate),secondary=True),latitude,longitude,active],spacing=12)),
                ft.Text('Nome, endereço e disponibilidade do posto valem para todos os seus pontos.',size=12,color=theme.GRAY_TEXT),
                button('Salvar posto',app.action(save))]
    if station:
        controls += [button('Adicionar ponto simulado a este posto' if is_demo else 'Vincular outra tela a este posto',app.link('operator',station_id=station['id'],claim=True))]
        for connector in station['connectors']:
            status = ('Tela restaurada' if connector.get('retired') else
                      'Desativado' if not connector.get('active') else
                      'Online' if connector.get('online') else 'Offline')
            details = [ft.Text(f"{connector['public_code']} · {connector['connector_type']}",weight=ft.FontWeight.BOLD),
                       ft.Text(status)]
            if is_demo:
                from ..demo import DEMO_PRESENCE_CODE
                details.append(ft.Text(f'Código de presença da demonstração: {DEMO_PRESENCE_CODE}',size=12,color=theme.GRAY_TEXT))
            if not connector.get('active') and not connector.get('retired'):
                shared = bool(station.get('active') or len(station['connectors']) > 1)
                details.append(button('Revisar e ativar ponto',app.link('operator',station_id=station['id'],
                                      point_id=connector['id'],onboarding=True,step=2 if shared else 1,
                                      **({'existing_station':True} if shared else {}))))
            details.append(button('Editar ponto / dispositivo',app.link('operator',station_id=station['id'],connector_id=connector['id'],connector=connector),secondary=True))
            controls.append(card(details))
    controls.append(button('Voltar à gestão',app.link('operator'),secondary=True))
    return ft.Column(controls,spacing=15,scroll=ft.ScrollMode.AUTO)


async def connector_form(app, station_id, connector=None, device_id=None):
    is_demo = bool(getattr(app.api,'is_demo',False))
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
        if linked_device else 'Nenhum dispositivo simulado vinculado. Simule o provisionamento para continuar.' if is_demo else
        'Nenhum dispositivo vinculado. Provisione para conectar o ESP32.',
        size=12,color=theme.GRAY_TEXT,
    )
    def update_device(identifier, message):
        nonlocal linked_device
        linked_device = {'device_id':identifier,'retired':False} if identifier else None
        reset_state.clear()
        reset_state['status'] = 'not_requested'
        device.value = identifier
        device.visible = bool(identifier)
        device_status.value = message
        provision_button.visible = not identifier
        rotate_button.visible = revoke_button.visible = bool(identifier)
        reset_button.visible = bool(identifier)
        reset_info.visible = bool(identifier)
        reset_info.value = reset_messages['not_requested']
        app.page.update()
    async def save():
        body = {'public_code':onboarding_screen._required(public,'código público',50),
                'connector_type':onboarding_screen._required(kind,'tipo de conector',50),
                'power_kw':onboarding_screen._number(power,'Potência',Decimal('0.001'),1000),
                'price_per_kwh':onboarding_screen._number(price,'Tarifa',0,10000),
                'max_duration_minutes':onboarding_screen._number(duration,'Tempo máximo',1,1440,integer=True)}
        if connector:
            body['active'] = active.value
        await app.api.request('PATCH' if connector else 'POST',f"connectors/{connector['id']}" if connector else f'stations/{station_id}/connectors',body)
        if hasattr(app,'mark_saved'):
            app.mark_saved()
        await app.go('operator',station_id=station_id)
    async def provision():
        result = await app.api.request('POST',f"connectors/{connector['id']}/device")
        update_device(result['device_id'],'Dispositivo simulado provisionado. Nenhuma chave precisa ser instalada em um ESP32.' if is_demo else
                      'Dispositivo provisionado. Configure a chave no ESP32 para conectar.')
        show_key(app,result)
    async def rotate():
        if not device.value.strip():
            raise ApiError('Informe o ID do dispositivo.')
        result = await app.api.request('POST',f'devices/{device.value.strip()}/rotate-key')
        device_status.value = 'Chave fictícia renovada nesta demonstração.' if is_demo else 'Chave renovada. Atualize a configuração do ESP32 para reconectar.'
        app.page.update()
        show_key(app,result)
    async def revoke():
        if not device.value.strip():
            raise ApiError('Informe o ID do dispositivo.')
        await app.api.request('POST',f'devices/{device.value.strip()}/revoke')
        update_device('','Dispositivo simulado revogado. Simule o provisionamento para criar outra credencial.' if is_demo else
                      'Dispositivo revogado. Provisione novamente para conectar o ESP32.')
        app.notice('Revogação simulada concluída.' if is_demo else 'Dispositivo revogado; chave anterior recusada.')
    reset_messages = {
        'not_requested': 'Remove o vínculo desta tela e preserva o Wi-Fi. O ponto antigo será desativado; histórico e recargas anteriores permanecem.',
        'pending': 'Aguardando a tela confirmar a restauração. Mantenha o ESP32 ligado e conectado.',
        'received': 'A tela recebeu o comando. Aguarde a confirmação antes de desligá-la.',
        'applied': 'Restauração confirmada. O Wi-Fi foi preservado. Escaneie o novo QR para vincular a tela novamente.',
        'failed': 'A tela não conseguiu restaurar. Verifique se está livre e tente novamente.',
        'expired': 'A tela não confirmou a tempo. Confira a conexão e tente novamente.',
    }
    if is_demo:
        reset_messages.update({
            'not_requested':'A restauração simulada desativa este ponto fictício e mantém seu histórico de demonstração.',
            'pending':'Aguardando a confirmação simulada da restauração.',
            'received':'O equipamento fictício recebeu o comando simulado.',
            'applied':'Restauração simulada confirmada. Adicione outro equipamento simulado para criar um novo vínculo.',
            'failed':'A restauração simulada falhou. Encerre reservas e recargas simuladas e tente novamente.',
            'expired':'O comando simulado expirou. Tente novamente nesta demonstração.',
        })
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
            rotate_button.visible = revoke_button.visible = False
        elif status in ('failed', 'expired'):
            active.disabled = False
            rotate_button.visible = revoke_button.visible = True
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
            if state.get('status') in ('pending', 'received'):
                app.set_poll(poll_reset, 5)
        app.page.show_dialog(ft.AlertDialog(
            modal=True,
            title=ft.Text('Simular restauração do equipamento?' if is_demo else 'Restaurar ESP32 de fábrica?'),
            content=ft.Text('Esta ação altera apenas o ponto fictício desta demonstração. Ele será desativado e o histórico simulado será mantido. Nenhum dispositivo físico ou Wi-Fi será alterado.' if is_demo else
                            'O vínculo desta tela será removido e o Wi-Fi será preservado. O ponto atual sairá de operação, mas seu histórico será mantido. Faça isso somente com a tela online e sem reserva ou recarga. Depois, escaneie o novo QR para vincular a tela novamente.'),
            actions=[ft.TextButton('Cancelar', on_click=cancel),
                     ft.TextButton('Simular restauração' if is_demo else 'Restaurar ESP32', on_click=app.action(confirm),
                                   style=ft.ButtonStyle(color=theme.RED))],
        ))
    controls = [title('Editar ponto' if connector else 'Novo ponto'),card(ft.Column([public,kind,power,price,duration,active],spacing=12)),ft.Text('Confira os dados e ative o ponto. O posto também precisa estar ativo para aparecer aos motoristas.',size=12,color=theme.GRAY_TEXT),button('Salvar ponto',app.action(save))]
    if is_demo:
        from ..demo import DEMO_PRESENCE_CODE
        controls.insert(1,card([
            ft.Text('EQUIPAMENTO SIMULADO',size=11,weight=ft.FontWeight.BOLD,color=theme.RED),
            ft.Text(f'Use {DEMO_PRESENCE_CODE} para testar a recarga no modo motorista. Nenhum dispositivo físico será acionado.',size=13,color=theme.GRAY_TEXT),
        ]))
    if connector:
        provision_button = button('Simular provisionamento' if is_demo else 'Provisionar dispositivo',app.action(provision))
        provision_button.visible = not linked_device
        rotate_button = button('Simular renovação de chave' if is_demo else 'Rotacionar chave',app.action(rotate),secondary=True)
        revoke_button = button('Simular revogação' if is_demo else 'Revogar dispositivo',app.action(revoke),secondary=True)
        rotate_button.visible = revoke_button.visible = bool(linked_device) and not linked_device.get('retired', False) and reset_state.get('status', 'not_requested') not in ('pending', 'received', 'applied')
        reset_button = button('Simular restauração' if is_demo else 'Restaurar ESP32 de fábrica',app.action(reset_device),secondary=True)
        reset_button.visible = bool(linked_device) and not linked_device.get('retired', False) and reset_state.get('status', 'not_requested') in ('not_requested', 'failed', 'expired')
        reset_info.visible = bool(linked_device)
        if linked_device and (linked_device.get('retired') or reset_state.get('status') in ('pending', 'received', 'applied')):
            active.value = False
            active.disabled = True
        maintenance = card([
            ft.Text('MANUTENÇÃO SIMULADA' if is_demo else 'MANUTENÇÃO AVANÇADA',size=11,weight=ft.FontWeight.BOLD,color=theme.RED),
            ft.Text('Todas estas ações são simulações locais. Nenhuma credencial ou conexão real será alterada.' if is_demo else
                    'Estas ações alteram a conexão do equipamento. Não são necessárias para mudar a tarifa.',size=12,color=theme.GRAY_TEXT),
            ft.Text('Provisionar gera uma credencial fictícia apenas para testar este fluxo.' if is_demo else
                    'Provisionar cria uma credencial. Configure-a no ESP32; a chave aparece apenas uma vez.',size=12,color=theme.GRAY_TEXT),
            provision_button,device,
            ft.Text('Renovar troca apenas a chave fictícia da demonstração.' if is_demo else
                    'Rotacionar invalida a chave atual. O ESP32 só reconecta após receber a nova chave.',size=12,color=theme.GRAY_TEXT),
            rotate_button,
            ft.Text('Revogar desativa a credencial simulada. Você pode simular outro provisionamento depois.' if is_demo else
                    'Revogar desconecta o equipamento. Para reconectar, provisione e configure outra credencial.',size=12,color=theme.GRAY_TEXT),
            revoke_button,ft.Divider(color=theme.LIGHT_GRAY),reset_button,
        ],visible=False)

        async def toggle_maintenance():
            maintenance.visible = not maintenance.visible
            maintenance_toggle.content.value = 'Ocultar manutenção avançada' if maintenance.visible else 'Mostrar manutenção avançada'
            app.page.update()

        maintenance_toggle = button('Mostrar manutenção avançada',app.action(toggle_maintenance),secondary=True)
        controls += [card([ft.Text('Dispositivo simulado' if is_demo else 'Dispositivo ESP32',size=18),device_status,reset_info]),
                     maintenance_toggle,maintenance]
        if reset_state.get('status') in ('pending', 'received'):
            app.set_poll(poll_reset, 5)
    controls += [button('Voltar ao posto',app.link('operator',station_id=station_id),secondary=True)]
    return ft.Column(controls,spacing=15,scroll=ft.ScrollMode.AUTO)


def show_key(app, result):
    is_demo = bool(getattr(app.api,'is_demo',False))
    secret = ft.Text(result['device_key'],selectable=True)
    identifier = ft.Text('Device ID: '+result['device_id'],selectable=True)
    async def dismiss(e):
        secret.value = ''
        app.page.pop_dialog()
    dialog = ft.AlertDialog(modal=True,title=ft.Text('Chave fictícia de demonstração' if is_demo else 'Chave exibida uma vez'),content=ft.Column([identifier,secret,ft.Text('Esta chave é simulada. Não a instale em um equipamento real.' if is_demo else 'Copie para a configuração do ESP32 agora. Não compartilhe. Ao fechar, a chave não será armazenada no app.')],tight=True),actions=[ft.TextButton('Fechar' if is_demo else 'Copiei, fechar',on_click=dismiss)])
    app.page.show_dialog(dialog)
