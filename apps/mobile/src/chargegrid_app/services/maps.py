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

from chargegrid_core.formatting import brl

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


def _draw_pin(draw, x, y, glyph, dark):
    color = _marker_color(glyph, dark)
    style = map_style(dark)
    ring = style['pin_ring']
    radius = 13 if glyph == "🚗" else 12
    draw.ellipse((x - radius + 1, y - radius + 2, x + radius + 1, y + radius + 2), fill=style['pin_shadow'])
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color, outline=ring, width=3)
    if glyph == "⚡":
        draw.polygon([(x + 1, y - 8), (x - 5, y + 1), (x - 1, y + 1),
                      (x - 3, y + 8), (x + 6, y - 2), (x + 1, y - 2)], fill=ring)
    elif glyph == "🚗":
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=ring)
    else:
        draw.rounded_rectangle((x - 5, y - 2, x + 5, y + 2), radius=2, fill=ring)


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
    """Map with an honest selected-station callout, no inferred GPS/distance.

    ``variant`` 'list' (green pin, "Disponível" chip) or 'detail' (navy pin, "N vagas" chip)
    switches to the wide reference card; ``None`` keeps the original home map.
    ``dark`` picks the map style variant; ``None`` follows the app's current theme.
    """
    import asyncio

    dark = theme.is_dark() if dark is None else bool(dark)
    style = map_style(dark)

    wide = variant in VARIANT_PIN
    ratio = (DETAIL_MAP_RATIO if variant == 'detail' else WIDE_MAP_RATIO) if wide else STATION_MAP_RATIO
    height = width / ratio

    positioned = []
    for station in stations:
        try:
            lat,lng = float(station['latitude']),float(station['longitude'])
            if not math.isfinite(lat) or not math.isfinite(lng) or not -90 <= lat <= 90 or not -180 <= lng <= 180:
                continue
        except (KeyError,ValueError,TypeError):
            continue
        positioned.append((station,lat,lng))
    if not positioned:
        text = 'Nenhum posto encontrado. Abra a lista para buscar.' if not stations else 'Os postos desta lista ainda não têm coordenadas válidas para o mapa.'
        return ft.Container(ft.Column([ft.Icon(ft.Icons.MAP_OUTLINED,size=32,color=theme.GRAY_TEXT),
                                        ft.Text(text,size=13,color=theme.GRAY_TEXT,text_align=ft.TextAlign.CENTER)],
                                       spacing=10,horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                            height=180,bgcolor=theme.WHITE,border_radius=12,padding=24,alignment=ft.Alignment(0,0))
    if offline and crop in DEMO_CROPS and variant in VARIANT_PIN:
        # Demo: the raster already carries the pin and callout, so show just the matching window.
        keyword = 'marginal' if crop == 'marginal' else 'villa lobos'
        station_id = next((item['id'] for item,_,_ in positioned if keyword in str(item.get('name','')).lower()),
                          positioned[0][0]['id'])
        raster = ft.Image(src=DEMO_MAP_SRC[dark],fit=ft.BoxFit.FILL,left=0,
                          semantics_label='Mapa da demonstração com o posto selecionado.')
        backdrop = ft.Stack([raster],width=width,height=height)

        def place(map_width):
            frame_height = map_width / ratio
            raster.width = map_width
            raster.height = frame_height * _RASTER_FRAMES
            raster.top = -frame_height * DEMO_CROPS[crop]
            backdrop.width = map_width
        place(width)
        frame = _map_frame(backdrop,'Demo',width=width,ratio=ratio,radius=16,show_credit=False,on_layout=place,dark=dark)
        frame.on_click = on_select(station_id)
        frame.ink = True
        return frame
    selected,lat,lng = next((item for item in positioned if item[0]['free_points']),positioned[0])
    markers = [(item_lat,item_lng,'⚡' if item['free_points'] else '⛔') for item,item_lat,item_lng in positioned]
    if reference is not None:
        markers.append((*reference,'🚗'))
    attribution = '© OpenStreetMap contributors'
    if offline:
        # This bundled vector extract is specific to the public demo fixture.
        # Never place another location on its fixed geographic marker.
        if abs(lat-(-23.5467)) < 0.000001 and abs(lng-(-46.7224)) < 0.000001 and reference is None and selected['free_points']:
            backdrop = ft.Image(src=DEMO_MAP_SRC[dark],width=width,height=height,fit=ft.BoxFit.COVER,
                                semantics_label='Mapa do Parque Villa-Lobos, com o posto de exemplo da demonstração.')
            attribution = 'Demo · © OpenStreetMap contributors'
        else:
            backdrop = _schematic_map(lat,lng,markers,height=height,center_glyph=None,dark=dark)
            attribution = 'Mapa esquemático da demonstração · sem acesso à rede'
    else:
        try:
            # Reframe the real geography so the featured pin sits beside the
            # callout. The station coordinates remain the source of truth.
            source_width, source_height = 720, round(720 / ratio)
            selected_x,selected_y = _lonlat_to_px(lat,lng,16)
            world_size = 2**16 * _TILE_SIZE
            center_x = selected_x + source_width*(0.06 if wide else 0.1)
            center_y = selected_y + source_height*(-0.08 if wide else 0.07)
            center_lng = center_x/world_size*360-180
            center_lat = math.degrees(math.atan(math.sinh(math.pi*(1-2*center_y/world_size))))
            data = await asyncio.wait_for(asyncio.to_thread(build_map_png,center_lat,center_lng,markers,
                                                            width=source_width,height=source_height,zoom=16,
                                                            center_glyph=None,dark=dark,selected_marker=(lat,lng),
                                                            **({'selected_color':style[VARIANT_PIN[variant]]} if wide else {})),
                                         timeout=7)
            backdrop = ft.Image(src=map_data_uri(data),
                                width=width,height=height,fit=ft.BoxFit.COVER,semantics_label='Mapa dos postos, centrado em '+selected.get('name','posto'))
        except (ImportError,OSError,RuntimeError,ValueError,TimeoutError):
            backdrop = _schematic_map(lat,lng,markers,height=height,center_glyph=None,dark=dark)
            attribution = 'Visão aproximada · mapa online indisponível'
    count = selected['free_points']
    status = f"{count} {'vaga' if count == 1 else 'vagas'}" if count else selected['status']
    if variant == 'list' and count:
        status = 'Disponível'
    name_text = ft.Text(selected.get('name') or 'Posto sem nome',size=9.3 if wide else 11.5,weight=ft.FontWeight.BOLD,
                        font_family='InterBold' if wide else 'BarlowSemiBold',color=style['callout_text'],
                        max_lines=2,overflow=ft.TextOverflow.ELLIPSIS)
    chip = 'chip_list' if variant == 'list' else 'chip_free'
    chip_bg,chip_fg = (style[chip],style[chip+'_fg']) if count else (style['chip_off'],style['chip_off_fg'])
    status_text = ft.Text(status,size=7 if wide else 11,weight=ft.FontWeight.BOLD if not wide else None,
                          font_family='InterMedium' if wide else None,color=chip_fg)
    badge = ft.Container(status_text,bgcolor=chip_bg,
                         border_radius=12,padding=ft.Padding.symmetric(horizontal=8,vertical=1 if wide else 2))
    details = [name_text,ft.Row([badge],spacing=0)]
    price = selected.get('price')
    distance = selected.get('distance_km')
    if wide:
        parts = []
        if distance is not None:
            parts.append(f"{distance:.1f}".replace('.',',')+' km')
        if price is not None:
            parts.append(f"{brl(price)}/kWh")
        if parts:
            details.append(ft.Text(' - '.join(parts),size=8.2,font_family='Inter',color=style['callout_muted']))
    elif price is not None:
        details.append(ft.Text(f"Desde {brl(price)}/kWh",size=11,color=style['callout_muted']))
    selected_action = on_select(selected['id'])
    callout = ft.Container(ft.Semantics(
                           content=ft.Column(details,spacing=3 if wide else 4,horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                           container=True,button=True,label='Ver pontos em '+(selected.get('name') or 'posto'),
                           on_tap=selected_action),
                           bgcolor=style['callout'],border_radius=10 if wide else 12,padding=ft.Padding(left=8,right=6,top=9,bottom=9) if wide else 10,
                           shadow=ft.BoxShadow(blur_radius=16,spread_radius=1,color=style['callout_shadow'],offset=ft.Offset(0,3)),
                           on_click=selected_action,ink=True)
    def typography(map_width):
        if not wide:
            name_text.size = max(13,min(16,map_width*16/563))
    return _map_frame(backdrop,attribution,width=width,callout=callout,on_layout=typography,ratio=ratio,dark=dark,
                      radius=16 if wide else 18,callout_pos=(.494,.32,.318) if variant == 'list' else (.5,.33,.285) if wide else (.455,.367,.295))


def build_map_png(center_lat, center_lng, markers, width=320, height=_MAP_HEIGHT, zoom=15,
                  center_glyph="🚗", dark=False, selected_marker=None, selected_color=None):
    """Baixa os tiles do OpenStreetMap ao redor de (center_lat, center_lng),
    monta um recorte de width x height já centralizado, desenha os
    marcadores por cima e devolve os bytes da imagem pronta (JPEG por padrão,
    ver MAP_IMAGE_FORMAT). Entradas iguais reutilizam a imagem já composta.

    Usa diretamente `tile.openstreetmap.org` (o servidor de tiles oficial e
    amplamente usado do projeto) em vez de serviços de terceiros que compõem
    a imagem pronta — esses costumam ser projetos pequenos/hobby e ficam
    fora do ar com frequência (foi o que já aconteceu com
    staticmap.openstreetmap.de). Buscar os tiles crus e montar a imagem nós
    mesmos com Pillow é mais robusto, ao custo de mais uma dependência
    (`pillow`, já usada neste projeto para gerar os ícones da barra inferior).
    """
    key = (round(center_lat, 7), round(center_lng, 7), tuple(markers), width, height, zoom,
           center_glyph, dark, selected_marker, selected_color, MAP_IMAGE_FORMAT)
    with _map_cache_lock:
        if key in _map_cache:
            # Polls redraw maps whenever a station changes; identical inputs
            # reuse the composed image instead of re-encoding it.
            _map_cache.move_to_end(key)
            return _map_cache[key]
    data = _compose_map(center_lat, center_lng, markers, width, height, zoom, center_glyph, dark, selected_marker, selected_color)
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


def _compose_map(center_lat, center_lng, markers, width, height, zoom, center_glyph, dark, selected_marker, selected_color=None):
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
                _draw_pin(draw, x, y, glyph, dark)
    if center_glyph:
        _draw_pin(draw, width / 2, height / 2, center_glyph, dark)

    buf = io.BytesIO()
    if MAP_IMAGE_FORMAT == 'JPEG':
        cropped.save(buf, format='JPEG', quality=85, optimize=True)
    else:
        cropped.save(buf, format='PNG')
    return buf.getvalue()

async def map_widget(lat, lng, markers, center_glyph="🚗", *, offline=False, width=320, dark=None):
    import asyncio
    dark = theme.is_dark() if dark is None else bool(dark)
    style = map_style(dark)
    height = width / STATION_MAP_RATIO
    if offline:
        preview = _schematic_map(lat, lng, markers, height=height,center_glyph=center_glyph,dark=dark)
        attribution = "Mapa esquemático da demonstração · sem acesso à rede"
    else:
        try:
            data = await asyncio.wait_for(
                asyncio.to_thread(build_map_png, lat, lng, markers,
                                  width=720,height=round(720/STATION_MAP_RATIO),
                                  center_glyph=center_glyph, dark=dark), timeout=7)
            preview = ft.Image(src=map_data_uri(data),
                               width=width,height=height,fit=ft.BoxFit.COVER)
            attribution = "© OpenStreetMap contributors"
        except (ImportError, OSError, RuntimeError, ValueError, TimeoutError):
            preview = _schematic_map(lat, lng, markers,height=height,center_glyph=center_glyph,dark=dark)
            attribution = "Visão aproximada · mapa online indisponível"

    def legend_item(label, color, icon):
        return ft.Row([
            ft.Icon(icon, size=15, color=color),
            ft.Text(label, size=11, color=theme.GRAY_TEXT),
        ], spacing=4, tight=True)

    legend = [legend_item("Livre", style['pin'], ft.Icons.BOLT),
              legend_item("Indisponível", style['pin_off'], ft.Icons.REMOVE)]
    if center_glyph:
        legend.insert(0, legend_item("Busca", theme.RED, ft.Icons.MY_LOCATION))
    return ft.Column([_map_frame(preview,attribution,width=width,dark=dark),
                      ft.Row(legend,wrap=True,spacing=12,run_spacing=4)],
                     spacing=10,horizontal_alignment=ft.CrossAxisAlignment.STRETCH)


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
