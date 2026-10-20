import asyncio
import unicodedata
from copy import deepcopy
from decimal import Decimal, InvalidOperation

import flet as ft

from ..api_client import ApiError
from ..services.discovery import discover
from ..services.driver import amenity_label
from ..services.location import geocode_address, geocode_demo_address
from ..services.maps import station_map_widget
from ..services.planning import estimate_text, intent_limits
from ..ui import design as D
from ..ui import theme
from ..ui.availability import point_status, station_map_record
from ..ui.components import badge, button, card, money, pill
from ..ui.deferred import fill_when_ready, skeleton
from ..ui.forecast import best_time_card
from ..ui.point_summary import point_context

CONNECTOR_LABELS = {'type2':'Tipo 2','ccs2':'CCS2','chademo':'CHAdeMO','bench':'Bancada'}
SORT_OPTIONS = [('default','Padrão'),('price','Menor tarifa'),('distance','Mais perto')]
PLAN_OPTIONS = [('none','Só comparar'),('time','Por tempo'),('value','Por valor')]
PLAN_LABELS = {'none':'Minutos ou valor em R$','time':'Tempo disponível (min)','value':'Orçamento máximo (R$)'}
PLAN_HINTS = {'none':'','time':'Ex.: 30','value':'Ex.: 25,00'}
DEFAULTS = dict(lat=None,lng=None,radius=5,query='',connector_type=None,available_only=False,
                max_price_per_kwh=None,sort='default',planning_intent={})
LOCATION_KEYS = ('lat','lng','radius','query')
FILTER_KEYS = ('connector_type','available_only','max_price_per_kwh','sort','planning_intent')


def _available(station, point):
    return (station.get('active') is not False and point.get('active') is not False
            and not point.get('retired') and point.get('online') is not False
            and point.get('available') is True
            and point.get('availability_status') in (None, 'available'))


def _map_records(items):
    """Dados do mapa (pino, vagas, preço e distância) de cada posto da lista."""
    records = []
    for station in items:
        metadata = station.get('discovery') or {}
        matching = metadata.get('matching_connector_ids')
        shown = {**station,'connectors':[p for p in station['connectors'] if matching is None or p['id'] in matching]}
        record = station_map_record(shown,_available)
        if metadata.get('point'):
            record['price'] = float(metadata['point']['price_per_kwh'])
            record['status'] = point_status(metadata['point'])[0]
        if metadata.get('distance_km') is not None:
            record['distance_km'] = float(metadata['distance_km'])
        records.append(record)
    return records


def _seed_details(app, items, path, params):
    """Cada posto da lista é a mesma resposta de ``GET stations/{id}`` (sem ``discovery``): o detalhe
    abre na hora, com a idade da lista, e se atualiza pelo poll da tela."""
    from ..services.prefetch import supported
    if not supported(app):
        return
    seed, at = app.api.seed, app.api.cached_at(path,params)
    for item in items:
        if isinstance(item,dict) and item.get('id'):
            seed(f"stations/{item['id']}",{key:value for key,value in item.items() if key != 'discovery'},at=at)


async def warm_list_map(app, items):
    """Compõe e guarda o mapa da aba Recarga (busca padrão) antes de a pessoa abrir a aba."""
    if not items:
        return
    width = max(200,min(getattr(app.page,'width',None) or 400,600)-40)
    await station_map_widget(_map_records(items),lambda selected_id:None,offline=False,width=width,variant='list')


async def warm_detail_map(app, station):
    """Compõe e guarda o mapa do detalhe de um posto (o provável próximo toque na lista)."""
    width = max(200,min(getattr(app.page,'width',None) or 400,600)-45)
    detail = {key:value for key,value in station.items() if key != 'discovery'}  # = GET stations/{id}
    await station_map_widget(_map_records([detail]),lambda selected_id:None,offline=False,width=width,
                             variant='detail')


def _fold(text):
    return unicodedata.normalize('NFKD', str(text or '')).encode('ascii', 'ignore').decode().lower().strip()


def _area(address):
    """'Av. X, 10, Pinheiros, São Paulo - SP' -> 'Pinheiros - São Paulo' (reference subtitle)."""
    text = str(address or '').strip()
    head, _, uf = text.rpartition(' - ')
    if head and len(uf.strip()) == 2:
        text = head
    parts = [part.strip() for part in text.split(',') if part.strip()]
    return f'{parts[-2]} - {parts[-1]}' if len(parts) >= 3 else text


def _street(address):
    """'Av. X, 10, Pinheiros, São Paulo - SP' -> 'Av. X, 10' (reference detail line)."""
    parts = [part.strip() for part in str(address or '').split(',') if part.strip()]
    return ', '.join(parts[:2]) if len(parts) >= 4 else str(address or '')


def _connector_groups(station):
    """Group points by connector type + nominal power: [(title, subtitle)]."""
    groups = {}
    for point in station.get('connectors') or []:
        key = (str(point.get('connector_type') or ''), _number(point.get('power_kw') or 0))
        total, free = groups.get(key, (0, 0))
        groups[key] = (total + 1, free + (1 if _available(station, point) else 0))
    rows = []
    for (kind, power), (total, free) in groups.items():
        if free == 0:
            sub = 'Nenhum conector livre'
        elif free == total:
            sub = f'{free} conector livre' if total == 1 else f'{free} conectores livres'
        else:
            sub = f"{free} de {total} conectores livre{'' if free == 1 else 's'}"
        rows.append((f'{kind} - {power} kW', sub))
    return rows


def _map_url(station):
    try:
        return f"https://www.google.com/maps/dir/?api=1&destination={float(station['latitude'])},{float(station['longitude'])}"
    except (KeyError, TypeError, ValueError):
        from urllib.parse import quote
        return 'https://www.google.com/maps/search/?api=1&query=' + quote(str(station.get('address') or station.get('name') or ''))


def _number(value):
    return f'{float(value):g}'.replace('.', ',')


def _booking_presets(intention):
    """Plano da busca (por valor, tempo ou autonomia) já preenchido no assistente de recarga."""
    intention = intention or {}
    if intention.get('mode') == 'value' and intention.get('max_cost'):
        return {'by':'value','amount':str(intention['max_cost']).replace('.',',')}
    if intention.get('mode') == 'autonomy' and intention.get('km'):
        return {'by':'autonomy','amount':intention['km']}
    if intention.get('mode') == 'time' and intention.get('minutes'):
        return {'by':'time','amount':intention['minutes']}
    return {}


def _filter_summary(connector_type, available_only, max_price_per_kwh, sort, intention):
    """Active filters in reading order (one entry per filter: the badge shows how many)."""
    summary = []
    if connector_type:
        summary.append(CONNECTOR_LABELS.get(connector_type, connector_type))
    if available_only:
        summary.append('disponíveis')
    if max_price_per_kwh is not None:
        summary.append(f'até {money(max_price_per_kwh)}/kWh')
    if sort != 'default':
        summary.append('menor tarifa' if sort == 'price' else 'mais perto da busca')
    if intention:
        summary.append(f"tenho {intention['minutes']} min" if intention['mode'] == 'time' else f"até {money(intention['max_cost'])}")
    return summary


async def _locate(demo, text):
    """Typed address -> (lat, lng). The demo account only resolves bundled places (no network)."""
    if demo:
        from ..demo import DEMO_LOCATIONS
        from ..services.driver_demo import DEMO_DRIVER_NETWORK
        coordinates = geocode_demo_address(text,(*DEMO_LOCATIONS,*DEMO_DRIVER_NETWORK))
        if not coordinates:
            raise ApiError('Na conta demo, busque um local de exemplo (Villa Lobos, Marginal Pinheiros, Av. Paulista, '
                           'Congonhas). A busca não acessa a internet.')
        return coordinates
    try:
        coordinates = await geocode_address(text)
    except Exception as exc:
        raise ApiError('Não foi possível localizar o endereço. Verifique a conexão e tente novamente.') from exc
    if not coordinates:
        raise ApiError('Endereço não encontrado. Tente o nome da rua com o bairro ou a cidade.')
    return coordinates


def _filter_sheet(app, current, location, *, close):
    """Bottom sheet with the comparison filters (connector, price, order, time/value plan).

    ``current`` holds the applied filter values (route params); ``location`` the active
    address search, kept untouched when the filters are applied or cleared.
    """
    intent = current['planning_intent'] or {}
    max_price = current['max_price_per_kwh']
    draft = {'connector_type':current['connector_type'] or '','available_only':bool(current['available_only']),
             'sort':current['sort'] or 'default','plan_mode':intent.get('mode','none')}
    price = D.input_field(str(max_price).replace('.',',') if max_price is not None else '','Ex.: 2,50',
                          keyboard=ft.KeyboardType.NUMBER,max_length=12)
    price.data = 'max_price_per_kwh'
    plan_value = D.input_field(str(intent.get('minutes',intent.get('max_cost',''))).replace('.',','),
                               PLAN_HINTS[draft['plan_mode']],keyboard=ft.KeyboardType.NUMBER,max_length=12)
    plan_value.data = 'plan_value'
    for control in (price,plan_value):
        control.counter = ''
    available = ft.Switch(value=draft['available_only'],active_track_color=theme.BTN_PRIMARY,
                          active_color=theme.BTN_PRIMARY_FG,inactive_track_color=theme.TILE,
                          inactive_thumb_color=theme.GRAY_TEXT,track_outline_color=ft.Colors.TRANSPARENT,
                          data='available_only')
    error = D.txt('',11.5,'medium',theme.RED,visible=False)
    sections = ft.Column(spacing=20,horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    def refresh():
        app.page.update()

    def pick(key, value):
        async def choose(event=None):
            if key == 'plan_mode' and value != draft['plan_mode']:
                # A number entered as minutes must not silently become a money limit.
                plan_value.value = ''
                plan_value.hint_text = PLAN_HINTS[value] or None
            draft[key] = value
            error.visible = False
            render()
            refresh()
        return choose

    def segment(key):
        return lambda value: pick(key,value)()

    async def toggle_available(event=None):
        draft['available_only'] = bool(available.value)

    available.on_change = toggle_available

    def render():
        chips = []
        for key,text in [('','Todos'),*CONNECTOR_LABELS.items()]:
            chip = D.chip_option(text,selected=draft['connector_type'] == key,on_click=pick('connector_type',key))
            chip.alignment = None  # hug the label (an aligned container would take the whole row)
            chips.append(chip)
        connectors = ft.Row(chips,wrap=True,spacing=8,run_spacing=8)
        mode = draft['plan_mode']
        plan = [D.segmented(PLAN_OPTIONS,mode,segment('plan_mode'))]
        if mode != 'none':
            plan.append(D.labeled(PLAN_LABELS[mode],plan_value))
        plan.append(D.txt('Estimativas pela potência nominal. O ponto pode entregar menos potência. Nenhuma cobrança real.',
                          10.5,'regular',theme.GRAY_TEXT))
        sections.controls = [
            D.labeled('Conector',connectors),
            D.card_box(ft.Row([ft.Column([D.txt('Somente pontos disponíveis',13,'semibold'),
                                          D.txt('Esconde postos sem conector livre agora',10.5,'regular',theme.GRAY_TEXT)],
                                         spacing=3,expand=True,tight=True),available],
                              vertical_alignment=ft.CrossAxisAlignment.CENTER),
                       padding=ft.Padding(left=14,right=8,top=10,bottom=10)),
            D.labeled('Tarifa máxima (R$/kWh)',price),
            D.labeled('Ordenar por',D.segmented(SORT_OPTIONS,draft['sort'],segment('sort'))),
            D.labeled('Tempo / valor em comparação',ft.Column(plan,spacing=12,horizontal_alignment=ft.CrossAxisAlignment.STRETCH)),
        ]

    def values():
        maximum = None
        try:
            text = (price.value or '').strip()
            if text:
                maximum = Decimal(text.replace(',','.'))
                if not maximum.is_finite() or not 0 <= maximum <= 10000:
                    raise InvalidOperation
        except (InvalidOperation,ValueError):
            raise ApiError('Informe uma tarifa máxima de zero a R$ 10.000 por kWh.')
        intent = {}
        mode = draft['plan_mode']
        if mode != 'none':
            try:
                amount = Decimal((plan_value.value or '').strip().replace(',','.'))
                ceiling = 1440 if mode == 'time' else 100000
                if not amount.is_finite() or not 0 < amount <= ceiling or (mode == 'time' and amount != amount.to_integral_value()):
                    raise InvalidOperation
                intent = {'mode':'time','minutes':int(amount)} if mode == 'time' else {'mode':'value','max_cost':format(amount,'f')}
            except (InvalidOperation,ValueError):
                raise ApiError('Informe minutos inteiros de 1 a 1.440 ou um valor maior que zero e de até R$ 100.000.')
        if draft['sort'] == 'distance' and location.get('lat') is None:
            raise ApiError('Busque um endereço na barra de busca para ordenar por proximidade.')
        return dict(connector_type=draft['connector_type'] or None,available_only=bool(available.value),
                    max_price_per_kwh=format(maximum,'f') if maximum is not None else None,
                    sort=draft['sort'],planning_intent=intent)

    async def apply(event=None):
        try:
            chosen = values()
        except ApiError as exc:
            error.value, error.visible = str(exc), True
            refresh()
            return
        close()
        await app.go('stations',**location,**{key:value for key,value in chosen.items() if value != DEFAULTS[key]})

    async def clear(event=None):
        close()
        await app.go('stations',**location)

    async def dismiss(event=None):
        close()

    render()
    summary = _filter_summary(current['connector_type'],current['available_only'],max_price,current['sort'],intent)
    header = ft.Row([
        ft.Column([D.txt('Filtros',18,'bold'),
                   D.txt('Ativos: '+' · '.join(summary) if summary else 'Compare por conector, preço e tempo',
                         11,'regular',theme.GRAY_TEXT,max_lines=2,overflow=ft.TextOverflow.ELLIPSIS)],
                  spacing=4,expand=True,tight=True),
        ft.Container(ft.Icon(ft.Icons.CLOSE,size=22,color=theme.TEXT_COLOR),width=40,height=40,border_radius=20,
                     alignment=ft.Alignment(0,0),on_click=dismiss,ink=True,tooltip='Fechar',bgcolor=theme.CARD)],
        vertical_alignment=ft.CrossAxisAlignment.START)
    handle = ft.Container(ft.Container(width=40,height=4,border_radius=2,bgcolor='#4A4A4A' if theme.is_dark() else theme.BORDER_SOFT),
                          alignment=ft.Alignment(0,0),padding=ft.Padding(left=0,right=0,top=0,bottom=6))
    footer = ft.Row([ft.Container(D.secondary_button('Limpar',clear,height=48),expand=2,border_radius=D.RADIUS_BTN,
                                  border=ft.Border.all(1,theme.BORDER_SOFT)),
                     ft.Container(D.primary_button('Aplicar filtros',apply,height=50,weight='bold'),expand=3)],spacing=12)
    body = ft.Column([handle,header,sections,error,footer],spacing=18,tight=True,
                     horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    return ft.BottomSheet(
        ft.Container(body,padding=ft.Padding(left=D.GUTTER,right=D.GUTTER,top=10,bottom=22)),
        bgcolor='#262626' if theme.is_dark() else theme.BG_COLOR,scrollable=True,dismissible=True,
        shape=ft.RoundedRectangleBorder(radius=ft.BorderRadius(top_left=24,top_right=24,bottom_left=0,bottom_right=0)),
        barrier_color='#A6000000',data='station-filters')


async def build(app, lat=None, lng=None, radius=5, query='', station_id=None, offset=0,
                connector_type=None, available_only=False, max_price_per_kwh=None, sort='default', planning_intent=None,
                typed_query='', filters_open=False, demo_seed=None, **_):
    intention = deepcopy(planning_intent) if planning_intent else {}
    route_state = dict(lat=lat,lng=lng,radius=radius,query=query,connector_type=connector_type,
                       available_only=available_only,max_price_per_kwh=max_price_per_kwh,sort=sort,planning_intent=intention)
    route_state = {key:value for key,value in route_state.items() if value != DEFAULTS[key]}
    demo = getattr(app.api,'is_demo',False) is True
    if demo_seed:
        from .reservations import seed_demo
        await seed_demo(app,demo_seed)
    # Aba Recarga: a busca é a tela da aba; a reserva ativa / recarga em andamento aparece no topo.
    show_active = not station_id and getattr(app,'browsing_mode','consumer') != 'vendor'
    active_box = ft.Column(spacing=10,horizontal_alignment=ft.CrossAxisAlignment.STRETCH,data='active-recharge')
    active_seen = [None]

    async def refresh_active(found=None):
        from .reservations import (
            active_recharge,
            active_recharge_cards,
            active_snapshot,
        )
        reservation, session = found if found is not None else await active_recharge(app)
        snapshot = active_snapshot(reservation, session)
        if snapshot == active_seen[0]:
            return False
        active_seen[0] = snapshot
        active_box.controls = active_recharge_cards(app,reservation,session,demo)
        active_box.visible = bool(active_box.controls)
        return True
    if station_id:
        # "Melhor horário" sai junto com o posto (em paralelo), não depois dele.
        prefetch = getattr(app.api,'prefetch',None)
        if prefetch is not None:
            prefetch(f'stations/{station_id}/best-times',{'hours':12})
        stations = [deepcopy(await app.api.request('GET',f'stations/{station_id}'))]
        total = 1
    else:
        params = {'limit':20,'offset':offset,'sort':sort,'available_only':available_only}
        if connector_type:
            params['connector_type'] = connector_type
        if max_price_per_kwh is not None:
            params['max_price_per_kwh'] = max_price_per_kwh
        if lat is not None and lng is not None:
            params.update(lat=lat,lng=lng,radius_km=radius)
        if show_active:
            from .reservations import active_recharge
            # Lista e cartão da recarga ativa em paralelo (antes: um depois do outro).
            result, found = await asyncio.gather(app.api.request('GET','stations',params=params),active_recharge(app))
            await refresh_active(found)
        else:
            result = await app.api.request('GET','stations',params=params)
        stations, total = deepcopy(result['items']), result['total']
        _seed_details(app,result['items'],'stations',params)
    if not show_active:
        active_box.visible = False
    if station_id:
        first = stations[0]
        station_heading = ft.Column([D.txt(first['name'],21.5,'bold'),D.txt(_street(first['address']),11.5,'regular',theme.GRAY_TEXT)],spacing=5)
        amenities = [amenity for amenity in first.get('amenities') or [] if isinstance(amenity,dict)]
        amenity_row = [ft.Row([pill(amenity_label(amenity)) for amenity in amenities],wrap=True,spacing=6,run_spacing=6)] if amenities else []
        group_rows = [ft.Container(ft.Row([D.icon_tile(None,size=42),
                                           ft.Column([D.txt(group_title,14,'semibold'),D.txt(group_sub,11,'regular',theme.GRAY_TEXT)],
                                                     spacing=3,expand=True,alignment=ft.MainAxisAlignment.CENTER)],
                                          spacing=8,vertical_alignment=ft.CrossAxisAlignment.CENTER),
                                   bgcolor=theme.CARD,border_radius=D.RADIUS_CARD,padding=ft.Padding(left=11,right=11,top=12,bottom=12))
                      for group_title,group_sub in _connector_groups(first)]
        route_row = ft.Container(ft.Row([ft.Icon(ft.Icons.TIMELINE,size=20,color=theme.TEXT_COLOR),
                                         D.txt('Abrir rota no Google Maps',14,'semibold',expand=True),
                                         ft.Icon(ft.Icons.OPEN_IN_NEW,size=20,color=theme.GRAY_TEXT)],
                                        spacing=12,vertical_alignment=ft.CrossAxisAlignment.CENTER),
                                 bgcolor=theme.CARD,border_radius=D.RADIUS_BTN,height=43,
                                 padding=ft.Padding(left=17,right=14,top=0,bottom=0),url=_map_url(first),ink=True)
        # "Melhor horário para carregar" (previsão + tarifa por horário); some se a API falhar.
        best_slot = ft.Container(data='best-time-slot')

        async def load_best_time():
            try:
                payload = await app.api.request('GET',f'stations/{station_id}/best-times',params={'hours':12})
            except ApiError:
                return ft.Container(visible=False)
            return best_time_card(payload) or ft.Container(visible=False)
        await fill_when_ready(app,best_slot,load_best_time,placeholder=ft.Container(height=0))
        controls = [ft.Container(D.txt('Detalhes da estação',19,'bold'),margin=ft.Margin(left=0,top=2,right=0,bottom=0)),
                    ft.Container(station_heading,padding=ft.Padding(left=0,right=0,top=22,bottom=16)),
                    D.section_label('Conectores'),ft.Column(group_rows,spacing=16.5),
                    ft.Container(height=6.5),route_row,best_slot,
                    # Dois caminhos, cada um com o seu assistente (conector, cobrança, potência e pagamento):
                    # reservar segura o ponto por 15 min até a chegada; carregar agora começa no ponto (código #F).
                    ft.Row([D.primary_button('Reservar estação',app.link('booking',station_id=station_id,step=1,kind='reserve',
                                                                          **_booking_presets(intention)),
                                             height=55,size=15,expand=True),
                            D.secondary_button('Carregar agora',app.link('booking',station_id=station_id,step=1,kind='now',
                                                                         **_booking_presets(intention)),
                                               height=55,size=15,expand=True)],spacing=10),
                    D.txt('Reservar guarda o ponto por 15 minutos até você chegar. Carregar agora é para quem já está no posto.',
                          11,'regular',theme.GRAY_TEXT,text_align=ft.TextAlign.CENTER),
                    *amenity_row]
        # The reference puts the map right under the title.
        map_slot_index = 2
    else:
        controls = []
    typed = {'text':str(typed_query or '')}  # typed_query: texto já digitado na busca (captura/atalhos)
    map_preview = ft.Container(visible=False)
    map_signature = None
    map_section = ft.Column(controls=[map_preview],visible=False,spacing=0,horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    map_width = max(200,min(getattr(app.page,'width',None) or 400,600)-(40 if not station_id else 45))
    map_ratio = 362/158
    async def resize_map_section(event):
        nonlocal map_width
        if event.width > 0:
            map_width = event.width
    map_section.on_size_change = resize_map_section

    def typed_matches(items):
        text = _fold(typed['text'])
        if not text:
            return items
        return [item for item in items if text in _fold(item.get('name')) or text in _fold(item.get('address'))]

    def demo_crop(records):
        # Reference demo map: Marginal Pinheiros by default, Villa Lobos when it is the searched/opened station.
        first = _fold(records[0].get('name')) if records else ''
        if (station_id or typed['text'].strip()) and first == 'villa lobos':
            return 'villa'
        return 'marginal' if first in ('villa lobos','marginal pinheiros') else None

    async def refresh_map(items, initial=False):
        nonlocal map_signature
        items = typed_matches(items) if not station_id else items
        records = _map_records(items)
        signature = [{key:record.get(key) for key in ('id','name','latitude','longitude','free_points','status','price','distance_km')}
                     for record in records] + [demo_crop(records)]
        if signature == map_signature:
            return
        if items:
            def draw():
                return station_map_widget(records,lambda selected_id:app.link('stations',station_id=selected_id,**route_state),
                                          offline=demo,crop=demo_crop(records),width=map_width,variant='detail' if station_id else 'list',
                                          reference=(lat,lng) if lat is not None and lng is not None else None)
            if initial:
                # The list is usable before the map tiles arrive.
                await fill_when_ready(app,map_preview,draw,placeholder=skeleton(map_width/map_ratio))
            else:
                map_preview.content = await draw()
        else:
            map_preview.content = None
        map_preview.visible = bool(items)
        map_section.visible = bool(items)
        map_signature = signature

    await refresh_map(stations, initial=True)
    result_count = ft.Text(size=12,color=theme.GRAY_TEXT,visible=not bool(station_id))
    listing = ft.Column(spacing=16 if not station_id else 10,horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    if station_id:
        # Sem lista de pontos aqui: a escolha do conector acontece no assistente (sem repetir a tela).
        controls.insert(map_slot_index-1,map_section)
    list_heading = D.txt('Perto de Você',15,'bold')
    page_head = D.txt('Encontre uma estação',15,'bold')
    page_head_box = ft.Container(page_head,margin=ft.Margin(left=0,top=2,right=0,bottom=0))
    search_box = ft.TextField(
        hint_text='Buscar por endereço ou estação', hint_style=ft.TextStyle(size=11,color=theme.GRAY_TEXT,font_family=D.FONT),
        text_style=ft.TextStyle(size=11,color=theme.GRAY_TEXT,font_family=D.FONT), border=ft.NoInputBorder(),
        cursor_color=theme.INPUT_TEXT, content_padding=ft.Padding(left=0,right=12,top=0,bottom=0), expand=True,
        text_size=11, capitalization=ft.TextCapitalization.WORDS, value=typed['text'])
    location_state = {key:route_state[key] for key in LOCATION_KEYS if key in route_state}
    filter_state = {key:route_state[key] for key in FILTER_KEYS if key in route_state}
    active_filters = _filter_summary(connector_type,available_only,max_price_per_kwh,sort,intention)

    def close_filters():
        pop = getattr(app.page,'pop_dialog',None)
        if pop:
            pop()

    def open_filters(event=None):
        sheet = _filter_sheet(app,dict(connector_type=connector_type,available_only=available_only,
                                       max_price_per_kwh=max_price_per_kwh,sort=sort,planning_intent=intention),
                              location_state,close=close_filters)
        app.page.show_dialog(sheet)

    filter_count = ft.Container(D.txt(str(len(active_filters)),8.5,'bold','#FFFFFF',text_align=ft.TextAlign.CENTER),
                                width=15,height=15,border_radius=8,bgcolor=theme.RED,alignment=ft.Alignment(0,0),
                                right=-6,top=-6,visible=bool(active_filters),data='filter-count')
    filter_button = ft.Container(
        ft.Stack([ft.Icon(ft.Icons.TUNE,size=22,color=theme.TEXT_COLOR if active_filters else theme.GRAY_TEXT),filter_count],
                 width=22,height=22,clip_behavior=ft.ClipBehavior.NONE),
        width=50,height=47,alignment=ft.Alignment(0,0),on_click=open_filters,ink=True,border_radius=12,
        tooltip='Filtros'+(f' ({len(active_filters)} ativos)' if active_filters else ''),data='station-filters')
    search_field = ft.Container(ft.Row([ft.Icon(ft.Icons.SEARCH,size=22,color=theme.GRAY_TEXT),search_box,filter_button],spacing=10,
                                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
                                bgcolor=theme.INPUT_BG,border_radius=12,height=47,padding=ft.Padding(left=13.5,right=2,top=0,bottom=0))
    location_chip = None
    if query or (lat is not None and lng is not None):
        place = query or f'{float(lat):.4f}, {float(lng):.4f}'.replace('.',',')
        location_chip = ft.Container(ft.Row([
            ft.Icon(ft.Icons.LOCATION_ON_OUTLINED,size=16,color=theme.GRAY_TEXT),
            D.txt(f'Perto de {place} · {_number(radius)} km',11,'medium',theme.TEXT_COLOR,expand=True,max_lines=1,
                  overflow=ft.TextOverflow.ELLIPSIS),
            ft.Container(ft.Icon(ft.Icons.CLOSE,size=16,color=theme.GRAY_TEXT),width=30,height=30,border_radius=15,
                         alignment=ft.Alignment(0,0),on_click=app.link('stations',**filter_state),ink=True,
                         tooltip='Limpar endereço')],
            spacing=6,vertical_alignment=ft.CrossAxisAlignment.CENTER),
            bgcolor=theme.CARD,border_radius=10,height=34,padding=ft.Padding(left=10,right=2,top=0,bottom=0))
    def station_cards(stations):
        items = []
        for station in (stations if station_id else typed_matches(stations)):
            metadata = station.get('discovery') or {}
            available_count = metadata.get('available_points',sum(_available(station,point) for point in station['connectors']))
            if not station_id:
                chosen = metadata.get('point')
                if chosen is None:
                    chosen = discover([station])[0]['discovery']['point']
                if station.get('active') is False:
                    right = D.txt('Posto desativado',11,'medium',theme.GRAY_TEXT)
                elif not station['connectors']:
                    right = D.txt('Sem pontos cadastrados',11,'medium',theme.GRAY_TEXT)
                elif chosen:
                    right = D.txt(f"{money(chosen['price_per_kwh'])}/kWh",13,'bold')
                    if not available_count:
                        right = ft.Column([right,D.txt('Sem pontos livres',10,'regular',theme.GRAY_TEXT)],spacing=2,
                                          horizontal_alignment=ft.CrossAxisAlignment.END)
                else:
                    right = D.txt('Indisponível',11,'medium',theme.GRAY_TEXT)
                subtitle = _area(station['address'])
                if intention and chosen:
                    subtitle += '\n'+estimate_text(chosen,**intent_limits(chosen,intention))
                from .home import _station_row
                items.append(_station_row(station,app.link('stations',station_id=station['id'],**route_state),
                                          right=right,subtitle=subtitle))
                continue
            matching_points = station['connectors']
            if connector_type or available_only or max_price_per_kwh is not None:
                matches = discover([station],connector_type=connector_type,available_only=available_only,max_price_per_kwh=max_price_per_kwh)
                ids = matches[0]['discovery']['matching_connector_ids'] if matches else []
                matching_points = [p for p in matching_points if p['id'] in ids]
            if not matching_points:
                items.append(card(ft.Text('Nenhum ponto atende à comparação neste momento.',color=theme.GRAY_TEXT)))
            for connector in sorted(matching_points, key=lambda item: not _available(station,item)):
                key = app.api.new_key()
                async def reserve(c=connector,k=key):
                    await app.api.request('POST','reservations',{'connector_id':c['id']},key=k)
                    app.planning_intent = {'connector_id':c['id'],'intent':deepcopy(intention),'station_search':deepcopy(route_state)} if intention or route_state else None
                    await app.go('reservations',detail=True)
                status, status_color = point_status(connector)
                if station.get('active') is False or connector.get('active') is False or connector.get('retired'):
                    status,status_color = 'Desativado',theme.SLATE
                elif connector.get('online') is False:
                    status,status_color = 'Offline',theme.SLATE
                elif status == 'Disponível' and not _available(station,connector):
                    status,status_color = 'Indisponível',theme.SLATE
                details = [ft.Text(f"{connector['public_code']} · {connector['connector_type']}",size=18,weight=ft.FontWeight.BOLD,color=theme.TEXT_COLOR),
                           ft.Row([badge(status,bg=status_color,width=110)]),
                           ft.Text(f"{_number(connector['power_kw'])} kW · {money(connector['price_per_kwh'])}/kWh",size=14,color=theme.TEXT_COLOR),
                           ft.Text(f"Tempo máximo: {connector['max_duration_minutes']} min",size=12,color=theme.GRAY_TEXT)]
                if intention:
                    limits = intent_limits(connector,intention)
                    details.append(ft.Text(estimate_text(connector,**limits),size=12,color=theme.GRAY_TEXT))
                    if intention.get('mode') == 'time' and limits['minutes'] < intention['minutes']:
                        details.append(ft.Text(f"Estimativa limitada a {limits['minutes']} min, máximo deste ponto.",size=12,color=theme.GRAY_TEXT))
                    if intention.get('mode') == 'value' and 'max_cost' not in limits:
                        details.append(ft.Text('Tarifa gratuita: o plano usa um limite de tempo de 30 min, ajustado ao ponto.',size=12,color=theme.GRAY_TEXT))
                if connector.get('availability_status') == 'reconciling' and connector.get('reserved_until'):
                    details.append(ft.Text('O equipamento está restaurando uma reserva. Aguarde a confirmação.',size=12,color=theme.GRAY_TEXT))
                if _available(station,connector):
                    details += [ft.Divider(color=theme.LIGHT_GRAY),
                                button('Já estou aqui: iniciar',app.link('charging',public_code=connector['public_code'],max_duration=min(30,connector['max_duration_minutes']),point_context=point_context(station,connector),**({'planning_intent':intention} if intention else {}),**({'station_search':deepcopy(route_state)} if route_state else {}))),
                                button('Reservar para chegar',app.action(reserve),secondary=True),
                                ft.Text('A reserva precisa ser confirmada pelo equipamento antes de você se deslocar.',size=12,color=theme.GRAY_TEXT)]
                elif status == 'Offline':
                    details.append(ft.Text('Equipamento sem comunicação no momento.',size=12,color=theme.GRAY_TEXT))
                items.append(card(ft.Column(details,spacing=10,horizontal_alignment=ft.CrossAxisAlignment.STRETCH),padding=16))
        return items
    listing.controls = station_cards(stations)
    empty_state = ft.Text(
        'Nenhum posto nesta página. Volte para a página anterior.' if offset and total
        else 'Nenhum posto encontrado para esta busca.', visible=not listing.controls and not station_id,
        color=theme.GRAY_TEXT)
    pagination = ft.Column(spacing=10)

    def refresh_pagination():
        pagination.controls = []
        shown = len(current_stations)
        result_count.value = (f"{shown} {'posto' if shown == 1 else 'postos'} nesta página · "
                              f"{total} {'encontrado' if total == 1 else 'encontrados'}")
        if station_id:
            return
        if offset:
            pagination.controls.append(button('Anterior',app.link('stations',**route_state,offset=max(0,offset-20)),secondary=True))
        if offset+20 < total:
            pagination.controls.append(button('Mais postos',app.link('stations',**route_state,offset=offset+20)))

    current_stations = stations
    refresh_pagination()
    body = ft.Column(spacing=16,horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    def layout_list():
        searching = bool(typed['text'].strip())
        shown_items = typed_matches(current_stations)
        list_heading.value = 'Resultados Encontrados' if searching else 'Perto de Você'
        page_head_box.visible = not searching
        empty_state.visible = not shown_items
        if searching and not shown_items:
            empty_state.value = 'Nenhum posto com esse nome. Toque em buscar no teclado para procurar este endereço.'
        elif not shown_items:
            empty_state.value = ('Nenhum posto nesta página. Volte para a página anterior.'
                                 if offset and total else 'Nenhum posto encontrado para esta busca.')
        head = [*([active_box] if active_box.visible and not searching else []),page_head_box,
                ft.Container(search_field,margin=ft.Margin(left=0,top=5 if searching else -1,right=0,bottom=0))]
        if location_chip is not None:
            head.append(ft.Container(location_chip,margin=ft.Margin(left=0,top=-6,right=0,bottom=0)))
        top = [] if searching else [map_section,ft.Container(height=4)]
        bottom = [map_section] if searching and shown_items else []
        # Contagem e paginação ficam abaixo da dobra: o primeiro ecrã segue a referência.
        rows = len(shown_items)
        used = (95 + 24 + 63 + (16 + 158 if shown_items else 0) + 40 + rows * 101
                + (44 if location_chip is not None else 0)
                + (110 * len(active_box.controls) if active_box.visible and not searching else 0))
        fold = ft.Container(height=max(0,800 - used))
        body.controls = [*head,*top,ft.Container(list_heading,margin=ft.Margin(left=0,top=-2 if searching else 0,right=0,bottom=0)),
                         listing,empty_state,*bottom,fold,result_count,pagination]

    async def typing(event):
        typed['text'] = search_box.value or ''
        await refresh_map(current_stations)
        listing.controls = station_cards(current_stations)
        layout_list()
        app.page.update()

    async def submit_search():
        text = (search_box.value or '').strip()
        if not text or typed_matches(current_stations):
            return
        found_lat,found_lng = await _locate(demo,text)
        try:
            reach = float(radius)
        except (TypeError,ValueError):
            reach = DEFAULTS['radius']
        if not 0 < reach <= 500:  # also rejects NaN
            reach = DEFAULTS['radius']
        await app.go('stations',lat=found_lat,lng=found_lng,radius=reach,query=text,**filter_state)

    if not station_id:
        search_box.on_change = typing
        search_box.on_submit = app.action(submit_search)
        layout_list()
        controls = [body]
        if filters_open and hasattr(app.page,'show_dialog'):
            open_filters()

    async def update():
        nonlocal current_stations,total
        # Só acompanha o cartão enquanto ele existe (some quando a reserva/recarga termina);
        # uma reserva nova chega pelo próprio fluxo de reserva, que reconstrói a tela.
        if show_active and active_box.visible and await refresh_active():
            layout_list()
            app.page.update()
        if station_id:
            fresh = [deepcopy(await app.api.request("GET",f"stations/{station_id}"))]
            fresh_total = 1
        else:
            result = await app.api.request("GET","stations",params=params)
            fresh, fresh_total = deepcopy(result['items']),result['total']
        if fresh == current_stations and total == fresh_total:
            return
        current_stations,total = fresh,fresh_total
        if fresh != stations_seen[0]:
            stations_seen[0] = fresh
            await refresh_map(fresh)
            listing.controls = station_cards(fresh)
            if station_id and fresh:
                station_heading.controls[0].value = fresh[0]['name']
                station_heading.controls[1].value = fresh[0]['address']
        if station_id:
            empty_state.visible = not fresh
        else:
            layout_list()
        refresh_pagination()
        app.page.update()
    stations_seen = [stations]
    # Detalhe e cartão de recarga ativa: a cada 10 s; só a lista de busca: a cada 15 s.
    app.set_poll(update,10 if station_id or (show_active and active_box.visible) else 15)
    if station_id:
        controls += [empty_state]
    column = ft.Column(controls,scroll=ft.ScrollMode.AUTO,spacing=15 if not station_id else 14,horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    if station_id:
        # The reference detail frame uses a slightly wider side margin (25 pt).
        # The map is 357 pt wide (5 pt wider on the right); everything else keeps the 25/25 pt margins.
        column.controls = [item if item is map_section else ft.Container(item,margin=ft.Margin(left=0,top=0,right=5,bottom=0))
                           for item in column.controls]
        return ft.Column([ft.Container(column,padding=ft.Padding(left=5,right=0,top=0,bottom=0),expand=True)],expand=True)
    return column
