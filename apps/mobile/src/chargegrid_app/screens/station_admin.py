"""Estação do vendedor: detalhe e subpáginas (dados, potência por conector, limite de bateria).

Rota ``station_admin`` (``station_id``, ``page`` = None | 'data' | 'power' | 'battery').
Nome, endereço e status usam ``PATCH stations``; a potência usa ``PATCH connectors`` (``power_kw``);
o limite de bateria é uma regra local simulada (``services/station_settings.py``).
"""

import math

import flet as ft

from ..api_client import ApiError
from ..services import station_settings
from ..ui import design, theme

POWER_MAX = {'Tipo 2': 45}
POWER_MAX_DEFAULT = 80
POWER_MIN = 1


def _street(address):
    from .stations import _street as street
    return street(address)


def station_code(stations, station_id):
    """Identificador exibido (``CG-001``): posição da estação na lista do vendedor."""
    for index, item in enumerate(stations or [], 1):
        if item.get('id') == station_id:
            return f'CG-{index:03d}'
    return 'CG-001'


def _power_text(value):
    try:
        number = float(str(value).replace(',', '.'))
    except (TypeError, ValueError):
        return '0'
    return str(int(number)) if number == int(number) else f'{number:.1f}'.replace('.', ',')


def _live_points(station):
    return [point for point in station.get('connectors') or [] if not point.get('retired')]


def menu_row(title, subtitle, icon, on_click=None, *, tile=38, chevron=True, tile_control=None):
    """Linha sem cartão: tile escuro + título/subtítulo + ``>`` (visual das listas do vendedor)."""
    lead = tile_control if tile_control is not None else design.icon_tile(icon, size=tile, dark=True)
    if tile_control is None and tile < 44:
        lead = ft.Container(lead.content, width=tile, height=tile - 4, bgcolor=theme.TILE, border_radius=10,
                            alignment=ft.Alignment(0, 0))
    parts = [lead, ft.Column([design.txt(title, 12.7, 'semibold'), design.txt(subtitle, 9.7, 'regular', theme.GRAY_TEXT)],
                             spacing=3, expand=True, alignment=ft.MainAxisAlignment.CENTER)]
    if chevron:
        parts.append(ft.Icon(ft.Icons.CHEVRON_RIGHT, size=22, color=theme.GRAY_TEXT))
    return ft.Container(ft.Row(parts, spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        on_click=on_click, ink=False, height=max(tile, 38), padding=ft.Padding(left=0, right=0, top=0, bottom=0))


def heading(app, text, on_back=None):
    """Título de tela do vendedor: ``<`` grande + título 22 em negrito."""
    back = ft.Container(ft.Icon(ft.Icons.CHEVRON_LEFT, size=42, color=theme.TEXT_COLOR), on_click=on_back or app.back,
                        ink=False, width=44, height=34, alignment=ft.Alignment(0, 0), tooltip='Voltar',
                        margin=ft.Margin(left=-10, top=0, right=-2, bottom=0))
    return ft.Container(ft.Row([back, design.txt(text, 22, 'bold', expand=True)], spacing=0,
                               vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        height=34, margin=ft.Margin(left=0, top=-1, right=0, bottom=0))


def battery_tile():
    return ft.Container(ft.Icon(ft.Icons.BATTERY_0_BAR_OUTLINED, size=20, color=theme.TILE_FG, rotate=ft.Rotate(math.pi / 2)),
                        width=38, height=34, bgcolor=theme.TILE, border_radius=10, alignment=ft.Alignment(0, 0))


def _round(field):
    return ft.Container(field, border_radius=14, bgcolor=theme.INPUT_BG, clip_behavior=ft.ClipBehavior.ANTI_ALIAS)


def chatbot_button(app, height=40):
    """Botão branco "Fale com o ChatBot" (ícone de balão redondo, texto regular)."""
    content = ft.Row([ft.Image(src='/design/nav_chat.svg', width=20, height=20, color=theme.BTN_PRIMARY_FG,
                               exclude_from_semantics=True),
                      design.txt('Fale com o ChatBot', 15, 'regular', theme.BTN_PRIMARY_FG)],
                     spacing=10, alignment=ft.MainAxisAlignment.CENTER, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    return ft.Container(content, height=height, bgcolor=theme.BTN_PRIMARY, border_radius=design.RADIUS_BTN,
                        alignment=ft.Alignment(0, 0), on_click=app.link('chat'), ink=True)


async def _load(app, station_id):
    import asyncio
    station, listing = await asyncio.gather(
        app.api.request('GET', f'stations/{station_id}'),
        app.api.request('GET', 'operator/stations', params={'limit': 100, 'offset': 0}))
    items = listing.get('items', []) if isinstance(listing, dict) else []
    return station, station_code(items, station_id)


async def build(app, station_id=None, page=None, **params):
    if not station_id:
        from . import operator
        return await operator.build(app)
    station, code = await _load(app, station_id)
    if page == 'data':
        return _data_page(app, station, code)
    if page == 'power':
        return _power_page(app, station)
    if page == 'battery':
        return _battery_page(app, station)
    return _main_page(app, station, code)


def _main_page(app, station, code):
    sid = station['id']
    points = _live_points(station)
    power_line = ' - '.join(dict.fromkeys(f"{point.get('connector_type')}: {_power_text(point.get('power_kw'))} kW"
                                          for point in points)) or 'Nenhum conector vinculado'
    go = lambda page: app.link('station_admin', station_id=sid, page=page)  # noqa: E731
    return design.page(
        heading(app, station.get('name') or 'Estação'),
        ft.Container(height=11),
        ft.Column([design.txt(f'Estação {code}', 16, 'bold'),
                   design.txt(_street(station.get('address')), 11, 'regular', theme.GRAY_TEXT)], spacing=9),
        ft.Container(height=19),
        ft.Column([
            menu_row('Dados da estação', 'Endereço, nome e status', ft.Icons.EDIT_OUTLINED, go('data')),
            menu_row('Potência por conector', power_line, ft.Icons.BOLT_OUTLINED, go('power')),
            menu_row('Tarifas dinâmicas', 'Rotatividade, demanda e pico', ft.Icons.TRENDING_UP,
                     app.link('tariffs', station_id=sid)),
            menu_row('Limite de bateria', 'Proteção e alertas de carga', None, go('battery'), tile_control=battery_tile()),
        ], spacing=29),
        ft.Container(height=18),
        chatbot_button(app, 38), gap=14)


def _data_page(app, station, code):
    sid = station['id']
    name = design.input_field(station.get('name') or '')
    address = design.input_field(station.get('address') or '')
    ident = design.input_field(code, read_only=True)
    state = {'active': station.get('active', True), 'saved': (station.get('name'), station.get('address'))}
    holder = ft.Container()

    async def persist(extra=None):
        current = (name.value.strip(), address.value.strip())
        body = dict(extra or {})
        if current != state['saved']:
            if not current[0] or not current[1]:
                raise ApiError('Informe nome e endereço da estação.')
            body.update({'name': current[0], 'address': current[1]})
        if not body:
            return
        await app.api.request('PATCH', f'stations/{sid}', body)
        state['saved'] = current
        if hasattr(app, 'mark_saved'):
            app.mark_saved()
        app.notice('Dados da estação salvos.')

    async def blur():
        await persist()

    async def choose(value):
        active = value == 'on'
        try:
            await persist({'active': active})
        except ApiError as exc:
            app.notice(str(exc))
            return
        state['active'] = active
        draw()
        app.page.update()

    def draw():
        holder.content = design.segmented([('on', 'Ativa'), ('off', 'Inativa')],
                                          'on' if state['active'] else 'off', choose, height=37.5)
    draw()
    name.on_blur = app.action(blur)
    address.on_blur = app.action(blur)
    name.on_submit = app.action(blur)
    address.on_submit = app.action(blur)
    return design.page(
        heading(app, 'Dados de estação'),
        ft.Container(ft.Column([
            design.labeled('Nome da estação', _round(name), gap=14),
            design.labeled('Endereço', _round(address), gap=14),
            design.labeled('Identificador', _round(ident), gap=14),
            ft.Container(design.labeled('Status', holder, gap=5, strong=False), margin=ft.Margin(left=0, top=1, right=0, bottom=0)),
        ], spacing=15), margin=ft.Margin(left=0, top=16, right=0, bottom=0)),
        ft.Container(height=5),
        ft.Container(design.section_label('Configurações adicionais'), margin=ft.Margin(left=0, top=0, right=0, bottom=-3)),
        menu_row('Potência por conector', 'Definir limite de cada conector', ft.Icons.BOLT_OUTLINED,
                 app.link('station_admin', station_id=sid, page='power')),
        ft.Container(height=8),
        menu_row('Pontos e equipamentos', 'Vincular por QR, editar e restaurar', ft.Icons.QR_CODE_SCANNER,
                 app.link('operator', station_id=sid, nav=False)),
        gap=16, gutter=3)


def _power_page(app, station):
    points = _live_points(station)
    controls = []
    if not points:
        controls.append(design.txt('Nenhum conector vinculado a esta estação.', 12, 'regular', theme.GRAY_TEXT))
    for index, point in enumerate(points, 1):
        kind = point.get('connector_type') or 'Conector'
        top = POWER_MAX.get(kind, POWER_MAX_DEFAULT)
        try:
            current = max(POWER_MIN, min(top, round(float(point.get('power_kw') or POWER_MIN))))
        except (TypeError, ValueError):
            current = POWER_MIN
        value = design.txt(str(current), 36, 'bold')
        slider_ref = {'value': current, 'saved': current}
        controls.append(_power_card(app, point, kind, index, current, top, value, slider_ref))
    return design.page(heading(app, 'Potência por conector'), ft.Container(height=3), *controls, gap=14, gutter=5)


def _power_card(app, point, kind, index, current, top, value, state):
    async def changed(event):
        state['value'] = round(event.control.value)
        value.value = str(state['value'])
        app.page.update()

    async def save_power():
        new = round(slider.value)
        slider.value = new
        value.value = str(new)
        app.page.update()
        if new == state['saved']:
            return
        await app.api.request('PATCH', f"connectors/{point['id']}", {'power_kw': new})
        state['saved'] = new
        app.notice(f'Potência de {kind} atualizada para {new} kW.')

    async def done(event=None):
        try:
            await save_power()
        except ApiError as exc:
            app.notice(str(exc))

    slider = ft.Slider(value=current, min=POWER_MIN, max=top, active_color=theme.BTN_PRIMARY,
                       inactive_color=theme.SEGMENT_OFF, thumb_color=theme.BTN_PRIMARY, data='power',
                       on_change=changed, on_change_end=done, padding=0)
    unit = design.txt('kW', 14, 'semibold', theme.GRAY_TEXT)
    card = design.card_box(ft.Column([
        design.txt('Potência máxima permitida', 12, 'regular', theme.GRAY_TEXT),
        ft.Row([value, ft.Container(unit, margin=ft.Margin(left=0, top=10, right=0, bottom=0))], spacing=6,
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
        slider], spacing=3), padding=ft.Padding(left=16, right=16, top=17, bottom=17))
    return ft.Container(ft.Column([design.txt(f'{kind} - Conector {index:02d}', 14.6, 'bold'), card], spacing=14),
                        margin=ft.Margin(left=0, top=0, right=0, bottom=24))


def _battery_page(app, station):
    sid = station['id']
    rule = station_settings.battery_rule(app, sid)
    state = {'limit': rule['limit'], 'active': rule['active']}
    readout = design.txt(f"{state['limit']}%", 46, 'bold')
    holder = ft.Container()

    async def changed(event):
        state['limit'] = round(event.control.value)
        readout.value = f"{state['limit']}%"
        app.page.update()

    async def choose(value):
        state['active'] = value == 'on'
        draw()
        app.page.update()

    def draw():
        holder.content = design.segmented([('on', 'Ativa'), ('off', 'Inativa')],
                                          'on' if state['active'] else 'off', choose, height=37.5)
    draw()

    async def save():
        station_settings.save_battery_rule(app, sid, state['limit'], state['active'])
        app.notice('Regra de limite de bateria salva.')

    slider = ft.Slider(value=state['limit'], min=0, max=100, active_color=theme.BTN_PRIMARY,
                       inactive_color=theme.SEGMENT_OFF, thumb_color=theme.BTN_PRIMARY, data='battery',
                       on_change=changed, padding=0)
    limit_card = design.card_box(ft.Column([
        design.txt('Limite desejado', 11.5, 'regular', theme.GRAY_TEXT),
        ft.Container(readout, margin=ft.Margin(left=0, top=-2, right=0, bottom=0)),
        ft.Container(slider, margin=ft.Margin(left=0, top=6.5, right=0, bottom=0)),
        ft.Row([design.txt('0%', 11.5, 'regular', theme.GRAY_TEXT), design.txt('100%', 11.5, 'regular', theme.GRAY_TEXT)],
               alignment=ft.MainAxisAlignment.SPACE_BETWEEN)], spacing=10),
        padding=ft.Padding(left=16, right=16, top=20, bottom=18.5))
    action_card = design.card_box(ft.Column([
        ft.Row([ft.Stack([ft.Icon(ft.Icons.NOTIFICATIONS_NONE, size=22, color=theme.TEXT_COLOR),
                          ft.Container(width=6, height=6, bgcolor=theme.RED, border_radius=3, right=1, top=1)],
                         width=22, height=22),
                design.txt('Enviar notificação', 12.5, 'bold')], spacing=9),
        ft.Container(design.txt('A recarga segue a configuração de segurança do equipamento e do veículo.', 10.5,
                                'regular', theme.GRAY_TEXT), width=250)], spacing=22),
        padding=ft.Padding(left=15, right=15, top=22, bottom=18))
    return design.page(
        heading(app, 'Limite de bateria'),
        ft.Container(ft.Column([design.txt('Configure a meta de carga', 12.5, 'regular', theme.GRAY_TEXT),
                                design.txt('usada nos alertas.', 12.5, 'regular', theme.GRAY_TEXT)], spacing=2),
                     margin=ft.Margin(left=0, top=-6, right=0, bottom=22)),
        limit_card,
        ft.Container(design.section_label('Ao atingir o limite'), margin=ft.Margin(left=0, top=0, right=0, bottom=-2)),
        action_card,
        gap=16, gutter=5,
        footer=[design.labeled('Status', holder, gap=4, strong=False),
                ft.Container(design.primary_button('Salvar regra', app.action(save), height=46, weight='bold', size=13),
                             margin=ft.Margin(left=0, top=4, right=0, bottom=5))])
