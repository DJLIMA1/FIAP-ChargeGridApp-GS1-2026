"""Estação (a CENTRAL) × Carregadores no app do vendedor.

A estação é a central (painel com chave, ``screen``/``screens`` da API); cada ponto do posto é um
carregador GoodWe HCA G2 (simulado) com endereço Modbus 1–247 (``charger_address``/``charger_link``).
Aqui ficam os textos e blocos comuns da lista **Carregadores** (``station_admin``), do status da central
e do cartão do carregador no formulário (``operator.connector_form``), além das ações
**Adicionar carregador** (``POST connectors/{id}/chargers``) e **Remover carregador**
(``DELETE connectors/{id}``, só carregador adicional). A entidade da API continua ``connector``.
"""

from decimal import Decimal, InvalidOperation

import flet as ft

from chargegrid_core import power as power_rules
from chargegrid_core.chargers import link as charger_link

from ..api_client import ApiError
from ..ui import design, theme
from ..ui.components import date_time

ADD_LABEL = 'Adicionar carregador'
ADD_HINT = 'Nasce inativo no próximo endereço livre; o ESP do carregador precisa de CG_ADDR = esse endereço.'
ADD_ERRORS = {
    'screen_required': 'Este posto ainda não tem central vinculada. Vincule uma central antes de adicionar carregadores.',
    'charger_address_full': 'Todos os endereços de carregador (1 a 247) já estão em uso neste posto.',
}
REMOVE_LABEL = 'Remover'
REMOVE_HINT = 'Tira este carregador da estação e libera o endereço dele.'
REMOVE_DETAIL = 'Ele sai da estação e o endereço fica livre.'
REMOVE_ERRORS = {
    'screen_charger': 'Este é o carregador da própria central e não pode ser removido.',
    'point_busy': 'Este carregador tem recarga ou reserva em andamento. Encerre-a antes de remover.',
}
LINK_LABELS = {'online': 'Online', 'offline': 'Offline', 'pending': 'Aguardando a central'}
ROLE_LABELS = {'screen': 'Este ponto é a central', 'charger': 'Carregador adicional desta central'}


def plural(count, one, many):
    return f'{count} {one if count == 1 else many}'


def pill(label, color):
    """Etiqueta de status (mesma da lista de carregadores)."""
    return ft.Container(design.txt(label, 10.5, 'bold', theme.on_color(color), text_align=ft.TextAlign.CENTER),
                        bgcolor=color, border_radius=6, padding=ft.Padding(left=8, right=8, top=4, bottom=4))


def link_state(connector):
    """``online``/``offline``/``pending`` do carregador (``charger_link.link``); API sem o bloco: ``online``."""
    block = connector.get('charger_link') or {}
    if block.get('link') in LINK_LABELS:
        return block['link']
    return 'online' if connector.get('online') else 'offline'


def link_status(connector):
    """``(rótulo, cor)`` do carregador: Online, Offline ou Aguardando a central."""
    state = link_state(connector)
    colors = {'online': theme.GREEN, 'offline': theme.SLATE, 'pending': theme.AMBER}
    return LINK_LABELS[state], colors[state]


def screen_status(online):
    return ('Online', theme.GREEN) if online else ('Offline', theme.SLATE)


def live_points(station):
    return [point for point in station.get('connectors') or [] if not point.get('retired')]


def station_screens(station):
    """Centrais do posto: ``station.screens`` (dono) ou, na API sem a lista, os ``screen`` dos pontos."""
    screens = [screen for screen in station.get('screens') or [] if isinstance(screen, dict)]
    if screens:
        return screens
    found = {}
    for point in live_points(station):
        screen = point.get('screen')
        if isinstance(screen, dict) and screen.get('device_id'):
            entry = found.setdefault(screen['device_id'], {**screen, 'charger_ids': []})
            entry['charger_ids'].append(point.get('id'))
    return list(found.values())


def screen_online(station):
    """Central da estação com contato (``True``/``False``) ou ``None`` quando a API não informa."""
    value = station.get('screen_online')
    if value is not None:
        return bool(value)
    screens = station_screens(station)
    return any(screen.get('online') for screen in screens) if screens else None


def screen_connector_id(station):
    """Ponto usado no ``POST connectors/{id}/chargers``: o da central (de preferência online)."""
    screens = sorted(station_screens(station), key=lambda screen: not screen.get('online'))
    for screen in screens:
        if screen.get('connector_id'):
            return screen['connector_id']
    points = live_points(station)
    for point in points:
        if (point.get('screen') or {}).get('role') == 'screen':
            return point['id']
    for point in points:
        if point.get('screen'):
            return point['id']
    return points[0]['id'] if points else None


def address_of(connector):
    block = connector.get('charger_link') or {}
    value = connector.get('charger_address', block.get('address'))
    return value if value is not None else block.get('address')


def kw_label(value):
    return f'{power_rules.kw_text(value)} kW'


def measured_text(watts):
    if watts is None:
        return 'Sem leitura'
    try:
        return kw_label(Decimal(str(watts)) / 1000)
    except (InvalidOperation, ValueError):
        return 'Sem leitura'


def spec_line(connector):
    """``CCS2 · 60 kW (limite 22 kW) · publicado``: o que o carregador entrega e se aparece na busca."""
    parts = [connector.get('connector_type')]
    if connector.get('power_kw') not in (None, ''):
        power = kw_label(connector['power_kw'])
        if connector.get('power_limit_kw') not in (None, ''):
            power += f" (limite {kw_label(connector['power_limit_kw'])})"
        parts.append(power)
    parts.append('publicado' if connector.get('active', True) else 'inativo')
    return ' · '.join(str(part) for part in parts if part)


def charger_subtitle(connector, price_text=None):
    """Linha da lista: ``Carregador 1 · CCS2 · 60 kW · R$ 1,89/kWh`` (+ status do link se inativo)."""
    parts = []
    address = address_of(connector)
    if address is not None:
        parts.append(f'Carregador {address}')
    parts.append(connector.get('connector_type'))
    if connector.get('power_kw') not in (None, ''):
        parts.append(kw_label(connector['power_kw']))
    if price_text:
        parts.append(price_text)
    if connector.get('active') is False and not connector.get('retired') and connector.get('charger_link'):
        parts.append(charger_link.LINK_TEXT.get(link_state(connector), charger_link.WAITING_TEXT))
    return ' · '.join(str(part) for part in parts if part)


def screen_line(screen, count=None):
    """``DEMO-11 · 2 carregadores``."""
    parts = [screen.get('public_code') or 'Central']
    if count is not None:
        parts.append(plural(count, 'carregador', 'carregadores'))
    return ' · '.join(parts)


def contact_text(screen):
    """``Último contato 21/10/2026 13:55`` ou ``Sem contato``."""
    return f"Último contato {date_time(screen['last_seen'])}" if screen.get('last_seen') else 'Sem contato'


def row(label, value, detail=None, *, data=None):
    """Linha rótulo cinza × valor em negrito (mesmo desenho da tela Tarifa)."""
    left = [design.txt(label, 12.5, 'regular', theme.GRAY_TEXT)]
    if detail:
        left.append(design.txt(detail, 10.5, 'regular', theme.GRAY_TEXT))
    right = value if isinstance(value, ft.Control) else design.txt(value, 12.5, 'bold', data=data,
                                                                    text_align=ft.TextAlign.END)
    return ft.Row([ft.Column(left, spacing=1, expand=True), right], spacing=12,
                  vertical_alignment=ft.CrossAxisAlignment.CENTER)


def card(title, *controls, trailing=None, subtitle=None, spacing=10, head=None):
    """Cartão da tela Tarifa: título 13,5 em negrito (+ etiqueta à direita) e o conteúdo.

    ``head`` substitui título/subtítulo por controles próprios (cabeçalho que se atualiza)."""
    if head is not None:
        top = list(head)
    else:
        row = [design.txt(title, 13.5, 'bold', expand=True)]
        if trailing is not None:
            row.append(trailing)
        top = [ft.Row(row, spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)]
    if subtitle:
        top.append(design.txt(subtitle, 11, 'regular', theme.GRAY_TEXT))
    return design.card_box(ft.Column([ft.Column(top, spacing=3), *controls], spacing=spacing,
                                     horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                           padding=ft.Padding(left=15, right=15, top=14, bottom=15), radius=18)


def central_head(name, badge, meta=None):
    """Cabeçalho de cartão de central: ``Central CODE`` + etiqueta Online/Offline e a linha cinza de contato.

    Mesmo desenho no cartão de manutenção (``central_admin``) e no de status sem manutenção."""
    head = [ft.Row([name, badge], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)]
    if meta is not None:
        head.append(meta)
    return head


def screens_card(station):
    """Status da CENTRAL da estação (separado do status de cada carregador), ou ``None`` sem dados.

    Um cartão por central com o mesmo cabeçalho do cartão de manutenção (``central_head``)."""
    screens = station_screens(station)
    online = screen_online(station)
    if not screens and online is None:
        return None
    if not screens:
        label, color = screen_status(online)
        return card('', head=central_head(design.txt('Central', 13.5, 'bold', expand=True), pill(label, color),
                                          design.txt('A estação fica online enquanto a central tiver contato.',
                                                     11, 'regular', theme.GRAY_TEXT)))
    cards = []
    for screen in screens:
        label, color = screen_status(screen.get('online'))
        count = len(screen.get('charger_ids') or [])
        meta = [contact_text(screen)] + ([plural(count, 'carregador', 'carregadores')] if count else [])
        cards.append(card('', head=central_head(
            design.txt(f"Central {screen.get('public_code') or ''}".strip(), 13.5, 'bold', expand=True),
            pill(label, color), design.txt(' · '.join(meta), 11, 'regular', theme.GRAY_TEXT))))
    if len(cards) == 1:
        return cards[0]
    return ft.Column(cards, spacing=15, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)


def add_error_message(exc):
    return ADD_ERRORS.get(getattr(exc, 'code', None)) or str(exc)


async def add_charger(app, station):
    """``POST connectors/{ponto da central}/chargers`` → linha do novo carregador (com endereço)."""
    target = screen_connector_id(station)
    if not target:
        raise ApiError(ADD_ERRORS['screen_required'], 409, 'screen_required')
    try:
        created = await app.api.request('POST', f'connectors/{target}/chargers')
    except ApiError as exc:
        if exc.code in ADD_ERRORS:
            raise ApiError(ADD_ERRORS[exc.code], exc.status, exc.code) from None
        raise
    return created if isinstance(created, dict) else {}


def removable(connector):
    """Carregador adicional de uma central (pode sair da estação); o carregador da própria central, nunca."""
    screen = connector.get('screen')
    if connector.get('retired') or not isinstance(screen, dict):
        return False
    if screen.get('role') in ('screen', 'charger'):
        return screen['role'] == 'charger'
    return bool(screen.get('connector_id')) and screen['connector_id'] != connector.get('id')


async def remove_charger(app, connector):
    """``DELETE connectors/{id}`` (204); 409 ``screen_charger``/``point_busy`` com o texto do app."""
    try:
        await app.api.request('DELETE', f"connectors/{connector['id']}")
    except ApiError as exc:
        if exc.code in REMOVE_ERRORS:
            raise ApiError(REMOVE_ERRORS[exc.code], exc.status, exc.code) from None
        raise


def removed_text(connector):
    address = address_of(connector)
    name = f'Carregador {address}' if address is not None else 'Carregador'
    return f'{name} removido. O endereço ficou livre para outro carregador.'


def added_text(created):
    address = address_of(created)
    code = created.get('public_code') or 'novo ponto'
    return (f'Carregador {address} criado ({code}), inativo. Configure CG_ADDR = {address} no ESP do carregador '
            'e publique quando ele ficar online.')
