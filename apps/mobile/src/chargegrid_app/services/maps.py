import io
import math
import urllib.request
from functools import lru_cache

import flet as ft

from ..ui import theme

_MARKER_COLOR = {"🚗": (30,144,255), "⚡": (46,125,50), "⛔": (218,41,46)}
_TILE_SIZE = 256

def _fetch_bytes(url, headers=None, timeout=3):
    request = urllib.request.Request(url, headers=headers or {"User-Agent":"ChargeGridApp/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


@lru_cache(maxsize=128)
def _tile_bytes(zoom, x, y):
    # Polls reuse a bounded set of tiles; failed requests are not cached.
    return _fetch_bytes(
        f'https://tile.openstreetmap.org/{zoom}/{x}/{y}.png',
        headers={'User-Agent': 'ChargeGridAcademic/1.0'},
        timeout=5,
    )

def _haversine_km(lat1, lng1, lat2, lng2):
    """Distância aproximada em km entre duas coordenadas (fórmula de haversine)."""
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1, max(0, a))))

def _schematic_map(center_lat, center_lng, markers_data, height=200, zoom=14, center_glyph="🚗"):
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

    def pin(x, y, glyph, size=28, bg=None, border_color=None):
        return ft.Container(
            content=ft.Text(glyph, size=size * 0.55, text_align=ft.TextAlign.CENTER),
            width=size, height=size, left=x - size / 2, top=y - size / 2,
            bgcolor=bg or theme.WHITE, border_radius=size / 2,
            border=ft.Border.all(width=2, color=border_color or theme.LIGHT_GRAY),
            alignment=ft.Alignment(0, 0),
        )

    ring_color = theme.LIGHT_GRAY
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
        # marcador extra sempre por cima, exatamente no centro (ex: "você está aqui")
        ux, uy = project(center_lat, center_lng)
        layers.append(pin(ux, uy, center_glyph, size=32, bg=theme.RED, border_color=theme.RED))

    return ft.Container(
        content=ft.Stack(layers, width=canvas_w, height=canvas_h),
        height=canvas_h,
        bgcolor=theme.BG_COLOR,
        border=ft.Border.all(width=1, color=theme.LIGHT_GRAY),
        border_radius=10,
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

def build_map_png(center_lat, center_lng, markers, width=320, height=200, zoom=15):
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

    draw = ImageDraw.Draw(cropped)
    for lat, lng, glyph in markers:
        px, py = _lonlat_to_px(lat, lng, zoom)
        x, y = px - left, py - top
        color = _MARKER_COLOR.get(glyph, (218, 41, 46))
        radius = 10 if glyph == "🚗" else 8
        draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=color, outline=(255, 255, 255), width=2)

    buf = io.BytesIO()
    cropped.save(buf, format="PNG")
    return buf.getvalue()

async def map_widget(lat, lng, markers, center_glyph="🚗"):
    import asyncio
    import base64
    try:
        data = await asyncio.wait_for(asyncio.to_thread(build_map_png, lat, lng, markers), timeout=7)
        return ft.Column([
            ft.Container(ft.Image(src="data:image/png;base64," + base64.b64encode(data).decode(), height=200, fit="cover"),
                         border_radius=12, clip_behavior=ft.ClipBehavior.ANTI_ALIAS),
            ft.Text("© OpenStreetMap contributors", size=10, color=theme.GRAY_TEXT),
        ], horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    except (ImportError, OSError, RuntimeError, ValueError, TimeoutError):
        return ft.Column([
            _schematic_map(lat,lng,markers,center_glyph=center_glyph),
            ft.Text("Mapa esquemático: mapa online indisponível",size=10,color=theme.GRAY_TEXT),
        ], horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
