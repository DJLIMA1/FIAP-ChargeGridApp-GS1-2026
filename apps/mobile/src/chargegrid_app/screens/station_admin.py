"""Estação do vendedor: detalhe e subpáginas (dados, limites de potência).

Rota ``station_admin`` (``station_id``, ``page`` = None | 'data' | 'power').
Nome, endereço e status usam ``PATCH stations``. A página de potência edita o teto do posto
(``PATCH stations``: ``max_power_kw``, ``power_limit_notify``) e o limite de cada conector
(``PATCH connectors``: ``power_limit_kw``). ``power_kw`` é a potência nominal do carregador e nunca é
alterada aqui. A divisão do teto entre os conectores usa ``chargegrid_core.power`` (a mesma regra da API),
recalculada ao vivo enquanto os controles se movem.
"""


from decimal import Decimal

import flet as ft

from chargegrid_core import power as power_rules
from chargegrid_core.formatting import kwh

from ..api_client import ApiError
from ..ui import design, theme

NEXT_START_NOTE = ('Recargas em andamento mantêm a potência com que começaram; '
                   'os novos limites valem a partir da próxima recarga.')
SHARE_NOTE = ('Se a soma dos conectores passar do limite do posto, a potência é dividida '
              'proporcionalmente (mínimo de 1,4 kW por conector).')


def _street(address):
    from .stations import _street as street
    return street(address)


def station_code(stations, station_id):
    """Identificador exibido (``CG-001``): posição da estação na lista do vendedor."""
    for index, item in enumerate(stations or [], 1):
        if item.get('id') == station_id:
            return f'CG-{index:03d}'
    return 'CG-001'


def _live_points(station):
    return [point for point in station.get('connectors') or [] if not point.get('retired')]


def power_summary(station, points=None):
    """Subtítulo do menu: ``Limite do posto: 80 kW · CCS2: 60 kW · Tipo 2: 22 kW``."""
    points = _live_points(station) if points is None else points
    parts = list(dict.fromkeys(
        f"{point.get('connector_type')}: "
        f"{power_rules.kw_text(power_rules.requested_kw(point.get('power_kw'), point.get('power_limit_kw')))} kW"
        for point in points))
    if not parts:
        return 'Nenhum conector vinculado'
    cap = power_rules.to_kw(station.get('max_power_kw'))
    if cap is not None:
        parts.insert(0, f'Limite do posto: {power_rules.kw_text(cap)} kW')
    return ' · '.join(parts)


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
    return _main_page(app, station, code)


def _main_page(app, station, code):
    sid = station['id']
    points = _live_points(station)
    power_line = power_summary(station, points)
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
        menu_row('Potência por conector', 'Limite do posto e de cada conector', ft.Icons.BOLT_OUTLINED,
                 app.link('station_admin', station_id=sid, page='power')),
        ft.Container(height=8),
        menu_row('Pontos e equipamentos', 'Vincular por QR, editar e restaurar', ft.Icons.QR_CODE_SCANNER,
                 app.link('operator', station_id=sid, nav=False)),
        gap=16, gutter=3)


def _participates(point):
    return point.get('active') is not False and not point.get('retired')


def _kw(value):
    return power_rules.to_kw(value)


def _effective_note(allocated, rating):
    if allocated['limited_by'] == power_rules.LIMITED_BY_STATION:
        return 'limitado pelo posto'
    if allocated['limited_by'] == power_rules.LIMITED_BY_PORT:
        return 'limite do conector'
    return 'potência máxima' if allocated['effective_kw'] >= rating else ''


def _value_row(value, size=36):
    unit = design.txt('kW', 14, 'semibold', theme.GRAY_TEXT)
    return ft.Row([value, ft.Container(unit, margin=ft.Margin(left=0, top=size * 0.28, right=0, bottom=0))],
                  spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)


def _slider(value, low, high, on_change, data):
    return ft.Slider(value=float(value), min=float(low), max=float(max(high, low + 1)),
                     active_color=theme.BTN_PRIMARY, inactive_color=theme.SEGMENT_OFF, thumb_color=theme.BTN_PRIMARY,
                     data=data, on_change=on_change, padding=0)


def _snap(value, low, high):
    """Valor do controle em kW inteiros (o piso de 1,4 kW fica exato)."""
    number = power_rules.to_kw(round(float(value))) or low
    return max(low, min(high, number))


def _power_page(app, station):
    """Limite do posto + limite de cada conector, com a divisão recalculada ao vivo."""
    sid = station['id']
    points = _live_points(station)
    participants = [point for point in points if _participates(point)]
    total_rating = sum((_kw(point.get('power_kw')) or 0 for point in participants), Decimal(0))
    floor_total = sum((power_rules.floor_for(point.get('power_kw')) for point in participants), Decimal(0))
    saved = {'cap': _kw(station.get('max_power_kw')), 'notify': bool(station.get('power_limit_notify')),
             'limits': {point['id']: _kw(point.get('power_limit_kw')) for point in points}}
    state = {'cap': saved['cap'], 'notify': saved['notify'], 'limits': dict(saved['limits'])}
    views = {}

    def allocation():
        rows = [{**point, 'power_limit_kw': state['limits'].get(point['id'])} for point in points]
        return power_rules.allocate(rows, state['cap'])

    cap_value = design.txt('', 36, 'bold')
    cap_caption = design.txt('', 11, 'regular', theme.GRAY_TEXT)
    allocated_text = design.txt('', 11.5, 'semibold')
    bar = ft.ProgressBar(value=0, color=theme.BTN_PRIMARY, bgcolor=theme.SEGMENT_OFF, bar_height=8, border_radius=4)

    def refresh(update=True):
        result = allocation()
        cap = state['cap']
        if cap is None:
            cap_value.value = power_rules.kw_text(total_rating)
            cap_caption.value = 'Sem limite: cada conector usa o próprio limite.'
        else:
            cap_value.value = power_rules.kw_text(cap)
            cap_caption.value = ('Dividido entre os conectores ativos.' if result['shared']
                                 else 'Os conectores cabem no limite do posto.')
        top = cap if cap is not None else total_rating
        allocated_text.value = (f"Alocado: {power_rules.kw_text(result['allocated_kw'])} de "
                                f"{power_rules.kw_text(top)} kW")
        bar.value = float(min(1, result['allocated_kw'] / top)) if top else 0
        for point in points:
            view = views.get(point['id'])
            if not view:
                continue
            allocated = result['connectors'][point['id']]
            rating = _kw(point.get('power_kw')) or Decimal(0)
            limit = allocated['requested_kw']
            view['value'].value = power_rules.kw_text(limit)
            if not _participates(point):
                view['effective'].value = 'Conector inativo: fica fora da divisão do posto.'
                view['effective'].color = theme.GRAY_TEXT
                continue
            note = _effective_note(allocated, rating)
            view['effective'].value = (f"Efetivo: {power_rules.kw_text(allocated['effective_kw'])} kW"
                                       + (f' ({note})' if note else ''))
            view['effective'].color = theme.RED if allocated['limited_by'] == power_rules.LIMITED_BY_STATION \
                else theme.TEXT_COLOR
        if update:
            app.page.update()

    async def cap_changed(event):
        value = _snap(event.control.value, floor_total or power_rules.FLOOR_KW, total_rating)
        state['cap'] = None if value >= total_rating else value
        refresh()

    async def notify_changed(event):
        state['notify'] = bool(event.control.value)

    def port_changed(point):
        rating = _kw(point.get('power_kw')) or Decimal(0)
        low = power_rules.floor_for(rating)

        async def handler(event):
            value = _snap(event.control.value, low, rating)
            state['limits'][point['id']] = None if value >= rating else value
            refresh()
        return handler

    cap_slider = _slider(state['cap'] if state['cap'] is not None else total_rating,
                         floor_total or power_rules.FLOOR_KW, total_rating, cap_changed, 'station_power')
    notify = ft.Switch(value=state['notify'], on_change=notify_changed, data='power_notify',
                       active_color=theme.RED)
    station_card = design.card_box(ft.Column([
        design.txt('Potência total do posto', 12, 'regular', theme.GRAY_TEXT),
        _value_row(cap_value),
        cap_slider,
        ft.Container(height=4),
        ft.Row([allocated_text], alignment=ft.MainAxisAlignment.START),
        bar,
        cap_caption,
        design.txt(SHARE_NOTE, 10.5, 'regular', theme.GRAY_TEXT),
        ft.Container(height=2),
        ft.Row([design.txt('Notificar quando o limite estiver em uso', 12.5, 'semibold', expand=True), notify],
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
    ], spacing=6), padding=ft.Padding(left=16, right=16, top=17, bottom=12))
    controls = [ft.Container(ft.Column([design.txt('Limite do posto', 14.6, 'bold'), station_card], spacing=14),
                             margin=ft.Margin(left=0, top=0, right=0, bottom=12))]
    if not points:
        controls.append(design.txt('Nenhum conector vinculado a esta estação.', 12, 'regular', theme.GRAY_TEXT))
    for index, point in enumerate(points, 1):
        controls.append(_port_card(point, index, state, views, port_changed(point)))
    controls.append(design.txt(NEXT_START_NOTE, 10.5, 'regular', theme.GRAY_TEXT))
    refresh(update=False)

    async def save():
        failures, done = [], []
        body = {}
        if state['cap'] != saved['cap']:
            body['max_power_kw'] = None if state['cap'] is None else float(state['cap'])
        if state['notify'] != saved['notify']:
            body['power_limit_notify'] = state['notify']
        changed = [point for point in points if state['limits'].get(point['id']) != saved['limits'].get(point['id'])]
        if not body and not changed:
            app.notice('Nenhuma alteração para salvar.')
            return
        if body:
            try:
                await app.api.request('PATCH', f'stations/{sid}', body)
                saved['cap'], saved['notify'] = state['cap'], state['notify']
                done.append('limite do posto')
            except ApiError as exc:
                failures.append(f'Limite do posto: {exc}')
        for index, point in enumerate(points, 1):
            if point not in changed:
                continue
            limit = state['limits'].get(point['id'])
            name = f"{point.get('connector_type') or 'Conector'} - Conector {index:02d}"
            try:
                await app.api.request('PATCH', f"connectors/{point['id']}",
                                      {'power_limit_kw': None if limit is None else float(limit)})
                saved['limits'][point['id']] = limit
                done.append(name)
            except ApiError as exc:
                failures.append(f'{name}: {exc}')
        if failures:
            prefix = f"Salvo: {', '.join(done)}. " if done else ''
            app.notice(prefix + 'Não salvo: ' + ' | '.join(failures))
        else:
            if hasattr(app, 'mark_saved'):
                app.mark_saved()
            app.notice('Limites de potência salvos.')

    async def restore():
        state['cap'] = None
        state['limits'] = {key: None for key in state['limits']}
        cap_slider.value = float(total_rating)
        for point in points:
            view = views.get(point['id'])
            if view:
                view['slider'].value = float(_kw(point.get('power_kw')) or 0)
        refresh()
        app.notice('Padrão restaurado: sem limites. Toque em Salvar limites para aplicar.')

    footer = [ft.Row([
        design.secondary_button('Restaurar padrão', app.action(restore), height=50, expand=True),
        design.primary_button('Salvar limites', app.action(save), height=50, expand=True),
    ], spacing=12)]
    return design.page(heading(app, 'Potência por conector'), ft.Container(height=3), *controls, gap=14, gutter=5,
                       footer=footer)


def _port_card(point, index, state, views, on_change):
    kind = point.get('connector_type') or 'Conector'
    rating = _kw(point.get('power_kw')) or Decimal(0)
    current = state['limits'].get(point['id']) or rating
    value = design.txt(power_rules.kw_text(current), 36, 'bold')
    effective = design.txt('', 12, 'semibold')
    slider = _slider(current, power_rules.floor_for(rating), rating, on_change, 'power')
    views[point['id']] = {'value': value, 'effective': effective, 'slider': slider}
    energy = point.get('energy_kwh_total')
    lines = [design.txt(f'Potência máxima do carregador: {power_rules.kw_text(rating)} kW', 11.5, 'regular',
                        theme.GRAY_TEXT)]
    if energy is not None:
        lines.append(design.txt(f'Energia entregue: {kwh(energy, 1)}', 11.5, 'regular', theme.GRAY_TEXT))
    card = design.card_box(ft.Column([
        *lines,
        ft.Container(height=6),
        design.txt('Limite do conector', 12, 'regular', theme.GRAY_TEXT),
        _value_row(value),
        slider,
        effective], spacing=3), padding=ft.Padding(left=16, right=16, top=17, bottom=17))
    return ft.Container(ft.Column([design.txt(f'{kind} - Conector {index:02d}', 14.6, 'bold'), card], spacing=14),
                        margin=ft.Margin(left=0, top=0, right=0, bottom=12))
