import math
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
from ..services.search_location import SearchLocation
from ..ui import design as D
from ..ui import theme
from ..ui.ai_features import ai_search_card, ai_supported
from ..ui.availability import point_status, station_map_record
from ..ui.components import badge, button, card, field, money, pill
from ..ui.deferred import fill_when_ready, skeleton
from ..ui.point_summary import point_context

CONNECTOR_LABELS = {'type2':'Tipo 2','ccs2':'CCS2','chademo':'CHAdeMO','bench':'Bancada'}


def _available(station, point):
    return (station.get('active') is not False and point.get('active') is not False
            and not point.get('retired') and point.get('online') is not False
            and point.get('available') is True
            and point.get('availability_status') in (None, 'available'))


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
            sub = f"{free} de {total} {'conector livre' if free == 1 else 'conectores livres'}"
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


async def build(app, lat=None, lng=None, radius=5, query='', station_id=None, offset=0,
                connector_type=None, available_only=False, max_price_per_kwh=None, sort='default', planning_intent=None):
    intention = deepcopy(planning_intent) if planning_intent else {}
    route_state = dict(lat=lat,lng=lng,radius=radius,query=query,connector_type=connector_type,
                       available_only=available_only,max_price_per_kwh=max_price_per_kwh,sort=sort,planning_intent=intention)
    defaults = dict(lat=None,lng=None,radius=5,query='',connector_type=None,available_only=False,
                    max_price_per_kwh=None,sort='default',planning_intent={})
    route_state = {key:value for key,value in route_state.items() if value != defaults[key]}
    demo = getattr(app.api,'is_demo',False) is True
    if station_id:
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
        result = await app.api.request('GET','stations',params=params)
        stations, total = deepcopy(result['items']), result['total']
    connector_filter = ft.Dropdown(label='Conector',value=connector_type or '',
        options=[ft.DropdownOption(key=k,text=v) for k,v in [('', 'Todos'),*CONNECTOR_LABELS.items()]],
        color=theme.TEXT_COLOR,bgcolor=theme.WHITE)
    available_filter = ft.Checkbox(label='Somente pontos disponíveis',value=available_only)
    price_filter = field('Tarifa máxima (R$/kWh)',str(max_price_per_kwh) if max_price_per_kwh is not None else '')
    price_filter.keyboard_type = ft.KeyboardType.NUMBER
    order_filter = ft.Dropdown(label='Ordenar por',value=sort,
        options=[ft.DropdownOption(key=k,text=v) for k,v in [('default','Padrão'),('price','Menor tarifa'),('distance','Mais perto da busca')]],
        color=theme.TEXT_COLOR,bgcolor=theme.WHITE)
    plan_mode = ft.Dropdown(label='Minha intenção',value=intention.get('mode','none'),
        options=[ft.DropdownOption(key=k,text=v) for k,v in [('none','Só comparar pontos'),('time','Tenho alguns minutos'),('value','Até um valor em reais')]],
        color=theme.TEXT_COLOR,bgcolor=theme.WHITE)
    plan_value = field('Minutos ou valor em R$',str(intention.get('minutes',intention.get('max_cost',''))))
    plan_value.keyboard_type = ft.KeyboardType.NUMBER
    active_plan_mode = plan_mode.value
    plan_value.visible = active_plan_mode != 'none'
    if active_plan_mode == 'time':
        plan_value.label = 'Tempo disponível (min)'
    elif active_plan_mode == 'value':
        plan_value.label = 'Orçamento máximo (R$)'

    async def change_plan_mode(event):
        nonlocal active_plan_mode
        if plan_mode.value != active_plan_mode:
            # A number entered as minutes must not silently become a money limit.
            plan_value.value = ''
        active_plan_mode = plan_mode.value
        plan_value.visible = active_plan_mode != 'none'
        plan_value.label = ('Tempo disponível (min)' if active_plan_mode == 'time'
                            else 'Orçamento máximo (R$)' if active_plan_mode == 'value'
                            else 'Minutos ou valor em R$')
        app.page.update()

    plan_mode.on_select = change_plan_mode

    def filter_values():
        maximum = None
        try:
            if price_filter.value.strip():
                maximum = Decimal(price_filter.value.strip().replace(',','.'))
                if not maximum.is_finite() or not 0 <= maximum <= 10000:
                    raise InvalidOperation
        except (InvalidOperation,ValueError):
            raise ApiError('Informe uma tarifa máxima de zero a R$ 10.000 por kWh.')
        intent = {}
        if plan_mode.value != 'none':
            try:
                amount = Decimal(plan_value.value.strip().replace(',','.'))
                ceiling = 1440 if plan_mode.value == 'time' else 100000
                if not amount.is_finite() or not 0 < amount <= ceiling or (plan_mode.value == 'time' and amount != amount.to_integral_value()):
                    raise InvalidOperation
                intent = {'mode':'time','minutes':int(amount)} if plan_mode.value == 'time' else {'mode':'value','max_cost':format(amount,'f')}
            except (InvalidOperation,ValueError):
                raise ApiError('Informe minutos inteiros de 1 a 1.440 ou um valor maior que zero e de até R$ 100.000.')
        return dict(connector_type=connector_filter.value or None,available_only=bool(available_filter.value),
                    max_price_per_kwh=format(maximum,'f') if maximum is not None else None,
                    sort=order_filter.value,planning_intent=intent)

    address = field('Endereço para buscar',query)
    address.max_length = 300
    latitude, longitude, reach = field('Latitude',str(lat) if lat is not None else ''),field('Longitude',str(lng) if lng is not None else ''),field('Raio (km)',f'{float(radius):g}'.replace('.',',') if isinstance(radius,(int,float)) else str(radius))
    search_mode = ft.Dropdown(label='Buscar por',value='address' if query or lat is None else 'coordinates',
                              options=[ft.DropdownOption(key='address',text='Endereço'),ft.DropdownOption(key='coordinates',text='Coordenadas')],
                              color=theme.TEXT_COLOR,bgcolor=theme.WHITE)

    async def search_values():
        search_lat, search_lng = None, None
        search_query = address.value.strip() if search_mode.value == 'address' else ''
        if search_query:
            if demo:
                from ..demo import DEMO_LOCATIONS
                from ..services.driver_demo import DEMO_DRIVER_NETWORK
                coordinates = geocode_demo_address(search_query,(*DEMO_LOCATIONS,*DEMO_DRIVER_NETWORK))
                if not coordinates:
                    raise ApiError('Na conta demo, busque um local de exemplo (Praça da Sé, Av. Paulista, Congonhas, '
                                   'Vila Madalena) ou selecione Coordenadas. A busca não acessa a internet.')
            else:
                try:
                    coordinates = await geocode_address(search_query)
                except Exception as exc:
                    raise ApiError('Não foi possível localizar o endereço. Selecione Coordenadas em Buscar por ou tente novamente.') from exc
            if not coordinates:
                raise ApiError('Endereço não encontrado. Selecione Coordenadas em Buscar por para informar latitude e longitude.')
            search_lat,search_lng = coordinates
        elif search_mode.value == 'coordinates':
            if not latitude.value.strip() or not longitude.value.strip():
                raise ApiError('Informe latitude e longitude juntas.')
            try:
                search_lat,search_lng = float(latitude.value.replace(',','.')),float(longitude.value.replace(',','.'))
            except ValueError as exc:
                raise ApiError('Informe números válidos para latitude e longitude.') from exc
        if search_lat is not None and (not -90 <= search_lat <= 90 or not -180 <= search_lng <= 180):
            raise ApiError('Informe latitude de -90 a 90 e longitude de -180 a 180.')
        try:
            search_radius = float(reach.value.replace(',','.'))
        except ValueError as exc:
            raise ApiError('Informe um raio numérico maior que zero e de até 500 km.') from exc
        if not math.isfinite(search_radius) or not 0 < search_radius <= 500:
            raise ApiError('Informe um raio maior que zero e de até 500 km.')
        return {'lat':search_lat,'lng':search_lng,'radius':search_radius,'query':search_query}

    async def search():
        location = await search_values()
        filters = filter_values()
        if filters['sort'] == 'distance' and location['lat'] is None:
            raise ApiError('Informe um endereço ou coordenadas para ordenar por proximidade.')
        await app.go('stations',**location,**{key:value for key,value in filters.items() if value != defaults[key]})

    latitude.expand = True
    longitude.expand = True
    coordinates = ft.Row([latitude,longitude],visible=search_mode.value == 'coordinates')
    address.visible = search_mode.value == 'address'

    async def change_search_mode(event):
        address.visible = search_mode.value == 'address'
        coordinates.visible = not address.visible
        app.page.update()

    search_mode.on_select = change_search_mode
    profile = getattr(app,'profile',{}) or {}
    user = getattr(getattr(app.api,'session',None),'user',None) or {}
    saved_location = None if demo else SearchLocation(profile.get('id') or user.get('id'))
    saved = saved_location.load() if saved_location else None
    saved_box = ft.Column(spacing=8)

    async def remove_saved():
        nonlocal saved
        if not saved_location.remove():
            raise ApiError('Não foi possível remover a busca deste dispositivo. Tente novamente.')
        saved = None
        refresh_saved()
        app.page.update()
        app.notice('Busca salva removida deste dispositivo.')

    def refresh_saved():
        saved_box.controls = []
        if saved:
            label = saved['query'] or f"{saved['lat']:.4f}, {saved['lng']:.4f}"
            saved_box.controls = [ft.Text('Busca salva nesta conta: '+label,size=12,color=theme.GRAY_TEXT),
                                  button('Usar busca salva',app.link('stations',**{**route_state,**saved}),secondary=True),
                                  button('Remover busca salva',app.action(remove_saved),secondary=True)]

    async def save_search():
        nonlocal saved
        data = await search_values()
        if data['lat'] is None:
            raise ApiError('Informe um endereço ou coordenadas antes de salvar esta busca.')
        if not saved_location.save(data):
            raise ApiError('Não foi possível salvar a busca nesta conta e dispositivo.')
        saved = data
        refresh_saved()
        app.page.update()
        app.notice('Busca salva somente para esta conta neste dispositivo.')

    refresh_saved()
    if station_id:
        first = stations[0]
        station_heading = ft.Column([D.txt(first['name'],25,'bold'),D.txt(first['address'],13.5,'regular',theme.GRAY_TEXT)],spacing=8)
        amenities = [amenity for amenity in first.get('amenities') or [] if isinstance(amenity,dict)]
        amenity_row = [ft.Row([pill(amenity_label(amenity)) for amenity in amenities],wrap=True,spacing=6,run_spacing=6)] if amenities else []
        group_rows = [D.list_row(group_title,group_sub,chevron=False,tile=40)
                      for group_title,group_sub in _connector_groups(first)]
        route_row = ft.Container(ft.Row([ft.Icon(ft.Icons.ALT_ROUTE,size=20,color=theme.TEXT_COLOR),
                                         D.txt('Abrir rota no Google Maps',14,'semibold',expand=True),
                                         ft.Icon(ft.Icons.OPEN_IN_NEW,size=20,color=theme.GRAY_TEXT)],
                                        spacing=12,vertical_alignment=ft.CrossAxisAlignment.CENTER),
                                 bgcolor=theme.CARD,border_radius=D.RADIUS_BTN,height=43,
                                 padding=ft.Padding(left=17,right=14,top=0,bottom=0),url=_map_url(first),ink=True)
        controls = [D.txt('Detalhes da estação',19,'bold'),
                    ft.Container(height=0),
                    ft.Container(station_heading,padding=ft.Padding(left=0,right=0,top=22,bottom=10)),
                    D.section_label('Conectores'),*group_rows,
                    ft.Container(height=14),route_row,
                    D.primary_button('Reservar estação',app.link('booking',station_id=station_id,step=1),height=55,size=16),
                    *amenity_row,
                    card(ft.Row([
                        ft.Icon(ft.Icons.LOCATION_ON_OUTLINED,color=theme.RED,size=23),
                        ft.Text('Para iniciar, você precisa estar no ponto. Leia o código #F atual na tela do equipamento; ele muda periodicamente.',
                                size=13,color=theme.TEXT_COLOR,expand=True),
                    ],spacing=12),padding=14),
                    ft.Text('Pontos de recarga',size=20,weight=ft.FontWeight.BOLD,color=theme.TEXT_COLOR,font_family='BarlowCondensedBold')]
        # The reference puts the map right under the title.
        map_slot_index = 2
    else:
        search_controls = [search_mode,address,coordinates,reach,button('Buscar',app.action(search)),
                           ft.Text('Sem endereço, mostramos todos os postos. O raio é aplicado à localização informada.',size=12,color=theme.GRAY_TEXT)]
        if saved_location is not None and saved_location.path is not None:
            search_controls += [button('Salvar busca neste dispositivo',app.action(save_search),secondary=True),
                                ft.Text('Salvamos a localização somente ao tocar em Salvar. Você pode removê-la aqui.',size=12,color=theme.GRAY_TEXT),saved_box]
        search_section = ft.ExpansionTile(
            expanded_cross_axis_alignment=ft.CrossAxisAlignment.STRETCH,
            title=ft.Text('Buscar perto de um endereço',size=15,color=theme.TEXT_COLOR),
            leading=ft.Icons.SEARCH,
            controls=[card(ft.Column(search_controls,spacing=12,horizontal_alignment=ft.CrossAxisAlignment.STRETCH))],
            expanded=bool(query.strip() or lat is not None or lng is not None),
            maintain_state=True,
            min_tile_height=44,
            tile_padding=ft.Padding(left=0,right=0,top=0,bottom=0),
            controls_padding=0,
            icon_color=theme.RED,
            collapsed_icon_color=theme.GRAY_TEXT,
        )
        filters_section = ft.ExpansionTile(
            expanded_cross_axis_alignment=ft.CrossAxisAlignment.STRETCH,
            title=ft.Text('Comparar por conector, preço e tempo',size=15,color=theme.TEXT_COLOR),
            expanded=False,
            maintain_state=True,
            controls=[card(ft.Column([ft.Semantics(label='Conector',content=connector_filter),available_filter,price_filter,ft.Semantics(label='Ordenar por',content=order_filter),
                ft.Semantics(label='Minha intenção',content=plan_mode),plan_value,ft.Text('Estimativas pela potência nominal, antes de cupons. O ponto pode entregar menos potência. Nenhuma cobrança real.',size=12,color=theme.GRAY_TEXT),
                button('Aplicar comparação',app.action(search))],spacing=12,horizontal_alignment=ft.CrossAxisAlignment.STRETCH))])
        summary = []
        if connector_type:
            summary.append(CONNECTOR_LABELS.get(connector_type, connector_type))
        if available_only:
            summary.append('disponíveis')
        if max_price_per_kwh is not None:
            summary.append(f'até {money(max_price_per_kwh)}/kWh')
        if sort != 'default':
            summary.append('menor tarifa' if sort == 'price' else 'proximidade da busca')
        if intention:
            summary.append(f"tenho {intention['minutes']} min" if intention['mode'] == 'time' else f"até {money(intention['max_cost'])}")
        extras = [ai_search_card(app,lat=lat,lng=lng)] if ai_supported(app) else []
        extras += [filters_section,search_section]
        if summary:
            extras.append(ft.Text('Comparação: '+ ' · '.join(summary)+'. Abra Comparar para editar.',size=13,color=theme.TEXT_COLOR))
        controls = []
    typed = {'text':''}
    map_preview = ft.Container(visible=False)
    map_signature = None
    map_section = ft.Column(controls=[map_preview],visible=False,spacing=0,horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    map_width = max(200,min(getattr(app.page,'width',None) or 400,600)-(40 if not station_id else 50))
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

    async def refresh_map(items, initial=False):
        nonlocal map_signature
        items = typed_matches(items) if not station_id else items
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
        signature = [{key:record.get(key) for key in ('id','name','latitude','longitude','free_points','status','price','distance_km')}
                     for record in records]
        if signature == map_signature:
            return
        if items:
            def draw():
                return station_map_widget(records,lambda selected_id:app.link('stations',station_id=selected_id,**route_state),
                                          offline=demo,width=map_width,variant='detail' if station_id else 'list',
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
    listing = ft.Column(spacing=12 if not station_id else 10,horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    if station_id:
        controls.insert(map_slot_index,map_section)
        controls.append(listing)
    list_heading = D.txt('Perto de Você',15,'bold')
    page_head = D.txt('Encontre uma estação',15,'bold')
    search_box = ft.TextField(
        hint_text='Buscar por endereço ou estação', hint_style=ft.TextStyle(size=11,color=theme.GRAY_TEXT,font_family=D.FONT),
        text_style=ft.TextStyle(size=11,color=theme.INPUT_TEXT,font_family=D.FONT), border=ft.NoInputBorder(),
        cursor_color=theme.INPUT_TEXT, content_padding=ft.Padding(left=0,right=12,top=0,bottom=0), expand=True,
        text_size=11, capitalization=ft.TextCapitalization.WORDS)
    search_field = ft.Container(ft.Row([ft.Icon(ft.Icons.SEARCH,size=22,color=theme.GRAY_TEXT),search_box],spacing=12,
                                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
                                bgcolor=theme.INPUT_BG,border_radius=12,height=47,padding=ft.Padding(left=16,right=0,top=0,bottom=0))
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
                items.append(D.list_row(station['name'],subtitle,trailing=right,
                                        on_click=app.link('stations',station_id=station['id'],**route_state)))
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
                    await app.go('reservations')
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
            items.append(ft.TextButton(content=ft.Text('Ver cupons deste posto',color=theme.GRAY_TEXT),on_click=app.link('coupons',station_id=station['id'])))
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
        page_head.visible = not searching
        empty_state.visible = not shown_items
        if searching and not shown_items:
            empty_state.value = 'Nenhum posto com esse nome. Toque em buscar no teclado para procurar este endereço.'
        elif not shown_items:
            empty_state.value = ('Nenhum posto nesta página. Volte para a página anterior.'
                                 if offset and total else 'Nenhum posto encontrado para esta busca.')
        head = [page_head,search_field]
        top = [] if searching else [map_section,ft.Container(height=4)]
        bottom = [map_section] if searching and shown_items else []
        body.controls = [*head,*top,list_heading,listing,empty_state,*bottom,result_count,pagination,*extras]

    async def typing(event):
        typed['text'] = search_box.value or ''
        await refresh_map(current_stations)
        listing.controls = station_cards(current_stations)
        layout_list()
        app.page.update()

    async def submit_search(event):
        text = (search_box.value or '').strip()
        if not text or typed_matches(current_stations):
            return
        search_mode.value = 'address'
        address.value = text
        await search()

    if not station_id:
        search_box.on_change = typing
        search_box.on_submit = app.action(submit_search)
        layout_list()
        controls = [body]

    async def update():
        nonlocal current_stations,total
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
    app.set_poll(update,10)
    if station_id:
        controls += [empty_state]
    column = ft.Column(controls,scroll=ft.ScrollMode.AUTO,spacing=15 if not station_id else 14,horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    if station_id:
        # The reference detail frame uses a slightly wider side margin (25 pt).
        return ft.Column([ft.Container(column,padding=ft.Padding(left=5,right=5,top=0,bottom=0),expand=True)],expand=True)
    return column
