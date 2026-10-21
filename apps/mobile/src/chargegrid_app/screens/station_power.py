"""Potência do posto (vendedor): limite contratado, rebalanceamento, loja SIMULADA e cada conector.

Rota ``station_admin`` com ``page='power'`` e ``section`` (None | 'site' | 'cap' | 'connector', este com
``connector_id``). Mesmo padrão da Tarifa: um cartão com o que vale agora e linhas de ajuste que abrem
subtelas simples (descrição, campos e Salvar no rodapé).

* Cartão (``GET stations/{id}/power``, a cada 3 s): disponível para os carregadores, limite contratado
  (o do dono ou o padrão do tipo/porte), consumo da loja agora (SIMULADO) e potência dos carros.
* Rebalanceamento: Ligado/Desligado (``PUT power-site``), ligado por padrão; muda só com a resposta.
* Por conector: potência configurada e efetiva; a subtela edita ``power_limit_kw`` (``PATCH connectors``).
* Ajustes: Limite contratado (valor, tipo e porte do estabelecimento; ``PUT power-site``) e Teto dos
  carregadores (``max_power_kw`` e aviso; ``PATCH stations``).

API sem a rota de potência (404): sem cartão nem rebalanceamento; conectores e teto continuam.
"""

from decimal import Decimal

import flet as ft

from chargegrid_core import power as power_rules
from chargegrid_core import site_load

from ..api_client import ApiError
from ..services import site_power as sp
from ..ui import design, theme
from ..ui.states import status_chip
from .station_admin import heading
from .tariffs import _row, _save_button, entry_row

CONNECTOR_ICON = '/design/icon_station_charge.svg'
SITE_HELP = 'Potência máxima da instalação, loja incluída. Vazio usa o padrão do tipo de estabelecimento.'
CAP_HELP = ('Soma máxima dos conectores deste posto. Acima dela a potência é dividida '
            '(mínimo de 1,4 kW por conector).')
CONNECTOR_HELP = 'Potência máxima que este conector entrega. O rebalanceamento pode reduzi-la enquanto houver outros carros.'
FIXED_NOTE = 'Rebalanceamento desligado: recargas em andamento mantêm a potência com que começaram.'


def _link(app, sid, **data):
    return app.link('station_admin', station_id=sid, page='power', **data)


def _demo(app):
    return getattr(app.api, 'is_demo', False) is True


async def _view(app, sid):
    try:
        return await app.api.request('GET', f'stations/{sid}/power')
    except ApiError as exc:
        if exc.status == 404:
            return None  # API sem o rebalanceamento ao vivo
        raise


async def build(app, station, section=None, connector_id=None):
    sid = station['id']
    view = await _view(app, sid) if sp.has_rebalance(station) else None
    if section == 'site' and view is not None:
        return site_page(app, station, view)
    if section == 'cap':
        return cap_page(app, station)
    if section == 'connector':
        for index, point in enumerate(sp.points(station), 1):
            if point.get('id') == connector_id:
                return connector_page(app, station, point, index, view)
    return overview(app, station, view)


# ---------------------------------------------------------------- visão geral
def summary_card(view):
    """Cartão "Disponível para os carregadores" (mesmo visual do "Tarifa atual")."""
    info = sp.summary(view)
    load_label = ft.Row([design.txt('Loja agora', 12.5, 'regular', theme.GRAY_TEXT),
                         status_chip(site_load.LABEL, 'AMBER')], spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER)
    load = ft.Row([ft.Column([load_label, design.txt(info['load_detail'], 10.5, 'regular', theme.GRAY_TEXT)],
                             spacing=1, expand=True),
                   design.txt(info['load'], 12.5, 'bold')], vertical_alignment=ft.CrossAxisAlignment.CENTER,
                  data='store-load')
    body = [design.txt('Disponível para os carregadores', 13.5, 'bold'),
            design.txt(info['available'], 30, 'semibold', data='available'),
            _row('Limite contratado', info['limit'], info['limit_detail']),
            load,
            _row('Carros agora', info['cars'], info['cars_detail'])]
    if info['over']:
        body.append(design.txt(info['over'], 11, 'semibold', theme.ERROR))
    return design.card_box(ft.Column(body, spacing=8), padding=ft.Padding(left=15, right=15, top=14, bottom=15),
                           radius=18, data='power-card')


def _demo_traffic(app, sid):
    async def simulate():
        await app.api.request('POST', f'stations/{sid}/demo-traffic', {})
        app.notice('Movimento simulado no posto: carros fictícios carregando e na vaga.')
        await app.go('station_admin', station_id=sid, page='power')
    return ft.Column([
        design.secondary_button('Simular carros no posto (demo)', app.action(simulate), height=46),
        design.txt('Só na demonstração: carros fictícios carregando para ver a divisão da potência.', 10.5,
                   'regular', theme.GRAY_TEXT)], spacing=6, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)


def overview(app, station, view):
    sid = station['id']
    state = {'view': view, 'busy': False}
    card = ft.Container()
    rebalance = ft.Container(data='rebalance')
    rows = {}

    async def set_rebalance(key):
        enabled = key == 'on'
        if state['busy'] or enabled == bool(state['view'].get('rebalance_enabled')):
            return
        state['busy'] = True
        try:
            fresh = await app.api.request('PUT', f'stations/{sid}/power-site', {'rebalance_enabled': enabled})
        except ApiError as exc:
            app.notice(f'Rebalanceamento não alterado: {exc}')  # sem atualização otimista
        else:
            state['view'] = fresh
            station['rebalance_enabled'] = bool(fresh.get('rebalance_enabled'))
            app.notice('Rebalanceamento ligado' if station['rebalance_enabled'] else 'Rebalanceamento desligado')
        finally:
            state['busy'] = False
            draw()
            app.page.update()

    def draw():
        current = state['view']
        if current is not None:
            card.content = summary_card(current)
            rebalance.content = design.segmented([('on', 'Ligado'), ('off', 'Desligado')],
                                                 'on' if current.get('rebalance_enabled') else 'off',
                                                 set_rebalance, height=37.5)
        for point_id, subtitle in rows.items():
            point = next(item for item in sp.points(station) if item.get('id') == point_id)
            subtitle.value = sp.connector_line(point, station, current)

    connectors = []
    for index, point in enumerate(sp.points(station), 1):
        row = entry_row(sp.point_name(point, index), '', CONNECTOR_ICON,
                        _link(app, sid, section='connector', connector_id=point['id']),
                        f"power-connector:{point['id']}")
        rows[point['id']] = row.content.controls[1].controls[1]
        connectors.append(row)
    draw()

    async def update():
        if state['busy']:
            return
        state['view'] = await app.api.request('GET', f'stations/{sid}/power')
        draw()
        app.page.update()

    controls = []
    if view is not None:
        app.set_poll(update, sp.POLL_SECONDS)
        controls += [card, ft.Column([design.labeled('Rebalanceamento', rebalance, gap=5, strong=False),
                                      design.txt(sp.REBALANCE_HELP, 11, 'regular', theme.GRAY_TEXT)], spacing=6,
                                     horizontal_alignment=ft.CrossAxisAlignment.STRETCH)]
    controls.append(design.section_label('Por conector'))
    controls += connectors or [design.txt('Nenhum conector vinculado a esta estação.', 12, 'regular',
                                          theme.GRAY_TEXT)]
    controls.append(design.section_label('Ajustes'))
    if view is not None:
        controls.append(entry_row('Limite contratado', sp.site_subtitle(view), ft.Icons.ELECTRICAL_SERVICES,
                                  _link(app, sid, section='site'), 'power-site'))
    controls.append(entry_row('Teto dos carregadores', sp.cap_subtitle(station), ft.Icons.SPEED,
                              _link(app, sid, section='cap'), 'power-cap'))
    if _demo(app) and view is not None:
        controls.append(_demo_traffic(app, sid))
    return design.page(heading(app, 'Potência', app.link('station_admin', station_id=sid)), *controls, gap=16)


# ---------------------------------------------------------------- subtelas
def _sub_page(app, sid, title, description, controls, footer):
    return design.page(heading(app, title, _link(app, sid)),
                       ft.Container(design.txt(description, 13, 'regular', theme.GRAY_TEXT),
                                    margin=ft.Margin(left=0, top=-6, right=0, bottom=4)),
                       *controls, footer=footer, gap=16, gutter=4)


def _rounded(field):
    return ft.Container(field, border_radius=14, bgcolor=theme.INPUT_BG, clip_behavior=ft.ClipBehavior.ANTI_ALIAS)


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


def site_page(app, station, view):
    """Limite contratado (vazio = padrão) e tipo/porte do estabelecimento (curva SIMULADA da loja)."""
    sid = station['id']
    state = {'profile': view.get('building_profile') or site_load.DEFAULT_PROFILE,
             'size': view.get('building_size') or site_load.DEFAULT_SIZE}
    field = design.number_field(sp.limit_input(view.get('site_limit_configured_kw')), suffix='kW')
    field.data = 'site_limit'
    kinds, sizes = ft.Container(), ft.Container()
    hint = design.txt('', 11, 'regular', theme.GRAY_TEXT, data='site-default')
    message = design.txt('', 12, 'regular', theme.ERROR, visible=False)

    def draw():
        default = site_load.default_site_limit_kw(state['profile'], state['size'])
        field.hint_text = f'{sp.limit_input(default)} (padrão)'
        hint.value = (f"Padrão: {sp.kw(default)} · pico típico da loja "
                      f"{sp.kw(site_load.peak_kw(state['profile'], state['size']))} ({site_load.LABEL})")
        chips = [ft.Container(design.chip_option(item.label, selected=key == state['profile'],
                                                 on_click=choose('profile', key)), expand=True)
                 for key, item in site_load.PROFILES.items()]
        kinds.content = ft.Column([ft.Row(chips[index:index + 2], spacing=8) for index in range(0, len(chips), 2)],
                                  spacing=8)  # duas colunas, como os atalhos de valor
        sizes.content = design.segmented([(key, label) for key, (label, _) in site_load.SIZES.items()],
                                         state['size'], pick_size, height=37.5)

    def choose(name, key):
        async def handler(event=None):
            state[name] = key
            draw()
            app.page.update()
        return handler

    async def pick_size(key):
        await choose('size', key)()
    draw()

    async def save(event=None):
        value, error = sp.parse_site_limit(field.value)
        if error:
            message.value, message.visible = error, True
            app.page.update()
            return
        body = {'site_limit_kw': value, 'building_profile': state['profile'], 'building_size': state['size']}
        try:
            await app.api.request('PUT', f'stations/{sid}/power-site', body)
        except ApiError as exc:
            message.value, message.visible = str(exc), True
            app.page.update()
            return
        app.notice('Limite contratado salvo.')
        await app.go('station_admin', station_id=sid, page='power')

    return _sub_page(app, sid, 'Limite contratado', SITE_HELP, [
        design.labeled('Limite contratado', _rounded(field), gap=9),
        design.labeled('Tipo de estabelecimento', kinds, gap=9),
        design.labeled('Porte', sizes, gap=9),
        hint,
    ], [message, _save_button('Salvar limite', app.action(save))])


def cap_page(app, station):
    """Teto dos carregadores do posto (``max_power_kw``) e aviso quando ele limita uma recarga."""
    sid = station['id']
    participants = [point for point in sp.points(station) if point.get('active') is not False]
    total = sum((power_rules.to_kw(point.get('power_kw')) or Decimal(0) for point in participants), Decimal(0))
    low = sum((power_rules.floor_for(point.get('power_kw')) for point in participants), Decimal(0)) \
        or power_rules.FLOOR_KW
    state = {'cap': power_rules.to_kw(station.get('max_power_kw')), 'notify': bool(station.get('power_limit_notify'))}
    value = design.txt('', 36, 'bold')
    caption = design.txt('', 11, 'regular', theme.GRAY_TEXT)
    notify = ft.Container()

    def draw():
        cap = state['cap']
        value.value = power_rules.kw_text(cap if cap is not None else total)
        caption.value = ('Sem teto: cada conector usa a própria potência.' if cap is None else
                         'Dividido entre os conectores ativos.' if total > cap else 'Os conectores cabem no teto.')
        notify.content = design.segmented([(True, 'Ligado'), (False, 'Desligado')], state['notify'], set_notify,
                                          height=37.5)

    async def moved(event):
        number = _snap(event.control.value, low, total)
        state['cap'] = None if number >= total else number
        draw()
        app.page.update()

    def set_notify(flag):
        state['notify'] = flag
        draw()
        app.page.update()

    slider = _slider(state['cap'] if state['cap'] is not None else total, low, total, moved, 'station_power')
    draw()

    async def clear(event=None):
        state['cap'] = None
        slider.value = float(total)
        draw()
        app.page.update()

    async def save(event=None):
        body = {'max_power_kw': None if state['cap'] is None else float(state['cap']),
                'power_limit_notify': state['notify']}
        await app.api.request('PATCH', f'stations/{sid}', body)
        if hasattr(app, 'mark_saved'):
            app.mark_saved()
        app.notice('Teto dos carregadores salvo.')
        await app.go('station_admin', station_id=sid, page='power')

    card = design.card_box(ft.Column([design.txt('Teto do posto', 12, 'regular', theme.GRAY_TEXT), _value_row(value),
                                      slider, caption], spacing=6),
                           padding=ft.Padding(left=16, right=16, top=17, bottom=14), radius=18)
    return _sub_page(app, sid, 'Teto dos carregadores', CAP_HELP, [
        card, design.labeled('Avisar quando o teto limitar uma recarga', notify, gap=5, strong=False),
    ], [ft.Row([design.secondary_button('Sem teto', app.action(clear), height=50, expand=True),
                design.primary_button('Salvar teto', app.action(save), height=50, expand=True)], spacing=12)])


def connector_page(app, station, point, index, view):
    """Potência de um conector (``power_limit_kw``): configurada × efetiva agora."""
    sid = station['id']
    rating = power_rules.to_kw(point.get('power_kw')) or Decimal(0)
    low = power_rules.floor_for(rating)
    state = {'limit': power_rules.to_kw(point.get('power_limit_kw'))}
    value = design.txt('', 36, 'bold')

    def draw():
        value.value = power_rules.kw_text(state['limit'] if state['limit'] is not None else rating)

    async def moved(event):
        number = _snap(event.control.value, low, rating)
        state['limit'] = None if number >= rating else number
        draw()
        app.page.update()

    slider = _slider(state['limit'] if state['limit'] is not None else rating, low, rating, moved, 'power')
    draw()

    async def use_max(event=None):
        state['limit'] = None
        slider.value = float(rating)
        draw()
        app.page.update()

    async def save(event=None):
        await app.api.request('PATCH', f"connectors/{point['id']}",
                              {'power_limit_kw': None if state['limit'] is None else float(state['limit'])})
        if hasattr(app, 'mark_saved'):
            app.mark_saved()
        app.notice('Potência do conector salva.')
        await app.go('station_admin', station_id=sid, page='power')

    lines = [design.txt(f'Máximo do carregador: {sp.kw(rating)}', 11.5, 'regular', theme.GRAY_TEXT),
             _value_row(value), slider,
             design.txt(sp.connector_line(point, station, view), 12, 'semibold', data='connector-effective')]
    controls = [design.card_box(ft.Column(lines, spacing=6), padding=ft.Padding(left=16, right=16, top=17, bottom=14),
                                radius=18)]
    if station.get('rebalance_enabled') is False:
        controls.append(design.txt(FIXED_NOTE, 10.5, 'regular', theme.GRAY_TEXT))
    return _sub_page(app, sid, sp.point_name(point, index), CONNECTOR_HELP, controls,
                     [ft.Row([design.secondary_button('Usar o máximo', app.action(use_max), height=50, expand=True),
                              design.primary_button('Salvar potência', app.action(save), height=50, expand=True)],
                             spacing=12)])
