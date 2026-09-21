"""
Paleta de cores e constantes visuais do ChargeGrid.

Suporta os temas claro (padrão) e escuro. Como o resto do app importa as
cores como `import theme` e acessa `theme.WHITE`, `theme.BG_COLOR` etc.,
usamos um `__getattr__` de módulo (PEP 562): cada acesso a `theme.NOME`
é resolvido dinamicamente contra a paleta ativa no momento, então
chamar `theme.set_dark(True)` muda a cor retornada por TODO o app
imediatamente, sem precisar reimportar nada.
"""

from contextvars import ContextVar

LIGHT = {
    "BG_COLOR": "#F2F2F3",
    "RED": "#D72B32",
    "WHITE": "#FFFFFF",        # Cartões e superfícies
    "TEXT_COLOR": "#1D1F20",
    "GRAY_TEXT": "#62666B",
    "LIGHT_GRAY": "#E1E2E3",
    "GREEN": "#2E7D32",        # Indicadores de sucesso / disponibilidade
}

DARK = {
    "BG_COLOR": "#131313",
    "RED": "#D72B32",
    "WHITE": "#1F1F1F",
    "TEXT_COLOR": "#FFFFFF",
    "GRAY_TEXT": "#ADB3BA",
    "LIGHT_GRAY": "#2A2A2A",
    "GREEN": "#34C759",        # Indicadores de sucesso / disponibilidade
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
