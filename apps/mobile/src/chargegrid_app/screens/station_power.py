"""Potência do posto (vendedor): Limites, rebalanceamento e cada carregador.

Rota ``station_admin`` com ``page='power'`` e ``section`` (None | 'limits' | 'connector', este com
``connector_id``; 'site' e 'cap' são apelidos antigos de 'limits'). Mesmo padrão da Tarifa: um cartão
com o que vale agora e linhas de ajuste que abrem subtelas simples (descrição, campos e Salvar no rodapé).

* Cartão (``GET stations/{id}/power``, a cada 3 s): disponível para os carregadores, uma régua só de
  leitura (margem da loja, carros agora, livre), limite contratado, margem ESTIMADA da loja e carros.
  Não há consumo da loja ao vivo nem simulado: sem medidor, o pico estimado fica reservado o tempo todo.
* Rebalanceamento: Ligado/Desligado (``PUT power-site``), ligado por padrão; muda só com a resposta.
* Por carregador: potência configurada e efetiva; a subtela edita ``power_limit_kw`` (``PATCH connectors``).
* Limites (um só lugar, um só ``PUT power-site``): régua 0→escala com três faixas de arrastar alinhadas
  a ela (loja: mínimo e pico; limite contratado; máximo dos carregadores, embaixo da parte verde),
  "Digitar valores" para números exatos e o aviso quando os limites reduzirem uma recarga.

API sem a rota de potência (404): sem cartão, rebalanceamento nem Limites; conectores e teto continuam.
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
from .tariffs import (  # noqa: F401  (_save_button: compatibilidade)
    _row,
    _save_button,
    entry_row,
)

CONNECTOR_ICON = '/design/icon_station_charge.svg'
LIMITS_HELP = 'Quanto o posto pode puxar da rede e quanto fica guardado para a loja.'
CAP_HELP = ('Soma máxima dos carregadores deste posto. Acima dela a potência é dividida '
            '(mínimo de 1,4 kW por carregador).')
CONNECTOR_HELP = 'Potência máxima que este carregador entrega. O rebalanceamento pode reduzi-la enquanto houver outros carros.'
FIXED_NOTE = 'Rebalanceamento desligado: recargas em andamento mantêm a potência com que começaram.'
LIMIT_HELP = 'Demanda da instalação inteira, loja incluída (a da conta de luz).'
CAP_LANE_HELP = 'Soma máxima dos carregadores. No fim da faixa: sem teto próprio.'
FIXED_LIMITS_NOTE = ('Rebalanceamento desligado: os limites valem no início de cada recarga, '
                     'divididos entre os carregadores ativos.')
BAR_HEIGHT = 22
MARKER_HEIGHT = 32
TRACK_INSET = 24  # recuo do trilho do RangeSlider do Flutter: régua e faixas usam o mesmo, alinhadas


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
    if section in ('limits', 'site', 'cap') and view is not None:
        return limits_page(app, station, view)
    if section == 'cap':
        return cap_page(app, station)
    if section == 'connector':
        for index, point in enumerate(sp.points(station), 1):
            if point.get('id') == connector_id:
                return connector_page(app, station, point, index, view)
    return overview(app, station, view)


# ---------------------------------------------------------------- régua
def _colors():
    return {'store_base': theme.AMBER, 'store_peak': None, 'cars': theme.GREEN,
            'chargers': theme.GREEN, 'unused': ft.Colors.with_opacity(0.2, theme.GREEN),
            'above': theme.SEGMENT_OFF}


def _stripes():
    """Âmbar listrado: a parte da loja entre o mínimo e o pico é estimativa."""
    light = '#F2C27D'
    return ft.LinearGradient(begin=ft.Alignment(-1, -1), end=ft.Alignment(-0.6, 0.2), tile_mode=ft.GradientTileMode.REPEATED,
                             colors=[theme.AMBER, theme.AMBER, light, light], stops=[0, 0.5, 0.5, 1])


def _segment(key, value, live=False):
    color = _colors()[key]
    if live and key == 'chargers':
        color = ft.Colors.with_opacity(0.45, theme.GREEN)  # livre (os carros em uso ficam cheios)
    return ft.Container(expand=max(1, int(value * 10)), height=BAR_HEIGHT, bgcolor=color,
                        gradient=_stripes() if key == 'store_peak' else None, data=f'bar-{key}')


def bar(state, used=None):
    """Régua 0→escala: loja (âmbar, listrada = estimativa), carregadores (verde), marcador do
    contratado e trilho acima dele. Larguras proporcionais (``expand``), sem medir pixels."""
    items = sp.segments(state, used)
    live = used is not None
    inside = [_segment(key, value, live) for key, value in items if key != 'above']
    above = [value for key, value in items if key == 'above']
    left = ft.Container(ft.Row(inside, spacing=0), expand=max(1, int(state['limit'] * 10)),
                        border_radius=ft.BorderRadius.only(top_left=7, bottom_left=7, top_right=0, bottom_right=0)
                        if above else 7, clip_behavior=ft.ClipBehavior.ANTI_ALIAS)
    parts = [left, ft.Container(width=3, height=MARKER_HEIGHT, bgcolor=theme.TEXT_COLOR, border_radius=2,
                                data='bar-contracted')]
    if above:
        parts.append(ft.Container(expand=max(1, int(above[0] * 10)), height=BAR_HEIGHT, bgcolor=theme.SEGMENT_OFF,
                                  border_radius=ft.BorderRadius.only(top_left=0, bottom_left=0, top_right=7,
                                                                     bottom_right=7), data='bar-above'))
    return ft.Row(parts, spacing=0, height=MARKER_HEIGHT, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                  data='limits-bar')


def _dot(color, striped=False):
    return ft.Container(width=10, height=10, border_radius=3, bgcolor=color, gradient=_stripes() if striped else None)


def legend(state, live=False):
    entries = [(_dot(theme.AMBER, True), 'Loja (estimativa)')]
    if live:
        entries += [(_dot(theme.GREEN), 'Em uso'), (_dot(ft.Colors.with_opacity(0.45, theme.GREEN)), 'Livre')]
    else:
        entries.append((_dot(theme.GREEN), 'Carregadores'))
    entries.append((ft.Container(width=3, height=12, bgcolor=theme.TEXT_COLOR, border_radius=2),
                    f"Contratado {sp.kw(state['limit'])}"))
    return ft.Row([ft.Row([mark, design.txt(text, 10.5, 'regular', theme.GRAY_TEXT)], spacing=5, tight=True)
                   for mark, text in entries], spacing=12, wrap=True, run_spacing=4)


def axis(state):
    return ft.Row([design.txt('0', 10, 'regular', theme.GRAY_TEXT), ft.Container(expand=True),
                   design.txt(sp.kw(state['scale']), 10, 'regular', theme.GRAY_TEXT)], spacing=0)


# ---------------------------------------------------------------- visão geral
def summary_card(view):
    """Cartão "Disponível para os carregadores" (mesmo visual do "Tarifa atual") com a régua só de leitura."""
    info = sp.summary(view)
    state = sp.limits_state(view)
    used = sp.number(view.get('envelope_kw'))
    if used is None:
        used = sp.number(view.get('allocated_kw'))
    store_label = ft.Row([design.txt('Margem da loja', 12.5, 'regular', theme.GRAY_TEXT),
                          status_chip(site_load.LABEL, 'SLATE')], spacing=8,
                         vertical_alignment=ft.CrossAxisAlignment.CENTER)
    store = ft.Row([ft.Column([store_label, design.txt(info['store_detail'], 10.5, 'regular', theme.GRAY_TEXT)],
                              spacing=1, expand=True),
                    design.txt(info['store'], 12.5, 'bold')], vertical_alignment=ft.CrossAxisAlignment.CENTER,
                   data='store-margin')
    limit = info['limit'] + (' (padrão)' if view.get('site_limit_default') else '')
    body = [design.txt('Disponível para os carregadores', 13.5, 'bold'),
            design.txt(info['available'], 30, 'semibold', data='available'),
            ft.Column([bar(state, used or 0), legend(state, live=True)], spacing=6),
            _row('Limite contratado', limit, info['limit_detail']),
            store,
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
    controls.append(design.section_label('Por carregador'))
    controls += connectors or [design.txt('Nenhum carregador vinculado a esta estação.', 12, 'regular',
                                          theme.GRAY_TEXT)]
    controls.append(design.section_label('Ajustes'))
    if view is not None:
        controls.append(entry_row('Limites', sp.limits_subtitle(view), ft.Icons.TUNE,
                                  _link(app, sid, section='limits'), 'power-limits'))
    else:
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


def _inset(control):
    """Mesmo recuo do trilho do RangeSlider (que não aceita ``padding``): régua e faixas alinhadas."""
    return ft.Container(control, padding=ft.Padding(left=TRACK_INSET, right=TRACK_INSET, top=0, bottom=0))


def _lane_head(color, title, value, chip=None, striped=False):
    left = [_dot(color, striped), design.txt(title, 12.5, 'semibold')]
    if chip:
        left.append(status_chip(chip, 'SLATE'))
    return ft.Row([ft.Row(left, spacing=7, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                   ft.Container(expand=True), value], vertical_alignment=ft.CrossAxisAlignment.CENTER)


def limits_page(app, station, view):
    """Limites: régua + faixas de arrastar (loja, contratado, máximo dos carregadores), um só ``PUT power-site``."""
    sid = station['id']
    original = sp.limits_state(view, station)
    state = dict(original)
    hero = design.txt('', 30, 'semibold', data='limits-budget')
    equation = design.txt('', 11.5, 'regular', theme.GRAY_TEXT, data='limits-equation')
    ruler = ft.Container(data='limits-ruler')
    store_value = design.txt('', 12.5, 'bold', data='store-value')
    limit_value = design.txt('', 12.5, 'bold', data='limit-value')
    cap_value = design.txt('', 12.5, 'bold', data='cap-value')
    hint = design.txt('', 11, 'semibold', theme.AMBER, visible=False, data='limits-hint')
    message = design.txt('', 12, 'regular', theme.ERROR, visible=False)
    notify = ft.Container()
    cap_lane = ft.Container(data='cap-lane')

    store_range = ft.RangeSlider(start_value=float(state['min']), end_value=float(state['peak']), min=0,
                                 max=float(state['scale']), active_color=theme.AMBER,
                                 inactive_color=theme.SEGMENT_OFF, data='store-range')
    limit_slider = ft.Slider(value=float(state['limit']), min=0, max=float(state['scale']),
                             active_color=theme.BTN_PRIMARY, inactive_color=theme.SEGMENT_OFF,
                             thumb_color=theme.BTN_PRIMARY, padding=0, data='limit-slider')
    cap_slider = ft.Slider(value=0, min=0, max=1, active_color=theme.GREEN, inactive_color=theme.SEGMENT_OFF,
                           thumb_color=theme.GREEN, padding=0, data='cap-slider')

    def sync_controls():
        """Valores, escala e passos das faixas a partir do rascunho (abrir, digitar, restaurar)."""
        divisions = int(state['scale'] / state['step'])
        store_range.max = limit_slider.max = float(state['scale'])
        store_range.divisions = limit_slider.divisions = divisions
        store_range.start_value, store_range.end_value = float(state['min']), float(state['peak'])
        limit_slider.value = float(state['limit'])

    def draw():
        left = sp.remainder(state)
        hero.value = sp.kw(sp.budget(state))
        equation.value = sp.equation(state)
        ruler.content = ft.Column([_inset(bar(state)), _inset(axis(state)), legend(state)], spacing=5)
        store_value.value = sp.store_text(state)
        limit_value.value = sp.kw(state['limit']) + (' (padrão)' if state['limit_default'] else '')
        cap_value.value = sp.cap_text(state)
        cap_slider.max = float(max(left, Decimal('0.1')))
        cap_slider.value = float(min(sp.budget(state), left))
        cap_lane.content = ft.Row([
            ft.Container(expand=max(1, int(state['peak'] * 10)) if state['peak'] > 0 else None,
                         width=None if state['peak'] > 0 else 0),
            ft.Container(cap_slider, expand=max(1, int(left * 10))),
            ft.Container(expand=max(1, int((state['scale'] - state['limit']) * 10)))
            if state['scale'] > state['limit'] else ft.Container(width=0)], spacing=0)
        notify.content = design.segmented([(True, 'Ligado'), (False, 'Desligado')], state['notify'], set_notify,
                                          height=37.5)

    def show_hint(text):
        hint.value, hint.visible = text or '', bool(text)

    def refresh():
        draw()
        app.page.update()

    async def store_moved(event):
        text = sp.move_store(state, event.control.start_value, event.control.end_value)
        if text:
            store_range.start_value, store_range.end_value = float(state['min']), float(state['peak'])
        show_hint(text)
        refresh()

    async def limit_moved(event):
        text = sp.move_limit(state, event.control.value)
        if text:
            limit_slider.value = float(state['limit'])
        show_hint(text)
        refresh()

    async def cap_moved(event):
        show_hint(sp.move_cap(state, event.control.value))
        refresh()

    def set_notify(flag):
        state['notify'] = flag
        refresh()

    store_range.on_change = store_moved
    limit_slider.on_change = limit_moved
    cap_slider.on_change = cap_moved

    async def restore(event=None):
        sp.restore_defaults(state)
        sync_controls()
        show_hint(None)
        refresh()

    async def ask_values(event=None):
        fields = {
            'limit': design.number_field(sp.limit_input(state['limit']), suffix='kW'),
            'min': design.number_field(sp.limit_input(state['min']), suffix='kW'),
            'peak': design.number_field(sp.limit_input(state['peak']), suffix='kW'),
            'cap': design.number_field('' if state['cap'] is None else sp.limit_input(state['cap']), suffix='kW',
                                       hint='Vazio = sem teto próprio'),
        }
        for key, field in fields.items():
            field.data = f'type-{key}'
        error = design.txt('', 11.5, 'regular', theme.ERROR, visible=False)

        def apply(event=None):
            parsed = {}
            for key, field in fields.items():
                value, problem = sp.parse_kw(field.value, allow_zero=key == 'min' or key == 'peak')
                if problem or (value is None and key != 'cap'):
                    error.value, error.visible = problem or 'Preencha o contratado e a estimativa da loja.', True
                    app.page.update()
                    return
                parsed[key] = value
            problem = sp.set_values(state, parsed['limit'], parsed['min'], parsed['peak'], parsed['cap'])
            if problem:
                error.value, error.visible = problem, True
                app.page.update()
                return
            app.page.pop_dialog()
            sync_controls()
            show_hint(None)
            refresh()

        app.page.show_dialog(ft.AlertDialog(
            modal=True, title=ft.Text('Digitar valores'),
            content=ft.Column([design.labeled('Limite contratado', fields['limit'], gap=6),
                               design.labeled('Loja · mínimo estimado', fields['min'], gap=6),
                               design.labeled('Loja · pico estimado', fields['peak'], gap=6),
                               design.labeled('Máximo dos carregadores', fields['cap'], gap=6), error],
                              tight=True, spacing=10, scroll=ft.ScrollMode.AUTO),
            actions=[ft.TextButton('Cancelar', on_click=lambda event: app.page.pop_dialog()),
                     ft.TextButton('Aplicar', on_click=apply)]))

    async def save(event=None):
        changes = sp.body(state, original)
        if not changes:
            await app.go('station_admin', station_id=sid, page='power')
            return
        try:
            await app.api.request('PUT', f'stations/{sid}/power-site', changes)
        except ApiError as exc:
            message.value, message.visible = str(exc), True
            app.page.update()
            return
        if hasattr(app, 'mark_saved'):
            app.mark_saved()
        app.notice('Limites salvos.')
        await app.go('station_admin', station_id=sid, page='power')

    sync_controls()
    draw()
    lanes = ft.Column([
        _lane_head(theme.AMBER, 'Loja', store_value, site_load.LABEL, striped=True),
        store_range,
        design.txt(sp.ESTIMATE_HELP, 10.5, 'regular', theme.GRAY_TEXT, data='estimate-help'),
        ft.Container(height=6),
        _lane_head(theme.BTN_PRIMARY, 'Limite contratado', limit_value),
        _inset(limit_slider),
        design.txt(LIMIT_HELP, 10.5, 'regular', theme.GRAY_TEXT),
        ft.Container(height=6),
        _lane_head(theme.GREEN, 'Máximo dos carregadores', cap_value),
        _inset(cap_lane),
        design.txt(CAP_LANE_HELP, 10.5, 'regular', theme.GRAY_TEXT),
    ], spacing=4, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    card = design.card_box(ft.Column([
        design.txt('Para os carregadores', 13.5, 'bold'), hero, equation, ft.Container(height=4), ruler,
        ft.Divider(height=18, color=theme.BORDER_SOFT), lanes, hint,
    ], spacing=4, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
        padding=ft.Padding(left=16, right=16, top=15, bottom=14), radius=18, data='limits-card')
    controls = [card,
                ft.Row([ft.TextButton('Digitar valores', icon=ft.Icons.KEYBOARD, on_click=ask_values,
                                      data='type-values')], alignment=ft.MainAxisAlignment.END),
                design.labeled('Avisar quando os limites reduzirem uma recarga', notify, gap=5, strong=False)]
    if station.get('rebalance_enabled') is False:
        controls.append(design.txt(FIXED_LIMITS_NOTE, 10.5, 'regular', theme.GRAY_TEXT))
    return _sub_page(app, sid, 'Limites', LIMITS_HELP, controls,
                     [message, ft.Row([design.secondary_button('Restaurar padrão', app.action(restore), height=50,
                                                               expand=True),
                                       design.primary_button('Salvar limites', app.action(save), height=50,
                                                             expand=True)], spacing=12)])


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
        caption.value = ('Sem teto: cada carregador usa a própria potência.' if cap is None else
                         'Dividido entre os carregadores ativos.' if total > cap else 'Os carregadores cabem no teto.')
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
        app.notice('Potência do carregador salva.')
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
