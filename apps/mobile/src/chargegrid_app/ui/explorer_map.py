"""Recharge camera backed by the shared, on-device OpenFreeMap vector renderer."""
import json
import math

from ..services import maps
from . import theme
from .vector_map import coordinates, create_map, map_records

MIN_ZOOM, MAX_ZOOM = 3, 20


def unproject(x, y, zoom):
    world = 256 * 2 ** zoom
    y = max(0, min(world, y))
    return (math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / world)))),
            (x / world * 360) % 360 - 180)


class ExplorerMap:
    def __init__(self, app, records, on_select, *, reference=None, on_move=None):
        self.app, self.records, self.on_select, self.on_move = app, records, on_select, on_move
        self.style = maps.map_style(theme.is_dark())
        self.width, self.height, self.sheet_height = 400, 740, 260
        self.selected = None
        self.center, self.zoom = reference or (-23.5505, -46.6333), 14
        self.reference = reference
        self.mounted = self.loaded = False
        self.revision = 0
        self.generation = getattr(app, 'generation', None)
        self.viewport = create_map(records, self.select, center=self.center, zoom=self.zoom,
                                   on_camera=self.camera_changed, on_ready=self.ready)
        self.viewport.expand = True
        self.control = self.viewport
        self.fit(reference, initial=True)
        self.sync_camera()

    def current(self):
        return not getattr(self.app, 'closed', False) and getattr(self.app, 'generation', None) == self.generation

    def select(self, station_id):
        return self.on_select(station_id)

    def fit(self, reference=None, *, initial=False):
        points = [point for item in self.records if (point := coordinates(item))]
        if initial:
            points = points[:3]
        if reference:
            self.center, self.zoom = reference, 14
        elif points:
            for zoom in range(16, (13 if initial else MIN_ZOOM) - 1, -1):
                pixels = [maps._lonlat_to_px(*point, zoom) for point in points]
                xs, ys = zip(*pixels)
                if max(xs) - min(xs) <= max(100, self.width - 110) and max(ys) - min(ys) <= max(120, self.height - self.sheet_height - 200):
                    break
            self.zoom = zoom
            self.center = unproject((min(xs) + max(xs)) / 2,
                                    (min(ys) + max(ys)) / 2 + (self.sheet_height - 100) / 2, zoom)
        self.paint_markers()

    def paint_markers(self):
        self.viewport.markers = map_records(self.records)
        self.viewport.selected = self.selected
        self.viewport.credit_bottom = self.sheet_height + 8

    def set_records(self, records):
        self.records = records
        if self.selected not in {item['id'] for item in records}:
            self.selected = None
        self.paint_markers()

    def sync_camera(self):
        self.revision += 1
        self.viewport.latitude, self.viewport.longitude = self.center
        # MapLibre uses a 512 px world at zoom zero; the app's Mercator math uses 256.
        self.viewport.zoom = self.zoom - 1
        self.viewport.camera_revision = self.revision

    async def camera_changed(self, event):
        if not self.current():
            return
        try:
            data = json.loads(event.data)
            point = coordinates(data)
            zoom = float(data['zoom']) + 1
            if point is None or not math.isfinite(zoom) or not MIN_ZOOM <= zoom <= MAX_ZOOM + 1:
                return
        except (KeyError, TypeError, ValueError):
            return
        self.center, self.zoom = point, zoom
        if self.on_move:
            self.on_move()
        self.app.page.update()

    async def ready(self, event=None):
        if self.current():
            self.loaded = True

    async def resize(self, event):
        width, height = round(event.width), round(event.height)
        if width <= 0 or height <= 0 or (self.mounted and (width, height) == (self.width, self.height)):
            return
        first = not self.mounted
        self.mounted = True
        self.width, self.height = width, height
        if first:
            self.fit(self.reference, initial=True)
            self.sync_camera()
        self.paint_markers()
        if self.current():
            self.app.page.update()

    async def zoom_by(self, delta):
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, self.zoom + delta))
        self.sync_camera()
        if self.on_move:
            self.on_move()
        self.app.page.update()

    async def recenter(self, event=None):
        self.fit(self.reference)
        self.sync_camera()
        self.app.page.update()

    async def focus(self, station_id):
        self.selected = station_id
        record = next((item for item in self.records if item['id'] == station_id), None)
        point = coordinates(record or {})
        if point:
            self.zoom = max(self.zoom, 15)
            x, y = maps._lonlat_to_px(*point, self.zoom)
            self.center = unproject(x, y + (self.sheet_height - 100) / 2, self.zoom)
            self.sync_camera()
        self.paint_markers()
        self.app.page.update()
