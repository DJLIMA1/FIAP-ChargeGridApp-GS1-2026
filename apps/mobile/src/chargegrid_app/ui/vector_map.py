"""Shared OpenFreeMap/MapLibre entry point for every map in the app.

Styles are bundled JSON, not screenshots. Tiles, labels, touch gestures and
geographic projection are rendered by MapLibre on the device.
"""
import json
import math
from functools import lru_cache
from pathlib import Path

import flet as ft
from chargegrid_map import MapOverlay, VectorMap

from . import theme

STYLE_DIR = Path(__file__).resolve().parents[3] / 'assets' / 'maps' / 'styles'


def coordinates(record):
    try:
        lat, lng = float(record['latitude']), float(record['longitude'])
        if math.isfinite(lat) and math.isfinite(lng) and -85.05112878 <= lat <= 85.05112878 and -180 <= lng <= 180:
            return lat, lng
    except (KeyError, TypeError, ValueError):
        pass
    return None


@lru_cache(maxsize=2)
def vector_style(dark):
    data = json.loads((STYLE_DIR / ('dark.json' if dark else 'liberty.json')).read_text())
    data['name'] = 'ChargeGrid Dark' if dark else 'ChargeGrid Light'
    data['sources']['openmaptiles']['attribution'] = (
        '<a href="https://openfreemap.org/">OpenFreeMap</a> · '
        '<a href="https://openmaptiles.org/">© OpenMapTiles</a> · '
        '<a href="https://www.openstreetmap.org/copyright">© OpenStreetMap</a>')
    # Keep the provider's native label antialiasing and zoom-dependent sizes.
    # Tints are applied to geographic layers, never to an already rasterized image.
    colors = {'water': '#284B60' if dark else '#95C9DE',
              'park': '#2D493D' if dark else '#B8D5B8'}
    for layer in data['layers']:
        identity = layer['id'].lower()
        paint, layout = layer.setdefault('paint', {}), layer.setdefault('layout', {})
        if identity.startswith('poi') or identity == 'building-3d':
            layout['visibility'] = 'none'
        if layer['type'] == 'background':
            paint['background-color'] = '#1D242A' if dark else '#E4ECEE'
        if identity == 'landuse_residential':
            paint['fill-color'] = '#202A31' if dark else '#DFE7E9'
        if identity == 'building':
            paint['fill-color'] = '#2C3842' if dark else '#D0DBDF'
            paint['fill-outline-color'] = '#34434E' if dark else '#BFCDD2'
        if layer['type'] == 'fill':
            paint['fill-antialias'] = True
        if identity in ('landuse_park', 'landcover_wood', 'landcover_grass'):
            paint['fill-color'] = colors['park']
        if layer['type'] == 'fill' and identity in ('water', 'park'):
            paint['fill-color'] = colors[identity]
        if layer['type'] == 'line' and identity.startswith(('road_', 'bridge_', 'tunnel_')) and 'rail' not in identity:
            paint['line-color'] = ('#354650' if dark else '#BACBD0') if 'casing' in identity else ('#5B6F7C' if dark else '#FFFFFF')
        if dark and layer['type'] == 'line' and identity.startswith('highway_'):
            paint['line-color'] = '#2A3842' if 'casing' in identity else '#657C8B' if 'major' in identity or 'motorway' in identity else '#3A4C58'
            if identity in ('highway_minor', 'highway_path'):
                layer['minzoom'] = max(13, layer.get('minzoom', 0))
                paint['line-opacity'] = .65
        if layer['type'] == 'symbol' and 'text-field' in layout:
            paint['text-color'] = '#DFE8EF' if dark else '#344C59'
            paint['text-halo-color'] = '#1D242A' if dark else '#F9FCFD'
            paint['text-halo-width'] = 1
            layout['text-font'] = ['Noto Sans Regular']
            layout['text-transform'] = 'none'
            size = layout.get('text-size')
            if isinstance(size, (int, float)):
                layout['text-size'] = max(11.5, size)
            elif isinstance(size, dict) and 'stops' in size:
                size['stops'] = [[zoom, max(11.5, value)] for zoom, value in size['stops']]
            elif isinstance(size, list) and size[0] == 'interpolate':
                for index in range(4, len(size), 2):
                    if isinstance(size[index], (int, float)):
                        size[index] = max(11.5, size[index])
    return json.dumps(data, ensure_ascii=False, separators=(',', ':'))


def map_records(records):
    result = []
    for record in records:
        if (point := coordinates(record)) is not None:
            marker = {'id': str(record['id']), 'name': record.get('name') or 'Estação de recarga',
                      'latitude': point[0], 'longitude': point[1], 'status': record.get('status', '')}
            result.append(marker)
    return result


def create_map(records=(), on_select=None, *, center=None, zoom=14, dark=None,
               width=None, height=None, interactive=True, selected=None, credit_bottom=8, on_camera=None, on_ready=None):
    records = map_records(records)
    center = center or ((records[0]['latitude'], records[0]['longitude']) if records else (-23.5505, -46.6333))

    async def select(event):
        if on_select and any(record['id'] == event.data for record in viewport.markers):
            action = on_select(event.data)
            if callable(action):
                result = action(event)
                if hasattr(result, '__await__'):
                    await result

    viewport = VectorMap(latitude=center[0], longitude=center[1], zoom=zoom - 1,
                     style_json=vector_style(theme.is_dark() if dark is None else bool(dark)),
                     markers=records, selected=selected, on_select=select if on_select else None,
                     width=width, height=height, interactive=interactive, credit_bottom=credit_bottom,
                     on_camera=on_camera, on_ready=on_ready, data='openfreemap-vector-map')
    return viewport


def overlay(content, **layout):
    """Keep floating Flet controls clickable above a web platform view."""
    return MapOverlay(content=content, **layout)


def map_placeholder(height=180, text='Os postos ainda não têm coordenadas válidas para o mapa.'):
    return ft.Container(ft.Column([
        ft.Icon(ft.Icons.MAP_OUTLINED, size=30, color=theme.GRAY_TEXT),
        ft.Text(text, size=13, color=theme.GRAY_TEXT, text_align=ft.TextAlign.CENTER)],
        spacing=10, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        height=height, bgcolor=theme.CARD, border_radius=16, padding=24, alignment=ft.Alignment(0, 0))
