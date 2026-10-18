"""
Design kit do ChargeGrid — espelha o design de referência (402 x 874 pt, PNGs 2x).

TODOS os blocos visuais novos devem sair daqui; não repita medidas nas telas.
Cores vêm de ``ui.theme`` (tema escuro = referência; o claro é derivado).

=====================================================================
CONTRATO DE ROTAS  (``app.go(route, **params)`` / ``app.link(route, **params)``)
=====================================================================
Cada rota é ``screens/<nome>.py`` com ``async def build(app, **params)``
(retorna um ``ft.Column``). Toda rota aceita kwargs arbitrários; ``**_`` no fim
da assinatura evita quebrar quando o shell/outras telas passam parâmetros extras.

Rotas do consumidor
  home            início (consumidor). No modo vendedor ``go('home')`` abre o início do
                  vendedor: ``screens/home.py`` pode definir ``build_vendor(app, **p)``;
                  enquanto não existir, o shell mostra ``operator.build``.
  stations        busca/detalhe de estação       (aba Recarga)
  booking         assistente de recarga          (aba Recarga) params: step (1..N),
                  station_id, connector_id, mode, ...
  reservations / charging   fluxos já existentes (aba Recarga)
  history, chat, profile (Conta), coupons
  wallet          saldo do consumidor (aba Conta) params: step, page, ... ; voltar -> profile
  notifications   lista de notificações (sem aba ativa; voltar -> home)

Rotas do vendedor  (``app.browsing_mode == 'vendor'``)
  home            Início do vendedor (aba Início)
  operator        lista/detalhe de estações (aba Estações), params: station_id, ...
  station_admin   detalhe/ajustes de uma estação (aba Estações)
                  params: station_id, page ('power' | 'battery' | 'edit' | ...)
                  voltar: page -> station_admin(station_id); sem page -> operator
  tariffs         tarifas dinâmicas (aba Estações) params: station_id opcional
                  voltar: station_id -> station_admin(station_id); senão -> home
  payout          carteira / resgate (aba Início) params: step, page ; voltar -> home
  history         (manage=True), chat, profile

Voltar (``parent_route``) para booking / wallet / payout / tariffs:
  * ``step`` > 1  -> mesma rota com ``step - 1``;
  * senão, ``origin='<rota>'`` (se informado) ou o pai padrão descrito acima.
O botão "<" do cabeçalho de página usa ``app.back``; telas só precisam renderizar
``page_title(..., on_back=app.back)`` (o seletor de abas do shell também usa o contrato).

Param ``nav=False`` em qualquer rota esconde a barra inferior (o shell remove a chave antes de chamar
``build``); no vendedor ela já fica oculta em ``operator`` com ``onboarding`` ou ``claim`` (cadastro de
estação/totem, como na referência).

Shell (app.py): cabeçalho (logo, sino -> ``notifications``, avatar -> ``profile``) e barra
inferior são desenhados pelo shell; as telas NÃO desenham cabeçalho/abas. O corpo da tela
recebe 20 pt de margem lateral (``GUTTER``).

=====================================================================
API  (todas as funções retornam controles Flet)
=====================================================================
Escala tipográfica medida na referência (pt): saudação 22 negrito; título de página 18-19 negrito
("Conta" 15); rótulo de seção 15 negrito; título de linha 13 semibold (estação 14); subtítulo 10
(11 em linhas grandes); rótulo de campo 11 negrito cinza; texto de campo 13; botão 14,5 semibold
(assistente: 16 negrito); aviso 12; navegação 11 (Barlow Condensed Medium); dinheiro 28 Barlow.
Texto/tokens
  txt(value, size=14, weight='regular'|'medium'|'semibold'|'bold', color=None, **kw)
  num(value, size=28, color=None, **kw)               # Barlow Condensed SemiBold (valores R$ grandes: 28; vendedor 36)
  money_text(value, size=28, color=None)              # num() com "R$ 214,80"
  GUTTER, RADIUS_CARD, RADIUS_BTN, FONT_*             # constantes
Estrutura
  page(*controls, title=None, on_back=None, steps=None, step=None, footer=None,
       scroll=True, center_title=False, gap=16, gutter=0, title_size=18)  -> Column(expand)
       # título com "<" + progresso opcional + conteúdo rolável + rodapé fixo
  page_title(title, on_back=None, *, center=False, size=18)   # 18 negrito ("Minhas recargas" 19, "Conta" 15)
  progress_bar(total, current)                         # barra de etapas (current 1-based)
  section_label(text)                                  # rótulo de seção em negrito
  label(text, strong=True)                             # rótulo de campo: cinza negrito 11 (strong=False: branco 11,5)
Cartões/linhas
  card_box(content, *, padding=16, radius=16, bgcolor=None, border=None, on_click=None)
  info_card(title, lines=(), *, icon=None)             # cartão com título + linhas cinza
  icon_tile(icon=None, *, size=56, dark=False)         # quadrado de ícone (padrão: pino da estação)
  list_row(title, subtitle=None, *, on_click=None, trailing=None, chevron=True, icon=None,
           tile=56, selected=False, dark_tile=False, plain=False)
       # trailing: str -> texto em negrito à direita; Control -> usado direto.
       # plain=True: sem cartão (como "Meu saldo" / "Perfil" em Conta; usa tile escuro)
  radio_option(title, subtitle=None, *, selected=False, on_click=None, icon=None)
  segmented(options, value, on_change=None, *, height=36, radius=4)  # options: [(valor, rótulo)]
  chip_option(text, *, selected=False, on_click=None, width=None)    # botão de valor/pílula selecionável
Botões
  primary_button(text, on_click=None, *, icon=None, height=48, expand=False, disabled=False,
                 size=14.5, weight='semibold')           # branco (assistentes: height=55, size=16, weight='bold')
  secondary_button(...mesmos parâmetros...)              # escuro
  danger_button(...mesmos parâmetros...)                 # vermelho (ex.: height=54)
  icon_button_tile(icon, on_click=None, size=46)       # quadrado escuro com ícone
Avisos/estados
  warning_box(text)                                    # caixa vermelha com ícone de informação
  success_state(title, subtitle=None, *, icon=...)     # círculo verde com check
Campos
  input_field(value='', hint='', *, password=False, keyboard=None, prefix=None, suffix=None,
              on_change=None, multiline=False, read_only=False, height=45, text_align=None) -> TextField
  labeled_input(label, value='', hint='', **kw) -> Column  # rótulo + campo; campo = ``.controls[1]``
  labeled(label, control, gap=8, *, strong=True)       # rótulo acima de qualquer controle
Mídia
  avatar(app=None, size=25)                            # foto de demonstração ou inicial
  car_image(width=None), totem_image(height=None), map_image(height=160, radius=16, src=None)
  logo()                                               # marca do cabeçalho
Shell (usado por app.py)
  app_header(app), bottom_nav(app, entries, active)
  demo_note(app)                                       # linha discreta "DEMONSTRAÇÃO..." p/ a tela Conta
Imagens ficam em ``assets/design/`` (``/design/<nome>``): avatar_joao.jpg, car_byd_dolphin.png,
totem_goodwe.png, map_villa_lobos.jpg, qr_pix_demo.png, icon_station_pin.svg, nav_*.svg.
"""

import flet as ft

from . import motion, theme

GUTTER = 20
RADIUS_CARD = 16
RADIUS_BTN = 12

FONT = 'Inter'
FONT_MEDIUM = 'InterMedium'
FONT_SEMIBOLD = 'InterSemiBold'
FONT_BOLD = 'InterBold'
FONT_NUM = 'BarlowCondensedSemiBold'
FONT_NAV = 'BarlowCondensedMedium'
_WEIGHTS = {'regular': FONT, 'medium': FONT_MEDIUM, 'semibold': FONT_SEMIBOLD, 'bold': FONT_BOLD}

ASSET_DIR = '/design/'
AVATAR_SRC = ASSET_DIR + 'avatar_joao.jpg'
CAR_SRC = ASSET_DIR + 'car_byd_dolphin.png'
TOTEM_SRC = ASSET_DIR + 'totem_goodwe.png'
MAP_SRC = ASSET_DIR + 'map_villa_lobos.jpg'
QR_SRC = ASSET_DIR + 'qr_pix_demo.png'
STATION_PIN_SRC = ASSET_DIR + 'icon_station_pin.svg'
WORDMARK_SRC = '/figma/wordmark-dark.svg'


# ---------------------------------------------------------------- texto
def txt(value, size=14, weight='regular', color=None, **kwargs):
    """Texto Inter; ``weight`` escolhe o arquivo de fonte (sem negrito sintético)."""
    return ft.Text(str(value), size=size, color=color or theme.TEXT_COLOR,
                   font_family=_WEIGHTS.get(weight, FONT), **kwargs)


def num(value, size=28, color=None, **kwargs):
    """Número grande em Barlow Condensed (saldo, valores)."""
    return ft.Text(str(value), size=size, color=color or theme.TEXT_COLOR, font_family=FONT_NUM, **kwargs)


def money_text(value, size=28, color=None, **kwargs):
    """``R$ 214,80`` em Barlow Condensed. ``value`` numérico/Decimal ou texto já formatado."""
    if isinstance(value, str) and value.lstrip().startswith('R$'):
        text = value
    else:
        from .components import money
        text = money(value)
    return num(text, size, color, **kwargs)


def label(text, *, strong=True, **kwargs):
    """Rótulo sobre um campo: ``strong`` = cinza em negrito 11 (``Nome da estação``);
    ``strong=False`` = branco regular 11,5 (``Status``)."""
    if strong:
        return txt(text, 11, 'bold', theme.GRAY_TEXT, **kwargs)
    return txt(text, 11.5, 'regular', **kwargs)


def section_label(text, **kwargs):
    """Rótulo de seção em negrito 15 (``Próximas``, ``Conectores``, ``Em andamento``)."""
    return txt(text, 15, 'bold', **kwargs)


def labeled(text, control, gap=8, *, strong=True):
    return ft.Column([label(text, strong=strong), control], spacing=gap,
                     horizontal_alignment=ft.CrossAxisAlignment.STRETCH)


# ---------------------------------------------------------------- estrutura
def progress_bar(total, current):
    """Barra segmentada do assistente; ``current`` é 1-based (segmentos <= current acesos)."""
    return ft.Container(
        ft.Row([ft.Container(height=3, expand=True, border_radius=2,
                             bgcolor=theme.BTN_PRIMARY if index < current else theme.SEGMENT_OFF)
                for index in range(total)], spacing=6),
        padding=ft.Padding(left=3, right=3, top=0, bottom=0))


def page_title(title, on_back=None, *, center=False, size=18, trailing=None):
    """Linha de título: ``<`` (se ``on_back``) + título em negrito."""
    chevron = ft.Container(
        ft.Icon(ft.Icons.CHEVRON_LEFT, size=26, color=theme.TEXT_COLOR),
        on_click=on_back, width=34, height=34, ink=False, tooltip='Voltar',
        alignment=ft.Alignment(-1, 0), margin=ft.Margin(left=-4, top=0, right=0, bottom=0)) if on_back else None
    heading = txt(title, 14.7 if center else size, 'regular' if center else 'bold', expand=True,
                  text_align=ft.TextAlign.CENTER if center else ft.TextAlign.START)
    if center:
        # Título centralizado (telas de formulário): o espaçador à direita equilibra o "<".
        row = [chevron or ft.Container(width=34), heading, trailing or ft.Container(width=34)]
    else:
        row = [*([chevron] if chevron else []), heading, *([trailing] if trailing else [])]
    return ft.Row(row, spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER)


def page(*controls, title=None, on_back=None, steps=None, step=None, footer=None, scroll=True,
         center_title=False, gap=16, gutter=0, title_size=18):
    """Esqueleto padrão de tela: [progresso] + [título] + conteúdo (rolável) + [rodapé fixo].

    ``footer`` (controle ou lista) fica fixo acima da barra inferior (botão principal, aviso).
    ``gutter`` acrescenta margem lateral extra (assistentes usam 3).
    """
    head = []
    if steps:
        head.append(ft.Container(progress_bar(steps, step or 1), margin=ft.Margin(left=0, top=3.5, right=0, bottom=0)))
    if title is not None:
        head.append(page_title(title, on_back, center=center_title, size=title_size))
    body = ft.Column(list(controls), spacing=gap, scroll=ft.ScrollMode.AUTO if scroll else None, expand=True,
                     horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    foot = footer if isinstance(footer, (list, tuple)) else ([footer] if footer is not None else [])
    parts = [*head, body, *([ft.Column(list(foot), spacing=12, horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                                       )] if foot else [])]
    column = ft.Column(parts, spacing=10 if steps else gap, expand=True,
                       horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    if foot:
        column.controls[-1] = ft.Container(column.controls[-1], padding=ft.Padding(left=0, right=0, top=0, bottom=16))
    if gutter:
        return ft.Column([ft.Container(column, padding=ft.Padding(left=gutter, right=gutter, top=0, bottom=0),
                                       expand=True)], expand=True)
    return column


# ---------------------------------------------------------------- cartões e linhas
def card_box(content, *, padding=16, radius=RADIUS_CARD, bgcolor=None, border=None, on_click=None, **kwargs):
    return ft.Container(content, padding=padding, border_radius=radius, bgcolor=bgcolor or theme.CARD,
                        border=border, on_click=on_click, ink=bool(on_click), **kwargs)


def icon_tile(icon=None, *, size=56, dark=False, icon_size=None):
    """Quadrado arredondado com ícone. ``icon``: ``ft.Icons.X``, caminho SVG/PNG ou ``None`` (pino da estação)."""
    bg = theme.TILE if dark else theme.ICON_TILE
    fg = theme.TILE_FG if dark else theme.ICON_TILE_FG
    inner = icon_size or round(size * (0.46 if dark else 0.64))
    if icon is None:
        glyph = ft.Image(src=STATION_PIN_SRC, width=inner, height=inner, color=fg, exclude_from_semantics=True)
    elif isinstance(icon, str) and icon.startswith('/'):
        glyph = ft.Image(src=icon, width=inner, height=inner, color=fg, exclude_from_semantics=True)
    else:
        glyph = ft.Icon(icon, size=inner, color=fg)
    return ft.Container(glyph, width=size, height=size, bgcolor=bg, border_radius=round(size * 0.25) if size < 50 else 14,
                        alignment=ft.Alignment(0, 0))


def _chevron(color=None, size=24):
    return ft.Icon(ft.Icons.CHEVRON_RIGHT, size=size, color=color or theme.TEXT_COLOR)


def list_row(title, subtitle=None, *, on_click=None, trailing=None, chevron=True, icon=None, tile=56,
             selected=False, dark_tile=False, plain=False, tile_control=None):
    """Linha de lista: [tile] título + subtítulo cinza ... [trailing] [>].

    ``plain=True`` remove o cartão (listas de Conta); use junto com ``dark_tile=True``.
    """
    texts = [txt(title, 14 if tile >= 50 else 13, 'semibold')]
    if subtitle:
        texts.append(txt(subtitle, 11 if tile >= 50 else 10, 'regular', theme.GRAY_TEXT))
    lead = tile_control if tile_control is not None else icon_tile(icon, size=tile, dark=dark_tile)
    right = []
    if trailing is not None:
        right.append(txt(trailing, 13, 'bold') if isinstance(trailing, str) else trailing)
    if chevron:
        right.append(_chevron(theme.GRAY_TEXT if plain else theme.TEXT_COLOR, 22 if plain else 26))
    row = ft.Row([lead, ft.Column(texts, spacing=3, expand=True, alignment=ft.MainAxisAlignment.CENTER), *right],
                 spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    if plain:
        return ft.Container(row, padding=ft.Padding(left=10, right=10, top=8, bottom=8), on_click=on_click,
                            ink=bool(on_click), border_radius=RADIUS_CARD)
    return ft.Container(row, padding=ft.Padding(left=13, right=14, top=13, bottom=13), on_click=on_click,
                        ink=bool(on_click), border_radius=RADIUS_CARD, bgcolor=theme.CARD,
                        border=ft.Border.all(1, theme.BORDER) if selected else None)


def radio_option(title, subtitle=None, *, selected=False, on_click=None, icon=None):
    """Cartão de opção com seletor circular à direita (conector, pagamento...)."""
    dot = ft.Container(
        ft.Container(width=14, height=14, border_radius=7, bgcolor=theme.BTN_PRIMARY) if selected else None,
        width=22, height=22, border_radius=11, alignment=ft.Alignment(0, 0),
        border=None if selected else ft.Border.all(2, theme.TEXT_COLOR))
    return list_row(title, subtitle, on_click=on_click, trailing=dot, chevron=False, icon=icon, tile=42,
                    selected=selected)


def segmented(options, value, on_change=None, *, height=36, radius=4):
    """Alternância segmentada (Ativa/Inativa, Por tempo/Por valor). ``options``: ``[(valor, rótulo)]``."""
    def make(option):
        key, text = option
        active = key == value

        async def click(event, key=key):
            if on_change:
                result = on_change(key)
                if hasattr(result, '__await__'):
                    await result
        return ft.Container(
            txt(text, 11.5, 'bold' if active else 'regular', theme.BTN_PRIMARY_FG if active else theme.TEXT_COLOR,
                text_align=ft.TextAlign.CENTER),
            expand=True, height=height - 2, alignment=ft.Alignment(0, 0), on_click=click, ink=False,
            bgcolor=theme.BTN_PRIMARY if active else None, border_radius=max(radius - 1, 0))
    return ft.Container(ft.Row([make(option) for option in options], spacing=0), height=height, border_radius=radius,
                        border=ft.Border.all(1, '#6B6B6B' if theme.is_dark() else theme.BORDER_SOFT),
                        clip_behavior=ft.ClipBehavior.ANTI_ALIAS, bgcolor=theme.INPUT_BG)


def chip_option(text, *, selected=False, on_click=None, width=None):
    """Valor selecionável (R$ 50, 30 min...): branco quando ativo, escuro quando não."""
    return ft.Container(
        txt(text, 13, 'bold' if selected else 'medium', theme.BTN_PRIMARY_FG if selected else theme.TEXT_COLOR,
            text_align=ft.TextAlign.CENTER),
        padding=ft.Padding(left=14, right=14, top=11, bottom=11), alignment=ft.Alignment(0, 0), width=width,
        bgcolor=theme.BTN_PRIMARY if selected else theme.CARD, border_radius=RADIUS_BTN, on_click=on_click,
        ink=bool(on_click))


def info_card(title, lines=(), *, icon=None):
    """Cartão informativo: título + linhas cinza (opcionalmente ícone à esquerda)."""
    body = ft.Column([txt(title, 14, 'semibold'), *[txt(line, 11, 'regular', theme.GRAY_TEXT) for line in lines]],
                     spacing=4, expand=True)
    content = ft.Row([icon_tile(icon, size=42, dark=True), body], spacing=14,
                     vertical_alignment=ft.CrossAxisAlignment.CENTER) if icon else body
    return card_box(content, padding=16)


# ---------------------------------------------------------------- botões
def _button(text, on_click, bg, fg, *, icon=None, height=48, expand=False, disabled=False, border=None,
            size=14.5, weight='semibold'):
    content = [txt(text, size, weight, fg, text_align=ft.TextAlign.CENTER)]
    if icon is not None:
        content.insert(0, ft.Icon(icon, size=22, color=fg))
    return ft.Container(
        ft.Row(content, spacing=10, alignment=ft.MainAxisAlignment.CENTER, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor=bg, border_radius=RADIUS_BTN, padding=ft.Padding(left=16, right=16, top=0, bottom=0), height=height,
        alignment=ft.Alignment(0, 0), on_click=None if disabled else on_click, ink=not disabled, expand=expand,
        opacity=0.45 if disabled else 1, border=border, animate_opacity=motion.duration(120), tooltip=None)


def primary_button(text, on_click=None, *, icon=None, height=48, expand=False, disabled=False, size=14.5,
                   weight='semibold'):
    """Botão principal: fundo branco, texto preto (no tema claro, invertido)."""
    return _button(text, on_click, theme.BTN_PRIMARY, theme.BTN_PRIMARY_FG, icon=icon, height=height, expand=expand,
                   disabled=disabled, size=size, weight=weight)


def secondary_button(text, on_click=None, *, icon=None, height=48, expand=False, disabled=False, size=14.5,
                     weight='semibold'):
    """Botão secundário escuro."""
    return _button(text, on_click, theme.BTN_SECONDARY, theme.BTN_SECONDARY_FG, icon=icon, height=height,
                   expand=expand, disabled=disabled, size=size, weight=weight)


def danger_button(text, on_click=None, *, icon=None, height=48, expand=False, disabled=False, size=14.5,
                  weight='semibold'):
    """Botão vermelho (ação de destaque/destrutiva)."""
    return _button(text, on_click, theme.RED, '#FFFFFF', icon=icon, height=height, expand=expand, disabled=disabled,
                   size=size, weight=weight)


def icon_button_tile(icon, on_click=None, size=46, tooltip=None):
    """Quadrado escuro com ícone branco (ex.: extrato / adicionar saldo no cartão de saldo)."""
    return ft.Container(ft.Icon(icon, size=26, color=theme.TILE_FG), width=size, height=size, bgcolor=theme.TILE,
                        border_radius=RADIUS_BTN, alignment=ft.Alignment(0, 0), on_click=on_click, ink=bool(on_click),
                        tooltip=tooltip)


# ---------------------------------------------------------------- avisos
def warning_box(text, *, icon=ft.Icons.INFO_OUTLINE):
    """Caixa de aviso avermelhada com ícone de informação."""
    return ft.Container(
        ft.Row([ft.Icon(icon, size=22, color=theme.RED),
                txt(text, 12, 'regular', theme.TEXT_COLOR if theme.is_dark() else theme.ERROR, expand=True)],
               spacing=10.5, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor=theme.WARN_BG, border_radius=RADIUS_CARD, padding=ft.Padding(left=52, right=48, top=33, bottom=33))


def success_state(title, subtitle=None, *, icon=ft.Icons.CHECK, size=120):
    """Estado de sucesso: círculo verde com check, título e subtítulo centralizados."""
    texts = [txt(title, 18, 'bold', text_align=ft.TextAlign.CENTER)]
    if subtitle:
        texts.append(txt(subtitle, 12, 'regular', theme.GRAY_TEXT, text_align=ft.TextAlign.CENTER))
    return ft.Column([
        ft.Container(ft.Icon(icon, size=round(size * 0.5), color='#FFFFFF'), width=size, height=size,
                     border_radius=size / 2, bgcolor=theme.SUCCESS, alignment=ft.Alignment(0, 0)),
        ft.Column(texts, spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
    ], spacing=28, horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER)


# ---------------------------------------------------------------- campos
def input_field(value='', hint='', *, password=False, keyboard=None, prefix=None, suffix=None, on_change=None,
                multiline=False, read_only=False, height=45, text_align=None, on_submit=None, on_blur=None,
                max_length=None, capitalization=None):
    """Campo escuro arredondado sem contorno (fundo #1A1A1A, texto branco 15)."""
    return ft.TextField(
        value=value, hint_text=hint or None, password=password, can_reveal_password=password,
        keyboard_type=keyboard, prefix=prefix, suffix=suffix, on_change=on_change, on_submit=on_submit, on_blur=on_blur,
        multiline=multiline, min_lines=3 if multiline else None, read_only=read_only, text_align=text_align or ft.TextAlign.START,
        max_length=max_length, capitalization=capitalization,
        filled=True, fill_color=theme.INPUT_BG, color=theme.INPUT_TEXT, cursor_color=theme.INPUT_TEXT,
        hint_style=ft.TextStyle(color=theme.GRAY_TEXT, size=13, font_family=FONT),
        text_style=ft.TextStyle(size=12.5, font_family=FONT, color=theme.INPUT_TEXT),
        border=ft.OutlineInputBorder(), border_color=ft.Colors.TRANSPARENT, border_width=0,
        border_radius=RADIUS_BTN + 2, focused_border_color=theme.BORDER,
        content_padding=ft.Padding(left=13, right=13, top=13, bottom=13), text_size=12.5,
        height=None if multiline else height)


def labeled_input(text, value='', hint='', **kwargs):
    """Rótulo + campo. O ``TextField`` é ``resultado.controls[1]``."""
    return labeled(text, input_field(value, hint, **kwargs))


# ---------------------------------------------------------------- mídia
def avatar(app=None, size=25):
    """Foto de demonstração (conta demo) ou círculo com a inicial do nome."""
    demo = bool(app is not None and getattr(getattr(app, 'api', None), 'is_demo', False))
    if demo or app is None:
        return ft.Container(ft.Image(src=AVATAR_SRC, width=size, height=size, fit=ft.BoxFit.COVER,
                                     exclude_from_semantics=True),
                            width=size, height=size, border_radius=size / 2, clip_behavior=ft.ClipBehavior.ANTI_ALIAS)
    name = str((getattr(app, 'profile', None) or {}).get('name') or 'C').strip()
    return ft.Container(txt(name[:1].upper() or 'C', size * 0.5, 'bold', theme.BTN_PRIMARY_FG), width=size, height=size,
                        border_radius=size / 2, bgcolor=theme.BTN_PRIMARY, alignment=ft.Alignment(0, 0))


def car_image(width=None, height=None):
    return ft.Image(src=CAR_SRC, width=width, height=height, fit=ft.BoxFit.CONTAIN, exclude_from_semantics=True)


def totem_image(width=None, height=None):
    return ft.Image(src=TOTEM_SRC, width=width, height=height, fit=ft.BoxFit.CONTAIN, exclude_from_semantics=True)


def map_image(height=160, radius=RADIUS_CARD, src=None):
    """Mapa estático arredondado (imagem de referência, recortada)."""
    return ft.Container(ft.Image(src=src or MAP_SRC, fit=ft.BoxFit.COVER, width=10000, height=height,
                                 exclude_from_semantics=True),
                        height=height, border_radius=radius, clip_behavior=ft.ClipBehavior.ANTI_ALIAS)


def logo():
    """Marca do cabeçalho (quadrado branco com ícone + ``ChargeGrid``)."""
    image = ft.Image(src=WORDMARK_SRC, width=101, height=21, fit=ft.BoxFit.CONTAIN, semantics_label='ChargeGrid')
    if theme.is_dark():
        return image
    # The wordmark is white artwork: keep it on a dark plate in the light theme.
    return ft.Container(image, bgcolor='#1F1F1F', border_radius=4, padding=ft.Padding(left=0, right=2, top=0, bottom=0))


# ---------------------------------------------------------------- shell
_NAV_ICONS = {
    'home': ('nav_home', 'Início'),
    'stations': ('nav_zap', 'Recarga'),
    'reservations': ('nav_zap', 'Recarga'),
    'operator': ('nav_station', 'Estações'),
    'history': ('nav_clock', 'Histórico'),
    'chat': ('nav_chat', 'Chat'),
    'profile': ('nav_user', 'Conta'),
    'coupons': ('nav_user', 'Cupons'),
}


def app_header(app):
    """Cabeçalho: logo (-> home) à esquerda; sino com ponto vermelho e avatar à direita."""
    bell = ft.Container(
        ft.Stack([ft.Icon(ft.Icons.NOTIFICATIONS_NONE, size=24, color='#FFFFFF' if theme.is_dark() else theme.TEXT_COLOR),
                  ft.Container(width=6, height=6, border_radius=3, bgcolor='#D94141', right=3, top=1)],
                 width=30, height=30),
        on_click=app.link('notifications'), tooltip='Notificações', width=36, height=36, alignment=ft.Alignment(0, 0),
        margin=ft.Margin(left=0, top=6, right=0, bottom=0))
    person = ft.Container(avatar(app, 25), on_click=app.link('profile'), tooltip='Conta')
    return ft.Container(
        ft.Row([ft.Container(logo(), on_click=app.link('home'), tooltip='Início'), ft.Container(expand=True),
                bell, person], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=ft.Padding(left=24, right=24, top=23.5, bottom=2.5), bgcolor=theme.BG_COLOR)


def bottom_nav(app, entries, active):
    """Barra inferior; ``entries`` = ``tab_entries(mode)``; ``active`` = nome da aba ativa."""
    items = []
    for name, text, parameters in entries:
        key = _NAV_ICONS.get(name, ('nav_home', text))[0]
        on = name == active
        color = theme.NAV_ACTIVE if on else theme.NAV_INACTIVE
        icon = ft.Image(src=f'{ASSET_DIR}{key}{"_fill" if on else ""}.svg', width=21, height=21, color=color,
                        fit=ft.BoxFit.CONTAIN, exclude_from_semantics=True)
        tab = ft.TextButton(
            content=ft.Column([icon, ft.Text(text, size=11, font_family=FONT_NAV, color=color,
                                             text_align=ft.TextAlign.CENTER)],
                              horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=3, tight=True),
            on_click=app.link(name, **parameters), tooltip=text,
            style=ft.ButtonStyle(padding=ft.Padding(left=4, right=4, top=0, bottom=0),
                                 shape=ft.RoundedRectangleBorder(radius=8), overlay_color=theme.LIGHT_GRAY,
                                 side={ft.ControlState.FOCUSED: ft.BorderSide(2, theme.FOCUS)}))
        items.append(ft.Semantics(content=tab, selected=on, expand=True))
    return ft.Container(ft.Row(items, spacing=0), bgcolor=theme.NAV_BG, height=81,
                        padding=ft.Padding(left=15, right=15, top=21.5, bottom=0), alignment=ft.Alignment(0, -1))


def demo_note(app):
    """Indicação discreta de demonstração (para a tela Conta); lista vazia fora do demo."""
    if not getattr(getattr(app, 'api', None), 'is_demo', False):
        return ft.Container(visible=False)
    return txt('Demonstração · dados e equipamentos simulados', 11, 'regular', theme.GRAY_TEXT,
               text_align=ft.TextAlign.CENTER)
