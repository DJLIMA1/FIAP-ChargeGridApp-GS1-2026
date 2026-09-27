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
                hint_style=ft.TextStyle(color='#62666B'),
                password=password,
                can_reveal_password=password,
                height=50,
                filled=True,
                fill_color=theme.INPUT_BG,
                color=theme.INPUT_TEXT,
                cursor_color=theme.INPUT_TEXT,
                prefix_style=ft.TextStyle(color=theme.INPUT_TEXT),
                suffix_style=ft.TextStyle(color=theme.INPUT_TEXT),
                border_color=theme.INPUT_BORDER,
                border_radius=4,
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
    inner = ft.Column(content, spacing=6, tight=True) if isinstance(content, list) else content
    if isinstance(inner, ft.Column):
        inner.horizontal_alignment = ft.CrossAxisAlignment.STRETCH
    return ft.Container(
        content=inner,
        bgcolor=theme.WHITE,
        border_radius=4,
        padding=padding,
        height=height,
        **kwargs,
    )


def disclosure_field(label, summary, controls, *, expanded=False, on_toggle=None, on_update=None):
    """Compact optional form section with full-width, retained field controls."""
    chevron = ft.Icon(ft.Icons.EXPAND_LESS if expanded else ft.Icons.EXPAND_MORE,size=20,color=theme.GRAY_TEXT)
    body = ft.Column(controls,visible=expanded,spacing=10,horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    summary_text = ft.Text(summary,size=12,color=theme.GRAY_TEXT)
    async def toggle(event=None):
        body.visible = not body.visible
        chevron.icon = ft.Icons.EXPAND_LESS if body.visible else ft.Icons.EXPAND_MORE
        semantic_header.expanded = body.visible
        if on_toggle:
            on_toggle(body.visible)
        if on_update:
            on_update()
        else:
            section.update()
    header = ft.TextButton(
        content=ft.Row([ft.Column([ft.Text(label,size=14,weight=ft.FontWeight.BOLD,color=theme.TEXT_COLOR),summary_text],
                                 spacing=3,expand=True),chevron],spacing=10),
        on_click=toggle,
        style=ft.ButtonStyle(padding=0,shape=ft.RoundedRectangleBorder(radius=4),overlay_color=theme.LIGHT_GRAY),
    )
    semantic_header = ft.Semantics(content=header,expanded=expanded)
    section = card(ft.Column([semantic_header,body],spacing=12,horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                   padding=14,border=ft.Border.all(1,theme.LIGHT_GRAY))
    return section,summary_text

def flat_button(text, bg, fg='#FFFFFF', on_click=None, bold=True, height=48, radius=4, expand=None, border=None):
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
    # Filled Material labels stay inside the white input instead of crossing
    # the dark card edge, where an outlined floating label loses contrast.
    control.border = ft.UnderlineInputBorder()
    control.label_style = ft.TextStyle(color='#767676', size=14)
    # Let Flutter allocate space for multi-line validation errors. A fixed
    # height clips error_text below the input on narrow phones.
    control.height = None
    control.error_max_lines = 3
    return control


def title(text, subtitle=""):
    controls = [ft.Text(text, size=24, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR,font_family="BarlowCondensed")]
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
