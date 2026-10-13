"""Gráficos leves feitos com controles nativos do Flet (sem dependências extras).

Funcionam no app mobile e no dashboard web, nos temas claro e escuro. Cada
gráfico expõe um rótulo semântico com o resumo dos dados para leitores de tela.
"""

import flet as ft
import flet.canvas as cv

from . import theme


def _number(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def bar_chart(values, labels, *, height=160, color=None, format_value=str, title=None,
              label_every=1, empty_message='Sem dados no período.'):
    """Barras verticais responsivas; cada barra mostra o valor no tooltip."""
    numbers = [_number(value) for value in values]
    peak = max(numbers, default=0)
    color = color or theme.RED
    header = [ft.Text(title, size=13, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR)] if title else []
    if not numbers or peak <= 0:
        return ft.Column(header + [ft.Container(ft.Text(empty_message, size=12, color=theme.GRAY_TEXT),
                                                height=height, alignment=ft.Alignment(0, 0))], spacing=8)
    bars, ticks = [], []
    for index, (number, label) in enumerate(zip(numbers, labels, strict=False)):
        ratio = number / peak if peak else 0
        bars.append(ft.Container(
            ft.Container(height=max(2, ratio * (height - 4)) if number > 0 else 2,
                         bgcolor=color if number > 0 else theme.LIGHT_GRAY,
                         border_radius=ft.BorderRadius(top_left=3, top_right=3, bottom_left=0, bottom_right=0)),
            expand=True, height=height, alignment=ft.Alignment(0, 1),
            tooltip=f'{label}: {format_value(values[index])}',
        ))
        ticks.append(ft.Container(
            ft.Text(label if index % max(1, label_every) == 0 else '', size=10, color=theme.GRAY_TEXT,
                    text_align=ft.TextAlign.CENTER, no_wrap=True, overflow=ft.TextOverflow.CLIP),
            expand=True,
        ))
    best = max(range(len(numbers)), key=numbers.__getitem__)
    summary = (f'{title or "Gráfico"}: {len(numbers)} períodos, máximo {format_value(values[best])} '
               f'em {labels[best]}.')
    chart = ft.Column([
        ft.Row(bars, spacing=2, vertical_alignment=ft.CrossAxisAlignment.END, height=height),
        ft.Row(ticks, spacing=2),
    ], spacing=4)
    return ft.Column(header + [ft.Semantics(content=chart, label=summary)], spacing=8)


def sparkline(values, *, width=120, height=36, color=None, stroke=2):
    """Linha simples (canvas) para tendência dentro de cartões."""
    numbers = [_number(value) for value in values]
    if len(numbers) < 2:
        return ft.Container(width=width, height=height)
    low, high = min(numbers), max(numbers)
    span = (high - low) or 1
    step = width / (len(numbers) - 1)
    elements = []
    for index, number in enumerate(numbers):
        x = index * step
        y = height - stroke - (number - low) / span * (height - 2 * stroke)
        elements.append(cv.Path.MoveTo(x, y) if index == 0 else cv.Path.LineTo(x, y))
    paint = ft.Paint(color=color or theme.RED, stroke_width=stroke, style=ft.PaintingStyle.STROKE)
    return ft.Semantics(
        content=cv.Canvas([cv.Path(elements, paint=paint)], width=width, height=height),
        label=f'Tendência: de {numbers[0]:g} a {numbers[-1]:g}',
    )


def heatmap(cells, row_labels, column_labels, *, color=None, cell_height=18, format_value=str,
            label_every=3):
    """Mapa de calor (linhas × colunas) com intensidade proporcional ao valor."""
    color = color or theme.RED
    peak = max((max(row) for row in cells if row), default=0)
    rows = []
    for row_label, row in zip(row_labels, cells, strict=False):
        boxes = []
        for column_label, value in zip(column_labels, row, strict=False):
            ratio = (value / peak) if peak else 0
            boxes.append(ft.Container(
                expand=True, height=cell_height, border_radius=3,
                bgcolor=ft.Colors.with_opacity(0.12 + 0.88 * ratio, color) if value else theme.LIGHT_GRAY,
                tooltip=f'{row_label} {column_label}: {format_value(value)}',
            ))
        rows.append(ft.Row([ft.Container(ft.Text(row_label, size=11, color=theme.GRAY_TEXT), width=34), *boxes],
                           spacing=2))
    header = ft.Row([ft.Container(width=34)] + [
        ft.Container(ft.Text(str(label) if index % label_every == 0 else '', size=10, color=theme.GRAY_TEXT,
                             no_wrap=True), expand=True)
        for index, label in enumerate(column_labels)
    ], spacing=2)
    legend = ft.Row([
        ft.Text('Menos', size=10, color=theme.GRAY_TEXT),
        *[ft.Container(width=14, height=10, border_radius=2,
                       bgcolor=ft.Colors.with_opacity(level, color)) for level in (0.15, 0.4, 0.7, 1)],
        ft.Text('Mais', size=10, color=theme.GRAY_TEXT),
    ], spacing=4, alignment=ft.MainAxisAlignment.END)
    total = sum(sum(row) for row in cells)
    return ft.Semantics(content=ft.Column([header, *rows, legend], spacing=3),
                        label=f'Mapa de calor com {format_value(total)} no total; máximo {format_value(peak)} '
                              'em um único horário.')


def ranking_bars(items, *, value_key, label_key, format_value=str, color=None, limit=8, caption_key=None):
    """Barras horizontais ordenadas (ex.: ranking de pontos por receita)."""
    color = color or theme.RED
    items = list(items)[:limit]
    peak = max((_number(item.get(value_key)) for item in items), default=0)
    rows = []
    for position, item in enumerate(items, start=1):
        number = _number(item.get(value_key))
        caption = item.get(caption_key) if caption_key else None
        rows.append(ft.Semantics(content=ft.Column([
            ft.Row([
                ft.Text(f'{position}. {item.get(label_key, "")}', size=13, color=theme.TEXT_COLOR, expand=True,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(format_value(item.get(value_key)), size=13, weight=ft.FontWeight.BOLD,
                        color=theme.TEXT_COLOR),
            ]),
            ft.Row([ft.Container(height=6, border_radius=3, bgcolor=color,
                                 expand=max(1, round(number / peak * 100)) if peak and number else 1,
                                 visible=bool(peak and number)),
                    ft.Container(height=6, border_radius=3, bgcolor=theme.LIGHT_GRAY,
                                 expand=max(1, 100 - round(number / peak * 100)) if peak and number else 100,
                                 visible=not peak or number < peak)], spacing=0),
            *([ft.Text(caption, size=11, color=theme.GRAY_TEXT)] if caption else []),
        ], spacing=4), label=f'{position}º {item.get(label_key, "")}: {format_value(item.get(value_key))}'))
    return ft.Column(rows, spacing=12)
