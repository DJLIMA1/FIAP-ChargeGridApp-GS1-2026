import re
from decimal import Decimal, InvalidOperation

import flet as ft

from chargegrid_core.chargers import link as charger_link

from ..api_client import ApiError
from ..services.location import station_location
from ..ui import address_autocomplete, design, theme
from ..ui.ai_features import ai_supported, owner_insights_control
from ..ui.components import (
    date_time,
    money,
    title,
)
from . import chargers, ownership
from . import onboarding as onboarding_screen
from .setup_ui import FIELD_HEIGHT, cta, setup_field, setup_title
from .station_admin import chatbot_button, menu_row


def _plural(count, one, many):
    return f'{count} {one if count == 1 else many}'


async def build(app, station_id=None, connector_id=None, device_id=None, offset=0, connector=None,
                claim=False, onboarding=False, point_id=None, step=1, existing_station=False, edited=False,
                show_real=False, **_):
    is_demo = bool(getattr(app.api,'is_demo',False))
    prefetch = getattr(app.api,'prefetch',None)
    if prefetch is not None and not (claim or onboarding or connector_id or station_id == 'new'):
        # A lista (ou o posto) sai junto com o perfil, em paralelo, e não depois dele.
        prefetch('operator/stations',{'limit':100,'offset':0 if station_id else offset})
        if station_id:
            prefetch(f'stations/{station_id}')
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
        # Um único lugar para cada posto: dados, conectores, potência e tarifas (station_admin).
        from . import station_admin
        return await station_admin.build(app, station_id=station_id)
    return await station_list(app, offset, is_demo)


def _station_state(station):
    points = [point for point in station.get('connectors') or [] if not point.get('retired')]
    online = [point for point in points if point.get('online')]
    in_use = [point for point in online if point.get('available') is False]
    live = [point for point in points if point.get('active', True)]
    screen = chargers.screen_online(station)  # estação = a tela: online enquanto a tela tiver contato
    if not station.get('active', True):
        status = 'Desativada'
    elif points and not live:
        return 'Carregadores desativados - revise para publicar'
    elif online or screen:
        status = 'Online'
    else:
        status = 'Offline'
    if in_use:
        return f'{status} - Carregadores em uso'
    return f'{status} - Carregadores livres' if online and station.get('active', True) else status


def text_button(text, on_click, *, primary=True, height=48):
    """Botão com o texto como conteúdo direto (primário branco ou secundário escuro)."""
    return ft.Container(design.txt(text, 14.5, 'semibold', theme.BTN_PRIMARY_FG if primary else theme.BTN_SECONDARY_FG,
                                   text_align=ft.TextAlign.CENTER),
                        bgcolor=theme.BTN_PRIMARY if primary else theme.BTN_SECONDARY, border_radius=design.RADIUS_BTN,
                        height=height, alignment=ft.Alignment(0, 0), on_click=on_click, ink=True)


ADD_STATION = 'Adicionar nova estação'
ADD_STATION_HINT = 'Pelo QR de uma tela sem dono'
ADD_STATION_DEMO = 'Com um equipamento simulado'


async def station_list(app, offset, is_demo):
    params = {'limit': 100, 'offset': offset}
    result = await app.api.request('GET', 'operator/stations', params=params)
    stations = result['items']
    from .stations import _seed_details
    _seed_details(app, stations, 'operator/stations', params)
    add_label = 'Adicionar equipamento simulado' if is_demo else 'Escanear QR da tela'
    rows = [menu_row(station['name'], _station_state(station), '/design/icon_station_charge.svg',
                     app.link('station_admin', station_id=station['id']), tile=44) for station in stations]
    body = [ft.Container(height=8)]
    if rows:
        # Nova estação = o fluxo de vínculo que já cria o posto: QR da tela sem dono (ou equipamento
        # simulado na demo) -> Localização (nome e endereço) -> Ponto e tarifa -> Revisão -> esta lista.
        rows.append(menu_row(ADD_STATION, ADD_STATION_DEMO if is_demo else ADD_STATION_HINT, ft.Icons.ADD,
                             app.link('operator', claim=True), tile=44))
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
    """Criar posto (``Configurar Estação``): nome e endereço com sugestões; a localização vem do endereço.

    Postos existentes são editados em ``station_admin`` (dados, carregadores, potência e tarifas)."""
    is_demo = bool(getattr(app.api,'is_demo',False))
    name_box = setup_field('Nome da estação', '', 'Ex.: Posto Centro', gap=14, height=FIELD_HEIGHT)
    address_box = setup_field('Endereço', '', 'Rua, número, bairro, cidade e estado', gap=14, height=FIELD_HEIGHT)
    name, address = name_box.controls[1], address_box.controls[1]
    chosen = {}
    address_box.controls.append(address_autocomplete.attach(app, address, lambda item: chosen.update(item=item)))

    async def save():
        body = {'name':onboarding_screen._required(name,'nome do posto',100),
                'address':onboarding_screen._required(address,'endereço',300)}
        try:
            body['latitude'], body['longitude'] = (str(value) for value in await station_location(
                app.api, body['address'], chosen.get('item'), demo=is_demo))
        except ValueError as error:
            address.error_text = str(error)
            app.page.update()
            raise ApiError(str(error)) from None
        result = await app.api.request('POST','stations',body)
        if hasattr(app,'mark_saved'):
            app.mark_saved()
        await app.go('station_admin',station_id=result['id'])
    return design.page(
        setup_title(app, 'Configurar Estação', bottom=2.25),
        ft.Column([name_box, address_box], spacing=15.5, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
        design.txt('Escolha uma sugestão de endereço: a localização no mapa vem dele.', 11.5, 'regular', theme.GRAY_TEXT),
        cta('Salvar posto', app.action(save), weight='semibold', height=47.5),
        cta('Voltar à gestão',app.link('operator'),primary=False,weight='semibold'), gap=16)


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
    """Status do CARREGADOR: Desvinculado, Desativado, Online, Offline ou Aguardando a tela."""
    if connector.get('retired') or (device or {}).get('retired'):
        return 'Desvinculado', theme.SLATE
    if not connector.get('active', True):
        return 'Desativado', theme.AMBER
    if connector.get('charger_link') and (device or {}).get('online') is not False:
        return chargers.link_status(connector)  # o link lido pela tela (online/offline/aguardando a tela)
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
    duration_box = setup_field('Limite por recarga', str(connector.get('max_duration_minutes','60')),
                               keyboard=ft.KeyboardType.NUMBER, gap=gap, height=FIELD_HEIGHT, suffix='min')
    public, kind, power, duration = (box.controls[1] for box in (public_box, kind_box, power_box, duration_box))
    # Dispositivo (a tela) que comanda este carregador: só leitura, usado por trocar chave/revogar.
    device = design.txt(linked_device['device_id'] if linked_device else '', 12.5, 'bold', data='device-id',
                        text_align=ft.TextAlign.END)
    back_to_connectors = app.link('station_admin', station_id=station_id, page='connectors')
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

    device_status = ft.Text(
        ('Desvinculado após restauração de fábrica' if linked_device.get('retired') else
         'Último contato: '+date_time(linked_device.get('last_seen')))
        if linked_device else 'Nenhum equipamento simulado vinculado.' if is_demo else
        'Nenhum equipamento vinculado. Provisione uma credencial abaixo.',
        size=13,color=theme.TEXT_COLOR,expand=True,font_family=design.FONT,
    )
    status_label, status_color = _point_status(connector, linked_device)
    status_badge = _status_pill(status_label, status_color)
    def paint_status():
        label, color = _point_status(connector, linked_device)
        status_badge.content.value = label
        status_badge.bgcolor = color
        status_badge.content.color = theme.on_color(color)

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
        paint_status()
        app.page.update()
    async def save():
        body = {'public_code':onboarding_screen._required(public,'código público',50),
                'connector_type':onboarding_screen._required(kind,'tipo de conector',50),
                'power_kw':onboarding_screen._number(power,'Potência',Decimal('0.001'),1000),
                'max_duration_minutes':onboarding_screen._number(duration,'Limite',1,1440,integer=True)}
        if connector:
            body['active'] = active.value
        await app.api.request('PATCH' if connector else 'POST',f"connectors/{connector['id']}" if connector else f'stations/{station_id}/connectors',body)
        if hasattr(app,'mark_saved'):
            app.mark_saved()
        await app.go('station_admin',station_id=station_id,page='connectors')
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
            key_row.visible = rotate_button.visible = revoke_button.visible = False
        elif status in ('failed', 'expired'):
            active.disabled = False
            active.draw()
            key_row.visible = rotate_button.visible = revoke_button.visible = True
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
        setup_title(app, 'Editar carregador' if connector else 'Novo carregador', on_back=back_to_connectors,
                    bottom=2.25),
        design.card_box(ft.Column(header,spacing=8)),
        design.section_label('Conector'),
        ft.Row(list(type_chips.values()),wrap=True,spacing=8,run_spacing=8),
        kind_box,
        power_box,
        ft.Row(list(power_chips.values()),wrap=True,spacing=8,run_spacing=8),
        design.section_label('Tempo por recarga'),
        duration_box,
        note('Tempo máximo de cada recarga. A tarifa por kWh fica em Tarifa, na tela do posto.'),
    ]
    if connector:
        controls += [active_box, note('O posto também precisa estar ativo para o carregador aparecer na busca.')]
    controls += [design.section_label('Identificação'), public_box,
                 note('Código exibido aos motoristas para encontrar este carregador.'),
                 cta('Salvar alterações' if connector else 'Salvar carregador',app.action(save),weight='semibold')]
    if connector:
        # Daqui para baixo: o carregador GoodWe HCA G2 (simulado) e a tela que o comanda.
        provision_button = _mini_button('Provisionar',app.action(provision),'primary')
        rotate_button = _mini_button('Rotacionar',app.action(rotate))
        revoke_button = _mini_button('Revogar',app.action(revoke))
        reset_button = _mini_button('Restaurar',app.action(reset_device),'danger')
        for button in (rotate_button, revoke_button):
            button.expand = True
        provision_row = ft.Row([design.txt('Sem credencial. Gere uma para a tela conectar.' if not is_demo else
                                           'Sem credencial simulada.', 11.5, 'regular', theme.GRAY_TEXT, expand=True),
                                provision_button], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        key_row = ft.Row([rotate_button, revoke_button], spacing=10)
        reset_box = ft.Container(
            ft.Row([design.txt(reset_messages['not_requested'], 10.5, 'regular', theme.GRAY_TEXT, expand=True),
                    reset_button], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            bgcolor=theme.WARN_BG, border=ft.Border.all(1, ft.Colors.with_opacity(0.45, theme.RED)),
            border_radius=design.RADIUS_BTN, padding=ft.Padding(left=12, right=10, top=10, bottom=10))
        device_row = chargers.row('Dispositivo', device)
        maintenance_ok = bool(linked_device) and not linked_device.get('retired', False) and \
            reset_state.get('status', 'not_requested') not in ('pending', 'received', 'applied')
        provision_row.visible = provision_button.visible = not linked_device
        key_row.visible = rotate_button.visible = revoke_button.visible = maintenance_ok
        reset_button.visible = bool(linked_device) and not linked_device.get('retired', False) and reset_state.get('status', 'not_requested') in ('not_requested', 'failed', 'expired')
        reset_box.visible = device_row.visible = bool(linked_device)
        if linked_device and (linked_device.get('retired') or reset_state.get('status') in ('pending', 'received', 'applied')):
            active.value, active.disabled = False, True
            active.draw()
        controls += [design.section_label('Carregador e tela'),
                     charger_controls(app, connector),
                     screen_card(app, station_id, connector, linked_device, device_row,
                                 [design.txt('Credencial e restauração simuladas' if is_demo else
                                             'Credencial e restauração da tela', 11, 'bold', theme.GRAY_TEXT),
                                  provision_row, key_row, reset_box])]
        if reset_state.get('status') in ('pending', 'received'):
            app.set_poll(poll_reset, 5)
    controls.append(cta('Voltar aos carregadores',back_to_connectors,primary=False,weight='semibold'))
    return design.page(*controls, gap=16)


CHARGER_FIELD = 'Endereço do carregador'
CHARGER_HINT = f'{charger_link.MIN_ADDRESS} a {charger_link.MAX_ADDRESS}'
_ADDRESS_ERRORS = ('invalid_charger_address', 'charger_address_taken')


def charger_status(connector):
    """``Carregador 1 · GoodWe HCA G2 (simulado) · online`` (``offline``, ``aguardando a tela``), do core.

    Todo ponto é um carregador GoodWe HCA G2; vazio só em payload sem endereço (API antiga/motorista)."""
    block = connector.get('charger_link')
    if not block and connector.get('charger_address') is not None:
        block = charger_link.owner_block(connector['charger_address'], None, bool(connector.get('online')))
    return charger_link.status_text(block)


def charger_address_input(value):
    """Endereço digitado → int 1–247 (mensagens do core; vazio não é aceito)."""
    text = (value or '').strip()
    if not text:
        return charger_link.validate_address(None)
    try:
        number = int(text)
    except ValueError:
        raise ValueError('Endereço do carregador deve ser um número inteiro de 1 a 247') from None
    return charger_link.validate_address(number)


def charger_controls(app, connector):
    """Cartão do carregador GoodWe HCA G2 (simulado): status do link, endereço (salvo à parte),
    última leitura e potência lida. Salva só ``charger_address`` (``PATCH connectors``)."""
    current = connector.get('charger_address')
    field = design.input_field('' if current is None else str(current), CHARGER_HINT, keyboard=ft.KeyboardType.NUMBER)
    field.data = CHARGER_FIELD
    field.input_filter = ft.InputFilter(regex_string=r'[0-9 ]', allow=True)
    field.fill_color = theme.BTN_SECONDARY  # destaca o campo sobre o cartão
    holder = ft.Container(data='charger-card')

    def draw():
        block = connector.get('charger_link') or {}
        label, color = chargers.link_status(connector)
        editor = ft.Row([ft.Container(field, expand=True), _mini_button('Salvar', app.action(save), 'primary')],
                        spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        address = chargers.address_of(connector)
        holder.content = chargers.card(
            f'Carregador {address}' if address is not None else 'Carregador',
            ft.Column([design.label(CHARGER_FIELD), editor,
                       design.txt('Único no posto. Use o mesmo número no CG_ADDR do ESP do carregador.', 10.5,
                                  'regular', theme.GRAY_TEXT)], spacing=6,
                      horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
            chargers.row('Última leitura', date_time(block.get('last_online_at')) if block.get('last_online_at')
                         else 'Sem leitura'),
            chargers.row('Potência lida', chargers.measured_text(block.get('measured_power_w'))),
            trailing=chargers.pill(label, color),
            subtitle=f'{charger_link.STATUS_LABEL} · {chargers.spec_line(connector)}')

    def refuse(message):
        field.error_text = message
        app.page.update()
        raise ApiError(message)

    async def save():
        try:
            address = charger_address_input(field.value)
        except ValueError as exc:
            refuse(str(exc))
        try:
            saved = await app.api.request('PATCH', f"connectors/{connector['id']}", {'charger_address': address})
        except ApiError as exc:
            if exc.code in _ADDRESS_ERRORS:
                field.error_text = str(exc)
                app.page.update()
            raise
        saved = saved if isinstance(saved, dict) else {}
        connector['charger_address'] = saved.get('charger_address', address)
        connector['charger_link'] = saved.get('charger_link')
        for key in ('online', 'screen', 'screen_online', 'unavailable_reason'):
            if key in saved:
                connector[key] = saved[key]
        field.value = str(connector['charger_address'])
        field.error_text = None
        draw()
        app.page.update()
        app.notice(f'Endereço {connector["charger_address"]} salvo. Configure CG_ADDR = '
                   f'{connector["charger_address"]} no ESP do carregador.')

    draw()
    return holder


def screen_card(app, station_id, connector, linked_device, device_row, maintenance):
    """Vínculo com a TELA da estação: código do ponto da tela, online, papel e (no ponto da tela) a
    credencial/restauração. Carregador adicional: atalho para a tela, sem ações de credencial aqui."""
    screen = connector.get('screen') if isinstance(connector.get('screen'), dict) else None
    if screen is None and linked_device:
        screen = {'device_id': linked_device.get('device_id'), 'online': linked_device.get('online'),
                  'last_seen': linked_device.get('last_seen'), 'public_code': connector.get('public_code'),
                  'role': 'screen'}
    role = (screen or {}).get('role') or 'screen'
    if screen is None:
        return chargers.card('Tela da estação', device_row, *maintenance, subtitle='Nenhuma tela vinculada a este ponto.')
    label, color = chargers.screen_status(screen.get('online'))
    rows = [chargers.row('Ponto da tela', screen.get('public_code') or '—'),
            chargers.row('Último contato', date_time(screen.get('last_seen')) if screen.get('last_seen') else 'Sem contato')]
    if role == 'charger':
        rows.append(cta(f"Abrir a tela ({screen.get('public_code') or 'ponto da tela'})",
                        app.link('operator', station_id=station_id, connector_id=screen.get('connector_id'), nav=False),
                        primary=False, height=42, size=13, weight='semibold'))
        return chargers.card('Tela da estação', *rows, trailing=_status_pill(label, color),
                             subtitle=chargers.ROLE_LABELS['charger'])
    return chargers.card('Tela da estação', *rows, device_row, ft.Divider(height=1, color=theme.BORDER_SOFT),
                         *maintenance, trailing=_status_pill(label, color), subtitle=chargers.ROLE_LABELS['screen'])


def show_key(app, result):
    is_demo = bool(getattr(app.api,'is_demo',False))
    secret = ft.Text(result['device_key'],selectable=True)
    identifier = ft.Text('Device ID: '+result['device_id'],selectable=True)
    async def dismiss(e):
        secret.value = ''
        app.page.pop_dialog()
    dialog = ft.AlertDialog(modal=True,title=ft.Text('Chave fictícia de demonstração' if is_demo else 'Chave exibida uma vez'),content=ft.Column([identifier,secret,ft.Text('Esta chave é simulada. Não a instale em um equipamento real.' if is_demo else 'Copie para a configuração do equipamento agora. Não compartilhe. Ao fechar, a chave não será armazenada no app.')],tight=True),actions=[ft.TextButton('Fechar' if is_demo else 'Copiei, fechar',on_click=dismiss)])
    app.page.show_dialog(dialog)
