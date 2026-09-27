import io
import math
import tempfile
import time
import urllib.request
from functools import lru_cache
from pathlib import Path

import flet as ft

from ..ui import theme

_TILE_SIZE = 256
_MAP_HEIGHT = 210
_TILE_CACHE_DIR = Path(tempfile.gettempdir()) / 'chargegrid-map-tiles-v1'
_TILE_CACHE_AGE = 7 * 24 * 60 * 60
STATION_MAP_RATIO = 563 / 389


def _marker_color(glyph, dark):
    if glyph == "🚗":
        return (215, 43, 50)
    if glyph == "⚡":
        return (35, 57, 73)
    return (88, 98, 111)

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
    data = _fetch_bytes(
        f'https://tile.openstreetmap.org/{zoom}/{x}/{y}.png',
        headers={'User-Agent': 'ChargeGridAcademic/1.0'},
        timeout=5,
    )
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

def _schematic_map(center_lat, center_lng, markers_data, height=_MAP_HEIGHT, center_glyph="🚗"):
    """Mini-mapa esquemático (tipo radar) usado como reserva quando o mapa real
    não consegue carregar (ex: sem internet). Não depende de nenhum controle
    nativo de mapa nem de tiles externos — só Container/Stack/Text — então
    sempre renderiza."""
    canvas_w, canvas_h = 280, height
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
        color = theme.RED if glyph == "🚗" else '#233949' if glyph == "⚡" else theme.SLATE
        icon = ft.Icons.MY_LOCATION if glyph == "🚗" else ft.Icons.BOLT if glyph == "⚡" else ft.Icons.REMOVE
        return ft.Container(
            content=ft.Icon(icon, size=size * 0.58, color="#FFFFFF"),
            width=size, height=size, left=x - size / 2, top=y - size / 2,
            bgcolor=color, border_radius=size / 2,
            border=ft.Border.all(width=2, color="#FFFFFF"),
            alignment=ft.Alignment(0, 0),
        )

    ring_color = '#CED8DE'
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
        bgcolor='#E9ECEE',
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

def _style_tiles(image, dark):
    from PIL import Image, ImageEnhance, ImageOps

    if dark:
        # Keep the streets legible while matching the app's charcoal surfaces.
        gray = ImageOps.invert(ImageOps.grayscale(image))
        gray = ImageEnhance.Contrast(gray).enhance(0.8)
        return ImageOps.colorize(gray, "#1D2326", "#A3AEB2").convert("RGB")
    muted = ImageEnhance.Color(image).enhance(0.85)
    return Image.blend(muted, Image.new("RGB", image.size, "#F2F2F3"), 0.10)


def _draw_pin(draw, x, y, glyph, dark):
    color = _marker_color(glyph, dark)
    radius = 13 if glyph == "🚗" else 12
    draw.ellipse((x - radius + 1, y - radius + 2, x + radius + 1, y + radius + 2), fill=(30, 35, 39))
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color, outline="white", width=3)
    if glyph == "⚡":
        draw.polygon([(x + 1, y - 8), (x - 5, y + 1), (x - 1, y + 1),
                      (x - 3, y + 8), (x + 6, y - 2), (x + 1, y - 2)], fill="white")
    elif glyph == "🚗":
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill="white")
    else:
        draw.rounded_rectangle((x - 5, y - 2, x + 5, y + 2), radius=2, fill="white")


def _draw_station_pin(draw, x, y, radius=26, available=True):
    """Featured navy pin and its geographic dot, scaled with the basemap."""
    color = '#233949' if available else '#58626F'
    edge = max(2, round(radius / 7))
    draw.polygon([(x-radius*.76,y+radius*.55),(x+radius*.76,y+radius*.55),
                  (x,y+radius*1.55)],fill=color,outline='white',width=edge)
    draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill=color,outline='white',width=edge)
    dot = radius*.27
    draw.ellipse((x-dot,y+radius*1.9-dot,x+dot,y+radius*1.9+dot),fill=color,outline='white',width=edge)
    if available:
        draw.polygon([(x+radius*.1,y-radius*.58),(x-radius*.3,y+radius*.06),
                      (x-radius*.02,y+radius*.06),(x-radius*.13,y+radius*.58),
                      (x+radius*.34,y-radius*.15),(x+radius*.04,y-radius*.15)],fill='white')
    else:
        draw.line([(x-radius*.25,y),(x+radius*.25,y)],fill='white',width=edge+1)


def _map_frame(backdrop, attribution, *, width=320, callout=None, on_layout=None):
    """One responsive visual shell for every map, including explicit fallbacks."""
    height = width / STATION_MAP_RATIO
    is_osm = 'OpenStreetMap' in attribution
    credit = ft.Container(ft.Text('© OpenStreetMap' if is_osm else attribution,size=11,color='#40484B'),
                          bgcolor='#EFFFFFFF',border_radius=4,
                          padding=ft.Padding.symmetric(horizontal=6,vertical=3),bottom=6,right=8,
                          url='https://www.openstreetmap.org/copyright' if is_osm else None,
                          tooltip='Origem dos dados e licença do mapa' if is_osm else None)
    layers = [ft.Container(backdrop,left=0,right=0,top=0,bottom=0,alignment=ft.Alignment(0,0))]
    if callout is not None:
        layers.append(callout)
    layers.append(credit)
    stack = ft.Stack(layers,height=height)
    frame = ft.Container(stack,height=height,bgcolor='#E9EDEF',border_radius=18,
                         clip_behavior=ft.ClipBehavior.ANTI_ALIAS)

    def layout(map_width):
        map_height = map_width / STATION_MAP_RATIO
        frame.height = stack.height = map_height
        # The source has the same aspect ratio, so resizing never crops a pin.
        backdrop.height = map_height
        if isinstance(backdrop,ft.Image):
            backdrop.width = map_width
        credit.width = None if is_osm else min(260,map_width-16)
        if callout is not None:
            callout.left,callout.top = map_width*.455,map_height*.367
            callout.width = min(max(132,map_width*.295),map_width-callout.left-12)
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


async def station_map_widget(stations, on_select, *, offline=False, width=320, reference=None):
    """Home map with an honest selected-station callout, no inferred GPS/distance."""
    import asyncio
    import base64

    height = width / STATION_MAP_RATIO

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
    selected,lat,lng = next((item for item in positioned if item[0]['free_points']),positioned[0])
    markers = [(item_lat,item_lng,'⚡' if item['free_points'] else '⛔') for item,item_lat,item_lng in positioned]
    if reference is not None:
        markers.append((*reference,'🚗'))
    attribution = '© OpenStreetMap contributors'
    if offline:
        # This bundled vector extract is specific to the public demo fixture.
        # Never place another location on its fixed geographic marker.
        if abs(lat-(-23.5505)) < 0.000001 and abs(lng-(-46.6333)) < 0.000001 and reference is None and selected['free_points']:
            backdrop = ft.Image(src='maps/demo-centro.png',width=width,height=height,fit=ft.BoxFit.COVER,
                                semantics_label='Mapa da Praça da Sé, com o posto de exemplo da demonstração.')
            attribution = 'Demo · © OpenStreetMap contributors'
        else:
            backdrop = _schematic_map(lat,lng,markers,height=height,center_glyph=None)
            attribution = 'Mapa esquemático da demonstração · sem acesso à rede'
    else:
        try:
            # Reframe the real geography so the featured pin sits beside the
            # callout. The station coordinates remain the source of truth.
            source_width, source_height = 720, round(720 / STATION_MAP_RATIO)
            selected_x,selected_y = _lonlat_to_px(lat,lng,16)
            world_size = 2**16 * _TILE_SIZE
            center_x = selected_x + source_width*0.1
            center_y = selected_y + source_height*0.07
            center_lng = center_x/world_size*360-180
            center_lat = math.degrees(math.atan(math.sinh(math.pi*(1-2*center_y/world_size))))
            data = await asyncio.wait_for(asyncio.to_thread(build_map_png,center_lat,center_lng,markers,
                                                            width=source_width,height=source_height,zoom=16,
                                                            center_glyph=None,dark=False,selected_marker=(lat,lng)),timeout=7)
            backdrop = ft.Image(src='data:image/png;base64,'+base64.b64encode(data).decode(),
                                width=width,height=height,fit=ft.BoxFit.COVER,semantics_label='Mapa dos postos, centrado em '+selected.get('name','posto'))
        except (ImportError,OSError,RuntimeError,ValueError,TimeoutError):
            backdrop = _schematic_map(lat,lng,markers,height=height,center_glyph=None)
            attribution = 'Visão aproximada · mapa online indisponível'
    count = selected['free_points']
    status = f"{count} {'vaga' if count == 1 else 'vagas'}" if count else selected['status']
    name_text = ft.Text(selected.get('name') or 'Posto sem nome',size=14,weight=ft.FontWeight.BOLD,
                        font_family='BarlowSemiBold',color='#1D2835',max_lines=2,overflow=ft.TextOverflow.ELLIPSIS)
    status_text = ft.Text(status,size=11,weight=ft.FontWeight.BOLD,color='#205EA8' if count else '#58626F')
    badge = ft.Container(status_text,bgcolor='#D5E6FF' if count else '#E7EBEF',
                         border_radius=12,padding=ft.Padding.symmetric(horizontal=8,vertical=2))
    details = [name_text,ft.Row([badge],spacing=0)]
    if selected.get('price') is not None:
        details.append(ft.Text(f"Desde R$ {float(selected['price']):.2f}/kWh".replace('.',','),size=11,color='#58626F'))
    selected_action = on_select(selected['id'])
    callout = ft.Container(ft.Semantics(
                           content=ft.Column(details,spacing=4,horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                           container=True,button=True,label='Ver pontos em '+(selected.get('name') or 'posto'),
                           on_tap=selected_action),
                           bgcolor='#FFFFFF',border_radius=12,padding=10,
                           shadow=ft.BoxShadow(blur_radius=16,spread_radius=1,color='#38000000',offset=ft.Offset(0,3)),
                           on_click=selected_action,ink=True)
    def typography(map_width):
        name_text.size = max(13,min(16,map_width*16/563))
    return _map_frame(backdrop,attribution,width=width,callout=callout,on_layout=typography)


def build_map_png(center_lat, center_lng, markers, width=320, height=_MAP_HEIGHT, zoom=15,
                  center_glyph="🚗", dark=False, selected_marker=None):
    """Baixa os tiles do OpenStreetMap ao redor de (center_lat, center_lng),
    monta um recorte de width x height já centralizado, desenha os
    marcadores por cima e devolve os bytes de um PNG pronto.

    Usa diretamente `tile.openstreetmap.org` (o servidor de tiles oficial e
    amplamente usado do projeto) em vez de serviços de terceiros que compõem
    a imagem pronta — esses costumam ser projetos pequenos/hobby e ficam
    fora do ar com frequência (foi o que já aconteceu com
    staticmap.openstreetmap.de). Buscar os tiles crus e montar a imagem nós
    mesmos com Pillow é mais robusto, ao custo de mais uma dependência
    (`pillow`, já usada neste projeto para gerar os ícones da barra inferior).
    """
    from PIL import Image, ImageDraw  # import local: se o Pillow não estiver

    cx, cy = _lonlat_to_px(center_lat, center_lng, zoom)
    left, top = cx - width / 2, cy - height / 2

    tile_x_min, tile_x_max = int(left // _TILE_SIZE), int((left + width - 1) // _TILE_SIZE)
    tile_y_min, tile_y_max = int(top // _TILE_SIZE), int((top + height - 1) // _TILE_SIZE)
    n_tiles = 2 ** zoom

    canvas = Image.new("RGB", ((tile_x_max - tile_x_min + 1) * _TILE_SIZE,
                                (tile_y_max - tile_y_min + 1) * _TILE_SIZE), (245, 245, 245))

    got_any_tile = False
    for tx in range(tile_x_min, tile_x_max + 1):
        for ty in range(tile_y_min, tile_y_max + 1):
            if ty < 0 or ty >= n_tiles:
                continue
            wrapped_x = tx % n_tiles
            try:
                tile_bytes = _tile_bytes(zoom, wrapped_x, ty)
                tile_img = Image.open(io.BytesIO(tile_bytes)).convert("RGB")
                canvas.paste(tile_img, ((tx - tile_x_min) * _TILE_SIZE, (ty - tile_y_min) * _TILE_SIZE))
                got_any_tile = True
            except (OSError, ValueError):
                continue  # deixa essa região em cinza-claro se uma tile específica falhar

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
                _draw_station_pin(draw,x,y,radius=width*.038,available=glyph == '⚡')
            elif glyph != '🚗':
                _draw_station_pin(draw,x,y,radius=width*.025,available=glyph == '⚡')
            else:
                _draw_pin(draw, x, y, glyph, dark)
    if center_glyph:
        _draw_pin(draw, width / 2, height / 2, center_glyph, dark)

    buf = io.BytesIO()
    cropped.save(buf, format="PNG")
    return buf.getvalue()

async def map_widget(lat, lng, markers, center_glyph="🚗", *, offline=False, width=320):
    import asyncio
    import base64
    height = width / STATION_MAP_RATIO
    if offline:
        preview = _schematic_map(lat, lng, markers, height=height,center_glyph=center_glyph)
        attribution = "Mapa esquemático da demonstração · sem acesso à rede"
    else:
        try:
            data = await asyncio.wait_for(
                asyncio.to_thread(build_map_png, lat, lng, markers,
                                  width=720,height=round(720/STATION_MAP_RATIO),
                                  center_glyph=center_glyph, dark=False), timeout=7)
            preview = ft.Image(src="data:image/png;base64," + base64.b64encode(data).decode(),
                               width=width,height=height,fit=ft.BoxFit.COVER)
            attribution = "© OpenStreetMap contributors"
        except (ImportError, OSError, RuntimeError, ValueError, TimeoutError):
            preview = _schematic_map(lat, lng, markers,height=height,center_glyph=center_glyph)
            attribution = "Visão aproximada · mapa online indisponível"

    def legend_item(label, color, icon):
        return ft.Row([
            ft.Icon(icon, size=15, color=color),
            ft.Text(label, size=11, color=theme.GRAY_TEXT),
        ], spacing=4, tight=True)

    legend = [legend_item("Livre", '#233949', ft.Icons.BOLT),
              legend_item("Indisponível", theme.SLATE, ft.Icons.REMOVE)]
    if center_glyph:
        legend.insert(0, legend_item("Busca", theme.RED, ft.Icons.MY_LOCATION))
    return ft.Column([_map_frame(preview,attribution,width=width),
                      ft.Row(legend,wrap=True,spacing=12,run_spacing=4)],
                     spacing=10,horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
