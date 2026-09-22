"""
Paleta de cores e constantes visuais do ChargeGrid.

Suporta os temas claro (padrão) e escuro. Como o resto do app importa as
cores como `import theme` e acessa `theme.WHITE`, `theme.BG_COLOR` etc.,
usamos um `__getattr__` de módulo (PEP 562): cada acesso a `theme.NOME`
é resolvido dinamicamente contra a paleta ativa no momento, então
chamar `theme.set_dark(True)` muda a cor retornada por TODO o app
imediatamente, sem precisar reimportar nada.
"""

DATA_FILE = "ev_data.json"

LIGHT = {
    "BG_COLOR": "#F5F5F5",     # Fundo geral do app
    "RED": "#DA292E",          # Cor de marca (destaque / botões primários)
    "WHITE": "#FFFFFF",        # Cartões e superfícies
    "TEXT_COLOR": "#222222",   # Texto principal
    "GRAY_TEXT": "#888888",    # Texto secundário
    "LIGHT_GRAY": "#E0E0E0",   # Bordas, divisores, avatares, placeholders
    "GREEN": "#2E7D32",        # Indicadores de sucesso / disponibilidade
}

DARK = {
    "BG_COLOR": "#0D0D0D",     # Fundo geral do app (preto, como no print de referência)
    "RED": "#E5484D",          # Mesma cor de marca, levemente mais clara p/ contraste no escuro
    "WHITE": "#1C1C1E",        # Usado como cor de "superfície" (cards, campos) no tema escuro
    "TEXT_COLOR": "#F2F2F2",   # Texto principal (quase branco)
    "GRAY_TEXT": "#9A9A9A",    # Texto secundário
    "LIGHT_GRAY": "#2E2E30",   # Bordas/divisores no escuro
    "GREEN": "#34C759",        # Indicadores de sucesso / disponibilidade
}

_current = LIGHT
_dark_enabled = False


def set_dark(enabled: bool):
    """Ativa/desativa o tema escuro. Chame de novo qualquer show_login()/
    show_consumer()/show_retailer() depois disso para redesenhar a tela
    com as novas cores."""
    global _current, _dark_enabled
    _dark_enabled = bool(enabled)
    _current = DARK if _dark_enabled else LIGHT


def is_dark() -> bool:
    """Estado atual do tema — usado pra desenhar o Switch de modo escuro
    já na posição certa e pra decidir a legenda 🚗/⚡/⛔ dos marcadores do
    mapa em cada paleta."""
    return _dark_enabled


def __getattr__(name):
    """Hook de módulo (PEP 562): intercepta `theme.QUALQUER_NOME` e resolve
    contra `_current` (LIGHT ou DARK) em vez de contra atributos fixos do
    módulo — é o mecanismo que faz `theme.set_dark(True)` valer para
    chamadas futuras a `theme.BG_COLOR` etc. em qualquer lugar do app."""
    if name in _current:
        return _current[name]
    raise AttributeError(f"module 'theme' has no attribute {name!r}")