"""
Paleta de cores e constantes visuais do ChargeGrid.

Suporta os temas escuro (padrão; é o design de referência) e claro. Como o resto do app importa as
cores como `import theme` e acessa `theme.WHITE`, `theme.BG_COLOR` etc.,
usamos um `__getattr__` de módulo (PEP 562): cada acesso a `theme.NOME`
é resolvido dinamicamente contra a paleta ativa no momento, então
chamar `theme.set_dark(True)` muda a cor retornada por TODO o app
imediatamente, sem precisar reimportar nada.
"""

from contextvars import ContextVar

# Cores-base da marca (design de referência): verde dos pinos/"Disponível" e azul-marinho do posto
# em destaque. Os tokens MAP_* de cada paleta derivam delas (e das superfícies do tema) via _mix.
BRAND_GREEN = "#039F25"
BRAND_NAVY = "#1D3355"


def _mix(base, other, amount):
    """Hex de `base` com `amount` (0..1) de `other` misturado — deriva tons sem cores soltas."""
    a = [int(base.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4)]
    b = [int(other.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4)]
    return '#' + ''.join(f'{round(x + (y - x) * amount):02X}' for x, y in zip(a, b))


# Estilo de mapa ChargeGrid (services/maps.py): os tiles do OpenStreetMap são dessaturados e
# remapeados por luminância numa rampa land → block → road (+ labels), com água e áreas verdes
# levemente tingidas pelas cores da marca. Pinos, balões e o crédito "© OpenStreetMap" também
# têm variante por tema.
_MAP_LIGHT_LAND = "#EEF0F1"
_MAP_DARK_LAND = "#1E2124"

LIGHT = {
    "NAV_BG": "#FFFFFF",
    "INPUT_BG": "#FFFFFF",
    "INPUT_TEXT": "#1D1F20",
    "INPUT_BORDER": "#6B6B6B",
    "BG_COLOR": "#F2F2F3",
    "RED": "#D72B32",
    "ACCENT": "#B91C24",
    "FOCUS": "#205EA8",
    "ERROR": "#B91C24",
    "WHITE": "#FFFFFF",        # Cartões e superfícies
    "TEXT_COLOR": "#1D1F20",
    "GRAY_TEXT": "#62666B",
    "LIGHT_GRAY": "#E1E2E3",
    "GREEN": "#2E7D32",        # Indicadores de sucesso / disponibilidade
    "AMBER": "#9A5300",        # Reserva confirmada
    "BLUE": "#205EA8",         # Sincronização em andamento
    "SLATE": "#58626F",        # Estado indisponível sem erro
    "WARNING": "#9A5300",      # Texto de aviso (AA sobre superfícies claras)
    # --- tokens do design de referência (ver ui/design.py) ---
    "CARD": "#FFFFFF",         # cartões / linhas de lista
    "TILE": "#E7E8EA",         # quadrado de ícone secundário
    "TILE_FG": "#1D1F20",
    "ICON_TILE": "#1D1F20",    # quadrado de ícone "branco" da referência
    "ICON_TILE_FG": "#FFFFFF",
    "SEGMENT_OFF": "#D5D6D9",  # segmento inativo da barra de etapas
    "BORDER": "#1D1F20",       # contorno do item selecionado
    "BORDER_SOFT": "#D5D6D9",
    "BTN_PRIMARY": "#1D1F20",  # botão primário (invertido em relação ao tema)
    "BTN_PRIMARY_FG": "#FFFFFF",
    "BTN_SECONDARY": "#E1E2E3",
    "BTN_SECONDARY_FG": "#1D1F20",
    "WARN_BG": "#FBE9EA",
    "NAV_INACTIVE": "#6B6F75",
    "NAV_ACTIVE": "#1D1F20",
    "SUCCESS": "#2E7D32",
    "ON_PRIMARY": "#FFFFFF",
    # --- mapa (estilo ChargeGrid, variante clara) ---
    "MAP_LAND": _MAP_LIGHT_LAND,                  # terreno / fundo do mapa e do esquemático
    "MAP_BLOCK": "#E2E5E7",                       # edificações e quadras
    "MAP_EDGE": "#D2D6DA",                        # contornos de quadras e bordas de vias
    "MAP_ROAD": "#FFFFFF",
    "MAP_ROAD_MAJOR": "#FFFFFF",                  # avenidas (laranja/amarelo no OSM padrão)
    "MAP_LABEL": "#5E6870",                       # nomes de ruas e ícones
    "MAP_WATER": _mix(_MAP_LIGHT_LAND, "#205EA8", .25),
    "MAP_PARK": _mix(_MAP_LIGHT_LAND, BRAND_GREEN, .18),
    "MAP_RING": "#CED8DE",                        # anéis do mapa esquemático
    "MAP_PIN": "#233949",                         # posto livre
    "MAP_PIN_OFF": "#58626F",                     # posto indisponível
    "MAP_PIN_LIST": BRAND_GREEN,                  # posto em destaque na lista
    "MAP_PIN_DETAIL": BRAND_NAVY,                 # posto em destaque no detalhe
    "MAP_PIN_RING": "#FFFFFF",
    "MAP_PIN_SHADOW": "#1E2327",
    "MAP_CALLOUT": "#FFFFFF",
    "MAP_CALLOUT_TEXT": "#101828",
    "MAP_CALLOUT_MUTED": "#3F4654",
    "MAP_CALLOUT_SHADOW": "#38000000",
    "MAP_CHIP_FREE": "#BAD4FB",
    "MAP_CHIP_FREE_FG": "#1E4FA3",
    "MAP_CHIP_OFF": "#E7EBEF",
    "MAP_CHIP_OFF_FG": "#58626F",
    "MAP_CHIP_LIST": "#05A02B",
    "MAP_CHIP_LIST_FG": "#FFFFFF",
    "MAP_CREDIT_BG": "#EFFFFFFF",                 # ARGB: crédito do OSM legível sobre o mapa
    "MAP_CREDIT_FG": "#40484B",
}

# Tema escuro = o design de referência (amostrado dos PNGs):
# fundo #1F1F1F, cartões/campos #1A1A1A, barra inferior #191919,
# quadrado de ícone secundário #2B2B2B, segmento inativo #343434,
# aviso #2D1D20, vermelho #D72B32, botão primário branco com texto preto.
DARK = {
    "NAV_BG": "#191919",
    "INPUT_BG": "#1A1A1A",
    "INPUT_TEXT": "#FFFFFF",
    "INPUT_BORDER": "#3A3A3A",
    "BG_COLOR": "#1F1F1F",
    "RED": "#D72B32",
    "ACCENT": "#FF858A",
    "FOCUS": "#9DC8FF",
    "ERROR": "#FF858A",
    "WHITE": "#1A1A1A",        # superfície de cartão (nome histórico do token)
    "TEXT_COLOR": "#FFFFFF",
    "GRAY_TEXT": "#ADADAD",
    "LIGHT_GRAY": "#2B2B2B",
    "GREEN": "#34C759",        # Indicadores de sucesso / disponibilidade
    "AMBER": "#9A5300",
    "BLUE": "#205EA8",
    "SLATE": "#58626F",
    "WARNING": "#F5B76B",      # Âmbar legível (AA) sobre superfícies escuras
    "CARD": "#1A1A1A",
    "TILE": "#2B2B2B",
    "TILE_FG": "#FFFFFF",
    "ICON_TILE": "#FFFFFF",
    "ICON_TILE_FG": "#000000",
    "SEGMENT_OFF": "#343434",
    "BORDER": "#FFFFFF",
    "BORDER_SOFT": "#3A3A3A",
    "BTN_PRIMARY": "#FFFFFF",
    "BTN_PRIMARY_FG": "#000000",
    "BTN_SECONDARY": "#252525",
    "BTN_SECONDARY_FG": "#FFFFFF",
    "WARN_BG": "#2D1D20",
    "NAV_INACTIVE": "#7F7F7F",
    "NAV_ACTIVE": "#FFFFFF",
    "SUCCESS": "#34C759",
    "ON_PRIMARY": "#000000",
    # --- mapa (estilo ChargeGrid, variante escura: fundo charcoal, ruas claras) ---
    "MAP_LAND": _MAP_DARK_LAND,
    "MAP_BLOCK": "#272B2F",
    "MAP_EDGE": "#30353A",
    "MAP_ROAD": "#3D444A",
    "MAP_ROAD_MAJOR": "#545D65",
    "MAP_LABEL": "#AEB6BD",
    "MAP_WATER": _mix(_MAP_DARK_LAND, "#205EA8", .35),
    "MAP_PARK": _mix(_MAP_DARK_LAND, BRAND_GREEN, .22),
    "MAP_RING": "#3A4146",
    "MAP_PIN": "#3A78C2",                         # azul da marca clareado: contraste no charcoal
    "MAP_PIN_OFF": "#58626F",
    "MAP_PIN_LIST": BRAND_GREEN,
    "MAP_PIN_DETAIL": "#3A78C2",
    "MAP_PIN_RING": "#FFFFFF",
    "MAP_PIN_SHADOW": "#000000",
    "MAP_CALLOUT": "#2A2E32",
    "MAP_CALLOUT_TEXT": "#FFFFFF",
    "MAP_CALLOUT_MUTED": "#C5CBD1",
    "MAP_CALLOUT_SHADOW": "#80000000",
    "MAP_CHIP_FREE": "#1F3A5C",
    "MAP_CHIP_FREE_FG": "#9DC8FF",
    "MAP_CHIP_OFF": "#3A3F44",
    "MAP_CHIP_OFF_FG": "#C5CBD1",
    "MAP_CHIP_LIST": "#05A02B",
    "MAP_CHIP_LIST_FG": "#FFFFFF",
    "MAP_CREDIT_BG": "#E6202326",
    "MAP_CREDIT_FG": "#D3D8DC",
}

_dark_enabled = ContextVar('chargegrid_dark_mode', default=True)


def set_dark(enabled: bool):
    """Ativa/desativa o tema escuro. Chame de novo qualquer show_login()/
    show_consumer()/show_retailer() depois disso para redesenhar a tela
    com as novas cores."""
    _dark_enabled.set(bool(enabled))


def is_dark() -> bool:
    """Estado atual do tema — usado pra desenhar o Switch de modo escuro
    já na posição certa e pra decidir a legenda 🚗/⚡/⛔ dos marcadores do
    mapa em cada paleta."""
    return _dark_enabled.get()


def __getattr__(name):
    """Hook de módulo (PEP 562): intercepta `theme.QUALQUER_NOME` e resolve
    contra `_current` (LIGHT ou DARK) em vez de contra atributos fixos do
    módulo — é o mecanismo que faz `theme.set_dark(True)` valer para
    chamadas futuras a `theme.BG_COLOR` etc. em qualquer lugar do app."""
    palette = DARK if is_dark() else LIGHT
    if name in palette:
        return palette[name]
    raise AttributeError(f"module 'theme' has no attribute {name!r}")


def on_color(background):
    """Choose the higher-contrast neutral foreground for a solid hex fill."""
    try:
        channels = [int(background.lstrip('#')[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        luminance = sum(weight * (channel / 12.92 if channel <= .04045
                                 else ((channel + .055) / 1.055) ** 2.4)
                        for weight, channel in zip((.2126, .7152, .0722), channels))
    except (ValueError, AttributeError):
        return '#FFFFFF'
    return '#000000' if luminance > .179 else '#FFFFFF'
