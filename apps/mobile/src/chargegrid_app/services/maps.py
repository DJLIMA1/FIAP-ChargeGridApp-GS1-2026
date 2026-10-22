import base64
import io
import math
import tempfile
import threading
import time
import urllib.request
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

import flet as ft

from ..ui import theme

_TILE_SIZE = 256
_MAP_HEIGHT = 210
_TILE_CACHE_DIR = Path(tempfile.gettempdir()) / 'chargegrid-map-tiles-v1'
_TILE_CACHE_AGE = 7 * 24 * 60 * 60
STATION_MAP_RATIO = 563 / 389
# Reference redesign: the finder/detail map is a wide 362 x 158 card.
WIDE_MAP_RATIO = 362 / 158
DETAIL_MAP_RATIO = 357 / 158  # the detail frame is 5 pt wider on the right
# The reference demo map is one tall raster with both stations (pin + callout) baked in;
# each frame shows a different vertical window of it. Value = vertical Alignment of the cover crop.
DEMO_CROPS = {'marginal': 1.46716, 'villa': 0.253828}  # top offset in frame heights (reference frames)
_RASTER_FRAMES = 3.9357  # raster height / frame height in the reference
# Featured-pin colour per wide variant, as a map-style token (resolved per theme).
VARIANT_PIN = {'list': 'pin_list', 'detail': 'pin_detail'}
DEMO_MAP_SRC = {False: '/design/map_villa_lobos.jpg', True: '/design/map_villa_lobos_dark.jpg'}
# The composed map travels to the client as a data URI on every render. JPEG
# q85 is ~70 % smaller than the PNG (≈138 KB vs 461 KB for 720×497 tiles).
MAP_IMAGE_FORMAT = 'JPEG'
_MAP_CACHE_SIZE = 12
_map_cache = OrderedDict()
_map_cache_lock = threading.Lock()
# After a failed tile download, skip the network for a while: an offline
# device then falls back to the schematic map at once instead of waiting.
_NETWORK_RETRY_SECONDS = 60
_network_down_until = 0.0


def map_style(dark=None):
    """ChargeGrid map style for the light or dark variant (``None`` = the app's current theme).

    Every colour comes from the ``MAP_*`` tokens of ``ui/theme.py``: keys are the token names
    without the prefix, lower-case (``land``, ``road``, ``water``, ``pin_list``, ``callout`` ...).
    """
    dark = theme.is_dark() if dark is None else bool(dark)
    palette = theme.DARK if dark else theme.LIGHT
    return {key[4:].lower(): value for key, value in palette.items() if key.startswith('MAP_')}


def _rgb(color):
    """'#RRGGBB' or ARGB '#AARRGGBB' -> (r, g, b)."""
    color = color.lstrip('#')[-6:]
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def _marker_color(glyph, dark):
    style = map_style(dark)
    if glyph == "🚗":
        return _rgb(theme.LIGHT['RED'])
    return _rgb(style['pin'] if glyph == "⚡" else style['pin_off'])

def _fetch_bytes(url, headers=None, timeout=3):
    request = urllib.request.Request(url, headers=headers or {"User-Agent":"ChargeGridApp/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


@lru_cache(maxsize=128)
def _tile_bytes(zoom, x, y):
    # Keep fetched viewport tiles across app restarts for at least seven days.
    # Never prefetch an area or download an offline map from the OSM tile server.
    cached = _TILE_CACHE_DIR / f'{int(zoom)}-{int(x)}-{int(y)}.png'
    try:
        if time.time() - cached.stat().st_mtime < _TILE_CACHE_AGE:
            return cached.read_bytes()
    except OSError:
        pass
    global _network_down_until
    if time.monotonic() < _network_down_until:
        raise OSError('Mapa online indisponível; nova tentativa em instantes.')
    try:
        data = _fetch_bytes(
            f'https://tile.openstreetmap.org/{zoom}/{x}/{y}.png',
            headers={'User-Agent': 'ChargeGridAcademic/1.0'},
            timeout=5,
        )
    except OSError:
        _network_down_until = time.monotonic() + _NETWORK_RETRY_SECONDS
        raise
    try:
        _TILE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(data)
    except OSError:
        pass  # Read-only storage still permits the in-process bounded cache.
    return data

def _haversine_km(lat1, lng1, lat2, lng2):
    """Distância aproximada em km entre duas coordenadas (fórmula de haversine)."""
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1, max(0, a))))

def _schematic_map(center_lat, center_lng, markers_data, height=_MAP_HEIGHT, center_glyph="🚗", dark=None):
    """Mini-mapa esquemático (tipo radar) usado como reserva quando o mapa real
    não consegue carregar (ex: sem internet). Não depende de nenhum controle
    nativo de mapa nem de tiles externos — só Container/Stack/Text — então
    sempre renderiza."""
    canvas_w, canvas_h = 280, height
    style = map_style(dark)
    max_radius_px = min(canvas_w, canvas_h) / 2 - 24
    km_at_edge = 5.0  # distância (km) representada até a borda do mapa
    px_per_km = max_radius_px / km_at_edge

    lat0_rad = math.radians(center_lat)

    def project(lat, lng):
        dx_km = (lng - center_lng) * 111.320 * math.cos(lat0_rad)
        dy_km = (center_lat - lat) * 110.574
        x_px, y_px = dx_km * px_per_km, dy_km * px_per_km
        dist = math.hypot(x_px, y_px)
        if dist > max_radius_px and dist > 0:
            factor = max_radius_px / dist
            x_px, y_px = x_px * factor, y_px * factor
        return canvas_w / 2 + x_px, canvas_h / 2 + y_px

    def pin(x, y, glyph, size=28):
        color = theme.LIGHT['RED'] if glyph == "🚗" else style['pin'] if glyph == "⚡" else style['pin_off']
        icon = ft.Icons.MY_LOCATION if glyph == "🚗" else ft.Icons.BOLT if glyph == "⚡" else ft.Icons.REMOVE
        return ft.Container(
            content=ft.Icon(icon, size=size * 0.58, color=style['pin_ring']),
            width=size, height=size, left=x - size / 2, top=y - size / 2,
            bgcolor=color, border_radius=size / 2,
            border=ft.Border.all(width=2, color=style['pin_ring']),
            alignment=ft.Alignment(0, 0),
        )

    ring_color = style['ring']
    layers = []
    for fraction in (1.0, 2 / 3, 1 / 3):
        d = max_radius_px * 2 * fraction
        layers.append(
            ft.Container(
                width=d, height=d, border_radius=d / 2,
                left=canvas_w / 2 - d / 2, top=canvas_h / 2 - d / 2,
                border=ft.Border.all(width=1, color=ring_color),
            )
        )

    for lat, lng, glyph in markers_data:
        x, y = project(lat, lng)
        layers.append(pin(x, y, glyph, size=26))

    if center_glyph:
        # A referência da busca fica por cima dos postos no centro.
        ux, uy = project(center_lat, center_lng)
        layers.append(pin(ux, uy, center_glyph, size=32))

    return ft.Container(
        content=ft.Stack(layers, width=canvas_w, height=canvas_h),
        height=canvas_h,
        bgcolor=style['land'],
        border_radius=18,
        alignment=ft.Alignment(0, 0),
        padding=0,
    )

def _lonlat_to_px(lat, lng, zoom):
    """Converte lat/lng em coordenadas de pixel no 'mundo' inteiro nesse zoom
    (sistema de tiles padrão usado por OpenStreetMap/Google/etc.)."""
    lat_rad = math.radians(max(-85.05112878, min(85.05112878, lat)))
    n = 2.0 ** zoom
    x = (lng + 180.0) / 360.0 * n * _TILE_SIZE
    y = (1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2.0 * n * _TILE_SIZE
    return x, y

# Luminance ramp of the ChargeGrid map style: (input brightness 0..255, style token). The input
# is each pixel's brightest channel, so OSM's pastel fills keep their order (labels/icons <
# outlines < buildings < land < roads) while all hue noise is dropped. Non-monotonic on purpose
# in the dark variant: land goes charcoal, roads lighter, dark labels turn light.
_RAMP = ((0, 'label'), (110, 'label'), (200, 'edge'), (218, 'block'), (236, 'land'), (244, 'land'),
         (251, 'road'), (255, 'road'))
# Soft thresholds (lo, hi) for the few OSM classes that keep a (brand) tint. Calibrated on the
# standard OSM Carto palette: water #AAD3DF (B-R 53), parks #C8FACC / grass #CDEBB0 / forest
# #ADD19E (G above both R and B by 30+), major roads #F9B29C/#FCD6A4/#F7FABF/#E892A2 (R-B 56+).
# 'water_red' drops saturated blue icons (bus stops, cycleway dashes) that are not water (R 170).
OSM_PROFILE = {'ramp': _RAMP, 'fill': (180, 200), 'water': (22, 40), 'water_red': (110, 140), 'park': (12, 26),
               'major': (32, 50), 'major_value': (200, 220)}


@lru_cache(maxsize=16)
def _ramp_lut(stops):
    """768-entry RGB lookup table interpolating the (level, (r, g, b)) stops."""
    channels = ([], [], [])
    for level in range(256):
        for (start, low), (end, high) in zip(stops, stops[1:]):
            if start <= level <= end:
                t = (level - start) / (end - start) if end > start else 0
                break
        for index, values in enumerate(channels):
            values.append(round(low[index] + (high[index] - low[index]) * t))
    return channels[0] + channels[1] + channels[2]


@lru_cache(maxsize=32)
def _soft_step(low, high):
    """0 below ``low``, 255 above ``high``, linear between: anti-aliased class masks."""
    return [0 if v <= low else 255 if v >= high else round((v - low) * 255 / (high - low)) for v in range(256)]


def _style_tiles(image, dark, profile=None):
    """Recolour raw OSM raster tiles into the ChargeGrid map style (light or dark variant).

    Pure Pillow channel arithmetic and lookup tables (no per-pixel Python loop): the image is
    desaturated through the brand ramp of ``map_style(dark)``, then water, parks and major roads
    are laid back on top with their own tokens through soft masks, so they stay legible.
    """
    from PIL import Image, ImageChops

    style = map_style(dark)
    profile = {**OSM_PROFILE, **(profile or {})}
    red, green, blue = image.convert('RGB').split()
    value = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    stops = tuple((level, _rgb(style[token])) for level, token in profile['ramp'])
    styled = Image.merge('RGB', (value, value, value)).point(_ramp_lut(stops))
    fill = value.point(_soft_step(*profile['fill']))  # area fills only, never dark text/icons
    water = ImageChops.multiply(ImageChops.multiply(ImageChops.subtract(blue, red).point(_soft_step(*profile['water'])),
                                                    red.point(_soft_step(*profile['water_red']))), fill)
    park = ImageChops.multiply(ImageChops.darker(ImageChops.subtract(green, red), ImageChops.subtract(green, blue))
                               .point(_soft_step(*profile['park'])), fill)
    major = ImageChops.multiply(ImageChops.subtract(red, blue).point(_soft_step(*profile['major'])),
                                red.point(_soft_step(*profile['major_value'])))
    box = (0, 0, *styled.size)
    for token, mask in (('water', water), ('park', park), ('road_major', major)):
        styled.paste(_rgb(style[token]), box, mask)
    return styled


def _draw_pin(draw, x, y, glyph, dark, *, scale=1):
    color = _marker_color(glyph, dark)
    style = map_style(dark)
    ring = style['pin_ring']
    radius = (13 if glyph == "🚗" else 12) * scale
    draw.ellipse((x - radius + scale, y - radius + 2 * scale,
                  x + radius + scale, y + radius + 2 * scale), fill=style['pin_shadow'])
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color, outline=ring, width=3 * scale)
    if glyph == "⚡":
        draw.polygon([(x + dx * scale, y + dy * scale)
                      for dx, dy in ((1, -8), (-5, 1), (-1, 1), (-3, 8), (6, -2), (1, -2))], fill=ring)
    elif glyph == "🚗":
        draw.ellipse((x - 4 * scale, y - 4 * scale, x + 4 * scale, y + 4 * scale), fill=ring)
    else:
        draw.rounded_rectangle((x - 5 * scale, y - 2 * scale, x + 5 * scale, y + 2 * scale),
                               radius=2 * scale, fill=ring)


def _draw_station_pin(draw, x, y, radius=26, available=True, color=None, dark=False):
    """Featured station pin and its geographic dot, scaled with the basemap."""
    style = map_style(dark)
    color = (color if available and color else style['pin'] if available else style['pin_off'])
    ring = style['pin_ring']
    edge = max(2, round(radius / 7))
    draw.polygon([(x-radius*.76,y+radius*.55),(x+radius*.76,y+radius*.55),
                  (x,y+radius*1.55)],fill=color,outline=ring,width=edge)
    draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill=color,outline=ring,width=edge)
    dot = radius*.27
    draw.ellipse((x-dot,y+radius*1.9-dot,x+dot,y+radius*1.9+dot),fill=color,outline=ring,width=edge)
    if available:
        draw.polygon([(x+radius*.1,y-radius*.58),(x-radius*.3,y+radius*.06),
                      (x-radius*.02,y+radius*.06),(x-radius*.13,y+radius*.58),
                      (x+radius*.34,y-radius*.15),(x+radius*.04,y-radius*.15)],fill=ring)
    else:
        draw.line([(x-radius*.25,y),(x+radius*.25,y)],fill=ring,width=edge+1)


def _map_frame(backdrop, attribution, *, width=320, callout=None, on_layout=None, ratio=STATION_MAP_RATIO,
               radius=18, callout_pos=(.455, .367, .295), show_credit=True, dark=None):
    """One responsive visual shell for every map, including explicit fallbacks."""
    style = map_style(dark)
    height = width / ratio
    is_osm = 'OpenStreetMap' in attribution
    credit = ft.Container(ft.Text('© OpenStreetMap' if is_osm else attribution,size=11 if ratio == STATION_MAP_RATIO else 7,
                                  color=style['credit_fg']),
                          bgcolor=style['credit_bg'],border_radius=4,
                          padding=ft.Padding.symmetric(horizontal=6,vertical=3),bottom=6,right=8,
                          url='https://www.openstreetmap.org/copyright' if is_osm else None,
                          tooltip='Origem dos dados e licença do mapa' if is_osm else None)
    layers = [ft.Container(backdrop,left=0,right=0,top=0,bottom=0,alignment=ft.Alignment(0,0))]
    if callout is not None:
        layers.append(callout)
    if show_credit:
        layers.append(credit)
    stack = ft.Stack(layers,height=height)
    frame = ft.Container(stack,height=height,bgcolor=style['land'],border_radius=radius,
                         clip_behavior=ft.ClipBehavior.ANTI_ALIAS)

    def layout(map_width):
        map_height = map_width / ratio
        frame.height = stack.height = map_height
        # The source has the same aspect ratio, so resizing never crops a pin.
        backdrop.height = map_height
        if isinstance(backdrop,ft.Image):
            backdrop.width = map_width
        credit.width = None if is_osm else min(260,map_width-16)
        if callout is not None:
            callout.left,callout.top = map_width*callout_pos[0],map_height*callout_pos[1]
            callout.width = min(max(132 if ratio == STATION_MAP_RATIO else 100,map_width*callout_pos[2]),map_width-callout.left-12)
        if on_layout:
            on_layout(map_width)

    layout(width)
    measured_width = width
    async def resize(event):
        nonlocal measured_width
        if event.width <= 0 or abs(event.width-measured_width) < .5:
            return
        measured_width = event.width
        layout(event.width)
        frame.update()
    frame.on_size_change = resize
    return frame


async def station_map_widget(stations, on_select, *, offline=False, width=320, reference=None, variant=None, crop=None,
                             dark=None):
    """Every station map, including demo/detail, uses the shared vector renderer.

    Legacy offline/crop arguments remain accepted by screen callers; they never
    substitute fixed geographic artwork for a real map.
    """
    from ..ui.vector_map import coordinates, create_map, map_placeholder

    records = [record for record in stations if coordinates(record) is not None]
    ratio = DETAIL_MAP_RATIO if variant == 'detail' else WIDE_MAP_RATIO if variant == 'list' else STATION_MAP_RATIO
    if not records:
        return map_placeholder(width / ratio)
    selected = next((record for record in records if record.get('free_points')), records[0])
    viewport = create_map(records, on_select, center=reference or coordinates(selected), zoom=15,
                          dark=dark, height=width / ratio, selected=selected['id'])
    frame = ft.Container(viewport, height=width / ratio, bgcolor=map_style(dark)['land'],
                         border_radius=16, clip_behavior=ft.ClipBehavior.ANTI_ALIAS)
    measured_width = width

    async def resize(event):
        nonlocal measured_width
        if event.width > 0 and abs(event.width - measured_width) > .5:
            measured_width = event.width
            frame.height = viewport.height = event.width / ratio
            frame.update()
    frame.on_size_change = resize
    return frame


def build_map_png(center_lat, center_lng, markers, width=320, height=_MAP_HEIGHT, zoom=15,
                  center_glyph="🚗", dark=False, selected_marker=None, selected_color=None, *, pixel_ratio=1):
    """Baixa os tiles do OpenStreetMap ao redor de (center_lat, center_lng),
    monta um recorte de width x height já centralizado, desenha os
    marcadores por cima e devolve os bytes da imagem pronta (JPEG por padrão,
    ver MAP_IMAGE_FORMAT). Entradas iguais reutilizam a imagem já composta.
    ``pixel_ratio=2`` busca detalhes no próximo zoom, mantendo a área geográfica,
    e entrega PNG sem perda com o dobro de pixels por eixo até o zoom 18.

    Usa diretamente `tile.openstreetmap.org` (o servidor de tiles oficial e
    amplamente usado do projeto) em vez de serviços de terceiros que compõem
    a imagem pronta — esses costumam ser projetos pequenos/hobby e ficam
    fora do ar com frequência (foi o que já aconteceu com
    staticmap.openstreetmap.de). Buscar os tiles crus e montar a imagem nós
    mesmos com Pillow é mais robusto, ao custo de mais uma dependência
    (`pillow`, já usada neste projeto para gerar os ícones da barra inferior).
    """
    # The standard OSM endpoint supplies 256 px tiles, without a retina URL.
    # For dense displays fetch the same geographic viewport one zoom deeper:
    # twice the real detail per axis, rather than enlarging the original bitmap.
    # Never request beyond the provider's maximum zoom (19).
    scale = 2 if pixel_ratio > 1 and zoom < 19 else 1
    image_format = 'PNG' if pixel_ratio > 1 else MAP_IMAGE_FORMAT
    key = (round(center_lat, 7), round(center_lng, 7), tuple(markers), width, height, zoom,
           center_glyph, dark, selected_marker, selected_color, image_format, scale)
    with _map_cache_lock:
        if key in _map_cache:
            # Polls redraw maps whenever a station changes; identical inputs
            # reuse the composed image instead of re-encoding it.
            _map_cache.move_to_end(key)
            return _map_cache[key]
    data = _compose_map(center_lat, center_lng, markers, width * scale, height * scale,
                        zoom + (scale == 2), center_glyph, dark, selected_marker, selected_color,
                        image_format=image_format, pin_scale=scale)
    with _map_cache_lock:
        _map_cache[key] = data
        while len(_map_cache) > _MAP_CACHE_SIZE:
            _map_cache.popitem(last=False)
    return data


def _fetch_tiles(zoom, coordinates):
    """Download the viewport's tiles concurrently (not one after another)."""
    def fetch(coordinate):
        try:
            return coordinate, _tile_bytes(zoom, *coordinate)
        except (OSError, ValueError):
            return coordinate, None
    if not coordinates:
        return {}
    with ThreadPoolExecutor(max_workers=min(6, len(coordinates))) as pool:
        return dict(pool.map(fetch, coordinates))


def map_data_uri(data):
    kind = 'jpeg' if data[:3] == b'\xff\xd8\xff' else 'png'
    return f'data:image/{kind};base64,' + base64.b64encode(data).decode()


def _compose_map(center_lat, center_lng, markers, width, height, zoom, center_glyph, dark, selected_marker,
                 selected_color=None, *, image_format=None, pin_scale=1):
    from PIL import Image, ImageDraw  # import local: se o Pillow não estiver

    cx, cy = _lonlat_to_px(center_lat, center_lng, zoom)
    left, top = cx - width / 2, cy - height / 2

    tile_x_min, tile_x_max = int(left // _TILE_SIZE), int((left + width - 1) // _TILE_SIZE)
    tile_y_min, tile_y_max = int(top // _TILE_SIZE), int((top + height - 1) // _TILE_SIZE)
    n_tiles = 2 ** zoom

    canvas = Image.new("RGB", ((tile_x_max - tile_x_min + 1) * _TILE_SIZE,
                                (tile_y_max - tile_y_min + 1) * _TILE_SIZE), (245, 245, 245))

    wanted = [(tx % n_tiles, ty) for tx in range(tile_x_min, tile_x_max + 1)
              for ty in range(tile_y_min, tile_y_max + 1) if 0 <= ty < n_tiles]
    tiles = _fetch_tiles(zoom, sorted(set(wanted)))
    got_any_tile = False
    for tx in range(tile_x_min, tile_x_max + 1):
        for ty in range(tile_y_min, tile_y_max + 1):
            tile_bytes = tiles.get((tx % n_tiles, ty))
            if tile_bytes is None:
                continue  # deixa essa região em cinza-claro se uma tile específica falhar
            try:
                tile_img = Image.open(io.BytesIO(tile_bytes)).convert("RGB")
            except (OSError, ValueError):
                continue
            canvas.paste(tile_img, ((tx - tile_x_min) * _TILE_SIZE, (ty - tile_y_min) * _TILE_SIZE))
            got_any_tile = True

    if not got_any_tile:
        raise RuntimeError("Nenhuma tile do mapa pôde ser baixada.")

    offset_x, offset_y = left - tile_x_min * _TILE_SIZE, top - tile_y_min * _TILE_SIZE
    cropped = canvas.crop((int(offset_x), int(offset_y), int(offset_x) + width, int(offset_y) + height))

    cropped = _style_tiles(cropped, dark)
    draw = ImageDraw.Draw(cropped)
    for lat, lng, glyph in markers:
        px, py = _lonlat_to_px(lat, lng, zoom)
        x, y = px - left, py - top
        if -14 <= x <= width + 14 and -14 <= y <= height + 14:
            if selected_marker == (lat,lng):
                _draw_station_pin(draw,x,y,radius=width*.038,available=glyph == '⚡',color=selected_color,dark=dark)
            elif glyph != '🚗':
                _draw_station_pin(draw,x,y,radius=width*.025,available=glyph == '⚡',dark=dark)
            else:
                _draw_pin(draw, x, y, glyph, dark, scale=pin_scale)
    if center_glyph:
        _draw_pin(draw, width / 2, height / 2, center_glyph, dark, scale=pin_scale)

    buf = io.BytesIO()
    if (image_format or MAP_IMAGE_FORMAT) == 'JPEG':
        cropped.save(buf, format='JPEG', quality=85, optimize=True)
    else:
        cropped.save(buf, format='PNG')
    return buf.getvalue()

async def map_widget(lat, lng, markers, center_glyph="🚗", *, offline=False, width=320, dark=None):
    """Generic map uses the same vector component as station maps."""
    from ..ui.vector_map import create_map

    records = [{'id': str(index), 'name': 'Estação de recarga', 'latitude': point_lat, 'longitude': point_lng,
                'status': 'Disponível' if glyph == '⚡' else 'Indisponível'}
               for index, (point_lat, point_lng, glyph) in enumerate(markers) if glyph != '🚗']
    return ft.Container(create_map(records, center=(lat, lng), width=width, height=_MAP_HEIGHT, dark=dark),
                        height=_MAP_HEIGHT, border_radius=16, clip_behavior=ft.ClipBehavior.ANTI_ALIAS)


# Dark variant of the reference demo raster (assets/design/map_villa_lobos.jpg, both stations' pins
# and callouts baked in). Its palette differs from OSM Carto (land #E1E2E6, water #61C4F7, highway
# lanes #A5BAC8), hence its own thresholds. Pins and callouts are kept from the source untouched.
DEMO_RASTER_PROFILE = {'ramp': ((0, 'label'), (120, 'label'), (196, 'edge'), (214, 'block'), (224, 'land'),
                                (242, 'land'), (249, 'road'), (255, 'road')),
                       'water': (50, 90), 'water_red': (0, 1), 'major': (60, 80)}
# (x0, y0, x1, y1, corner radius) of each baked callout card, and (x, y, radius) of each pin head +
# tip + geographic dot, in source pixels (941 x 1672).
DEMO_RASTER_CARDS = ((421, 236, 692, 378, 20), (462, 757, 765, 903, 20))
DEMO_RASTER_PINS = ((379, 285, 36, 327, 345, 13), (415, 802, 40, 852, 871, 13))


def render_dark_demo_raster(source, target):
    """Write the dark-theme demo raster from the light reference one (development step, offline).

        PYTHONPATH=src:packages python -c "from chargegrid_app.services.maps import render_dark_demo_raster as r;
            r('assets/design/map_villa_lobos.jpg', 'assets/design/map_villa_lobos_dark.jpg')"
    """
    from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

    original = Image.open(source).convert('RGB')
    styled = _style_tiles(original, True, DEMO_RASTER_PROFILE)
    keep = Image.new('L', original.size, 0)
    draw = ImageDraw.Draw(keep)
    for x0, y0, x1, y1, radius in DEMO_RASTER_CARDS:
        draw.rounded_rectangle((x0, y0, x1, y1), radius=radius, fill=255)
    pins = []
    for x, y, radius, tip_y, dot_y, dot in DEMO_RASTER_PINS:
        pin = Image.new('L', original.size, 0)
        shape = ImageDraw.Draw(pin)
        shape.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)
        shape.polygon([(x - radius * .72, y + radius * .5), (x + radius * .72, y + radius * .5), (x, tip_y)], fill=255)
        shape.ellipse((x - dot, dot_y - dot, x + dot, dot_y + dot), fill=255)
        pins.append(pin)
        keep = ImageChops.lighter(keep, pin)
    styled.paste(original, (0, 0), keep.filter(ImageFilter.GaussianBlur(1.2)))
    # The detail (Villa Lobos) pin is navy in the reference; on charcoal it takes the dark
    # variant's lighter brand blue, like the live map's featured pin.
    red, _, blue = original.split()
    value = ImageOps.grayscale(original)
    navy = ImageChops.multiply(ImageChops.subtract(blue, red).point(_soft_step(12, 32)),
                               ImageOps.invert(value).point(_soft_step(115, 150)))
    styled.paste(_rgb(map_style(True)['pin_detail']), (0, 0, *styled.size), ImageChops.multiply(navy, pins[0]))
    styled.save(target, format='JPEG', quality=85, optimize=True)
    return target
