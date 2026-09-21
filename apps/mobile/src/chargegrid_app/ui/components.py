import flet as ft

from . import motion, theme


def labeled_field(label, value="", hint="", password=False, on_change=None, on_blur=None):
    """Campo de texto com rótulo acima."""
    return ft.Column(
        [
            ft.Text(label, size=14, color=theme.GRAY_TEXT),
            ft.TextField(
                value=value,
                hint_text=hint,
                password=password,
                can_reveal_password=password,
                height=50,
                bgcolor=theme.WHITE,
                color=theme.TEXT_COLOR,
                cursor_color=theme.TEXT_COLOR,
                border_color=theme.LIGHT_GRAY,
                border_radius=8,
                text_size=15,
                content_padding=ft.Padding(left=15,right=15,top=10,bottom=10),
                on_change=on_change,
                on_blur=on_blur,
            ),
        ],
        spacing=8,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
    )

def card(content, height=None, padding=16, **kwargs):
    """Cartão branco com cantos arredondados."""
    inner = ft.Column(content, spacing=4, tight=True) if isinstance(content, list) else content
    if isinstance(inner, ft.Column):
        inner.horizontal_alignment = ft.CrossAxisAlignment.STRETCH
    return ft.Container(
        content=inner,
        bgcolor=theme.WHITE,
        border_radius=12,
        padding=padding,
        height=height,
        **kwargs,
    )

def flat_button(text, bg, fg='#FFFFFF', on_click=None, bold=True, height=48, radius=8, expand=None, border=None):
    """Botão "chapado" sem sombra."""
    return ft.Container(
        content=ft.Text(
            text,
            color=fg,
            size=16,
            font_family="BarlowSemiBold" if bold else "Barlow",
            weight=ft.FontWeight.BOLD if bold else ft.FontWeight.NORMAL,
            text_align=ft.TextAlign.CENTER,
        ),
        bgcolor=bg,
        height=height,
        border_radius=radius,
        alignment=ft.Alignment(0, 0),
        on_click=on_click,
        ink=True,
        expand=expand,
        border=border,
        padding=ft.Padding( left=10,right=10),
        animate=motion.animation(),
        animate_opacity=motion.animation(140),
        animate_scale=motion.animation(160),
        scale=1,
        on_hover=motion.hover,
    )

def badge(text, bg=None, width=90):
    """Etiqueta pequena arredondada (ex: 'Disponível', 'Pago')."""
    return ft.Container(
        content=ft.Text(text, size=11, color='#FFFFFF', text_align=ft.TextAlign.CENTER, weight=ft.FontWeight.BOLD),
        bgcolor=bg or theme.RED,
        border_radius=6,
        width=width,
        height=24,
        alignment=ft.Alignment(0, 0),
    )

def pill(text, bg=None, fg=None):
    """Chip/pilula cinza usada em tags de estação/cupom."""
    return ft.Container(
        content=ft.Text(text, size=11, color=fg or theme.GRAY_TEXT),
        bgcolor=bg or theme.LIGHT_GRAY,
        border_radius=10,
        padding=ft.Padding(left=10,right=10,top=4, bottom=4),
    )

def field(label, value="", password=False):
    control = labeled_field(label, value=value, password=password).controls[1]
    control.label = label
    control.label_style = ft.TextStyle(color=theme.GRAY_TEXT, size=12)
    control.height = 52
    return control


def title(text, subtitle=""):
    controls = [ft.Text(text, size=28, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR,font_family="BarlowCondensed")]
    if subtitle:
        controls.append(ft.Text(subtitle, size=13, color=theme.GRAY_TEXT))
    return ft.Column(controls,spacing=2)


def button(text, action, secondary=False):
    return flat_button(text, theme.LIGHT_GRAY if secondary else theme.RED, fg=theme.TEXT_COLOR if secondary else "#FFFFFF", on_click=action)


def text_link(text, action):
    return ft.Container(
        ft.Text(text,size=13,color=theme.TEXT_COLOR,style=ft.TextStyle(decoration=ft.TextDecoration.UNDERLINE)),
        on_click=action,
        alignment=ft.Alignment(-1,0),
        ink=True,
    )


def money(value):
    return f"R$ {float(value or 0):.2f}".replace(".", ",")


def date_time(value):
    from datetime import datetime
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().strftime("%d/%m/%Y %H:%M")
    except (ValueError, AttributeError):
        return "—"
