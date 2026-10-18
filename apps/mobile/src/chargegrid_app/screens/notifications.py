"""Notificações (consumidor e vendedor): cartões agrupados por dia, como na referência."""

import flet as ft

from ..services import notifications as service
from ..ui import design, theme

_ICONS = {
    service.KIND_BATTERY: (ft.Icons.BATTERY_0_BAR, '#3EBF80'),
    service.KIND_OFFLINE: (ft.Icons.NOTIFICATIONS_NONE, '#F2B84A'),
}


def notification_card(item):
    icon, color = _ICONS.get(item['kind'], (ft.Icons.NOTIFICATIONS_NONE, theme.GRAY_TEXT))
    if item['kind'] == service.KIND_BATTERY:
        glyph = ft.Container(width=19, height=11, border=ft.Border.all(2, color), border_radius=3,
                             margin=ft.Margin(left=2, top=4, right=0, bottom=0))
    else:
        glyph = ft.Icon(icon, size=24, color=color)
    head = ft.Row([
        ft.Container(glyph, width=28, alignment=ft.Alignment(-1, -1)),
        ft.Column([design.txt(item['title'], 12.6, 'bold'),
                   design.txt(item['subtitle'], 10.5, 'regular', theme.GRAY_TEXT)], spacing=6, expand=True),
    ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.START)
    return design.card_box(
        ft.Column([head, ft.Container(design.txt(item['detail'], 11.3, 'regular'),
                                      margin=ft.Margin(left=0, top=6, right=0, bottom=0))], spacing=12),
        padding=ft.Padding(left=16, right=16, top=23, bottom=18))


async def build(app, **_):
    items = await service.collect(app)
    body = []
    for heading, group in service.grouped(items):
        body.append(ft.Container(design.txt(heading, 14.5, 'bold'), margin=ft.Margin(left=0, top=14, right=0, bottom=0)))
        body.extend(notification_card(item) for item in group)
    if not body:
        body.append(design.txt('Nenhuma notificação por enquanto.', 13, 'regular', theme.GRAY_TEXT))
    return design.page(*body, title='Notificações', on_back=app.back, title_size=22)
