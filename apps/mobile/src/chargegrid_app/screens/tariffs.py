"""Tarifa do posto (vendedor): tarifa atual, base e motivo numa tela só.

A visão geral mostra o que o motorista paga agora (tarifa atual), a tarifa base e o motivo
("Alta demanda", "Horário 22:00–06:00", "Preço normal"). O cálculo fica em **Detalhes**.
O dono define só dados base em subtelas: tarifa base por conector (``PATCH connectors/{id}``),
tarifação por horário, tarifa por demanda e taxa de permanência (``PUT stations/{id}/pricing``; a chave JSON
continua ``rotation``; o campo Teto ``max_amount`` só aparece quando a API o devolve).
O cálculo é ``chargegrid_core.pricing`` na API.

Rota ``tariffs``: ``station_id``, ``page`` (None | 'base' | 'schedule' | 'demand' | 'rotation'),
``interval`` (com ``page='schedule'``: índice do horário ou ``'new'``) e ``details`` (abre os detalhes).
O antigo ``page='peak'`` cai na visão geral.
"""

from datetime import time
from decimal import Decimal

import flet as ft

from chargegrid_core import pricing

from ..api_client import ApiError
from ..services import tariffs as svc
from ..ui import design, theme
from .station_admin import heading

PAGES = {
    'base': ('Tarifa base', 'Preço por kWh de cada conector, fora dos horários especiais e antes da demanda.'),
    'schedule': ('Tarifação por horário', 'Defina tarifas base diferentes por horário. Fora desses horários vale a '
                                          'tarifa base de cada conector.'),
    'demand': ('Tarifa por demanda', 'O ChargeGrid ajusta o preço pela procura real do posto, como um app de '
                                     'corrida. Você define só o limite e quão rápido ele reage.'),
    'rotation': ('Taxa de permanência', 'Cobrada quando o carro continua conectado depois que a recarga '
                                        'terminou, passada a tolerância. O motorista vê e aceita antes de iniciar.'),
}
SENSITIVITY_HELP = {
    'low': 'Só sobe com o posto bem cheio.',
    'medium': 'Equilíbrio entre ocupação e preço.',
    'high': 'Sobe cedo, assim que a procura começa a crescer.',
}
LEVEL_COLORS = {'low': '#3B8B5A', 'normal': '#4A6FA5', 'high': '#C27C1E', 'very_high': '#D72B32'}
REASON_COLORS = {'normal': '#3B8B5A', 'schedule': '#4A6FA5'}
REFRESH_SECONDS = 30
NEW_INTERVAL = {'start': '18:00', 'end': '21:00', 'days': [0, 1, 2, 3, 4], 'prices': {}}
SCENARIOS = (  # simulação com 4 conectores
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


def _points(connectors):
    """Conectores não retirados; os publicados primeiro decidem a tarifa exibida."""
    points = [p for p in connectors if not p.get('retired')]
    published = [p for p in points if p.get('active') is not False]
    return published or points


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


def _schedule(rules):
    """Tarifação por horário das regras (API antiga: sem ``schedule``)."""
    schedule = rules.get('schedule') or {}
    return {'enabled': schedule.get('enabled', True), 'intervals': list(schedule.get('intervals') or [])}


def _interval_index(interval):
    if interval in (None, ''):
        return None
    if str(interval) == 'new':
        return 'new'
    try:
        return int(interval)
    except (TypeError, ValueError):
        return None


async def build(app, station_id=None, page=None, interval=None, details=False, **_):
    station = await _station(app, station_id)
    sid = (station or {}).get('id') or station_id
    if not sid:
        return design.page(heading(app, 'Tarifa'), design.txt('Cadastre uma estação para definir tarifas.', 13,
                                                              'regular', theme.GRAY_TEXT))
    try:
        data = await app.api.request('GET', f'stations/{sid}/pricing')
    except ApiError as error:
        return design.page(heading(app, 'Tarifa'), design.txt(str(error), 13, 'regular', theme.GRAY_TEXT))
    if not isinstance(data, dict) or not {'rules', 'status', 'connectors'} <= data.keys():
        return design.page(heading(app, 'Tarifa'), design.txt('Tarifas indisponíveis agora. Tente de novo em instantes.',
                                                              13, 'regular', theme.GRAY_TEXT))
    if page == 'schedule' and _interval_index(interval) is not None:
        index = _interval_index(interval)
        intervals = _schedule(data['rules'])['intervals']
        if index == 'new' or 0 <= index < len(intervals):
            return interval_page(app, sid, data, index)
    if page in PAGES:
        return {'base': base_page, 'schedule': schedule_page, 'demand': demand_page,
                'rotation': rotation_page}[page](app, sid, data)
    return overview(app, sid, data, details=details is True or str(details).lower() == 'true')


# ---------------------------------------------------------------- visão geral
def _prices(point, status):
    """``(base do conector, base agora, preço agora)``; API antiga: sem a base do horário."""
    base = Decimal(str(point['base_price_per_kwh']))
    current = point.get('current_base_price_per_kwh')
    current = Decimal(str(current)) if current is not None else base
    price = point.get('current_price_per_kwh')
    price = Decimal(str(price)) if price is not None else pricing.dynamic_price(current, status['multiplier'])
    return base, current, price


def _reason(status):
    key = status.get('reason') or ('demand' if Decimal(str(status['multiplier'])) > 1 else 'normal')
    label = status.get('reason_label') or ('Alta demanda' if key == 'demand' else 'Preço normal')
    color = REASON_COLORS.get(key) or LEVEL_COLORS.get(status.get('level'), LEVEL_COLORS['high'])
    if key.startswith('demand') and status.get('level') in ('low', 'normal'):
        color = LEVEL_COLORS['high']
    return label, color


def _formula(point, status):
    """Como chegamos ao valor de um conector: base (do horário) × demanda = preço."""
    base, current, price = _prices(point, status)
    interval = status.get('schedule_now')
    in_schedule = bool(interval) and str(point['id']) in (interval.get('prices') or {})
    source = f"Tarifa do horário {pricing.window_label(interval)}" if in_schedule else 'Tarifa base'
    return f"{source} {svc.fmt_money(current)} × demanda {svc.multiplier_label(status['multiplier'])} = " \
           f"{svc.fmt_money(price)}"


def _details(status, connectors, rules):
    points = _points(connectors)
    schedule, interval = _schedule(rules), status.get('schedule_now')
    if interval:
        window = f"{pricing.window_label(interval)} · {svc.days_label(interval['days'])}"
    elif not schedule['enabled']:
        window = 'Desligada'
    else:
        window = 'Fora dos horários' if schedule['intervals'] else 'Nenhum horário'
    if status['enabled']:
        increase = f" (+{status['increase_percent']}%)" if status['increase_percent'] else ''
        demand = f"{status['level_label']} · {svc.multiplier_label(status['multiplier'])}{increase}"
    else:
        demand = 'Desligada'
    bar = ft.ProgressBar(value=status['pressure'] / 100, bar_height=6, border_radius=3,
                         color=LEVEL_COLORS[status['level']], bgcolor=theme.SEGMENT_OFF)
    formulas = [(point['public_code'], _formula(point, status)) for point in points]
    if len({formula for _, formula in formulas}) <= 1:  # todos iguais: uma linha só
        formulas = [(None, formula) for formula in {formula for _, formula in formulas}]
    lines = [design.txt((f'{code}: ' if code else '') + formula + ' por kWh', 12, 'semibold')
             for code, formula in formulas]
    return ft.Column([
        ft.Divider(height=1, color=theme.BORDER_SOFT),
        design.txt('Como chegamos a este valor', 12, 'bold'),
        *lines,
        _row('Tarifação por horário', window),
        _row('Demanda agora', demand),
        ft.Column([bar, design.txt(f"Pressão de demanda: {status['pressure']}%", 10.5, 'regular', theme.GRAY_TEXT)],
                  spacing=5),
        *[_row(item['label'], item['value'], item['detail']) for item in status['factors']],
        design.txt(f"Calculado pelo ChargeGrid. Teto da demanda: até {svc.multiplier_label(status['max_multiplier'])}. "
                   'Quem reserva ou inicia uma recarga trava o preço do momento.', 10.5, 'regular', theme.GRAY_TEXT),
    ], spacing=10, data='tariff-details-body')


def tariff_card(status, connectors, rules, expanded=False, on_toggle=None):
    """Cartão "Tarifa atual": preço de agora, tarifa base e motivo; o cálculo só em Detalhes."""
    label, color = _reason(status)
    points = _points(connectors)
    pairs = {(_prices(p, status)[0], _prices(p, status)[2]) for p in points}
    body = [ft.Row([design.txt('Tarifa atual', 13.5, 'bold', expand=True), _pill(label, color)],
                   vertical_alignment=ft.CrossAxisAlignment.CENTER)]
    if not points:
        body.append(design.txt('Nenhum conector neste posto.', 12, 'regular', theme.GRAY_TEXT))
    elif len(pairs) == 1:
        base, price = next(iter(pairs))
        body += [design.txt(_per_kwh(price), 30, 'semibold'),
                 design.txt(f'Tarifa base: {_per_kwh(base)}', 12.5, 'regular', theme.GRAY_TEXT)]
    else:
        for point in points:
            base, _, price = _prices(point, status)
            body.append(_row(point['public_code'], _per_kwh(price), f'Tarifa base: {_per_kwh(base)}'))
    toggle = ft.Container(
        ft.Row([design.txt('Detalhes', 12.5, 'semibold'),
                ft.Icon(ft.Icons.KEYBOARD_ARROW_UP if expanded else ft.Icons.KEYBOARD_ARROW_DOWN, size=20,
                        color=theme.TEXT_COLOR)], spacing=2, tight=True),
        on_click=on_toggle, ink=False, data='tariff-details', padding=ft.Padding(left=0, right=8, top=2, bottom=2))
    body.append(toggle)
    if expanded:
        body.append(_details(status, connectors, rules))
    return design.card_box(ft.Column(body, spacing=8), padding=ft.Padding(left=15, right=15, top=14, bottom=15),
                           radius=18, data='tariff-card')


def _base_summary(connectors):
    prices = {Decimal(str(p['base_price_per_kwh'])) for p in _points(connectors)}
    if not prices:
        return 'Nenhum conector'
    if len(prices) == 1:
        return f'{_per_kwh(next(iter(prices)))} · todos os conectores'
    return f'De {svc.fmt_money(min(prices))} a {_per_kwh(max(prices))} por conector'


def _schedule_summary(schedule):
    count = len(schedule['intervals'])
    text = 'Nenhum horário' if not count else f"{count} horário{'s' if count != 1 else ''}"
    return text + ('' if schedule['enabled'] or not count else ' · Inativa')


def entry_row(title, subtitle, icon, on_click, data=None):
    """Linha de ajuste (Tarifa, Potência): tile escuro 46 + título/subtítulo + ``>``."""
    return ft.Container(
        ft.Row([design.icon_tile(icon, size=46, dark=True, icon_size=24),
                ft.Column([design.txt(title, 13, 'semibold'), design.txt(subtitle, 11, 'regular', theme.GRAY_TEXT)],
                          spacing=2, expand=True),
                ft.Icon(ft.Icons.CHEVRON_RIGHT, size=22, color=theme.GRAY_TEXT)],
               spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        on_click=on_click, ink=False, data=data)


def overview(app, sid, data, details=False):
    rules = data['rules']
    state = {'data': data, 'details': details}
    slot = ft.Container()

    def draw():
        current = state['data']
        slot.content = tariff_card(current['status'], current['connectors'], current['rules'], state['details'], toggle)
        _refresh(slot)

    def toggle(event=None):
        state['details'] = not state['details']
        draw()
    draw()

    async def update():
        state['data'] = await app.api.request('GET', f'stations/{sid}/pricing')
        draw()
        app.page.update()
    if hasattr(app, 'set_poll'):
        app.set_poll(update, REFRESH_SECONDS)

    def entry(title, subtitle, key, icon):
        return entry_row(title, subtitle, icon, app.link('tariffs', station_id=sid, page=key), f'tariff-{key}')

    demand, rotation = rules['demand'], rules['rotation']
    entries = [
        entry('Tarifa base', _base_summary(data['connectors']), 'base', ft.Icons.ELECTRIC_BOLT),
        entry('Tarifação por horário', _schedule_summary(_schedule(rules)), 'schedule', ft.Icons.SCHEDULE),
        entry('Tarifa por demanda', f"Até +{demand['max_increase_percent']}% · sensibilidade "
                                    f"{pricing.SENSITIVITY_LABELS[demand['sensitivity']].lower()}"
                                    f"{'' if demand['enabled'] else ' · Inativa'}", 'demand', ft.Icons.TRENDING_UP),
        entry('Taxa de permanência', svc.rotation_summary(rotation), 'rotation', ft.Icons.ACCESS_TIME),
    ]
    return design.page(heading(app, 'Tarifa'), slot, design.section_label('Ajustes'), *entries, gap=16)


# ---------------------------------------------------------------- formulários
def _go(app, sid, **data):
    async def go(event=None):
        await app.go('tariffs', station_id=sid, **data)
    return go


def _back(app, sid):
    return _go(app, sid)


def _price_rows(points, values):
    """Um campo ``R$ … /kWh`` por conector: ``(linhas, {id: campo})``."""
    fields, rows = {}, []
    for point in points:
        field = design.number_field(svc.input_number(values[point['id']]), prefix='R$', suffix='/kWh')
        field.data = point['id']
        fields[point['id']] = field
        rows.append(ft.Row([ft.Column([design.txt(point['public_code'], 12.5, 'semibold'),
                                       design.txt('Publicado' if point.get('active') else 'Não publicado', 10.5,
                                                  'regular', theme.GRAY_TEXT)], spacing=1, expand=True),
                            ft.Container(_rounded(field), width=170)],
                           vertical_alignment=ft.CrossAxisAlignment.CENTER))
    return rows, fields


def _read_prices(points, fields):
    """``{id: Decimal}`` ou a mensagem de erro do primeiro campo inválido."""
    values = {}
    for point in points:
        value = svc.parse_decimal(fields[point['id']].value, maximum=Decimal('100'))
        if value is None:
            return f"Informe a tarifa de {point['public_code']} (R$ 0,00 a R$ 100,00)."
        values[point['id']] = value
    return values


def _simple_page(app, title, description, fields, footer, on_back):
    return design.page(heading(app, title, on_back),
                       ft.Container(design.txt(description, 13, 'regular', theme.GRAY_TEXT),
                                    margin=ft.Margin(left=0, top=-6, right=0, bottom=4)),
                       *fields, footer=footer, gap=16, gutter=4)


def _save_button(text, on_click):
    return ft.Container(design.primary_button(text, on_click, height=46, weight='bold'),
                        margin=ft.Margin(left=0, top=4, right=0, bottom=4))


def base_page(app, sid, data):
    """Tarifa base por conector (``PATCH connectors/{id}``: ``price_per_kwh``)."""
    title, description = PAGES['base']
    points = [p for p in data['connectors'] if not p.get('retired')]
    message = design.txt('', 12, 'regular', theme.ERROR, visible=False)
    if not points:
        return _simple_page(app, title, description,
                            [design.txt('Nenhum conector neste posto.', 12, 'regular', theme.GRAY_TEXT)], [],
                            _back(app, sid))
    rows, fields = _price_rows(points, {p['id']: p['base_price_per_kwh'] for p in points})

    async def save(event=None):
        values = _read_prices(points, fields)
        if isinstance(values, str):
            message.value, message.visible = values, True
            _refresh(message)
            return
        message.visible = False
        changes = {pid: value for pid, value in values.items()
                   if value != Decimal(str(next(p for p in points if p['id'] == pid)['base_price_per_kwh']))}
        for point_id, value in changes.items():
            await app.api.request('PATCH', f'connectors/{point_id}', {'price_per_kwh': str(value)})
        app.notice('Tarifa base salva.' if changes else 'Nenhuma alteração na tarifa base.')
        await _back(app, sid)()
    return _simple_page(app, title, description, rows, [message, _save_button('Salvar tarifa base', app.action(save))],
                        _back(app, sid))


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
              _save_button('Salvar regra', save)]
    return _simple_page(app, title, description, fields, footer, _back(app, sid))


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
            sample = {'demand': {'enabled': True, 'max_increase_percent': percent, 'sensitivity': state['sensitivity']}}
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
            'O acréscimo vale sobre a tarifa base do horário.',
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


def _days_row(state):
    row = ft.Row(wrap=True, spacing=8, run_spacing=8)

    def draw():
        row.controls = [
            ft.Container(design.txt(name, 12, 'bold' if index in state['days'] else 'medium',
                                    theme.BTN_PRIMARY_FG if index in state['days'] else theme.TEXT_COLOR),
                         width=44, height=38, border_radius=10, alignment=ft.Alignment(0, 0), on_click=toggle(index),
                         bgcolor=theme.BTN_PRIMARY if index in state['days'] else theme.TILE, ink=True, data=f'day-{index}')
            for index, name in enumerate(pricing.DAY_LABELS)]
        _refresh(row)

    def toggle(index):
        def handler(event=None):
            state['days'] ^= {index}
            draw()
        return handler
    draw()
    return row


def _interval_prices(interval, connectors):
    """``R$ 1,20/kWh`` (um preço) ou ``CG-01 R$ 1,20 · CG-02 R$ 1,60``."""
    codes = {p['id']: p['public_code'] for p in connectors}
    prices = [(codes.get(pid), Decimal(str(value))) for pid, value in (interval.get('prices') or {}).items()
              if pid in codes]
    if not prices:
        return 'Sem tarifa'
    if len({value for _, value in prices}) == 1:
        return _per_kwh(prices[0][1])
    return ' · '.join(f'{code} {svc.fmt_money(value)}' for code, value in prices)


def schedule_page(app, sid, data):
    """Lista de horários + Status. Cada horário abre o editor (``interval``)."""
    schedule = _schedule(data['rules'])
    connectors = data['connectors']
    items = [
        ft.Container(
            ft.Row([ft.Column([design.txt(pricing.window_label(item), 13, 'semibold'),
                               design.txt(f"{svc.days_label(item['days'])} · {_interval_prices(item, connectors)}",
                                          11, 'regular', theme.GRAY_TEXT)], spacing=2, expand=True),
                    ft.Icon(ft.Icons.CHEVRON_RIGHT, size=22, color=theme.GRAY_TEXT)],
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            on_click=app.link('tariffs', station_id=sid, page='schedule', interval=index), ink=False,
            data=f'interval-{index}', bgcolor=theme.CARD, border_radius=14,
            padding=ft.Padding(left=14, right=10, top=11, bottom=11))
        for index, item in enumerate(schedule['intervals'])]
    if not items:
        items = [design.txt('Nenhum horário cadastrado.', 12, 'regular', theme.GRAY_TEXT)]
    full = len(schedule['intervals']) >= pricing.MAX_INTERVALS
    add = design.secondary_button('Adicionar horário', app.link('tariffs', station_id=sid, page='schedule',
                                                                interval='new'),
                                  icon=ft.Icons.ADD, height=42, disabled=full)

    def collect(enabled):
        return {'enabled': enabled, 'intervals': schedule['intervals']}
    return _form_page(app, sid, 'schedule', data, [*items, add], schedule['enabled'], collect)


def interval_page(app, sid, data, index):
    """Editor de um horário: início/fim pelo seletor, dias e a tarifa base de cada conector."""
    schedule = _schedule(data['rules'])
    current = NEW_INTERVAL if index == 'new' else schedule['intervals'][index]
    points = [p for p in data['connectors'] if not p.get('retired')]
    state = {'start': current['start'], 'end': current['end'], 'days': set(current['days'])}
    start_box, _ = _time_box(app, 'Início', current['start'], lambda value: state.update(start=value))
    end_box, _ = _time_box(app, 'Fim', current['end'], lambda value: state.update(end=value))
    prices = current.get('prices') or {}
    rows, fields = _price_rows(points, {p['id']: prices.get(p['id'], p['base_price_per_kwh']) for p in points})
    message = design.txt('', 12, 'regular', theme.ERROR, visible=False)
    back = _go(app, sid, page='schedule')

    def fail(text):
        message.value, message.visible = text, True
        _refresh(message)

    async def put(intervals, notice):
        try:
            await app.api.request('PUT', f'stations/{sid}/pricing',
                                  {**data['rules'], 'schedule': {'enabled': schedule['enabled'], 'intervals': intervals}})
        except ApiError as error:
            fail(str(error))
            return
        app.notice(notice)
        await back()

    async def save(event=None):
        if state['start'] == state['end']:
            return fail('O início e o fim do horário devem ser diferentes.')
        if not state['days']:
            return fail('Escolha ao menos um dia.')
        if not points:
            return fail('Cadastre um conector antes de definir horários.')
        values = _read_prices(points, fields)
        if isinstance(values, str):
            return fail(values)
        item = {'start': state['start'], 'end': state['end'], 'days': sorted(state['days']),
                'prices': {pid: str(value) for pid, value in values.items()}}
        intervals = list(schedule['intervals'])
        if index == 'new':
            intervals.append(item)
        else:
            intervals[index] = item
        await put(intervals, 'Horário salvo.')

    async def remove(event=None):
        await put([item for position, item in enumerate(schedule['intervals']) if position != index],
                  'Horário removido.')

    fields_ = [ft.Row([ft.Container(start_box, expand=True), ft.Container(end_box, expand=True)], spacing=12),
               _labeled('Dias', _days_row(state), 'Horário que passa da meia-noite (ex.: 22:00–06:00) começa no dia '
                                                  'marcado e termina no dia seguinte.'),
               _labeled('Tarifa base neste horário', ft.Column(rows, spacing=10),
                        'O acréscimo por demanda, se houver, vale sobre esta tarifa.')]
    footer = [message, _save_button('Salvar horário', app.action(save))]
    if index != 'new':
        footer.append(design.secondary_button('Remover horário', app.action(remove), height=42))
    title = 'Novo horário' if index == 'new' else 'Editar horário'
    return _simple_page(app, title, 'Escolha quando esta tarifa vale e o preço de cada conector.', fields_, footer,
                        back)


def rotation_page(app, sid, data):
    """Taxa de permanência (regra ``rotation``): tolerância, intervalo, valor e, com a API nova, o Teto."""
    rule = data['rules']['rotation']
    capped = 'max_amount' in rule  # API antiga não tem teto: o campo fica oculto
    after = design.number_field(str(rule['start_after_min']), suffix='min', decimals=False)
    every = design.number_field(str(rule['interval_min']), suffix='min', decimals=False)
    amount = design.number_field(svc.input_number(rule['amount']), prefix='R$')
    cap = design.number_field(svc.input_number(rule['max_amount']) if capped else '', prefix='R$')
    line1 = design.txt('', 12.5, 'regular', theme.GRAY_TEXT)
    line2 = design.txt('', 12.5, 'bold')

    def values():
        return (svc.parse_int(after.value, minimum=0 if capped else 1), svc.parse_int(every.value),
                svc.parse_decimal(amount.value, maximum=Decimal('100')),
                svc.parse_decimal(cap.value, maximum=Decimal('1000')) if capped else None)

    def refresh(event=None):
        start, step, value, maximum = values()
        if None in (start, step, value) or (capped and maximum is None):
            line1.value, line2.value = 'Preencha valores válidos.', ''
        else:
            sample = {'enabled': True, 'start_after_min': start, 'interval_min': step}
            minutes = start + 2 * step
            count = svc.rotation_intervals(sample, minutes)
            total = value * count
            line1.value = f'Carro conectado por {minutes} min após a recarga:'
            line2.value = f'{count} intervalos × {svc.fmt_money(value)} = {svc.fmt_money(total)}'
            if capped and total > maximum:
                line2.value = f'{count} intervalos × {svc.fmt_money(value)}, limitado ao teto: {svc.fmt_money(maximum)}'
        _refresh(line1, line2)
    for field in (after, every, amount, cap):
        field.on_change = refresh
    refresh()

    def collect(enabled):
        start, step, value, maximum = values()
        if start is None:
            return f"Informe a tolerância de {0 if capped else 1} a 1440 minutos."
        if step is None:
            return 'Informe o intervalo de 1 a 1440 minutos.'
        if value is None:
            return 'Informe um valor de R$ 0,00 a R$ 100,00.'
        result = {'enabled': enabled, 'start_after_min': start, 'interval_min': step, 'amount': str(value)}
        if capped:
            if maximum is None:
                return 'Informe o teto de R$ 0,00 a R$ 1.000,00.'
            result['max_amount'] = str(maximum)
        return result
    fields = [_labeled('Tolerância depois da recarga', _rounded(after)),
              _labeled('Repetir a cobrança a cada', _rounded(every)),
              _labeled('Valor por intervalo', _rounded(amount))]
    if capped:
        fields.append(_labeled('Teto por recarga', _rounded(cap), 'A cobrança para ao chegar neste valor.'))
    fields.append(_card('Exemplo', line1, line2, spacing=5))
    return _form_page(app, sid, 'rotation', data, fields, rule['enabled'], collect)
