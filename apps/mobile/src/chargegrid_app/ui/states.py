"""Empty states and compact status chips shared by list screens."""
import flet as ft

from . import theme


def empty_state(icon, heading, message, action=None):
    """Illustrated empty list: what is missing, why, and the next step."""
    controls = [
        ft.Container(ft.Icon(icon, size=34, color=theme.ACCENT), width=72, height=72, border_radius=36,
                     bgcolor=theme.LIGHT_GRAY, alignment=ft.Alignment(0, 0)),
        ft.Text(heading, size=18, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR,
                font_family='BarlowSemiBold', text_align=ft.TextAlign.CENTER),
        ft.Text(message, size=13, color=theme.GRAY_TEXT, text_align=ft.TextAlign.CENTER),
    ]
    if action is not None:
        controls.append(action)
    return ft.Semantics(container=True, label=f'{heading}. {message}', content=ft.Container(
        ft.Column(controls, spacing=12, horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True),
        padding=ft.Padding(left=16, right=16, top=28, bottom=28), alignment=ft.Alignment(0, 0),
    ))


SESSION_TONES = {
    'completed': 'GREEN', 'charging': 'BLUE', 'starting': 'BLUE', 'stopping': 'BLUE',
    'interrupted': 'AMBER', 'failed': 'RED',
}


def status_chip(text, tone='SLATE'):
    """Filled chip; the foreground is computed for AA contrast on the fill."""
    fill = getattr(theme, tone)
    return ft.Container(
        ft.Text(text, size=11, weight=ft.FontWeight.BOLD, color=theme.on_color(fill)),
        bgcolor=fill, border_radius=12, padding=ft.Padding(left=10, right=10, top=3, bottom=3),
    )
