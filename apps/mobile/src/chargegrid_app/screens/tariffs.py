"""Tarifas dinâmicas do vendedor: base da estação + regras de rotatividade, demanda e pico.

Tudo simulado no aparelho (``services.tariffs``); a tarifa base vem dos conectores reais.
Rota ``tariffs``: ``station_id`` e ``page`` (None | 'rotation' | 'demand' | 'peak').
"""

from decimal import Decimal

import flet as ft

from ..services import tariffs as svc
from ..ui import design, theme
from .station_admin import heading

PAGES = {
    'rotation': ('Tarifa de rotatividade', 'Cobre a ocupação prolongada da vaga\napós o tempo de tolerância.'),
    'demand': ('Tarifa por demanda', 'O preço aumenta quando múltiplas\nestações do vendedor estão em uso.'),
    'peak': ('Tarifa em horário de pico', 'Defina quando a energia tem\nmaior procura na sua região.'),
}
FIELD_GAP = 15
SPACER = {'rotation': 16, 'demand': 20, 'peak': 8}  # a referência varia o respiro por tela


async def _station(app, station_id):
    try:
        if station_id:
            return await app.api.request('GET', f'stations/{station_id}')
        result = await app.api.request('GET', 'operator/stations', params={'limit': 100})
        items = result.get('items', result) if isinstance(result, dict) else result
        return (items or [None])[0]
    except Exception:  # noqa: BLE001 - tela continua sem a tarifa base
        return None


def _store(app):
    return svc.TariffStore(demo=bool(getattr(app.api, 'is_demo', False)))


def _refresh(*controls):
    """update() só quando o controle já está na página (na montagem inicial não há o que atualizar)."""
    for control in controls:
        try:
            control.update()
        except RuntimeError:
            pass


def _per_kwh(value):
    return f'{svc.fmt_money(value)}/kWh'


def _example_card(title, *controls, spacing=12, padding=(14, 12)):
    return design.card_box(ft.Column([design.txt(title, 13, 'bold'), *controls], spacing=spacing),
                           padding=ft.Padding(left=15, right=15, top=padding[0], bottom=padding[1]), radius=18)


def _description(text):
    return design.txt(text, 13, 'regular', theme.GRAY_TEXT)


def _row(label, value, strong=False):
    return ft.Row([design.txt(label, 12.5, 'regular', theme.GRAY_TEXT), design.txt(value, 12.5, 'bold')],
                  alignment=ft.MainAxisAlignment.SPACE_BETWEEN)


async def build(app, station_id=None, page=None, **_):
    station = await _station(app, station_id)
    sid = (station or {}).get('id') or station_id
    base = svc.base_price((station or {}).get('connectors'))
    store = _store(app)
    rules = store.load(sid)

    if page == 'rotation':
        return rotation_page(app, sid, base, store, rules)
    if page == 'demand':
        return demand_page(app, sid, base, store, rules)
    if page == 'peak':
        return peak_page(app, sid, base, store, rules)
    return overview(app, sid, base, rules)


def overview(app, sid, base, rules):
    def open_page(key):
        return app.link('tariffs', station_id=sid, page=key) if sid else app.link('tariffs', page=key)

    active = any(rule['enabled'] for rule in rules.values())
    pill = design.txt('Ativa' if active else 'Inativa', 11, 'bold', '#FFFFFF')
    base_card = design.card_box(
        ft.Row([
            ft.Column([
                design.txt('Tarifa base', 13.5, 'regular', theme.GRAY_TEXT),
                ft.Row([design.txt(svc.fmt_money(base) if base is not None else '—', 26, 'semibold'),
                        ft.Container(design.txt('/ kWh', 11.5, 'regular', theme.GRAY_TEXT),
                                     margin=ft.Margin(left=7, top=12, right=0, bottom=0))],
                       spacing=0, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ], spacing=9, expand=True),
            ft.Container(pill, width=70, height=27, border_radius=6, alignment=ft.Alignment(0, 0),
                         bgcolor='#3B8B5A' if active else '#4A4A4A'),
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=ft.Padding(left=15, right=31, top=15, bottom=16), radius=18)
    def entry(title, key, icon):
        return ft.Container(
            ft.Row([design.icon_tile(icon, size=49, dark=True, icon_size=26), design.txt(title, 13, 'semibold', expand=True),
                    ft.Icon(ft.Icons.CHEVRON_RIGHT, size=22, color=theme.GRAY_TEXT)],
                   spacing=7, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            on_click=open_page(key), ink=False, margin=ft.Margin(left=0, top=0, right=-6, bottom=17))
    rows = [entry('Tarifa de rotatividade', 'rotation', ft.Icons.ACCESS_TIME),
            entry('Tarifa por demanda', 'demand', ft.Icons.TRENDING_UP),
            entry('Tarifa em horário de pico', 'peak', ft.Icons.WB_SUNNY_OUTLINED)]
    return design.page(heading(app, 'Tarifas dinâmicas'), ft.Container(base_card, margin=ft.Margin(left=0, top=10, right=0, bottom=17)),
                       *rows, gap=17)


def _back_to_list(app, sid):
    async def back(event=None):
        await app.go('tariffs', station_id=sid) if sid else await app.go('tariffs')
    return back


def _form_page(app, sid, key, fields, example, enabled, collect):
    """Esqueleto das 3 subtelas: descrição, campos, exemplo, Status + Salvar regra (rodapé fixo)."""
    title, description = PAGES[key]
    state = {'enabled': enabled}
    message = design.txt('', 12, 'regular', theme.RED, visible=False)
    status_slot = ft.Container()

    def draw_status():
        status_slot.content = design.segmented([(True, 'Ativa'), (False, 'Inativa')], state['enabled'], set_status,
                                               height=37.5)
        _refresh(status_slot)

    def set_status(value):
        state['enabled'] = value
        draw_status()
    draw_status()

    async def save(event=None):
        rule = collect(state['enabled'])
        if isinstance(rule, str):
            message.value, message.visible = rule, True
            _refresh(message)
            return
        if not sid or not _store(app).save_rule(sid, key, rule):
            message.value, message.visible = 'Não foi possível salvar a regra.', True
            _refresh(message)
            return
        app.notice('Regra salva.')
        await _back_to_list(app, sid)()

    footer = [ft.Column([design.label('Status', strong=False), status_slot], spacing=4), message,
              ft.Container(design.primary_button('Salvar regra', save, height=46, weight='bold'),
                           margin=ft.Margin(left=0, top=4, right=0, bottom={'rotation': 3, 'demand': 4, 'peak': 5}.get(key, 3)))]
    return design.page(heading(app, title, _back_to_list(app, sid)),
                       ft.Container(_description(description), margin=ft.Margin(left=0, top=-6, right=0, bottom=0)),
                       ft.Container(height=0, margin=ft.Margin(left=0, top=SPACER.get(key, 16), right=0, bottom=0)),
                       *fields, example, footer=footer, gap=FIELD_GAP, gutter=4)


def _field(label, value, example_update=None, **kw):
    box = design.labeled_input(label, value, **kw)
    box.controls[0] = design.txt(label, 11, 'bold')
    box.spacing = 14
    field = box.controls[1]
    if example_update:
        field.on_change = lambda e: example_update()
    return box, field


def rotation_page(app, sid, base, store, rules):
    rule = rules['rotation']
    after_box, after = _field('Começar a cobrar após', f"{rule['start_after_min']} minutos")
    every_box, every = _field('Repetir cobrança a cada', f"{rule['interval_min']} minutos")
    amount_box, amount = _field('Valor adicional por intervalo', svc.fmt_money(rule['amount']))
    line1 = design.txt('', 12.5, 'regular', theme.GRAY_TEXT)
    line2 = design.txt('', 12.5, 'bold')
    example = _example_card('Exemplo', line1, ft.Container(line2, margin=ft.Margin(left=0, top=4.5, right=0, bottom=0)),
                            spacing=5, padding=(12, 16.5))

    def values():
        return (svc.parse_minutes(after.value), svc.parse_minutes(every.value), svc.parse_decimal(amount.value))

    def refresh(event=None):
        start, step, value = values()
        if None in (start, step, value):
            line1.value, line2.value = 'Preencha valores válidos.', ''
        else:
            sample = {'enabled': True, 'start_after_min': start, 'interval_min': step, 'amount': str(value)}
            minutes = start + 2 * step
            count = svc.rotation_intervals(sample, minutes)
            line1.value = f'Após {minutes} min de ocupação:'
            line2.value = f'{count} intervalos × {svc.fmt_money(value)} = {svc.fmt_money(value * count)}'
        _refresh(line1, line2)
    for field in (after, every, amount):
        field.on_change = refresh
    refresh()

    def collect(enabled):
        start, step, value = values()
        if start is None:
            return 'Informe o tempo de tolerância em minutos.'
        if step is None:
            return 'Informe o intervalo de repetição em minutos.'
        if value is None:
            return 'Informe um valor válido, como R$ 0,20.'
        return {'enabled': enabled, 'start_after_min': start, 'interval_min': step, 'amount': str(value)}
    return _form_page(app, sid, 'rotation', [after_box, every_box, amount_box], example, rule['enabled'], collect)


def demand_page(app, sid, base, store, rules):
    rule = rules['demand']
    need_box, need = _field('Ativar quando estiverem em uso', f"{rule['min_stations']} ou mais estações")
    extra_box, extra = _field('Adicional por energia consumida', f"+ {svc.fmt_money(rule['extra'])} por kWh")
    base_value = base if base is not None else Decimal('0')
    row_extra, row_total = (design.txt('', 12.5, 'bold') for _ in range(2))
    row_base = design.txt(_per_kwh(base_value) if base is not None else '—', 12.5, 'bold')
    example = _example_card(
        'Exemplo com demanda alta',
        ft.Row([design.txt('Tarifa base', 12.5, 'regular', theme.GRAY_TEXT), row_base],
               alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        ft.Row([design.txt('Demanda', 12.5, 'regular', theme.GRAY_TEXT), row_extra],
               alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        ft.Container(height=8),
        ft.Row([design.txt('Tarifa aplicável', 12.5, 'regular', theme.GRAY_TEXT), row_total],
               alignment=ft.MainAxisAlignment.SPACE_BETWEEN))

    def refresh(event=None):
        value = svc.parse_decimal(extra.value)
        row_extra.value = f'+ {_per_kwh(value)}' if value is not None else '—'
        if value is None or base is None:
            row_total.value = '—'
        else:
            sample = {'demand': {'enabled': True, 'min_stations': 2, 'extra': str(value)}}
            row_total.value = _per_kwh(svc.effective_price(base, sample, None, occupancy=2))
        _refresh(row_extra, row_total)
    extra.on_change = refresh
    refresh()

    def collect(enabled):
        stations = svc.parse_minutes(need.value, minimum=1, maximum=99)
        value = svc.parse_decimal(extra.value)
        if stations is None:
            return 'Informe quantas estações em uso ativam a regra (1 a 99).'
        if value is None:
            return 'Informe um valor válido, como R$ 0,30.'
        return {'enabled': enabled, 'min_stations': stations, 'extra': str(value)}
    return _form_page(app, sid, 'demand', [need_box, extra_box], example, rule['enabled'], collect)


def peak_page(app, sid, base, store, rules):
    rule = rules['peak']
    start_box, start = _field('Início do período', rule['start'])
    end_box, end = _field('Fim do período', rule['end'])
    extra_box, extra = _field('Adicional por energia consumida', f"+ {svc.fmt_money(rule['extra'])} por kWh")
    days = list(rule['days'])
    days_text = design.txt(svc.days_label(days), 13, 'bold')
    sun = ft.Icon(ft.Icons.WB_SUNNY_OUTLINED, size=24, color='#F2B63C')
    calendar = ft.Icon(ft.Icons.CALENDAR_TODAY_OUTLINED, size=22, color=theme.TEXT_COLOR)
    days_card = design.card_box(
        ft.Column([ft.Row([sun, design.txt('Dias selecionados', 13.5, 'regular', theme.GRAY_TEXT), ft.Container(expand=True),
                           calendar], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                   ft.Container(days_text, margin=ft.Margin(left=0, top=6, right=0, bottom=0))], spacing=10),
        padding=ft.Padding(left=16, right=16, top=16, bottom=17), radius=18)

    def collect(enabled):
        begin, finish, value = svc.parse_time(start.value), svc.parse_time(end.value), svc.parse_decimal(extra.value)
        if begin is None or finish is None:
            return 'Informe horários válidos, como 18:00.'
        if begin == finish:
            return 'O início e o fim do período devem ser diferentes.'
        if value is None:
            return 'Informe um valor válido, como R$ 0,25.'
        return {'enabled': enabled, 'start': begin, 'end': finish, 'extra': str(value), 'days': days}
    return _form_page(app, sid, 'peak', [start_box, end_box, extra_box], days_card, rule['enabled'], collect)
