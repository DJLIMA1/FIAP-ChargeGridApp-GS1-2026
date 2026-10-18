"""Blocos visuais dos formulários de vínculo e configuração de estação (referência do vendedor).

Campos: repouso = cartão escuro arredondado com rótulo cinza em negrito; foco/edição = campo branco
com contorno cinza e rótulo branco regular (``cadastro_estacao_2``). Os botões mantêm um ``ft.Text``
como conteúdo direto, centralizado, como a referência.
"""

import flet as ft

from ..ui import design, theme

FIELD_HEIGHT = 44.5


def _border(radius, color, width=1):
    return ft.OutlineInputBorder(border_radius=radius, side=ft.BorderSide(width, color))


def setup_field(name, value='', hint='', *, password=False, keyboard=None, read_only=False, rest_bg=None,
                text_size=12.5, height=None, gap=6, edited=False, prefix=None, suffix=None):
    """Rótulo + campo. ``resultado.controls[1]`` é o ``TextField`` (identificado por ``.data == name``)."""
    transparent = '#00000000'
    rest_bg = rest_bg or theme.INPUT_BG
    caption = design.label(name)
    dark = theme.is_dark()
    if edited:  # estado de edição/foco da referência: campo branco, contorno cinza, rótulo branco regular
        rest_bg = '#FFFFFF' if dark else theme.INPUT_BG
    control = ft.TextField(
        value=value, hint_text=hint or None, password=password, can_reveal_password=password,
        keyboard_type=keyboard, read_only=read_only, data=name,
        filled=True, fill_color=rest_bg, focused_bgcolor='#FFFFFF' if dark else theme.INPUT_BG,
        color=theme.INPUT_TEXT, focused_color='#1D1F20' if dark else theme.INPUT_TEXT,
        cursor_color='#1D1F20' if dark else theme.INPUT_TEXT,
        hint_style=ft.TextStyle(color=theme.GRAY_TEXT, size=text_size, font_family=design.FONT),
        text_style=ft.TextStyle(size=text_size, font_family=design.FONT),
        border={ft.ControlState.DEFAULT: _border(design.RADIUS_CARD, transparent, 0),
                ft.ControlState.FOCUSED: _border(4, '#6B6B6B' if dark else theme.FOCUS)},
        content_padding=ft.Padding(left=13, right=13, top=13, bottom=13), text_size=text_size,
        error_max_lines=3, height=height, prefix=prefix, suffix=suffix)
    if edited:
        control.color = '#1D1F20' if dark else theme.INPUT_TEXT
        control.border = {ft.ControlState.DEFAULT: _border(4, '#6B6B6B' if dark else theme.FOCUS),
                          ft.ControlState.FOCUSED: _border(4, '#6B6B6B' if dark else theme.FOCUS)}
        caption.font_family = design.FONT
        caption.size = 11.5
        caption.color = theme.TEXT_COLOR

    def focus(event):
        caption.font_family = design.FONT
        caption.size = 11.5
        caption.color = theme.TEXT_COLOR
        caption.update()

    def blur(event):
        caption.font_family = design.FONT_BOLD
        caption.size = 11
        caption.color = theme.GRAY_TEXT
        caption.update()

    control.on_focus = focus
    control.on_blur = blur
    return ft.Column([caption, control], spacing=gap, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)


def cta(text, on_click, *, primary=True, height=49, size=14.6, weight='regular'):
    """Botão largo com o texto como conteúdo direto (branco com texto preto = principal)."""
    bg = theme.BTN_PRIMARY if primary else theme.BTN_SECONDARY
    fg = theme.BTN_PRIMARY_FG if primary else theme.BTN_SECONDARY_FG
    return ft.Container(design.txt(text, size, weight, fg, text_align=ft.TextAlign.CENTER), bgcolor=bg,
                        border_radius=design.RADIUS_BTN, height=height, alignment=ft.Alignment(0, 0),
                        padding=ft.Padding(left=16, right=16, top=0, bottom=0), on_click=on_click, ink=True)


def status_card(*controls, padding=14, spacing=6, height=None, top=None):
    """Cartão escuro (#191919) com cantos 20 do cartão de vínculo."""
    return ft.Container(ft.Column(list(controls), spacing=spacing, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                        bgcolor=theme.CARD, border_radius=20, height=height,
                        padding=ft.Padding(left=padding, right=padding, top=padding if top is None else top,
                                           bottom=padding))


def setup_title(app, text, on_back=None, bottom=-0.75):
    """Título centralizado dos formulários de vínculo: ``<`` fino à esquerda + título regular (referência)."""
    back = ft.Container(ft.Icon(ft.Icons.CHEVRON_LEFT, size=20, color=theme.TEXT_COLOR),
                        on_click=on_back or getattr(app, 'back', None), ink=False, width=34, height=34,
                        alignment=ft.Alignment(-1, 0), tooltip='Voltar')
    return ft.Container(ft.Row([back, design.txt(text, 14.7, 'regular', expand=True, text_align=ft.TextAlign.CENTER),
                                ft.Container(width=34)], spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        margin=ft.Margin(left=0, top=-4.25, right=0, bottom=bottom))
