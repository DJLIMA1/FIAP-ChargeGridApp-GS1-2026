"""Histórico do vendedor: receita/energia, KPIs, gráfico de 7 dias e a página de consumo de energia.

Números reais de ``owner/overview`` e ``owner/timeseries`` (os mesmos da API do painel).
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import flet as ft
import flet.canvas as cv

from chargegrid_core import analytics
from chargegrid_core.formatting import brl

from ..ui import theme
from ..ui.design import card_box, page, txt

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


def line_chart(values, labels, *, color, fill, plot_height, dot_color=None, dots=(0, 2, 4, 6)):
    """Linha com área, grade horizontal (4 linhas) e rótulos, como na referência."""
    numbers = [_number(value) for value in values]
    count = len(numbers)
    top = (max(numbers, default=0) or 1) * 1.12
    inner = CHART_W - 2 * PAD_X
    step = inner / max(1, count - 1)
    points = [(PAD_X + index * step, plot_height - number / top * plot_height) for index, number in enumerate(numbers)]
    elements = [cv.Line(PAD_X, plot_height * row / 3, CHART_W - PAD_X, plot_height * row / 3,
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
    summary = (f'Gráfico: {count} dias, de {numbers[0]:g} a {numbers[-1]:g}, máximo {max(numbers):g}.' if numbers
               else 'Gráfico sem dados.')
    return ft.Semantics(content=cv.Canvas(elements, width=CHART_W, height=plot_height + 40), label=summary)


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
