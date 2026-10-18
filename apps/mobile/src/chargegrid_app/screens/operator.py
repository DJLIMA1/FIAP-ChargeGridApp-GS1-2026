import re
from decimal import Decimal, InvalidOperation

import flet as ft

from ..api_client import ApiError
from ..services.location import geocode_address
from ..ui import design, theme
from ..ui.ai_features import ai_supported, owner_insights_control
from ..ui.components import (
    date_time,
    money,
    title,
)
from . import onboarding as onboarding_screen
from . import ownership
from .setup_ui import FIELD_HEIGHT, cta, setup_field, setup_title
from .station_admin import chatbot_button, menu_row, station_code


def _plural(count, one, many):
    return f'{count} {one if count == 1 else many}'


async def build(app, station_id=None, connector_id=None, device_id=None, offset=0, connector=None,
                claim=False, onboarding=False, point_id=None, step=1, existing_station=False, edited=False,
                show_real=False, **_):
    is_demo = bool(getattr(app.api,'is_demo',False))
    profile = await app.api.request('GET','me')
    app.profile = profile
    if not profile.get('operator_enabled') and profile.get('account_type') != 'vendor':
        return title('Gestão de postos','Entre com uma conta de operador para vincular equipamentos.')
    if claim:
        return await ownership.build(app, station_id=station_id, show_real=show_real)
    if onboarding:
        return await onboarding_screen.build(app, station_id=station_id, point_id=point_id,
                                             step=step, existing_station=existing_station)
    if not profile.get('operator_enabled'):
        return design.page(
            design.card_box(ft.Column([
                ft.Icon(ft.Icons.QR_CODE_SCANNER, size=44, color=theme.TEXT_COLOR),
                design.txt('Adicione um equipamento simulado para criar seu posto. Todo o processo acontece nesta demonstração.'
                           if is_demo else 'A tela sem dono mostra um QR de vinculação. Escaneie-o para se tornar o proprietário.',
                           13, 'semibold'),
                design.txt('Depois informe nome, endereço e tarifa. O ponto só aparece aos motoristas quando você publicar.',
                           11, 'regular', theme.GRAY_TEXT),
                design.txt('Posto é o local com endereço. Cada ponto é um equipamento de recarga nesse local.',
                           11, 'regular', theme.GRAY_TEXT)], spacing=10)),
            text_button('Adicionar equipamento simulado' if is_demo else 'Escanear QR da tela',
                        app.link('operator', claim=True)),
            title='Configure seu primeiro ponto simulado' if is_demo else 'Configure sua primeira tela',
            title_size=20)
    if connector_id:
        if connector_id == 'new':
            return await ownership.build(app, station_id=station_id)
        connector = connector or app.data.get('connector')
        if not connector and station_id:
            owner = await app.api.request('GET',f'stations/{station_id}')
            found = next((item for item in owner.get('connectors') or [] if item.get('id') == connector_id),None)
            connector = {**found,'station_name':owner.get('name')} if found else None
        return await connector_form(app,station_id,connector,device_id)
    if station_id == 'new':
        return await station_form(app)
    if station_id:
        station = await app.api.request('GET',f'stations/{station_id}')
        code = None
        try:
            listing = await app.api.request('GET','operator/stations',params={'limit':100,'offset':0})
            if isinstance(listing,dict) and isinstance(listing.get('items'),list):
                code = station_code(listing['items'],station_id)
        except ApiError:
            pass
        return await station_form(app,station,edited=edited,code=code)
    return await station_list(app, offset, is_demo)


def _station_state(station):
    points = [point for point in station.get('connectors') or [] if not point.get('retired')]
    online = [point for point in points if point.get('online')]
    in_use = [point for point in online if point.get('available') is False]
    live = [point for point in points if point.get('active', True)]
    if not station.get('active', True):
        status = 'Desativada'
    elif points and not live:
        return 'Pontos desativados - revise para publicar'
    elif online:
        status = 'Online'
    else:
        status = 'Offline'
    if in_use:
        return f'{status} - Conectores em uso'
    return f'{status} - Conectores livres' if online and station.get('active', True) else status


def text_button(text, on_click, *, primary=True, height=48):
    """Botão com o texto como conteúdo direto (primário branco ou secundário escuro)."""
    return ft.Container(design.txt(text, 14.5, 'semibold', theme.BTN_PRIMARY_FG if primary else theme.BTN_SECONDARY_FG,
                                   text_align=ft.TextAlign.CENTER),
                        bgcolor=theme.BTN_PRIMARY if primary else theme.BTN_SECONDARY, border_radius=design.RADIUS_BTN,
                        height=height, alignment=ft.Alignment(0, 0), on_click=on_click, ink=True)


async def station_list(app, offset, is_demo):
    result = await app.api.request('GET', 'operator/stations', params={'limit': 100, 'offset': offset})
    stations = result['items']
    add_label = 'Adicionar equipamento simulado' if is_demo else 'Escanear QR da tela'
    rows = [menu_row(station['name'], _station_state(station), '/design/icon_station_charge.svg',
                     app.link('station_admin', station_id=station['id']), tile=44) for station in stations]
    body = [ft.Container(height=8)]
    if rows:
        body.append(ft.Column(rows, spacing=22))
    else:
        body.append(design.card_box(ft.Column([
            design.txt('Seu primeiro ponto começa adicionando um equipamento simulado.' if is_demo else
                       'Seu primeiro ponto começa no QR do equipamento.', 13, 'semibold'),
            design.txt('Adicione um equipamento fictício para experimentar a gestão.' if is_demo else
                       'O QR aparece na tela do ponto ainda sem dono.', 11, 'regular', theme.GRAY_TEXT),
            design.txt('1. Adicione um equipamento simulado.\n2. Configure nome, endereço de exemplo e tarifa.\n'
                       '3. Revise, publique e teste a recarga simulada.' if is_demo else
                       '1. Ligue a tela e configure o Wi-Fi, se necessário.\n2. Escaneie o QR com sua conta de operador.\n'
                       '3. Defina nome, local e tarifa; revise e publique.', 11, 'regular', theme.GRAY_TEXT)], spacing=8)))
        body.append(text_button(add_label, app.link('operator', claim=True)))
    if offset + 100 < result['total']:
        body.append(text_button('Mais postos', app.link('operator', offset=offset + 100), primary=False))
    if offset:
        body.append(text_button('Postos anteriores', app.link('operator', offset=max(0, offset - 100)), primary=False))
    body += [ft.Container(height=16), chatbot_button(app, 38), ft.Container(height=560),  # opções extras: abaixo da 1ª tela
             design.section_label('Mais opções'),
             *([menu_row(add_label, 'Novo equipamento ou outro ponto em um posto', ft.Icons.QR_CODE_SCANNER,
                         app.link('operator', claim=True))] if rows else []),
             menu_row('Gerenciar cupons', 'Criar e acompanhar descontos', ft.Icons.CONFIRMATION_NUMBER_OUTLINED,
                      app.link('coupons', manage=True))]
    if ai_supported(app):
        body.append(owner_insights_control(app))
    return design.page(*body, title='Suas Estações', title_size=22, gap=16)


class _Toggle:
    """Ativa/Inativa segmentado com ``.value`` booleano (substitui o Switch dos formulários antigos)."""

    def __init__(self, app, value=True, height=37.5):
        self.app, self.value, self.disabled, self.height = app, bool(value), False, height
        self.holder = ft.Container(data=self)
        self.draw()

    def draw(self):
        self.holder.content = design.segmented([('on', 'Ativa'), ('off', 'Inativa')], 'on' if self.value else 'off',
                                               self.choose, height=self.height)
        self.holder.opacity = 0.5 if self.disabled else 1

    async def choose(self, key):
        if self.disabled:
            return
        self.value = key == 'on'
        self.draw()
        self.app.page.update()


def _status_pill(label, color):
    return ft.Container(design.txt(label, 10.5, 'bold', theme.on_color(color), text_align=ft.TextAlign.CENTER),
                        bgcolor=color, border_radius=6, padding=ft.Padding(left=8, right=8, top=4, bottom=4))


async def station_form(app, station=None, edited=False, code=None):
    """Editar/criar posto no visual da referência (``Configurar Estação``): campos escuros rotulados,
    Ativa/Inativa segmentado, botão branco. Coordenadas, pontos e atalhos ficam abaixo da primeira tela."""
    is_demo = bool(getattr(app.api,'is_demo',False))
    station = station or {}
    editing = bool(station)
    gap, height = (3.5, 42.5) if edited else (14, FIELD_HEIGHT)
    name_box = setup_field('Nome da estação', station.get('name',''), 'Ex.: Posto Centro', gap=gap, edited=edited,
                           height=height)
    address_box = setup_field('Endereço', station.get('address',''), 'Rua, número, bairro, cidade e estado',
                              gap=gap, edited=edited, height=height)
    ident_box = setup_field('Identificador', code or station_code([station], station.get('id')) if editing else '',
                            read_only=True, gap=gap, height=height)
    ident_box.visible = editing and not edited
    latitude_box = setup_field('Latitude', str(station.get('latitude','')), keyboard=ft.KeyboardType.NUMBER, gap=14, height=FIELD_HEIGHT)
    longitude_box = setup_field('Longitude', str(station.get('longitude','')), keyboard=ft.KeyboardType.NUMBER, gap=14,
                                height=FIELD_HEIGHT)
    name, address, latitude, longitude = (box.controls[1] for box in (name_box, address_box, latitude_box, longitude_box))
    toggle = _Toggle(app, False if edited else station.get('active', True))
    status_box = ft.Column([design.label('Status', strong=False), toggle.holder], spacing=4,
                           horizontal_alignment=ft.CrossAxisAlignment.STRETCH, visible=editing)
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
            body['active'] = toggle.value
        result = await app.api.request('PATCH' if station else 'POST',f"stations/{station['id']}" if station else 'stations',body)
        if hasattr(app,'mark_saved'):
            app.mark_saved()
        await app.go('operator',station_id=result['id'],nav=False)
    controls = [setup_title(app, 'Configurar Estação', bottom=3.25 if edited else 2.25),
                ft.Column([name_box, address_box, ident_box], spacing=16.5 if edited else 15.5, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                status_box,
                cta('Salvar alterações' if editing else 'Salvar posto', app.action(save), weight='semibold', height=47.5),
                ft.Container(height=450),  # coordenadas, pontos e atalhos: abaixo da primeira tela (referência)
                design.section_label('Localização'),
                ft.Column([latitude_box, longitude_box], spacing=14),
                cta('Usar localização de exemplo' if is_demo else 'Localizar endereço',app.action(locate),primary=False,weight='semibold'),
                design.txt('Nome, endereço e disponibilidade do posto valem para todos os seus pontos.', 11.5, 'regular',
                           theme.GRAY_TEXT)]
    if station:
        controls += [ft.Container(height=4), design.section_label('Pontos de recarga')]
        for connector in station['connectors']:
            status, color = _point_status(connector)
            row = design.list_row(connector['public_code'], _point_line(connector), tile=44, dark_tile=True,
                                  icon='/design/icon_station_charge.svg', trailing=_status_pill(status, color),
                                  on_click=app.link('operator',station_id=station['id'],connector_id=connector['id'],
                                                    connector={**connector,'station_name':station.get('name')},nav=False))
            details = [row]
            if is_demo:
                from ..demo import DEMO_PRESENCE_CODE
                details.append(design.txt(f'Teste no modo motorista com {DEMO_PRESENCE_CODE}.', 11, 'regular', theme.GRAY_TEXT))
            if not connector.get('active') and not connector.get('retired'):
                shared = bool(station.get('active') or len(station['connectors']) > 1)
                details.append(cta('Revisar e ativar ponto',app.link('operator',station_id=station['id'],
                                   point_id=connector['id'],onboarding=True,step=2 if shared else 1,
                                   **({'existing_station':True} if shared else {})),weight='semibold'))
            controls.append(ft.Column(details, spacing=8))
        controls.append(cta('Adicionar ponto simulado a este posto' if is_demo else 'Vincular outra tela a este posto',
                            app.link('operator',station_id=station['id'],claim=True),primary=False,weight='semibold'))
    controls.append(cta('Voltar à gestão',app.link('operator'),primary=False,weight='semibold'))
    return design.page(*controls, gap=16)


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


def _chip(text, selected=False, on_click=None, width=None):
    return design.chip_option(text, selected=selected, on_click=on_click, width=width or max(66, len(text) * 9 + 34))


def _chip_palette():
    # Resolved while building: theme is a ContextVar that event handlers may not share.
    return {'on': theme.BTN_PRIMARY, 'on_fg': theme.BTN_PRIMARY_FG, 'off': theme.CARD, 'off_fg': theme.TEXT_COLOR}


def _paint_chips(chips, selected, palette):
    for value, chip in chips.items():
        on = value == selected
        chip.bgcolor = palette['on'] if on else palette['off']
        chip.content.color = palette['on_fg'] if on else palette['off_fg']
        chip.content.font_family = design.FONT_BOLD if on else design.FONT_MEDIUM


def _mini_button(text, on_click, kind='secondary'):
    """Botão compacto (texto como conteúdo direto): primário branco, secundário escuro ou perigo vermelho."""
    colors = {'primary': (theme.BTN_PRIMARY, theme.BTN_PRIMARY_FG), 'secondary': (theme.BTN_SECONDARY, theme.BTN_SECONDARY_FG),
              'danger': (theme.RED, '#FFFFFF')}
    bg, fg = colors[kind]
    return ft.Container(design.txt(text, 12.5, 'semibold', fg, text_align=ft.TextAlign.CENTER), bgcolor=bg,
                        border_radius=design.RADIUS_BTN, padding=ft.Padding(left=14, right=14, top=10, bottom=10),
                        alignment=ft.Alignment(0, 0), on_click=on_click, ink=True)


def _action_row(icon, label, description, control):
    """Linha de equipamento: tile branco + título/descrição + botão compacto."""
    return ft.Row([design.icon_tile(icon, size=40),
                   ft.Column([design.txt(label, 13, 'semibold'), design.txt(description, 10.5, 'regular', theme.GRAY_TEXT)],
                             spacing=2, expand=True),
                   control], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER)


def _set_visible(box, visible):
    box.visible = visible
    box.controls[1].visible = visible


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
    gap = 14
    public_box = setup_field('Código público', connector.get('public_code',''), gap=gap, height=FIELD_HEIGHT)
    kind_box = setup_field('Tipo de conector', connector.get('connector_type','Tipo 2'), gap=gap, height=FIELD_HEIGHT)
    power_box = setup_field('Potência', _decimal_text(connector.get('power_kw','7.4')), keyboard=ft.KeyboardType.NUMBER,
                            gap=gap, height=FIELD_HEIGHT, suffix='kW')
    price_box = setup_field('Tarifa', _decimal_text(connector.get('price_per_kwh','1.00'),2), keyboard=ft.KeyboardType.NUMBER,
                            gap=gap, height=FIELD_HEIGHT, prefix='R$ ', suffix='/kWh')
    duration_box = setup_field('Limite por recarga', str(connector.get('max_duration_minutes','60')),
                               keyboard=ft.KeyboardType.NUMBER, gap=gap, height=FIELD_HEIGHT, suffix='min')
    device_box = setup_field('Dispositivo vinculado', linked_device['device_id'] if linked_device else '', read_only=True,
                             gap=gap, height=FIELD_HEIGHT)
    public, kind, power, price, duration, device = (box.controls[1] for box in
                                                    (public_box, kind_box, power_box, price_box, duration_box, device_box))
    price_box.expand = duration_box.expand = True
    active = _Toggle(app, connector.get('active',True))
    active_box = ft.Column([design.label('Disponível para motoristas', strong=False), active.holder], spacing=4,
                           horizontal_alignment=ft.CrossAxisAlignment.STRETCH, visible=bool(connector))

    palette = _chip_palette()
    selected_type = _known_type(kind.value) or 'Outro'
    _set_visible(kind_box, selected_type == 'Outro')
    def choose_type(value):
        def handler(event=None):
            nonlocal selected_type
            selected_type = value
            if value != 'Outro':
                kind.value = value
            elif _known_type(kind.value):
                kind.value = ''
            _set_visible(kind_box, value == 'Outro')
            kind.error_text = None
            _paint_chips(type_chips, value, palette)
            app.page.update()
        return handler
    type_chips = {value: _chip(value, on_click=choose_type(value)) for value in (*CONNECTOR_TYPES, 'Outro')}
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
    power_chips = {value: _chip(f'{_decimal_text(value)} kW', on_click=choose_power(value)) for value in POWER_PRESETS}
    _paint_chips(power_chips, power_preset(), palette)
    power.on_change = typed_power

    _set_visible(device_box, bool(linked_device))
    device_status = ft.Text(
        ('Desvinculado após restauração de fábrica' if linked_device.get('retired') else
         'Último contato: '+date_time(linked_device.get('last_seen')))
        if linked_device else 'Nenhum equipamento simulado vinculado.' if is_demo else
        'Nenhum equipamento vinculado. Provisione uma credencial abaixo.',
        size=13,color=theme.TEXT_COLOR,expand=True,font_family=design.FONT,
    )
    status_label, status_color = _point_status(connector, linked_device)
    status_badge = _status_pill(status_label, status_color)
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
        _set_visible(device_box, bool(identifier))
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
            active.value, active.disabled = False, True
            active.draw()
            rotate_row.visible = revoke_row.visible = rotate_button.visible = revoke_button.visible = False
        elif status in ('failed', 'expired'):
            active.disabled = False
            active.draw()
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
    header = [ft.Row([ft.Column([design.num(connector.get('public_code') or 'Novo ponto', 26)], spacing=0, expand=True)]
                     + ([status_badge] if connector else []), spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)]
    if connector.get('station_name'):
        header.append(ft.Row([ft.Icon(ft.Icons.PLACE_OUTLINED,size=16,color=theme.GRAY_TEXT),
                              design.txt(connector['station_name'], 13, 'regular', theme.GRAY_TEXT, expand=True)],spacing=6))
    if connector:
        header += [ft.Row([ft.Icon(ft.Icons.ROUTER_OUTLINED,size=18,color=theme.GRAY_TEXT),device_status],spacing=8),
                   reset_info]
    if is_demo:
        from ..demo import DEMO_PRESENCE_CODE
        header.append(ft.Row([ft.Icon(ft.Icons.SCIENCE_OUTLINED,size=16,color=theme.GRAY_TEXT),
                              design.txt(f'Ponto simulado. Teste no modo motorista com {DEMO_PRESENCE_CODE}.',
                                         12, 'regular', theme.GRAY_TEXT, expand=True)],spacing=8))

    note = lambda text: design.txt(text, 11.5, 'regular', theme.GRAY_TEXT)  # noqa: E731
    controls = [
        setup_title(app, 'Editar ponto' if connector else 'Novo ponto', on_back=app.link('operator',station_id=station_id),
                    bottom=2.25),
        design.card_box(ft.Column(header,spacing=8)),
        design.section_label('Conector'),
        ft.Row(list(type_chips.values()),wrap=True,spacing=8,run_spacing=8),
        kind_box,
        power_box,
        ft.Row(list(power_chips.values()),wrap=True,spacing=8,run_spacing=8),
        design.section_label('Preço e tempo'),
        ft.Row([price_box,duration_box],spacing=10,vertical_alignment=ft.CrossAxisAlignment.START),
        note('Tarifa estimada por kWh e tempo máximo de cada recarga.'),
    ]
    if connector:
        controls += [active_box, note('O posto também precisa estar ativo para o ponto aparecer na busca.')]
    controls += [design.section_label('Identificação'), public_box,
                 note('Código exibido aos motoristas para encontrar este ponto.'),
                 cta('Salvar alterações' if connector else 'Salvar ponto',app.action(save),weight='semibold')]
    if connector:
        provision_button = _mini_button('Provisionar',app.action(provision),'primary')
        rotate_button = _mini_button('Rotacionar',app.action(rotate))
        revoke_button = _mini_button('Revogar',app.action(revoke))
        reset_button = _mini_button('Restaurar',app.action(reset_device),'danger')
        provision_row = _action_row(ft.Icons.KEY_OUTLINED,'Nova credencial','Gera uma chave fictícia para testar o fluxo.' if is_demo else
                                    'Gera a chave do equipamento; ela aparece uma única vez.',provision_button)
        rotate_row = _action_row(ft.Icons.SYNC,'Trocar chave','Troca a chave fictícia da demonstração.' if is_demo else
                                 'Invalida a chave atual; o equipamento precisa da nova.',rotate_button)
        revoke_row = _action_row(ft.Icons.LINK_OFF,'Desconectar','Desativa a credencial simulada.' if is_demo else
                                 'Recusa a chave atual até nova credencial.',revoke_button)
        reset_box = ft.Container(
            _action_row(ft.Icons.RESTORE,'Restaurar de fábrica',reset_messages['not_requested'],reset_button),
            bgcolor=theme.WARN_BG,border=ft.Border.all(1,ft.Colors.with_opacity(0.45,theme.RED)),
            border_radius=design.RADIUS_CARD,padding=14)
        provision_row.visible = provision_button.visible = not linked_device
        rotate_row.visible = revoke_row.visible = rotate_button.visible = revoke_button.visible = bool(linked_device) and not linked_device.get('retired', False) and reset_state.get('status', 'not_requested') not in ('pending', 'received', 'applied')
        reset_button.visible = bool(linked_device) and not linked_device.get('retired', False) and reset_state.get('status', 'not_requested') in ('not_requested', 'failed', 'expired')
        reset_box.visible = bool(linked_device)
        if linked_device and (linked_device.get('retired') or reset_state.get('status') in ('pending', 'received', 'applied')):
            active.value, active.disabled = False, True
            active.draw()
        controls += [
            design.section_label('Conexão do equipamento'),
            note('Credencial e restauração simuladas' if is_demo else 'Credencial, chave e restauração'),
            note('Ações apenas desta demonstração; nada real é alterado.' if is_demo else
                 'Não é preciso mexer aqui para mudar tarifa ou disponibilidade.'),
            device_box,provision_row,rotate_row,revoke_row,reset_box]
        if reset_state.get('status') in ('pending', 'received'):
            app.set_poll(poll_reset, 5)
    controls.append(cta('Voltar ao posto',app.link('operator',station_id=station_id),primary=False,weight='semibold'))
    return design.page(*controls, gap=16)


def show_key(app, result):
    is_demo = bool(getattr(app.api,'is_demo',False))
    secret = ft.Text(result['device_key'],selectable=True)
    identifier = ft.Text('Device ID: '+result['device_id'],selectable=True)
    async def dismiss(e):
        secret.value = ''
        app.page.pop_dialog()
    dialog = ft.AlertDialog(modal=True,title=ft.Text('Chave fictícia de demonstração' if is_demo else 'Chave exibida uma vez'),content=ft.Column([identifier,secret,ft.Text('Esta chave é simulada. Não a instale em um equipamento real.' if is_demo else 'Copie para a configuração do equipamento agora. Não compartilhe. Ao fechar, a chave não será armazenada no app.')],tight=True),actions=[ft.TextButton('Fechar' if is_demo else 'Copiei, fechar',on_click=dismiss)])
    app.page.show_dialog(dialog)
