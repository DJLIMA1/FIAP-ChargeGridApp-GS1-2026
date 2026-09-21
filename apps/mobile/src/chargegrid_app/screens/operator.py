import flet as ft

from ..api_client import ApiError
from ..services.location import geocode_address
from ..ui import theme
from ..ui.components import button, card, date_time, field, money, title


async def build(app, station_id=None, connector_id=None, device_id=None, offset=0, connector=None):
    profile = await app.api.request('GET','me')
    if not profile.get('operator_enabled'):
        return title('Gestão de postos','Sua conta precisa de aprovação de operador.')
    if connector_id:
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
    controls = [title('Meus postos','Gestão do operador aprovado'),card([ft.Text(f"{summary['stations']} postos · {summary['total_sessions']} sessões"),ft.Text(f"{float(summary['total_energy_wh'])/1000:.3f} kWh · {money(summary['total_estimated_cost'])} estimados")]),button('Cadastrar posto',app.link('operator',station_id='new')),button('Gerenciar cupons',app.link('coupons',manage=True))]
    for station in stations:
        controls.append(card([ft.Text(station['name'],size=18),ft.Text(station['address']),button('Editar posto / pontos',app.link('operator',station_id=station['id'])),button('Histórico deste posto',app.link('history',station_id=station['id']),secondary=True)]))
    if offset + 100 < result['total']:
        controls.append(button('Mais postos',app.link('operator',offset=offset+100)))
    if not stations:
        controls.append(ft.Text('Você ainda não possui postos.'))
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
        controls += [button('Adicionar ponto',app.link('operator',station_id=station['id'],connector_id='new'))]
        for connector in station['connectors']:
            controls.append(card([ft.Text(f"{connector['public_code']} · {connector['connector_type']}"),ft.Text('Online' if connector.get('online') else 'Offline'),button('Editar ponto / dispositivo',app.link('operator',station_id=station['id'],connector_id=connector['id'],connector=connector))]))
    controls.append(button('Voltar à gestão',app.link('operator'),secondary=True))
    return ft.Column(controls,spacing=15,scroll=ft.ScrollMode.AUTO)


async def connector_form(app, station_id, connector=None, device_id=None):
    connector = connector or {}
    linked_device = None
    if connector:
        try:
            linked_device = await app.api.request('GET',f"connectors/{connector['id']}/device")
        except ApiError as exc:
            if exc.status != 404:
                raise
    public, kind, power = field('Código público',connector.get('public_code','')),field('Tipo de conector',connector.get('connector_type','Type 2')),field('Potência kW',str(connector.get('power_kw','7.4')))
    price, duration = field('Tarifa estimada por kWh',str(connector.get('price_per_kwh','1.00'))),field('Limite máximo min',str(connector.get('max_duration_minutes','60')))
    active = ft.Switch(label='Ponto ativo',value=connector.get('active',True),visible=bool(connector))
    device = field('Dispositivo vinculado',linked_device['device_id'] if linked_device else '')
    device.read_only = True
    device.visible = bool(linked_device)
    device_status = ft.Text(
        ('Online' if linked_device.get('online') else 'Offline')+' · Último contato: '+date_time(linked_device.get('last_seen'))
        if linked_device else 'Nenhum dispositivo vinculado. Provisione para conectar o ESP32.',
        size=12,color=theme.GRAY_TEXT,
    )
    def update_device(identifier, message):
        device.value = identifier
        device.visible = bool(identifier)
        device_status.value = message
        provision_button.visible = not identifier
        rotate_button.visible = revoke_button.visible = bool(identifier)
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
    controls = [title('Editar ponto' if connector else 'Novo ponto'),card(ft.Column([public,kind,power,price,duration,active],spacing=12)),button('Salvar ponto',app.action(save))]
    if connector:
        provision_button = button('Provisionar dispositivo',app.action(provision))
        provision_button.visible = not linked_device
        rotate_button = button('Rotacionar chave',app.action(rotate),secondary=True)
        revoke_button = button('Revogar dispositivo',app.action(revoke),secondary=True)
        rotate_button.visible = revoke_button.visible = bool(linked_device)
        controls += [card([ft.Text('Dispositivo ESP32',size=18),ft.Text('Configure a chave no equipamento. Ela é exibida somente após provisionar ou renovar.'),device_status,provision_button,device,rotate_button,revoke_button])]
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
