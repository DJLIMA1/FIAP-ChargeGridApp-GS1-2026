"""Cartões de indicador (KPI), skeleton e estados vazios compartilhados por app e dashboard."""

import flet as ft

from . import theme
from .availability import point_status
from .components import badge


def kpi_card(label, value, *, hint=None, icon=None, tone=None, width=None, col=None, tooltip=None):
    """Indicador com rótulo, valor em destaque e nota opcional.

    ``tone`` colore somente o ícone; o valor usa ``TEXT_COLOR`` para manter contraste.
    """
    header = [ft.Text(label.upper(), size=11, color=theme.GRAY_TEXT, weight=ft.FontWeight.BOLD,
                      font_family='BarlowCondensedSemiBold', expand=True, max_lines=2)]
    if icon:
        header.append(ft.Icon(icon, size=18, color=tone or theme.ACCENT))
    controls = [ft.Row(header, spacing=6, vertical_alignment=ft.CrossAxisAlignment.START),
                ft.Text(value, size=26, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR,
                        font_family='BarlowCondensed', max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)]
    if hint:
        controls.append(ft.Text(hint, size=11, color=theme.GRAY_TEXT, max_lines=2))
    body = ft.Container(
        ft.Column(controls, spacing=4, tight=True),
        bgcolor=theme.WHITE, border_radius=12, padding=ft.Padding(left=14, right=14, top=12, bottom=12),
        border=ft.Border.all(1, theme.LIGHT_GRAY), width=width, tooltip=tooltip,
    )
    semantic = ft.Semantics(content=body, label=f'{label}: {value}' + (f'. {hint}' if hint else ''))
    if col is not None:
        semantic.col = col
    return semantic


def kpi_grid(cards, *, columns=None):
    """Grade responsiva: 2 colunas no celular, 3 no tablet e 4 no desktop."""
    columns = columns or {'xs': 6, 'md': 4, 'lg': 3}
    for item in cards:
        if getattr(item, 'col', 12) in (None, {}, 12):
            item.col = columns
    return ft.ResponsiveRow(cards, spacing=12, run_spacing=12)


def skeleton_block(height=16, width=None, radius=8, expand=None):
    """Placeholder neutro de carregamento (estático → respeita movimento reduzido)."""
    return ft.Container(height=height, width=width, border_radius=radius, bgcolor=theme.LIGHT_GRAY,
                        expand=expand)


def skeleton_cards(count=4, height=96, columns=None):
    cards = [ft.Semantics(content=ft.Container(height=height, border_radius=12, bgcolor=theme.LIGHT_GRAY),
                          label='Carregando indicador') for _ in range(count)]
    return kpi_grid(cards, columns=columns)


def empty_state(title, message, *, icon=ft.Icons.INSIGHTS_OUTLINED, action=None):
    controls = [ft.Icon(icon, size=40, color=theme.GRAY_TEXT),
                ft.Text(title, size=16, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR,
                        text_align=ft.TextAlign.CENTER),
                ft.Text(message, size=13, color=theme.GRAY_TEXT, text_align=ft.TextAlign.CENTER)]
    if action is not None:
        controls.append(action)
    return ft.Container(ft.Column(controls, spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                  tight=True),
                        padding=24, alignment=ft.Alignment(0, 0))


def error_state(message, retry=None):
    from .components import button
    return empty_state('Não foi possível carregar', message, icon=ft.Icons.CLOUD_OFF_OUTLINED,
                       action=button('Tentar novamente', retry, secondary=True) if retry else None)


def point_status_badge(point, width=110):
    """Badge com o mesmo rótulo/cor de disponibilidade usados no app."""
    label, color = point_status(point)
    return badge(label, color, width=width)


SEVERITY = {
    'critical': ('Crítico', 'RED', ft.Icons.ERROR_OUTLINE),
    'warning': ('Atenção', 'AMBER', ft.Icons.WARNING_AMBER_ROUNDED),
    'info': ('Info', 'BLUE', ft.Icons.INFO_OUTLINE),
}


def alert_tile(alert):
    label, color_name, icon = SEVERITY.get(alert.get('severity'), SEVERITY['info'])
    color = getattr(theme, color_name)
    return ft.Semantics(
        content=ft.Container(
            ft.Row([
                ft.Icon(icon, color=theme.ACCENT if color_name == 'AMBER' else color, size=22),
                ft.Column([ft.Text(alert.get('title', ''), size=14, weight=ft.FontWeight.BOLD,
                                   color=theme.TEXT_COLOR),
                           ft.Text(alert.get('detail', ''), size=12, color=theme.GRAY_TEXT)],
                          spacing=2, expand=True, tight=True),
                badge(label, color, width=72),
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.START),
            padding=12, border_radius=10, bgcolor=theme.WHITE, border=ft.Border.all(1, theme.LIGHT_GRAY),
        ),
        label=f"Alerta {label}: {alert.get('title', '')}. {alert.get('detail', '')}",
    )
