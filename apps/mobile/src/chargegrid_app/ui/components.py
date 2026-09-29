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
                # Intrinsic height follows system text scaling.
                height=None,
                filled=True,
                fill_color=theme.INPUT_BG,
                color=theme.INPUT_TEXT,
                cursor_color=theme.INPUT_TEXT,
                prefix_style=ft.TextStyle(color=theme.INPUT_TEXT),
                suffix_style=ft.TextStyle(color=theme.INPUT_TEXT),
                border_color=theme.INPUT_BORDER,
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
    inner = ft.Column(content, spacing=6, tight=True) if isinstance(content, list) else content
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
    """Keyboard-accessible Material action that grows with wrapped/scaled text.

    ``height`` remains the requested baseline size; vertical padding provides
    that target without imposing a clipping box on larger accessibility text.
    """
    return ft.TextButton(
        content=ft.Text(
            text,
            color=fg,
            size=16,
            font_family="BarlowSemiBold" if bold else "Barlow",
            weight=ft.FontWeight.BOLD if bold else ft.FontWeight.NORMAL,
            text_align=ft.TextAlign.CENTER,
        ),
        style=ft.ButtonStyle(
            bgcolor=bg,
            color=fg,
            padding=ft.Padding(left=14, right=14, top=max(12, (height or 48) / 2 - 10),
                               bottom=max(12, (height or 48) / 2 - 10)),
            shape=ft.RoundedRectangleBorder(radius=radius),
            side={ft.ControlState.FOCUSED: ft.BorderSide(2, theme.FOCUS),
                  ft.ControlState.DEFAULT: border.top if border else ft.BorderSide(0, bg)},
            overlay_color=ft.Colors.with_opacity(0.12, fg),
            animation_duration=motion.duration(160),
        ),
        on_click=on_click,
        expand=expand,
    )


def badge(text, bg=None, width=90):
    """Status always has a readable label, including bright dark-theme fills."""
    background = bg or theme.RED
    return ft.Container(
        content=ft.Text(text, size=12, color=theme.on_color(background),
                        text_align=ft.TextAlign.CENTER, weight=ft.FontWeight.BOLD),
        bgcolor=background,
        border_radius=6,
        width=width,
        padding=ft.Padding(left=6, right=6, top=5, bottom=5),
        alignment=ft.Alignment(0, 0),
    )


BRAND_PROMISE = 'Recarga com confirmação, do app ao ponto.'


def brand(*, compact=False):
    """One wordmark for authentication and the application shell."""
    size = 32 if compact else 44
    return ft.Row([
        ft.Container(
            ft.Image(src='/icon.png', width=size, height=size, fit=ft.BoxFit.COVER,
                     exclude_from_semantics=True),
            width=size, height=size, border_radius=10,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            alignment=ft.Alignment(0, 0),
        ),
        ft.Text('ChargeGrid', size=26 if compact else 32,
                weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR,
                font_family='BarlowSemiBold', expand=True),
    ], spacing=8, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER)


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
    return ft.TextButton(
        content=ft.Text(text,size=14,color=theme.TEXT_COLOR,
                        style=ft.TextStyle(decoration=ft.TextDecoration.UNDERLINE)),
        on_click=action,
        style=ft.ButtonStyle(alignment=ft.Alignment(-1,0),
                             padding=ft.Padding(left=0, right=8, top=14, bottom=14),
                             side={ft.ControlState.FOCUSED: ft.BorderSide(2, theme.FOCUS)}),
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
