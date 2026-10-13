"""Tabela responsiva, paginação e seletor de período compartilhados (app e dashboard)."""

import flet as ft

from . import theme

PERIODS = (('today', 'Hoje'), ('7d', '7 dias'), ('30d', '30 dias'), ('custom', 'Personalizado'))


def data_table(columns, rows, *, empty_message='Nenhum registro encontrado.', numeric=()):
    """``columns``: [(chave, título)]; ``rows``: dicionários já formatados (strings ou controles).

    Rola na horizontal em telas estreitas; números alinham à direita.
    """
    if not rows:
        return ft.Container(ft.Text(empty_message, size=13, color=theme.GRAY_TEXT), padding=20,
                            alignment=ft.Alignment(0, 0))
    heading = ft.TextStyle(size=12, weight=ft.FontWeight.BOLD, color=theme.GRAY_TEXT,
                           font_family='BarlowSemiBold')

    def cell(value):
        if isinstance(value, ft.Control):
            return ft.DataCell(value)
        return ft.DataCell(ft.Text('—' if value in (None, '') else str(value), size=13, color=theme.TEXT_COLOR,
                                   selectable=True))

    table = ft.DataTable(
        columns=[ft.DataColumn(ft.Text(title), numeric=key in numeric) for key, title in columns],
        rows=[ft.DataRow(cells=[cell(row.get(key)) for key, _ in columns]) for row in rows],
        heading_text_style=heading,
        heading_row_height=40,
        data_row_min_height=40,
        data_row_max_height=56,
        column_spacing=20,
        horizontal_margin=12,
        divider_thickness=0.5,
        horizontal_lines=ft.BorderSide(0.5, theme.LIGHT_GRAY),
        bgcolor=theme.WHITE,
        border_radius=12,
    )
    return ft.Row([table], scroll=ft.ScrollMode.AUTO)


def cell_badge(control, height=26):
    """Badges alinhados ocupariam a altura da linha; fixa a altura dentro da tabela."""
    control.height = height
    control.padding = ft.Padding(left=6, right=6, top=0, bottom=0)
    return control


def pagination(total, limit, offset, on_change, *, label='registros'):
    """Rodapé "1–25 de 120" com anterior/próxima. ``on_change(novo_offset)`` é assíncrono."""
    first = 0 if not total else offset + 1
    last = min(offset + limit, total)

    def go(target):
        async def handler(event=None):
            await on_change(target)
        return handler

    previous = ft.IconButton(ft.Icons.CHEVRON_LEFT, tooltip='Página anterior', disabled=offset <= 0,
                             on_click=go(max(0, offset - limit)), icon_color=theme.TEXT_COLOR)
    following = ft.IconButton(ft.Icons.CHEVRON_RIGHT, tooltip='Próxima página', disabled=last >= total,
                              on_click=go(offset + limit), icon_color=theme.TEXT_COLOR)
    return ft.Row([
        ft.Text(f'{first}–{last} de {total} {label}', size=12, color=theme.GRAY_TEXT),
        previous, following,
    ], alignment=ft.MainAxisAlignment.END, spacing=4)


def period_selector(selected, on_select, *, options=PERIODS):
    """Segmentos acessíveis; ``on_select(chave)`` é assíncrono."""
    buttons = []
    for key, label in options:
        active = key == selected

        def choose(value):
            async def handler(event=None):
                await on_select(value)
            return handler

        control = ft.TextButton(
            content=ft.Text(label, size=13, color='#FFFFFF' if active else theme.TEXT_COLOR,
                            weight=ft.FontWeight.BOLD if active else ft.FontWeight.NORMAL),
            on_click=choose(key),
            style=ft.ButtonStyle(
                bgcolor=theme.RED if active else theme.WHITE,
                padding=ft.Padding(left=12, right=12, top=8, bottom=8),
                shape=ft.RoundedRectangleBorder(radius=6),
                side={ft.ControlState.FOCUSED: ft.BorderSide(2, theme.FOCUS),
                      ft.ControlState.DEFAULT: ft.BorderSide(1, theme.LIGHT_GRAY)},
            ),
        )
        control.data = key
        buttons.append(ft.Semantics(content=control, selected=active, button=True, label=f'Período: {label}'))
    return ft.Row(buttons, spacing=6, wrap=True)
