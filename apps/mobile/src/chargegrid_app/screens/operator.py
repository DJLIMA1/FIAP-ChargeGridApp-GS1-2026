import re
from decimal import Decimal, InvalidOperation

import flet as ft

from chargegrid_core.chargers import link as charger_link

from .. import api_cache
from ..api_client import ApiError
from ..services.charger_refresh import POLL_SECONDS, StationRefresh, merge_telemetry
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
                design.txt('Adicione uma central simulada para criar seu posto. Todo o processo acontece nesta demonstração.'
                           if is_demo else 'A central sem dono mostra um QR de vinculação. Escaneie-o para se tornar o proprietário.',
                           13, 'semibold'),
                design.txt('Depois informe nome, endereço e tarifa. O ponto só aparece aos motoristas quando você publicar.',
                           11, 'regular', theme.GRAY_TEXT),
                design.txt('Posto é o local com endereço. Cada ponto é um equipamento de recarga nesse local.',
                           11, 'regular', theme.GRAY_TEXT)], spacing=10)),
            text_button('Adicionar central simulada' if is_demo else 'Escanear QR da central',
                        app.link('operator', claim=True)),
            title='Configure seu primeiro ponto simulado' if is_demo else 'Configure sua primeira central',
            title_size=20)
    if connector_id:
        if connector_id == 'new':
            return await ownership.build(app, station_id=station_id)
        if station_id:
            with api_cache.network_only():
                owner = await app.api.request('GET',f'stations/{station_id}')
            found = next((item for item in owner.get('connectors') or [] if item.get('id') == connector_id),None)
            if found is None:
                raise ApiError('Carregador não encontrado nesta estação.', 404, 'not_found')
            connector = {**found,'station_name':owner.get('name')}
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
    screen = chargers.screen_online(station)  # estação = a central: online enquanto a central tiver contato
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
ADD_STATION_HINT = 'Pelo QR de uma central sem dono'
ADD_STATION_DEMO = 'Com uma central simulada'


async def station_list(app, offset, is_demo):
    params = {'limit': 100, 'offset': offset}
    result = await app.api.request('GET', 'operator/stations', params=params)
    stations = result['items']
    from .stations import _seed_details
    _seed_details(app, stations, 'operator/stations', params)
    add_label = 'Adicionar central simulada' if is_demo else 'Escanear QR da central'
    rows = [menu_row(station['name'], _station_state(station), '/design/icon_station_charge.svg',
                     app.link('station_admin', station_id=station['id']), tile=44) for station in stations]
    body = [ft.Container(height=8)]
    if rows:
        # Nova estação = o fluxo de vínculo que já cria o posto: QR da central sem dono (ou equipamento
        # simulado na demo) -> Localização (nome e endereço) -> Ponto e tarifa -> Revisão -> esta lista.
        rows.append(menu_row(ADD_STATION, ADD_STATION_DEMO if is_demo else ADD_STATION_HINT, ft.Icons.ADD,
                             app.link('operator', claim=True), tile=44))
        body.append(ft.Column(rows, spacing=22))
    else:
        body.append(design.card_box(ft.Column([
            design.txt('Seu primeiro ponto começa adicionando um equipamento simulado.' if is_demo else
                       'Seu primeiro ponto começa no QR do equipamento.', 13, 'semibold'),
            design.txt('Adicione um equipamento fictício para experimentar a gestão.' if is_demo else
                       'O QR é exibido pela central ainda sem dono.', 11, 'regular', theme.GRAY_TEXT),
            design.txt('1. Adicione uma central simulada.\n2. Configure nome, endereço de exemplo e tarifa.\n'
                       '3. Revise, publique e teste a recarga simulada.' if is_demo else
                       '1. Ligue a central e configure o Wi-Fi, se necessário.\n2. Escaneie o QR com sua conta de operador.\n'
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
    """Status do CARREGADOR: Desvinculado, Desativado, Online, Offline ou Aguardando a central."""
    if connector.get('retired') or (device or {}).get('retired'):
        return 'Desvinculado', theme.SLATE
    if not connector.get('active', True) or connector.get('availability_status') == 'disabled':
        return 'Desativado', theme.AMBER
    if connector.get('charger_link') and (device or {}).get('online') is not False:
        return chargers.link_status(connector)  # o link lido pela central (online/offline/aguardando a central)
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
    """Editar carregador: status ao vivo no topo, campos do conector, identificação e ``Salvar alterações`` por último.

    Cada identificador aparece uma vez: o código público e o endereço do carregador só nos campos de
    Identificação; o cartão do topo usa o nome ``Carregador N`` (o mesmo da lista) e o status."""
    connector = connector or {}
    # Form fields: the TextFields stay the source of truth for save().
    gap = 8
    public_box = setup_field('Código público', connector.get('public_code',''), gap=gap, height=FIELD_HEIGHT)
    kind_box = setup_field('Tipo de conector', connector.get('connector_type','Tipo 2'), gap=gap, height=FIELD_HEIGHT)
    power_box = setup_field('Potência', _decimal_text(connector.get('power_kw','7.4')), keyboard=ft.KeyboardType.NUMBER,
                            gap=gap, height=FIELD_HEIGHT, suffix='kW')
    duration_box = setup_field('Limite por recarga', str(connector.get('max_duration_minutes','60')),
                               keyboard=ft.KeyboardType.NUMBER, gap=gap, height=FIELD_HEIGHT, suffix='min')
    public, kind, power, duration = (box.controls[1] for box in (public_box, kind_box, power_box, duration_box))
    back_to_connectors = app.link('station_admin', station_id=station_id, page='connectors')
    active = _Toggle(app, connector.get('active',True))
    active_box = ft.Column([design.label('Disponível para motoristas', strong=False), active.holder], spacing=6,
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

    refresh = StationRefresh(app, station_id)
    address_field = charger_address_field(connector) if connector else None

    async def save():
        refresh.invalidate()
        body = {'public_code':onboarding_screen._required(public,'código público',50),
                'connector_type':onboarding_screen._required(kind,'tipo de conector',50),
                'power_kw':onboarding_screen._number(power,'Potência',Decimal('0.001'),1000),
                'max_duration_minutes':onboarding_screen._number(duration,'Limite',1,1440,integer=True)}
        moved = None
        if connector:
            body['active'] = active.value
        if address_field is not None and ((address_field.value or '').strip()
                                          or connector.get('charger_address') is not None):
            try:
                address = charger_address_input(address_field.value)
            except ValueError as exc:
                address_field.error_text = str(exc)
                app.page.update()
                raise ApiError(str(exc)) from None
            address_field.error_text = None
            if address != connector.get('charger_address'):
                body['charger_address'] = moved = address  # só quando muda: o mesmo endereço não é reenviado
        refresh.invalidate()
        try:
            await app.api.request('PATCH' if connector else 'POST',
                                  f"connectors/{connector['id']}" if connector else f'stations/{station_id}/connectors', body)
        except ApiError as exc:
            if address_field is not None and exc.code in _ADDRESS_ERRORS:
                address_field.error_text = str(exc)
                app.page.update()
            raise
        finally:
            refresh.invalidate()
        if hasattr(app,'mark_saved'):
            app.mark_saved()
        if moved is not None:
            app.notice(f'Endereço {moved} salvo. Configure CG_ADDR = {moved} no ESP do carregador.')
        await app.go('station_admin',station_id=station_id,page='connectors')

    note = lambda text: design.txt(text, 11, 'regular', theme.GRAY_TEXT)  # noqa: E731
    controls = [setup_title(app, 'Editar carregador' if connector else 'Novo carregador', on_back=back_to_connectors,
                            bottom=2.25)]
    if connector:
        charger, redraw_charger = charger_card(app, connector)
        controls.append(charger)
    controls += [
        _section('Conector', ft.Row(list(type_chips.values()), wrap=True, spacing=8, run_spacing=8), kind_box,
                 power_box, ft.Row(list(power_chips.values()), wrap=True, spacing=8, run_spacing=8)),
        _section('Recarga', duration_box,
                 note('Tempo máximo de cada recarga. A tarifa por kWh fica em Tarifa, na tela do posto.'),
                 *([active_box, note('O posto também precisa estar ativo para o carregador aparecer na busca.')]
                   if connector else [])),
    ]
    identity = [public_box, note('Código exibido aos motoristas para encontrar este carregador.')]
    if address_field is not None:
        identity += [ft.Column([design.label(CHARGER_FIELD), address_field], spacing=gap,
                               horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                     note('Único no posto. Use o mesmo número no CG_ADDR do ESP do carregador.')]
    controls.append(_section('Identificação', *identity))
    if connector and chargers.removable(connector):
        controls.append(remove_box(app, station_id, connector, refresh))
    controls.append(cta('Salvar alterações' if connector else 'Salvar carregador', app.action(save), weight='semibold'))
    if connector:
        async def update():
            fresh = await refresh.read()
            if not isinstance(fresh, dict):
                return
            latest = next((p for p in fresh.get('connectors', []) if p['id'] == connector['id']), None)
            if latest is None:
                return
            merge_telemetry(connector, latest)
            redraw_charger()
            app.page.update()

        app.set_poll(update, POLL_SECONDS)
    return design.page(*controls, gap=20)


def _section(title, *controls):
    """Título de seção + campos com o mesmo respiro (o ``gap`` da página separa as seções)."""
    return ft.Column([design.section_label(title), *controls], spacing=12,
                     horizontal_alignment=ft.CrossAxisAlignment.STRETCH)


CHARGER_FIELD = 'Endereço do carregador'
CHARGER_HINT = f'{charger_link.MIN_ADDRESS} a {charger_link.MAX_ADDRESS}'
_ADDRESS_ERRORS = ('invalid_charger_address', 'charger_address_taken')


def charger_status(connector):
    """``Carregador 1 · GoodWe HCA G2 (simulado) · online`` (``offline``, ``aguardando a central``), do core.

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


def charger_address_field(connector):
    """Campo do endereço Modbus (1–247), salvo junto com o formulário."""
    current = connector.get('charger_address')
    field = setup_field(CHARGER_FIELD, '' if current is None else str(current), CHARGER_HINT,
                        keyboard=ft.KeyboardType.NUMBER, height=FIELD_HEIGHT).controls[1]
    field.input_filter = ft.InputFilter(regex_string=r'[0-9 ]', allow=True)
    return field


def charger_card(app, connector):
    """Cartão do topo: ``Carregador N`` + status, modelo/potência, última leitura e potência lida.

    Estável durante o poll: ``draw()`` só troca os textos (nenhum controle é recriado)."""
    name = design.txt('', 15, 'bold', expand=True)
    subtitle = design.txt('', 11, 'regular', theme.GRAY_TEXT)
    badge = chargers.pill('', theme.SLATE)
    reading = design.txt('', 12.5, 'bold', text_align=ft.TextAlign.END)
    measured = design.txt('', 12.5, 'bold', text_align=ft.TextAlign.END)

    def draw():
        block = connector.get('charger_link') or {}
        label, color = _point_status(connector)
        address = chargers.address_of(connector)
        name.value = f'Carregador {address}' if address is not None else 'Carregador'
        place = connector.get('station_name')
        subtitle.value = ' · '.join(part for part in (place, charger_link.STATUS_LABEL, chargers.spec_line(connector))
                                    if part)
        badge.content.value, badge.bgcolor, badge.content.color = label, color, theme.on_color(color)
        reading.value = date_time(block['last_online_at']) if block.get('last_online_at') else 'Sem leitura'
        measured.value = chargers.measured_text(block.get('measured_power_w'))

    lines = [ft.Column([ft.Row([name, badge], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER), subtitle],
                       spacing=4),
             chargers.row('Última leitura', reading), chargers.row('Potência lida', measured)]
    if getattr(app.api, 'is_demo', False):
        from ..demo import DEMO_PRESENCE_CODE
        lines.append(design.txt(f'Carregador simulado. Teste no modo motorista com {DEMO_PRESENCE_CODE}.',
                                10.5, 'regular', theme.GRAY_TEXT))
    holder = ft.Container(design.card_box(
        ft.Column(lines, spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
        padding=ft.Padding(left=15, right=15, top=14, bottom=15), radius=18), data='charger-card')
    draw()
    return holder, draw


def remove_box(app, station_id, connector, refresh=None):
    """Zona de perigo: ``Remover carregador N`` (só carregador adicional; o da central nunca)."""
    address = chargers.address_of(connector)
    title = f'Remover carregador {address}?' if address is not None else 'Remover este carregador?'

    async def confirm():
        app.page.pop_dialog()
        if refresh is not None:
            refresh.invalidate()
        await chargers.remove_charger(app, connector)
        if hasattr(app, 'mark_saved'):
            app.mark_saved()
        app.notice(chargers.removed_text(connector))
        await app.go('station_admin', station_id=station_id, page='connectors')

    async def ask():
        if hasattr(app, 'prepare_navigation') and not await app.prepare_navigation():
            return
        app.page.show_dialog(ft.AlertDialog(
            modal=True, title=ft.Text(title),
            content=ft.Text(chargers.REMOVE_DETAIL),
            actions=[ft.TextButton('Cancelar', on_click=lambda event: app.page.pop_dialog()),
                     ft.TextButton('Remover', on_click=app.action(confirm), style=ft.ButtonStyle(color=theme.RED))]))

    return ft.Container(
        ft.Row([design.txt(chargers.REMOVE_HINT, 10.5, 'regular', theme.GRAY_TEXT, expand=True),
                _mini_button(chargers.REMOVE_LABEL, app.action(ask), 'danger')],
               spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor=theme.WARN_BG, border=ft.Border.all(1, ft.Colors.with_opacity(0.45, theme.RED)),
        border_radius=design.RADIUS_BTN, padding=ft.Padding(left=12, right=10, top=10, bottom=10), data='remove-charger')


def show_key(app, result):
    is_demo = bool(getattr(app.api,'is_demo',False))
    secret = ft.Text(result['device_key'],selectable=True)
    identifier = ft.Text('Device ID: '+result['device_id'],selectable=True)
    async def dismiss(e):
        secret.value = ''
        app.page.pop_dialog()
    dialog = ft.AlertDialog(modal=True,title=ft.Text('Chave fictícia de demonstração' if is_demo else 'Chave exibida uma vez'),content=ft.Column([identifier,secret,ft.Text('Esta chave é simulada. Não a instale em um equipamento real.' if is_demo else 'Copie para a configuração do equipamento agora. Não compartilhe. Ao fechar, a chave não será armazenada no app.')],tight=True),actions=[ft.TextButton('Fechar' if is_demo else 'Copiei, fechar',on_click=dismiss)])
    app.page.show_dialog(dialog)
