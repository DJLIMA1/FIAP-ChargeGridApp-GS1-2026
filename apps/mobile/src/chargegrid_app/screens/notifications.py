"""Notificações (consumidor e vendedor): cartões agrupados por dia, como na referência."""

import flet as ft

from ..services import notifications as service
from ..ui import design, theme

_ICONS = {
    service.KIND_BATTERY: (ft.Icons.BATTERY_0_BAR, '#3EBF80'),
    service.KIND_OFFLINE: (ft.Icons.NOTIFICATIONS_NONE, '#F2B84A'),
    service.KIND_POWER: (ft.Icons.BOLT_OUTLINED, '#F2B84A'),
    service.KIND_OVERSTAY: (ft.Icons.TIMER_OUTLINED, '#E8922B'),
}


def notification_card(item, unread=False, on_read=None):
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
        # Não lida: ponto vermelho, como o do sino.
        ft.Container(width=8, height=8, border_radius=4, bgcolor='#D94141', visible=unread,
                     margin=ft.Margin(left=0, top=4, right=0, bottom=0)),
    ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.START)
    footer = [design.txt(item['detail'], 11.3, 'regular', expand=True)]
    if unread and on_read:
        footer.append(ft.TextButton(content=design.txt('Marcar como lida', 11, 'semibold', theme.GRAY_TEXT),
                                    on_click=on_read, style=ft.ButtonStyle(padding=ft.Padding(4, 0, 0, 0))))
    return design.card_box(
        ft.Column([head, ft.Container(ft.Row(footer, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                                      margin=ft.Margin(left=0, top=6, right=0, bottom=0))], spacing=12),
        padding=ft.Padding(left=16, right=16, top=23, bottom=18), on_click=on_read if unread else None)


async def build(app, **_):
    items = await service.collect(app)
    pending = {item['id'] for item in service.unread(app, items)}

    def read(ids):
        async def handler(event=None):
            service.mark_read(app, ids)
            app.has_unread_notifications = bool(service.unread(app, items))
            await app.go('notifications')
        return handler

    body = []
    for heading, group in service.grouped(items):
        body.append(ft.Container(design.txt(heading, 14.5, 'bold'), margin=ft.Margin(left=0, top=14, right=0, bottom=0)))
        body.extend(notification_card(item, item['id'] in pending, read([item['id']])) for item in group)
    if not body:
        body.append(design.txt('Nenhuma notificação por enquanto.', 13, 'regular', theme.GRAY_TEXT))
    trailing = (ft.TextButton(content=design.txt('Marcar todas como lidas', 11.5, 'semibold', theme.GRAY_TEXT),
                              on_click=read(sorted(pending))) if pending else None)
    if trailing:
        body.insert(0, ft.Row([trailing], alignment=ft.MainAxisAlignment.END))
    return design.page(*body, title='Notificações', on_back=app.back, title_size=22)
