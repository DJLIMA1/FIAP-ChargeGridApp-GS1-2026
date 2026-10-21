"""Estação do vendedor: um único lugar para cada posto.

Rota ``station_admin`` (``station_id``, ``page`` = None | 'data' | 'connectors' | 'power'; ``page='power'``
aceita ``section``/``connector_id``, ver ``station_power``). A tela do posto leva a Dados da estação
(nome, endereço, status, a central e o totem de autoatendimento), Carregadores (pontos da central: status de cada
um, edição e Adicionar carregador), Potência (limite contratado, rebalanceamento, loja SIMULADA e cada
carregador) e Tarifa (``tariffs``). Estação = a central; carregador = cada ponto (``connector`` na API).
Nome, endereço, status e totem usam ``PATCH stations``; a localização vem do endereço (sem
latitude/longitude na tela). ``power_kw`` é a potência nominal do carregador e nunca é alterada aqui.
"""


import asyncio

import flet as ft

from chargegrid_core import power as power_rules

from ..api_client import ApiError
from ..services import site_power
from ..services.charger_refresh import POLL_SECONDS, StationRefresh
from ..services.location import station_location
from ..ui import address_autocomplete, design, theme
from . import chargers, station_ops


def _street(address):
    from .stations import _street as street
    return street(address)


def station_code(stations, station_id):
    """Identificador exibido (``CG-001``): posição da estação na lista do vendedor."""
    for index, item in enumerate(stations or [], 1):
        if item.get('id') == station_id:
            return f'CG-{index:03d}'
    return 'CG-001'


def _live_points(station):
    return [point for point in station.get('connectors') or [] if not point.get('retired')]


def power_summary(station, points=None):
    """Subtítulo do menu: ``Limite 75 kW (padrão) · rebalanceamento ligado``; API sem o rebalanceamento:
    ``Limite do posto: 80 kW · CCS2: 60 kW · Tipo 2: 22 kW``."""
    if site_power.has_rebalance(station):
        return site_power.menu_subtitle(station)
    points = _live_points(station) if points is None else points
    parts = list(dict.fromkeys(
        f"{point.get('connector_type')}: "
        f"{power_rules.kw_text(power_rules.requested_kw(point.get('power_kw'), point.get('power_limit_kw')))} kW"
        for point in points))
    if not parts:
        return 'Nenhum carregador vinculado'
    cap = power_rules.to_kw(station.get('max_power_kw'))
    if cap is not None:
        parts.insert(0, f'Limite do posto: {power_rules.kw_text(cap)} kW')
    return ' · '.join(parts)


def menu_row(title, subtitle, icon, on_click=None, *, tile=38, chevron=True, tile_control=None):
    """Linha sem cartão: tile escuro + título/subtítulo + ``>`` (visual das listas do vendedor)."""
    lead = tile_control if tile_control is not None else design.icon_tile(icon, size=tile, dark=True)
    if tile_control is None and tile < 44:
        lead = ft.Container(lead.content, width=tile, height=tile - 4, bgcolor=theme.TILE, border_radius=10,
                            alignment=ft.Alignment(0, 0))
    parts = [lead, ft.Column([design.txt(title, 12.7, 'semibold'), design.txt(subtitle, 9.7, 'regular', theme.GRAY_TEXT)],
                             spacing=3, expand=True, alignment=ft.MainAxisAlignment.CENTER)]
    if chevron:
        parts.append(ft.Icon(ft.Icons.CHEVRON_RIGHT, size=22, color=theme.GRAY_TEXT))
    return ft.Container(ft.Row(parts, spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        on_click=on_click, ink=False, height=max(tile, 38), padding=ft.Padding(left=0, right=0, top=0, bottom=0))


def heading(app, text, on_back=None):
    """Título de tela do vendedor: ``<`` grande + título 22 em negrito."""
    back = ft.Container(ft.Icon(ft.Icons.CHEVRON_LEFT, size=42, color=theme.TEXT_COLOR), on_click=on_back or app.back,
                        ink=False, width=44, height=34, alignment=ft.Alignment(0, 0), tooltip='Voltar',
                        margin=ft.Margin(left=-10, top=0, right=-2, bottom=0))
    return ft.Container(ft.Row([back, design.txt(text, 22, 'bold', expand=True)], spacing=0,
                               vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        height=34, margin=ft.Margin(left=0, top=-1, right=0, bottom=0))


def _round(field):
    return ft.Container(field, border_radius=14, bgcolor=theme.INPUT_BG, clip_behavior=ft.ClipBehavior.ANTI_ALIAS)


def chatbot_button(app, height=40):
    """Botão branco "Fale com o ChatBot" (ícone de balão redondo, texto regular)."""
    content = ft.Row([ft.Image(src='/design/nav_chat.svg', width=20, height=20, color=theme.BTN_PRIMARY_FG,
                               exclude_from_semantics=True),
                      design.txt('Fale com o ChatBot', 15, 'regular', theme.BTN_PRIMARY_FG)],
                     spacing=10, alignment=ft.MainAxisAlignment.CENTER, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    return ft.Container(content, height=height, bgcolor=theme.BTN_PRIMARY, border_radius=design.RADIUS_BTN,
                        alignment=ft.Alignment(0, 0), on_click=app.link('chat'), ink=True)


async def _load(app, station_id):
    import asyncio
    station, listing = await asyncio.gather(
        app.api.request('GET', f'stations/{station_id}'),
        app.api.request('GET', 'operator/stations', params={'limit': 100, 'offset': 0}))
    items = listing.get('items', []) if isinstance(listing, dict) else []
    return station, station_code(items, station_id)


async def build(app, station_id=None, page=None, section=None, connector_id=None, **params):
    if not station_id:
        from . import operator
        return await operator.build(app)
    prefetch = getattr(app.api, 'prefetch', None)
    if prefetch is not None and page == 'power':
        prefetch(f'stations/{station_id}/power')  # em paralelo com o posto (a página só precisa do id)
    station, code = await _load(app, station_id)
    if page == 'data':
        config = None
        if (station_ops.has_kiosk(station) and not station_ops.account_presentation(app)
                and station_ops.server_kiosk_status(station, False) is None):
            # Status do totem: conta oficial sem Stripe no servidor → indisponível (payments_unavailable).
            # A API com ``kiosk_status`` no posto já decide; só a antiga precisa da consulta.
            from ..services import payments
            config = await payments.config(app, refresh=True)
        from . import central_admin
        central = await central_admin.build(app, station)
        return _data_page(app, station, code, config, central)
    if page == 'power':
        from . import station_power
        return await station_power.build(app, station, section=section, connector_id=connector_id)
    if page == 'connectors':
        return _connectors_page(app, station)
    return _main_page(app, station, code)


def _connectors_line(points):
    if not points:
        return 'Nenhum carregador · vincular uma central'
    live = sum(1 for point in points if point.get('active') is not False)
    parts = [chargers.plural(len(points), 'carregador', 'carregadores'),
             chargers.plural(live, 'publicado', 'publicados')]
    if any('charger_link' in point for point in points):
        online = sum(1 for point in points if chargers.link_state(point) == 'online')
        parts.append(f'{online} online')
    return ' · '.join(parts)


def _data_subtitle(station):
    parts = ['Nome', 'endereço', 'status']
    if chargers.screen_online(station) is not None:
        parts.append('central')  # a estação é a central: o status online dela fica em Dados da estação
    if station_ops.has_kiosk(station):
        parts.append(f"totem ({'ligado' if station.get('kiosk_mode') else 'desligado'})")
    return ', '.join(parts[:-1]) + ' e ' + parts[-1]


def _main_page(app, station, code):
    sid = station['id']
    points = _live_points(station)
    go = lambda page: app.link('station_admin', station_id=sid, page=page)  # noqa: E731
    title = [design.txt(f'Estação {code}', 16, 'bold', expand=True)]
    online = chargers.screen_online(station)
    if online is not None:  # status da central; cada carregador tem o seu em Carregadores
        title.append(chargers.pill(f"Central {'online' if online else 'offline'}", chargers.screen_status(online)[1]))
    return design.page(
        heading(app, station.get('name') or 'Estação'),
        ft.Container(height=11),
        ft.Column([ft.Row(title, spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                   design.txt(_street(station.get('address')), 11, 'regular', theme.GRAY_TEXT)], spacing=9),
        ft.Container(height=19),
        ft.Column([
            menu_row('Dados da estação', _data_subtitle(station), ft.Icons.EDIT_OUTLINED, go('data')),
            menu_row('Carregadores', _connectors_line(points), ft.Icons.EV_STATION_OUTLINED, go('connectors')),
            menu_row('Potência', power_summary(station, points), ft.Icons.BOLT_OUTLINED, go('power')),
            menu_row('Tarifa', 'Tarifa base, por horário e por demanda', ft.Icons.TRENDING_UP,
                     app.link('tariffs', station_id=sid)),
        ], spacing=29),
        ft.Container(height=18),
        chatbot_button(app, 38), gap=14)


def _connectors_page(app, station):
    """Carregadores do posto: status de cada carregador, editar e Adicionar carregador."""
    from .operator import _point_status  # evita import circular
    from .setup_ui import cta

    sid = station['id']
    is_demo = bool(getattr(app.api, 'is_demo', False))
    refresh = StationRefresh(app, sid)

    def charger_row(connector):
        status, color = _point_status(connector)
        details = [design.list_row(
            connector['public_code'], chargers.charger_subtitle(connector), tile=44, dark_tile=True,
            icon='/design/icon_station_charge.svg', trailing=chargers.pill(status, color),
            on_click=app.link('operator', station_id=sid, connector_id=connector['id'], nav=False))]
        if not connector.get('active') and not connector.get('retired'):
            shared = bool(station.get('active') or len(station.get('connectors') or []) > 1)
            details.append(cta('Revisar e ativar carregador', app.link(
                'operator', station_id=sid, point_id=connector['id'], onboarding=True, step=2 if shared else 1,
                **({'existing_station': True} if shared else {})), weight='semibold'))
        return ft.Column(details, spacing=8)

    rows = ft.Column(spacing=16, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    row_holders = {}

    def paint_rows():
        listing = []
        for point in station.get('connectors') or []:
            holder = row_holders.setdefault(point['id'], ft.Container(data=f"charger-row:{point['id']}"))
            holder.content = charger_row(point)
            listing.append(holder)
        rows.controls = listing or [design.txt('Nenhum carregador neste posto.', 12.5, 'regular', theme.GRAY_TEXT)]

    paint_rows()
    result = design.txt('', 11.5, 'semibold', visible=False, data='charger-added')

    async def add():
        refresh.invalidate()
        try:
            created = await chargers.add_charger(app, station)
        except ApiError as exc:
            result.value, result.color, result.visible = str(exc), theme.RED, True
            app.page.update()
            raise
        finally:
            refresh.invalidate()
        station.setdefault('connectors', []).append(created)
        paint_rows()
        result.value, result.color, result.visible = chargers.added_text(created), theme.TEXT_COLOR, True
        if hasattr(app, 'mark_saved'):
            app.mark_saved()
        app.page.update()

    async def update():
        fresh = await refresh.read()
        if not isinstance(fresh, dict):
            return
        station.update(fresh)
        paint_rows()
        app.page.update()

    app.set_poll(update, POLL_SECONDS)
    body = [heading(app, 'Carregadores', app.link('station_admin', station_id=sid)),
            design.txt('Toque em um carregador para editar tipo, potência e endereço. A tarifa fica em Tarifa.',
                       11.5, 'regular', theme.GRAY_TEXT),
            rows, result,
            cta(chargers.ADD_LABEL, app.action(add), weight='semibold'),
            design.txt(chargers.ADD_HINT, 11, 'regular', theme.GRAY_TEXT)]
    if is_demo:
        from ..demo import DEMO_PRESENCE_CODE
        body.append(design.txt(f'Teste no modo motorista com {DEMO_PRESENCE_CODE}.', 11, 'regular', theme.GRAY_TEXT))
    return design.page(*body, gap=16, gutter=3)


def _data_page(app, station, code, payments_config=None, central=None):
    sid = station['id']
    name = design.input_field(station.get('name') or '')
    address = design.input_field(station.get('address') or '')
    ident = design.input_field(code, read_only=True)
    state = {'active': station.get('active', True), 'saved': (station.get('name'), station.get('address'))}
    holder = ft.Container(data='data-status')

    chosen = {}

    async def persist(extra=None):
        current = (name.value.strip(), address.value.strip())
        body = dict(extra or {})
        if current != state['saved']:
            if not current[0] or not current[1]:
                raise ApiError('Informe nome e endereço da estação.')
            body.update({'name': current[0], 'address': current[1]})
            if current[1] != state['saved'][1]:
                # Endereço novo: a localização do mapa vem dele (sugestão escolhida ou busca).
                try:
                    lat, lng = await station_location(app.api, current[1], chosen.get('item'), station,
                                                      demo=bool(getattr(app.api, 'is_demo', False)))
                except ValueError as error:
                    address.error_text = str(error)
                    app.page.update()
                    raise ApiError(str(error)) from None
                address.error_text = None
                body.update({'latitude': str(lat), 'longitude': str(lng)})
        if not body:
            return
        saved = await app.api.request('PATCH', f'stations/{sid}', body)
        if isinstance(saved, dict):  # status novo muda o totem (estação inativa = indisponível)
            station.update({key: saved[key] for key in ('active', 'kiosk_status') if key in saved})
        state['saved'] = current
        if hasattr(app, 'mark_saved'):
            app.mark_saved()
        app.notice('Dados da estação salvos.')

    async def blur():
        # Tocar numa sugestão tira o foco antes do clique: espera a escolha (que já salva) e só
        # então salva o texto digitado, para não gravar o endereço pela metade.
        await asyncio.sleep(0.35)
        await persist()

    async def picked(item):
        chosen['item'] = item
        await persist()
    suggestions = address_autocomplete.attach(app, address, picked)

    async def choose(value):
        active = value == 'on'
        try:
            await persist({'active': active})
        except ApiError as exc:
            app.notice(str(exc))
            return
        state['active'] = active
        station['active'] = active
        draw()
        if redraw_kiosk:
            redraw_kiosk()
        app.page.update()

    def draw():
        holder.content = design.segmented([('on', 'Ativa'), ('off', 'Inativa')],
                                          'on' if state['active'] else 'off', choose, height=37.5)
    draw()
    kiosk, redraw_kiosk = station_ops.kiosk_control(app, station, payments_config)
    central = central if central is not None else chargers.screens_card(station)
    name.on_blur = app.action(blur)
    address.on_blur = app.action(blur)
    name.on_submit = app.action(blur)
    address.on_submit = app.action(blur)
    return design.page(
        heading(app, 'Dados de estação'),
        ft.Container(ft.Column([
            design.labeled('Nome da estação', _round(name), gap=14),
            design.labeled('Endereço', ft.Column([_round(address), suggestions], spacing=6,
                                                 horizontal_alignment=ft.CrossAxisAlignment.STRETCH), gap=14),
            design.labeled('Identificador', _round(ident), gap=14),
            ft.Container(design.labeled('Status', holder, gap=5, strong=False), margin=ft.Margin(left=0, top=1, right=0, bottom=0)),
            *([central] if central else []),
            *([kiosk] if kiosk else []),
        ], spacing=15), margin=ft.Margin(left=0, top=16, right=0, bottom=0)),
        gap=16, gutter=3)
