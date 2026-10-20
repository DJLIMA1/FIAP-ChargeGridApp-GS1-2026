"""Histórico do vendedor: receita/energia, KPIs, gráfico de 7 dias e a página de consumo de energia.

Números reais de ``owner/overview`` e ``owner/timeseries`` (os mesmos da API do painel).
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import flet as ft
import flet.canvas as cv

from chargegrid_core import analytics, economics
from chargegrid_core.formatting import brl

from ..ui import theme
from ..ui.design import card_box, labeled, number_field, page, primary_button, txt
from .history_export import export_card

DOWN, UP = ft.Icons.KEYBOARD_ARROW_DOWN, ft.Icons.KEYBOARD_ARROW_UP
WEEKDAYS_SHORT = ('Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom')
WEEKDAYS_LONG = ('Segunda-feira', 'Terça-feira', 'Quarta-feira', 'Quinta-feira', 'Sexta-feira', 'Sábado', 'Domingo')
PERIODS = ((7, 'Últimos 7 dias'), (14, 'Últimos 14 dias'), (30, 'Últimos 30 dias'))
GREEN = '#3EBF80'
GREEN_DOT = '#C7FFE4'
GREEN_FILL = '#222A25'
BLUE = '#6B9DFF'
BLUE_FILL = '#282E3A'
GRID = '#2E2E2E'
CHART_W = 362
PAD_X = 17.5


def _number(value):
    try:
        return float(Decimal(str(value or 0)))
    except (ArithmeticError, ValueError):
        return 0.0


def _int_text(value, digits=0):
    return f'{value:,.{digits}f}'.replace(',', '_').replace('.', ',').replace('_', '.')


def money_short(value):
    """``R$ 8.420`` (sem centavos, como na referência)."""
    return 'R$ ' + _int_text(_number(value))


def kwh_short(value):
    return _int_text(_number(value)) + ' kWh'


def _chart_shapes(numbers, labels, width, *, color, fill, plot_height, dot_color, dots):
    """Formas do gráfico para uma largura (redesenhadas quando a tela muda de tamanho)."""
    count = len(numbers)
    top = (max(numbers, default=0) or 1) * 1.12
    inner = width - 2 * PAD_X
    step = inner / max(1, count - 1)
    points = [(PAD_X + index * step, plot_height - number / top * plot_height) for index, number in enumerate(numbers)]
    elements = [cv.Line(PAD_X, plot_height * row / 3, width - PAD_X, plot_height * row / 3,
                        paint=ft.Paint(color=GRID, stroke_width=1)) for row in range(4)]
    if count > 1:
        area = [cv.Path.MoveTo(points[0][0], plot_height)] + [cv.Path.LineTo(x, y) for x, y in points] + [
            cv.Path.LineTo(points[-1][0], plot_height), cv.Path.Close()]
        elements.append(cv.Path(area, paint=ft.Paint(color=fill, style=ft.PaintingStyle.FILL)))
        line = [cv.Path.MoveTo(*points[0])] + [cv.Path.LineTo(x, y) for x, y in points[1:]]
        elements.append(cv.Path(line, paint=ft.Paint(color=color, stroke_width=2.5, style=ft.PaintingStyle.STROKE,
                                                     stroke_join=ft.StrokeJoin.ROUND, stroke_cap=ft.StrokeCap.ROUND)))
    last = count - 1
    for index in range(count):
        if index in dots or index == last:
            x, y = points[index]
            elements.append(cv.Circle(x, y, 3.6, paint=ft.Paint(color=dot_color or color, style=ft.PaintingStyle.FILL)))
    style = ft.TextStyle(size=10.5, color=theme.GRAY_TEXT, font_family='Inter')
    for index, text in enumerate(labels):
        elements.append(cv.Text(points[index][0], plot_height + 19.5, text, style=style, alignment=ft.Alignment(0, 0)))
    return elements


def line_chart(values, labels, *, color, fill, plot_height, dot_color=None, dots=(0, 2, 4, 6)):
    """Linha com área, grade horizontal (4 linhas) e rótulos, como na referência.

    Ocupa a largura disponível: o desenho é refeito quando o tamanho do gráfico muda (tela girada,
    janela do navegador, celulares de larguras diferentes)."""
    numbers = [_number(value) for value in values]
    draw = dict(color=color, fill=fill, plot_height=plot_height, dot_color=dot_color, dots=dots)
    state = {'width': CHART_W}

    def resized(event):
        width = float(getattr(event, 'width', 0) or 0)
        if width <= 2 * PAD_X or abs(width - state['width']) < 1:
            return
        state['width'] = width
        canvas.shapes = _chart_shapes(numbers, labels, width, **draw)
        try:
            canvas.update()
        except (RuntimeError, AssertionError, AttributeError):
            pass  # ainda não montado

    canvas = cv.Canvas(_chart_shapes(numbers, labels, CHART_W, **draw), height=plot_height + 40,
                       expand=True, resize_interval=60, on_resize=resized)
    count = len(numbers)
    summary = (f'Gráfico: {count} dias, de {numbers[0]:g} a {numbers[-1]:g}, máximo {max(numbers):g}.' if numbers
               else 'Gráfico sem dados.')
    # Row: o gráfico ocupa toda a largura disponível, dentro ou fora de um Container.
    return ft.Row([ft.Semantics(content=canvas, label=summary, expand=True)], spacing=0)


def _window(days, shift=0):
    """``days`` dias locais completos terminando hoje (baldes alinhados à meia-noite do relatório)."""
    midnight = datetime.now(analytics.REPORT_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    end = midnight + timedelta(days=1 - shift)
    return {'from': (end - timedelta(days=days)).astimezone(timezone.utc).isoformat(),
            'to': end.astimezone(timezone.utc).isoformat()}


async def _series(app, days):
    data = await app.api.request('GET', 'owner/timeseries', params={**_window(days), 'granularity': 'day'})
    labels, values = [], data['series']['energy_kwh']
    for bucket in data['buckets']:
        labels.append(WEEKDAYS_SHORT[datetime.fromisoformat(bucket).weekday()])
    return data, labels, values


def _row_card(content, on_click=None):
    return card_box(content, padding=ft.Padding(left=15, right=12, top=4, bottom=0), radius=12, on_click=on_click,
                    height=39.5, alignment=ft.Alignment(-1, 0))


def _chat_button(app):
    return ft.Container(ft.Row([ft.Image(src='/design/nav_chat.svg', width=20, height=20, color=theme.BTN_PRIMARY_FG, exclude_from_semantics=True),
                                txt('Fale com o ChatBot', 15.7, 'regular', theme.BTN_PRIMARY_FG)],
                               spacing=12, alignment=ft.MainAxisAlignment.CENTER),
                        padding=ft.Padding(left=0, right=22, top=0, bottom=0),
                        bgcolor=theme.BTN_PRIMARY, border_radius=12, height=38, on_click=app.link('chat'), ink=True)


def _stat(caption, value, *, align=ft.CrossAxisAlignment.START, size=22.6):
    return ft.Column([txt(caption, 10.7, 'regular', theme.GRAY_TEXT), txt(value, size, 'bold')], spacing=7.5,
                     horizontal_alignment=align)


async def dashboard(app, *, chart=True):
    days = 7
    overview = await app.api.request('GET', 'owner/overview', params=_window(days))
    result = await result_section(app, days)
    _, labels, values = await _series(app, days)
    kpis, stations = overview['kpis'], overview['stations']
    expanded = bool(chart)
    header = ft.Row([txt('Últimos 7 dias', 11.6, 'bold'), ft.Icon(DOWN if expanded else UP, size=24,
                                                                  color=theme.GRAY_TEXT)],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    body = [
        ft.Row([ft.Container(_stat('Receita total', money_short(kpis['revenue'])), expand=True,
                             margin=ft.Margin(left=0, top=2, right=0, bottom=0)),
                ft.Container(_stat('Energia vendida', kwh_short(kpis['energy_kwh'])), width=129)]),
        ft.Container(height=38),
        _row_card(ft.Row([txt('Consumo de Energia', 11.6, 'bold'), ft.Icon(ft.Icons.CHEVRON_RIGHT, size=22,
                                                                         color=theme.GRAY_TEXT)],
                         alignment=ft.MainAxisAlignment.SPACE_BETWEEN), app.link('history', manage=True, page='energy')),
        ft.Container(height=36),
        card_box(ft.Column([
            ft.Row([ft.Column([txt('Recargas', 9.7, 'regular', theme.GRAY_TEXT), ft.Container(txt(kpis['sessions'], 17.2, 'bold'), margin=ft.Margin(0, -2, 0, 0))],
                              spacing=1.5),
                    ft.Column([txt('Ticket médio', 9.7, 'regular', theme.GRAY_TEXT),
                               ft.Container(txt(brl(kpis['average_ticket'] or 0), 17.2, 'bold'), margin=ft.Margin(0, -2, 0, 0))], spacing=1.5,
                              horizontal_alignment=ft.CrossAxisAlignment.END)],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Container(height=1, bgcolor=theme.BORDER_SOFT, margin=ft.Margin(left=0, top=12, right=0, bottom=19)),
            ft.Row([txt('Estações ativas', 11.7, 'regular', theme.GRAY_TEXT),
                    txt(f"{stations['active']} de {stations['total']}", 12.2, 'bold', GREEN)],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        ], spacing=0), padding=ft.Padding(left=16.5, right=16.5, top=18.5, bottom=18), radius=16, height=130),
        ft.Container(height=35.5),
        *result,
        _row_card(header, app.link('history', manage=True, chart=not expanded)),
    ]
    if expanded:
        body.append(ft.Container(line_chart(values, labels, color=GREEN, fill=GREEN_FILL, plot_height=157.5,
                                            dot_color=GREEN_DOT), margin=ft.Margin(left=0, top=38.5, right=0, bottom=0)))
        body.append(ft.Container(height=31.5))
    else:
        body.append(ft.Container(height=36))
    body.append(_chat_button(app))
    return body


async def energy_page(app, *, days=7):
    days = days if days in (7, 14, 30) else 7
    current = await app.api.request('GET', 'owner/overview', params=_window(days))
    previous = await app.api.request('GET', 'owner/overview', params=_window(days, shift=days))
    data, labels, values = await _series(app, days)
    if days != 7:
        labels = [f"{datetime.fromisoformat(b).day:02d}" if index % 5 == 0 else '' for index, b in enumerate(data['buckets'])]
    total = _number(current['kpis']['energy_kwh'])
    before = _number(previous['kpis']['energy_kwh'])
    numbers = [_number(v) for v in values]
    peak = max(numbers, default=0)
    peak_day = ''
    if peak > 0:
        peak_day = WEEKDAYS_LONG[datetime.fromisoformat(data['buckets'][numbers.index(peak)]).weekday()]
    delta = []
    if before > 0:
        change = (total - before) / before * 100
        up = change >= 0
        delta = [txt(('↑ ' if up else '↓ ') + _int_text(abs(change), 1) + '%', 11, 'semibold', GREEN if up else theme.RED)]
    label = next(text for value, text in PERIODS if value == days)
    selector = ft.PopupMenuButton(
        content=card_box(ft.Row([txt(label, 12.5, 'bold'), ft.Icon(ft.Icons.CALENDAR_TODAY_OUTLINED, size=19,
                                                                  color=theme.TEXT_COLOR)],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER),
                         padding=ft.Padding(left=18, right=18, top=0, bottom=0), radius=14, height=45,
                         alignment=ft.Alignment(-1, 0)),
        tooltip='Escolher período',
        items=[ft.PopupMenuItem(content=text, on_click=app.link('history', manage=True, page='energy', days=value))
               for value, text in PERIODS])
    controls = [
        ft.Container(height=32.5),
        selector,
        ft.Container(height=41),
        ft.Row([ft.Container(ft.Column([txt('Energia total', 10.7, 'regular', theme.GRAY_TEXT),
                                        txt(kwh_short(total), 22.6, 'bold'), *delta], spacing=5.5), expand=True),
                ft.Container(ft.Column([txt('Pico de consumo', 10.7, 'regular', theme.GRAY_TEXT),
                                        txt(kwh_short(peak), 22.6, 'bold'),
                                        txt(peak_day, 11, 'semibold', GREEN)], spacing=5.5), width=112)],
               vertical_alignment=ft.CrossAxisAlignment.START),
        ft.Container(height=38),
        txt('Energia entregue - kWh', 13, 'bold'),
        ft.Container(height=36.5),
        line_chart(values, labels, color=BLUE, fill=BLUE_FILL, plot_height=183, dots=(0, 2, 4, 6)),
        ft.Container(height=32),
        _chat_button(app),
    ]
    back = ft.Container(ft.Icon(ft.Icons.KEYBOARD_ARROW_LEFT, size=34, color=theme.TEXT_COLOR), width=28, height=34,
                        on_click=app.link('history', manage=True), tooltip='Voltar', alignment=ft.Alignment(-1, 0),
                        margin=ft.Margin(left=-9, top=0, right=0, bottom=0))
    head = ft.Row([back, txt('Consumo de energia', 22.6, 'bold', expand=True)], spacing=3,
                  vertical_alignment=ft.CrossAxisAlignment.CENTER)
    return page(head, *controls, gap=0)


# ------------------------------------------------- resultado do período (margem)
RESULT_TITLE = 'Resultado do período'
NOT_PROFIT = 'Receita bruta não é lucro.'
ECONOMICS_PERIODS = PERIODS


async def _margin(app, params):
    owner_margin = getattr(app.api, 'owner_margin', None)
    if owner_margin is not None:
        return await owner_margin(params)
    return await app.api.request('GET', 'owner/margin', params=params)


def _brl(value):
    return brl(Decimal(str(value))) if value not in (None, '') else '—'


def _fee_label(report):
    fees = {item.get('platform_fee_percent') for item in report.get('stations') or [] if item.get('platform_fee_percent')}
    if len(fees) != 1:
        return 'Comissão da plataforma'
    percent = Decimal(next(iter(fees))).normalize()
    return f"Comissão da plataforma ({f'{percent:f}'.replace('.', ',')}%)"


def _cascade_row(label, value, *, strong=False, color=None):
    return ft.Row([txt(label, 11.7, 'semibold' if strong else 'regular', None if strong else theme.GRAY_TEXT,
                       expand=True),
                   txt(value, 13 if strong else 12.2, 'bold', color)],
                  alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER)


def cascade(report, *, detailed=False):
    """Receita bruta → comissão → (tarifa do pagamento) → repasse → custo da energia → margem."""
    totals = report.get('totals') or {}
    rows = [_cascade_row('Receita bruta', _brl(totals.get('revenue_total'))),
            _cascade_row(_fee_label(report), '− ' + _brl(totals.get('platform_fee')))]
    if totals.get('provider_fee') is not None:
        rows.append(_cascade_row('Tarifa do pagamento', '− ' + _brl(totals['provider_fee'])))
    rows.append(_cascade_row('Repasse ao dono', _brl(totals.get('owner_net')), strong=True))
    energy_cost = totals.get('energy_cost')
    coverage = totals.get('coverage') or {}
    missing = int(coverage.get('missing_energy_cost') or 0)
    if energy_cost is None:
        cost = 'não informado'
    else:
        cost = '− ' + _brl(energy_cost) + ('*' if missing else '')
    rows.append(_cascade_row('Custo da energia', cost))
    margin = totals.get('margin')
    color = None
    if margin is not None:
        color = GREEN if Decimal(str(margin)) >= 0 else theme.RED
    rows.append(_cascade_row('Margem estimada', _brl(margin) if margin is not None else '—', strong=True, color=color))
    if detailed:
        coupons = report.get('coupons') or {}
        dynamic = report.get('dynamic_pricing') or {}
        if coupons.get('sessions'):
            rows.append(_cascade_row(f"Cupons ({coupons['sessions']} recargas)", '− ' + _brl(coupons.get('discount'))))
        if dynamic.get('sessions_with_increase'):
            rows.append(_cascade_row(f"Preço dinâmico ({dynamic['sessions_with_increase']} recargas)",
                                     '+ ' + _brl(dynamic.get('demand_effect'))))
    if missing:
        rows.append(txt(f"* {missing} de {coverage.get('sessions')} recargas sem custo do kWh: margem total não "
                        'calculada. Informe o custo do kWh do posto.', 10, 'regular', theme.WARNING))
    rows.append(txt(NOT_PROFIT + ' Margem = repasse − custo estimado da energia (sem custos fixos).', 10,
                    'regular', theme.GRAY_TEXT))
    return rows


def result_card(app, report, *, days=7, on_click=None):
    totals = report.get('totals') or {}
    sessions = int(totals.get('sessions') or 0)
    head = [txt(RESULT_TITLE, 11.6, 'bold', expand=True)]
    if on_click:
        head.append(ft.Icon(ft.Icons.CHEVRON_RIGHT, size=22, color=theme.GRAY_TEXT))
    caption = f"Últimos {days} dias · {sessions} {'recarga' if sessions == 1 else 'recargas'}"
    return card_box(ft.Column([ft.Row(head, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                               txt(caption, 9.7, 'regular', theme.GRAY_TEXT), ft.Container(height=4),
                               *cascade(report, detailed=on_click is None)], spacing=8),
                    padding=ft.Padding(left=16.5, right=16.5, top=16, bottom=16), radius=16, on_click=on_click,
                    data='owner-result')


async def result_section(app, days=7):
    """Cartão "Resultado do período" no dashboard (lista vazia se a API não tiver ``/owner/margin``)."""
    try:
        report = await _margin(app, {**_window(days), 'limit': 1})
        card = result_card(app, report, days=days, on_click=app.link('history', manage=True, page='economics'))
    except Exception:  # API antiga, sem rede ou dados incompletos: o dashboard segue sem o cartão
        return []
    return [card, ft.Container(height=35.5)]


def cost_text(value):
    """``'0.8500'`` -> ``'0,85'`` (campo do custo do kWh)."""
    if value in (None, ''):
        return ''
    number = Decimal(str(value)).normalize()
    if number == number.quantize(Decimal('0.01')):
        number = number.quantize(Decimal('0.01'))
    return f'{number:f}'.replace('.', ',')


async def _save_economics(app, station_id, value):
    update = getattr(app.api, 'update_station_economics', None)
    if update is not None:
        return await update(station_id, value)
    return await app.api.request('PUT', f'stations/{station_id}/economics', {'energy_cost_per_kwh': value})


def station_cost_editor(app, station, days):
    field = number_field(cost_text(station.get('energy_cost_per_kwh')), prefix='R$', suffix='/kWh', hint='0,85')
    field.data = f"energy-cost-{station.get('station_id')}"

    async def save():
        raw = (field.value or '').strip()
        try:
            value = economics.clean_energy_cost(raw or None)
        except ValueError as error:
            app.notice(str(error))
            return
        await _save_economics(app, station['station_id'], None if value is None else str(value))
        app.notice('Custo do kWh salvo. Vale para as próximas recargas.')
        await app.go('history', manage=True, page='economics', days=days)

    fee = station.get('platform_fee_percent')
    fee_text = (f"{cost_text(fee).replace(',00', '')}%" if fee else 'padrão do contrato')
    return card_box(ft.Column([
        txt(station.get('station_name') or 'Posto', 13.5, 'semibold'),
        labeled('Custo do kWh pago à distribuidora', field),
        txt(f'Comissão da plataforma: {fee_text} · definida em contrato (só leitura).', 10.5, 'regular',
            theme.GRAY_TEXT),
        primary_button('Salvar custo', app.action(save), height=42, size=13),
    ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
        padding=ft.Padding(left=16, right=16, top=16, bottom=16), radius=16)


async def economics_page(app, *, days=7):
    """Subpágina ``history?manage=1&page=economics``: resultado, custo do kWh por posto e exportação."""
    days = days if days in (7, 14, 30) else 7
    params = _window(days)
    report = await _margin(app, {**params, 'limit': 1})
    label = next(text for value, text in ECONOMICS_PERIODS if value == days)
    selector = ft.PopupMenuButton(
        content=card_box(ft.Row([txt(label, 12.5, 'bold'), ft.Icon(ft.Icons.CALENDAR_TODAY_OUTLINED, size=19,
                                                                  color=theme.TEXT_COLOR)],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER),
                         padding=ft.Padding(left=18, right=18, top=0, bottom=0), radius=14, height=45,
                         alignment=ft.Alignment(-1, 0)),
        tooltip='Escolher período',
        items=[ft.PopupMenuItem(content=text, on_click=app.link('history', manage=True, page='economics', days=value))
               for value, text in ECONOMICS_PERIODS])
    warnings = [txt('• ' + text, 10.5, 'regular', theme.WARNING) for text in report.get('warnings') or []]
    stations = [station_cost_editor(app, station, days) for station in report.get('stations') or []]

    async def fetch(fmt, query):
        return await app.api.owner_export('margin', fmt, query)
    stamp = datetime.now(analytics.REPORT_TZ).strftime('%Y%m%d-%H%M')
    exporter = export_card(app, fetch, lambda fmt: f'chargegrid-resultado-{stamp}.{fmt}', params=params,
                           title='Exportar resultado (PDF/CSV)', data='margin-export',
                           subtitle=f'{label}: cascata, efeitos do preço dinâmico e cupons, por posto e por recarga.')
    methodology = [txt(text, 10, 'regular', theme.GRAY_TEXT) for text in report.get('methodology') or []]
    back = ft.Container(ft.Icon(ft.Icons.KEYBOARD_ARROW_LEFT, size=34, color=theme.TEXT_COLOR), width=28, height=34,
                        on_click=app.link('history', manage=True), tooltip='Voltar', alignment=ft.Alignment(-1, 0),
                        margin=ft.Margin(left=-9, top=0, right=0, bottom=0))
    head = ft.Row([back, txt(RESULT_TITLE, 22.6, 'bold', expand=True)], spacing=3,
                  vertical_alignment=ft.CrossAxisAlignment.CENTER)
    controls = [ft.Container(height=24), selector, ft.Container(height=24), result_card(app, report, days=days)]
    if warnings:
        controls += [ft.Container(height=14), ft.Column(warnings, spacing=4)]
    controls += [ft.Container(height=30), txt('Custo da energia', 15, 'bold'), ft.Container(height=12)]
    controls += [ft.Column(stations, spacing=14)] if stations else [
        txt('Cadastre um posto para informar o custo do kWh.', 11, 'regular', theme.GRAY_TEXT)]
    controls += [ft.Container(height=30), exporter, ft.Container(height=22), ft.Column(methodology, spacing=6),
                 ft.Container(height=16)]
    return page(head, *controls, gap=0)
