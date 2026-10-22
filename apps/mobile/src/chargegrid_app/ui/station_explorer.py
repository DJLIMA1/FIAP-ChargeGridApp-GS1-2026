"""Map-first recharge screen and draggable station sheet, using the app's design kit."""
import math

import flet as ft

from ..services import geolocation
from . import design as D
from . import theme
from .components import money
from .explorer_map import ExplorerMap
from .vector_map import overlay


class StationExplorer:
    @staticmethod
    def map_button(icon, callback, tooltip):
        return ft.Container(ft.Icon(icon, size=21, color=theme.TEXT_COLOR), width=42, height=42,
                            bgcolor=theme.CARD, border_radius=13, on_click=callback, ink=False, tooltip=tooltip,
                            shadow=ft.BoxShadow(blur_radius=10, color='#18000000', offset=ft.Offset(0, 2)))

    def __init__(self, app, records, *, search, active, heading, listing, empty, count, pagination,
                 on_select, open_station, route_url, reference=None, location_chip=None):
        self.app, self.open_station, self.route_url = app, open_station, route_url
        self.selected = None
        self.records = records
        self.listing, self.heading = listing, heading
        self.map = ExplorerMap(app, records, on_select, reference=reference)
        self.selection = ft.Container(visible=False, data='selected-station')
        self.nearby = ft.Column([
            ft.Row([heading, ft.Icon(ft.Icons.NEAR_ME_OUTLINED, size=18, color=theme.GRAY_TEXT)],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            count, listing, empty, pagination], spacing=12, scroll=ft.ScrollMode.AUTO, expand=True,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        handle = ft.GestureDetector(
            ft.Container(ft.Container(width=36, height=4, border_radius=2, bgcolor=theme.BORDER_SOFT),
                         height=24, alignment=ft.Alignment(0, 0)),
            on_vertical_drag_start=self.start_sheet, on_vertical_drag_update=self.drag_sheet,
            on_tap=self.toggle_sheet, data='station-sheet-handle')
        self.sheet = overlay(ft.Container(
            ft.Column([handle, ft.Container(ft.Column([self.selection, self.nearby], expand=True, spacing=0,
                                                       horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                                            expand=True, padding=ft.Padding(left=20, right=20, top=2, bottom=14))],
                      spacing=0, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
            bgcolor=theme.CARD,
            border_radius=ft.BorderRadius.only(top_left=28, top_right=28),
            shadow=ft.BoxShadow(blur_radius=24, color='#23000000', offset=ft.Offset(0, -4)),
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS),
            height=260, bottom=0, left=0, right=0, data='station-sheet')
        self.actions = overlay(
            ft.Column([self.map_button(ft.Icons.ADD, self.zoom_in, 'Ampliar mapa'),
                       self.map_button(ft.Icons.REMOVE, self.zoom_out, 'Reduzir mapa'),
                       self.map_button(ft.Icons.CENTER_FOCUS_STRONG, self.map.recenter, 'Mostrar estações no mapa'),
                       *([self.map_button(ft.Icons.MY_LOCATION_ROUNDED, self.locate, 'Usar minha localização')]
                         if geolocation.available(app) else [])], spacing=8),
            right=16, bottom=280, data='map-actions')
        top = ft.Column([search, *([location_chip] if location_chip is not None else []), active], spacing=8,
                        horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        self.control = ft.Column([ft.Container(
            ft.Stack([self.map.viewport,
                      overlay(top, top=18, left=20, right=20),
                      self.actions, self.sheet], expand=True, fit=ft.StackFit.EXPAND),
            expand=True, on_size_change=self.resize, bgcolor=self.map.style['land'],
            data='recharge-explorer')], expand=True, spacing=0)
        self.height = 740
        self.expanded = False
        self.sheet_anchor = None

    def set_height(self, height):
        self.sheet.height = max(min(220, self.height * .45), min(self.height * .8, height))
        self.map.sheet_height = self.sheet.height
        self.actions.bottom = self.sheet.height + 18
        self.map.viewport.credit_bottom = self.sheet.height + 8

    async def resize(self, event):
        if event.height <= 0 or event.width <= 0:
            return
        if self.map.mounted and (round(event.width), round(event.height)) == (self.map.width, self.map.height):
            return
        self.height = event.height
        self.set_height(self.height * (.7 if self.expanded else .45 if self.selected else .34))
        self.app.page.update()
        await self.map.resize(event)

    def start_sheet(self, event):
        self.sheet_anchor = (self.sheet.height, event.global_position.y)

    def drag_sheet(self, event):
        if self.sheet_anchor and getattr(event, 'global_position', None) is not None:
            height, y = self.sheet_anchor
            self.set_height(height - (event.global_position.y - y))
        else:
            self.set_height(self.sheet.height - (event.primary_delta or 0))
        self.expanded = self.sheet.height > self.height * .55
        self.app.page.update()

    def toggle_sheet(self, event=None):
        self.expanded = not self.expanded
        self.set_height(self.height * (.7 if self.expanded else .45 if self.selected else .34))
        self.app.page.update()

    async def zoom_in(self, event=None):
        await self.map.zoom_by(1)

    async def zoom_out(self, event=None):
        await self.map.zoom_by(-1)

    async def locate(self, event=None):
        position = await geolocation.current_position(self.app, ask=True)
        if position is None:
            self.app.notice('Localização indisponível. Busque um endereço no campo acima.')
            return
        self.map.reference = position
        await self.map.recenter()
        self.app.page.update()

    def refresh(self, records):
        self.records = records
        self.map.set_records(records)
        selected = next((item for item in records if item['id'] == self.selected), None)
        if selected:
            self.draw_selection(selected)
        elif self.selected:
            self.close_selection()

    def close_selection(self, event=None):
        self.selected = self.map.selected = None
        self.selection.visible, self.nearby.visible = False, True
        self.map.paint_markers()
        self.set_height(self.height * .34)
        self.app.page.update()

    async def select(self, station_id):
        record = next((item for item in self.records if item['id'] == station_id), None)
        if record is None:
            return
        self.selected = station_id
        self.draw_selection(record)
        self.selection.visible, self.nearby.visible = True, False
        self.set_height(max(320, self.height * .45))
        self.app.page.update()
        await self.map.focus(station_id)
        self.app.page.update()

    def draw_selection(self, record):
        available = record.get('free_points', 0)
        status = f"{available} conector{'es' if available != 1 else ''} livre{'s' if available != 1 else ''}" if available else record.get('status', 'Indisponível')
        status_color = theme.GREEN if available else theme.GRAY_TEXT
        points = record.get('connectors') or []
        kinds = list(dict.fromkeys(str(item.get('connector_type') or '') for item in points if not item.get('retired')))
        powers = []
        for point in points:
            try:
                power = float(point.get('power_kw', 0))
                if math.isfinite(power) and power > 0 and not point.get('retired'):
                    powers.append(power)
            except (TypeError, ValueError):
                pass
        rate = f"{money(record['price'])}/kWh" if record.get('price') is not None else 'Tarifa indisponível'
        power_label = f"Até {max(powers):g} kW" if powers else 'Potência não informada'
        distance = record.get('distance_km')
        title = ft.Row([
            ft.Column([D.txt(record.get('name') or 'Estação', 19, 'bold', max_lines=1,
                             overflow=ft.TextOverflow.ELLIPSIS),
                       D.txt(status, 11, 'medium', status_color)], spacing=5, expand=True),
            D.icon_button_tile(ft.Icons.CLOSE, self.close_selection, size=34, tooltip='Voltar às estações próximas')],
            spacing=10)
        details = ft.Row([
            ft.Column([D.txt(rate, 16, 'bold'), D.txt('Tarifa atual', 10, color=theme.GRAY_TEXT)], spacing=5, expand=True),
            ft.Column([D.txt(power_label, 13, 'semibold'),
                       D.txt(' · '.join(kinds) or 'Sem conectores', 10, color=theme.GRAY_TEXT)], spacing=5)], spacing=12)
        address = record.get('address') or 'Endereço não informado'
        if distance is not None:
            address += f" · {float(distance):.1f} km".replace('.', ',')
        self.selection.content = ft.Column([
            title, D.txt(address, 11, color=theme.GRAY_TEXT, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
            ft.Container(details, padding=ft.Padding.symmetric(vertical=12)),
            ft.Row([
                D.primary_button('Ver estação', self.open_station(record['id']), height=44, size=13, expand=True),
                ft.Container(ft.Icon(ft.Icons.NEAR_ME_OUTLINED, size=21, color=theme.TEXT_COLOR),
                             width=48, height=44, bgcolor=theme.BTN_SECONDARY, border_radius=12,
                             alignment=ft.Alignment(0, 0), url=self.route_url(record), tooltip='Traçar rota')], spacing=10)],
            spacing=10, scroll=ft.ScrollMode.AUTO, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
