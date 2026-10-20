"""Tarifas do posto (vendedor): tarifa base por conector + tarifa dinâmica calculada pelo ChargeGrid.

O dono define só dados base (acréscimo máximo e sensibilidade, horário de pico, taxa de
rotatividade) em ``PUT stations/{id}/pricing``; o cálculo é ``chargegrid_core.pricing`` na API.
A visão geral mostra a demanda atual do posto (nível, multiplicador, preço agora e os fatores).
Rota ``tariffs``: ``station_id`` e ``page`` (None | 'demand' | 'peak' | 'rotation').
"""

from datetime import datetime, time
from decimal import Decimal

import flet as ft

from chargegrid_core import pricing

from ..api_client import ApiError
from ..services import tariffs as svc
from ..ui import design, theme
from .station_admin import heading

PAGES = {
    'demand': ('Tarifa por demanda', 'O ChargeGrid ajusta o preço pela procura real do posto, como um app de '
                                     'corrida. Você define só o limite e quão rápido ele reage.'),
    'peak': ('Horário de pico', 'Quando a energia tem mais procura na sua região. Nesse horário, a mesma '
                                'procura pesa mais no cálculo; com o posto vazio, o preço continua o base.'),
    'rotation': ('Taxa de rotatividade', 'Cobre a ocupação prolongada da vaga depois do tempo de tolerância.'),
}
SENSITIVITY_HELP = {
    'low': 'Só sobe com o posto bem cheio.',
    'medium': 'Equilíbrio entre ocupação e preço.',
    'high': 'Sobe cedo, assim que a procura começa a crescer.',
}
LEVEL_COLORS = {'low': '#3B8B5A', 'normal': '#4A6FA5', 'high': '#C27C1E', 'very_high': '#D72B32'}
REFRESH_SECONDS = 30
SCENARIOS = (  # simulação com 4 conectores, sem pico
    ('Metade ocupado', {'in_use': 2, 'busy_15m': Decimal('0.5'), 'starts_60m': 2, 'baseline_60m': 2}),
    ('3 de 4 ocupados', {'in_use': 3, 'busy_15m': Decimal('0.7'), 'starts_60m': 3, 'baseline_60m': 2}),
    ('Lotado, procura em alta', {'in_use': 4, 'busy_15m': Decimal('0.9'), 'starts_60m': 6, 'baseline_60m': 2}),
)


async def _station(app, station_id):
    try:
        if station_id:
            return await app.api.request('GET', f'stations/{station_id}')
        result = await app.api.request('GET', 'operator/stations', params={'limit': 100})
        items = result.get('items', result) if isinstance(result, dict) else result
        return (items or [None])[0]
    except ApiError:
        return None


def _refresh(*controls):
    """update() só quando o controle já está na página (na montagem inicial não há o que atualizar)."""
    for control in controls:
        try:
            control.update()
        except (RuntimeError, AssertionError):
            pass


def _base(connectors):
    """Menor tarifa base entre os conectores publicados do payload de ``pricing``."""
    return svc.base_price([{'price_per_kwh': c['base_price_per_kwh'], 'active': c.get('active')} for c in connectors])


def _per_kwh(value):
    return f'{svc.fmt_money(value)}/kWh'


def _row(label, value, detail=None):
    left = [design.txt(label, 12.5, 'regular', theme.GRAY_TEXT)]
    if detail:
        left.append(design.txt(detail, 10.5, 'regular', theme.GRAY_TEXT))
    return ft.Row([ft.Column(left, spacing=1, expand=True), design.txt(value, 12.5, 'bold')],
                  vertical_alignment=ft.CrossAxisAlignment.CENTER)


def _card(title, *controls, spacing=10):
    return design.card_box(ft.Column([design.txt(title, 13.5, 'bold'), *controls], spacing=spacing),
                           padding=ft.Padding(left=15, right=15, top=14, bottom=15), radius=18)


def _pill(text, color):
    return ft.Container(design.txt(text, 11, 'bold', '#FFFFFF'), bgcolor=color, border_radius=6,
                        padding=ft.Padding(left=9, right=9, top=4, bottom=4))


def _labeled(label, control, help_text=None):
    items = [design.txt(label, 11, 'bold'), control]
    if help_text:
        items.append(design.txt(help_text, 11, 'regular', theme.GRAY_TEXT))
    return ft.Column(items, spacing=9, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)


def _rounded(field):
    return ft.Container(field, border_radius=14, bgcolor=theme.INPUT_BG, clip_behavior=ft.ClipBehavior.ANTI_ALIAS)


async def build(app, station_id=None, page=None, **_):
    station = await _station(app, station_id)
    sid = (station or {}).get('id') or station_id
    if not sid:
        return design.page(heading(app, 'Tarifas'), design.txt('Cadastre uma estação para definir tarifas.', 13,
                                                               'regular', theme.GRAY_TEXT))
    try:
        data = await app.api.request('GET', f'stations/{sid}/pricing')
    except ApiError as error:
        return design.page(heading(app, 'Tarifas'), design.txt(str(error), 13, 'regular', theme.GRAY_TEXT))
    if not isinstance(data, dict) or not {'rules', 'status', 'connectors'} <= data.keys():
        return design.page(heading(app, 'Tarifas'), design.txt('Tarifas indisponíveis agora. Tente de novo em instantes.',
                                                               13, 'regular', theme.GRAY_TEXT))
    if page in PAGES:
        return {'demand': demand_page, 'peak': peak_page, 'rotation': rotation_page}[page](app, sid, data)
    return overview(app, sid, station, data)


# ---------------------------------------------------------------- visão geral
def demand_card(status, connectors):
    """Cartão "Demanda agora": nível, multiplicador, preço atual e os fatores medidos."""
    base = _base(connectors)
    current = pricing.dynamic_price(base, status['multiplier']) if base is not None else None
    if not status['enabled']:
        headline = [design.txt('Tarifa por demanda desligada', 15, 'semibold'),
                    design.txt('Os motoristas pagam a tarifa base.', 12, 'regular', theme.GRAY_TEXT)]
    else:
        increase = f"+{status['increase_percent']}%" if status['increase_percent'] else 'sem acréscimo'
        headline = [ft.Row([design.txt(svc.multiplier_label(status['multiplier']), 30, 'semibold'),
                            design.txt(increase, 13, 'regular', theme.GRAY_TEXT)],
                           spacing=10, vertical_alignment=ft.CrossAxisAlignment.END),
                    design.txt(f'Preço agora: {_per_kwh(current)}' if current is not None else 'Sem conectores ativos',
                               12.5, 'semibold')]
    bar = ft.ProgressBar(value=status['pressure'] / 100, bar_height=6, border_radius=3,
                         color=LEVEL_COLORS[status['level']], bgcolor=theme.SEGMENT_OFF)
    factors = [_row(item['label'], item['value'], item['detail']) for item in status['factors']]
    return design.card_box(ft.Column([
        ft.Row([design.txt('Demanda agora', 13.5, 'bold', expand=True),
                _pill(status['level_label'], LEVEL_COLORS[status['level']])]),
        *headline,
        ft.Column([bar, design.txt(f"Pressão de demanda: {status['pressure']}%", 10.5, 'regular', theme.GRAY_TEXT)],
                  spacing=5),
        ft.Divider(height=1, color=theme.BORDER_SOFT),
        *factors,
        design.txt(f"Calculado pelo ChargeGrid. Seu teto: até {svc.multiplier_label(status['max_multiplier'])}. "
                   'Quem reserva ou inicia uma recarga trava o preço do momento.', 10.5, 'regular', theme.GRAY_TEXT),
    ], spacing=10), padding=ft.Padding(left=15, right=15, top=14, bottom=15), radius=18, data='demand-card')


def overview(app, sid, station, data):
    rules, connectors = data['rules'], data['connectors']
    status_slot = ft.Container(demand_card(data['status'], connectors))

    async def update():
        fresh = await app.api.request('GET', f'stations/{sid}/pricing')
        status_slot.content = demand_card(fresh['status'], fresh['connectors'])
        app.page.update()
    if hasattr(app, 'set_poll'):
        app.set_poll(update, REFRESH_SECONDS)

    def open_page(key):
        return app.link('tariffs', station_id=sid, page=key)

    def entry(title, subtitle, key, icon):
        return ft.Container(
            ft.Row([design.icon_tile(icon, size=46, dark=True, icon_size=24),
                    ft.Column([design.txt(title, 13, 'semibold'), design.txt(subtitle, 11, 'regular', theme.GRAY_TEXT)],
                              spacing=2, expand=True),
                    ft.Icon(ft.Icons.CHEVRON_RIGHT, size=22, color=theme.GRAY_TEXT)],
                   spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            on_click=open_page(key), ink=False, data=f'tariff-{key}')

    demand, peak, rotation = rules['demand'], rules['peak'], rules['rotation']
    state = '' if demand['enabled'] else ' · Inativa'
    entries = [
        entry('Tarifa por demanda', f"Até +{demand['max_increase_percent']}% · sensibilidade "
                                     f"{pricing.SENSITIVITY_LABELS[demand['sensitivity']].lower()}{state}",
              'demand', ft.Icons.TRENDING_UP),
        entry('Horário de pico', f"{peak['start']}–{peak['end']} · {svc.days_label(peak['days'])}"
                                 f"{'' if peak['enabled'] else ' · Inativo'}", 'peak', ft.Icons.WB_SUNNY_OUTLINED),
        entry('Taxa de rotatividade', f"{svc.fmt_money(rotation['amount'])} a cada {rotation['interval_min']} min "
                                      f"após {rotation['start_after_min']} min{'' if rotation['enabled'] else ' · Inativa'}",
              'rotation', ft.Icons.ACCESS_TIME),
    ]
    return design.page(heading(app, 'Tarifas'), status_slot, base_tariffs(app, sid, connectors),
                       design.section_label('Tarifa dinâmica'), *entries, gap=16)


def base_tariffs(app, sid, connectors):
    """Tarifa base por conector (``PATCH connectors/{id}``: ``price_per_kwh``)."""
    points = [p for p in connectors if not p.get('retired')]
    fields = {}
    rows = []
    for point in points:
        field = design.number_field(svc.input_number(point['base_price_per_kwh']), prefix='R$', suffix='/kWh')
        field.data = point['id']
        fields[point['id']] = field
        rows.append(ft.Row([ft.Column([design.txt(point['public_code'], 12.5, 'semibold'),
                                       design.txt('Publicado' if point.get('active') else 'Não publicado', 10.5,
                                                  'regular', theme.GRAY_TEXT)], spacing=1, expand=True),
                            ft.Container(_rounded(field), width=170)],
                           vertical_alignment=ft.CrossAxisAlignment.CENTER))
    message = design.txt('', 11.5, 'regular', theme.ERROR, visible=False)

    async def save():
        changes = {}
        for point in points:
            value = svc.parse_decimal(fields[point['id']].value, maximum=Decimal('100'))
            if value is None:
                message.value, message.visible = f"Informe a tarifa de {point['public_code']} (R$ 0,00 a R$ 100,00).", True
                _refresh(message)
                return
            if value != Decimal(str(point['base_price_per_kwh'])):
                changes[point['id']] = value
        message.visible = False
        for point_id, value in changes.items():
            await app.api.request('PATCH', f'connectors/{point_id}', {'price_per_kwh': str(value)})
        app.notice('Tarifa base salva.' if changes else 'Nenhuma alteração na tarifa base.')
        await app.go('tariffs', station_id=sid)
    if not points:
        return _card('Tarifa base', design.txt('Nenhum conector neste posto.', 12, 'regular', theme.GRAY_TEXT))
    return _card('Tarifa base', design.txt('Preço por kWh de cada conector, antes da demanda.', 11.5, 'regular',
                                           theme.GRAY_TEXT),
                 *rows, message, design.secondary_button('Salvar tarifa base', app.action(save), height=42))


# ---------------------------------------------------------------- formulários
def _back(app, sid):
    async def back(event=None):
        await app.go('tariffs', station_id=sid)
    return back


def _form_page(app, sid, key, data, fields, enabled, collect):
    """Subtela: descrição, campos, Status + Salvar regra (rodapé fixo). ``collect`` -> regra ou erro."""
    title, description = PAGES[key]
    state = {'enabled': enabled}
    message = design.txt('', 12, 'regular', theme.ERROR, visible=False)
    status_slot = ft.Container()

    def draw_status():
        status_slot.content = design.segmented([(True, 'Ativa'), (False, 'Inativa')], state['enabled'], set_status,
                                               height=37.5)
        _refresh(status_slot)

    def set_status(value):
        state['enabled'] = value
        draw_status()
    draw_status()

    def fail(text):
        message.value, message.visible = text, True
        _refresh(message)

    async def save(event=None):
        rule = collect(state['enabled'])
        if isinstance(rule, str):
            fail(rule)
            return
        try:
            await app.api.request('PUT', f'stations/{sid}/pricing', {**data['rules'], key: rule})
        except ApiError as error:
            fail(str(error))
            return
        app.notice('Regra salva.')
        await _back(app, sid)()

    footer = [ft.Column([design.label('Status', strong=False), status_slot], spacing=4), message,
              ft.Container(design.primary_button('Salvar regra', save, height=46, weight='bold'),
                           margin=ft.Margin(left=0, top=4, right=0, bottom=4))]
    return design.page(heading(app, title, _back(app, sid)),
                       ft.Container(design.txt(description, 13, 'regular', theme.GRAY_TEXT),
                                    margin=ft.Margin(left=0, top=-6, right=0, bottom=4)),
                       *fields, footer=footer, gap=16, gutter=4)


def demand_page(app, sid, data):
    rule = data['rules']['demand']
    increase = design.number_field(str(rule['max_increase_percent']), prefix='até +', suffix='%', decimals=False)
    state = {'sensitivity': rule['sensitivity']}
    sensitivity_slot = ft.Container()
    help_text = design.txt('', 11, 'regular', theme.GRAY_TEXT)
    base = _base(data['connectors'])
    rows = ft.Column(spacing=10)

    def simulate(event=None):
        percent = svc.parse_int(increase.value, minimum=0, maximum=100)
        rows.controls = []
        if percent is None:
            rows.controls.append(design.txt('Informe um acréscimo de 0% a 100%.', 12, 'regular', theme.GRAY_TEXT))
        for label, signals in SCENARIOS if percent is not None else ():
            sample = {'demand': {'enabled': True, 'max_increase_percent': percent, 'sensitivity': state['sensitivity']},
                      'peak': {'enabled': False}}
            status = pricing.demand_status(sample, {**signals, 'connectors': 4, 'reserved': 0, 'local_now': None})
            price = _per_kwh(pricing.dynamic_price(base, status['multiplier'])) if base is not None else ''
            rows.controls.append(_row(label, f"{svc.multiplier_label(status['multiplier'])}  {price}".strip()))
        _refresh(rows)

    def draw_sensitivity():
        options = [(key, pricing.SENSITIVITY_LABELS[key]) for key in ('low', 'medium', 'high')]
        sensitivity_slot.content = design.segmented(options, state['sensitivity'], set_sensitivity, height=37.5)
        help_text.value = SENSITIVITY_HELP[state['sensitivity']]
        _refresh(sensitivity_slot, help_text)

    def set_sensitivity(value):
        state['sensitivity'] = value
        draw_sensitivity()
        simulate()
    increase.on_change = simulate
    draw_sensitivity()
    simulate()
    how = _card('Como calculamos', *[
        design.txt(f'• {text}', 12, 'regular', theme.GRAY_TEXT) for text in (
            'Ocupação dos conectores agora e a média dos últimos 15 minutos.',
            'Recargas da última hora comparadas ao normal deste dia e horário.',
            'Reservas aguardando com o posto lotado.',
            'Seu horário de pico, que amplifica a procura existente.',
            'O preço sobe em passos de 0,05× e nunca passa do seu limite.')], spacing=6)
    simulation = _card('Simulação (4 conectores)', rows)

    def collect(enabled):
        percent = svc.parse_int(increase.value, minimum=0, maximum=100)
        if percent is None:
            return 'Informe o acréscimo máximo de 0% a 100%.'
        return {'enabled': enabled, 'max_increase_percent': percent, 'sensitivity': state['sensitivity']}
    fields = [_labeled('Acréscimo máximo sobre a tarifa base', _rounded(increase),
                       'Com o posto lotado e procura alta, o preço chega a esse limite.'),
              _labeled('Sensibilidade', sensitivity_slot, None), help_text, simulation, how]
    return _form_page(app, sid, 'demand', data, fields, rule['enabled'], collect)


def _time_box(app, label, value, on_pick):
    """Campo de horário que abre o seletor do sistema (sem digitar ``18:00`` à mão)."""
    shown = design.txt(value, 15, 'semibold')

    async def open_picker(event=None):
        hour, minute = (int(part) for part in shown.value.split(':'))

        def picked(event):
            chosen = event.control.value
            if chosen:
                shown.value = f'{chosen.hour:02d}:{chosen.minute:02d}'
                on_pick(shown.value)
                _refresh(shown)
        app.page.show_dialog(ft.TimePicker(value=time(hour, minute), on_change=picked, help_text=label,
                                           confirm_text='OK', cancel_text='Cancelar',
                                           hour_format=ft.TimePickerHourFormat.H24))
    box = ft.Container(ft.Row([shown, ft.Icon(ft.Icons.SCHEDULE, size=20, color=theme.GRAY_TEXT)],
                              alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                       bgcolor=theme.INPUT_BG, border_radius=14, height=48,
                       padding=ft.Padding(left=14, right=14, top=0, bottom=0), on_click=open_picker, ink=True,
                       data=f'time-{label}')
    return _labeled(label, box), shown


def peak_page(app, sid, data):
    rule = data['rules']['peak']
    state = {'start': rule['start'], 'end': rule['end'], 'days': set(rule['days'])}
    start_box, _ = _time_box(app, 'Início', rule['start'], lambda value: state.update(start=value))
    end_box, _ = _time_box(app, 'Fim', rule['end'], lambda value: state.update(end=value))
    days_row = ft.Row(wrap=True, spacing=8, run_spacing=8)

    def draw_days():
        days_row.controls = [
            ft.Container(design.txt(name, 12, 'bold' if index in state['days'] else 'medium',
                                    theme.BTN_PRIMARY_FG if index in state['days'] else theme.TEXT_COLOR),
                         width=44, height=38, border_radius=10, alignment=ft.Alignment(0, 0), on_click=toggle(index),
                         bgcolor=theme.BTN_PRIMARY if index in state['days'] else theme.TILE, ink=True, data=f'day-{index}')
            for index, name in enumerate(pricing.DAY_LABELS)]
        _refresh(days_row)

    def toggle(index):
        def handler(event=None):
            state['days'] ^= {index}
            draw_days()
        return handler
    draw_days()
    note = design.txt(f"Agora: {datetime.now():%H:%M} · {'dentro' if data['status']['peak_now'] else 'fora'} "
                      'do horário de pico', 11, 'regular', theme.GRAY_TEXT)

    def collect(enabled):
        if state['start'] == state['end']:
            return 'O início e o fim do período devem ser diferentes.'
        if enabled and not state['days']:
            return 'Escolha ao menos um dia.'
        return {'enabled': enabled, 'start': state['start'], 'end': state['end'], 'days': sorted(state['days'])}
    fields = [ft.Row([ft.Container(start_box, expand=True), ft.Container(end_box, expand=True)], spacing=12),
              _labeled('Dias', days_row, 'Toque para marcar ou desmarcar.'), note]
    return _form_page(app, sid, 'peak', data, fields, rule['enabled'], collect)


def rotation_page(app, sid, data):
    rule = data['rules']['rotation']
    after = design.number_field(str(rule['start_after_min']), suffix='min', decimals=False)
    every = design.number_field(str(rule['interval_min']), suffix='min', decimals=False)
    amount = design.number_field(svc.input_number(rule['amount']), prefix='R$')
    line1 = design.txt('', 12.5, 'regular', theme.GRAY_TEXT)
    line2 = design.txt('', 12.5, 'bold')

    def values():
        return (svc.parse_int(after.value), svc.parse_int(every.value),
                svc.parse_decimal(amount.value, maximum=Decimal('100')))

    def refresh(event=None):
        start, step, value = values()
        if None in (start, step, value):
            line1.value, line2.value = 'Preencha valores válidos.', ''
        else:
            sample = {'enabled': True, 'start_after_min': start, 'interval_min': step}
            minutes = start + 2 * step
            count = svc.rotation_intervals(sample, minutes)
            line1.value = f'Vaga ocupada por {minutes} min após a recarga:'
            line2.value = f'{count} intervalos × {svc.fmt_money(value)} = {svc.fmt_money(value * count)}'
        _refresh(line1, line2)
    for field in (after, every, amount):
        field.on_change = refresh
    refresh()

    def collect(enabled):
        start, step, value = values()
        if start is None:
            return 'Informe a tolerância de 1 a 1440 minutos.'
        if step is None:
            return 'Informe o intervalo de 1 a 1440 minutos.'
        if value is None:
            return 'Informe um valor de R$ 0,00 a R$ 100,00.'
        return {'enabled': enabled, 'start_after_min': start, 'interval_min': step, 'amount': str(value)}
    fields = [_labeled('Começar a cobrar após', _rounded(after)), _labeled('Repetir a cobrança a cada', _rounded(every)),
              _labeled('Valor por intervalo', _rounded(amount)), _card('Exemplo', line1, line2, spacing=5)]
    return _form_page(app, sid, 'rotation', data, fields, rule['enabled'], collect)
