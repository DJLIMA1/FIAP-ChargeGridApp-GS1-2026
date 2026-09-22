"""
ChargeGrid
=========================

Como executar:
    pip install flet
    python main.py
"""

import asyncio
import hashlib
import json
import math
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

import flet as ft

from data_manager import DataManager
import theme


# ==========================================
# HELPERS DE UI (equivalentes aos widgets/estilos do KV)
# ==========================================
def labeled_field(label, value="", hint="", password=False, on_change=None, on_blur=None):
    """Campo de texto com rótulo acima."""
    return ft.Column(
        [
            ft.Text(label, size=11, color=theme.GRAY_TEXT),
            ft.TextField(
                value=value,
                hint_text=hint,
                password=password,
                can_reveal_password=password,
                height=45,
                bgcolor=theme.WHITE,
                color=theme.TEXT_COLOR,
                cursor_color=theme.TEXT_COLOR,
                border_color=theme.LIGHT_GRAY,
                border_radius=5,
                text_size=14,
                content_padding=ft.Padding(left=15,right=15,top=10,bottom=10),
                on_change=on_change,
                on_blur=on_blur,
            ),
        ],
        spacing=5,
    )


def card(content, height=None, padding=15, **kwargs):
    """Cartão branco com cantos arredondados."""
    inner = ft.Column(content, spacing=4, tight=True) if isinstance(content, list) else content
    return ft.Container(
        content=inner,
        bgcolor=theme.WHITE,
        border_radius=5,
        padding=padding,
        height=height,
        **kwargs,
    )


def flat_button(text, bg, fg=theme.WHITE, on_click=None, bold=True, height=50, radius=0, expand=None, border=None):
    """Botão "chapado" sem sombra."""
    return ft.Container(
        content=ft.Text(
            text,
            color=fg,
            size=14,
            weight=ft.FontWeight.BOLD if bold else ft.FontWeight.NORMAL,
            text_align=ft.TextAlign.CENTER,
        ),
        bgcolor=bg,
        height=height,
        border_radius=radius,
        alignment=ft.Alignment(0, 0),
        on_click=on_click,
        ink=True,
        expand=expand,
        border=border,
        padding=ft.Padding( left=10,right=10),
    )


def badge(text, bg=theme.RED, width=70):
    """Etiqueta pequena arredondada (ex: 'Disponível', 'Pago')."""
    return ft.Container(
        content=ft.Text(text, size=10, color=theme.WHITE, text_align=ft.TextAlign.CENTER, weight=ft.FontWeight.BOLD),
        bgcolor=bg,
        border_radius=3,
        width=width,
        height=20,
        alignment=ft.Alignment(0, 0),
    )


def pill(text, bg=theme.LIGHT_GRAY, fg=theme.GRAY_TEXT):
    """Chip/pilula cinza usada em tags de estação/cupom."""
    return ft.Container(
        content=ft.Text(text, size=9, color=fg),
        bgcolor=bg,
        border_radius=10,
        padding=ft.Padding(left=10,right=10,top=4, bottom=4),
    )


def _haversine_km(lat1, lng1, lat2, lng2):
    """Distância aproximada em km entre duas coordenadas (fórmula de haversine)."""
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


NEARBY_RADIUS_KM = 5.0  # raio considerado "perto do usuário" nas telas do consumidor


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


def map_widget(center_lat, center_lng, markers_data, height=200, zoom=15, center_glyph="🚗"):
    """Mapa real (ruas, como o OpenStreetMap/Google Maps), centrado em
    (center_lat, center_lng), com marcadores para cada item em markers_data
    (lista de tuplas lat, lng, glifo) e, se `center_glyph` for informado, um
    marcador extra exatamente no centro (ex: "você está aqui").

    A imagem é montada por nós (`build_map_png`) a partir dos tiles oficiais
    do OpenStreetMap — não depende de nenhum serviço de terceiros de "mapa
    estático pronto" (esses tendem a ser projetos pequenos/hobby que ficam
    fora do ar com frequência). O PNG gerado é salvo dentro da própria pasta
    de assets do app (`assets/map_cache/`) e referenciado por caminho de
    arquivo — o mesmo mecanismo que já funciona comprovadamente pros ícones
    da barra de navegação — em vez de embutir como base64 (que nesta versão
    do Flet não é exibido mesmo quando aceito como atributo). Mapas iguais
    (mesma localização/zoom/marcadores) reaproveitam o arquivo já salvo, sem
    baixar tiles de novo. Se qualquer coisa falhar (sem internet, Pillow não
    instalado, servidor de tiles fora do ar), cai no mini-mapa esquemático
    (`_schematic_map`) — a tela nunca fica vazia.
    """
    markers = list(markers_data)
    if center_glyph:
        markers = markers + [(center_lat, center_lng, center_glyph)]

    fallback = _schematic_map(center_lat, center_lng, markers_data, height, zoom, center_glyph)

    try:
        cache_key = f"{round(center_lat, 5)}_{round(center_lng, 5)}_{zoom}_{height}_{markers}"
        digest = hashlib.md5(cache_key.encode("utf-8")).hexdigest()
        # Ancorado na pasta do próprio script (não no diretório de onde o
        # comando foi executado), pra sempre cair dentro da mesma pasta
        # 'assets' que o Flet está servindo via assets_dir="assets".
        app_dir = os.path.dirname(os.path.abspath(__file__))
        cache_dir = os.path.join(app_dir, "assets", "map_cache")
        os.makedirs(cache_dir, exist_ok=True)
        file_path = os.path.join(cache_dir, f"{digest}.png")

        if not os.path.exists(file_path):
            png_bytes = build_map_png(center_lat, center_lng, markers, width=320, height=height, zoom=zoom)
            with open(file_path, "wb") as f:
                f.write(png_bytes)

        image_control = ft.Image(src=f"/map_cache/{digest}.png", fit="cover", expand=True)
        return ft.Container(
            content=image_control,
            height=height,
            border_radius=10,
            border=ft.Border.all(width=1, color=theme.LIGHT_GRAY),
            bgcolor=theme.WHITE,
        )
    except ImportError:
        print("[ChargeGrid] Pillow não instalado — rode 'pip install pillow' para ver o mapa real. "
              "Usando o mapa esquemático por enquanto.")
        return fallback
    except Exception as exc:
        # Sem internet, servidor de tiles fora do ar, ou algum parâmetro do
        # ft.Image/Container não bate com esta versão do Flet — cai no
        # mini-mapa esquemático em vez de deixar a tela quebrada/vazia.
        # Imprime o motivo real no console para dar pra diagnosticar.
        print(f"[ChargeGrid] Mapa real indisponível, usando o esquemático. Motivo: {exc!r}")
        return fallback


def parse_currency(value):
    """Converte 'R$ 1.234,50' (ou '1234.50') em float. Retorna 0.0 se inválido."""
    if value is None:
        return 0.0
    cleaned = str(value).replace("R$", "").strip()
    if not cleaned:
        return 0.0
    cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        try:
            return float(str(value))
        except ValueError:
            return 0.0


def parse_float(value, default=0.0):
    """Converte texto em float aceitando vírgula como separador decimal
    (formato brasileiro). Devolve `default` para qualquer valor não numérico."""
    try:
        return float(str(value).strip().replace(",", "."))
    except (ValueError, TypeError):
        return default


def parse_int(value, default=0):
    """Igual a `parse_float`, mas arredonda para o inteiro mais próximo — usado
    para normalizar campos como minutos de recarga ou tempo máximo de carga,
    que podem chegar como string com vírgula vindos de um TextField."""
    try:
        return int(round(float(str(value).strip().replace(",", "."))))
    except (ValueError, TypeError):
        return default


def format_currency(value):
    """Converte float em 'R$ 1.234,50' (formato brasileiro)."""
    s = f"{max(value, 0):,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def _fetch_json(url, headers=None, timeout=6):
    """Faz uma requisição HTTP GET e decodifica a resposta como JSON. Usada por
    todas as integrações externas (ViaCEP, Nominatim, ip-api.com). Se a conexão
    falhar por causa de um certificado SSL não confiável — comum em instalações
    do Python no Windows sem o certificado raiz configurado — repete a mesma
    requisição sem validar o certificado antes de desistir, em vez de propagar
    um erro genérico de conexão que seria confuso para o usuário final."""
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "ChargeGridApp/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        # Em algumas instalações do Python no Windows, o certificado raiz não
        # está configurado corretamente e QUALQUER chamada HTTPS falha com
        # CERTIFICATE_VERIFY_FAILED mesmo com a internet funcionando normalmente
        # (é a causa mais comum de "sem conexão" mesmo estando conectado). Como
        # reserva, tenta de novo sem validar o certificado antes de desistir.
        reason = getattr(exc, "reason", None)
        if isinstance(reason, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(exc):
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return json.loads(resp.read().decode("utf-8"))
        raise


def _fetch_bytes(url, headers=None, timeout=6):
    """Baixa o conteúdo bruto (bytes) de uma URL — usado para trazer a imagem
    do mapa nós mesmos em vez de deixar o controle de imagem do Flet buscar a
    URL remota sozinho. Assim ganhamos controle total sobre erro/timeout/SSL
    (mesmo problema de certificado do Windows tratado em `_fetch_json`), e
    conseguimos decidir com certeza, em Python, se o mapa real está disponível
    ou se devemos cair no mapa esquemático — em vez de depender de um
    parâmetro de "conteúdo de erro" do controle de imagem que pode nem existir
    nesta versão do Flet."""
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "ChargeGridApp/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None)
        if isinstance(reason, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(exc):
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return resp.read()
        raise


def lookup_cep(cep):
    """Consulta a ViaCEP e devolve um dicionário com o endereço encontrado, ou None
    se o CEP for inválido/não encontrado ou se não houver conexão com a internet."""
    digits = re.sub(r"\D", "", cep or "")
    if len(digits) != 8:
        return None
    try:
        data = _fetch_json(f"https://viacep.com.br/ws/{digits}/json/")
    except Exception:
        return None
    if not data or data.get("erro"):
        return None

    logradouro = data.get("logradouro") or ""
    bairro = data.get("bairro") or ""
    cidade = data.get("localidade") or ""
    uf = data.get("uf") or ""
    rua_bairro = ", ".join(p for p in [logradouro, bairro] if p)
    endereco = ", ".join(p for p in [rua_bairro, cidade, uf] if p)
    return {"cep": digits, "logradouro": logradouro, "bairro": bairro,
            "cidade": cidade, "uf": uf, "endereco": endereco}


def geocode_address(query):
    """Geocodifica um endereço em texto livre usando o Nominatim (OpenStreetMap) e
    devolve (lat, lng), ou None se não encontrar ou se não houver internet."""
    if not query:
        return None
    try:
        params = urllib.parse.urlencode({"q": query, "format": "json", "limit": 1, "countrycodes": "br"})
        url = f"https://nominatim.openstreetmap.org/search?{params}"
        data = _fetch_json(url, headers={"User-Agent": "ChargeGridApp/1.0 (contato@chargegrid.app)"})
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        return None
    return None


def ip_geolocate():
    """Localização aproximada com base no IP público — não exige permissão do
    dispositivo nem nenhum controle nativo de geolocalização, então funciona em
    qualquer plataforma que tenha acesso à internet (é, porém, uma aproximação
    no nível da cidade, não a posição exata do usuário)."""
    try:
        data = _fetch_json("http://ip-api.com/json/?fields=status,lat,lon,city,regionName")
        if data.get("status") == "success":
            cidade = ", ".join(p for p in [data.get("city"), data.get("regionName")] if p)
            return {"lat": data["lat"], "lng": data["lon"], "address": cidade}
    except Exception:
        pass
    return None


# Cor (RGB) de cada marcador desenhado no mapa real, conforme o glifo lógico
# usado internamente: 🚗 = posição do usuário, ⚡ = estação disponível,
# ⛔ = estação ocupada no momento. Qualquer outro glifo cai no vermelho.
_MARKER_COLOR = {"🚗": (30, 144, 255), "⚡": (46, 125, 50), "⛔": (218, 41, 46)}
_TILE_SIZE = 256  # tamanho padrão (px) de um tile do sistema slippy map do OSM


def _lonlat_to_px(lat, lng, zoom):
    """Converte lat/lng em coordenadas de pixel no 'mundo' inteiro nesse zoom
    (sistema de tiles padrão usado por OpenStreetMap/Google/etc.)."""
    lat_rad = math.radians(lat)
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
    import io                          # instalado, quem chama trata o ImportError

    cx, cy = _lonlat_to_px(center_lat, center_lng, zoom)
    left, top = cx - width / 2, cy - height / 2

    tile_x_min, tile_x_max = int(left // _TILE_SIZE), int((left + width - 1) // _TILE_SIZE)
    tile_y_min, tile_y_max = int(top // _TILE_SIZE), int((top + height - 1) // _TILE_SIZE)
    n_tiles = 2 ** zoom

    canvas = Image.new("RGB", ((tile_x_max - tile_x_min + 1) * _TILE_SIZE,
                                (tile_y_max - tile_y_min + 1) * _TILE_SIZE), (245, 245, 245))

    headers = {"User-Agent": "ChargeGridApp/1.0 (contato@chargegrid.app)"}
    got_any_tile = False
    for tx in range(tile_x_min, tile_x_max + 1):
        for ty in range(tile_y_min, tile_y_max + 1):
            if ty < 0 or ty >= n_tiles:
                continue
            wrapped_x = tx % n_tiles
            try:
                tile_bytes = _fetch_bytes(
                    f"https://tile.openstreetmap.org/{zoom}/{wrapped_x}/{ty}.png",
                    headers=headers, timeout=5,
                )
                tile_img = Image.open(io.BytesIO(tile_bytes)).convert("RGB")
                canvas.paste(tile_img, ((tx - tile_x_min) * _TILE_SIZE, (ty - tile_y_min) * _TILE_SIZE))
                got_any_tile = True
            except Exception:
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


def _configure_window(page: ft.Page):
    """Ajusta o tamanho da janela para o formato 'app de celular' do design original."""
    try:
        page.window.width = 400
        page.window.height = 800
        page.window.min_width = 360
        page.window.resizable = True
    except Exception:
        try:
            page.window_width = 400
            page.window_height = 800
            page.window_resizable = True
        except Exception:
            pass


# ==========================================
# APLICAÇÃO PRINCIPAL
# ==========================================
class ChargeGridApp:
    """Controla o app inteiro. Não existe um sistema de rotas/telas separado:
    um único container (`self.root`) fica na página, e cada `show_*` decide o
    que colocar dentro dele com base no estado guardado nos atributos desta
    classe (papel logado, aba ativa, sub-tela dentro da aba, etc.). Qualquer
    mudança de estado é seguida de uma chamada a `show_consumer()`/
    `show_retailer()`/`show_login()`, que reconstrói a tela inteira a partir
    do zero — mais simples de raciocinar do que atualizar widgets individuais,
    ao custo de recriar a árvore de controles a cada interação."""

    def __init__(self, page: ft.Page):
        """Carrega os dados persistidos, aplica o tema salvo, configura a
        janela e inicializa o estado de navegaçao (login, consumidor,
        vendedor) com valores neutros antes de decidir a primeira tela via
        `route_start`. Os blocos abaixo estão agrupados por área da UI que
        cada grupo de atributos controla."""
        self.page = page
        self.page.title = "ChargeGrid APP"

        # --- dados persistidos ---
        self.data = DataManager.load_data()

        # Aplica a preferência de tema (claro/escuro) salva ANTES de montar
        # qualquer tela, para que tudo já nasça com as cores corretas.
        theme.set_dark(bool(self.data["settings"].get("dark_mode", False)))

        self.page.bgcolor = theme.BG_COLOR
        self.page.padding = 0
        self.page.spacing = 0
        _configure_window(page)

        self.current_user = None
        self.current_role = "consumer"

        # --- estado da tela de login/cadastro ---
        self.role_selected = "consumer"
        self.login_email = ""
        self.login_password = ""
        self.login_error = ""
        self.register_name = ""
        self.register_email = ""
        self.register_password = ""
        self.register_msg = ""

        # --- estado da tela "Esqueci minha senha" ---
        self.forgot_step = "email"  # "email" ou "reset"
        self.forgot_email = ""
        self.forgot_new_password = ""
        self.forgot_confirm_password = ""
        self.forgot_error = ""

        # --- estado da tela "Editar informações" (aba Conta do consumidor) ---
        self.consumer_conta_view = "view"  # "view" ou "edit"
        self.profile_form = {}

        # --- estado de navegação do consumidor ---
        self.consumer_tab = "tab_inicio"
        self.recarga_step = "step_bt"
        self.charger_selected = None
        self.charger_owner = None
        self.recharge_mode = "tempo"
        self.recharge_minutes = "30"
        self.recharge_value = "50,00"
        self.recharge_valor = 0.0
        self.chat_draft = ""

        # --- localização do consumidor para o mapa da aba Início ---
        # None = ainda não verificado; dict com lat/lng/source depois de resolvido.
        self.consumer_live_location = None
        self._locating = False
        self.location_draft = None  # rascunho do campo de localização na aba Conta

        # --- simulação da recarga em andamento (1 segundo real = 1 minuto simulado) ---
        self._charge_cancel = True
        self.charge_total_minutes = 0
        self.charge_remaining_minutes = 0
        self.chat_messages = [
            {"from": "bot", "text": "Oi! Sou o assistente da #ffive. Posso ajudar com recarga, "
                                     "pagamento ou um resumo da sua conta."},
            {"from": "user", "text": "Quero um resumo da minha última recarga."},
            {"from": "bot", "text": "Última recarga: Marginal Pinheiros, 12 de agosto — 32,4 kWh "
                                     "por R$ 68,04, pago via Pix."},
        ]

        # --- estado de navegação do vendedor ---
        self.retailer_tab = "tab_inicio"
        self.estacoes_view = "list_stations"
        self.descontos_view = "list_coupons"
        self.editing_station_index = None
        self.historico_filter = "Tudo"

        self.station_form_data = {
            "name": "", "cep": "", "endereco": "", "cidade": "", "uf": "",
            "lat": None, "lng": None, "max_time": "60", "power": "50",
            "price": "R$ 2,00", "active": True,
        }
        self.coupon_form_data = {"code": "", "desc": "", "station": "Todos os postos", "valid": "", "active": True}

        # Estações e cupons agora pertencem a cada CONTA DE VENDEDOR individualmente
        # (guardados em self.data["users"][email]["stations"/"coupons"]), e não mais
        # a uma lista global. Isso garante que cada vendedor só vê e gerencia seus
        # próprios carregadores/cupons, e que o consumidor enxerga qual carregador
        # pertence a qual vendedor (usado para filtrar o histórico do vendedor).

        # container raiz único: todo o app troca o conteúdo deste container
        self.root = ft.Container(expand=True, bgcolor=theme.BG_COLOR)
        self.page.add(self.root)

        self.route_start()

    # ------------------------------------------------------------
    # ROTEAMENTO INICIAL / SESSÃO
    # ------------------------------------------------------------
    def route_start(self):
        """Decide a primeira tela ao abrir o app: se houver uma sessão salva
        em `settings.active_session`/`active_role` no ev_data.json, pula
        direto para o painel do consumidor ou do vendedor; caso contrário,
        mostra o login."""
        active_user = self.data["settings"].get("active_session")
        active_role = self.data["settings"].get("active_role")
        if active_user and active_user in self.data["users"] and active_role:
            self.current_user = active_user
            self.current_role = active_role
            if active_role == "retailer":
                self.show_retailer()
            else:
                self.show_consumer()
        else:
            self.show_login()

    def logout(self, e):
        """Encerra a sessão: cancela qualquer recarga em andamento, limpa o
        estado de navegação específico do consumidor e apaga a sessão salva
        no JSON antes de voltar para o login."""
        self._charge_cancel = True
        self.current_user = None
        self.current_role = "consumer"
        self.consumer_live_location = None
        self._locating = False
        self.location_draft = None
        self.consumer_conta_view = "view"
        self.data["settings"]["active_session"] = None
        self.data["settings"]["active_role"] = None
        DataManager.save_data(self.data)
        self.show_login()

    def _show_snack(self, msg):
        """Mostra uma mensagem curta e temporária no rodapé da tela (SnackBar),
        usada para erros de validação e confirmações rápidas em toda a app."""
        self.page.snack_bar = ft.SnackBar(content=ft.Text(msg))
        self.page.snack_bar.open = True
        self.page.update()

    def toggle_dark_mode(self, e):
        """Alterna entre tema claro/escuro, salva a preferência e redesenha a
        tela atual (login, consumidor ou vendedor) com as novas cores."""
        enabled = e.control.value if hasattr(e, "control") else not theme.is_dark()
        theme.set_dark(enabled)
        self.data["settings"]["dark_mode"] = enabled
        DataManager.save_data(self.data)
        self.page.bgcolor = theme.BG_COLOR
        self.root.bgcolor = theme.BG_COLOR

        if self.current_user and self.current_role == "retailer":
            self.show_retailer()
        elif self.current_user and self.current_role == "consumer":
            self.show_consumer()
        else:
            self.show_login()

    def _dark_mode_section(self):
        """Cartão com o interruptor de modo escuro, reutilizado nas telas de
        Conta do consumidor e do vendedor (é uma preferência do aplicativo
        inteiro, não de um papel específico)."""
        return card(
            ft.Row(
                [
                    ft.Column(
                        [
                            ft.Text("Modo escuro", weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
                            ft.Text("Muda a aparência de todo o aplicativo.", size=11, color=theme.GRAY_TEXT),
                        ],
                        spacing=2, expand=True,
                    ),
                    ft.Switch(value=theme.is_dark(), on_change=self.toggle_dark_mode),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            height=70,
        )

    def _retailer_stations(self, owner=None):
        """Lista de estações da conta de vendedor indicada (por padrão, o usuário logado).
        Cria a lista vazia na primeira vez que a conta acessa a aba de estações."""
        owner = owner or self.current_user
        if not owner or owner not in self.data["users"]:
            return []
        return self.data["users"][owner].setdefault("stations", [])

    def _retailer_coupons(self, owner=None):
        """Lista de cupons da conta de vendedor indicada (por padrão, o usuário logado)."""
        owner = owner or self.current_user
        if not owner or owner not in self.data["users"]:
            return []
        return self.data["users"][owner].setdefault("coupons", [])

    def _consumer_all_stations(self):
        """Junta as estações de TODAS as contas de vendedor, para exibir ao consumidor.
        Retorna uma lista de tuplas (email_do_vendedor, estacao)."""
        result = []
        for email, user in self.data["users"].items():
            for st in user.get("stations", []) or []:
                result.append((email, st))
        return result

    def _find_selected_station(self):
        """Localiza o carregador escolhido pelo consumidor dentro da conta do vendedor dono."""
        if not self.charger_owner or self.charger_owner not in self.data["users"]:
            return None
        for st in self.data["users"][self.charger_owner].get("stations", []) or []:
            if st.get("name") == self.charger_selected:
                return st
        return None

    def _consumer_month_spend(self):
        """Soma o valor das recargas do usuário logado feitas no mês corrente."""
        if not self.current_user or self.current_user not in self.data["users"]:
            return 0.0
        history = self.data["users"][self.current_user].get("history", [])
        now = time.localtime()
        total = 0.0
        for item in history:
            ts = item.get("timestamp")
            if not ts:
                continue
            item_time = time.localtime(ts)
            if item_time.tm_year == now.tm_year and item_time.tm_mon == now.tm_mon:
                total += parse_currency(item.get("valor"))
        return total

    def _all_transactions(self):
        """Junta as recargas feitas especificamente nas estações da conta de vendedor
        logada no momento."""
        txs = []
        for user in self.data["users"].values():
            for item in user.get("history", []):
                if item.get("owner") == self.current_user:
                    txs.append(item)
        txs.sort(key=lambda i: i.get("timestamp") or 0, reverse=True)
        return txs

    def _total_received(self):
        """Total recebido por este vendedor: soma das recargas feitas em suas próprias estações."""
        return sum(parse_currency(t.get("valor")) for t in self._all_transactions())

    async def _try_device_geolocation(self):
        """Tenta obter a localização real do dispositivo (GPS/serviço de localização
        do sistema) através do controle Geolocator do Flet. Em vários ambientes
        (principalmente apps desktop, ou quando o usuário nunca deu permissão) isso
        não está disponível — qualquer falha aqui é tratada como 'sem localização do
        dispositivo' e o app cai para as reservas em _try_auto_locate, sem travar."""
        try:
            geolocator = ft.Geolocator()
            if geolocator not in self.page.overlay:
                self.page.overlay.append(geolocator)
                self.page.update()
            pos = await asyncio.wait_for(geolocator.get_current_position(), timeout=5)
            if pos is not None and getattr(pos, "latitude", None) is not None:
                return pos.latitude, pos.longitude
        except Exception:
            pass
        return None

    async def _try_auto_locate(self):
        """Resolve a localização usada no mapa da aba Início do consumidor.
        Prioridade: (1) localização real do dispositivo, se ligada/disponível;
        (2) localização definida manualmente na aba Conta, caso a do
        dispositivo não esteja disponível; (3) localização aproximada por IP,
        como último recurso; (4) nenhuma (mostra aviso na tela)."""
        device_coords = await self._try_device_geolocation()
        if device_coords:
            self.consumer_live_location = {
                "lat": device_coords[0], "lng": device_coords[1], "source": "device",
            }
            self._locating = False
            if self.current_role == "consumer" and self.current_user and self.consumer_tab == "tab_inicio":
                try:
                    self.show_consumer()
                except Exception:
                    pass
            return

        saved = None
        if self.current_user and self.current_user in self.data["users"]:
            saved = self.data["users"][self.current_user].get("location")

        if saved and saved.get("lat") is not None:
            self.consumer_live_location = {
                "lat": saved["lat"], "lng": saved["lng"],
                "source": "account", "address": saved.get("address", ""),
            }
        else:
            result = await asyncio.to_thread(ip_geolocate)
            if result:
                self.consumer_live_location = {
                    "lat": result["lat"], "lng": result["lng"],
                    "source": "ip", "address": result.get("address", ""),
                }
            else:
                self.consumer_live_location = {"lat": None, "lng": None, "source": "none"}

        self._locating = False
        if self.current_role == "consumer" and self.current_user and self.consumer_tab == "tab_inicio":
            try:
                self.show_consumer()
            except Exception:
                pass

    def _nav_btn(self, icon_default, icon_active, label, active, on_click):
        """Um item da barra de navegação inferior: troca entre o ícone
        'outline' (inativo) e o 'preenchido' (ativo) conforme a aba atual, e
        colore o rótulo de vermelho quando selecionado. Os ícones vêm de
        arquivos em assets/icons/, servidos pelo assets_dir configurado em
        ft.run()."""
        color = theme.RED if active else theme.GRAY_TEXT  # Cores mantidas do theme.py
        current_icon = icon_active if active else icon_default
        return ft.Container(
            content=ft.Column(
                [
                    ft.Image(
                        src=current_icon,
                        width=22,
                        height=22,
                        fit="contain"
                    ),
                    ft.Text(label, size=10, color=color, text_align=ft.TextAlign.CENTER),
                ],
                spacing=2,
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            expand=1,
            alignment=ft.Alignment(0, 0),
            on_click=on_click,
            padding=ft.Padding(top=8, bottom=8),
        )

    # ==============================================================
    # LOGIN
    # ==============================================================
    def show_login(self):
        """Tela de entrada. O papel (consumidor/vendedor) é escolhido aqui, não
        é uma propriedade fixa da conta: a mesma credencial pode logar como
        consumidor numa sessão e como vendedor em outra — cada papel só lê/
        escreve os campos que fazem sentido pra ele dentro do registro do
        usuário (histórico para consumidor, stations/coupons para vendedor)."""
        def on_email_change(e):
            self.login_email = e.control.value

        def on_password_change(e):
            self.login_password = e.control.value

        def select_role(role):
            self.role_selected = role
            self.show_login()

        btn_consumer = flat_button(
            "Sou consumidor",
            bg=theme.RED if self.role_selected == "consumer" else theme.WHITE,
            fg=theme.WHITE if self.role_selected == "consumer" else theme.GRAY_TEXT,
            on_click=lambda e: select_role("consumer"), height=45, expand=True,
        )
        btn_retailer = flat_button(
            "Sou vendedor",
            bg=theme.RED if self.role_selected == "retailer" else theme.WHITE,
            fg=theme.WHITE if self.role_selected == "retailer" else theme.GRAY_TEXT,
            on_click=lambda e: select_role("retailer"), height=45, expand=True,
        )

        content = ft.Column(
            [
                ft.Text("#ffive", size=32, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
                ft.Row([btn_consumer, btn_retailer], spacing=0),
                labeled_field("E-mail", value=self.login_email, hint="voce@email.com", on_change=on_email_change),
                labeled_field("Senha", value=self.login_password, hint="********", password=True,
                               on_change=on_password_change),
                ft.Container(
                    content=ft.Text(
                        "Esqueci minha senha", size=12, color=theme.GRAY_TEXT,
                        style=ft.TextStyle(decoration=ft.TextDecoration.UNDERLINE),
                    ),
                    on_click=lambda e: self.show_forgot_password(),
                ),
                ft.Text(self.login_error, color=theme.RED, size=12),
                flat_button("Entrar", theme.RED, theme.WHITE, on_click=self.do_login),
                flat_button("Criar conta", theme.WHITE, theme.TEXT_COLOR, on_click=lambda e: self.show_register()),
            ],
            spacing=20,
            scroll=ft.ScrollMode.AUTO,
        )

        self.root.content = ft.Container(
            content=content,
            padding=ft.Padding(left=30, right=30, top=50, bottom=30),
            bgcolor=theme.BG_COLOR,
            expand=True,
        )
        self.page.update()

    def do_login(self, e):
        """Valida e-mail/senha contra `data["users"]` e, se corretos, grava a
        sessão ativa no JSON (persiste entre execuções do app) antes de abrir
        o painel do papel escolhido na tela anterior."""
        email = (self.login_email or "").strip()
        password = (self.login_password or "").strip()
        users = self.data["users"]

        if email in users and users[email]["password"] == password:
            self.current_user = email
            self.current_role = self.role_selected
            self.data["settings"]["active_session"] = email
            self.data["settings"]["active_role"] = self.current_role
            DataManager.save_data(self.data)

            self.login_email = ""
            self.login_password = ""
            self.login_error = ""

            if self.current_role == "retailer":
                self.show_retailer()
            else:
                self.consumer_tab = "tab_inicio"
                self.recarga_step = "step_bt"
                self.show_consumer()
        else:
            self.login_error = "Credenciais inválidas!"
            self.show_login()

    # ==============================================================
    # CADASTRO
    # ==============================================================
    def show_register(self):
        """Formulário de criação de conta (nome, e-mail, senha). Não pede o
        papel — a conta criada aqui pode logar tanto como consumidor quanto
        como vendedor depois, conforme escolhido na tela de login."""
        def on_name(e):
            self.register_name = e.control.value

        def on_email(e):
            self.register_email = e.control.value

        def on_pass(e):
            self.register_password = e.control.value

        content = ft.Column(
            [
                ft.Container(
                    content=ft.Text(
                        "<  Voltar", size=14, color=theme.TEXT_COLOR,
                        style=ft.TextStyle(decoration=ft.TextDecoration.UNDERLINE),
                    ),
                    on_click=lambda e: self.show_login(),
                ),
                ft.Text("Criar conta", size=28, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
                labeled_field("Nome completo", value=self.register_name, hint="Seu nome", on_change=on_name),
                labeled_field("E-mail", value=self.register_email, hint="voce@email.com", on_change=on_email),
                labeled_field("Senha", value=self.register_password, hint="********", password=True,
                               on_change=on_pass),
                ft.Text(self.register_msg, color=theme.RED, size=12),
                flat_button("Criar conta", theme.RED, theme.WHITE, on_click=self.do_register),
            ],
            spacing=20,
            scroll=ft.ScrollMode.AUTO,
        )

        self.root.content = ft.Container(
            content=content,
            padding=ft.Padding(left=30, right=30, top=40, bottom=30),
            bgcolor=theme.BG_COLOR,
            expand=True,
        )
        self.page.update()

    def do_register(self, e):
        """Cria a conta se o e-mail ainda não existir em `data["users"]`. O
        registro nasce só com nome/senha/histórico vazio — os campos
        específicos de vendedor (stations/coupons) são criados sob demanda na
        primeira vez que essa conta acessa o papel de vendedor."""
        name = (self.register_name or "").strip()
        email = (self.register_email or "").strip()
        password = (self.register_password or "").strip()

        if not name or not email or not password:
            self.register_msg = "Preencha todos os campos."
            self.show_register()
            return

        if email not in self.data["users"]:
            self.data["users"][email] = {"name": name, "password": password, "history": []}
            DataManager.save_data(self.data)
            self.register_name = ""
            self.register_email = ""
            self.register_password = ""
            self.register_msg = ""
            self.show_login()
        else:
            self.register_msg = "E-mail já cadastrado."
            self.show_register()

    # ==============================================================
    # ESQUECI MINHA SENHA
    # ==============================================================
    def show_forgot_password(self):
        """Tela de recuperação de senha em duas etapas: (1) confirmar o e-mail
        cadastrado; (2) definir uma nova senha para essa conta."""
        if self.forgot_step == "reset":
            content = self._forgot_password_reset_step()
        else:
            content = self._forgot_password_email_step()

        self.root.content = ft.Container(
            content=content,
            padding=ft.Padding(left=30, right=30, top=50, bottom=30),
            bgcolor=theme.BG_COLOR,
            expand=True,
        )
        self.page.update()

    def _forgot_password_email_step(self):
        """Primeira etapa: campo de e-mail + botão que valida se existe conta
        cadastrada com ele (ver `check_forgot_email`)."""
        def on_email_change(e):
            self.forgot_email = e.control.value

        return ft.Column(
            [
                ft.Container(
                    content=ft.Text(
                        "<  Voltar", size=14, color=theme.TEXT_COLOR,
                        style=ft.TextStyle(decoration=ft.TextDecoration.UNDERLINE),
                    ),
                    on_click=lambda e: self._close_forgot_password(),
                ),
                ft.Text("Recuperar senha", size=28, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
                ft.Text("Digite o e-mail cadastrado na sua conta para definir uma nova senha.",
                        size=12, color=theme.GRAY_TEXT),
                labeled_field("E-mail", value=self.forgot_email, hint="voce@email.com",
                               on_change=on_email_change),
                ft.Text(self.forgot_error, color=theme.RED, size=12),
                flat_button("Continuar", theme.RED, theme.WHITE, on_click=self.check_forgot_email),
            ],
            spacing=20,
            scroll=ft.ScrollMode.AUTO,
        )

    def _forgot_password_reset_step(self):
        """Segunda etapa: campos de nova senha + confirmação, já sabendo que
        o e-mail em `self.forgot_email` existe (validado na etapa anterior)."""
        def on_pass1(e):
            self.forgot_new_password = e.control.value

        def on_pass2(e):
            self.forgot_confirm_password = e.control.value

        return ft.Column(
            [
                ft.Container(
                    content=ft.Text(
                        "<  Voltar", size=14, color=theme.TEXT_COLOR,
                        style=ft.TextStyle(decoration=ft.TextDecoration.UNDERLINE),
                    ),
                    on_click=lambda e: self._back_to_forgot_email_step(),
                ),
                ft.Text("Nova senha", size=28, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
                ft.Text(f"Definindo uma nova senha para {self.forgot_email}.",
                        size=12, color=theme.GRAY_TEXT),
                labeled_field("Nova senha", value=self.forgot_new_password, hint="********",
                               password=True, on_change=on_pass1),
                labeled_field("Confirmar nova senha", value=self.forgot_confirm_password, hint="********",
                               password=True, on_change=on_pass2),
                ft.Text(self.forgot_error, color=theme.RED, size=12),
                flat_button("Alterar senha", theme.RED, theme.WHITE, on_click=self.do_reset_password),
            ],
            spacing=20,
            scroll=ft.ScrollMode.AUTO,
        )

    def check_forgot_email(self, e):
        """Avança para a etapa de nova senha somente se o e-mail informado
        corresponder a uma conta existente; caso contrário, mostra o erro
        sem sair da primeira etapa."""
        email = (self.forgot_email or "").strip()
        if not email:
            self.forgot_error = "Informe o e-mail."
        elif email not in self.data["users"]:
            self.forgot_error = "Não encontramos uma conta com esse e-mail."
        else:
            self.forgot_email = email
            self.forgot_error = ""
            self.forgot_step = "reset"
        self.show_forgot_password()

    def do_reset_password(self, e):
        """Valida a nova senha (preenchida, confirmação igual, tamanho mínimo)
        e, se tudo certo, sobrescreve a senha da conta no JSON e volta para o
        login com uma confirmação."""
        new_pass = (self.forgot_new_password or "").strip()
        confirm = (self.forgot_confirm_password or "").strip()

        if not new_pass or not confirm:
            self.forgot_error = "Preencha os dois campos de senha."
        elif new_pass != confirm:
            self.forgot_error = "As senhas não coincidem."
        elif len(new_pass) < 4:
            self.forgot_error = "Use uma senha com pelo menos 4 caracteres."
        else:
            self.data["users"][self.forgot_email]["password"] = new_pass
            DataManager.save_data(self.data)
            self._close_forgot_password()
            self._show_snack("Senha alterada com sucesso! Faça login com a nova senha.")
            return

        self.show_forgot_password()

    def _back_to_forgot_email_step(self):
        """Volta da etapa de nova senha para a etapa de e-mail, limpando os
        campos de senha (mas mantendo o e-mail já digitado)."""
        self.forgot_step = "email"
        self.forgot_error = ""
        self.forgot_new_password = ""
        self.forgot_confirm_password = ""
        self.show_forgot_password()

    def _close_forgot_password(self):
        """Reseta o estado do fluxo de recuperação de senha e volta ao login."""
        self.forgot_step = "email"
        self.forgot_email = ""
        self.forgot_new_password = ""
        self.forgot_confirm_password = ""
        self.forgot_error = ""
        self.show_login()

    # ==============================================================
    # MÓDULO CONSUMIDOR
    # ==============================================================
    def show_consumer(self):
        """Monta a casca fixa do app do consumidor: cabeçalho com "Sair",
        área de conteúdo (preenchida por `render_consumer_tab`, que muda
        conforme `self.consumer_tab`) e a barra de navegação inferior."""
        header = ft.Container(
            content=ft.Row(
                [
                    ft.Text("#ffive", size=20, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR, expand=True),
                    ft.Container(
                        content=ft.Text(
                            "Sair", size=14, color=theme.TEXT_COLOR,
                            style=ft.TextStyle(decoration=ft.TextDecoration.UNDERLINE),
                        ),
                        on_click=self.logout,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            height=60,
            padding=ft.Padding(  left=20, right=20, top = 10, bottom = 10,),
        )

        content_area = ft.Container(content=self.render_consumer_tab(), expand=True)

        bottom_nav = ft.Container(
            content=ft.Row(
                [
                    self._nav_btn("/icons/home_icon.png", "/icons/home_icon_fill.png", "Início",
                                  self.consumer_tab == "tab_inicio",
                                  lambda e: self.switch_consumer_tab("tab_inicio")),
                    self._nav_btn("/icons/recarga_icon.png", "/icons/recarga_icon_fill.png", "Recarga",
                                  self.consumer_tab == "tab_recarga",
                                  lambda e: self.switch_consumer_tab("tab_recarga")),
                    self._nav_btn("/icons/historico_icon.png", "/icons/historico_icon_fill.png", "Histórico",
                                  self.consumer_tab == "tab_historico",
                                  lambda e: self.switch_consumer_tab("tab_historico")),
                    self._nav_btn("/icons/chat_icon.png", "/icons/chat_icon_fill.png", "Chat",
                                  self.consumer_tab == "tab_chat",
                                  lambda e: self.switch_consumer_tab("tab_chat")),
                    self._nav_btn("/icons/profile_icon.png", "/icons/profile_icon_fill.png", "Conta",
                                  self.consumer_tab == "tab_conta",
                                  lambda e: self.switch_consumer_tab("tab_conta")),
                ],
                spacing=0,
            ),
            height=60,
            bgcolor=theme.WHITE,
            border=ft.Border.all(width=1, color=theme.LIGHT_GRAY)
        )

        self.root.content = ft.Column([header, content_area, bottom_nav], spacing=0, expand=True)
        self.page.update()

    def switch_consumer_tab(self, tab):
        """Troca a aba ativa do consumidor. Ao sair da aba Conta, força a
        volta pra visualização normal (sai do modo "editar informações"
        caso estivesse aberto); ao entrar na aba Recarga, sempre reinicia o
        fluxo na primeira etapa (busca por Bluetooth)."""
        self.consumer_tab = tab
        self.consumer_conta_view = "view"
        if tab == "tab_recarga":
            self.recarga_step = "step_bt"
        self.show_consumer()

    def render_consumer_tab(self):
        """Despacha para a função que constrói o conteúdo da aba ativa."""
        return {
            "tab_inicio": self.consumer_home,
            "tab_recarga": self.consumer_recarga,
            "tab_historico": self.consumer_historico,
            "tab_chat": self.consumer_chat,
            "tab_conta": self.consumer_conta,
        }.get(self.consumer_tab, lambda: ft.Container())()

    # ---------------- TAB INÍCIO ----------------
    def consumer_home(self):
        """Painel inicial do consumidor: saudação, mapa com a localização e
        eletropostos próximos, gasto do mês, dica de IA, lista de estações
        próximas e atalho para iniciar uma recarga."""
        # Dispara a localização automática (uma única vez) assim que a aba Início é
        # exibida. Quando resolver, chama show_consumer() de novo para desenhar o mapa.
        if self.consumer_live_location is None and not self._locating:
            self._locating = True
            self.page.run_task(self._try_auto_locate)

        user_name = "Usuário"
        if self.current_user and self.current_user in self.data["users"]:
            user_name = self.data["users"][self.current_user]["name"]

        avatar_row = ft.Row(
            [
                ft.Container(width=50, height=50, bgcolor=theme.LIGHT_GRAY, border_radius=25),
                ft.Column(
                    [
                        ft.Text(f"Olá, {user_name}", weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
                        ft.Text("Bateria em 42% · Aprox: 180 km", size=12, color=theme.GRAY_TEXT),
                    ],
                    spacing=2,
                ),
            ],
            spacing=15,
        )

        map_section = self._build_home_map_section()

        spend_card = card(
            [
                ft.Text("GASTO ESTE MÊS", size=10, color=theme.GRAY_TEXT),
                ft.Text(format_currency(self._consumer_month_spend()), size=26,
                        weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
            ],
            height=90,
        )

        ai_card = card(
            ft.Row(
                [
                    ft.Container(
                        content=ft.Container(
                            content=ft.Text("IA", size=12, color=theme.TEXT_COLOR),
                            width=38,
                            height=38,
                            bgcolor=theme.WHITE,
                            border_radius=19,
                            alignment=ft.Alignment(0, 0),
                        ),
                        width=40,
                        height=40,
                        bgcolor=theme.LIGHT_GRAY,
                        border_radius=20,
                        alignment=ft.Alignment(0, 0),
                    ),
                    ft.Text(
                        "Carregue após as 22h na Marginal Pinheiros e economize até 20%.",
                        size=12, color="#555555", expand=True,
                    ),
                ],
                spacing=15,
            ),
            height=70,
        )

        def station_row(name, subtitle, status_text, busy):
            return ft.Row(
                [
                    ft.Column(
                        [
                            ft.Text(name, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
                            ft.Text(subtitle, size=11, color=theme.GRAY_TEXT),
                        ],
                        spacing=2, expand=True,
                    ),
                    badge(status_text, bg=theme.RED if busy else theme.GREEN, width=90),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            )

        loc = self.consumer_live_location
        now = time.time()
        nearby = []
        for _owner, st in self._consumer_all_stations():
            if not st.get("active", True) or st.get("lat") is None or st.get("lng") is None:
                continue
            if loc and loc.get("lat") is not None:
                dist_km = _haversine_km(loc["lat"], loc["lng"], st["lat"], st["lng"])
                if dist_km > NEARBY_RADIUS_KM:
                    continue
            else:
                dist_km = None
            nearby.append((dist_km, st))

        # sem distância (localização ainda não resolvida) fica no fim, sem ordenar por km
        nearby.sort(key=lambda item: (item[0] is None, item[0] or 0))

        station_rows = []
        for dist_km, st in nearby:
            busy = bool(st.get("busy_until")) and st["busy_until"] > now
            local = st.get("endereco") or f"{st.get('cidade', '')}/{st.get('uf', '')}".strip("/")
            dist_txt = f"{dist_km:.1f} km · ".replace(".", ",") if dist_km is not None else ""
            subtitle = f"{dist_txt}{local} · {st.get('price', '')}/kWh"
            station_rows.append(station_row(st["name"], subtitle, "Indisponível" if busy else "Disponível", busy))

        if not station_rows:
            msg = ("Nenhuma estação cadastrada a menos de "
                   f"{NEARBY_RADIUS_KM:g} km de você.") if (loc and loc.get("lat") is not None) \
                else "Nenhuma estação cadastrada no momento."
            station_rows = [ft.Text(msg, size=12, color=theme.GRAY_TEXT)]

        stations_section = ft.Column(
            [ft.Text("Estações próximas", weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR, size=14)] + station_rows,
            spacing=15,
        )

        return ft.Container(
            content=ft.ListView(
                [
                    avatar_row,
                    map_section,
                    spend_card,
                    ai_card,
                    stations_section,
                    flat_button("Recarregar agora", theme.RED, theme.WHITE, on_click=self.start_recharge_flow),
                ],
                spacing=20, padding=20, expand=True,
            ),
            expand=True,
        )

    def _build_home_map_section(self):
        """Monta o cartão de mapa da aba Início: localização do usuário + eletropostos
        próximos cadastrados por qualquer vendedor. Cai para uma mensagem de aviso
        quando ainda não há localização resolvida."""
        loc = self.consumer_live_location

        if not loc or loc.get("lat") is None:
            message = (
                "Localizando você..." if self._locating else
                "Não foi possível localizar você automaticamente. Defina sua "
                "localização na aba Conta para ver o mapa."
            )
            return ft.Container(
                content=ft.Column(
                    [
                        ft.Text("📍", size=26),
                        ft.Text(message, size=12, color=theme.GRAY_TEXT, text_align=ft.TextAlign.CENTER),
                    ],
                    spacing=8, alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                height=140, bgcolor=theme.WHITE, border_radius=5, alignment=ft.Alignment(0, 0), padding=20,
            )

        now = time.time()
        markers_data = []
        nearest_available_km = None
        nearest_busy_km = None
        for _owner, st in self._consumer_all_stations():
            if not st.get("active", True) or st.get("lat") is None or st.get("lng") is None:
                continue
            dist_km = _haversine_km(loc["lat"], loc["lng"], st["lat"], st["lng"])
            if dist_km > NEARBY_RADIUS_KM:
                continue
            busy = bool(st.get("busy_until")) and st["busy_until"] > now
            markers_data.append((st["lat"], st["lng"], "⛔" if busy else "⚡"))
            if busy:
                nearest_busy_km = dist_km if nearest_busy_km is None else min(nearest_busy_km, dist_km)
            else:
                nearest_available_km = dist_km if nearest_available_km is None else min(nearest_available_km, dist_km)

        if nearest_available_km is not None:
            status_icon, status_color = "⚡", theme.GREEN
            status_text = f"Eletroposto disponível a {nearest_available_km:.1f} km".replace(".", ",")
        elif nearest_busy_km is not None:
            status_icon, status_color = "⛔", theme.RED
            status_text = f"Eletroposto mais próximo ocupado ({nearest_busy_km:.1f} km)".replace(".", ",")
        else:
            status_icon, status_color = "📍", theme.GRAY_TEXT
            status_text = f"Nenhum eletroposto cadastrado a menos de {NEARBY_RADIUS_KM:g} km."

        status_row = ft.Row(
            [ft.Text(status_icon, size=14), ft.Text(status_text, size=12, color=status_color,
                                                      weight=ft.FontWeight.BOLD)],
            spacing=6,
        )

        caption = {
            "device": "Localização do dispositivo",
            "account": "Localização definida na sua conta",
            "ip": "Localização aproximada (baseada na sua conexão)",
        }.get(loc.get("source"), "")

        children = [map_widget(loc["lat"], loc["lng"], markers_data), status_row]
        if caption:
            children.append(ft.Text(caption, size=10, color=theme.GRAY_TEXT))

        return ft.Column(children, spacing=6)

    def start_recharge_flow(self, e):
        """Atalho do botão "Recarregar agora": muda pra aba Recarga já
        reiniciada na primeira etapa."""
        self.consumer_tab = "tab_recarga"
        self.recarga_step = "step_bt"
        self.show_consumer()

    # ---------------- TAB RECARGA (fluxo em etapas) ----------------
    def consumer_recarga(self):
        """Fluxo de recarga como uma máquina de estados guardada em
        `self.recarga_step`, com seis etapas em sequência:
        step_bt (busca do carregador) → step_list (escolher a estação) →
        step_setup (definir tempo ou valor) → step_summary (confirmar) →
        step_qr (pagamento via Pix) → step_active (carga em andamento,
        com contagem regressiva assíncrona). Cada etapa é uma função
        própria; esta apenas despacha para a etapa atual."""
        step_fn = {
            "step_bt": self.recarga_step_bt,
            "step_list": self.recarga_step_list,
            "step_setup": self.recarga_step_setup,
            "step_summary": self.recarga_step_summary,
            "step_qr": self.recarga_step_qr,
            "step_active": self.recarga_step_active,
        }.get(self.recarga_step, lambda: ft.Container())
        return ft.Container(content=step_fn(), expand=True)

    def _go_recarga_step(self, step):
        """Avança/volta manualmente para uma etapa específica do fluxo de recarga."""
        self.recarga_step = step
        self.show_consumer()

    def recarga_step_bt(self):
        """Etapa 1: tela de espera simulando a busca por carregadores via
        Bluetooth (não faz nenhuma busca real — é só uma transição visual)."""
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text("Buscando carregadores", size=18, color=theme.TEXT_COLOR, text_align=ft.TextAlign.CENTER),
                    ft.Text("Verifique se o Bluetooth está ativado no seu celular.",
                            size=12, color=theme.GRAY_TEXT, text_align=ft.TextAlign.CENTER),
                    flat_button("Continuar", theme.RED, theme.WHITE, on_click=lambda e: self._go_recarga_step("step_list")),
                ],
                spacing=20, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding(left=30,right=30,top=50,bottom=50),
        )

    def recarga_step_list(self):
        """Etapa 2: lista todas as estações ativas de todos os vendedores
        (não só as próximas — aqui o consumidor pode escolher qualquer
        carregador cadastrado). Estações ocupadas (busy_until no futuro)
        aparecem marcadas e não podem ser selecionadas."""
        now = time.time()
        active_stations = [
            (owner, st) for owner, st in self._consumer_all_stations() if st.get("active", True)
        ]

        cards = [
            ft.Text("Carregadores encontrados", weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
            ft.Text("Toque em um carregador para continuar.", size=12, color=theme.GRAY_TEXT),
        ]

        if not active_stations:
            cards.append(ft.Text("Nenhum carregador cadastrado no momento.", size=12, color=theme.GRAY_TEXT))

        for owner, st in active_stations:
            busy = bool(st.get("busy_until")) and st["busy_until"] > now
            status_label = "Indisponível" if busy else "Sinal forte"
            status_bg = theme.RED if busy else theme.GREEN

            def handler(e, name=st["name"], owner_email=owner, is_busy=busy):
                if is_busy:
                    self._show_snack("Estação indisponível no momento.")
                else:
                    self.select_charger(name, owner_email)

            cards.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text(st["name"], weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
                                    ft.Text(f"{st.get('power', '')} kW · {st.get('price', '')}/kWh",
                                            size=11, color=theme.GRAY_TEXT),
                                ], spacing=2, expand=True,
                            ),
                            badge(status_label, bg=status_bg, width=90),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    bgcolor=theme.WHITE, border_radius=5, padding=15, height=70,
                    on_click=handler,
                    ink=not busy,
                )
            )

        return ft.Container(content=ft.ListView(cards, spacing=15, padding=20, expand=True), expand=True)

    def select_charger(self, name, owner):
        """Guarda qual carregador foi escolhido (nome + e-mail do vendedor
        dono, necessário porque nomes de estação não são únicos entre
        contas) e avança para a etapa de configuração da recarga."""
        self.charger_selected = name
        self.charger_owner = owner
        self.recarga_step = "step_setup"
        self.show_consumer()

    def _station_rate_per_minute(self):
        """Preço (R$) de cada minuto de recarga no carregador selecionado."""
        station = self._find_selected_station()
        price_per_kwh = parse_currency(station.get("price")) if station else 2.0
        power_kw = parse_float(station.get("power") if station else None, default=50.0)
        return (power_kw / 60.0) * price_per_kwh

    def recarga_step_setup(self):
        """Etapa 3: o consumidor define a recarga de duas formas possíveis,
        alternadas pelo botão "Por tempo"/"Por valor" (`self.recharge_mode`):
        - "tempo": digita os minutos e o valor a pagar é calculado a partir
          da tarifa por minuto (`_station_rate_per_minute`);
        - "valor": digita quanto quer pagar e os minutos equivalentes são
          calculados invertendo a mesma conta.
        Em ambos os casos, o campo abaixo mostra uma prévia calculada em
        tempo real, mas o valor definitivo só é fixado ao avançar
        (`_confirm_setup`), evitando recalcular a cada tecla digitada."""
        def on_minutes_change(e):
            self.recharge_minutes = e.control.value

        def on_value_change(e):
            self.recharge_value = e.control.value

        def set_mode(mode):
            self.recharge_mode = mode
            self.show_consumer()

        btn_tempo = flat_button(
            "Por tempo", bg=theme.RED if self.recharge_mode == "tempo" else theme.WHITE,
            fg=theme.WHITE if self.recharge_mode == "tempo" else theme.GRAY_TEXT,
            on_click=lambda e: set_mode("tempo"), height=45, expand=True,
        )
        btn_valor = flat_button(
            "Por valor", bg=theme.RED if self.recharge_mode == "valor" else theme.WHITE,
            fg=theme.WHITE if self.recharge_mode == "valor" else theme.GRAY_TEXT,
            on_click=lambda e: set_mode("valor"), height=45, expand=True,
        )

        rate = self._station_rate_per_minute()

        if self.recharge_mode == "tempo":
            field_label = "Tempo de recarga (minutos)"
            input_field = ft.TextField(
                value=self.recharge_minutes, height=50, bgcolor=theme.WHITE, color=theme.TEXT_COLOR,
                border_color=theme.LIGHT_GRAY, border_radius=5,
                content_padding=ft.Padding(left=15, right=15),
                keyboard_type=ft.KeyboardType.NUMBER, on_change=on_minutes_change,
            )
            minutes_preview = parse_int(self.recharge_minutes, default=30)
            preview_text = f"Valor estimado: {format_currency(minutes_preview * rate)}"
        else:
            field_label = "Valor a pagar (R$)"
            input_field = ft.TextField(
                value=self.recharge_value, height=50, bgcolor=theme.WHITE, color=theme.TEXT_COLOR,
                border_color=theme.LIGHT_GRAY, border_radius=5,
                content_padding=ft.Padding(left=15, right=15),
                keyboard_type=ft.KeyboardType.NUMBER, on_change=on_value_change,
            )
            valor_preview = parse_currency(self.recharge_value)
            minutes_preview = int(round(valor_preview / rate)) if rate > 0 else 0
            preview_text = f"Tempo estimado: {max(minutes_preview, 0)} min"

        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(f"{self.charger_selected or 'Estação'} - escolha como definir sua recarga.",
                            color="#555555"),
                    ft.Row([btn_tempo, btn_valor], spacing=0),
                    ft.Text(field_label, size=12, color=theme.GRAY_TEXT),
                    input_field,
                    ft.Text(preview_text, size=11, color=theme.GRAY_TEXT),
                    flat_button("Continuar", theme.RED, theme.WHITE, on_click=self._confirm_setup),
                ],
                spacing=20,
                scroll=ft.ScrollMode.AUTO,
            ),
            padding=20,
        )

    def _confirm_setup(self, e):
        """Fixa os minutos e o valor final da recarga a partir do modo ativo
        (tempo ou valor), normalizando ambos pra um mínimo de 1 minuto/valor
        positivo, e avança para a tela de resumo."""
        rate = self._station_rate_per_minute()

        if self.recharge_mode == "tempo":
            minutes = max(parse_int(self.recharge_minutes, default=30), 1)
            valor = minutes * rate
        else:
            valor = max(parse_currency(self.recharge_value), 0.0)
            minutes = max(int(round(valor / rate)), 1) if rate > 0 else 1

        self.recharge_minutes = str(minutes)
        self.recharge_valor = valor
        self.recarga_step = "step_summary"
        self.show_consumer()

    def recarga_step_summary(self):
        """Etapa 4: confirma carregador, tempo e valor final antes do
        pagamento — puramente informativa, sem cálculo novo."""
        resumo_card = card(
            [
                ft.Text("RESUMO", size=10, color=theme.GRAY_TEXT),
                ft.Row(
                    [
                        ft.Text("Carregador\nTempo escolhido", size=12, color="#555555"),
                        ft.Text(f"{self.charger_selected or 'Estação 01'}\n{self.recharge_minutes} min",
                                size=12, color=theme.TEXT_COLOR, text_align=ft.TextAlign.RIGHT),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                ft.Row(
                    [
                        ft.Text("Valor final", color=theme.GRAY_TEXT),
                        ft.Text(format_currency(self.recharge_valor), size=20,
                                weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
            ],
            height=120,
        )
        return ft.Container(
            content=ft.Column(
                [resumo_card, flat_button("Pagar com Pix", theme.RED, theme.WHITE,
                                           on_click=lambda e: self._go_recarga_step("step_qr"))],
                spacing=20,
            ),
            padding=20,
        )

    def recarga_step_qr(self):
        """Etapa 5: pagamento via Pix simulado — o "código" copiado é fixo e
        fictício (não gera cobrança real). Confirmar o pagamento chama
        `start_charging`, que só então marca a estação como ocupada."""
        qr_box = ft.Container(
            width=150,
            height=150,
            bgcolor=theme.WHITE,
            border=ft.Border.all(width=1, color=theme.LIGHT_GRAY),
            alignment=ft.Alignment(0, 0),
            content=ft.Text("QR CODE", size=14, color=theme.GRAY_TEXT),
        )

        def copy_pix(e):
            self.page.set_clipboard(
                "00020126580014BR.GOV.BCB.PIX-CHARGEGRID-DEMO5204000053039865405 44.905802BR"
            )
            self._show_snack("Código Pix copiado.")

        return ft.Container(
            content=ft.Column(
                [
                    qr_box,
                    ft.Text(format_currency(self.recharge_valor), size=18, weight=ft.FontWeight.BOLD,
                            color=theme.TEXT_COLOR, text_align=ft.TextAlign.CENTER),
                    ft.Text(
                        "Escaneie o QR Code com o app do seu banco ou copie o código Pix para "
                        "concluir o pagamento.",
                        size=12, color=theme.GRAY_TEXT, text_align=ft.TextAlign.CENTER,
                    ),
                    flat_button("Copiar código Pix", theme.WHITE, theme.TEXT_COLOR, on_click=copy_pix),
                    flat_button("Pagamento Efetuado", theme.RED, theme.WHITE, on_click=self.start_charging),
                ],
                spacing=15, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding(left=30, right=30, top=50, bottom=30),
        )

    def start_charging(self, e=None):
        """Inicia a simulação da recarga: 1 segundo real representa 1 minuto simulado.
        Enquanto a recarga estiver ativa, a estação escolhida fica indisponível para
        outros consumidores, voltando a ficar disponível automaticamente ao final.
        A contagem roda como uma tarefa assíncrona presa ao loop de eventos do Flet
        (page.run_task), então a tela se atualiza sozinha a cada segundo, sem que o
        usuário precise tocar em nada."""
        total = max(parse_int(self.recharge_minutes, default=30), 1)
        self.charge_total_minutes = total
        self.charge_remaining_minutes = total
        self._charge_cancel = False

        station = self._find_selected_station()
        if station:
            station["busy_until"] = time.time() + total
            DataManager.save_data(self.data)

        self.recarga_step = "step_active"
        self.show_consumer()

        self.page.run_task(self._run_charge_timer)

    async def _run_charge_timer(self):
        """Laço assíncrono da simulação de carga: dorme 1 segundo (equivalente
        a 1 minuto simulado), decrementa o tempo restante e redesenha a tela
        — mas só se o consumidor ainda estiver olhando pra etapa "carga
        ativa", pra não forçar redesenhos desnecessários caso ele tenha
        navegado pra outra aba enquanto carrega. Termina sozinho quando o
        tempo acaba (`_complete_charge(auto=True)`) ou quando `finish_charge`
        seta `self._charge_cancel = True` (encerramento manual)."""
        while not self._charge_cancel and self.charge_remaining_minutes > 0:
            await asyncio.sleep(1)
            if self._charge_cancel:
                return
            self.charge_remaining_minutes -= 1
            if self.consumer_tab == "tab_recarga" and self.recarga_step == "step_active":
                try:
                    self.show_consumer()
                except Exception:
                    pass
        if not self._charge_cancel:
            self._complete_charge(auto=True)

    def recarga_step_active(self):
        """Etapa 6: tela da carga em andamento, com barra de progresso e
        kWh entregues calculados a partir do tempo já decorrido
        (`total - remaining`) e da potência da estação — não há medição
        real, é só a simulação proporcional ao tempo simulado."""
        total = max(self.charge_total_minutes, 1)
        remaining = max(self.charge_remaining_minutes, 0)
        elapsed = total - remaining
        power_kw = parse_float(
            (self._find_selected_station() or {}).get("power"), default=50.0
        )
        kwh_so_far = (power_kw / 60.0) * elapsed
        progress = elapsed / total if total else 0

        status_card = card(
            [
                ft.Text("⚡", size=30, color=theme.RED),
                ft.Text("Carga sendo efetuada", weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
                ft.ProgressBar(value=progress, color=theme.RED, bgcolor=theme.LIGHT_GRAY, height=10, border_radius=0),
                ft.Text(
                    f"Faltam {remaining} minuto(s)" if remaining > 0 else "Finalizando...",
                    weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR, text_align=ft.TextAlign.CENTER,
                ),
                ft.Text(f"{self.charger_selected or 'Estação'} - {kwh_so_far:.1f} kWh entregues",
                        size=10, color=theme.GRAY_TEXT, text_align=ft.TextAlign.CENTER),
            ],
            height=190, padding=20,
        )
        return ft.Container(
            content=ft.Column(
                [status_card, flat_button("Encerrar recarga", theme.RED, theme.WHITE, on_click=self.finish_charge)],
                spacing=20,
            ),
            padding=20,
        )

    def finish_charge(self, e):
        """Botão "Encerrar recarga": termina a carga antes do tempo total,
        cobrando apenas pelo tempo realmente decorrido."""
        self._complete_charge(auto=False)

    def _complete_charge(self, auto=False):
        """Fecha a recarga (seja por tempo esgotado, `auto=True`, seja por
        encerramento manual): calcula o kWh e o valor cobrado com base no
        tempo decorrido, grava um novo item no histórico do consumidor
        (marcando `owner` com o e-mail do vendedor dono da estação, usado
        depois para calcular a receita/histórico do vendedor), libera a
        estação (`busy_until = None`) e volta para a aba Início."""
        self._charge_cancel = True
        total = max(self.charge_total_minutes, 0)
        remaining = max(self.charge_remaining_minutes, 0)
        elapsed = max(total - remaining, 0)

        station = self._find_selected_station()
        price_per_kwh = parse_currency(station.get("price")) if station else 2.0
        power_kw = parse_float(station.get("power") if station else None, default=50.0)
        kwh = (power_kw / 60.0) * elapsed
        valor = kwh * price_per_kwh

        if self.current_user and self.current_user in self.data["users"]:
            new_entry = {
                "local": self.charger_selected or "Estação",
                "owner": self.charger_owner,
                "data": time.strftime("%d %b, %H:%M").lower(),
                "timestamp": time.time(),
                "kwh": f"{kwh:.1f} kWh",
                "valor": format_currency(valor),
                "status": "Pago",
            }
            self.data["users"][self.current_user].setdefault("history", [])
            self.data["users"][self.current_user]["history"].insert(0, new_entry)

        if station:
            station["busy_until"] = None

        DataManager.save_data(self.data)

        self.consumer_tab = "tab_inicio"
        self.recarga_step = "step_bt"
        self.charger_selected = None
        self.charger_owner = None
        self.charge_total_minutes = 0
        self.charge_remaining_minutes = 0

        if self.current_role == "consumer" and self.current_user:
            self.show_consumer()
        if auto:
            self._show_snack("Recarga concluída!")

    # ---------------- TAB HISTÓRICO ----------------
    def consumer_historico(self):
        """Lista as recargas reais do usuário logado (não mostra dados de
        exemplo/fictícios: se o histórico estiver vazio, mostra uma mensagem
        de estado vazio em vez de dados fictícios)."""
        history = []
        if self.current_user and self.current_user in self.data["users"]:
            history = self.data["users"][self.current_user].get("history", [])

        if not history:
            return ft.Container(
                content=ft.Text(
                    "Nenhuma recarga realizada ainda.", size=13, color=theme.GRAY_TEXT,
                    text_align=ft.TextAlign.CENTER,
                ),
                alignment=ft.Alignment(0, 0),
                padding=40, expand=True,
            )

        cards = [self._history_card(item) for item in history]
        return ft.Container(content=ft.ListView(cards, spacing=15, padding=20, expand=True), expand=True)

    def _history_card(self, item):
        """Um cartão de recarga no histórico. `item["status"]` é sempre
        "Pago" nesta versão (não há fluxo de pagamento pendente), então o
        badge verde é o único caminho exercitado hoje."""
        status_bg = theme.GREEN if item["status"] == "Pago" else theme.RED
        return ft.Container(
            content=ft.Row(
                [
                    ft.Column(
                        [
                            ft.Text(item["local"], weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
                            ft.Text(f"{item['data']} · {item['kwh']}", size=12, color=theme.GRAY_TEXT),
                        ], spacing=2, expand=True,
                    ),
                    ft.Column(
                        [
                            ft.Text(item["valor"], weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
                            badge(item["status"], bg=status_bg),
                        ], spacing=5, horizontal_alignment=ft.CrossAxisAlignment.END,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            bgcolor=theme.WHITE, border_radius=5, padding=15, height=80,
        )

    # ---------------- TAB CHAT ----------------
    def consumer_chat(self):
        """Chat de suporte simulado: histórico de mensagens fixo em
        `self.chat_messages` (não persiste entre sessões nem chama nenhum
        serviço de IA real). Mensagens do bot aparecem à esquerda em cinza,
        do usuário à direita em vermelho."""
        def on_chat_change(e):
            self.chat_draft = e.control.value

        bubbles = []
        for msg in self.chat_messages:
            if msg["from"] == "bot":
                bubbles.append(
                    ft.Container(
                        content=ft.Text(msg["text"], color=theme.TEXT_COLOR, size=13),
                        bgcolor=theme.LIGHT_GRAY, border_radius=5, padding=10,
                    )
                )
            else:
                bubbles.append(
                    ft.Row(
                        [
                            ft.Container(
                                content=ft.Text(msg["text"], color=theme.WHITE, size=13,
                                                 text_align=ft.TextAlign.CENTER),
                                bgcolor=theme.RED, border_radius=5, padding=10, width=260,
                            )
                        ],
                        alignment=ft.MainAxisAlignment.END,
                    )
                )

        suggestions = ft.Row(
            [pill("Resumo da última recarga"), pill("Ajuda com pagamento")],
            spacing=10, wrap=True,
        )

        messages_view = ft.ListView(bubbles + [suggestions], spacing=15, padding=20, expand=True)

        chat_field = ft.TextField(
            value=self.chat_draft, hint_text="Digite sua mensagem", expand=True, height=50,
            bgcolor=theme.WHITE, color=theme.TEXT_COLOR, border_color=theme.LIGHT_GRAY,
            content_padding=ft.Padding(left=15,right=15),
            on_change=on_chat_change, on_submit=self.send_chat_message,
        )

        input_row = ft.Container(
            content=ft.Row(
                [
                    chat_field,
                    ft.Container(
                        content=ft.Text("▶", color=theme.WHITE, size=16),
                        bgcolor=theme.RED, width=50, height=50, alignment=ft.Alignment(0, 0),
                        on_click=self.send_chat_message,
                    ),
                ],
                spacing=10,
            ),
            bgcolor=theme.WHITE, padding=ft.Padding(left=15,right=15,top=10,bottom=10), height=70,
        )

        return ft.Column([ft.Container(content=messages_view, expand=True), input_row], spacing=0, expand=True)

    def send_chat_message(self, e):
        """Envia a mensagem digitada e responde com uma resposta fixa
        (o "bot" não interpreta o conteúdo, só confirma o recebimento)."""
        text = (self.chat_draft or "").strip()
        if not text:
            return
        self.chat_messages.append({"from": "user", "text": text})
        self.chat_messages.append({
            "from": "bot",
            "text": "Entendido! Já registrei sua mensagem — posso ajudar em mais alguma coisa?",
        })
        self.chat_draft = ""
        self.show_consumer()

    # ---------------- TAB CONTA ----------------
    def consumer_conta(self):
        """Aba Conta do consumidor. Tem dois estados internos controlados por
        `self.consumer_conta_view` (não é uma aba de verdade, mas evita criar
        uma tela separada para uma sub-tela simples):
        - "view" (padrão): dados cadastrais somente leitura, campo de
          localização e o interruptor de modo escuro;
        - "edit": formulário para alterar nome/telefone/veículo/chave Pix
          (ver `consumer_edit_profile`).
        Telefone/veículo/chave Pix têm valores padrão fictícios quando a
        conta ainda não os definiu explicitamente."""
        if self.consumer_conta_view == "edit":
            return self.consumer_edit_profile()

        user_name = "Marina Souza"
        user_email = "marina.souza@email.com"
        phone = "(11) 98888-2211"
        vehicle = "BYD Dolphin · ABC-1D23 · CCS2"
        pix_key = "marina.souza@pix.com"
        saved_location = None
        if self.current_user and self.current_user in self.data["users"]:
            user = self.data["users"][self.current_user]
            user_name = user["name"]
            user_email = self.current_user
            phone = user.get("phone", phone)
            vehicle = user.get("vehicle", vehicle)
            pix_key = user.get("pix_key", f"{self.current_user.split('@')[0]}@pix.com")
            saved_location = user.get("location")

        if self.location_draft is None:
            self.location_draft = (saved_location or {}).get("address", "")

        def field(label, value):
            return ft.Column([ft.Text(label, size=11, color=theme.GRAY_TEXT), ft.Text(value, color=theme.TEXT_COLOR)],
                              spacing=2)

        edit_btn = ft.Container(
            content=ft.Text(
                "Editar informações",
                weight=ft.FontWeight.BOLD,
                color=theme.TEXT_COLOR,
                text_align=ft.TextAlign.CENTER,
            ),
            bgcolor=theme.LIGHT_GRAY,
            border=ft.Border.all(width=1, color=theme.LIGHT_GRAY),
            border_radius=5,
            height=50,
            alignment=ft.Alignment(0, 0),
            on_click=self.open_edit_profile,
        )

        def on_location_change(e):
            self.location_draft = e.control.value

        has_saved_location = bool(saved_location and saved_location.get("lat") is not None)
        if has_saved_location:
            location_status = f"Localização salva: {saved_location.get('address') or 'endereço definido'}"
        else:
            location_status = "Nenhuma localização definida ainda — usada como reserva quando " \
                               "não for possível localizar você automaticamente."

        location_children = [
            ft.Text("Localização", size=11, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
        ]
        if has_saved_location:
            location_children.append(
                map_widget(saved_location["lat"], saved_location["lng"], [], height=160, zoom=15)
            )
        location_children += [
            labeled_field(
                "Endereço, cidade ou CEP", value=self.location_draft,
                hint="Ex: Av. Paulista, 1000, São Paulo - SP", on_change=on_location_change,
            ),
            flat_button("Salvar localização", theme.RED, theme.WHITE, on_click=self.save_location),
            ft.Text(location_status, size=11, color=theme.GRAY_TEXT),
        ]

        location_section = ft.Column(location_children, spacing=10)

        return ft.Container(
            content=ft.ListView(
                [
                    field("Nome", user_name),
                    field("E-mail", user_email),
                    field("Telefone", phone),
                    field("Veículo", vehicle),
                    field("Chave Pix", pix_key),
                    edit_btn,
                    location_section,
                    self._dark_mode_section(),
                ],
                spacing=20, padding=20, expand=True,
            ),
            expand=True,
        )

    def open_edit_profile(self, e):
        """Copia os dados atuais da conta para `self.profile_form` (rascunho
        editável) e troca a aba Conta para o modo de edição."""
        user = self.data["users"].get(self.current_user, {}) if self.current_user else {}
        self.profile_form = {
            "name": user.get("name", ""),
            "phone": user.get("phone", "(11) 98888-2211"),
            "vehicle": user.get("vehicle", "BYD Dolphin · ABC-1D23 · CCS2"),
            "pix_key": user.get("pix_key", f"{self.current_user.split('@')[0]}@pix.com" if self.current_user else ""),
        }
        self.consumer_conta_view = "edit"
        self.show_consumer()

    def consumer_edit_profile(self):
        """Formulário de edição: cada campo escreve direto em
        `self.profile_form`, só persistido no JSON quando "Salvar
        alterações" é clicado (`save_profile`)."""
        def upd(field_name):
            def handler(e):
                self.profile_form[field_name] = e.control.value
            return handler

        controls = [
            ft.Text("Editar informações", size=18, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
            labeled_field("Nome", value=self.profile_form.get("name", ""), on_change=upd("name")),
            labeled_field("Telefone", value=self.profile_form.get("phone", ""), on_change=upd("phone")),
            labeled_field("Veículo", value=self.profile_form.get("vehicle", ""), on_change=upd("vehicle")),
            labeled_field("Chave Pix", value=self.profile_form.get("pix_key", ""), on_change=upd("pix_key")),
            flat_button("Salvar alterações", theme.RED, theme.WHITE, on_click=self.save_profile),
            flat_button("Cancelar", theme.WHITE, theme.TEXT_COLOR, on_click=self.cancel_edit_profile),
        ]
        return ft.Container(content=ft.ListView(controls, spacing=12, padding=20, expand=True), expand=True)

    def save_profile(self, e):
        """Grava o rascunho de `self.profile_form` na conta do usuário (exige
        pelo menos um nome não vazio) e volta para o modo de visualização."""
        name = (self.profile_form.get("name") or "").strip()
        if not name:
            self._show_snack("Informe um nome.")
            return
        if self.current_user and self.current_user in self.data["users"]:
            self.data["users"][self.current_user]["name"] = name
            self.data["users"][self.current_user]["phone"] = self.profile_form.get("phone", "")
            self.data["users"][self.current_user]["vehicle"] = self.profile_form.get("vehicle", "")
            self.data["users"][self.current_user]["pix_key"] = self.profile_form.get("pix_key", "")
            DataManager.save_data(self.data)
        self.consumer_conta_view = "view"
        self._show_snack("Informações atualizadas!")
        self.show_consumer()

    def cancel_edit_profile(self, e):
        """Descarta o rascunho e volta para a visualização normal da conta."""
        self.consumer_conta_view = "view"
        self.show_consumer()

    async def save_location(self, e):
        """Resolve coordenadas para o texto digitado (endereço livre ou CEP
        de 8 dígitos, detectado automaticamente) e grava como a localização
        de referência da conta. Se o texto for um CEP, primeiro busca o
        endereço completo via `lookup_cep` para melhorar a precisão da
        geocodificação (endereço completo tende a bater com um ponto mais
        exato do que apenas os dígitos do CEP)."""
        text = (self.location_draft or "").strip()
        if not text:
            self._show_snack("Informe um endereço ou CEP.")
            return

        self._show_snack("Buscando coordenadas...")

        endereco = text
        digits = re.sub(r"\D", "", text)
        if len(digits) == 8:
            cep_info = await asyncio.to_thread(lookup_cep, digits)
            if cep_info:
                endereco = cep_info["endereco"]

        coords = await asyncio.to_thread(geocode_address, f"{endereco}, Brasil")
        if not coords:
            self._show_snack("Não foi possível localizar esse endereço/CEP.")
            return

        lat, lng = coords
        if self.current_user and self.current_user in self.data["users"]:
            self.data["users"][self.current_user]["location"] = {
                "address": endereco, "lat": lat, "lng": lng,
            }
            DataManager.save_data(self.data)

        self.consumer_live_location = None  # força reavaliar (vai priorizar a conta agora)
        self._show_snack("Localização salva!")
        self.show_consumer()

    # ==============================================================
    # MÓDULO VENDEDOR (RETAILER)
    # ==============================================================
    def show_retailer(self):
        """Monta a casca do app do vendedor. O cabeçalho muda de acordo com o
        estado de navegação: dentro de uma sub-tela (editar/criar estação ou
        cupom) mostra um botão "<" de voltar no lugar de "Sair", já que ali
        faz mais sentido voltar para a listagem do que encerrar a sessão."""
        in_subscreen = (
            (self.retailer_tab == "tab_estacoes" and self.estacoes_view == "edit_station")
            or (self.retailer_tab == "tab_descontos" and self.descontos_view == "add_coupon")
        )

        if in_subscreen:
            left = ft.Container(
                content=ft.Text("<", size=20, color=theme.TEXT_COLOR),
                width=30, on_click=self.go_back_subscreen,
            )
            right = ft.Container(width=40)
        else:
            left = ft.Container(width=30)
            right = ft.Container(
                content=ft.Text(
                    "Sair", size=14, color=theme.TEXT_COLOR,
                    style=ft.TextStyle(decoration=ft.TextDecoration.UNDERLINE),
                ),
                on_click=self.logout,
            )

        header = ft.Container(
            content=ft.Row(
                [left, ft.Text("#ffive", size=20, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR, expand=True), right],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            height=60, padding=ft.Padding(  left=20, right=20, top = 10, bottom = 10,),
        )

        content_area = ft.Container(content=self.render_retailer_tab(), expand=True)

        bottom_nav = ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        height=1,
                        bgcolor=theme.LIGHT_GRAY,
                    ),
                    ft.Row(
                        [
                            self._nav_btn("/icons/home_icon.png", "/icons/home_icon_fill.png", "Início",
                                          self.retailer_tab == "tab_inicio",
                                          lambda e: self.switch_retailer_tab("tab_inicio")),
                            self._nav_btn("/icons/estacao_icon.png", "/icons/estacao_icon_fill.png", "Estações",
                                          self.retailer_tab == "tab_estacoes",
                                          lambda e: self.switch_retailer_tab("tab_estacoes")),
                            self._nav_btn("/icons/historico_icon.png", "/icons/historico_icon_fill.png", "Histórico",
                                          self.retailer_tab == "tab_historico",
                                          lambda e: self.switch_retailer_tab("tab_historico")),
                            self._nav_btn("/icons/desconto_icon.png", "/icons/desconto_icon_fill.png", "Descontos",
                                          self.retailer_tab == "tab_descontos",
                                          lambda e: self.switch_retailer_tab("tab_descontos")),
                            self._nav_btn("/icons/profile_icon.png", "/icons/profile_icon_fill.png", "Conta",
                                          self.retailer_tab == "tab_conta",
                                          lambda e: self.switch_retailer_tab("tab_conta")),
                        ],
                        spacing=0,
                        expand=True,
                    ),
                ],
                spacing=0,
            ),
            height=61,
            bgcolor=theme.WHITE,
        )

        self.root.content = ft.Column([header, content_area, bottom_nav], spacing=0, expand=True)
        self.page.update()

    def switch_retailer_tab(self, tab):
        """Troca a aba ativa do vendedor, sempre voltando as sub-telas de
        Estações/Descontos para a listagem (evita reabrir a aba já dentro
        de um formulário de edição de uma navegação anterior)."""
        self.retailer_tab = tab
        self.estacoes_view = "list_stations"
        self.descontos_view = "list_coupons"
        self.show_retailer()

    def go_back_subscreen(self, e):
        """Botão "<" do cabeçalho: volta da tela de formulário (estação ou
        cupom) para a listagem da aba correspondente, sem trocar de aba."""
        if self.retailer_tab == "tab_estacoes":
            self.estacoes_view = "list_stations"
        elif self.retailer_tab == "tab_descontos":
            self.descontos_view = "list_coupons"
        self.show_retailer()

    def render_retailer_tab(self):
        """Despacha para a função que constrói o conteúdo da aba/sub-tela ativa."""
        if self.retailer_tab == "tab_inicio":
            return self.retailer_home()
        if self.retailer_tab == "tab_estacoes":
            return self.retailer_station_list() if self.estacoes_view == "list_stations" \
                else self.retailer_station_form()
        if self.retailer_tab == "tab_historico":
            return self.retailer_historico()
        if self.retailer_tab == "tab_descontos":
            return self.coupon_list() if self.descontos_view == "list_coupons" else self.coupon_form()
        if self.retailer_tab == "tab_conta":
            return self.retailer_conta()
        return ft.Container()

    # ---------------- TAB INÍCIO (vendedor) ----------------
    def retailer_home(self):
        """Painel inicial do vendedor: receita total (soma de todas as
        recargas feitas nas estações desta conta, via `_total_received`) e
        um atalho pra gerenciar a primeira estação cadastrada — não lista
        todas aqui, só na aba Estações."""
        stations = self._retailer_stations()
        main_station = stations[0] if stations else None

        items = [
            ft.Text("Painel do vendedor", size=18, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
            ft.Text("Valor recebido", size=12, color=theme.TEXT_COLOR),
            card([ft.Text(format_currency(self._total_received()), size=22,
                          weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR)],
                 height=60, padding=ft.Padding( left=20, right=20, top = 10, bottom = 10)),
            ft.Text("Suas estações", size=12, color=theme.TEXT_COLOR),
        ]

        if main_station:
            items.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text(main_station["name"], weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
                                    ft.Text(
                                        f"Até {main_station.get('max_time', '-')} min de carga · "
                                        f"{main_station['power']} kW",
                                        size=11, color=theme.GRAY_TEXT,
                                    ),
                                ], spacing=2, expand=True,
                            ),
                            ft.Container(
                                content=ft.Text("Gerenciar", weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
                                on_click=lambda e: self.open_config_station(0),
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    bgcolor=theme.WHITE, border_radius=5, padding=15, height=80,
                )
            )
        else:
            items.append(ft.Text("Você ainda não cadastrou nenhuma estação.", size=12, color=theme.GRAY_TEXT))

        items.append(flat_button("+ Adicionar estação", theme.RED, theme.WHITE, on_click=self.open_add_station))

        return ft.Container(content=ft.ListView(items, spacing=20, padding=20, expand=True), expand=True)

    # ---------------- TAB ESTAÇÕES ----------------
    def open_add_station(self, e):
        """Abre o formulário de estação vazio (modo "criar"). `editing_station_index
        = None` é o que diferencia esse modo do de edição em `retailer_station_form`."""
        self.retailer_tab = "tab_estacoes"
        self.estacoes_view = "edit_station"
        self.editing_station_index = None
        self.station_form_data = {
            "name": "", "cep": "", "endereco": "", "cidade": "", "uf": "",
            "lat": None, "lng": None, "max_time": "60", "power": "50",
            "price": "R$ 2,00", "active": True, "busy_until": None,
        }
        self.show_retailer()

    def open_config_station(self, index):
        """Abre o formulário pré-preenchido com os dados da estação no
        índice `index` (modo "editar"). Copia o dicionário (`dict(...)`) em
        vez de referenciar o original, para que os campos digitados no
        formulário não alterem a estação real até "Salvar alterações"."""
        self.retailer_tab = "tab_estacoes"
        self.estacoes_view = "edit_station"
        self.editing_station_index = index
        self.station_form_data = dict(self._retailer_stations()[index])
        self.show_retailer()

    def retailer_station_list(self):
        """Lista as estações da conta logada, cada uma com atalhos para
        configurar (abre o formulário) ou remover diretamente."""
        stations = self._retailer_stations()
        items = [flat_button("+ Adicionar estação", theme.RED, theme.WHITE, on_click=self.open_add_station)]

        if not stations:
            items.append(
                ft.Text("Você ainda não cadastrou nenhuma estação. Toque em \"+ Adicionar estação\" "
                        "para começar.", size=12, color=theme.GRAY_TEXT)
            )

        for idx, st in enumerate(stations):
            configure_btn = ft.Container(
                content=ft.Text("✎ Configurar", color=theme.TEXT_COLOR, size=13),
                bgcolor=theme.WHITE,
                border=ft.Border.all(width=1, color=theme.LIGHT_GRAY),
                border_radius=5,
                alignment=ft.Alignment(0, 0),
                expand=True,
                height=40,
                on_click=lambda e, i=idx: self.open_config_station(i),
            )
            delete_btn = ft.Container(
                content=ft.Text("🗑", size=16, color=theme.TEXT_COLOR),
                width=40, height=40, alignment=ft.Alignment(0, 0),
                on_click=lambda e, i=idx: self.delete_station(i),
            )
            items.append(
                card(
                    [
                        ft.Text(st["name"], weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
                        ft.Text(f"Até {st.get('max_time', '-')} min de carga · {st['power']} kW",
                                size=11, color=theme.GRAY_TEXT),
                        ft.Text(st.get("endereco") or "CEP não informado", size=11, color=theme.GRAY_TEXT),
                        ft.Row([configure_btn, delete_btn], spacing=10),
                    ],
                    height=130,
                )
            )

        return ft.Container(content=ft.ListView(items, spacing=15, padding=20, expand=True), expand=True)

    def delete_station(self, index):
        """Remove a estação de índice `index` (sem confirmação adicional —
        o botão de lixeira já é a ação direta) e persiste a mudança."""
        stations = self._retailer_stations()
        if 0 <= index < len(stations):
            stations.pop(index)
            DataManager.save_data(self.data)
        self.show_retailer()

    def retailer_station_form(self):
        """Formulário de criar/editar estação, compartilhado pelos dois modos
        (`editing` diferencia se é criação ou edição, controlado pelo valor
        de `self.editing_station_index`). O único campo de endereço é o CEP:
        ao perder o foco (`on_cep_blur`), busca a rua/bairro/cidade via
        ViaCEP e depois geocodifica esse endereço para lat/lng via Nominatim
        — os dois passos em sequência, porque geocodificar o endereço
        completo dá um ponto mais preciso do que geocodificar só o CEP."""
        editing = self.editing_station_index is not None

        def upd(field_name):
            def handler(e):
                self.station_form_data[field_name] = e.control.value
            return handler

        def toggle_status(active):
            self.station_form_data["active"] = active
            self.show_retailer()

        async def on_cep_blur(e):
            digits = re.sub(r"\D", "", self.station_form_data.get("cep", "") or "")
            if len(digits) != 8:
                if digits:
                    self._show_snack("CEP deve ter 8 dígitos.")
                return

            self._show_snack("Buscando endereço pelo CEP...")
            info = await asyncio.to_thread(lookup_cep, digits)
            if not info:
                self._show_snack("CEP não encontrado.")
                return

            self.station_form_data["endereco"] = info["endereco"]
            self.station_form_data["cidade"] = info["cidade"]
            self.station_form_data["uf"] = info["uf"]

            coords = await asyncio.to_thread(geocode_address, f"{info['endereco']}, Brasil")
            if coords:
                self.station_form_data["lat"], self.station_form_data["lng"] = coords
            else:
                self.station_form_data["lat"] = None
                self.station_form_data["lng"] = None
                self._show_snack("Endereço encontrado, mas não foi possível localizar no mapa.")

            self.show_retailer()

        active = self.station_form_data.get("active", True)
        btn_active = flat_button("Ativa", bg=theme.RED if active else theme.WHITE, fg=theme.WHITE if active else theme.GRAY_TEXT,
                                  on_click=lambda e: toggle_status(True), height=45, expand=True)
        btn_inactive = flat_button("Inativa", bg=theme.RED if not active else theme.WHITE,
                                    fg=theme.WHITE if not active else theme.GRAY_TEXT,
                                    on_click=lambda e: toggle_status(False), height=45, expand=True)

        endereco_resolvido = self.station_form_data.get("endereco")
        endereco_preview = ft.Text(
            endereco_resolvido or "Digite o CEP e toque fora do campo para buscar o endereço automaticamente.",
            size=11, color=theme.TEXT_COLOR if endereco_resolvido else theme.GRAY_TEXT,
        )

        controls = [
            labeled_field("Nome da estação", value=self.station_form_data.get("name", ""), on_change=upd("name")),
            labeled_field("CEP", value=self.station_form_data.get("cep", ""), hint="00000-000",
                           on_change=upd("cep"), on_blur=on_cep_blur),
            endereco_preview,
            labeled_field("Tempo máximo de carga (minutos)", value=self.station_form_data.get("max_time", ""),
                           on_change=upd("max_time")),
            labeled_field("Potência (kW)", value=self.station_form_data.get("power", ""), on_change=upd("power")),
            labeled_field("Preço por kWh", value=self.station_form_data.get("price", ""), on_change=upd("price")),
        ]

        if self.station_form_data.get("lat") is not None:
            controls.append(
                map_widget(
                    self.station_form_data["lat"], self.station_form_data["lng"],
                    [(self.station_form_data["lat"], self.station_form_data["lng"], "⚡")],
                    height=180, zoom=15, center_glyph=None,
                )
            )

        controls += [
            ft.Text("Status", size=11, color=theme.GRAY_TEXT),
            ft.Row([btn_active, btn_inactive], spacing=0),
            flat_button("Salvar alterações", theme.RED, theme.WHITE, on_click=self.save_station_and_back),
        ]
        if editing:
            controls.append(flat_button("Remover estação", theme.WHITE, theme.TEXT_COLOR,
                                         on_click=self.remove_station_and_back))

        return ft.Container(content=ft.ListView(controls, spacing=12, padding=20, expand=True), expand=True)

    def save_station_and_back(self, e):
        """Grava (cria ou atualiza, conforme `editing_station_index`) a
        estação a partir do rascunho do formulário e volta pra listagem.
        `busy_until`/`active` recebem um padrão só por segurança — na
        prática sempre chegam preenchidos pelo formulário."""
        values = dict(self.station_form_data)
        values.setdefault("active", True)
        values.setdefault("busy_until", None)
        if not values.get("name", "").strip():
            self._show_snack("Informe o nome da estação.")
            return
        stations = self._retailer_stations()
        if self.editing_station_index is not None:
            stations[self.editing_station_index] = values
        else:
            stations.append(values)
        DataManager.save_data(self.data)
        self.estacoes_view = "list_stations"
        self.show_retailer()

    def remove_station_and_back(self, e):
        """Botão "Remover estação" dentro do formulário de edição (diferente
        do ícone de lixeira da listagem, mas leva ao mesmo resultado)."""
        if self.editing_station_index is not None:
            stations = self._retailer_stations()
            stations.pop(self.editing_station_index)
            DataManager.save_data(self.data)
        self.estacoes_view = "list_stations"
        self.show_retailer()

    # ---------------- TAB HISTÓRICO (vendedor) ----------------
    def retailer_historico(self):
        """Tabela de transações desta conta de vendedor (já filtradas por
        `_all_transactions`, que só traz recargas feitas nas próprias
        estações), com filtro de período aplicado sobre o timestamp de cada
        transação. `expand=N` nas colunas do cabeçalho/linhas define a
        largura proporcional de cada uma (substitui o `size_hint_x` do
        Kivy)."""
        def set_filter(f):
            self.historico_filter = f
            self.show_retailer()

        filters = ft.Row(
            [
                flat_button(
                    label, bg=theme.RED if self.historico_filter == label else theme.WHITE,
                    fg=theme.WHITE if self.historico_filter == label else theme.TEXT_COLOR,
                    on_click=lambda e, l=label: set_filter(l), height=45, expand=True,
                )
                for label in ["Tudo", "7 dias", "30 dias"]
            ],
            spacing=0, width=240,
        )

        header_row = ft.Row(
            [
                ft.Text("Data", size=11, color=theme.GRAY_TEXT, expand=25),
                ft.Text("Estação", size=11, color=theme.GRAY_TEXT, expand=35),
                ft.Text("kWh", size=11, color=theme.GRAY_TEXT, expand=15, text_align=ft.TextAlign.RIGHT),
                ft.Text("Valor", size=11, color=theme.GRAY_TEXT, expand=25, text_align=ft.TextAlign.RIGHT),
            ],
        )

        divider = ft.Container(height=1, bgcolor=theme.LIGHT_GRAY)

        now = time.time()
        period_seconds = {"Tudo": None, "7 dias": 7 * 86400, "30 dias": 30 * 86400}[self.historico_filter]
        txs = self._all_transactions()
        if period_seconds is not None:
            txs = [t for t in txs if t.get("timestamp") and (now - t["timestamp"]) <= period_seconds]

        if txs:
            rows = [
                ft.Row(
                    [
                        ft.Text(t.get("data", "-"), size=11, color=theme.TEXT_COLOR, expand=25),
                        ft.Text(t.get("local", "-"), size=11, color=theme.TEXT_COLOR, expand=35),
                        ft.Text(t.get("kwh", "-"), size=11, color=theme.TEXT_COLOR, expand=15,
                                text_align=ft.TextAlign.RIGHT),
                        ft.Text(t.get("valor", "-"), size=11, color=theme.TEXT_COLOR, expand=25,
                                text_align=ft.TextAlign.RIGHT),
                    ]
                )
                for t in txs
            ]
        else:
            rows = [ft.Text("Nenhuma transação no período selecionado.", size=12, color=theme.GRAY_TEXT)]

        return ft.Container(
            content=ft.Column(
                [
                    filters,
                    header_row,
                    divider,
                    ft.Container(content=ft.ListView(rows, spacing=10, expand=True), expand=True),
                ],
                spacing=15,
            ),
            padding=20, expand=True,
        )

    # ---------------- TAB DESCONTOS ----------------
    def open_add_coupon(self, e):
        """Abre o formulário de novo cupom, bloqueando se a conta ainda não
        tiver nenhuma estação — um cupom sempre precisa apontar para um
        posto (ou "Todos os postos") desta mesma conta."""
        if not self._retailer_stations():
            self._show_snack("Cadastre uma estação antes de criar cupons.")
            return
        self.retailer_tab = "tab_descontos"
        self.descontos_view = "add_coupon"
        self.coupon_form_data = {"code": "", "desc": "", "station": "Todos os postos", "valid": "", "active": True}
        self.show_retailer()

    def coupon_list(self):
        """Lista os cupons da conta logada (não há edição, só criação e
        listagem — cupons não são removíveis nesta versão)."""
        coupons = self._retailer_coupons()
        items = [flat_button("+ Criar cupom", theme.RED, theme.WHITE, on_click=self.open_add_coupon)]

        if not coupons:
            items.append(
                ft.Text("Você ainda não criou nenhum cupom para as suas estações.",
                        size=12, color=theme.GRAY_TEXT)
            )

        for c in coupons:
            items.append(
                card(
                    [
                        ft.Text(c["code"], weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
                        ft.Text(c["desc"], size=12, color="#555555"),
                        ft.Row(
                            [pill(c["station"]), ft.Text(f"Válido até {c['valid']}", size=10, color=theme.GRAY_TEXT)],
                            spacing=10,
                        ),
                    ],
                    height=100,
                )
            )

        return ft.Container(content=ft.ListView(items, spacing=15, padding=20, expand=True), expand=True)

    def coupon_form(self):
        """Formulário de novo cupom. O seletor "Posto" só lista as estações
        desta conta (mais "Todos os postos"), reforçando que um cupom não
        pode ser aplicado a estações de outro vendedor."""
        station_options = ["Todos os postos"] + [s["name"] for s in self._retailer_stations()]

        def upd(field_name):
            def handler(e):
                self.coupon_form_data[field_name] = e.control.value
            return handler

        def on_station_change(e):
            self.coupon_form_data["station"] = e.control.value

        def toggle_status(active):
            self.coupon_form_data["active"] = active
            self.show_retailer()

        active = self.coupon_form_data.get("active", True)
        btn_active = flat_button("Ativo", bg=theme.RED if active else theme.WHITE, fg=theme.WHITE if active else theme.GRAY_TEXT,
                                  on_click=lambda e: toggle_status(True), height=45, expand=True)
        btn_inactive = flat_button("Inativo", bg=theme.RED if not active else theme.WHITE,
                                    fg=theme.WHITE if not active else theme.GRAY_TEXT,
                                    on_click=lambda e: toggle_status(False), height=45, expand=True)

        # Nesta versão do Flet, o Dropdown não aceita 'on_change' no construtor;
        # o handler precisa ser atribuído depois de criar o controle.
        station_dropdown = ft.Dropdown(
            options=[ft.dropdown.Option(o) for o in station_options],
            value=self.coupon_form_data.get("station", station_options[0]),
            bgcolor=theme.WHITE, height=45, color=theme.TEXT_COLOR, border_color=theme.LIGHT_GRAY,
        )
        station_dropdown.on_change = on_station_change

        controls = [
            labeled_field("Código", value=self.coupon_form_data.get("code", ""), hint="Ex: BEMVINDO10",
                           on_change=upd("code")),
            labeled_field("Descrição", value=self.coupon_form_data.get("desc", ""),
                           hint="Ex: 10% na primeira recarga", on_change=upd("desc")),
            ft.Text("Posto", size=11, color=theme.GRAY_TEXT),
            station_dropdown,
            labeled_field("Data de validade", value=self.coupon_form_data.get("valid", ""), hint="dd/mm/aaaa",
                           on_change=upd("valid")),
            ft.Text("Status", size=11, color=theme.GRAY_TEXT),
            ft.Row([btn_active, btn_inactive], spacing=0),
            flat_button("Criar Cupom", theme.RED, theme.WHITE, on_click=self.save_coupon_and_back),
        ]

        return ft.Container(content=ft.ListView(controls, spacing=12, padding=20, expand=True), expand=True)

    def save_coupon_and_back(self, e):
        """Adiciona o cupom à lista da conta logada (exige ao menos um
        código). Não há edição de cupom existente nesta versão — só criação."""
        code = (self.coupon_form_data.get("code") or "").strip()
        if not code:
            self._show_snack("Informe o código do cupom.")
            return
        entry = dict(self.coupon_form_data)
        entry["code"] = code
        entry["valid"] = entry.get("valid") or "-"
        self._retailer_coupons().append(entry)
        DataManager.save_data(self.data)
        self.descontos_view = "list_coupons"
        self.show_retailer()

    # ---------------- TAB CONTA (vendedor) ----------------
    def retailer_conta(self):
        """Dados cadastrais da empresa (nome/CNPJ) e bancários — sempre os
        mesmos valores fixos nesta versão (os botões "Editar dados"/"Alterar"
        não têm formulário real, só confirmam a intenção via snackbar), mais
        o interruptor de modo escuro compartilhado com a Conta do consumidor."""
        empresa_card = card(
            [
                ft.Text("Ampère Estações Ltda.", weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
                ft.Text("CNPJ 12.345.678/0001-90", size=11, color=theme.GRAY_TEXT),
                ft.Container(
                    content=ft.Text("Editar dados", weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
                    on_click=lambda e: self._show_snack("Em breve."),
                ),
            ],
            height=110,
        )

        banco_card = card(
            ft.Row(
                [
                    ft.Text("Banco 260 · Ag 0001 · CC 12345-6", size=12, color=theme.TEXT_COLOR, expand=True),
                    ft.Container(
                        content=ft.Text("Alterar", weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
                        on_click=lambda e: self._show_snack("Em breve."),
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            height=70,
        )

        return ft.Container(
            content=ft.ListView(
                [
                    ft.Text("Empresa", size=11, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
                    empresa_card,
                    ft.Text("Dados bancários", size=11, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
                    banco_card,
                    self._dark_mode_section(),
                ],
                spacing=20, padding=20, expand=True,
            ),
            expand=True,
        )


def _clear_map_cache():
    """Apaga os PNGs de mapa gerados em sessões anteriores (assets/map_cache),
    pra pasta não crescer sem limite — mapas são baratos de gerar de novo."""
    app_dir = os.path.dirname(os.path.abspath(__file__))
    cache_dir = os.path.join(app_dir, "assets", "map_cache")
    if not os.path.isdir(cache_dir):
        return
    for name in os.listdir(cache_dir):
        if name.endswith(".png"):
            try:
                os.remove(os.path.join(cache_dir, name))
            except OSError:
                pass


def main(page: ft.Page):
    """Ponto de entrada chamado pelo Flet para cada sessão/aba aberta —
    cria uma instância própria de ChargeGridApp por página."""
    ChargeGridApp(page)


if __name__ == "__main__":
    _clear_map_cache()
    ft.run(main, assets_dir="assets")