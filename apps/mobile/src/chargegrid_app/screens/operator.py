import asyncio
import re
from decimal import Decimal, InvalidOperation

import flet as ft

from chargegrid_core.formatting import kwh

from ..api_client import ApiError
from ..services.location import geocode_address
from ..ui import theme
from ..ui.ai_features import ai_supported, owner_insights_control
from ..ui.components import (
    badge,
    button,
    card,
    date_time,
    disclosure_field,
    field,
    flat_button,
    money,
    title,
)
from ..ui.kpi import kpi_card, kpi_grid
from . import onboarding as onboarding_screen
from . import ownership


def _plural(count, one, many):
    return f'{count} {one if count == 1 else many}'


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
                  'Experimente a gestão de postos com dados fictícios.' if is_demo else 'Vincule o equipamento à sua conta de operador'),
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
    # Independent reads: fetch together instead of one after the other.
    summary, result = await asyncio.gather(
        app.api.request('GET','operator/summary'),
        app.api.request('GET','operator/stations',params={'limit':100,'offset':offset}))
    stations = result['items']
    instructions = card([
        ft.Text('COMO FUNCIONA',size=15,font_family='BarlowCondensed',weight=ft.FontWeight.BOLD,color=theme.TEXT_COLOR),
        ft.Text('Adicione um equipamento fictício para experimentar a gestão.' if is_demo else
                'O QR aparece na tela do ponto ainda sem dono.',size=13,color=theme.TEXT_COLOR),
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
    help_button.content.size = 12
    # Intrinsic height: a fixed 40 px box clipped the 48 px touch-target padding.
    controls = [
        button('Adicionar equipamento simulado' if is_demo else 'Escanear QR da tela',app.link('operator',claim=True)),
        ft.Row([
            ft.Text(f"{_plural(summary['stations'],'posto','postos')} · {_plural(summary['total_sessions'],'recarga','recargas')}",size=18,
                    font_family='BarlowCondensed',weight=ft.FontWeight.BOLD,color=theme.TEXT_COLOR,expand=True),
            help_button,
        ],spacing=8),
        kpi_grid([kpi_card('Energia registrada',kwh(float(summary['total_energy_wh'])/1000, 2),icon=ft.Icons.BOLT),
                  kpi_card('Valor estimado',money(summary['total_estimated_cost']),icon=ft.Icons.PAYMENTS_OUTLINED)],
                 columns={'xs':6}),
        ft.Text('Energia simulada nesta conta.' if is_demo else
                'O total pode incluir energia simulada, medida ou estimada. Consulte a origem em cada sessão.',
                size=12,color=theme.GRAY_TEXT),
        instructions,
    ]
    if ai_supported(app):
        controls.append(owner_insights_control(app))
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
                   ft.Text(f"{_plural(len(points),'ponto','pontos')} · {online} online",size=12,color=theme.GRAY_TEXT)]
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
        if not disabled:
            configure.content = ft.Row([
                ft.Image(src='/figma/configure.svg',width=16,height=16,color=theme.TEXT_COLOR),configure.content,
            ],spacing=6,alignment=ft.MainAxisAlignment.CENTER,tight=True)
        actions = [button('Vincular',app.link('operator',station_id=station['id'],claim=True),secondary=True),
                   button('Recargas',app.link('history',station_id=station['id']),secondary=True)]
        for action in actions:
            action.expand = True
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
            status, color = _point_status(connector)
            details = [ft.Row([ft.Text(connector['public_code'],size=17,font_family='BarlowCondensed',weight=ft.FontWeight.BOLD,
                                       color=theme.TEXT_COLOR,expand=True),badge(status,color,width=112)],spacing=8),
                       ft.Text(_point_line(connector),size=12,color=theme.GRAY_TEXT)]
            if is_demo:
                from ..demo import DEMO_PRESENCE_CODE
                details.append(ft.Text(f'Teste no modo motorista com {DEMO_PRESENCE_CODE}.',size=12,color=theme.GRAY_TEXT))
            if not connector.get('active') and not connector.get('retired'):
                shared = bool(station.get('active') or len(station['connectors']) > 1)
                details.append(button('Revisar e ativar ponto',app.link('operator',station_id=station['id'],
                                      point_id=connector['id'],onboarding=True,step=2 if shared else 1,
                                      **({'existing_station':True} if shared else {}))))
            details.append(button('Editar ponto / dispositivo',app.link('operator',station_id=station['id'],connector_id=connector['id'],
                                                                        connector={**connector,'station_name':station.get('name')}),secondary=True))
            controls.append(card(ft.Column(details,spacing=8)))
    controls.append(button('Voltar à gestão',app.link('operator'),secondary=True))
    return ft.Column(controls,spacing=15,scroll=ft.ScrollMode.AUTO)


CONNECTOR_TYPES = ('Tipo 2', 'CCS2', 'CHAdeMO', 'GB/T')
POWER_PRESETS = ('7.4', '11', '22', '50')
_TYPE_ALIASES = {'tipo2': 'Tipo 2', 'type2': 'Tipo 2', 'typeii': 'Tipo 2', 'mennekes': 'Tipo 2',
                 'ccs': 'CCS2', 'ccs2': 'CCS2', 'combo2': 'CCS2', 'ccstype2': 'CCS2', 'ccscombo2': 'CCS2',
                 'chademo': 'CHAdeMO', 'gbt': 'GB/T', 'gbtac': 'GB/T', 'gbtdc': 'GB/T'}


def _known_type(value):
    return _TYPE_ALIASES.get(re.sub(r'[^a-z0-9]', '', str(value or '').lower()))


def _decimal_text(value, places=None):
    try:
        number = Decimal(str(value).replace(',', '.'))
    except (InvalidOperation, ValueError):
        return str(value or '')
    if places is not None and number == number.quantize(Decimal(1).scaleb(-places)):
        number = number.quantize(Decimal(1).scaleb(-places))
    else:
        number = number.normalize()
    return format(number, 'f').replace('.', ',')


def _point_status(connector, device=None):
    if connector.get('retired') or (device or {}).get('retired'):
        return 'Desvinculado', theme.SLATE
    if not connector.get('active', True):
        return 'Desativado', theme.AMBER
    online = (device or connector).get('online')
    return ('Online', theme.GREEN) if online else ('Offline', theme.SLATE)


def _point_line(connector):
    parts = [connector.get('connector_type')]
    if connector.get('power_kw') not in (None, ''):
        parts.append(f"{_decimal_text(connector['power_kw'])} kW")
    if connector.get('price_per_kwh') not in (None, ''):
        parts.append(f"{money(connector['price_per_kwh'])}/kWh")
    return ' · '.join(str(part) for part in parts if part)


def _heading(text):
    return ft.Text(text, size=11, weight=ft.FontWeight.BOLD, color=theme.ACCENT)


def _chip(text, on_click):
    return ft.TextButton(content=ft.Text(text, size=13, text_align=ft.TextAlign.CENTER), on_click=on_click,
                         style=ft.ButtonStyle(padding=ft.Padding(left=14, right=14, top=10, bottom=10),
                                              shape=ft.RoundedRectangleBorder(radius=20)))


def _chip_palette():
    # Resolved while building: theme is a ContextVar that event handlers may not share.
    return {'on': theme.RED, 'off': theme.LIGHT_GRAY, 'text': theme.TEXT_COLOR}


def _paint_chips(chips, selected, palette):
    for value, chip in chips.items():
        on = value == selected
        chip.style.bgcolor = palette['on'] if on else palette['off']
        chip.style.side = ft.BorderSide(1, palette['on'] if on else palette['off'])
        chip.content.color = '#FFFFFF' if on else palette['text']
        chip.content.weight = ft.FontWeight.BOLD if on else ft.FontWeight.NORMAL


def _action_row(label, description, control):
    control.content.size = 13
    return ft.Row([ft.Column([ft.Text(label, size=14, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
                              ft.Text(description, size=12, color=theme.GRAY_TEXT)], spacing=2, expand=True),
                   control], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER)


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

    # Form fields: the TextFields stay the source of truth for save().
    public = field('Código público',connector.get('public_code',''))
    kind = field('Tipo de conector',connector.get('connector_type','Tipo 2'))
    power = field('Potência',_decimal_text(connector.get('power_kw','7.4')))
    price = field('Tarifa',_decimal_text(connector.get('price_per_kwh','1.00'),2))
    duration = field('Limite por recarga',str(connector.get('max_duration_minutes','60')))
    power.suffix, price.prefix, price.suffix, duration.suffix = 'kW', 'R$ ', '/kWh', 'min'
    for control in (power, price, duration):
        control.keyboard_type = ft.KeyboardType.NUMBER
    price.expand = duration.expand = True
    active = ft.Switch(label='Disponível para motoristas',value=connector.get('active',True),visible=bool(connector),
                       label_text_style=ft.TextStyle(size=15,color=theme.TEXT_COLOR),active_color=theme.RED)

    palette = _chip_palette()
    selected_type = _known_type(kind.value) or 'Outro'
    kind.visible = selected_type == 'Outro'
    def choose_type(value):
        def handler(event=None):
            nonlocal selected_type
            selected_type = value
            if value != 'Outro':
                kind.value = value
            elif _known_type(kind.value):
                kind.value = ''
            kind.visible = value == 'Outro'
            kind.error_text = None
            _paint_chips(type_chips, value, palette)
            app.page.update()
        return handler
    type_chips = {value: _chip(value, choose_type(value)) for value in (*CONNECTOR_TYPES, 'Outro')}
    _paint_chips(type_chips, selected_type, palette)

    def power_preset():
        try:
            current = Decimal((power.value or '').strip().replace(',', '.'))
        except (InvalidOperation, ValueError):
            return None
        return next((value for value in POWER_PRESETS if Decimal(value) == current), None)
    def choose_power(value):
        def handler(event=None):
            power.value = _decimal_text(value)
            power.error_text = None
            _paint_chips(power_chips, value, palette)
            app.page.update()
        return handler
    def typed_power(event=None):
        _paint_chips(power_chips, power_preset(), palette)
        app.page.update()
    power_chips = {value: _chip(f'{_decimal_text(value)} kW', choose_power(value)) for value in POWER_PRESETS}
    _paint_chips(power_chips, power_preset(), palette)
    power.on_change = typed_power

    device = field('Dispositivo vinculado',linked_device['device_id'] if linked_device else '')
    device.read_only = True
    device.visible = bool(linked_device)
    device_status = ft.Text(
        ('Desvinculado após restauração de fábrica' if linked_device.get('retired') else
         'Último contato: '+date_time(linked_device.get('last_seen')))
        if linked_device else 'Nenhum equipamento simulado vinculado.' if is_demo else
        'Nenhum equipamento vinculado. Provisione uma credencial abaixo.',
        size=13,color=theme.TEXT_COLOR,expand=True,
    )
    status_label, status_color = _point_status(connector, linked_device)
    status_badge = badge(status_label, status_color, width=112)
    status_colors = {'Desvinculado': theme.SLATE, 'Desativado': theme.AMBER, 'Online': theme.GREEN, 'Offline': theme.SLATE}
    def paint_status():
        label = _point_status(connector, linked_device)[0]
        color = status_colors[label]
        status_badge.content.value = label
        status_badge.bgcolor = color
        status_badge.content.color = theme.on_color(color)

    def update_device(identifier, message):
        nonlocal linked_device
        linked_device = {'device_id':identifier,'retired':False} if identifier else None
        reset_state.clear()
        reset_state['status'] = 'not_requested'
        device.value = identifier
        device.visible = bool(identifier)
        device_status.value = message
        provision_row.visible = provision_button.visible = not identifier
        rotate_row.visible = revoke_row.visible = rotate_button.visible = revoke_button.visible = bool(identifier)
        reset_box.visible = bool(identifier)
        reset_button.visible = bool(identifier)
        reset_info.visible = False
        reset_info.value = reset_messages['not_requested']
        paint_status()
        app.page.update()
    async def save():
        body = {'public_code':onboarding_screen._required(public,'código público',50),
                'connector_type':onboarding_screen._required(kind,'tipo de conector',50),
                'power_kw':onboarding_screen._number(power,'Potência',Decimal('0.001'),1000),
                'price_per_kwh':onboarding_screen._number(price,'Tarifa',0,10000),
                'max_duration_minutes':onboarding_screen._number(duration,'Limite',1,1440,integer=True)}
        if connector:
            body['active'] = active.value
        await app.api.request('PATCH' if connector else 'POST',f"connectors/{connector['id']}" if connector else f'stations/{station_id}/connectors',body)
        if hasattr(app,'mark_saved'):
            app.mark_saved()
        await app.go('operator',station_id=station_id)
    async def provision():
        result = await app.api.request('POST',f"connectors/{connector['id']}/device")
        update_device(result['device_id'],'Credencial simulada criada. Nada precisa ser instalado.' if is_demo else
                      'Credencial criada. Configure a chave no equipamento para conectar.')
        show_key(app,result)
    async def rotate():
        if not device.value.strip():
            raise ApiError('Informe o ID do dispositivo.')
        result = await app.api.request('POST',f'devices/{device.value.strip()}/rotate-key')
        device_status.value = 'Chave fictícia renovada nesta demonstração.' if is_demo else 'Chave renovada. Atualize a configuração do equipamento para reconectar.'
        app.page.update()
        show_key(app,result)
    async def revoke():
        if not device.value.strip():
            raise ApiError('Informe o ID do dispositivo.')
        await app.api.request('POST',f'devices/{device.value.strip()}/revoke')
        update_device('','Credencial simulada revogada. Simule outra quando quiser.' if is_demo else
                      'Credencial revogada. Provisione outra para reconectar o equipamento.')
        app.notice('Revogação simulada concluída.' if is_demo else 'Dispositivo revogado; chave anterior recusada.')
    reset_messages = {
        'not_requested': 'Remove o vínculo e preserva o Wi-Fi. O ponto é desativado; o histórico fica.',
        'pending': 'Aguardando a tela confirmar a restauração. Mantenha o equipamento ligado e conectado.',
        'received': 'A tela recebeu o comando. Aguarde a confirmação antes de desligá-la.',
        'applied': 'Restauração confirmada. O Wi-Fi foi preservado. Escaneie o novo QR para vincular a tela novamente.',
        'failed': 'A tela não conseguiu restaurar. Verifique se está livre e tente novamente.',
        'expired': 'A tela não confirmou a tempo. Confira a conexão e tente novamente.',
    }
    if is_demo:
        reset_messages.update({
            'not_requested':'Desativa este ponto fictício e mantém o histórico da demonstração.',
            'pending':'Aguardando a confirmação simulada da restauração.',
            'received':'O equipamento fictício recebeu o comando simulado.',
            'applied':'Restauração simulada confirmada. Adicione outro equipamento simulado para criar um novo vínculo.',
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
            active.value = False
            active.disabled = True
            rotate_row.visible = revoke_row.visible = rotate_button.visible = revoke_button.visible = False
        elif status in ('failed', 'expired'):
            active.disabled = False
            rotate_row.visible = revoke_row.visible = rotate_button.visible = revoke_button.visible = True
        if status == 'applied':
            if linked_device:
                linked_device['retired'] = True
            device_status.value = 'Desvinculado após restauração de fábrica'
            paint_status()
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
            title=ft.Text('Simular restauração do equipamento?' if is_demo else 'Restaurar equipamento de fábrica?'),
            content=ft.Text('Esta ação altera apenas o ponto fictício desta demonstração. Ele será desativado e o histórico simulado será mantido. Nenhum dispositivo físico ou Wi-Fi será alterado.' if is_demo else
                            'O vínculo desta tela será removido e o Wi-Fi será preservado. O ponto atual sairá de operação, mas seu histórico será mantido. Faça isso somente com a tela online e sem reserva ou recarga. Depois, escaneie o novo QR para vincular a tela novamente.'),
            actions=[ft.TextButton('Cancelar', on_click=cancel),
                     ft.TextButton('Simular restauração' if is_demo else 'Restaurar', on_click=app.action(confirm),
                                   style=ft.ButtonStyle(color=theme.RED))],
        ))

    # Header: what is being edited and its live state.
    header = [ft.Row([ft.Column([ft.Text('EDITAR PONTO' if connector else 'NOVO PONTO',size=11,weight=ft.FontWeight.BOLD,color=theme.ACCENT),
                                 ft.Text(connector.get('public_code') or 'Novo ponto',size=26,font_family='BarlowCondensed',
                                         weight=ft.FontWeight.BOLD,color=theme.TEXT_COLOR)],spacing=0,expand=True)]
                     + ([status_badge] if connector else []),spacing=8,vertical_alignment=ft.CrossAxisAlignment.CENTER)]
    if connector.get('station_name'):
        header.append(ft.Row([ft.Icon(ft.Icons.PLACE_OUTLINED,size=16,color=theme.GRAY_TEXT),
                              ft.Text(connector['station_name'],size=13,color=theme.GRAY_TEXT,expand=True)],spacing=6))
    if connector:
        header += [ft.Divider(height=8,color=theme.LIGHT_GRAY),
                   ft.Row([ft.Icon(ft.Icons.ROUTER_OUTLINED,size=18,color=theme.GRAY_TEXT),device_status],spacing=8),
                   reset_info]
    if is_demo:
        from ..demo import DEMO_PRESENCE_CODE
        header.append(ft.Row([ft.Icon(ft.Icons.SCIENCE_OUTLINED,size=16,color=theme.GRAY_TEXT),
                              ft.Text(f'Ponto simulado. Teste no modo motorista com {DEMO_PRESENCE_CODE}.',
                                      size=12,color=theme.GRAY_TEXT,expand=True)],spacing=8))

    controls = [
        card(ft.Column(header,spacing=6)),
        card(ft.Column([_heading('CONECTOR'),
                        ft.Row(list(type_chips.values()),wrap=True,spacing=8,run_spacing=8),kind,
                        ft.Container(height=4),power,
                        ft.Row(list(power_chips.values()),wrap=True,spacing=8,run_spacing=8)],spacing=10)),
        card(ft.Column([_heading('PREÇO E TEMPO'),
                        ft.Row([price,duration],spacing=10,vertical_alignment=ft.CrossAxisAlignment.START),
                        ft.Text('Tarifa estimada por kWh e tempo máximo de cada recarga.',size=12,color=theme.GRAY_TEXT)],spacing=10)),
    ]
    if connector:
        controls.append(card(ft.Column([_heading('DISPONIBILIDADE'),active,
                                        ft.Text('O posto também precisa estar ativo para o ponto aparecer na busca.',
                                                size=12,color=theme.GRAY_TEXT)],spacing=8)))
    controls.append(card(ft.Column([_heading('IDENTIFICAÇÃO'),public,
                                    ft.Text('Código exibido aos motoristas para encontrar este ponto.',size=12,color=theme.GRAY_TEXT)],spacing=10)))
    controls.append(button('Salvar alterações' if connector else 'Salvar ponto',app.action(save)))
    if connector:
        provision_button = button('Provisionar',app.action(provision))
        rotate_button = button('Rotacionar',app.action(rotate),secondary=True)
        revoke_button = button('Revogar',app.action(revoke),secondary=True)
        reset_button = flat_button('Restaurar',theme.RED,on_click=app.action(reset_device))
        reset_button.content.size = 13
        provision_row = _action_row('Nova credencial','Gera uma chave fictícia para testar o fluxo.' if is_demo else
                                    'Gera a chave do equipamento; ela aparece uma única vez.',provision_button)
        rotate_row = _action_row('Trocar chave','Troca a chave fictícia da demonstração.' if is_demo else
                                 'Invalida a chave atual; o equipamento precisa da nova.',rotate_button)
        revoke_row = _action_row('Desconectar','Desativa a credencial simulada.' if is_demo else
                                 'Recusa a chave atual até nova credencial.',revoke_button)
        reset_box = ft.Container(
            _action_row('Restaurar de fábrica',reset_messages['not_requested'],reset_button),
            bgcolor=ft.Colors.with_opacity(0.08,theme.RED),border=ft.Border.all(1,ft.Colors.with_opacity(0.45,theme.RED)),
            border_radius=10,padding=12,margin=ft.Margin(left=0,right=0,top=6,bottom=0))
        provision_row.visible = provision_button.visible = not linked_device
        rotate_row.visible = revoke_row.visible = rotate_button.visible = revoke_button.visible = bool(linked_device) and not linked_device.get('retired', False) and reset_state.get('status', 'not_requested') not in ('pending', 'received', 'applied')
        reset_button.visible = bool(linked_device) and not linked_device.get('retired', False) and reset_state.get('status', 'not_requested') in ('not_requested', 'failed', 'expired')
        reset_box.visible = bool(linked_device)
        if linked_device and (linked_device.get('retired') or reset_state.get('status') in ('pending', 'received', 'applied')):
            active.value = False
            active.disabled = True
        maintenance, _summary = disclosure_field(
            'Conexão do equipamento',
            'Credencial e restauração simuladas' if is_demo else 'Credencial, chave e restauração',
            [ft.Text('Ações apenas desta demonstração; nada real é alterado.' if is_demo else
                     'Não é preciso mexer aqui para mudar tarifa ou disponibilidade.',size=12,color=theme.GRAY_TEXT),
             device,provision_row,rotate_row,revoke_row,reset_box],
            on_update=app.page.update)
        controls.append(maintenance)
        if reset_state.get('status') in ('pending', 'received'):
            app.set_poll(poll_reset, 5)
    controls.append(button('Voltar ao posto',app.link('operator',station_id=station_id),secondary=True))
    return ft.Column(controls,spacing=14,scroll=ft.ScrollMode.AUTO)


def show_key(app, result):
    is_demo = bool(getattr(app.api,'is_demo',False))
    secret = ft.Text(result['device_key'],selectable=True)
    identifier = ft.Text('Device ID: '+result['device_id'],selectable=True)
    async def dismiss(e):
        secret.value = ''
        app.page.pop_dialog()
    dialog = ft.AlertDialog(modal=True,title=ft.Text('Chave fictícia de demonstração' if is_demo else 'Chave exibida uma vez'),content=ft.Column([identifier,secret,ft.Text('Esta chave é simulada. Não a instale em um equipamento real.' if is_demo else 'Copie para a configuração do equipamento agora. Não compartilhe. Ao fechar, a chave não será armazenada no app.')],tight=True),actions=[ft.TextButton('Fechar' if is_demo else 'Copiei, fechar',on_click=dismiss)])
    app.page.show_dialog(dialog)
